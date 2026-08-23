import hashlib
import os
import re
import sys
import threading
from pathlib import Path



# https://github.com/newren/git-filter-repo
# 2.47.0

no_console = True

# Detach from the parent console when run by python.exe (dev mode only).
if no_console and sys.platform == "win32" and not getattr(sys, "frozen", False):
    import ctypes
    import io

    kernel32 = ctypes.windll.kernel32

    if kernel32.GetConsoleWindow() and kernel32.FreeConsole():
        # Detached from the console: discard stdout/stderr so later
        # print() calls do not raise OSError on the invalid handle.
        sys.stdout = io.StringIO()
        sys.stderr = io.StringIO()

# git.exe location.
#
# If git_binary is set (non-empty), that path is used.
# If empty, git.exe is looked up in the script's own directory.

git_binary = r"D:\2.Dev\Tools\MinGit\cmd\git.exe"

# git-filter-repo: a standalone python script located next to
# this program.  Used by the Purge workflow to rewrite history.

FILTER_REPO_SCRIPT = Path(__file__).resolve().parent / "git-filter-repo"

# Git_Func is a plain folder (no __init__.py), so it must be
# found via sys.path.  The script may be launched from any
# working directory, so add the script's own directory here.

_SCRIPT_DIR = Path(__file__).resolve().parent

if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

import tkinter as tk
from tkinter import ttk, messagebox

from Git_Func.git_core import GitCoreMixin
from Git_Func.git_state import GitStateMixin
from Git_Func.list import GitListMixin
from Git_Func.init import GitInitMixin
from Git_Func.commit import GitCommitMixin
from Git_Func.diff import GitDiffMixin
from Git_Func.purge import GitPurgeMixin


# ============================================================
# Constants
# ============================================================

APP_TITLE = "Easy Git GUI " + "v0.02 Rev.260823"

# Window position.
#
# The window is placed so that its top-left corner is at
# (DEFAULT_WIN_LEFT, DEFAULT_WIN_TOP) on the primary screen.
#
# These are the defaults used when the program starts.
# Adjust them to change where the window appears.

DEFAULT_WIN_LEFT = 100
DEFAULT_WIN_TOP = 100


# ============================================================
# Git ignore patterns (written to .gitignore)
#
# gitignore patterns match at any directory level unless they
# start with "/", so directory patterns are written with a
# trailing slash and the fossil-style "*/" prefixes are dropped.
# ============================================================

DEFAULT_IGNORE_PATTERNS = (
    "__pycache__/",
    "*.pyc",
    "*.lock",
    "*.pyo",
    "*.bak",
    ".pytest_cache/",
    ".venv/",
    "venv/",
    "env/",
    "build/",
    "dist/",
    ".kilo/",
    "hidden-commits.json",
    "git-filter-repo",
    "git-filter-repo-*.*"
)

# Files that must be tracked even though their names match the
# ignore patterns above.  gitignore supports negation, so each
# entry is written as "!path" at the end of .gitignore.
#
# Each entry is an exact repository-relative path, e.g.
#   "config.ini", "subfolder/settings.json"
FORCE_TRACK_PATTERNS = (
)


# ============================================================
# Application
#
# This is the main program, shared by all projects:
#
# - _git_frontend.py (the launcher) holds the USER / EMAIL
#   configuration and starts this script, passing its own path
#   plus the identity as command-line arguments.  Git_GUI.py
#   never executes the launcher; the identity is never read
#   back from the repository config.
# - The project directory is the launcher's parent directory.
# - The git.exe path comes from the git_binary constant above;
#   when it is empty, git.exe is looked up next to this script.
# - Shared constants (ignore patterns, force-track list)
#   live at the top of this module.
#
# Sub-functions live in the Git_Func package:
#   - git_core.py   logging, git execution, background tasks
#   - git_state.py  hidden-commits.json, commit details
#   - list.py       timeline list and its context menu
#   - init.py       repository initialization
#   - commit.py     commit workflow
#   - diff.py       diff panel and background diff worker
#   - purge.py      purge workflow (git-filter-repo)
# ============================================================

