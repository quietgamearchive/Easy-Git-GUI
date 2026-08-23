# Easy Git GUI

A lightweight Git GUI written in Python tkinter.

Python tkinter 製の軽量 Git GUI ツールです。

> ⚠️ **Windows only — tested on Windows only.**
> The program uses Windows-specific APIs (`ctypes.windll`, `CREATE_NO_WINDOW`, `attrib`, etc.) and has not been tested on other platforms.
>
> **Windows のみ対応(動作確認は Windows のみ)。**
> 内部で `ctypes.windll`、`CREATE_NO_WINDOW`、`attrib` などの Windows 専用 API を使用しており、他のプラットフォームでは動作しません。

## Features / 機能

- **Init** — Create a new repository (reftable format; falls back to the default format on older git). Generates `.gitignore` and creates the initial commit automatically. / 新規リポジトリを作成(reftable 形式、古い git では規定形式へ自動フォールバック)。`.gitignore` を自動生成し、最初のコミットを行います。
- **Commit** — Stage and commit all changes (optional tag); preview changed files and diffs before committing. / すべての変更をステージ/コミット(タグ付けも任意可能)。コミット前に変更ファイルの diff をプレビューできます。
- **Timeline** — Commit timeline (hover to see full message). Right-click menu:
  - **Switch(detach)** — Check out a commit in detached HEAD state. / 指定コミットを detached HEAD でチェックアウト
  - **Modify commit** — Rewrite a commit message via non-interactive rebase (optional tag). / 非対話型 rebase でコミットメッセージを書き換え(タグも可)
  - **Delete** — Permanently remove the selected commits from all history using git-filter-repo. / git-filter-repo で選択したコミットを全履歴から完全削除
  - **Hide / Show** — Hide or show commits in the timeline. / タイムライン上でコミットを表示/非表示
  - The timeline shows the latest 100 commits by default; scrolling to the bottom **auto-loads more** (+100 each time) until the full history is loaded. / タイムラインはデフォルトで最新 100 件を表示。スクロールバーを最下部までスクロールすると**自動で追加読み込み**(毎回 +100 件)され、全履歴が読み込まれるまで続きます。
- **Purge** — Permanently remove selected files from all history using git-filter-repo. / git-filter-repo で選択したファイルを全履歴から完全削除

## Requirements / 動作環境

| Dependency | Notes |
|---|---|
| Windows | Windows only (Windows のみ) |
| Python 3 | with tkinter (included in standard install) / tkinter 必須(標準インストールに含まれる) |
| git | **MinGit** recommended (~40–60 MB, much smaller than full Git for Windows). ≥ 2.45 suggested for reftable support. / **MinGit** 推奨(フル Git for Windows より大幅に小さい)。reftable 対応には ≥ 2.45 推奨。 |

**Finding git** (choose one):

1. Set `git_binary` at the top of `Git_GUI.py` to the absolute path of git.exe, e.g.:
   ```python
   git_binary = r"D:\Tools\MinGit\cmd\git.exe"
   ```
2. Leave `git_binary` empty — the program will look for `git.exe` next to the script.

## Installation & Usage / インストールと起動

The project separates the **frontend (launcher) from the main program**:

- `_git_frontend.py` — One launcher per project; holds project-specific configuration (user identity, main script path).
- `Git_GUI.py` + `Git_Func/` — Shared main program, placed in a fixed tool directory.

### Step 1: Prepare the launcher / 起動ファイルの準備

1. **Copy** `_git_frontend.py.sample` into your project directory and **remove the `.sample` extension** → `_git_frontend.py`.
2. Open it and edit the three configuration fields:

   ```python
   USER = "your_name"          # user name for commits / コミット時のユーザー名
   EMAIL = "your@email.com"    # email for commits / コミット時のメールアドレス
   MAIN_PATH = r"C:\Tools\Easy_Git_GUI\Git_GUI.py"   # absolute path to Git_GUI.py
   ```

   - The project directory is automatically the launcher's parent — no need to fill it.
   - MAIN_PATH only needs to be set once; it won't change unless you move the tool directory.

3. Make sure `git_binary` in `Git_GUI.py` points to your git.exe (see Requirements above).

### Step 2: Launch / 起動

```bat
python _git_frontend.py
```

You can also create a desktop shortcut to `_git_frontend.py` for one-click launch.

デスクトップに `_git_frontend.py` のショートカットを作成すれば、ダブルクリックで起動できます。

## ⚠️ Dangerous Operations / 危険な操作の警告

**Delete (commits) and Purge (files) rewrite history permanently:**

- All affected commit hashes change.
- **The reflog is expired** — the old history cannot be recovered via `git reflog`.
- Confirmation dialogs show detailed warnings; read them carefully before proceeding.

**コミット削除(Delete)とファイル削除(Purge)は履歴を永久に書き換えます:**
- 影響を受けるすべてのコミットのハッシュ値が変わります。
- **reflog も消去される**ため、`git reflog` による復旧はできません。
- 確認ダイアログに詳細な警告が表示されます。よく読んでから操作してください。

**Disk files are NEVER deleted:**

- Working files temporarily removed during the rewrite are automatically restored from the old commit content.
- Only the repository history is rewritten — **physical files in your project directory are never deleted**.
- So after a Purge, the files remain on disk. If you want them gone for good, delete them manually; otherwise the next Commit will re-add them (as stated in the confirmation dialog).

**ディスク上のファイルは決して削除されません:**
- 書き換え中に一時的に削除された作業ファイルは、古いコミットの内容から自動的に復元されます。
- 書き換えられるのはリポジトリの履歴のみで、**プロジェクトディレクトリ内の物理ファイルは絶対に削除されません。**
- そのため Purge 後もファイルはディスクに残ります。完全に消したい場合は手動で削除してください。削除しないと次回の Commit で再追加されます(確認ダイアログに記載あり)。

## License / ライセンス

- **Project**: GPL-3.0 (see `LICENSE`)
- **Third-party**:
  - git-filter-repo (used by Delete / Purge): MIT, see `licenses/git-filter-repo-MIT.txt`
  - git is installed by the user; not bundled

## Acknowledgments / 謝辞

All code in this project is AI-assisted. / 本プロジェクトの全コードは AI 支援で生成されています。

## Project Structure / ディレクトリ構成

```
Easy_Git_GUI/
├── Git_GUI.py              # Main program (shared across projects) / メインプログラム(全プロジェクト共通)
├── Git_Func/               # Modules (core / state / list / init / commit / diff / purge)
├── git-filter-repo         # History rewriting tool (MIT)
├── _git_frontend.py.sample # Launcher template (copy, rename to .py, configure) / 起動ファイルテンプレート
├── LICENSE                 # GPL-3.0
└── licenses/               # Third-party licenses