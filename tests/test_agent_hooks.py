import json
import subprocess
import sys
import unittest

from helpers import REPO_ROOT, RavenTestCase


class AgentHooksTests(RavenTestCase):
    def test_hooks_tolerate_null_tool_input(self):
        hooks = [
            "raven-post-bash-summarize.py",
            "raven-pre-bash-guard.py",
            "raven-pre-edit-guard.py",
            "raven-post-edit-format.py",
        ]
        payload = json.dumps({"tool_input": None})

        for hook in hooks:
            with self.subTest(hook=hook):
                result = subprocess.run(
                    [sys.executable, str(REPO_ROOT / "common" / ".claude" / "hooks" / hook)],
                    input=payload,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_hooks_tolerate_non_dict_tool_input(self):
        hooks = [
            "raven-post-bash-summarize.py",
            "raven-pre-bash-guard.py",
            "raven-pre-edit-guard.py",
            "raven-post-edit-format.py",
        ]
        payload = json.dumps({"tool_input": "unexpected"})

        for hook in hooks:
            with self.subTest(hook=hook):
                result = subprocess.run(
                    [sys.executable, str(REPO_ROOT / "common" / ".claude" / "hooks" / hook)],
                    input=payload,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_codex_pre_hooks_emit_deny_payload_for_blocked_actions(self):
        cases = [
            (
                "raven-pre-bash-guard.py",
                {
                    "hook_event_name": "PreToolUse",
                    "tool_name": "Bash",
                    "tool_input": {"command": "git reset --hard"},
                },
            ),
            (
                "raven-pre-edit-guard.py",
                {
                    "hook_event_name": "PreToolUse",
                    "tool_name": "apply_patch",
                    "tool_input": {"file_path": ".env"},
                },
            ),
        ]

        for hook, payload in cases:
            with self.subTest(hook=hook):
                result = subprocess.run(
                    [sys.executable, str(REPO_ROOT / "common" / ".codex" / "hooks" / hook)],
                    input=json.dumps(payload),
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                response = json.loads(result.stdout)
                decision = response["hookSpecificOutput"]
                self.assertEqual(decision["hookEventName"], "PreToolUse")
                self.assertEqual(decision["permissionDecision"], "deny")


if __name__ == "__main__":
    unittest.main()
