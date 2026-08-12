import json
import subprocess
import sys
import unittest
from pathlib import Path

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

# rg commands using a bundled short-flag cluster containing `r` -- ripgrep's
# `-r` is `--replace` (takes an argument), not grep's `--recursive`, and
# ripgrep is recursive by default. These MUST be denied.
RIPGREP_DENIED_COMMANDS = [
    "rg -rn PATTERN dir/",
    "rg -rln PATTERN dir/",
    "rg -nr PATTERN dir/",
    "rg -F -rn PATTERN dir/",
    "rtk proxy rg -rn PATTERN dir/",
]

# rg (and lookalike) commands that MUST stay allowed.
RIPGREP_ALLOWED_COMMANDS = [
    "rg -n PATTERN dir/",
    "rg PATTERN dir/",
    "rg -r QQQ PATTERN file.txt",
    "rg --replace=QQQ PATTERN file.txt",
    "rg -l PATTERN dir/",
    "grep -rn PATTERN dir/",
    "rg PATTERN dir/ | grep -rn bar",
    "rg --no-heading -n PATTERN dir/",
    "ls -lr",
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


class BashGuardRipgrepReplaceFlagTests(RavenTestCase):
    def test_claude_copy_denies_bundled_replace_cluster(self):
        for command in RIPGREP_DENIED_COMMANDS:
            with self.subTest(command=command):
                payload = {"tool_input": {"command": command}}
                result = _run_bash_guard(CLAUDE_BASH_GUARD, payload)
                self.assertEqual(
                    result.returncode, 2, f"stdout={result.stdout!r} stderr={result.stderr!r}"
                )
                self.assertIn("--replace", result.stderr)

    def test_codex_copy_denies_bundled_replace_cluster(self):
        for command in RIPGREP_DENIED_COMMANDS:
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
                self.assertIn(
                    "--replace", response["hookSpecificOutput"]["permissionDecisionReason"]
                )

    def test_claude_copy_allows_safe_ripgrep_commands(self):
        for command in RIPGREP_ALLOWED_COMMANDS:
            with self.subTest(command=command):
                payload = {"tool_input": {"command": command}}
                result = _run_bash_guard(CLAUDE_BASH_GUARD, payload)
                self.assertEqual(
                    result.returncode, 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
                )
                self.assertEqual(result.stderr, "")

    def test_codex_copy_allows_safe_ripgrep_commands(self):
        for command in RIPGREP_ALLOWED_COMMANDS:
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


# --- Codex hook launcher drift guard (issue #129) ------------------------
#
# common/.codex/hooks.json hand-maintains six byte-identical copies of the
# same Python launcher one-liner, differing only in the trailing script
# path. Per commit f425909 (closes #115) and
# test_codex_bash_guard_runs_outside_project_worktree in test_template.py,
# Codex Desktop can invoke a hook with a process cwd outside the project,
# so the launcher must parse the JSON payload on stdin before it can locate
# the project root -- neither a shim script nor a `git rev-parse` shell
# wrapper can be resolved any earlier than that. That constraint is what
# forces the inline expression instead of a single shared script; this
# guard exists so a missed copy fails loudly instead of silently.
CANONICAL_CODEX_LAUNCHER = (
    'python -c "import io,json,runpy,sys; from pathlib import Path; '
    "payload=sys.stdin.read(); relative=sys.argv[1]; "
    "cwd=Path(json.loads(payload)['cwd']).resolve(); "
    "root=next((path for path in (cwd,*cwd.parents) if (path/'.git').exists()), cwd); "
    "sys.stdin=io.StringIO(payload); sys.argv=sys.argv[1:]; "
    'runpy.run_path(str(root / relative), run_name=\'__main__\')" '
)

# The count assertion in find_codex_launcher_drift exists specifically so a
# newly added (or removed) hook event cannot skip this check by being
# invisible to it. Update this value -- and CANONICAL_CODEX_LAUNCHER, if the
# expression itself legitimately changed -- when that happens.
EXPECTED_CODEX_LAUNCHER_COUNT = 6


def _iter_command_strings(node):
    """Yield every string value found under a "command" key, recursively."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "command" and isinstance(value, str):
                yield value
            else:
                yield from _iter_command_strings(value)
    elif isinstance(node, list):
        for value in node:
            yield from _iter_command_strings(value)


def find_codex_launcher_drift(hooks_config: dict, scripts_root: Path) -> list[str]:
    """Pure, fixture-testable core of the drift guard.

    ``hooks_config`` is a parsed .codex/hooks.json document. ``scripts_root``
    is the directory the launcher's script-path argument is resolved
    against (``common/`` for the canonical file, since the launcher's
    relative path -- e.g. ``.codex/hooks/raven-pre-bash-guard.py`` -- lives
    directly under ``common/`` there). Returns a list of human-readable
    problem strings; an empty list means the file is drift-free.
    """
    problems: list[str] = []
    commands = [c for c in _iter_command_strings(hooks_config) if "raven-" in c]

    if len(commands) != EXPECTED_CODEX_LAUNCHER_COUNT:
        problems.append(
            f"expected exactly {EXPECTED_CODEX_LAUNCHER_COUNT} raven-* hook launcher "
            f"commands, found {len(commands)}. If a hook event was legitimately added "
            "or removed, update EXPECTED_CODEX_LAUNCHER_COUNT in tests/test_agent_hooks.py "
            "(and CANONICAL_CODEX_LAUNCHER too, if the launcher expression itself changed)."
        )

    suffixes: list[str] = []
    for command in commands:
        if not command.startswith(CANONICAL_CODEX_LAUNCHER):
            problems.append(
                "command does not match the canonical launcher prefix "
                f"(CANONICAL_CODEX_LAUNCHER in tests/test_agent_hooks.py): {command!r}"
            )
            continue
        suffixes.append(command[len(CANONICAL_CODEX_LAUNCHER) :])

    if len(suffixes) != len(set(suffixes)):
        problems.append(f"duplicate script-path suffix among launcher commands: {suffixes}")

    for suffix in suffixes:
        script = suffix.split(" ", 1)[0]
        if not (scripts_root / script).is_file():
            problems.append(f"launcher references a script that does not exist: {script}")

    return problems


class CodexHookLauncherDriftFixtureTests(unittest.TestCase):
    """Prove find_codex_launcher_drift has teeth against synthetic fixtures
    before trusting it to validate the real hooks.json (issue #129)."""

    @staticmethod
    def _good_suffixes():
        return [
            ".codex/scripts/raven-capability-roster.py",
            ".codex/hooks/raven-pre-bash-guard.py",
            ".codex/hooks/raven-pre-edit-guard.py",
            ".codex/hooks/raven-session-checkpoint.py",
            ".codex/hooks/raven-post-bash-summarize.py",
            ".codex/hooks/raven-post-edit-format.py",
        ]

    @classmethod
    def _good_commands(cls):
        return [CANONICAL_CODEX_LAUNCHER + suffix for suffix in cls._good_suffixes()]

    @staticmethod
    def _config(commands):
        # Distribute across events the way the real file does; the exact
        # event grouping doesn't matter to find_codex_launcher_drift, which
        # walks the whole document for "command" keys.
        return {
            "hooks": {
                "SessionStart": [{"hooks": [{"type": "command", "command": commands[0]}]}],
                "PreToolUse": [
                    {"hooks": [{"type": "command", "command": c}]} for c in commands[1:4]
                ],
                "PostToolUse": [
                    {"hooks": [{"type": "command", "command": c}]} for c in commands[4:6]
                ],
            }
        }

    def test_clean_fixture_has_no_drift(self):
        problems = find_codex_launcher_drift(
            self._config(self._good_commands()), REPO_ROOT / "common"
        )
        self.assertEqual(problems, [])

    def test_detects_drifted_command(self):
        # Simulates fixing 5-of-6 copies and missing one -- exactly the
        # silent-failure scenario this guard exists to prevent.
        commands = self._good_commands()
        commands[2] = commands[2].replace("(cwd,*cwd.parents)", "(cwd, *cwd.parents)")
        problems = find_codex_launcher_drift(self._config(commands), REPO_ROOT / "common")
        self.assertTrue(
            any("does not match the canonical launcher prefix" in p for p in problems), problems
        )

    def test_detects_seventh_command(self):
        commands = self._good_commands()
        config = self._config(commands)
        seventh = CANONICAL_CODEX_LAUNCHER + ".codex/scripts/raven-skeleton.py"
        config["hooks"]["PostToolUse"].append({"hooks": [{"type": "command", "command": seventh}]})
        problems = find_codex_launcher_drift(config, REPO_ROOT / "common")
        self.assertTrue(any("found 7" in p for p in problems), problems)
        # Isolate the count failure: the 7th copy is otherwise well-formed,
        # distinct, and points at a real script, so nothing else should fire.
        self.assertEqual(len(problems), 1, problems)

    def test_detects_missing_referenced_script(self):
        commands = self._good_commands()
        commands[1] = CANONICAL_CODEX_LAUNCHER + ".codex/hooks/raven-does-not-exist.py"
        problems = find_codex_launcher_drift(self._config(commands), REPO_ROOT / "common")
        self.assertTrue(
            any("does not exist: .codex/hooks/raven-does-not-exist.py" in p for p in problems),
            problems,
        )

    def test_detects_duplicate_script_paths(self):
        commands = self._good_commands()
        commands[1] = commands[0]
        problems = find_codex_launcher_drift(self._config(commands), REPO_ROOT / "common")
        self.assertTrue(any("duplicate script-path suffix" in p for p in problems), problems)


class CodexHookLauncherRealFileTests(unittest.TestCase):
    def test_common_codex_hooks_json_has_no_launcher_drift(self):
        config = json.loads(
            (REPO_ROOT / "common" / ".codex" / "hooks.json").read_text(encoding="utf-8")
        )
        problems = find_codex_launcher_drift(config, REPO_ROOT / "common")
        self.assertEqual(problems, [])

    def test_installed_codex_hooks_json_matches_canonical(self):
        """Root .codex/hooks.json is the *installed* copy; scripts/self-check.py's
        upgrade step regenerates it from common/.codex/hooks.json (tracked via
        sourceSha256 in .raven/manifest.json) on every self-check run, so in the
        steady state the two files are always byte-identical. This direct
        comparison is not fully redundant with that machinery, though: raven
        upgrade's manual-merge safety net (issue #97) deliberately leaves a
        *locally modified* installed file untouched instead of overwriting it,
        so a hand-edit to the installed copy alone could drift permanently
        without a check like this one ever failing loudly.
        """
        canonical = (REPO_ROOT / "common" / ".codex" / "hooks.json").read_text(encoding="utf-8")
        installed = (REPO_ROOT / ".codex" / "hooks.json").read_text(encoding="utf-8")
        self.assertEqual(installed, canonical)


if __name__ == "__main__":
    unittest.main()