class GitGUI(GitCoreMixin, GitStateMixin, GitListMixin, GitInitMixin, GitCommitMixin, GitDiffMixin, GitPurgeMixin):

    def __init__(self, root, project, user, email):
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry(f"1100x730+{DEFAULT_WIN_LEFT}+{DEFAULT_WIN_TOP}")
        self.root.minsize(900, 600)
        self.disable_resize_maximize(self.root)

        # git.exe path: use git_binary if set, otherwise look in
        # the script's own directory.
        if git_binary:
            self.git_exe = Path(git_binary)
        else:
            self.git_exe = Path(__file__).resolve().parent / "git.exe"
        self.project_dir = Path(project)
        self.project_name = self.project_dir.name
        self.git_user = user
        self.git_email = email
        self.busy = False
        self.no_commit_changes = False
        self._preview_paths = set()
        self._unpreviewed = []
        self.ignore_patterns = DEFAULT_IGNORE_PATTERNS
        self.force_track_patterns = FORCE_TRACK_PATTERNS
        self.filter_repo_script = FILTER_REPO_SCRIPT
        self.hidden_commits = set()
        self._timeline_limit = 100
        self._timeline_load_id = 0

        self.setup_style()
        self.build_ui()
        self.refresh_info()

    # ========================================================
    # Style
    # ========================================================

    def setup_style(self):
        style = ttk.Style()
        try:
            style.theme_use("vista")
        except Exception:
            pass
        style.configure("Treeview", rowheight=24)
        style.configure("Treeview.Heading", font=("Segoe UI", 9, "bold"))
        style.configure("TButton", padding=(8, 4))

    # ========================================================
    # Main UI
    # ========================================================

    def build_ui(self):
        # Information
        info = ttk.Frame(self.root)
        info.pack(fill="x", padx=8, pady=(8, 4))

        ttk.Label(info, text="Git executable:").grid(row=0, column=0, sticky="w", padx=(0, 5), pady=2)
        self.git_label = ttk.Label(info, text=str(self.git_exe))
        self.git_label.grid(row=0, column=1, sticky="w", pady=2)

        ttk.Label(info, text="Project:").grid(row=1, column=0, sticky="w", padx=(0, 5), pady=2)
        self.project_label = ttk.Label(info, text=str(self.project_dir))
        self.project_label.grid(row=1, column=1, sticky="w", pady=2)

        ttk.Label(info, text="User:").grid(row=2, column=0, sticky="w", padx=(0, 5), pady=2)
        self.user_label = ttk.Label(info, text=f"{self.git_user} <{self.git_email}>")
        self.user_label.grid(row=2, column=1, sticky="w", pady=2)

        # Buttons
        button_frame = ttk.Frame(self.root)
        button_frame.pack(fill="x", padx=8, pady=5)

        self.init_button = ttk.Button(button_frame, text="Init", command=self.init_repository)
        self.init_button.pack(side="left", padx=(0, 5))

        self.refresh_button = ttk.Button(button_frame, text="Refresh", command=self.refresh)
        self.refresh_button.pack(side="left", padx=5)

        self.commit_button = ttk.Button(button_frame, text="Commit", command=self.open_commit_dialog)
        self.commit_button.pack(side="left", padx=5)

        self.purge_button = ttk.Button(button_frame, text="Purge", command=self.open_purge_dialog)
        self.purge_button.pack(side="left", padx=5)

        # Timeline
        timeline_frame = ttk.LabelFrame(self.root, text="Timeline")
        timeline_frame.pack(fill="both", expand=True, padx=8, pady=5)

        timeline_columns = ("hash", "user", "date", "tag", "comment")

        self.timeline = ttk.Treeview(
            timeline_frame,
            columns=timeline_columns,
            show="headings",
            selectmode="extended"
        )

        self.timeline.heading("hash", text="Hash")
        self.timeline.heading("user", text="User")
        self.timeline.heading("date", text="Date")
        self.timeline.heading("tag", text="Tag")
        self.timeline.heading("comment", text="Comment")

        # self.timeline.column("hash", width=120, minwidth=100)
        # self.timeline.column("user", width=100, minwidth=80)
        # self.timeline.column("date", width=180, minwidth=160)
        # self.timeline.column("tag", width=100, minwidth=60)
        # self.timeline.column("comment", width=500, minwidth=300)
        self.timeline.column("hash", width=30)
        self.timeline.column("user", width=30)
        self.timeline.column("date", width=100)
        self.timeline.column("tag", width=50)
        self.timeline.column("comment", width=450)
        

        timeline_scroll = ttk.Scrollbar(timeline_frame, orient="vertical", command=self.timeline.yview)
        self.timeline.configure(yscrollcommand=timeline_scroll.set)
        self.timeline.pack(side="left", fill="both", expand=True)
        timeline_scroll.pack(side="right", fill="y")

        self.timeline.bind("<Double-1>", self.show_selected_commit)
        self.timeline.bind("<Button-3>", self.on_timeline_right_click)

        self._timeline_tooltip = TimelineToolTip(self.timeline, self.get_commit_comment)

        # Timeline context menu
        self.show_all_commits = tk.BooleanVar(value=False)
        self.timeline_menu = tk.Menu(self.root, tearoff=0)
        self.timeline_menu.add_command(label="Switch(detach)", command=self.timeline_switch)
        self.timeline_menu.add_command(label="Modify commit", command=self.timeline_modify)
        self.timeline_menu.add_command(label="Delete", command=self.timeline_delete)
        self.timeline_menu.add_separator()
        self.timeline_menu.add_command(label="Hide", command=self.timeline_hide_show)
        self.timeline_menu.add_command(label="Load more commits", command=self.timeline_load_more)
        self.timeline_menu.add_separator()
        self.timeline_menu.add_checkbutton(
            label="Show all commit",
            variable=self.show_all_commits,
            command=self.load_timeline
        )

        # Log
        log_frame = ttk.LabelFrame(self.root, text="Log")
        log_frame.pack(fill="both", expand=True, padx=8, pady=(5, 8))

        self.log_text = tk.Text(
            log_frame,
            font=("Consolas", 10),
            wrap="none",
            height=12,
            undo=False,
            bg="white",
            fg="black",
            insertbackground="black",
            relief="sunken",
            borderwidth=1
        )

        log_y = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        log_x = ttk.Scrollbar(log_frame, orient="horizontal", command=self.log_text.xview)
        self.log_text.configure(yscrollcommand=log_y.set, xscrollcommand=log_x.set)
        self.log_text.grid(row=0, column=0, sticky="nsew")
        log_y.grid(row=0, column=1, sticky="ns")
        log_x.grid(row=1, column=0, sticky="ew")
        log_frame.rowconfigure(0, weight=1)
        log_frame.columnconfigure(0, weight=1)

    # ========================================================
    # Refresh
    # ========================================================

    def refresh(self):
        self.refresh_info()

    def refresh_info(self):
        self.log(APP_TITLE)
        self.log(f"Git executable: {self.git_exe}")
        self.log(f"Project: {self.project_dir}")
        self.log(f"Project name: {self.project_name}")
        self.log(f"User: {self.git_user} <{self.git_email}>")

        if self.git_exe.exists():
            self.log("Git executable found.")
        else:
            self.log("WARNING: Git executable not found.")

        if self.is_repository():
            self.log("Git repository found.")
            self.load_hidden_commits()
            self.load_timeline()
        else:
            self.log("Git repository not found.")
            self.clear_timeline()

    # ========================================================
    # Center window
    #
    # Centering reference: the main window's wm geometry, which
    # describes its outer frame position and client size.  The
    # winfo_rootx/winfo_width values are client-area based and
    # would shift dialogs right by the left border and down by
    # the title bar.  Because the main window and the dialogs
    # share the same frame borders, aligning outer frames makes
    # the client areas coincide exactly.
    # ========================================================

    def center_window(self, window, width=None, height=None):
        # NOTE: a withdrawn window reports its geometry as
        # "1x1+0+0", so the requested size must be passed
        # explicitly by the caller instead of reading it back
        # from window.geometry().

        try:
            match = re.match(r"^(\d+)x(\d+)([+-]\d+)([+-]\d+)$", self.root.geometry())

            if not match:
                raise ValueError("unexpected geometry string")

            root_w = int(match.group(1))
            root_h = int(match.group(2))
            root_x = int(match.group(3))
            root_y = int(match.group(4))
        except Exception:
            root_x = self.root.winfo_rootx()
            root_y = self.root.winfo_rooty()
            root_w = self.root.winfo_width()
            root_h = self.root.winfo_height()

        win_w = width
        win_h = height

        if not win_w or not win_h or win_w <= 1 or win_h <= 1:
            win_w = max(window.winfo_reqwidth(), 1)
            win_h = max(window.winfo_reqheight(), 1)

        x = root_x + (root_w - win_w) // 2
        y = root_y + (root_h - win_h) // 2

        if x < 0:
            x = 0

        if y < 0:
            y = 0

        window.geometry(f"+{x}+{y}")

    # ========================================================
    # Disable resize and maximize
    #
    # On Windows the window cannot be resized by dragging and
    # the maximize button is removed from the title bar.
    #
    # resizable(False, False) alone is not enough: the
    # maximize button can stay enabled, so the WS_MAXIMIZEBOX
    # and WS_THICKFRAME styles are also cleared explicitly.
    # ========================================================

    def disable_resize_maximize(self, window):
        window.resizable(False, False)

        try:
            import ctypes

            user32 = ctypes.windll.user32
            gwl_style = -16
            ws_thickframe = 0x00040000
            ws_maximizebox = 0x00010000

            user32.GetWindowLongW.restype = ctypes.c_long
            user32.GetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int]
            user32.SetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_long]

            hwnd = user32.GetParent(window.winfo_id())

            if not hwnd:
                return

            style = user32.GetWindowLongW(hwnd, gwl_style)
            style &= ~(ws_thickframe | ws_maximizebox)
            user32.SetWindowLongW(hwnd, gwl_style, style)

            # Refresh the window frame so the title bar
            # immediately reflects the new style.
            #
            # SWP_NOSIZE | SWP_NOMOVE | SWP_NOZORDER
            # | SWP_FRAMECHANGED

            user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0004 | 0x0020)
        except Exception:
            pass


