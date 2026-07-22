from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from helpers import REPO_ROOT


def _attribution_line(tool: str, verb: str = "Generated", prep: str = "by") -> str:
    # Built at runtime, not written as one literal string, so this test file's
    # own source never contains the exact phrase the hook under test blocks --
    # the AI-attribution content scan runs on this repo too (see pre-commit).
    return f"# {verb} {prep} {tool}\n"


class AiAttributionContentHookTests(unittest.TestCase):
    SCRIPT_PATH = (
        REPO_ROOT / "common" / ".raven" / "git-hooks" / "lib" / "check-ai-attribution-content.py"
    )

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name)
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        subprocess.run(
            ["git", "-C", str(self.repo), "config", "user.email", "t@example.com"], check=True
        )
        subprocess.run(["git", "-C", str(self.repo), "config", "user.name", "Test"], check=True)

    def _commit(self, path: str, content: str, message: str = "commit") -> None:
        file_path = self.repo / path
        file_path.write_text(content, encoding="utf-8")
        subprocess.run(["git", "-C", str(self.repo), "add", path], check=True)
        subprocess.run(["git", "-C", str(self.repo), "commit", "-q", "-m", message], check=True)

    def _stage(self, path: str, content: str) -> None:
        (self.repo / path).write_text(content, encoding="utf-8")
        subprocess.run(["git", "-C", str(self.repo), "add", path], check=True)

    def _run(self, mode: str, config_text: str | None = None) -> tuple[int, str]:
        if config_text is not None:
            raven_dir = self.repo / ".raven"
            raven_dir.mkdir(exist_ok=True)
            (raven_dir / "config.toml").write_text(config_text, encoding="utf-8")
        result = subprocess.run(
            [sys.executable, str(self.SCRIPT_PATH), mode],
            capture_output=True,
            text=True,
            cwd=str(self.repo),
        )
        return result.returncode, result.stderr

    def test_blocks_staged_content_mentioning_claude(self):
        self._commit("README.md", "# repo\n")
        self._stage("notes.py", _attribution_line("Claude") + "print('hi')\n")
        rc, err = self._run("staged")
        self.assertEqual(rc, 1)
        self.assertIn("staged diff", err)

    def test_allows_staged_clean_content(self):
        self._commit("README.md", "# repo\n")
        self._stage("notes.py", "# written by the platform team\nprint('hi')\n")
        rc, _ = self._run("staged")
        self.assertEqual(rc, 0)

    def test_outbound_blocks_content_against_origin_main(self):
        self._commit("README.md", "# repo\n")
        base_sha = subprocess.run(
            ["git", "-C", str(self.repo), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        subprocess.run(
            ["git", "-C", str(self.repo), "update-ref", "refs/remotes/origin/main", base_sha],
            check=True,
        )
        self._commit(
            "notes.py",
            _attribution_line("Copilot", verb="Implemented", prep="with") + "print('hi')\n",
        )
        rc, err = self._run("outbound")
        self.assertEqual(rc, 1)
        self.assertIn("origin/main..HEAD", err)

    def test_outbound_allows_clean_content(self):
        self._commit("README.md", "# repo\n")
        base_sha = subprocess.run(
            ["git", "-C", str(self.repo), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        subprocess.run(
            ["git", "-C", str(self.repo), "update-ref", "refs/remotes/origin/main", base_sha],
            check=True,
        )
        self._commit("notes.py", "print('hi')\n")
        rc, _ = self._run("outbound")
        self.assertEqual(rc, 0)

    def test_outbound_skips_when_no_base_ref(self):
        self._commit("notes.py", _attribution_line("Claude") + "print('hi')\n")
        rc, _ = self._run("outbound")
        self.assertEqual(rc, 0)

    def test_respects_block_ai_attribution_content_false_in_config(self):
        self._commit("README.md", "# repo\n")
        self._stage("notes.py", _attribution_line("Claude") + "print('hi')\n")
        rc, _ = self._run(
            "staged", config_text="[git_hooks]\nblock_ai_attribution_content = false\n"
        )
        self.assertEqual(rc, 0)

    def test_default_blocks_when_no_config(self):
        self._commit("README.md", "# repo\n")
        self._stage("notes.py", _attribution_line("Claude") + "print('hi')\n")
        rc, _ = self._run("staged")
        self.assertEqual(rc, 1)

    def test_script_is_executable(self):
        self.assertTrue(self.SCRIPT_PATH.stat().st_mode & 0o111)


if __name__ == "__main__":
    unittest.main()
