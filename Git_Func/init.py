import shutil
import subprocess
import sys

from tkinter import messagebox


class GitInitMixin:

    # ========================================================
    # .gitignore
    # ========================================================

    def write_gitignore(self):
        # App-managed lines: the default patterns plus the negated
        # force-track entries.  User-added lines in an existing
        # .gitignore are preserved, so a commit no longer wipes
        # custom ignore rules.
        app_lines = list(self.ignore_patterns)

        for name in self.force_track_patterns:
            app_lines.append("!" + name)

        user_lines = []
        gitignore = self.project_dir / ".gitignore"

        if gitignore.exists():
            for line in gitignore.read_text(encoding="utf-8").splitlines():
                stripped = line.strip()

                if stripped and stripped not in app_lines:
                    user_lines.append(line)

        seen = set()
        merged = []

        for line in app_lines + user_lines:
            if line not in seen:
                seen.add(line)
                merged.append(line)

        content = "\n".join(merged) + "\n"

        existing = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""

        if existing != content:
            gitignore.write_text(content, encoding="utf-8")
            self.log(".gitignore updated.")

    # ========================================================
    # Force-track files that match the ignore patterns
    #
    # FORCE_TRACK_PATTERNS are negated in .gitignore, so the
    # files are no longer ignored; "git add -A" stages them
    # normally.  This method re-stages them explicitly in case
    # they were added to the list after the ignore file was
    # written (and as a safety net for already-committed files).
    # ========================================================

    def force_track_files(self):
        if not self.force_track_patterns:
            return

        for name in self.force_track_patterns:
            if not (self.project_dir / name).is_file():
                continue

            # -f overrides the ignore rules for this explicit add.
            code, _ = self.run_git(["add", "-f", "--", name], log_output=False)

            if code != 0:
                self.log(f"WARNING: failed to force-track file: {name}")

    # ========================================================
    # Init repository
    # ========================================================

    def init_repository(self):
        if not self.git_exe.exists():
            messagebox.showerror("Init", "Git executable was not found.", parent=self.root)
            return

        if not self.project_dir.exists():
            messagebox.showerror("Init", "Project directory was not found.", parent=self.root)
            return

        if self.is_repository():
            answer = messagebox.askyesno(
                "Init",
                (
                    "A Git repository already exists.\n\n"
                    "Re-initializing removes the existing .git directory - "
                    "ALL commit history will be lost - and creates a fresh "
                    "repository.\n\n"
                    "Continue?"
                ),
                parent=self.root
            )

            if not answer:
                return

        self.run_background(self.perform_init, self.init_finished)

    def perform_init(self):
        self.log("")
        self.log("Cleaning project Git data...")

        git_dir = self.project_dir / ".git"

        if git_dir.exists():
            try:
                if sys.platform == "win32":
                    # rmdir /s /q removes read-only files (e.g. git
                    # object files made read-only by git-filter-repo)
                    # without asking; shutil.rmtree would fail on
                    # them even after clearing the attribute.
                    r = subprocess.run(
                        ["cmd", "/c", "rmdir", "/s", "/q", str(git_dir)],
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        creationflags=subprocess.CREATE_NO_WINDOW
                    )

                    if r.returncode != 0:
                        raise RuntimeError(f"rmdir failed with exit code {r.returncode}")
                else:
                    shutil.rmtree(git_dir)

                self.log(f"Removed: {git_dir}")
            except Exception as e:
                raise RuntimeError(f"Failed to remove {git_dir}: {e}")

        self.log("Project Git data cleaned.")

        self.log("")
        self.log("Initializing Git repository (reftable ref format)...")

        # reftable (git >= 2.45): refs are stored in a compact,
        # faster table instead of per-file refs + packed-refs.
        code, output = self.run_git(["init", "--ref-format=reftable"])

        if code != 0:
            # Older git versions do not know --ref-format; fall
            # back to the default (legacy files) format.
            self.log("WARNING: this git does not support reftable; using the default ref format.")
            code, output = self.run_git(["init"])

        if code != 0:
            raise RuntimeError("Failed to initialize Git repository.")

        # Configure identity.
        self.log("Setting git identity...")

        code, _ = self.run_git(["config", "user.name", self.git_user])

        if code != 0:
            raise RuntimeError("Failed to set git user.name.")

        code, _ = self.run_git(["config", "user.email", self.git_email])

        if code != 0:
            raise RuntimeError("Failed to set git user.email.")

        # Ignore rules.
        self.log("Writing .gitignore...")

        self.write_gitignore()

        # Add all project files.
        self.log("")
        self.log("Scanning project files...")

        code, _ = self.run_git(["add", "-A"])

        if code != 0:
            raise RuntimeError("Failed to add project files.")

        self.force_track_files()

        # Check whether anything was staged.
        code, output = self.run_git(["status", "--porcelain"])

        if code != 0:
            raise RuntimeError("Failed to check git status.")

        if not output.strip():
            self.log("")
            self.log("No files to commit.")
            self.log("Initial commit skipped.")
            return

        # Initial commit.
        self.log("")
        self.log("Creating Initial commit: Initial commit")

        code, _ = self.run_git(["commit", "-m", "Initial commit"])

        if code != 0:
            raise RuntimeError("Initial commit failed.")

        self.log("")
        self.log("Initial commit completed successfully.")

    def init_finished(self):
        self.refresh_info()
