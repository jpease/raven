"""Behavioral tests for `scripts/check-staged-hygiene.py`.

Every test below builds a real temporary git repository, `git add`s real
content into it, and invokes the checker as a subprocess against that
staged index -- the checker's whole contract is "what git has staged", so a
test that feeds it a hand-written string proves nothing about the real
`git diff --cached` path.

No test uses a real private repository name. Name-check cases supply a
synthetic name through the denylist mechanism (`RAVEN_HYGIENE_DENYLIST`).
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from helpers import REPO_ROOT

CHECKER = REPO_ROOT / "scripts" / "check-staged-hygiene.py"

# A synthetic "private repo" name used only via the denylist mechanism --
# never written to a tracked file.
_SYNTHETIC_NAME = "zzz-quokka-vault"


class CheckStagedHygieneTests(unittest.TestCase):
    def setUp(self):
        # Same guard as tests/test_git_hooks.py: a hook-driven test run may
        # inherit GIT_DIR/GIT_INDEX_FILE, which would point git at the outer
        # repo instead of the temp repo these tests create.
        for var in [k for k in os.environ if k.startswith("GIT_")]:
            self.addCleanup(os.environ.__setitem__, var, os.environ[var])
            del os.environ[var]

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name)
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)

    def _git(self, *args: str, check: bool = True) -> str:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(self.repo),
                "-c",
                "user.email=hygiene-test@example.com",
                "-c",
                "user.name=Hygiene Test",
                *args,
            ],
            capture_output=True,
            text=True,
            check=check,
        )
        return result.stdout

    def _commit(self, path: str, content: str, message: str = "commit") -> None:
        target = self.repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        self._git("add", "--", path)
        self._git("commit", "-q", "-m", message)

    def _stage(self, path: str, content: str) -> None:
        target = self.repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        self._git("add", "--", path)

    def _run_checker(self, env_extra: dict[str, str] | None = None):
        env = dict(os.environ)
        env.pop("RAVEN_HYGIENE_DENYLIST", None)
        if env_extra:
            env.update(env_extra)
        return subprocess.run(
            [sys.executable, str(CHECKER)],
            cwd=self.repo,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

    def _denylist_env(self, *names: str) -> dict[str, str]:
        denylist_path = Path(self.tmp.name) / "denylist.txt"
        denylist_path.write_text("\n".join(names) + "\n", encoding="utf-8")
        return {"RAVEN_HYGIENE_DENYLIST": str(denylist_path)}

    # -- positive path match --------------------------------------------

    def test_positive_path_match_blocks_and_reports_path_and_line(self):
        self._stage(
            "docs/plan.md",
            "cd /Users/exampleuser/Developer/thing\n",  # raven-hygiene: allow
        )

        result = self._run_checker()

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("docs/plan.md:1:", result.stderr)
        self.assertIn("home-directory absolute path", result.stderr)
        self.assertIn("/Users/exampleuser/Developer/thing", result.stderr)  # raven-hygiene: allow
        self.assertIn("<downstream-repo>", result.stderr)
        self.assertIn("raven-hygiene: allow", result.stderr)

    # -- positive name match via a synthetic denylist ---------------------

    def test_positive_name_match_via_denylist_blocks(self):
        self._stage("docs/notes.md", f"See the {_SYNTHETIC_NAME} findings.\n")

        result = self._run_checker(self._denylist_env(_SYNTHETIC_NAME))

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("docs/notes.md:1:", result.stderr)
        self.assertIn("denylisted private repository name", result.stderr)

    def test_denylist_match_is_case_insensitive(self):
        self._stage("docs/notes.md", f"See the {_SYNTHETIC_NAME.upper()} findings.\n")

        result = self._run_checker(self._denylist_env(_SYNTHETIC_NAME))

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)

    # -- allow-marker suppression -----------------------------------------

    def test_allow_marker_suppresses_path_match(self):
        self._stage(
            "docs/plan.md",
            "cd /Users/exampleuser/Developer/thing  # raven-hygiene: allow\n",
        )

        result = self._run_checker()

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_allow_marker_suppresses_denylist_match(self):
        self._stage(
            "docs/notes.md",
            f"See the {_SYNTHETIC_NAME} findings.  # raven-hygiene: allow\n",
        )

        result = self._run_checker(self._denylist_env(_SYNTHETIC_NAME))

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_allow_marker_only_suppresses_its_own_line(self):
        # A marker on one line must not blanket-suppress a different
        # offending line in the same staged diff.
        self._stage(
            "docs/plan.md",
            "cd /Users/exampleuser/Developer/thing  # raven-hygiene: allow\n"
            "cd /Users/otheruser/Developer/thing\n",  # raven-hygiene: allow
        )

        result = self._run_checker()

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("/Users/otheruser/Developer/thing", result.stderr)  # raven-hygiene: allow
        suppressed = "/Users/exampleuser/Developer/thing"  # raven-hygiene: allow
        self.assertNotIn(suppressed, result.stderr)

    # -- absent denylist: skipped, not an error ---------------------------

    def test_absent_denylist_skips_name_check_silently(self):
        self._stage("docs/notes.md", f"See the {_SYNTHETIC_NAME} findings.\n")

        result = self._run_checker()  # no RAVEN_HYGIENE_DENYLIST, no default file

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stderr, "")

    # -- deleted lines must not fail the commit that removes them ---------

    def test_deleted_line_with_denylisted_name_does_not_fail(self):
        self._commit(
            "docs/notes.md",
            f"intro\n{_SYNTHETIC_NAME} appears here\noutro\n",
            "add note with name",
        )
        (self.repo / "docs" / "notes.md").write_text("intro\noutro\n", encoding="utf-8")
        self._git("add", "--", "docs/notes.md")

        result = self._run_checker(self._denylist_env(_SYNTHETIC_NAME))

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_deleted_path_line_does_not_fail(self):
        self._commit(
            "docs/plan.md",
            "cd /Users/exampleuser/Developer/thing\ndone\n",  # raven-hygiene: allow
            "add path",
        )
        (self.repo / "docs" / "plan.md").write_text("done\n", encoding="utf-8")
        self._git("add", "--", "docs/plan.md")

        result = self._run_checker()

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    # -- uv.lock is no longer exclude-listed (#181 design decision 2) -------
    #
    # `uv.lock` used to be a blanket EXCLUDED_PATHS entry to avoid noise from
    # routine hash/version-bump churn. Word-boundary + minimum-length
    # denylist matching (below) already makes that noise very unlikely to
    # false-positive, so the blanket exclusion was removed -- it was leaving
    # a real gap, since a `uv.lock` git-source dependency URL can legitimately
    # leak a private repo name.

    def test_uv_lock_content_is_now_scanned(self):
        # Same staged content the old, now-removed exclusion used to let
        # through clean -- it must now be caught like any other file.
        self._stage(
            "uv.lock",
            "# generated\npath = /Users/exampleuser/Developer/thing\n",  # raven-hygiene: allow
        )

        result = self._run_checker()

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("uv.lock:2:", result.stderr)
        self.assertIn("home-directory absolute path", result.stderr)

    def test_uv_lock_regeneration_noise_does_not_false_positive(self):
        # The original exclusion's noise-avoidance rationale: an ordinary
        # regenerated hash/version line should not trip the name check just
        # because a denylisted name appears as an unbounded substring of a
        # hex hash -- word-boundary matching (not a path exclusion) is what
        # prevents this now.
        self._stage(
            "uv.lock",
            'source = { git = "https://github.com/example/example-project" }\n'
            'sdist = { url = "https://example.com/pkg-1.2.3.tar.gz", '
            'hash = "sha256:9f8e7acorna1b2c3d4e5f60718293a4b5c6d7e8f9" }\n',
        )

        result = self._run_checker(self._denylist_env("acorn"))

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    # -- placeholder forms must NOT match -----------------------------------

    def test_bracket_placeholder_form_does_not_match(self):
        self._stage("docs/plan.md", "cd <downstream-repo> && raven doctor\n")

        result = self._run_checker()

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_users_placeholder_segment_does_not_match(self):
        self._stage("docs/plan.md", "Write repro steps as cd /Users/<name>/Developer/...\n")

        result = self._run_checker()

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_bare_users_prefix_in_prose_does_not_match(self):
        # Mirrors AGENTS.md's own rule text: a bare `/Users/` mentioned inside
        # backticks, immediately followed by punctuation, is not itself a path.
        self._stage(
            "docs/plan.md",
            "grep the diff for private repo names and `/Users/`. Keep the list local.\n",
        )

        result = self._run_checker()

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_bare_users_with_nothing_after_does_not_match(self):
        self._stage("docs/plan.md", "The prefix /Users/ alone is not a leak.\n")

        result = self._run_checker()

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_ellipsis_after_prefix_does_not_match(self):
        # A prose gesture at "and so on" (e.g. "/Users/...") must not read as
        # a real path segment -- "." alone is not an alnum lead.
        self._stage("docs/plan.md", "Home paths look like /Users/... on macOS.\n")

        result = self._run_checker()

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    # -- other absolute-path forms -----------------------------------------

    def test_home_linux_path_matches(self):
        self._stage("docs/plan.md", "rm -rf /home/exampleuser/project\n")  # raven-hygiene: allow

        result = self._run_checker()

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)

    def test_windows_backslash_path_matches(self):
        content = r"cd C:\Users\exampleuser\Developer" + "\n"  # raven-hygiene: allow
        self._stage("docs/plan.md", content)

        result = self._run_checker()

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)

    def test_wsl_path_matches(self):
        content = "cd /mnt/c/Users/exampleuser/Developer\n"  # raven-hygiene: allow
        self._stage("docs/plan.md", content)

        result = self._run_checker()

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)

    # -- binary content must not crash the checker --------------------------

    def test_binary_file_addition_does_not_crash(self):
        (self.repo / "blob.bin").write_bytes(bytes(range(256)))
        self._git("add", "--", "blob.bin")

        result = self._run_checker()

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    # -- denylist word boundaries + minimum entry length (#181 decision 1) --
    #
    # Two independent mechanisms close two different false-positive shapes:
    # word boundaries stop a name matching *inside* a longer word; the
    # length floor stops a short, common English word matching as a
    # perfectly legitimate *standalone* word. Each pair of tests below
    # isolates one mechanism so a regression in either shows up precisely.

    def test_denylist_word_boundary_prevents_substring_match_inside_word(self):
        # "acorns" contains "acorn" but is not the word "acorn" -- the old,
        # pre-#181 substring check would have matched this.
        self._stage("docs/notes.md", "The maple acorns fell in autumn.\n")

        result = self._run_checker(self._denylist_env("acorn"))

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_denylist_word_boundary_still_matches_standalone_word(self):
        # Positive control for the test above: the same entry must still
        # catch a genuine standalone occurrence -- word-boundary matching
        # narrows, it doesn't disable, the check.
        self._stage("docs/notes.md", "The acorn fell in autumn.\n")

        result = self._run_checker(self._denylist_env("acorn"))

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)

    def test_short_denylist_entry_is_dropped_with_warning(self):
        # "app" is word-bounded here (a genuine standalone token) -- a
        # boundary-only fix would still match it. The length floor is what
        # drops it, per #181 decision 1.
        self._stage("docs/notes.md", "This app works great.\n")

        result = self._run_checker(self._denylist_env("app"))

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("app", result.stderr)
        self.assertIn("shorter than", result.stderr)

    def test_denylist_entry_at_minimum_length_is_kept(self):
        # MIN_DENYLIST_ENTRY_LENGTH is 5; "acorn" is exactly 5 and must not
        # be dropped.
        self._stage("docs/notes.md", "acorn appears here.\n")

        result = self._run_checker(self._denylist_env("acorn"))

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertNotIn("shorter than", result.stderr)

    # -- home-path forms: ~, $HOME, case, doubled separators (decision 2) ---

    def test_tilde_home_path_matches(self):
        content = "cd ~/Developer/thing\n"  # raven-hygiene: allow
        self._stage("docs/plan.md", content)

        result = self._run_checker()

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)

    def test_dollar_home_env_var_path_matches(self):
        content = "cd $HOME/Developer/thing\n"  # raven-hygiene: allow
        self._stage("docs/plan.md", content)

        result = self._run_checker()

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)

    def test_home_path_matches_case_insensitively(self):
        content = "cd /USERS/exampleuser/Developer\n"  # raven-hygiene: allow
        self._stage("docs/plan.md", content)

        result = self._run_checker()

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)

    def test_home_path_matches_with_doubled_separator(self):
        content = "cd /Users//exampleuser/Developer\n"  # raven-hygiene: allow
        self._stage("docs/plan.md", content)

        result = self._run_checker()

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)

    def test_bare_tilde_in_prose_does_not_match(self):
        # "~30" has no path separator after the tilde -- not a home path,
        # mirrors the existing bare-`/Users/`-prefix exclusion philosophy.
        self._stage("docs/plan.md", "About ~30 users reported this.\n")

        result = self._run_checker()

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    # -- known-shared segments do not fire (#181 decision 5) -----------------

    def test_users_shared_segment_does_not_match(self):
        self._stage("docs/plan.md", "cp file /Users/Shared/screens/output.png\n")

        result = self._run_checker()

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_windows_users_public_segment_does_not_match(self):
        content = r"cd C:\Users\Public\Documents" + "\n"
        self._stage("docs/plan.md", content)

        result = self._run_checker()

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    # -- new/renamed file paths are scanned too (#181 decision 5/rename fix) -

    def test_new_file_path_with_denylisted_name_blocks(self):
        self._stage(f"docs/{_SYNTHETIC_NAME}/notes.md", "hello\n")

        result = self._run_checker(self._denylist_env(_SYNTHETIC_NAME))

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn(f"docs/{_SYNTHETIC_NAME}/notes.md: staged path contains", result.stderr)
        self.assertIn("denylisted private repository name", result.stderr)
        # Path-level findings have no line -- must not print a misleading ":0:".
        self.assertNotIn(f"docs/{_SYNTHETIC_NAME}/notes.md:0:", result.stderr)

    def test_new_file_path_with_home_path_blocks(self):
        self._stage("archive/Users/exampleuser/notes.md", "hello\n")  # raven-hygiene: allow

        result = self._run_checker()

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn(
            "archive/Users/exampleuser/notes.md: staged path contains",  # raven-hygiene: allow
            result.stderr,
        )
        self.assertIn("home-directory absolute path", result.stderr)

    def test_pure_rename_path_with_denylisted_name_blocks(self):
        # A 100%-similarity rename has no `+++`/hunk body at all -- this is
        # the exact gap #181 closes: the destination path from the
        # `diff --git a/X b/Y` header alone must be scanned.
        self._commit("docs/old-notes.md", "hello world\n", "add file")
        self._git("mv", "docs/old-notes.md", f"docs/{_SYNTHETIC_NAME}-notes.md")

        result = self._run_checker(self._denylist_env(_SYNTHETIC_NAME))

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn(f"docs/{_SYNTHETIC_NAME}-notes.md", result.stderr)
        self.assertIn("staged path contains", result.stderr)

    def test_deleted_file_path_does_not_block(self):
        # Removing a path is never a reason to block, same principle as a
        # removed line.
        self._commit(f"docs/{_SYNTHETIC_NAME}-notes.md", "hello\n", "add file")
        self._git("rm", f"docs/{_SYNTHETIC_NAME}-notes.md")

        result = self._run_checker(self._denylist_env(_SYNTHETIC_NAME))

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    # -- quoted `diff --git` headers must not hide the path scan (#193) -----
    #
    # git quotes a `diff --git a/X b/Y` header path (and the `+++`/`---`
    # lines) whenever it holds a byte >= 0x80 (subject to `core.quotePath`;
    # true is the default) or a literal `"` (always, regardless of
    # `core.quotePath` -- the header syntax needs it to stay parseable
    # either way). A path holding only a plain space is never quoted by
    # either setting. Verified directly against git 2.55 before writing
    # these two tests: an embedded `"` forces quoting under both settings,
    # which is what makes both of the tests below exercise the same real
    # gap -- the old header parsing only understood the unquoted form, so a
    # path like these was silently dropped from the path-level scan
    # entirely.

    def test_quoted_diff_header_path_with_home_path_hit_is_scanned_quote_path_true(
        self,
    ):
        self._git("config", "core.quotePath", "true")
        self._stage(
            'archive/Users/exampleuser/pärt "notes" plan.md',  # raven-hygiene: allow
            "hello\n",
        )

        result = self._run_checker()

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("staged path contains", result.stderr)
        self.assertIn("home-directory absolute path", result.stderr)

    def test_quoted_diff_header_path_with_denylist_hit_is_scanned_quote_path_false(
        self,
    ):
        self._git("config", "core.quotePath", "false")
        self._stage(f'docs/{_SYNTHETIC_NAME} pärt "notes".md', "hello\n")

        result = self._run_checker(self._denylist_env(_SYNTHETIC_NAME))

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("staged path contains", result.stderr)
        self.assertIn("denylisted private repository name", result.stderr)

    # -- staged combined diff (merge-conflict resolution) is never silently
    # skipped (#193) ---------------------------------------------------------
    #
    # #193's root-cause report assumed `git diff --cached` can show a git
    # "combined diff" (`@@@ ... @@@`) hunk header for a staged
    # merge-conflict resolution. Verified directly against real git (2.55)
    # for the exact scenario the issue describes (two branches modifying
    # the same lines of the same file, merge, resolve the conflict, stage
    # the resolution): it never does, with or without `-c`/`--cc` forced
    # explicitly. `--cached` always diffs the index against a single tree
    # (HEAD); git's own docs describe combined format as "the default
    # format when showing merges with git-diff(1) or git-show(1)" -- i.e.
    # displaying an *existing merge commit* (`git show`/`git log -p`),
    # never `--cached`'s index-vs-HEAD comparison. This test pins that
    # verified fact (so a future git behavior change would fail it loudly,
    # not silently) and guards what the acceptance criterion actually cares
    # about: a real staged merge-conflict resolution's content is fully
    # scanned, never silently dropped.
    def test_staged_merge_conflict_resolution_is_fully_scanned(self):
        self._commit("f.txt", "line1\nline2\n", "base")
        default_branch = self._git("branch", "--show-current").strip()
        self._git("checkout", "-q", "-b", "branch-a")
        self._commit("f.txt", "line1-a\nline2\n", "change on branch-a")
        self._git("checkout", "-q", default_branch)
        self._commit("f.txt", "line1-b\nline2\n", "change on original branch")
        self._git("merge", "-q", "branch-a", check=False)  # expected to conflict

        (self.repo / "f.txt").write_text(f"line1-{_SYNTHETIC_NAME}\nline2\n", encoding="utf-8")
        self._git("add", "--", "f.txt")

        raw_diff = self._git("diff", "--cached")
        self.assertNotIn("@@@", raw_diff)  # verified real behavior, see comment above

        result = self._run_checker(self._denylist_env(_SYNTHETIC_NAME))

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("f.txt:1:", result.stderr)
        self.assertIn("denylisted private repository name", result.stderr)

    # -- adjacent-added-line join closes the line-split gap (decision 3) ----

    def test_denylisted_name_split_across_two_added_lines_blocks(self):
        # Neither line matches on its own; only the no-separator join of the
        # two contiguous added lines reconstructs the name (mid-token wrap).
        self._stage(
            "docs/notes.md",
            "prefix zzz-quokka-\nvault suffix\n",
        )

        result = self._run_checker(self._denylist_env(_SYNTHETIC_NAME))

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("split across two added lines", result.stderr)

    def test_multiword_denylisted_name_split_across_two_added_lines_blocks(self):
        # Neither line matches alone; only the space-joined candidate
        # reconstructs a multi-word denylist entry reflowed across the break.
        self._stage("docs/notes.md", "See the acme\ncorp report.\n")

        result = self._run_checker(self._denylist_env("acme corp"))

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("split across two added lines", result.stderr)

    def test_context_line_between_added_lines_prevents_join(self):
        # Same two half-strings as the no-separator-join test above, but now
        # separated by an untouched context line -- they must NOT be joined.
        self._commit("docs/notes.md", "line1\ntarget\nline3\n", "seed")
        (self.repo / "docs" / "notes.md").write_text(
            "line1\nprefix zzz-quokka-\ntarget\nvault suffix\nline3\n", encoding="utf-8"
        )
        self._git("add", "--", "docs/notes.md")

        result = self._run_checker(self._denylist_env(_SYNTHETIC_NAME))

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_line_that_already_fired_alone_is_not_also_reported_via_join(self):
        # Each line already fires on its own (a home path, then a
        # denylisted name) -- the adjacent-line join must not additionally
        # report a "split across two added lines" triplicate for either.
        self._stage(
            "docs/plan.md",
            f"cd /Users/exampleuser/Developer/thing\n{_SYNTHETIC_NAME} appears too\n",  # raven-hygiene: allow
        )

        result = self._run_checker(self._denylist_env(_SYNTHETIC_NAME))

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertNotIn("split across two added lines", result.stderr)

    # -- clean/empty staged diff is a trivial pass ---------------------------

    def test_empty_staged_diff_passes(self):
        self._commit("README.md", "# repo\n", "init")

        result = self._run_checker()

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stderr, "")


if __name__ == "__main__":
    unittest.main()
