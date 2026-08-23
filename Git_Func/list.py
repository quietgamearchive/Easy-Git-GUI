import tkinter as tk
from tkinter import ttk, messagebox


class GitListMixin:

    # ========================================================
    # Double-click commit
    # ========================================================

    def show_selected_commit(self, event=None):
        if self.busy:
            return

        if getattr(self, "_commit_window_opening", False):
            return

        selection = self.timeline.selection()

        if not selection:
            return

        values = self.timeline.item(selection[0], "values")

        if not values:
            return

        commit_hash = str(values[0]).strip()

        if not commit_hash:
            return

        self._commit_window_opening = True

        self.log("")
        self.log(f"Opening commit {commit_hash}")

        def worker():
            code, output = self.run_git([
                "log", "-1",
                "--date=format-local:%Y-%m-%d %H:%M:%S",
                "--pretty=format:%h|%an|%ad|%s",
                "--name-status",
                commit_hash
            ])

            if code != 0:
                return code, output, None

            # The full comment/meta (log + branch --contains) also
            # runs off the main thread: opening the window must not
            # block the UI for two subprocesses.
            detail = self.get_commit_detail(commit_hash)
            return code, output, detail

        def done(result):
            try:
                code, output, detail = result

                if code != 0:
                    messagebox.showerror(
                        "Commit",
                        f"Failed to read commit:\n\n{commit_hash}",
                        parent=self.root
                    )
                    return

                self.show_commit_window(commit_hash, output, detail)
            finally:
                self._commit_window_opening = False

        def on_error(error):
            # Reset the re-entry guard: without this, a failed read
            # would block double-clicking forever.
            self._commit_window_opening = False

            messagebox.showerror(
                "Commit",
                f"Failed to read commit:\n\n{error}",
                parent=self.root
            )

        self._diff_worker(worker, done, on_error=on_error)

    # ========================================================
    # Commit detail window
    # ========================================================

    def show_commit_window(self, commit_hash, output, detail=None):
        window = tk.Toplevel(self.root)

        window.withdraw()
        window.title(f"Commit {commit_hash}")
        window.transient(self.root)
        window.geometry("1000x650")
        window.minsize(800, 500)

        frame = ttk.Frame(window)
        frame.pack(fill="both", expand=True, padx=12, pady=12)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(1, weight=1)

        # Parse the "git log --name-status" output: the first line
        # is the header (hash|user|date|subject), the following
        # lines are "STATUS\tpath" entries.  Renames/copies report
        # "STATUS\told\tnew" and are shown as "old -> new"; the
        # tree item id stays the destination path so the diff works.
        header = ""
        files = []

        for line in output.splitlines():
            stripped = line.strip()

            if not stripped:
                continue

            if not header and "|" in stripped:
                header = stripped
                continue

            parts = stripped.split("\t")

            if len(parts) == 2:
                status_code = parts[0].strip()
                display_path = parts[1].strip()
                item_path = display_path
            elif len(parts) == 3:
                status_code = parts[0].strip()
                display_path = f"{parts[1].strip()} -> {parts[2].strip()}"
                item_path = parts[2].strip()
            else:
                continue

            if status_code.startswith("A"):
                status = "ADDED"
            elif status_code.startswith("D"):
                status = "DELETED"
            elif status_code.startswith("R"):
                status = "RENAMED"
            elif status_code.startswith("C"):
                status = "ADDED"
            else:
                status = "EDITED"

            files.append((status, display_path, item_path))

        # Header as a read-only, word-wrapping text box so long
        # commit comments stay readable.
        #
        # The comment comes from git itself (--format=%B): the
        # subject line is truncated in the list, the database
        # view keeps the full multi-line message.
        if detail is None:
            detail = self.get_commit_detail(commit_hash)

        if detail:
            header_display = detail["comment"]

            meta = detail["date"]

            if detail["user"]:
                meta += f" | user: {detail['user']}"

            if detail["tags"]:
                meta += f" | tags: {', '.join(detail['tags'])}"

            header_display += "\n\n" + meta
        else:
            header_display = header

        header_text = tk.Text(
            frame,
            font=("Segoe UI", 9),
            wrap="word",
            height=5,
            relief="flat"
        )
        header_text.configure(state="normal")
        header_text.insert("1.0", header_display)
        header_text.configure(state="disabled")

        header_scroll = ttk.Scrollbar(frame, orient="vertical", command=header_text.yview)
        header_text.configure(yscrollcommand=header_scroll.set)

        header_text.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        header_scroll.grid(row=0, column=1, sticky="ns", pady=(0, 8))

        # Split pane: changed files on the left, file diff on the right.
        paned = ttk.Panedwindow(frame, orient="horizontal")
        paned.grid(row=1, column=0, sticky="nsew")

        list_frame = ttk.Frame(paned)
        diff_frame = ttk.Frame(paned)
        paned.add(list_frame, weight=1)
        paned.add(diff_frame, weight=2)

        file_tree = ttk.Treeview(
            list_frame,
            columns=("status", "file"),
            show="headings",
            selectmode="browse"
        )
        file_tree.heading("status", text="Status")
        file_tree.heading("file", text="File")
        file_tree.column("status", width=80, minwidth=70, stretch=False)
        file_tree.column("file", width=220, minwidth=120)

        tree_scroll = ttk.Scrollbar(list_frame, orient="vertical", command=file_tree.yview)
        file_tree.configure(yscrollcommand=tree_scroll.set)
        file_tree.grid(row=0, column=0, sticky="nsew")
        tree_scroll.grid(row=0, column=1, sticky="ns")
        list_frame.rowconfigure(0, weight=1)
        list_frame.columnconfigure(0, weight=1)

        diff_text = tk.Text(
            diff_frame,
            font=("Consolas", 9),
            wrap="none",
            bg="white",
            fg="black",
            insertbackground="black",
            state="disabled"
        )
        diff_text.configure(state="normal")
        diff_text.insert("1.0", "(select a changed file to see its diff)")
        diff_text.configure(state="disabled")

        diff_scroll_y = ttk.Scrollbar(diff_frame, orient="vertical", command=diff_text.yview)
        diff_scroll_x = ttk.Scrollbar(diff_frame, orient="horizontal", command=diff_text.xview)
        diff_text.configure(yscrollcommand=diff_scroll_y.set, xscrollcommand=diff_scroll_x.set)
        diff_text.grid(row=0, column=0, sticky="nsew")
        diff_scroll_y.grid(row=0, column=1, sticky="ns")
        diff_scroll_x.grid(row=1, column=0, sticky="ew")
        diff_frame.rowconfigure(0, weight=1)
        diff_frame.columnconfigure(0, weight=1)

        def on_file_selected(event=None):
            selection = file_tree.selection()

            if selection:
                self.show_version_diff(diff_text, commit_hash, selection[0])

        file_tree.bind("<<TreeviewSelect>>", on_file_selected)

        for status, display_path, item_path in files:
            file_tree.insert("", "end", iid=item_path, values=(status, display_path))

        window.bind("<Escape>", lambda event: window.destroy())
        window.protocol("WM_DELETE_WINDOW", window.destroy)

        self.center_window(window, 1000, 650)
        self.disable_resize_maximize(window)
        window.deiconify()

        window.grab_set()
        window.focus_force()

        window.wait_window(window)

    # ========================================================
    # Diff of a file in a specific commit
    # ========================================================

    def show_version_diff(self, diff_text, commit_hash, path):
        # Request guard: when the user clicks through the list
        # quickly, only the newest request is allowed to render.
        self._diff_request_id = getattr(self, "_diff_request_id", 0) + 1
        request_id = self._diff_request_id

        diff_text.configure(state="normal")
        diff_text.delete("1.0", "end")
        diff_text.configure(state="disabled")

        def worker():
            # git show handles the root commit too (no parent),
            # so no separate parent lookup is needed.
            return self.run_git(["show", commit_hash, "--", self.safe_git_path(path)], log_output=False)

        def done(result):
            if self._diff_request_id != request_id:
                return  # superseded by a newer selection

            try:
                exists = diff_text.winfo_exists()
            except tk.TclError:
                return  # window was closed while git was running

            if not exists:
                return

            code, output = result
            diff_text.configure(state="normal")
            diff_text.delete("1.0", "end")

            if code != 0:
                diff_text.insert("1.0", "(git show failed)\n")
            elif not output.strip():
                diff_text.insert("1.0", "(no textual diff - binary file)\n")
            else:
                self.render_diff(diff_text, output)

            diff_text.configure(state="disabled")

        self._diff_worker(worker, done)

    # ========================================================
    # Timeline context menu
    # ========================================================

    def on_timeline_right_click(self, event):
        row_id = self.timeline.identify_row(event.y)

        if row_id:
            # Right-clicking a row that is already part of the
            # multi-selection keeps the selection; right-clicking
            # an unselected row switches the selection to it.
            if row_id not in self.timeline.selection():
                self.timeline.selection_set(row_id)
            self.timeline.focus(row_id)

        selection = self.timeline.selection()
        count = len(selection)

        # Switch and Modify are only available for a single
        # selection; Delete accepts a multi-selection.
        self.timeline_menu.entryconfigure(0, state="normal" if count == 1 else "disabled")
        self.timeline_menu.entryconfigure(1, state="normal" if count == 1 else "disabled")
        self.timeline_menu.entryconfigure(2, state="normal" if count >= 1 else "disabled")

        # Dynamically label the hide/show entry: "Show" when every
        # selected commit is already hidden, "Hide" otherwise.
        if selection:
            hidden_flags = []

            for item in selection:
                values = self.timeline.item(item, "values")

                if not values:
                    hidden_flags.append(False)
                    continue

                hidden_flags.append(self.is_commit_hidden(str(values[0]).strip()))

            all_hidden = all(hidden_flags)
            hide_show_label = "Show" if all_hidden else "Hide"
        else:
            hide_show_label = "Hide"

        self.timeline_menu.entryconfigure(4, label=hide_show_label)

        try:
            self.timeline_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.timeline_menu.grab_release()

    # ========================================================
    # Switch (detached HEAD)
    # ========================================================

    def timeline_switch(self):
        if self.busy:
            return

        selection = self.timeline.selection()

        if len(selection) != 1:
            return

        values = self.timeline.item(selection[0], "values")

        if not values:
            return

        commit_hash = str(values[0]).strip()
        comment = str(values[4]).strip()

        answer = messagebox.askyesno(
            "Switch",
            (
                "Switch to commit:\n\n"
                f"{commit_hash} - {comment}\n\n"
                "git switch --detach (detached HEAD state).\n\n"
                "Continue?"
            ),
            parent=self.root
        )

        if not answer:
            return

        self.run_background(
            lambda: self.perform_switch_detach(commit_hash),
            self.switch_detach_finished
        )

    def perform_switch_detach(self, commit_hash):
        self.log("")
        self.log(f"Switching to commit (detached): {commit_hash}")

        code, output = self.run_git(["switch", "--detach", commit_hash])

        if code != 0:
            raise RuntimeError("Failed to switch to commit (uncommitted changes?).")

        self.log("Switched to detached commit.")

    def switch_detach_finished(self):
        self.load_timeline()

    # ========================================================
    # Modify commit
    #
    # Rewrites the selected commit's message (and optionally
    # creates a tag on it) via a non-interactive interactive
    # rebase: a sequence-editor script flips the target's todo
    # line to "edit", git stops there, the message is amended,
    # and the rebase continues replaying the rest.
    # ========================================================

    def timeline_modify(self):
        selection = self.timeline.selection()

        if len(selection) != 1:
            return

        values = self.timeline.item(selection[0], "values")

        if not values:
            return

        commit_hash = str(values[0]).strip()
        comment = str(values[4]).strip()

        self.open_modify_commit_dialog(commit_hash, comment)

    def open_modify_commit_dialog(self, commit_hash, comment):
        if self.busy:
            return

        dialog = tk.Toplevel(self.root)

        dialog.withdraw()
        dialog.title("Modify Commit")
        dialog.transient(self.root)
        dialog.geometry("640x420")
        dialog.minsize(560, 360)

        dialog_frame = ttk.Frame(dialog)
        dialog_frame.pack(fill="both", expand=True, padx=12, pady=12)
        dialog_frame.columnconfigure(0, weight=1)
        dialog_frame.rowconfigure(2, weight=1)

        ttk.Label(
            dialog_frame,
            text=f"Commit: {commit_hash} - {comment}",
            wraplength=560
        ).grid(row=0, column=0, sticky="w", pady=(0, 10))

        ttk.Label(dialog_frame, text="New commit message:").grid(row=1, column=0, sticky="w", pady=(0, 5))

        message_text = tk.Text(dialog_frame, font=("Consolas", 10), wrap="word", undo=True, height=6)
        message_scroll = ttk.Scrollbar(dialog_frame, orient="vertical", command=message_text.yview)
        message_text.configure(yscrollcommand=message_scroll.set)
        message_text.grid(row=2, column=0, sticky="nsew", pady=(0, 8))
        message_scroll.grid(row=2, column=1, sticky="ns", pady=(0, 8))

        ttk.Label(dialog_frame, text="Tag (optional):").grid(row=3, column=0, sticky="w", pady=(0, 5))

        tag_var = tk.StringVar()
        ttk.Entry(dialog_frame, textvariable=tag_var, width=30).grid(row=4, column=0, sticky="w", pady=(0, 8))

        ttk.Label(
            dialog_frame,
            text="The commit must be on the current branch. Its hash changes "
                 "and later commits get new hashes too.",
            foreground="#808080",
            wraplength=560
        ).grid(row=5, column=0, sticky="w", pady=(0, 8))

        button_frame = ttk.Frame(dialog_frame)
        button_frame.grid(row=6, column=0, sticky="e")

        cancel_button = ttk.Button(button_frame, text="Cancel", command=dialog.destroy)
        cancel_button.pack(side="right", padx=(5, 0))

        ok_button = ttk.Button(
            button_frame,
            text="Modify",
            command=lambda: self.modify_from_dialog(dialog, commit_hash, message_text, tag_var)
        )
        ok_button.pack(side="right")

        # Pre-fill the box with the commit's current full message on
        # a background thread; the Modify button stays disabled until
        # the fill completes (or fails).
        ok_button.state(["disabled"])

        def fill_worker():
            return self.get_commit_comment(commit_hash)

        def fill_done(result):
            try:
                exists = dialog.winfo_exists()
            except tk.TclError:
                return

            if not exists:
                return

            if result:
                message_text.insert("1.0", result)

            ok_button.state(["!disabled"])

        def fill_error(error):
            try:
                exists = dialog.winfo_exists()
            except tk.TclError:
                return

            if not exists:
                return

            self.log(f"!!! Could not load the commit message: {error}")
            ok_button.state(["!disabled"])

        self._diff_worker(fill_worker, fill_done, on_error=fill_error)

        dialog.bind("<Escape>", lambda event: dialog.destroy())
        dialog.protocol("WM_DELETE_WINDOW", dialog.destroy)

        self.center_window(dialog, 640, 420)
        self.disable_resize_maximize(dialog)
        dialog.deiconify()

        # Make the dialog modal only AFTER it is mapped: a grab taken
        # while the window is withdrawn does not take effect on Windows.
        dialog.grab_set()
        dialog.focus_force()
        message_text.focus_set()

        dialog.wait_window(dialog)

    def modify_from_dialog(self, dialog, commit_hash, message_widget, tag_widget):
        message = message_widget.get("1.0", "end-1c").strip()
        tag = tag_widget.get().strip()

        if not message:
            messagebox.showwarning("Modify Commit", "Commit message cannot be empty.", parent=dialog)
            return

        dialog.destroy()

        self.run_background(
            lambda: self.perform_modify_commit(commit_hash, message, tag),
            self.modify_commit_finished
        )

    def perform_modify_commit(self, commit_hash, message, tag=""):
        import os
        import sys
        import tempfile

        self.log("")
        self.log(f"Modifying commit {commit_hash}...")

        if self.is_rebase_in_progress():
            raise RuntimeError("A rebase is already in progress.")

        # rebase refuses to start with a dirty working tree, but
        # untracked files (e.g. .kilo/) are harmless.  Check only
        # tracked-file changes (staged or unstaged).
        code, _ = self.run_git(["diff", "--quiet", "HEAD"], log_command=False, log_output=False)

        if code != 0:
            raise RuntimeError("The working tree has uncommitted changes (tracked files modified); commit or discard them first.")

        code, _ = self.run_git(["diff", "--cached", "--quiet"], log_command=False, log_output=False)

        if code != 0:
            raise RuntimeError("The working tree has staged changes; commit or discard them first.")

        code, output = self.run_git(["rev-parse", commit_hash], log_command=False, log_output=False)

        if code != 0:
            raise RuntimeError(f"Failed to resolve commit: {commit_hash}")

        full_hash = output.strip()

        # The commit must be reachable from HEAD, otherwise it never
        # appears in the rebase todo list and nothing happens.
        code, _ = self.run_git(
            ["merge-base", "--is-ancestor", full_hash, "HEAD"],
            log_command=False,
            log_output=False
        )

        if code != 0:
            raise RuntimeError("The commit is not on the current branch; switch to its branch first.")

        # rebase -i <parent> puts the target at the top of the todo
        # list.  The root commit has no parent and cannot be rebased.
        code, output = self.run_git(["rev-parse", full_hash + "^"], log_command=False, log_output=False)

        if code != 0:
            raise RuntimeError("The root commit cannot be modified (it has no parent).")

        parent = output.strip()

        # Snapshot the commits that the rebase will rewrite (old
        # hashes), so hidden-commit entries can be remapped after
        # the rewrite.  The rebase preserves count and order, so the
        # post-rebase rev-list pairs up by index.
        code, output = self.run_git(["rev-list", parent + "..HEAD"], log_command=False, log_output=False)

        if code != 0:
            raise RuntimeError("Failed to list commits for the rewrite.")

        old_commits = [line.strip() for line in output.splitlines() if line.strip()]

        # Sequence editor: a tiny script that flips the target's
        # todo line from "pick" to "edit".  The target hashes are
        # passed through environment variables, so no shell-quoting
        # of commit ids is involved.
        editor_code = (
            "import os\n"
            "import sys\n"
            "target = os.environ['GITGUI_TARGET']\n"
            "short = os.environ['GITGUI_SHORT']\n"
            "path = sys.argv[1]\n"
            "lines = open(path, encoding='utf-8').read().splitlines()\n"
            "out = []\n"
            "for line in lines:\n"
            "    words = line.split()\n"
            "    if words and words[0] == 'pick' and len(words) > 1 and \\\n"
            "            (words[1] == target or words[1].startswith(short)):\n"
            "        out.append('edit' + line[len('pick'):])\n"
            "    else:\n"
            "        out.append(line)\n"
            "open(path, 'w', encoding='utf-8').write('\\n'.join(out) + '\\n')\n"
        )

        rebase_started = False
        editor_path = ""

        try:
            fd, editor_path = tempfile.mkstemp(suffix=".py", prefix="gitgui_rebase_editor_")
            os.close(fd)

            with open(editor_path, "w", encoding="utf-8") as f:
                f.write(editor_code)

            # GIT_SEQUENCE_EDITOR goes through the shell, so both
            # paths are quoted (the temp path may contain spaces).
            editor_cmd = f'"{sys.executable}" "{editor_path}"'.replace("\\", "/")

            env = {
                "GIT_SEQUENCE_EDITOR": editor_cmd,
                "GITGUI_TARGET": full_hash,
                "GITGUI_SHORT": commit_hash,
            }

            self.log(f"Starting interactive rebase: {parent}")

            code, _ = self.run_git_with_env(["rebase", "-i", parent], env)

            if code != 0:
                raise RuntimeError("Failed to start the rebase.")

            rebase_started = True

            self.log("Amending commit message...")

            code, _ = self.run_git(["commit", "--amend", "-m", message])

            if code != 0:
                raise RuntimeError("Failed to amend the commit message.")

            if tag:
                self.log(f"Creating tag: {tag}")

                code, _ = self.run_git(["tag", tag])

                if code != 0:
                    raise RuntimeError("Failed to create tag.")

            self.log("Finishing the rebase...")

            # GIT_EDITOR=true: the remaining commits are replayed
            # unchanged, never opening an editor.
            code, _ = self.run_git_with_env(["rebase", "--continue"], {"GIT_EDITOR": "true"})

            if code != 0:
                raise RuntimeError("Failed to finish the rebase.")

            # Remap the hidden-commit list: the rewrite changed the
            # hashes of the modified commit and everything after it.
            code, output = self.run_git(["rev-list", parent + "..HEAD"], log_command=False, log_output=False)

            if code == 0:
                new_commits = [line.strip() for line in output.splitlines() if line.strip()]
                self.remap_hidden_commits_after_rebase(old_commits, new_commits)
            else:
                self.log("WARNING: could not list rewritten commits; hidden commit list cleared.")
                self.hidden_commits = set()
                self.save_hidden_commits()

            self.log("")
            self.log("Modify completed successfully.")
        except RuntimeError:
            if rebase_started:
                # Never leave the repository stuck mid-rebase: abort
                # restores the original history.
                self.log("")
                self.log("Aborting the rebase to restore the original history...")

                abort_code, _ = self.run_git(["rebase", "--abort"], log_command=False, log_output=False)

                if abort_code != 0:
                    abort_code, _ = self.run_git(["rebase", "--quit"], log_command=False, log_output=False)

                if abort_code == 0:
                    self.log("Rebase aborted; the repository is back to its original state.")
                else:
                    self.log("WARNING: could not abort the rebase automatically.")
                    self.log("Run 'git rebase --abort' manually to restore the repository.")
            raise
        finally:
            if editor_path:
                try:
                    os.remove(editor_path)
                except OSError:
                    pass

    def modify_commit_finished(self):
        self.load_timeline()

        messagebox.showinfo("Modify Commit", "Commit modified successfully.", parent=self.root)

    # ========================================================
    # Delete
    #
    # Removes the selected commit(s) from ALL history with
    # git-filter-repo.  Every later commit gets a new hash.
    # ========================================================

    def timeline_delete(self):
        if self.busy:
            return

        selection = self.timeline.selection()

        if not selection:
            return

        rows = []

        for item in selection:
            values = self.timeline.item(item, "values")

            if not values:
                continue

            commit_hash = str(values[0]).strip()
            comment = str(values[4]).strip()

            if commit_hash:
                rows.append((commit_hash, comment))

        if not rows:
            return

        count = len(rows)
        preview = "\n".join(f"{h} - {c}" for h, c in rows[:10])

        if count > 10:
            preview += f"\n... and {count - 10} more"

        answer = messagebox.askyesno(
            "Delete",
            (
                f"Permanently delete {count} commit(s) from ALL history?\n\n"
                f"{preview}\n\n"
                "The commits will be removed with git-filter-repo and the "
                "repository history will be rewritten: every later commit "
                "gets a new hash.\n\n"
                "GUARANTEE: files on disk are NEVER deleted - only the "
                "history is rewritten. Any working file removed during "
                "the operation is restored automatically.\n\n"
                "This REWRITES HISTORY and cannot be undone.\n\n"
                "The reflog will be expired and orphaned objects pruned, "
                "so the old history cannot be recovered via 'git reflog'.\n\n"
                "Continue?"
            ),
            parent=self.root
        )

        if not answer:
            return

        self.run_background(lambda: self.perform_delete_commits(rows), self.delete_commits_finished)

    def perform_delete_commits(self, rows):
        import os
        import sys
        import tempfile

        self.log("")
        self.log(f"Deleting {len(rows)} commit(s) from all history...")

        filter_repo = self.filter_repo_script

        if not filter_repo.exists():
            raise RuntimeError("git-filter-repo was not found next to this program.")

        # Snapshot the current tree: files the rewrite will remove
        # from disk (files that existed only inside the deleted
        # commits) are restored afterwards - delete never removes
        # working files, only history.
        code, output = self.run_git(["rev-parse", "HEAD"], log_command=False, log_output=False)

        if code != 0:
            raise RuntimeError("Failed to resolve the current HEAD.")

        old_head = output.strip()

        code, output = self.run_git(["ls-tree", "-r", "--name-only", "HEAD"], log_command=False, log_output=False)

        if code != 0:
            raise RuntimeError("Failed to list the current tree.")

        old_files = set(line for line in output.splitlines() if line.strip())
        present = {f for f in old_files if (self.project_dir / f).is_file()}

        # The timeline holds short hashes, but git-filter-repo matches
        # commit.original_id (the full 40-character hash), so every
        # target must be expanded first - otherwise the drop set never
        # matches and the delete silently does nothing.
        drop_set = set()

        for commit_hash, _ in rows:
            code, output = self.run_git(["rev-parse", commit_hash], log_command=False, log_output=False)

            if code != 0:
                raise RuntimeError(f"Failed to resolve commit: {commit_hash}")

            full_hash = output.strip()
            drop_set.add(full_hash)
            self.log(f"  {commit_hash} -> {full_hash}")

        # The callback body is written to a temp file (git-filter-repo
        # reads a file path for --commit-callback) and empties the
        # file_changes of every commit whose original id is in the
        # drop set.  filter-repo then prunes empty commits and
        # remaps their children to the parent, which is the correct
        # way to delete commits via callback (commit.skip() does not
        # set up proper remapping).
        callback_code = (
            "drop_set = %r\n"
            "oid = commit.original_id\n"
            "if isinstance(oid, bytes):\n"
            "    oid = oid.decode('ascii')\n"
            "if oid in drop_set:\n"
            "    commit.file_changes = []\n"
        ) % (sorted(drop_set),)

        fd, callback_path = tempfile.mkstemp(suffix=".py", prefix="gitgui_delete_")
        os.close(fd)

        try:
            with open(callback_path, "w", encoding="utf-8") as f:
                f.write(callback_code)

            # run_filter_repo stashes the working tree (untracked
            # files included) so git-filter-repo's cleanliness check
            # passes, and restores it afterwards.
            # "--no-gc" keeps the pre-rewrite objects alive until the
            # working files are restored below (filter-repo's own
            # cleanup would prune them immediately); the reflog
            # expire and git gc at the end of this method finish it.
            code, output = self.run_filter_repo([
                "--commit-callback", callback_path,
                "--force", "--no-gc"
            ])

            # Restore the working files FIRST, even on failure: the
            # rewrite's checkout may have removed them from disk.
            code2, output2 = self.run_git(["ls-tree", "-r", "--name-only", "HEAD"], log_command=False, log_output=False)

            new_files = set(line.strip() for line in output2.splitlines() if line.strip()) if code2 == 0 else set()

            vanished = sorted((old_files - new_files) & present)
            self.restore_working_files_from(old_head, vanished)

            if code != 0:
                raise RuntimeError("git-filter-repo failed.")
        finally:
            try:
                os.remove(callback_path)
            except OSError:
                pass

        # Drop the reflog entries and prune the orphaned objects.
        self.log("Cleaning up orphaned objects...")

        code, _ = self.run_git(["reflog", "expire", "--expire=now", "--all"])

        if code != 0:
            self.log("WARNING: reflog expire failed.")

        code, _ = self.run_git(["gc", "--prune=now", "--quiet"])

        if code != 0:
            raise RuntimeError("Git gc failed.")

        # The rewrite changed every surviving hash: remap the
        # hidden-commit list via filter-repo's commit-map.
        self.log("Remapping hidden commit list...")
        self.remap_hidden_commits_after_filter_repo()

        self.log("")
        self.log("Delete completed successfully.")

    def delete_commits_finished(self):
        self.load_timeline()

        messagebox.showinfo(
            "Delete",
            (
                "Selected commit(s) removed from all history.\n\n"
                "Repository history rewritten and orphaned objects pruned."
            ),
            parent=self.root
        )

    # ========================================================
    # Hide / Show commits
    # ========================================================

    def timeline_hide_show(self):
        if self.busy:
            return

        selection = self.timeline.selection()

        if not selection:
            return

        rows = []

        for item in selection:
            values = self.timeline.item(item, "values")

            if not values or len(values) < 5:
                continue

            short_hash = str(values[0]).strip()

            if not short_hash:
                continue

            # Store the FULL hash: the timeline only displays a
            # short abbreviation, which is only guaranteed unique
            # among the objects present at display time.  A stored
            # abbreviation could later match a different commit
            # (new objects, history rewrites) and hide it by
            # mistake, so the stored list never holds abbreviations.
            full_hash = short_hash

            if len(short_hash) < 40:
                code, output = self.run_git(["rev-parse", short_hash], log_command=False, log_output=False)

                if code != 0 or not output.strip():
                    self.log(f"WARNING: could not resolve commit {short_hash}; skipped.")
                    continue

                full_hash = output.strip()

            rows.append((full_hash, short_hash, str(values[4])))

        if not rows:
            return

        # The hidden-state check uses the displayed abbreviation
        # (short) so legacy entries stored as abbreviations still
        # match; the stored list itself holds full hashes only.
        all_hidden = all(self.is_commit_hidden(short) for _, short, _ in rows)

        if all_hidden:
            action = "Show"
            question = "Show the selected commit(s)?"
        else:
            action = "Hide"
            question = "Hide the selected commit(s)?"

        answer = messagebox.askyesno(action, question, parent=self.root)

        if not answer:
            return

        self.load_hidden_commits()

        if all_hidden:
            for full_hash, _, _ in rows:
                self._discard_hidden_abbrev(full_hash)
                self.hidden_commits.discard(full_hash)
        else:
            for full_hash, _, _ in rows:
                self._discard_hidden_abbrev(full_hash)
                self.hidden_commits.add(full_hash)

        self.save_hidden_commits()
        self.load_timeline()
