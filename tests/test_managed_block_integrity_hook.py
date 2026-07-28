from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from helpers import REPO_ROOT, raven


class ManagedBlockIntegrityHookTests(unittest.TestCase):
    SCRIPT_PATH = (
        REPO_ROOT / "common" / ".raven" / "git-hooks" / "lib" / "check-managed-block-integrity.py"
    )

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name)
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)

    def _write(self, path: str, content: str) -> None:
        (self.repo / path).write_text(content, encoding="utf-8")

    def _symlink(self, path: str, target: str) -> None:
        (self.repo / path).symlink_to(target)

    def _stage(self, path: str) -> None:
        subprocess.run(["git", "add", "--", path], cwd=str(self.repo), check=True)

    def _stage_deletion(self, path: str) -> None:
        """Stage removal of an already-staged path, leaving the worktree file in place."""
        subprocess.run(["git", "rm", "-q", "--cached", "--", path], cwd=str(self.repo), check=True)

    def _run(self) -> tuple[int, str]:
        result = subprocess.run(
            [sys.executable, str(self.SCRIPT_PATH)],
            capture_output=True,
            text=True,
            cwd=str(self.repo),
        )
        return result.returncode, result.stderr

    def test_allows_unmodified_managed_block(self):
        self._write("AGENTS.md", raven.raven_managed_block("# Guidance\n"))
        self._stage("AGENTS.md")
        rc, _ = self._run()
        self.assertEqual(rc, 0)

    def test_blocks_directly_edited_managed_block(self):
        block = raven.raven_managed_block("# Guidance\n")
        tampered = block.replace("# Guidance", "# Guidance (hand-edited)")
        self._write("AGENTS.md", tampered)
        self._stage("AGENTS.md")
        rc, err = self._run()
        self.assertEqual(rc, 1)
        self.assertIn("AGENTS.md", err)
        self.assertIn("edited directly", err)

    def test_allows_file_with_no_managed_block(self):
        self._write("AGENTS.md", "# Plain guidance, no managed block\n")
        self._stage("AGENTS.md")
        rc, _ = self._run()
        self.assertEqual(rc, 0)

    def test_skips_symlinked_claude_md(self):
        block = raven.raven_managed_block("# Guidance\n")
        tampered = block.replace("# Guidance", "# Guidance (hand-edited)")
        self._write("AGENTS.md", tampered)
        self._stage("AGENTS.md")
        self._symlink("CLAUDE.md", "AGENTS.md")
        self._stage("CLAUDE.md")
        # AGENTS.md itself is still tampered, so this should still fail --
        # this test only proves the symlink target isn't double-reported.
        rc, err = self._run()
        self.assertEqual(rc, 1)
        self.assertEqual(err.count("edited directly"), 1)

    def test_checks_claude_md_when_it_is_a_real_file(self):
        block = raven.raven_managed_block("# Guidance\n")
        tampered = block.replace("# Guidance", "# Guidance (hand-edited)")
        self._write("CLAUDE.md", tampered)
        self._stage("CLAUDE.md")
        rc, err = self._run()
        self.assertEqual(rc, 1)
        self.assertIn("CLAUDE.md", err)

    def test_blocks_staged_tamper_even_when_worktree_is_restored(self):
        # Regression guard for the index-vs-worktree bypass: tamper the block,
        # stage it, then restore the working copy to valid text (e.g. as
        # `raven upgrade` would). The staged content -- what would actually be
        # committed -- is still tampered, so the hook must still fail.
        valid = raven.raven_managed_block("# Guidance\n")
        tampered = valid.replace("# Guidance", "# Guidance (hand-edited)")
        self._write("AGENTS.md", tampered)
        self._stage("AGENTS.md")
        self._write("AGENTS.md", valid)
        rc, err = self._run()
        self.assertEqual(rc, 1)
        self.assertIn("AGENTS.md", err)
        self.assertIn("edited directly", err)

    def test_allows_staged_valid_block_even_when_worktree_is_tampered(self):
        # Mirror of the regression guard: the index holds a valid block, only
        # the on-disk copy is tampered. The commit itself is clean, so the
        # hook must pass -- proving it checks the index rather than the
        # worktree (or both).
        valid = raven.raven_managed_block("# Guidance\n")
        tampered = valid.replace("# Guidance", "# Guidance (hand-edited)")
        self._write("AGENTS.md", valid)
        self._stage("AGENTS.md")
        self._write("AGENTS.md", tampered)
        rc, _ = self._run()
        self.assertEqual(rc, 0)

    def test_skips_file_absent_from_index(self):
        # Present on disk, tampered, but never staged: nothing under this
        # name is being committed, so the hook must not fail on it.
        block = raven.raven_managed_block("# Guidance\n")
        tampered = block.replace("# Guidance", "# Guidance (hand-edited)")
        self._write("AGENTS.md", tampered)
        rc, _ = self._run()
        self.assertEqual(rc, 0)

    def test_skips_staged_deletion(self):
        block = raven.raven_managed_block("# Guidance\n")
        tampered = block.replace("# Guidance", "# Guidance (hand-edited)")
        self._write("AGENTS.md", tampered)
        self._stage("AGENTS.md")
        self._stage_deletion("AGENTS.md")
        rc, _ = self._run()
        self.assertEqual(rc, 0)

    def test_script_is_executable(self):
        self.assertTrue(self.SCRIPT_PATH.stat().st_mode & 0o111)


if __name__ == "__main__":
    unittest.main()
