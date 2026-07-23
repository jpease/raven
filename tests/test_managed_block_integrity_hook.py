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
        rc, _ = self._run()
        self.assertEqual(rc, 0)

    def test_blocks_directly_edited_managed_block(self):
        block = raven.raven_managed_block("# Guidance\n")
        tampered = block.replace("# Guidance", "# Guidance (hand-edited)")
        self._write("AGENTS.md", tampered)
        rc, err = self._run()
        self.assertEqual(rc, 1)
        self.assertIn("AGENTS.md", err)
        self.assertIn("edited directly", err)

    def test_allows_file_with_no_managed_block(self):
        self._write("AGENTS.md", "# Plain guidance, no managed block\n")
        rc, _ = self._run()
        self.assertEqual(rc, 0)

    def test_skips_symlinked_claude_md(self):
        block = raven.raven_managed_block("# Guidance\n")
        tampered = block.replace("# Guidance", "# Guidance (hand-edited)")
        self._write("AGENTS.md", tampered)
        self._symlink("CLAUDE.md", "AGENTS.md")
        # AGENTS.md itself is still tampered, so this should still fail --
        # this test only proves the symlink target isn't double-reported.
        rc, err = self._run()
        self.assertEqual(rc, 1)
        self.assertEqual(err.count("edited directly"), 1)

    def test_checks_claude_md_when_it_is_a_real_file(self):
        block = raven.raven_managed_block("# Guidance\n")
        tampered = block.replace("# Guidance", "# Guidance (hand-edited)")
        self._write("CLAUDE.md", tampered)
        rc, err = self._run()
        self.assertEqual(rc, 1)
        self.assertIn("CLAUDE.md", err)

    def test_script_is_executable(self):
        self.assertTrue(self.SCRIPT_PATH.stat().st_mode & 0o111)


if __name__ == "__main__":
    unittest.main()
