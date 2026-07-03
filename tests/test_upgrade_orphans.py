"""End-to-end coverage for issue #97 Task 3: orphan handling wired into
``raven upgrade``.

These tests drive the real ``cmd_install``/``cmd_upgrade`` CLI entry points
(the same harness ``tests/test_installer_safety.py`` uses) against a
throwaway, single-use language template rather than the real ``python``
template under ``REPO_ROOT``: the real template is immutable and these tests
need to remove a file from the template between install and upgrade to
simulate "the template no longer ships this file".
"""

from __future__ import annotations

import argparse
import contextlib
import io
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from helpers import RavenTestCase, raven
from raven_lib.manifest import load_manifest


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _install_ns(destination: Path, *, language: str) -> argparse.Namespace:
    return argparse.Namespace(
        destination=str(destination),
        language=language,
        args=None,
        overrides=[],
        dry_run=False,
        include_readme=False,
        adopt_claude_symlink=False,
        platform=None,
    )


def _upgrade_ns(destination: Path) -> argparse.Namespace:
    return argparse.Namespace(
        destination=str(destination),
        overrides=[],
        dry_run=False,
        include_readme=False,
        adopt_claude_symlink=False,
    )


class UpgradeOrphanTests(RavenTestCase):
    def setUp(self) -> None:
        super().setUp()
        # A fake REPO_ROOT containing one throwaway language template
        # ("lang"), so the test can delete a file from it between install
        # and upgrade without touching the real, immutable python template.
        self._fake_repo_tmp = TemporaryDirectory()
        self.addCleanup(self._fake_repo_tmp.cleanup)
        self.fake_repo_root = Path(self._fake_repo_tmp.name)
        self.template_dir = self.fake_repo_root / "lang"
        _write(self.template_dir / "AGENTS.md", "root instructions\n")
        _write(self.template_dir / "docs" / "dropped.md", "shipped content\n")
        patcher = mock.patch("raven_lib.cli.REPO_ROOT", self.fake_repo_root)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _install(self) -> None:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            rc = raven.cmd_install(_install_ns(self.destination, language="lang"))
        self.assertEqual(rc, 0)

    def _upgrade(self) -> tuple[int, str]:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
            rc = raven.cmd_upgrade(_upgrade_ns(self.destination))
        return rc, buf.getvalue()

    def test_clean_orphan_removed_and_reported(self) -> None:
        self._install()
        dropped = self.destination / "docs" / "dropped.md"
        self.assertTrue(dropped.exists())
        self.assertIn("docs/dropped.md", load_manifest(self.destination)["files"])

        # Template stops shipping docs/dropped.md.
        (self.template_dir / "docs" / "dropped.md").unlink()

        rc, output = self._upgrade()
        self.assertEqual(rc, 0)
        self.assertFalse(dropped.exists())
        self.assertNotIn("docs/dropped.md", load_manifest(self.destination)["files"])
        self.assertIn("Removed 1 orphaned file(s)", output)
        self.assertIn("docs/dropped.md", output)

    def test_modified_orphan_kept_and_reported(self) -> None:
        self._install()
        dropped = self.destination / "docs" / "dropped.md"
        dropped.write_text("user edited this locally\n", encoding="utf-8")

        (self.template_dir / "docs" / "dropped.md").unlink()

        rc, output = self._upgrade()
        self.assertEqual(rc, 0)
        self.assertTrue(dropped.exists())
        self.assertEqual(dropped.read_text(encoding="utf-8"), "user edited this locally\n")
        # A locally modified orphan keeps its manifest record; it was never
        # removed, so there is nothing stale to prune.
        self.assertIn("docs/dropped.md", load_manifest(self.destination)["files"])
        self.assertIn(
            "Orphaned but left in place because you modified them",
            output,
        )
        self.assertIn("docs/dropped.md", output)

    def test_existing_starter_config_never_removed(self) -> None:
        from raven_lib.constants import STARTER_TOOL_CONFIG_PATHS

        starter = sorted(STARTER_TOOL_CONFIG_PATHS)[0]
        _write(self.template_dir / starter, "shipped\n")
        self._install()
        starter_path = self.destination / starter
        self.assertTrue(starter_path.exists())
        self.assertIn(starter, load_manifest(self.destination)["files"])

        # Upgrade against the same (full) template: the starter config is
        # still shipped, so it must never be classified as an orphan, let
        # alone removed.
        rc, output = self._upgrade()
        self.assertEqual(rc, 0)
        self.assertTrue(starter_path.exists())
        self.assertEqual(starter_path.read_text(encoding="utf-8"), "shipped\n")
        self.assertIn(starter, load_manifest(self.destination)["files"])
        self.assertNotIn("Removed", output)


if __name__ == "__main__":
    unittest.main()
