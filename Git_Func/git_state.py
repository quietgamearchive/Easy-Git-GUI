import json


class GitStateMixin:

    # ========================================================
    # Hidden commits
    #
    # Stored in project-dir/hidden-commits.json (listed in
    # .gitignore so it is never tracked by git).
    # ========================================================

    @property
    def _hidden_file(self):
        return self.project_dir / "hidden-commits.json"

    def load_hidden_commits(self):
        try:
            data = json.loads(self._hidden_file.read_text(encoding="utf-8"))
            self.hidden_commits = set(str(x) for x in data)
        except Exception:
            self.hidden_commits = set()

    def save_hidden_commits(self):
        self._hidden_file.write_text(
            json.dumps(sorted(self.hidden_commits), indent=4),
            encoding="utf-8"
        )

    def is_commit_hidden(self, short_hash):
        return any(h.startswith(short_hash) for h in self.hidden_commits)

    def _discard_hidden_abbrev(self, full_hash):
        # Drop legacy entries stored as short abbreviations of this
        # commit (older sessions stored the abbreviated hash).  The
        # set is small, so a linear scan is fine.
        for h in list(self.hidden_commits):
            if len(h) < 40 and full_hash.startswith(h):
                self.hidden_commits.discard(h)

    # ========================================================
    # Hidden commit remapping after history rewrites
    #
    # Delete / Purge / Modify rewrite commit hashes, which makes
    # the stored hidden list silently stop matching.  The list is
    # remapped after every rewrite:
    #   - Delete / Purge: git-filter-repo writes a commit-map
    #     (.git/filter-repo/commit-map) mapping old -> new hashes.
    #   - Modify: the rebase preserves commit count and order, so
    #     rev-list before/after pairs up by index.
    # Entries that no longer exist (deleted commits) are dropped;
    # if the mapping is unusable the list is cleared with a log
    # message - it is never left silently stale.
    # ========================================================

    def remap_hidden_commits_from_map(self, old_to_new):
        self.load_hidden_commits()

        if not self.hidden_commits:
            return

        old_keys = list(old_to_new.keys())
        new_set = set()

        for hidden in self.hidden_commits:
            matches = [k for k in old_keys if k.startswith(hidden)]

            if len(matches) != 1:
                continue  # ambiguous or no longer exists: drop

            new_hash = old_to_new[matches[0]]

            if new_hash:
                new_set.add(new_hash)

        if new_set != self.hidden_commits:
            self.hidden_commits = new_set
            self.save_hidden_commits()
            self.log(f"Hidden commit list remapped ({len(new_set)} entries).")
        else:
            self.log("Hidden commit list unchanged by the rewrite.")

    def remap_hidden_commits_after_filter_repo(self):
        self.load_hidden_commits()

        if not self.hidden_commits:
            return

        map_file = self.project_dir / ".git" / "filter-repo" / "commit-map"

        if not map_file.is_file():
            self.log("WARNING: commit-map not found; hidden commit list cleared.")
            self.hidden_commits = set()
            self.save_hidden_commits()
            return

        # Every rewritten commit appears in the map (unchanged ones
        # map to themselves); deleted commits map to 40 zeroes.
        deleted_hash = "0" * 40
        old_to_new = {}

        for line in map_file.read_text(encoding="utf-8").splitlines():
            parts = line.split()

            if len(parts) < 2:
                continue

            old, new = parts[0], parts[1]

            # Skip the "old new" header line and anything that is
            # not a hash.
            if len(old) != 40 or len(new) != 40:
                continue

            if new == deleted_hash:
                new = None  # commit was deleted by the rewrite

            old_to_new[old] = new

        self.remap_hidden_commits_from_map(old_to_new)

    def remap_hidden_commits_after_rebase(self, old_list, new_list):
        self.load_hidden_commits()

        if not self.hidden_commits:
            return

        if len(old_list) != len(new_list):
            self.log("WARNING: rebase changed the commit count; hidden commit list cleared.")
            self.hidden_commits = set()
            self.save_hidden_commits()
            return

        old_to_new = {}

        for old, new in zip(old_list, new_list):
            if old != new:
                old_to_new[old] = new

        self.remap_hidden_commits_from_map(old_to_new)

    # ========================================================
    # Commit detail from git
    #
    # The timeline list truncates the subject line; the detail
    # view shows the full comment (with line breaks preserved
    # by --format=%B).
    # ========================================================

    def get_commit_comment(self, short_hash):
        code, output = self.run_git(
            ["log", "-1", "--pretty=format:%B", short_hash],
            log_command=False,
            capture=True,
            log_output=False
        )

        if code == 0:
            return output.strip()

        return ""

    def get_commit_detail(self, short_hash):
        # --format full comment (%B), author date, author name
        code, output = self.run_git(
            ["log", "-1",
             "--date=format-local:%Y-%m-%d %H:%M:%S",
             "--pretty=format:%B%n%n===META===%n%H%n%an%n%ad",
             short_hash],
            log_command=False,
            capture=True,
            log_output=False
        )

        if code != 0 or not output.strip():
            return None

        # Split on the sentinel line
        parts = output.split("\n===META===\n")

        if len(parts) != 2:
            return None

        comment = parts[0].strip()
        meta_lines = parts[1].strip().splitlines()

        if len(meta_lines) < 3:
            return None

        full_hash = meta_lines[0].strip()
        author = meta_lines[1].strip()
        date_str = meta_lines[2].strip()

        # Tags: branches containing this commit
        tags = []
        tc, to = self.run_git(
            ["branch", "-a", "--contains", full_hash],
            log_command=False,
            log_output=False
        )

        if tc == 0:
            for line in to.splitlines():
                branch = line.strip().lstrip("* ")

                if branch:
                    tags.append(branch)

        return {
            "date": date_str,
            "comment": comment,
            "user": author,
            "tags": tags,
        }