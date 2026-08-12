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

    def _git(self, *args: str) -> str:
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
            check=True,
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

    # -- generated/vendored exclusion --------------------------------------

    def test_uv_lock_is_excluded_from_scanning(self):
        self._stage(
            "uv.lock",
            "# generated\npath = /Users/exampleuser/Developer/thing\n",  # raven-hygiene: allow
        )

        result = self._run_checker()

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

    # -- clean/empty staged diff is a trivial pass ---------------------------

    def test_empty_staged_diff_passes(self):
        self._commit("README.md", "# repo\n", "init")

        result = self._run_checker()

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stderr, "")


if __name__ == "__main__":
    unittest.main()
