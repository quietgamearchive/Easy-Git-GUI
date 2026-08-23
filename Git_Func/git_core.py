import os
import subprocess
import sys
import threading
from pathlib import Path

import tkinter as tk
from tkinter import messagebox


class GitCoreMixin:

    # ========================================================
    # Log
    # ========================================================

    def log(self, text=""):
        self.root.after(0, self._append_log, text)

    def _append_log(self, text):
        try:
            self.log_text.configure(state="normal")
            self.log_text.insert("end", text + "\n")
            self.log_text.see("end")
            self.log_text.configure(state="disabled")
        except tk.TclError:
            pass

    # ========================================================
    # Git command
    # ========================================================

    def run_git(self, args, log_command=True, capture=True, log_output=True, input=None, env=None):
        # core.quotepath=false: print non-ASCII file names (e.g.
        # Chinese) as plain UTF-8 instead of octal escapes, so
        # status/log output parses correctly and commit dialogs
        # show real names.  -c is a temporary config: the
        # repository settings are not modified.
        command = [str(self.git_exe), "-c", "core.quotepath=false"] + list(args)

        if log_command:
            self.log("")
            self.log(">>> " + subprocess.list2cmdline(command))

        try:
            flags = 0

            if sys.platform == "win32":
                # git.exe is a console program.  Without this
                # flag, every invocation creates a new console
                # window when the GUI runs without a console
                # (e.g. launched by pythonw.exe), which makes
                # Refresh / Revert visibly slow.
                flags = subprocess.CREATE_NO_WINDOW

            # input (stdin data) and stdin cannot both be passed:
            # when input is given, subprocess.run feeds it through
            # a pipe itself.
            if input is not None:
                stdin_kwargs = {"input": input}
            else:
                stdin_kwargs = {"stdin": subprocess.DEVNULL}

            full_env = None

            if env:
                full_env = os.environ.copy()
                full_env.update(env)

            result = subprocess.run(
                command,
                cwd=str(self.project_dir),
                stdout=subprocess.PIPE if capture else None,
                stderr=subprocess.STDOUT if capture else None,
                text=True,
                encoding="utf-8",
                errors="replace",
                shell=False,
                creationflags=flags,
                env=full_env,
                **stdin_kwargs
            )
        except Exception as e:
            self.log(f"!!! Git execution error: {e}")
            return -1, ""

        output = result.stdout or ""

        if capture and output and log_output:
            for line in output.splitlines():
                self.log(line)

        if log_command:
            self.log(f">>> Git exit code: {result.returncode}")

        return result.returncode, output

    # ========================================================
    # Repository state
    # ========================================================

    def is_repository(self):
        # .git may be a directory (regular repo) or a file (submodule
        # / worktree); either way it marks a git repository.
        return (self.project_dir / ".git").exists()

    def is_detached_head(self):
        # git symbolic-ref succeeds only when HEAD points at a branch.
        code, _ = self.run_git(["symbolic-ref", "--quiet", "HEAD"], log_command=False, log_output=False)
        return code != 0

    def get_short_head(self):
        code, output = self.run_git(["rev-parse", "--short", "HEAD"], log_command=False, log_output=False)

        if code == 0:
            return output.strip()

        return ""

    def is_rebase_in_progress(self):
        # A rebase in progress materializes either rebase-merge or
        # rebase-apply inside .git; both mean "do not start another
        # interactive rebase".
        for marker in ("rebase-merge", "rebase-apply"):
            code, output = self.run_git(
                ["rev-parse", "--git-path", marker],
                log_command=False,
                log_output=False
            )

            if code != 0:
                continue

            path = Path(output.strip())

            if not path.is_absolute():
                path = self.project_dir / path

            if path.exists():
                return True

        return False

    # ========================================================
    # Git command with environment variables
    #
    # Like run_git, but merges the given env entries into the
    # child environment.  Used by the Modify workflow to pass
    # GIT_SEQUENCE_EDITOR / GIT_EDITOR (and any auxiliary
    # variables) to git without touching the parent environment.
    # ========================================================

    def run_git_with_env(self, args, env, log_command=True, capture=True, log_output=True):
        # Thin wrapper: run_git merges the extra environment entries
        # (e.g. GIT_SEQUENCE_EDITOR / GIT_EDITOR for the Modify
        # workflow) into the child environment.
        return self.run_git(
            args,
            log_command=log_command,
            capture=capture,
            log_output=log_output,
            env=env
        )

    # ========================================================
    # Script command (git-filter-repo and friends)
    #
    # Like run_git, but runs an arbitrary python script (not the
    # git binary).  git-filter-repo invokes "git" internally, so
    # the git executable's directory is exposed to the child via
    # PATH.  Used by the Purge and Delete workflows.
    # ========================================================

    def run_git_script(self, command):
        import subprocess

        self.log("")
        self.log(">>> " + subprocess.list2cmdline(command))

        try:
            flags = 0

            if sys.platform == "win32":
                flags = subprocess.CREATE_NO_WINDOW

            # git-filter-repo invokes "git" internally; the git
            # binary may not be on PATH, so expose its directory
            # to the child process.
            env = os.environ.copy()

            git_dir = str(self.git_exe.parent)

            if git_dir not in env.get("PATH", ""):
                env["PATH"] = git_dir + os.pathsep + env.get("PATH", "")

            result = subprocess.run(
                command,
                cwd=str(self.project_dir),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                shell=False,
                creationflags=flags,
                env=env
            )
        except Exception as e:
            self.log(f"!!! Script execution error: {e}")
            return -1, ""

        output = result.stdout or ""

        for line in output.splitlines():
            self.log(line)

        self.log(f">>> Script exit code: {result.returncode}")

        return result.returncode, output

    # ========================================================
    # git-filter-repo runner
    #
    # git-filter-repo refuses to run while the working tree has
    # ANY untracked file - including gitignored ones, since its
    # check is "git ls-files -o" which lists everything (.kilo/,
    # __pycache__, the filter-repo script itself, ...).  To make
    # the rewrite possible on such trees, everything is stashed
    # away (git stash --all covers untracked and ignored files),
    # the rewrite runs from a copy of the script placed outside
    # the repo, and the working directory is restored afterwards.
    #
    # The restore must NOT use 'git stash pop': git-filter-repo
    # rewrites refs/stash like any other ref, which corrupts the
    # stash structure (its index/untracked child commits can be
    # pruned, leaving "not a stash-like commit").  Instead the
    # ORIGINAL stash commit is recorded before the rewrite and
    # applied directly afterwards (callers pass --no-gc, so the
    # original commit stays in the object database).  The leftover
    # refs/stash is then deleted - otherwise it keeps the stash
    # commits alive forever (phantom timeline rows, gc bloat).
    #
    # Returns (code, output) like run_git_script; on failure the
    # working tree is still restored before returning.
    # ========================================================

    def run_filter_repo(self, args):
        import shutil
        import tempfile

        filter_repo = self.filter_repo_script

        if not filter_repo.exists():
            raise RuntimeError("git-filter-repo was not found next to this program.")

        filter_repo_copy = ""
        stashed = False
        stash_commit = ""
        stash_entries_before = 0

        try:
            fd, filter_repo_copy = tempfile.mkstemp(suffix=".py", prefix="gitgui_filter_repo_")
            os.close(fd)
            shutil.copy2(str(filter_repo), filter_repo_copy)

            # Remember how many stash entries existed before, so
            # the temporary entry can be removed afterwards without
            # touching pre-existing user stashes.
            code, output = self.run_git(["stash", "list"], log_command=False, log_output=False)
            stash_entries_before = len(output.splitlines()) if code == 0 else 0

            code, output = self.run_git(["stash", "--all", "-m", "gitgui_autostash"])

            if code != 0:
                raise RuntimeError("Failed to stash the working tree before the rewrite.")

            # "No local changes to save": nothing was stashed, so
            # there is nothing to restore afterwards.
            if "No local changes" not in output:
                stashed = True
                self.log("Working tree stashed for the rewrite.")

                # Record the ORIGINAL stash commit: the rewrite will
                # rewrite refs/stash itself, corrupting the stash
                # structure, so the restore applies this original
                # commit directly instead of 'git stash pop'.
                code, output = self.run_git(["rev-parse", "refs/stash"], log_command=False, log_output=False)

                if code != 0:
                    raise RuntimeError("Failed to resolve the stash entry.")

                stash_commit = output.strip()

            command = [sys.executable, filter_repo_copy] + list(args)

            return self.run_git_script(command)
        finally:
            if stashed:
                self.log("Restoring the working tree...")

                code, output = self.run_git(["stash", "apply", stash_commit])

                if code != 0:
                    # Keep the original stash commit reachable so
                    # the user can retry 'git stash pop' manually.
                    self.run_git(["update-ref", "refs/stash", stash_commit], log_command=False, log_output=False)
                    self.log("WARNING: failed to restore the working tree automatically.")
                    self.log("Your changes are safe in the stash entry; run 'git stash pop' to restore them.")
                    self.log("List your stashes with 'git stash list'.")
                else:
                    self.log("Working tree restored.")

                    if stash_entries_before == 0:
                        # Remove the rewritten stash ref left behind
                        # by the rewrite: it would otherwise keep the
                        # stash commits alive forever (phantom rows
                        # in the timeline, gc bloat).
                        code, _ = self.run_git(["update-ref", "-d", "refs/stash"], log_command=False, log_output=False)

                        if code == 0:
                            self.log("Removed the temporary stash entry.")
                    else:
                        self.log("WARNING: pre-existing stash entries may have been affected by the rewrite; check 'git stash list'.")

            if filter_repo_copy:
                try:
                    os.remove(filter_repo_copy)
                except OSError:
                    pass

    # ========================================================
    # Safe file-path argument for git CLI
    #
    # git's option parser treats a path starting with "-" as an
    # option.  The "--" separator is honoured by git, but the
    # "./" prefix also works everywhere and is unambiguous.
    # ========================================================

    @staticmethod
    def safe_git_path(path):
        if path.startswith("-"):
            return "./" + path
        return path

    # ========================================================
    # Restore working files from a pre-rewrite commit
    #
    # git-filter-repo checks out the rewritten HEAD, which
    # removes files purged/deleted from history from the working
    # directory.  This helper restores them from the OLD commit
    # (which still exists in the object database between the
    # rewrite and the reflog expire / gc).  It only restores
    # files that are actually missing on disk, and uses the
    # binary "git show <sha>:<path>" form so the index is not
    # touched (the file stays untracked after restoration).
    # ========================================================

    def restore_working_files_from(self, old_head, paths):
        missing = [p for p in paths if not (self.project_dir / p).exists()]

        if not missing:
            return

        flags = 0

        if sys.platform == "win32":
            flags = subprocess.CREATE_NO_WINDOW

        restored = []

        for path in missing:
            target = self.project_dir / path
            target.parent.mkdir(parents=True, exist_ok=True)

            try:
                r = subprocess.run(
                    [str(self.git_exe), "show", "{}:{}".format(old_head, path)],
                    cwd=str(self.project_dir),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    shell=False,
                    creationflags=flags
                )

                if r.returncode != 0:
                    self.log(f"WARNING: could not restore working file: {path}")
                    continue

                with open(target, "wb") as f:
                    f.write(r.stdout)

                self.log(f"Restored working file: {path}")
                restored.append(path)
            except Exception as e:
                self.log(f"WARNING: could not restore working file {path}: {e}")

        if restored:
            self.log("Working files restored from the pre-rewrite commit.")
        else:
            self.log("WARNING: some working files could not be restored; "
                     "their content still exists in the object database until "
                     "a reflog expire / gc.")

    # ========================================================
    # Background task
    # ========================================================

    def run_background(self, function, done=None):
        if self.busy:
            return

        self.busy = True
        self.set_buttons(False)

        def runner():
            try:
                result = function()
            except Exception as e:
                # On failure the done callback is NOT called: it would
                # report a fake success (e.g. "Delete completed
                # successfully") although nothing was done.  The error
                # is logged and shown in a dialog instead.
                self.log(f"!!! ERROR: {e}")
                self.root.after(0, self._background_failed, str(e))
                return

            self.root.after(0, self._background_done, done)

        threading.Thread(target=runner, daemon=True).start()

    def _background_failed(self, message):
        self.busy = False
        self.set_buttons(True)
        messagebox.showerror("Git GUI", message, parent=self.root)

    def _background_done(self, done):
        self.busy = False
        self.set_buttons(True)

        if done:
            try:
                done()
            except Exception as e:
                self.log(f"!!! ERROR: {e}")
                messagebox.showerror("Git GUI", f"Unexpected error:\n\n{e}", parent=self.root)

    # ========================================================
    # Buttons
    # ========================================================

    def set_buttons(self, enabled):
        state = "normal" if enabled else "disabled"
        self.init_button.configure(state=state)
        self.refresh_button.configure(state=state)
        self.commit_button.configure(state=state)
        self.purge_button.configure(state=state)

    # ========================================================
    # Timeline helpers
    # ========================================================

    def load_timeline(self, keep_position=False):
        # Async: git log can take a moment on large repositories.
        # The newest request wins (request guard), so rapid
        # refreshes cannot interleave.
        if not self.is_repository():
            self.clear_timeline()
            return

        self._timeline_load_id = getattr(self, "_timeline_load_id", 0) + 1
        request_id = self._timeline_load_id
        self._timeline_loading = True
        limit = getattr(self, "_timeline_limit", 100)

        # Fetch one extra commit so we can tell whether more
        # history exists (for the auto-load-on-scroll feature).
        fetch = limit + 1

        # When auto-loading at the bottom, remember where the view
        # was so the rebuild does not jump back to the top.
        self._timeline_scroll_pos = None

        if keep_position:
            try:
                self._timeline_scroll_pos = float(self.timeline.yview()[0])
                self._timeline_scroll_count = len(self.timeline.get_children())
            except tk.TclError:
                self._timeline_scroll_pos = None

        def worker():
            # --all includes refs/stash, which would show stash
            # "WIP" entries as phantom commits; --exclude drops it
            # while keeping detached-HEAD commits visible.
            return self.run_git([
                "log",
                "--date=format-local:%Y-%m-%d %H:%M:%S",
                "--pretty=format:%h|%an|%ad|%D|%s",
                "--all",
                "--exclude=refs/stash",
                "-n", str(fetch)
            ], log_command=False)

        def done(result):
            if getattr(self, "_timeline_load_id", 0) != request_id:
                return  # superseded by a newer request

            self._timeline_loading = False

            code, output = result

            if code != 0:
                return

            try:
                self.timeline.delete(*self.timeline.get_children())
            except tk.TclError:
                return  # main window closed while git was running

            show_all = self.show_all_commits.get()

            lines = output.splitlines()
            self._timeline_has_more = len(lines) > limit

            for line in lines[:limit]:
                parts = line.split("|", 4)

                if len(parts) != 5:
                    continue

                commit_hash, user, date, refs, comment = (p.strip() for p in parts)

                if not commit_hash:
                    continue

                if not show_all and self.is_commit_hidden(commit_hash):
                    continue

                tag = self.parse_tags(refs)

                try:
                    self.timeline.insert("", "end", iid=commit_hash,
                                         values=(commit_hash, user, date, tag, comment))
                except tk.TclError:
                    return

            # Keep the same relative position after an auto-load
            # rebuild: rows are inserted in the same order, so the
            # previously topmost row keeps its index.
            if self._timeline_scroll_pos is not None:
                old_count = getattr(self, "_timeline_scroll_count", 0)
                new_count = len(self.timeline.get_children())

                if old_count > 0 and new_count > 0:
                    row = self._timeline_scroll_pos * old_count
                    self.timeline.yview_moveto(row / new_count)

        def on_error(error):
            self._timeline_loading = False

        self._diff_worker(worker, done, on_error=on_error)

    # ========================================================
    # Timeline auto-load (infinite scroll)
    #
    # Called from the vertical scrollbar callback when the view
    # reaches the bottom and more history is known to exist.
    # ========================================================

    def _on_timeline_scroll(self, first, last):
        try:
            self.timeline_scroll.set(first, last)
        except tk.TclError:
            return  # main window closed

        if self._timeline_loading or self.busy:
            return

        try:
            near_bottom = float(last) >= 0.995
        except (TypeError, ValueError):
            return

        if near_bottom and self._timeline_has_more:
            self._timeline_limit = getattr(self, "_timeline_limit", 100) + 100
            self.log(f"Loading up to {self._timeline_limit} commits...")
            self.load_timeline(keep_position=True)

    # ========================================================
    # Parse git's ref decorations (%D) into a tag string
    #
    # %D prints e.g. "HEAD -> master, tag: v1.0, develop".
    # Only the items with the "tag: " prefix are kept.
    # ========================================================

    @staticmethod
    def parse_tags(refs):
        refs = (refs or "").strip()

        if not refs:
            return ""

        tags = []

        for ref in refs.split(", "):
            ref = ref.strip()

            if ref.startswith("tag: "):
                tags.append(ref[5:])

        return ", ".join(sorted(set(tags)))

    def clear_timeline(self):
        self.timeline.delete(*self.timeline.get_children())
