import threading

import tkinter as tk
from tkinter import ttk, messagebox


# Status priority for sorting the change list.
CHANGE_STATUS_ORDER = {
    "EDITED": 1,
    "ADDED": 2,
    "DELETED": 3,
    "EXTRA": 4,
}


class GitDiffMixin:

    # ========================================================
    # Porcelain status parsing
    # ========================================================

    @staticmethod
    def _parse_status_rows(output):
        rows = []

        for line in output.splitlines():
            if len(line) < 4:
                continue

            xy = line[:2]
            path = line[3:]

            # Renames are reported as "old -> new"; the destination
            # is the real path (matches the add -A view used later).
            if " -> " in path:
                path = path.split(" -> ", 1)[1]

            if xy == "??":
                status = "EXTRA"
            elif "D" in xy:
                status = "DELETED"
            elif "A" in xy or "C" in xy or "R" in xy:
                status = "ADDED"
            elif "M" in xy or "T" in xy or "U" in xy:
                status = "EDITED"
            else:
                status = "EXTRA"

            rows.append((status, path))

        return rows

    @staticmethod
    def _extract_real_path(path):
        # Porcelain v1 reports a rename as "old -> new"; only the
        # destination is a real path git commands can use.
        if " -> " in path:
            return path.split(" -> ", 1)[1]

        return path

    # ========================================================
    # Background diff worker
    # ========================================================

    def _diff_worker(self, function, done, on_error=None):
        def runner():
            try:
                result = function()
            except Exception as e:
                self.log(f"!!! ERROR: {e}")
                self.root.after(0, lambda: self._diff_worker_error(e, on_error))
                return
            self.root.after(0, lambda: self._safe_done(done, result))

        threading.Thread(target=runner, daemon=True).start()

    def _diff_worker_error(self, error, on_error):
        # Without a custom handler the caller (e.g. a dialog) can be
        # left in a stuck state; the default is an error dialog.
        if on_error:
            try:
                on_error(error)
            except Exception as e:
                self.log(f"!!! ERROR: {e}")
            return

        try:
            messagebox.showerror("Git GUI", f"Unexpected error:\n\n{error}", parent=self.root)
        except Exception:
            pass

    def _safe_done(self, done, result):
        try:
            done(result)
        except Exception as e:
            self.log(f"!!! ERROR: {e}")

    # ========================================================
    # Changes list (left pane of the commit dialog)
    # ========================================================

    def load_commit_changes(self, tree, commit_button=None):
        def worker():
            # Porcelain status: "XY path" per line; "??" marks
            # untracked files.  Handles all change types at once.
            return self.run_git(["status", "--porcelain"], log_output=False)

        def done(result):
            try:
                exists = tree.winfo_exists()
            except tk.TclError:
                return  # dialog was closed while git was running

            if not exists:
                return

            code, output = result
            tree.delete(*tree.get_children())

            rows = []

            if code == 0:
                rows = self._parse_status_rows(output)

            rows.sort(key=lambda r: (CHANGE_STATUS_ORDER.get(r[0], 99), r[1].lower()))

            for status, path in rows:
                tree.insert("", "end", iid=path, values=(status, path))

            # Snapshot the preview paths now that the list is
            # complete.  The tree is populated asynchronously, so
            # capturing the set at Commit-click time used to see an
            # empty/partial tree and flag every committed file.
            self._preview_paths = {path for status, path in rows}

            if commit_button:
                commit_button.state(["!disabled"])
                commit_button.configure(text="Commit")

        def on_error(error):
            # Never leave the Commit button stuck on "Scanning...".
            if commit_button is not None:
                try:
                    commit_button.state(["!disabled"])
                    commit_button.configure(text="Commit")
                except tk.TclError:
                    pass

            messagebox.showerror(
                "Commit",
                f"Failed to scan the working tree:\n\n{error}",
                parent=self.root
            )

        self._diff_worker(worker, done, on_error=on_error)

    # ========================================================
    # File diff (right pane of the commit dialog)
    # ========================================================

    def show_file_diff(self, diff_text, path):
        # Request guard: when the user clicks through the list
        # quickly, only the newest request is allowed to render.
        self._diff_request_id = getattr(self, "_diff_request_id", 0) + 1
        request_id = self._diff_request_id

        diff_text.configure(state="normal")
        diff_text.delete("1.0", "end")
        diff_text.configure(state="disabled")

        real_path = self._extract_real_path(path)

        def worker():
            # Working tree vs index.
            return self.run_git(["diff", "--", self.safe_git_path(real_path)], log_output=False)

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
                diff_text.insert("1.0", "(git diff failed)\n")
            elif not output.strip():
                diff_text.insert("1.0", "(no textual diff - untracked or binary file)\n")
            else:
                self.render_diff(diff_text, output)

            diff_text.configure(state="disabled")

        self._diff_worker(worker, done)

    # ========================================================
    # Diff rendering
    # ========================================================

    @staticmethod
    def render_diff(diff_text, output):
        plus = diff_text.tag_configure("diff-plus", foreground="#008000")
        minus = diff_text.tag_configure("diff-minus", foreground="#cc0000")
        hunk = diff_text.tag_configure("diff-hunk", foreground="#0000cc")
        head = diff_text.tag_configure("diff-head", foreground="#808080")

        for line in output.splitlines():
            stripped = line.strip()

            if stripped.startswith("+++") or stripped.startswith("---") or stripped.startswith("diff "):
                diff_text.insert("end", line + "\n", "diff-head")
            elif stripped.startswith("@@"):
                diff_text.insert("end", line + "\n", "diff-hunk")
            elif line.startswith("+"):
                diff_text.insert("end", line + "\n", "diff-plus")
            elif line.startswith("-"):
                diff_text.insert("end", line + "\n", "diff-minus")
            else:
                diff_text.insert("end", line + "\n")
