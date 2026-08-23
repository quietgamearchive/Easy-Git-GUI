from pathlib import Path

import tkinter as tk
from tkinter import ttk, messagebox


# ============================================================
# Purge workflow
#
# Removes files from ALL history using git-filter-repo
# (--path <name> --invert-paths).  The repository is rewritten
# and the file becomes unreachable, then git gc removes the
# orphaned objects.
#
# IMPORTANT DESIGN DECISION:
#
# Purge ONLY rewrites the repository history and NEVER deletes
# files from the working directory.  git-filter-repo checks out
# the rewritten HEAD (which would remove the purged files from
# disk during the operation), so before the rewrite the current
# HEAD and the files present on disk are recorded, and after the
# rewrite (success or failure) any working file that went
# missing is restored from the pre-rewrite commit's blob.  The
# purge dialogs therefore warn the user that the selected files
# are still present in the working directory afterwards and MUST
# be deleted manually, otherwise the next commit re-adds them to
# the repository (they "resurrect").
#
# Never delete files from disk here without an explicit user
# decision; that is a destructive action this tool must not
# take on its own.
#
# git-filter-repo is a standalone python script located next to
# this program (FILTER_REPO_SCRIPT in Git_GUI.py).
# ============================================================

class GitPurgeMixin:

    # ========================================================
    # Purge dialog (async loader)
    # ========================================================

    def open_purge_dialog(self):
        if self.busy:
            return

        if getattr(self, "_purge_dialog_opening", False):
            return

        if not self.is_repository():
            messagebox.showerror("Purge", "Git repository was not found.", parent=self.root)
            return

        self._purge_dialog_opening = True

        # List every file that ever existed in the repository.
        #
        # The size column shows the committed blob size from the
        # repository itself (HEAD tree, via git ls-tree -l) - never
        # the working-directory file size, which would be wrong for
        # uncommitted edits and untracked files.  Files that no
        # longer exist in the current tree show "?" (their
        # historical size would require walking every commit's
        # tree, which is too expensive).
        #
        # Both scans run on a background thread (the _diff_worker
        # pattern) instead of freezing the UI.
        def worker():
            # --all includes refs/stash; stash entries would pollute
            # the file list with their (often junk) file names.
            code, output = self.run_git([
                "log", "--all", "--exclude=refs/stash",
                "--pretty=format:", "--name-only"
            ], log_output=False)

            if code != 0:
                return code, "", {}

            # "mode type sha size\tpath" per line; the size field is
            # the blob's object size (its committed content).
            sizes = {}

            sc, sizes_output = self.run_git(
                ["ls-tree", "-r", "-l", "HEAD"],
                log_command=False,
                log_output=False
            )

            if sc == 0:
                for line in sizes_output.splitlines():
                    meta, sep, path = line.partition("\t")

                    if not sep:
                        continue

                    parts = meta.split()

                    if len(parts) != 4 or parts[1] != "blob":
                        continue

                    size = parts[3]

                    if size.isdigit():
                        sizes[path] = int(size)

            return code, output, sizes

        def done(result):
            try:
                code, output, sizes = result

                if code != 0:
                    messagebox.showerror("Purge", "Failed to list repository files.", parent=self.root)
                    return

                names = set()

                for line in output.splitlines():
                    stripped = line.strip()

                    if not stripped:
                        continue

                    names.add(stripped)

                rows = sorted((name, sizes.get(name)) for name in names)

                self._build_purge_dialog(rows)
            finally:
                self._purge_dialog_opening = False

        def on_error(error):
            # Reset the re-entry guard so the Purge button can be
            # used again after a failed scan.
            self._purge_dialog_opening = False

            messagebox.showerror(
                "Purge",
                f"Failed to list repository files:\n\n{error}",
                parent=self.root
            )

        self._diff_worker(worker, done, on_error=on_error)

    # ========================================================
    # Purge dialog (built by the async loader above)
    # ========================================================

    def _build_purge_dialog(self, rows):
        dialog = tk.Toplevel(self.root)

        dialog.withdraw()
        dialog.title("Purge Files")
        dialog.transient(self.root)
        dialog.geometry("700x560")
        dialog.minsize(600, 400)

        dialog_frame = ttk.Frame(dialog)
        dialog_frame.pack(fill="both", expand=True, padx=12, pady=12)
        dialog_frame.columnconfigure(0, weight=1)
        dialog_frame.rowconfigure(2, weight=1)

        ttk.Label(
            dialog_frame,
            text="Select files to remove from ALL history (cannot be undone):"
        ).grid(row=0, column=0, sticky="w", pady=(0, 5))

        ttk.Label(
            dialog_frame,
            text='Size is the committed size at HEAD (from the repository); "?" = no longer in the current tree.',
            foreground="#808080"
        ).grid(row=1, column=0, sticky="w", pady=(0, 5))

        tree = ttk.Treeview(
            dialog_frame,
            columns=("file", "size"),
            show="headings",
            selectmode="extended"
        )
        tree.heading("file", text="File")
        tree.heading("size", text="Size")
        tree.column("file", width=420, minwidth=200)
        tree.column("size", width=100, minwidth=80, anchor="e", stretch=False)

        tree_scroll = ttk.Scrollbar(dialog_frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=tree_scroll.set)
        tree.grid(row=2, column=0, sticky="nsew")
        tree_scroll.grid(row=2, column=1, sticky="ns")

        for name, size in rows:
            tree.insert("", "end", iid=name, values=(name, self._format_size(size)))

        button_frame = ttk.Frame(dialog_frame)
        button_frame.grid(row=3, column=0, columnspan=2, sticky="e", pady=(10, 0))

        cancel_button = ttk.Button(button_frame, text="Cancel", command=dialog.destroy)
        cancel_button.pack(side="right", padx=(5, 0))

        purge_button = ttk.Button(
            button_frame,
            text="Purge",
            command=lambda: self.confirm_purge(dialog, tree)
        )
        purge_button.pack(side="right")

        dialog.bind("<Escape>", lambda event: dialog.destroy())
        dialog.protocol("WM_DELETE_WINDOW", dialog.destroy)

        self.center_window(dialog, 700, 560)
        self.disable_resize_maximize(dialog)
        dialog.deiconify()

        # Make the dialog modal only AFTER it is mapped: a grab taken
        # while the window is withdrawn does not take effect on Windows.
        dialog.grab_set()
        dialog.focus_force()
        dialog.wait_window(dialog)

    # ========================================================
    # Purge confirmation
    # ========================================================

    def confirm_purge(self, dialog, tree):
        selection = tree.selection()

        if not selection:
            messagebox.showwarning("Purge", "No files selected.", parent=dialog)
            return

        files = [tree.item(item, "values")[0] for item in selection]
        count = len(files)

        preview = "\n".join(files[:10])

        if count > 10:
            preview += f"\n... and {count - 10} more"

        answer = messagebox.askyesno(
            "Purge",
            (
                f"Permanently remove {count} file(s) from ALL history?\n\n"
                f"{preview}\n\n"
                "The files will be deleted from every version and the "
                "repository will be rewritten by git-filter-repo.\n\n"
                "GUARANTEE: files on disk are NEVER deleted by purge - "
                "only the repository history is rewritten. Any working "
                "file removed during the operation is restored "
                "automatically.\n\n"
                "If you also want the files gone from disk, delete them "
                "yourself NOW, otherwise the next commit re-adds them "
                "to the repository.\n\n"
                "This REWRITES HISTORY and cannot be undone.\n\n"
                "The reflog will be expired and orphaned objects pruned, "
                "so the old history cannot be recovered via 'git reflog'.\n\n"
                "Continue?"
            ),
            parent=dialog
        )

        if not answer:
            return

        dialog.destroy()

        self.run_background(lambda: self.perform_purge(files), self.purge_finished)

    # ========================================================
    # Purge implementation
    # ========================================================

    def perform_purge(self, files):
        self.log("")
        self.log(f"Purging {len(files)} file(s) from all history...")

        for name in files:
            self.log(f"  - {name}")

        filter_repo = self.filter_repo_script

        if not filter_repo.exists():
            raise RuntimeError("git-filter-repo was not found next to this program.")

        # Snapshot the current HEAD and the working files that
        # exist on disk before the rewrite: after the rewrite
        # (which may report failure) any of them missing from the
        # working tree is restored from the pre-rewrite commit.
        # Purge NEVER deletes working files - only history.
        code, output = self.run_git(["rev-parse", "HEAD"], log_command=False, log_output=False)

        if code != 0:
            raise RuntimeError("Failed to resolve the current HEAD.")

        old_head = output.strip()
        present = [name for name in files if (self.project_dir / name).is_file()]

        # "--path=name" (equals form) so names starting with "-"
        # are not parsed as options by git-filter-repo's argparse.
        # "--no-gc" keeps the pre-rewrite objects alive until the
        # working files are restored below (filter-repo's own
        # cleanup would prune them immediately); the reflog expire
        # and git gc at the end of this method finish the cleanup.
        filter_args = ["--path=" + files[0], "--invert-paths", "--force", "--no-gc"]

        for name in files[1:]:
            filter_args.append("--path=" + name)

        code, output = self.run_filter_repo(filter_args)

        # Restore the working files FIRST, even on failure: the
        # rewrite's checkout may have removed them from disk.
        self.restore_working_files_from(old_head, present)

        if code != 0:
            raise RuntimeError("git-filter-repo failed.")

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
        self.log("Purge completed successfully.")

    # ========================================================
    # Purge finished
    # ========================================================

    def purge_finished(self):
        self.load_timeline()

        messagebox.showinfo(
            "Purge",
            (
                "Files removed from all history.\n\n"
                "Repository history rewritten and orphaned objects pruned.\n\n"
                "REMINDER: the files still exist in the working "
                "directory. Delete them on disk yourself, otherwise "
                "the next commit re-adds them to the repository."
            ),
            parent=self.root
        )

    # ========================================================
    # Helpers
    # ========================================================

    @staticmethod
    def _format_size(size):
        # None or 0: file is not in the current tree (historical
        # only), so the repository cannot report a single size.
        if not size:
            return "?"

        try:
            size = int(size)
        except (TypeError, ValueError):
            return "?"

        if size < 0:
            return "?"

        if size >= 1024 * 1024 * 1024:
            return f"{size / 1024 / 1024 / 1024:.1f} GB"

        if size >= 1024 * 1024:
            return f"{size / 1024 / 1024:.1f} MB"

        if size >= 1024:
            return f"{size / 1024:.1f} KB"

        return f"{size} B"

