import tkinter as tk
from tkinter import ttk, messagebox


class GitCommitMixin:

    # ========================================================
    # Commit dialog
    # ========================================================

    def open_commit_dialog(self):
        if self.busy:
            return

        if not self.is_repository():
            messagebox.showerror("Commit", "Git repository was not found.", parent=self.root)
            return

        dialog = tk.Toplevel(self.root)

        dialog.withdraw()
        dialog.title("Commit")
        dialog.transient(self.root)
        dialog.geometry("1000x650")
        dialog.minsize(800, 500)

        dialog_frame = ttk.Frame(dialog)
        dialog_frame.pack(fill="both", expand=True, padx=12, pady=12)
        dialog_frame.columnconfigure(0, weight=1)
        dialog_frame.rowconfigure(4, weight=1)

        ttk.Label(dialog_frame, text="Commit message:").grid(row=0, column=0, sticky="w", pady=(0, 5))

        message_text = tk.Text(dialog_frame, font=("Consolas", 10), wrap="word", undo=True, height=4)
        message_scroll = ttk.Scrollbar(dialog_frame, orient="vertical", command=message_text.yview)
        message_text.configure(yscrollcommand=message_scroll.set)
        message_text.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        message_scroll.grid(row=1, column=1, sticky="ns", pady=(0, 8))

        # Tag (optional)
        ttk.Label(dialog_frame, text="Tag (optional):").grid(row=2, column=0, sticky="w", pady=(0, 5))

        tag_var = tk.StringVar()
        ttk.Entry(dialog_frame, textvariable=tag_var, width=30).grid(row=3, column=0, sticky="w", pady=(0, 8))

        # Split pane: changed files on the left, file diff on the right.
        paned = ttk.Panedwindow(dialog_frame, orient="horizontal")
        paned.grid(row=4, column=0, sticky="nsew")

        list_frame = ttk.Frame(paned)
        diff_frame = ttk.Frame(paned)
        paned.add(list_frame, weight=1)
        paned.add(diff_frame, weight=2)

        # Status hint: files tracked but missing on disk show up
        # as DELETED.  Committing removes them from version
        # control for good.
        ttk.Label(
            list_frame,
            text="DELETED = missing on disk; commit removes it from tracking",
            foreground="#808080"
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 4))

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
        file_tree.grid(row=1, column=0, sticky="nsew")
        tree_scroll.grid(row=1, column=1, sticky="ns")
        list_frame.rowconfigure(1, weight=1)
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
                self.show_file_diff(diff_text, selection[0])

        file_tree.bind("<<TreeviewSelect>>", on_file_selected)

        ttk.Label(dialog_frame, text=f"User: {self.git_user} <{self.git_email}>").grid(row=5, column=0, sticky="w", pady=(10, 8))

        button_frame = ttk.Frame(dialog_frame)
        button_frame.grid(row=6, column=0, sticky="e")

        cancel_button = ttk.Button(button_frame, text="Cancel", command=dialog.destroy)
        cancel_button.pack(side="right", padx=(5, 0))

        commit_button = ttk.Button(
            button_frame,
            text="Scanning...",
            state="disabled"
        )
        commit_button.configure(
            command=lambda: self.commit_from_dialog(
                dialog, message_text, tag_var, file_tree, commit_button
            )
        )
        commit_button.pack(side="right")

        dialog.bind("<Escape>", lambda event: dialog.destroy())
        dialog.protocol("WM_DELETE_WINDOW", dialog.destroy)
        message_text.focus_set()

        self.center_window(dialog, 1000, 650)
        self.disable_resize_maximize(dialog)
        dialog.deiconify()

        # Make the dialog modal only AFTER it is mapped: a grab taken
        # while the window is withdrawn does not take effect on Windows.
        dialog.grab_set()
        dialog.focus_force()

        # Load the changed-file list asynchronously, so the dialog
        # stays responsive while git scans the project tree.  The
        # Commit button stays disabled until the scan completes, so
        # the preview snapshot (_preview_paths, captured in
        # load_commit_changes) is always complete when committing.
        self.load_commit_changes(file_tree, commit_button)

        dialog.wait_window(dialog)

    # ========================================================
    # Commit from dialog
    # ========================================================

    def commit_from_dialog(self, dialog, message_widget, tag_widget, file_tree, commit_button):
        message = message_widget.get("1.0", "end-1c").strip()
        tag = tag_widget.get().strip()

        if not message:
            messagebox.showwarning("Commit", "Commit message cannot be empty.", parent=dialog)
            return

        # Disable button and show scanning state for the re-scan.
        commit_button.state(["disabled"])
        commit_button.configure(text="Scanning...")

        # Re-scan the working tree: files may have appeared or
        # changed while the dialog was open.  We refresh the
        # preview and compare against the original snapshot to
        # detect unpreviewed files before committing.
        def worker():
            return self.run_git(["status", "--porcelain"], log_output=False)

        def done(result):
            try:
                exists = dialog.winfo_exists()
            except tk.TclError:
                return

            if not exists:
                return

            code, output = result

            if code != 0:
                messagebox.showerror(
                    "Commit",
                    "Failed to scan the working tree.\n\n"
                    "The commit dialog will remain open.",
                    parent=dialog
                )
                commit_button.state(["!disabled"])
                commit_button.configure(text="Commit")
                return

            rows = self._parse_status_rows(output)
            new_paths = {path for _, path in rows}

            # Refresh the tree so the preview matches the working tree.
            file_tree.delete(*file_tree.get_children())

            for status, path in rows:
                file_tree.insert("", "end", iid=path, values=(status, path))

            # Files that were NOT in the preview when the dialog
            # opened: they must be confirmed before being committed.
            fresh = new_paths - self._preview_paths

            if fresh:
                preview = "\n".join(sorted(fresh)[:10])

                if len(fresh) > 10:
                    preview += f"\n... and {len(fresh) - 10} more"

                answer = messagebox.askyesno(
                    "Commit",
                    "The working tree changed while the dialog was open.\n"
                    "The following file(s) were not in the preview:\n\n"
                    f"{preview}\n\n"
                    "Include them in the commit?",
                    parent=dialog
                )

                if not answer:
                    commit_button.state(["!disabled"])
                    commit_button.configure(text="Commit")
                    return

            # The refreshed tree is the preview now; adopt its
            # snapshot so perform_commit's safety net does not warn
            # about files we just showed and confirmed.
            self._preview_paths = new_paths

            dialog.destroy()
            self.run_background(
                lambda: self.perform_commit(message, tag),
                self.commit_finished
            )

        def on_error(error):
            # Never leave the dialog stuck with a disabled Commit button.
            try:
                exists = dialog.winfo_exists()
            except tk.TclError:
                return

            if not exists:
                return

            commit_button.state(["!disabled"])
            commit_button.configure(text="Commit")

            messagebox.showerror(
                "Commit",
                "Failed to scan the working tree.\n\n" + str(error),
                parent=dialog
            )

        self._diff_worker(worker, done, on_error=on_error)

    # ========================================================
    # Commit
    # ========================================================

    def perform_commit(self, message, tag=""):
        self.no_commit_changes = False
        self._unpreviewed = []
        self._tag_failed = False
        self.log("")
        self.log("Preparing commit...")

        if tag:
            self.log(f"Tag: {tag}")

        # The identity always comes from the launcher
        # (_git_frontend.py), so the repository config is forced
        # to match it on every commit.
        self.log("Using git identity:")

        self.log(f"{self.git_user} <{self.git_email}>")

        code, _ = self.run_git(["config", "user.name", self.git_user])

        if code != 0:
            raise RuntimeError("Failed to set git user.name.")

        code, _ = self.run_git(["config", "user.email", self.git_email])

        if code != 0:
            raise RuntimeError("Failed to set git user.email.")

        # A commit made while HEAD is detached would be unreferenced:
        # it vanishes from the --all timeline as soon as the user
        # switches away.  Auto-create a branch so the commit stays
        # reachable (equivalent to fossil's fork-on-update behavior).
        if self.is_detached_head():
            branch = f"detached-{self.get_short_head()}"

            self.log("")
            self.log(f"Detached HEAD - keeping commits on branch: {branch}")

            code, _ = self.run_git(["switch", "-c", branch])

            if code != 0:
                # Branch already exists (committing here again).
                code, _ = self.run_git(["switch", branch])

                if code != 0:
                    raise RuntimeError("Failed to create branch for detached HEAD.")

        # Write the ignore rules (ignore patterns + force-track
        # negations) before staging anything.
        self.write_gitignore()

        # Stage all changes (add, modify, delete, rename).
        self.log("Scanning project files...")

        code, _ = self.run_git(["add", "-A"])

        if code != 0:
            raise RuntimeError("Failed to stage project files.")

        # Force-track files that the ignore patterns would skip.
        self.force_track_files()

        # Check changes.
        self.log("")
        self.log("Checking for file changes...")

        code, output = self.run_git(["status", "--porcelain"])

        if code != 0:
            raise RuntimeError("Failed to check git status.")

        changes = []

        for line in output.splitlines():
            stripped = line.strip()

            if not stripped:
                continue

            changes.append(stripped)

        # No changes.
        if not changes:
            self.log("")
            self.log("No changes detected.")
            self.log("Nothing to commit.")
            self.no_commit_changes = True
            return

        # Check for files that were never in the dialog preview.
        #
        # Path formats differ between the preview scan (before
        # add -A) and this scan (after add -A): a rename shows up
        # as " D old" + "?? new" in the preview but as a single
        # "R  old -> new" line here.  Split the arrow form so
        # either side of the rename counts as previewed.
        unpreviewed = []

        for line in changes:
            path = line[3:] if len(line) >= 4 else line

            if path not in self._preview_paths:
                parts = [p.strip() for p in path.split(" -> ")] if " -> " in path else []

                if not any(p in self._preview_paths for p in parts):
                    unpreviewed.append(path)

        self._unpreviewed = unpreviewed

        if unpreviewed:
            self.log("")
            self.log("WARNING: files not shown in the preview will also be committed:")
            self.log("  (created while the commit dialog was open)")

            for path in unpreviewed:
                self.log(f"  - {path}")

        # Changes exist.
        self.log("")
        self.log(f"Changes detected: {len(changes)}")

        for change in changes:
            self.log(change)

        # Commit
        self.log("")
        self.log("Creating commit...")

        code, output = self.run_git(["commit", "-m", message])

        new_version = self.extract_new_version()

        # Strict success.
        if code != 0:
            self.log("")
            self.log("ERROR: Git commit failed.")

            if new_version:
                self.log(f"New_Version was reported: {new_version}")

            self.log("Git returned a non-zero exit code.")
            self.log("The GUI will NOT report this commit as successful.")
            self.log("")
            self.log("Git status:")

            self.run_git(["status", "--porcelain"])

            raise RuntimeError("Git commit failed.")

        if not new_version:
            raise RuntimeError("Git returned success, but no commit hash was reported.")

        self.log("")
        self.log(f"New_Version: {new_version}")
        self.log("Commit completed successfully.")

        if tag:
            self.log("")
            self.log(f"Creating tag: {tag}")

            code, _ = self.run_git(["tag", tag])

            if code != 0:
                # The commit itself already landed; a failed tag must
                # not turn the whole operation into an error.
                self._tag_failed = True
                self.log("")
                self.log("WARNING: the commit succeeded, but the tag could not be created.")
                self.log(f"Create it manually with: git tag {tag}")

    # ========================================================
    # Extract New_Version
    # ========================================================

    def extract_new_version(self):
        code, output = self.run_git(["rev-parse", "HEAD"], log_command=False, log_output=False)

        if code == 0:
            return output.strip()

        return ""

    # ========================================================
    # Commit finished
    # ========================================================

    def commit_finished(self):
        self.load_timeline()

        if self.no_commit_changes:
            messagebox.showwarning("Commit", "No changes to commit.", parent=self.root)
            return

        message = "Commit completed successfully."

        if self._unpreviewed:
            preview = "\n".join(self._unpreviewed[:10])

            if len(self._unpreviewed) > 10:
                preview += f"\n... and {len(self._unpreviewed) - 10} more"

            message += (
                "\n\nWARNING: the following file(s) were committed "
                "but never shown in the preview (created while the "
                "commit dialog was open):\n\n"
                f"{preview}"
            )

        if getattr(self, "_tag_failed", False):
            self._tag_failed = False
            message += "\n\nWARNING: the commit succeeded, but the tag could not be created."

        messagebox.showinfo("Commit", message, parent=self.root)