# ============================================================
# Timeline hover tooltip
#
# Rows truncate long commit comments; hovering shows the full
# original comment (with its line breaks) fetched from git via
# the provided getter, in a small popup that follows the mouse.
# The getter is only called once per commit (memoized).
# ============================================================

class TimelineToolTip:

    _CACHE_LIMIT = 300

    def __init__(self, tree, comment_getter):
        self.tree = tree
        self.root = tree.winfo_toplevel()
        self.comment_getter = comment_getter
        self.tip = None
        self.tip_label = None
        self._cache = {}
        self._pending = set()
        self._hovering = None

        tree.bind("<Motion>", self._on_motion)
        tree.bind("<Leave>", self._on_leave)

    def _row_values(self, event):
        row_id = self.tree.identify_row(event.y)

        if not row_id:
            return None

        try:
            values = self.tree.item(row_id, "values")
        except tk.TclError:
            return None

        if not values or not values[0]:
            return None

        return values

    def _on_motion(self, event):
        values = self._row_values(event)

        if not values:
            self._hide()
            return

        commit_hash = str(values[0])
        self._hovering = commit_hash

        if commit_hash in self._cache:
            text = self._cache.get(commit_hash) or ""

            if text:
                self._show(text)
            else:
                self._hide()
            return

        # Fetch the comment on a background thread: the git lookup
        # runs a subprocess and must not block the UI on hover.
        if commit_hash not in self._pending:
            self._pending.add(commit_hash)
            self._show("(loading...)")

            def fetch():
                try:
                    text = self.comment_getter(commit_hash) or ""
                except Exception:
                    text = ""

                self._pending.discard(commit_hash)
                self._cache[commit_hash] = text

                if len(self._cache) > self._CACHE_LIMIT:
                    self._cache.clear()

                self.root.after(0, lambda: self._on_fetch_done(commit_hash, text))

            threading.Thread(target=fetch, daemon=True).start()

    def _on_fetch_done(self, commit_hash, text):
        if self._hovering != commit_hash:
            return

        if text:
            self._show(text)
        else:
            self._hide()

    def _show(self, text):
        x = self.root.winfo_pointerx() + 15
        y = self.root.winfo_pointery() + 15

        if self.tip is not None:
            try:
                self.tip.geometry(f"+{x}+{y}")
                self.tip_label.configure(text=text)
                return
            except tk.TclError:
                self.tip = None

        self.tip = tk.Toplevel(self.tree)
        self.tip.wm_overrideredirect(True)
        self.tip.wm_geometry(f"+{x}+{y}")
        self.tip_label = tk.Label(
            self.tip,
            text=text,
            justify="left",
            font=("Consolas", 9),
            background="#ffffe0",
            relief="solid",
            borderwidth=1
        )
        self.tip_label.pack()

    def _on_leave(self, event):
        self._hovering = None
        self._hide()

    def _hide(self):
        if self.tip is not None:
            try:
                self.tip.destroy()
            except tk.TclError:
                pass
            self.tip = None


