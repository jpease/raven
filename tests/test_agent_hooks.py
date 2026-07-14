import json
import subprocess
import sys
import unittest

from helpers import REPO_ROOT, RavenTestCase

CLAUDE_BASH_GUARD = REPO_ROOT / "common" / ".claude" / "hooks" / "raven-pre-bash-guard.py"
CODEX_BASH_GUARD = REPO_ROOT / "common" / ".codex" / "hooks" / "raven-pre-bash-guard.py"

# Commands that MUST be denied for the three destructive intents, across every
# option spelling (combined, split, reordered, long-option).
DENIED_BASH_COMMANDS = [
    "rm -rf /",
    "rm -fr /",
    "rm -r -f /",
    "rm -f -r /",
    "rm --recursive --force /",
    "rm --force --recursive /",
    "rm -rf ~",
    "rm -r -f ~",
    "rm --recursive --force ~/",
    "git clean -fdx",
    "git clean -xfd",
    "git clean -d -f -x",
    "git clean --force -d -x",
]

# Safe commands / lookalike paths that MUST stay allowed (exit 0, no deny).
ALLOWED_BASH_COMMANDS = [
    "rm -rf /tmp/foo",
    "rm -rf ./build",
    "rm -rf build/",
    "rm -rf /home/me/project",
    "npm run clean",
    "git clean -n",
    "cat /etc/rm-notes",
    "rm -rf /tmp/rf-cache",
]


def _run_bash_guard(guard_path, payload):
    return subprocess.run(
        [sys.executable, str(guard_path)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=False,
    )


class BashGuardDestructiveOptionTests(RavenTestCase):
    def test_claude_copy_denies_all_spellings(self):
        for command in DENIED_BASH_COMMANDS:
            with self.subTest(command=command):
                payload = {"tool_input": {"command": command}}
                result = _run_bash_guard(CLAUDE_BASH_GUARD, payload)
                self.assertEqual(
                    result.returncode, 2, f"stdout={result.stdout!r} stderr={result.stderr!r}"
                )
                self.assertIn("Blocked potentially destructive command.", result.stderr)

    def test_codex_copy_denies_all_spellings(self):
        for command in DENIED_BASH_COMMANDS:
            with self.subTest(command=command):
                payload = {
                    "hook_event_name": "PreToolUse",
                    "tool_name": "Bash",
                    "tool_input": {"command": command},
                }
                result = _run_bash_guard(CODEX_BASH_GUARD, payload)
                self.assertEqual(result.returncode, 0, result.stderr)
                response = json.loads(result.stdout)
                self.assertEqual(response["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_claude_copy_allows_safe_commands(self):
        for command in ALLOWED_BASH_COMMANDS:
            with self.subTest(command=command):
                payload = {"tool_input": {"command": command}}
                result = _run_bash_guard(CLAUDE_BASH_GUARD, payload)
                self.assertEqual(
                    result.returncode, 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
                )
                self.assertEqual(result.stderr, "")

    def test_codex_copy_allows_safe_commands(self):
        for command in ALLOWED_BASH_COMMANDS:
            with self.subTest(command=command):
                payload = {
                    "hook_event_name": "PreToolUse",
                    "tool_name": "Bash",
                    "tool_input": {"command": command},
                }
                result = _run_bash_guard(CODEX_BASH_GUARD, payload)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.strip(), "")


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
