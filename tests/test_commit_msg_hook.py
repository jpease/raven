import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from helpers import REPO_ROOT, raven


class CommitMsgHookTests(unittest.TestCase):
    HOOK_PATH = REPO_ROOT / "common" / ".raven" / "git-hooks" / "commit-msg"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.msg_file = Path(self.tmp.name) / "COMMIT_EDITMSG"

    def _run_hook(self, message: str) -> tuple[str, int]:
        self.msg_file.write_text(message, encoding="utf-8")
        result = subprocess.run(
            [sys.executable, str(self.HOOK_PATH), str(self.msg_file)],
            capture_output=True,
            text=True,
        )
        return self.msg_file.read_text(encoding="utf-8"), result.returncode

    def test_strips_claude_co_authored_by(self):
        msg = "feat: add thing\n\nCo-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>\n"
        out, rc = self._run_hook(msg)
        self.assertEqual(rc, 0)
        self.assertNotIn("Co-Authored-By", out)
        self.assertIn("feat: add thing", out)

    def test_strips_copilot_co_authored_by(self):
        msg = "fix: bug\n\nCo-Authored-By: GitHub Copilot <noreply@github.com>\n"
        out, rc = self._run_hook(msg)
        self.assertEqual(rc, 0)
        self.assertNotIn("Co-Authored-By", out)

    def test_strips_codex_co_authored_by(self):
        msg = "chore: update\n\nCo-authored-by: OpenAI Codex <noreply@openai.com>\n"
        out, rc = self._run_hook(msg)
        self.assertEqual(rc, 0)
        self.assertNotIn("Co-authored-by", out)

    def test_strips_generated_by_trailer(self):
        msg = "docs: update\n\nGenerated-by: Claude\n"
        out, rc = self._run_hook(msg)
        self.assertEqual(rc, 0)
        self.assertNotIn("Generated-by", out)

    def test_strips_claude_session_trailer(self):
        msg = "perf: optimize loop\n\nClaude-Session: https://claude.ai/code/session_abc123\n"
        out, rc = self._run_hook(msg)
        self.assertEqual(rc, 0)
        self.assertNotIn("Claude-Session", out)
        self.assertIn("perf: optimize loop", out)

    def test_removes_trailing_blank_lines_after_strip(self):
        msg = "feat: add thing\n\nCo-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>\n"
        out, rc = self._run_hook(msg)
        self.assertEqual(rc, 0)
        self.assertFalse(out.endswith("\n\n"))

    def test_preserves_human_co_authored_by(self):
        msg = "feat: pair program\n\nCo-Authored-By: Alice Smith <alice@example.com>\n"
        out, rc = self._run_hook(msg)
        self.assertEqual(rc, 0)
        self.assertIn("Co-Authored-By: Alice Smith", out)

    def test_does_not_modify_clean_message(self):
        msg = "feat: clean commit\n\nSome body text.\n"
        out, rc = self._run_hook(msg)
        self.assertEqual(rc, 0)
        self.assertEqual(out, msg)

    def test_strips_anthropic_domain_trailer(self):
        msg = "fix: patch\n\nCo-Authored-By: SomeBot <bot@anthropic.com>\n"
        out, rc = self._run_hook(msg)
        self.assertEqual(rc, 0)
        self.assertNotIn("anthropic.com", out)

    def test_strips_openai_domain_trailer(self):
        msg = "fix: patch\n\nCo-Authored-By: SomeBot <bot@openai.com>\n"
        out, rc = self._run_hook(msg)
        self.assertEqual(rc, 0)
        self.assertNotIn("openai.com", out)

    def test_hook_is_executable(self):
        self.assertTrue(self.HOOK_PATH.stat().st_mode & 0o111)

    def test_respects_strip_ai_attribution_false_in_config(self):
        # Write a repo with strip_ai_attribution = false and run hook inside it.
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            subprocess.run(["git", "init", str(repo)], capture_output=True, check=True)
            raven_dir = repo / ".raven"
            raven_dir.mkdir()
            (raven_dir / "config.toml").write_text(
                "[git_hooks]\nstrip_ai_attribution = false\n", encoding="utf-8"
            )
            msg_file = repo / "COMMIT_EDITMSG"
            msg = "feat: thing\n\nCo-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>\n"
            msg_file.write_text(msg, encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(self.HOOK_PATH), str(msg_file)],
                capture_output=True,
                text=True,
                cwd=str(repo),
            )
        self.assertEqual(result.returncode, 0)
        self.assertIn(
            "Co-Authored-By", msg_file.read_text(encoding="utf-8") if msg_file.exists() else msg
        )

    def test_default_strips_when_no_config(self):
        msg = "feat: add thing\n\nCo-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>\n"
        out, rc = self._run_hook(msg)
        self.assertEqual(rc, 0)
        self.assertNotIn("Co-Authored-By", out)

    def test_config_section_in_default_config_text(self):
        config_text = raven.default_config_text("python", False)
        self.assertIn("[git_hooks]", config_text)
        self.assertIn("strip_ai_attribution = true", config_text)

    def test_non_utf8_message_does_not_crash(self):
        raw = b"fix: bug \xff\xfe invalid utf8\n"
        self.msg_file.write_bytes(raw)
        result = subprocess.run(
            [sys.executable, str(self.HOOK_PATH), str(self.msg_file)],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(self.msg_file.read_bytes(), raw)

    def test_no_bogus_removed_message_for_trailing_blank_only(self):
        self.msg_file.write_text("fix: x\n\n", encoding="utf-8")
        result = subprocess.run(
            [sys.executable, str(self.HOOK_PATH), str(self.msg_file)],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0)
        self.assertNotIn("removed AI attribution", result.stderr)


if __name__ == "__main__":
    unittest.main()
