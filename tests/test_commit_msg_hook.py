from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from helpers import REPO_ROOT, install_raven_config_lib, raven


def _install_hook_into(repo: Path) -> Path:
    """Copy the commit-msg hook (and its raven_config.py sibling) into `repo`.

    _repo_root() (issue #202) is install-layout-derived from the hook's own
    __file__, not the process cwd -- so a test exercising a fixture repo's
    config must run a copy of the hook installed at the same relative
    offset (``.raven/git-hooks/commit-msg``) a real install would use, or
    _repo_root() resolves to this checkout's own tree instead of the
    fixture. Returns the installed hook's path.
    """
    hooks_dir = repo / ".raven" / "git-hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    installed = hooks_dir / "commit-msg"
    shutil.copy2(REPO_ROOT / "common" / ".raven" / "git-hooks" / "commit-msg", installed)
    install_raven_config_lib(repo)
    return installed


class CommitMsgHookTests(unittest.TestCase):
    HOOK_PATH = REPO_ROOT / "common" / ".raven" / "git-hooks" / "commit-msg"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name)
        subprocess.run(["git", "init", "-q", str(self.repo)], capture_output=True, check=True)
        self.installed_hook = _install_hook_into(self.repo)
        self.msg_file = self.repo / "COMMIT_EDITMSG"

    def _run_hook(self, message: str) -> tuple[str, int]:
        self.msg_file.write_text(message, encoding="utf-8")
        result = subprocess.run(
            [sys.executable, str(self.installed_hook), str(self.msg_file)],
            capture_output=True,
            text=True,
            cwd=str(self.repo),
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

    def test_strips_unlisted_bot_with_noreply_address(self):
        msg = "feat: add thing\n\nCo-Authored-By: SomeNewAI <noreply@newai.dev>\n"
        out, rc = self._run_hook(msg)
        self.assertEqual(rc, 0)
        self.assertNotIn("Co-Authored-By", out)

    def test_preserves_github_human_co_author_suggestion(self):
        # GitHub's own "co-author" suggestion for human collaborators uses
        # <id+username@users.noreply.github.com>, which does not start with
        # the literal "noreply@" the bot heuristic matches.
        msg = "feat: pair program\n\nCo-Authored-By: Bob <12345+bob@users.noreply.github.com>\n"
        out, rc = self._run_hook(msg)
        self.assertEqual(rc, 0)
        self.assertIn("Co-Authored-By: Bob", out)

    def test_hook_is_executable(self):
        self.assertTrue(self.HOOK_PATH.stat().st_mode & 0o111)

    def test_respects_strip_ai_attribution_false_in_config(self):
        # Write a repo with strip_ai_attribution = false and run hook inside it.
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            subprocess.run(["git", "init", str(repo)], capture_output=True, check=True)
            installed_hook = _install_hook_into(repo)
            raven_dir = repo / ".raven"
            (raven_dir / "config.toml").write_text(
                "[git_hooks]\nstrip_ai_attribution = false\n", encoding="utf-8"
            )
            msg_file = repo / "COMMIT_EDITMSG"
            msg = "feat: thing\n\nCo-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>\n"
            msg_file.write_text(msg, encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(installed_hook), str(msg_file)],
                capture_output=True,
                text=True,
                cwd=str(repo),
            )
        self.assertEqual(result.returncode, 0)
        self.assertIn(
            "Co-Authored-By", msg_file.read_text(encoding="utf-8") if msg_file.exists() else msg
        )

    def _run_in_repo(self, config_text: str | None) -> tuple[int, str]:
        """Run the hook against a fresh repo, optionally with a .raven/config.toml."""
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            subprocess.run(["git", "init", str(repo)], capture_output=True, check=True)
            installed_hook = _install_hook_into(repo)
            if config_text is not None:
                (repo / ".raven" / "config.toml").write_text(config_text, encoding="utf-8")
            msg_file = repo / "COMMIT_EDITMSG"
            msg = "feat: thing\n\nCo-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>\n"
            msg_file.write_text(msg, encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(installed_hook), str(msg_file)],
                capture_output=True,
                text=True,
                cwd=str(repo),
            )
            return result.returncode, msg_file.read_text(encoding="utf-8")

    def test_wrong_typed_value_falls_back_to_default_strip(self):
        rc, out = self._run_in_repo('[git_hooks]\nstrip_ai_attribution = "maybe"\n')
        self.assertEqual(rc, 0)
        self.assertNotIn("Co-Authored-By", out)

    def test_uppercase_false_still_disables_stripping(self):
        # Pre-#201, this hook's own _BOOL_RE matched true/false via
        # re.IGNORECASE, so an uppercase FALSE already worked here. The
        # shared parser's parse_bool must stay case-insensitive too, or this
        # silently reverts to the strip-on default without ever raising.
        rc, out = self._run_in_repo("[git_hooks]\nstrip_ai_attribution = FALSE\n")
        self.assertEqual(rc, 0)
        self.assertIn("Co-Authored-By", out)

    def test_missing_section_falls_back_to_default_strip(self):
        rc, out = self._run_in_repo("[other]\nstrip_ai_attribution = false\n")
        self.assertEqual(rc, 0)
        self.assertNotIn("Co-Authored-By", out)

    def test_unreadable_config_does_not_crash_and_falls_back_to_default_strip(self):
        # Pre-existing gap (issue #201): an unreadable-but-present config used
        # to propagate an uncaught OSError out of the hook. Fixed to fail
        # safe (fall back to the default) instead of crashing the commit.
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            subprocess.run(["git", "init", str(repo)], capture_output=True, check=True)
            installed_hook = _install_hook_into(repo)
            config = repo / ".raven" / "config.toml"
            config.write_text("[git_hooks]\nstrip_ai_attribution = false\n", encoding="utf-8")
            config.chmod(0o000)
            msg_file = repo / "COMMIT_EDITMSG"
            msg = "feat: thing\n\nCo-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>\n"
            msg_file.write_text(msg, encoding="utf-8")
            try:
                result = subprocess.run(
                    [sys.executable, str(installed_hook), str(msg_file)],
                    capture_output=True,
                    text=True,
                    cwd=str(repo),
                )
            finally:
                config.chmod(0o644)
            out = msg_file.read_text(encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("Co-Authored-By", out)

    def test_default_strips_when_no_config(self):
        msg = "feat: add thing\n\nCo-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>\n"
        out, rc = self._run_hook(msg)
        self.assertEqual(rc, 0)
        self.assertNotIn("Co-Authored-By", out)

    def test_config_section_in_default_config_text(self):
        config_text = raven.default_config_text("python", False)
        self.assertIn("[git_hooks]", config_text)
        self.assertIn("strip_ai_attribution = true", config_text)
        self.assertIn("block_ai_attribution_content = true", config_text)

    def test_non_utf8_message_does_not_crash(self):
        raw = b"fix: bug \xff\xfe invalid utf8\n"
        self.msg_file.write_bytes(raw)
        result = subprocess.run(
            [sys.executable, str(self.installed_hook), str(self.msg_file)],
            capture_output=True,
            text=True,
            cwd=str(self.repo),
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(self.msg_file.read_bytes(), raw)

    def test_no_bogus_removed_message_for_trailing_blank_only(self):
        self.msg_file.write_text("fix: x\n\n", encoding="utf-8")
        result = subprocess.run(
            [sys.executable, str(self.installed_hook), str(self.msg_file)],
            capture_output=True,
            text=True,
            cwd=str(self.repo),
        )
        self.assertEqual(result.returncode, 0)
        self.assertNotIn("removed AI attribution", result.stderr)


if __name__ == "__main__":
    unittest.main()