# ============================================================
# Main
# ============================================================

def enable_dpi_awareness():
    # Without this, tkinter renders blurry on high-DPI displays.
    # Must be called before any window is created.
    if sys.platform != "win32":
        return

    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def acquire_single_instance(project):
    # Kernel-level single-instance lock, selected by platform:
    #
    #   Windows  -> named mutex (kernel object, no file)
    #   Linux    -> abstract unix socket (kernel namespace, no file)
    #   macOS    -> flock on a lock file (kernel-managed advisory
    #               lock, auto-released on process death; the file
    #               stays on disk but can never be left "locked")
    #
    # Every variant releases itself automatically when the process
    # exits or crashes, so a stale lock can never block startup.
    # Returns a handle/socket/fd that must stay referenced for the
    # lifetime of the process, or None if another instance for this
    # project is already running.  Different projects may run in
    # parallel (the lock name is derived from the project path).
    name = hashlib.sha1(project.encode("utf-8")).hexdigest()

    if sys.platform == "win32":
        return _acquire_windows_mutex(name)

    if sys.platform == "linux":
        return _acquire_linux_socket(name)

    return _acquire_posix_flock(name)


def _acquire_windows_mutex(name):
    # Named kernel mutex: the same name always maps to the same
    # object; ERROR_ALREADY_EXISTS (183) means another process
    # already holds it.  The kernel destroys the object when the
    # last handle is closed, i.e. when that process exits.
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

    handle = kernel32.CreateMutexW(None, False, "GitGUI_" + name)

    if not handle:
        return None

    if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
        kernel32.CloseHandle(handle)
        return None

    return handle


