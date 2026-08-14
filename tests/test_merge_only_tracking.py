"""Tests for #216: a merge-only path that git does not track is reported.

Raven merges ``MERGE_ONLY_TEMPLATE_PATHS`` into files it does not own, so they
are deliberately absent from ``manifest.json`` and appear in no manifest-driven
listing. Git also honors a working-tree ``.gitattributes`` whether or not it is
tracked, so such a file works locally while reaching no other clone. Nothing
surfaced that state before this check.

The untracked case is driven off ``MERGE_ONLY_TEMPLATE_PATHS`` rather than a
hardcoded ``.gitattributes``, so a merge-only path added later is covered
without editing this file. The negative cases (not a git repo, deliberately
gitignored) are the false positives that would make the check noise.
"""

from __future__ import annotations

import contextlib
import io
import subprocess
import tempfile
import unittest
from pathlib import Path

from helpers import RavenTestCase, raven

MERGE_ONLY_PATHS = sorted(raven.MERGE_ONLY_TEMPLATE_PATHS)


class UntrackedMergeOnlyPathTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.destination = Path(self.tmp.name)

    def _git(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", "-C", str(self.destination), *args],
            capture_output=True,
            text=True,
            check=True,
        )

    def _init_repo(self) -> None:
        self._git("init", "-q")
        self._git("config", "user.email", "test@example.invalid")
        self._git("config", "user.name", "Test")

    def _write(self, relative: str, text: str = "* text=auto\n") -> Path:
        path = self.destination / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def test_every_merge_only_path_is_reported_when_present_but_untracked(self):
        self.assertTrue(MERGE_ONLY_PATHS, "expected at least one merge-only path to exercise this")
        self._init_repo()
        for relative in MERGE_ONLY_PATHS:
            self._write(relative)

        self.assertEqual(raven.untracked_merge_only_paths(self.destination), MERGE_ONLY_PATHS)

    def test_a_tracked_path_is_not_reported(self):
        self._init_repo()
        for relative in MERGE_ONLY_PATHS:
            self._write(relative)
            self._git("add", "--", relative)

        self.assertEqual(raven.untracked_merge_only_paths(self.destination), [])

    def test_a_path_absent_from_disk_is_not_reported(self):
        self._init_repo()

        self.assertEqual(raven.untracked_merge_only_paths(self.destination), [])

    def test_a_destination_that_is_not_a_git_repository_is_not_reported(self):
        # No `git init` -- Raven installs into plain directories too, and a
        # tracking complaint there is meaningless.
        for relative in MERGE_ONLY_PATHS:
            self._write(relative)

        self.assertEqual(raven.untracked_merge_only_paths(self.destination), [])

    def test_a_deliberately_gitignored_path_is_not_reported(self):
        self._init_repo()
        (self.destination / ".gitignore").write_text(
            "".join(f"{relative}\n" for relative in MERGE_ONLY_PATHS), encoding="utf-8"
        )
        for relative in MERGE_ONLY_PATHS:
            self._write(relative)

        self.assertEqual(raven.untracked_merge_only_paths(self.destination), [])

    def test_a_bare_repository_is_not_reported(self):
        # `rev-parse --is-inside-work-tree` says "false" for a bare repo; there
        # is no work tree for a merge-only path to sit untracked in.
        self._git("init", "-q", "--bare")

        self.assertEqual(raven.untracked_merge_only_paths(self.destination), [])


class MergeOnlyTrackingFindingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.destination = Path(self.tmp.name)
        subprocess.run(
            ["git", "-C", str(self.destination), "init", "-q"],
            capture_output=True,
            check=True,
        )

    def test_untracked_path_produces_a_warn_finding_naming_the_path(self):
        for relative in MERGE_ONLY_PATHS:
            (self.destination / relative).write_text("* text=auto\n", encoding="utf-8")

        findings = raven.merge_only_tracking_findings(self.destination)

        self.assertEqual(len(findings), 1)
        finding = findings[0]
        self.assertIs(finding.severity, raven.Severity.WARN)
        for relative in MERGE_ONLY_PATHS:
            self.assertIn(relative, finding.title)
        self.assertIsNotNone(finding.fix)

    def test_no_finding_when_nothing_is_untracked(self):
        self.assertEqual(raven.merge_only_tracking_findings(self.destination), [])


class InstallReportsUntrackedMergeOnlyPathTests(RavenTestCase):
    """The install/upgrade run that *creates* the file is the first chance to say so."""

    def _install(self) -> str:
        with contextlib.redirect_stdout(io.StringIO()) as out:
            rc = raven._run(
                self.destination,
                raven.load_config(self.destination),
                "python",
                False,
                False,
                [],
            )
        self.assertEqual(rc, 0, out.getvalue())
        return out.getvalue()

    def test_install_into_a_git_repo_reports_the_untracked_path(self):
        subprocess.run(
            ["git", "-C", str(self.destination), "init", "-q"], capture_output=True, check=True
        )

        output = self._install()

        self.assertIn("Not tracked by git", output)
        self.assertIn(".gitattributes", output)

    def test_install_into_a_plain_directory_reports_nothing(self):
        # No git repository, so no tracking claim to make.
        output = self._install()

        self.assertNotIn("Not tracked by git", output)


if __name__ == "__main__":
    unittest.main()