def _acquire_linux_socket(name):
    # Abstract unix socket: the leading "\0" puts the address in
    # the kernel's abstract namespace instead of the filesystem,
    # so no file is created.  Binding the same name twice fails
    # with EADDRINUSE; the kernel removes the binding when the
    # owning process dies.
    import socket

    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)

    try:
        sock.bind("\0GitGUI_" + name)
    except OSError:
        sock.close()
        return None

    sock.listen(1)
    return sock


def _acquire_posix_flock(name):
    # macOS (and any other POSIX system without abstract sockets):
    # advisory flock on a lock file.  The lock itself lives in the
    # kernel and is released automatically when the process dies,
    # so the leftover file can never block startup again.
    import fcntl
    import tempfile

    lock_path = os.path.join(tempfile.gettempdir(), "GitGUI_" + name + ".lock")
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)

    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        return None

    return fd


_instance_mutex = None


def main():
    enable_dpi_awareness()

    if len(sys.argv) < 4:
        fail("No launcher path was provided.\n\nStart _git_frontend.py instead.")
        return

    launcher_path = Path(sys.argv[1]).resolve()

    if not launcher_path.is_file():
        fail("Launcher script was not found:\n\n" + str(launcher_path))
        return

    project = str(launcher_path.parent)
    user = sys.argv[2].strip()
    email = sys.argv[3].strip()

    if not user or not email:
        fail("USER and EMAIL must be set in _git_frontend.py.")
        return

    global _instance_mutex
    _instance_mutex = acquire_single_instance(project)

    if not _instance_mutex:
        fail("Git GUI is already running for this project.")
        return

    root = tk.Tk()
    GitGUI(root, project, user, email)
    root.mainloop()


def fail(message):
    root = tk.Tk()
    root.withdraw()
    messagebox.showerror("Git GUI", message)
    root.destroy()


if __name__ == "__main__":
    main()
