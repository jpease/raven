import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import ClassVar

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
    "rm -rf /home/me/project",  # raven-hygiene: allow (synthetic path, unrelated fixture)
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


class BashGuardRegexPatternTests(RavenTestCase):
    """Raw-text matches are denied, but only for text a shell could execute.

    The raw-text family matches text rather than intent, so what it is shown
    decides its false-positive rate. A heredoc body is the stdin of the program
    on its introducer line: fed to `python3 -` or `gh --body-file -` it is data
    that never runs, and matching it can only misfire. Fed to `bash` it is code
    and must still be scanned. `_strip_heredoc_bodies` draws exactly that line.

    Denying the data case (as this guard originally did, per issue #155) is not
    the conservative choice it looks like. Review prose, commit messages, SQL and
    documentation routinely *name* destructive commands, so the block lands on
    ordinary work -- and the obvious way out is to write the same content to a
    file and run that, which bypasses the guard entirely and leaves a less
    reviewable artifact behind.
    """

    def test_claude_copy_allows_a_trigger_phrase_in_a_data_heredoc(self):
        """`python -` consumes its heredoc as stdin; the body never executes."""
        command = "python - <<'EOF'\n# Example showing: git reset --hard\nprint(1)\nEOF"
        payload = {"tool_input": {"command": command}}
        result = _run_bash_guard(CLAUDE_BASH_GUARD, payload)
        self.assertEqual(result.returncode, 0, f"stdout={result.stdout!r} stderr={result.stderr!r}")

    def test_codex_copy_allows_a_trigger_phrase_in_a_data_heredoc(self):
        """Codex version: a data heredoc body is not a command."""
        command = "python - <<'EOF'\n# Example: git reset --hard\nprint(1)\nEOF"
        payload = {
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": command},
        }
        result = _run_bash_guard(CODEX_BASH_GUARD, payload)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "", "a data heredoc must not be denied")

    def test_claude_copy_allows_a_commented_command_in_a_shell_heredoc(self):
        """A `#` comment is kept by the strip (the body is code) but never runs.

        Tokenizing is what tells these apart: the body of a `sh` heredoc is
        scanned, and within it a comment still resolves to no program.
        """
        command = "sh - <<'SCRIPT'\n# Safety check: dropdb unsafe_db\nexit 0\nSCRIPT"
        payload = {"tool_input": {"command": command}}
        result = _run_bash_guard(CLAUDE_BASH_GUARD, payload)
        self.assertEqual(result.returncode, 0, f"stdout={result.stdout!r}")

    def test_claude_copy_still_denies_an_unterminated_heredoc(self):
        """No terminator means no provable end, so the remainder is scanned."""
        payload = {"tool_input": {"command": "python - <<'EOF'\nsudo rm -rf /"}}
        result = _run_bash_guard(CLAUDE_BASH_GUARD, payload)
        self.assertEqual(result.returncode, 2, f"stdout={result.stdout!r}")

    def test_claude_copy_still_denies_a_herestring(self):
        """`<<<` is a herestring: its operand is on the line, not in a body."""
        payload = {"tool_input": {"command": "bash <<< 'sudo rm -rf /'"}}
        result = _run_bash_guard(CLAUDE_BASH_GUARD, payload)
        self.assertEqual(result.returncode, 2, f"stdout={result.stdout!r}")

    def test_claude_copy_still_denies_a_command_after_a_data_heredoc(self):
        """Stripping a body must not swallow what follows the terminator."""
        command = "python - <<'EOF'\nprint(1)\nEOF\nsudo rm -rf /"
        payload = {"tool_input": {"command": command}}
        result = _run_bash_guard(CLAUDE_BASH_GUARD, payload)
        self.assertEqual(result.returncode, 2, f"stdout={result.stdout!r}")

    def test_claude_copy_denies_real_git_reset_hard_command(self):
        """A real 'git reset --hard' invocation is still denied."""
        command = "git reset --hard HEAD"
        payload = {"tool_input": {"command": command}}
        result = _run_bash_guard(CLAUDE_BASH_GUARD, payload)
        self.assertEqual(result.returncode, 2, f"stdout={result.stdout!r} stderr={result.stderr!r}")
        self.assertIn("Blocked", result.stderr)

    def test_codex_copy_denies_real_git_reset_hard_command(self):
        """Codex version: real 'git reset --hard' is still denied."""
        command = "git reset --hard HEAD"
        payload = {
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": command},
        }
        result = _run_bash_guard(CODEX_BASH_GUARD, payload)
        self.assertEqual(result.returncode, 0, result.stderr)
        response = json.loads(result.stdout)
        self.assertEqual(response["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_claude_copy_denies_a_trigger_phrase_in_a_shell_heredoc(self):
        """`sh` executes its heredoc body, so that body is code and is scanned."""
        command = "sh - <<'SCRIPT'\ndropdb unsafe_db\nexit 0\nSCRIPT"
        payload = {"tool_input": {"command": command}}
        result = _run_bash_guard(CLAUDE_BASH_GUARD, payload)
        self.assertEqual(result.returncode, 2, f"stdout={result.stdout!r} stderr={result.stderr!r}")

    def test_codex_copy_denies_a_trigger_phrase_in_a_shell_heredoc(self):
        """Codex version: a shell heredoc body is code."""
        command = "sh - <<'SCRIPT'\nsudo rm -rf /\nexit 0\nSCRIPT"
        payload = {
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": command},
        }
        result = _run_bash_guard(CODEX_BASH_GUARD, payload)
        self.assertEqual(result.returncode, 0, result.stderr)
        response = json.loads(result.stdout)
        self.assertEqual(response["hookSpecificOutput"]["permissionDecision"], "deny")
        reason = response["hookSpecificOutput"]["permissionDecisionReason"]
        self.assertIn("destructive", reason.lower())


class BashGuardTokenizedIntentTests(RavenTestCase):
    """Destructive intents are matched at the program position, not in the text.

    A regex over raw command text is noisy *and* leaky. It fires on any mention
    -- a search pattern, a commit message, a line of documentation -- and it
    misses the ordinary spellings that put an option between a verb and its
    object. Claude Code documents the same fragility for its own Bash permission
    patterns, and a live check confirms it: a `Bash(git tag *)` deny rule blocks
    `git tag --list` but not `git -c core.pager=cat tag --list`.
    """

    #: Harmless: the words appear only inside an argument.
    MENTIONS: ClassVar[list[str]] = [
        'rg -n "dropdb|kubectl" guard.py',
        'git commit -m "note: never kubectl delete prod"',
        'echo "the runbook says dropdb staging"',
        'gh issue create --title "aws cleanup should delete stale keys"',
    ]

    #: Real invocations with an option between the program and its verb. A
    #: prefix regex requires adjacency and misses every one of these.
    NON_ADJACENT: ClassVar[list[str]] = [
        "git reset --hard HEAD".replace("reset --hard", "reset --hard"),
        "kubectl --context=prod delete pod web",
        "kubectl -n default delete deployment api",
    ]

    #: A payload handed to another interpreter still runs.
    NESTED: ClassVar[list[str]] = [
        'bash -c "kubectl delete pod web"',
        "ssh host 'dropdb prod'",
        "xargs -I{} kubectl delete pod {}",
        "timeout 30 kubectl delete pod web",
    ]

    def _claude(self, command):
        return _run_bash_guard(CLAUDE_BASH_GUARD, {"tool_input": {"command": command}})

    def test_a_mention_in_an_argument_is_allowed(self):
        for command in self.MENTIONS:
            with self.subTest(command=command):
                self.assertEqual(self._claude(command).returncode, 0)

    def test_an_option_between_verb_and_object_is_still_denied(self):
        for command in self.NON_ADJACENT:
            with self.subTest(command=command):
                self.assertEqual(self._claude(command).returncode, 2, command)

    def test_a_nested_payload_is_followed(self):
        for command in self.NESTED:
            with self.subTest(command=command):
                self.assertEqual(self._claude(command).returncode, 2, command)

    def test_a_herestring_fed_to_a_shell_is_followed(self):
        self.assertEqual(self._claude("bash <<< 'sudo rm -rf /'").returncode, 2)

    def test_sql_is_scoped_to_a_database_client(self):
        """DROP DATABASE has no program position, so it is matched per client."""
        self.assertEqual(self._claude('psql -c "DROP DATABASE prod"').returncode, 2)
        self.assertEqual(self._claude('grep -c "DROP DATABASE" schema.sql').returncode, 0)


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

    def test_hooks_tolerate_malformed_json_stdin(self):
        # Issue #152: _load_payload()'s except clause must stay narrowed to
        # (ValueError, OSError) -- json.load raises JSONDecodeError (a
        # ValueError) on unparseable stdin, and the hook must still fail
        # open (exit 0, no output) rather than crash noisily.
        hooks = [
            "raven-post-bash-summarize.py",
            "raven-pre-bash-guard.py",
            "raven-pre-edit-guard.py",
            "raven-post-edit-format.py",
            "raven-session-checkpoint.py",
            "raven-skeleton-read-guard.py",
        ]

        for hook in hooks:
            with self.subTest(hook=hook):
                result = subprocess.run(
                    [sys.executable, str(REPO_ROOT / "common" / ".claude" / "hooks" / hook)],
                    input="not json",
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, "")

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


# --- Edit guard: anchored `credentials` + `..` traversal normalization
# (issue #197) -----------------------------------------------------------
#
# The `blocked` list's bare `r"credentials"` pattern was an unanchored,
# case-insensitive substring match: it denied edits to
# docs/credentials-design.md, tests/test_credentials_helper.py, and
# src/credentialsProvider.ts, none of which hold actual credential material.
# Separately, the hook only did a backslash-to-forward-slash swap before
# matching -- no `..` collapsing -- so `src/../.env` and
# `a/b/../../secrets/prod.json` slipped past the anchored `.env`/`secrets`
# patterns. Both directions, driven through real subprocess invocations with
# real stdin JSON, for both denial protocols (Claude: stderr + exit 2; Codex:
# `hookSpecificOutput` JSON on stdout + exit 0).
EDIT_GUARD_CLAUDE = REPO_ROOT / "common" / ".claude" / "hooks" / "raven-pre-edit-guard.py"
EDIT_GUARD_CODEX = REPO_ROOT / "common" / ".codex" / "hooks" / "raven-pre-edit-guard.py"

# MUST be denied: real credential paths, plus `..`-traversal that resolves
# onto an already-blocked segment, in both forward-slash and Windows-style
# backslash spellings.
CREDENTIALS_TRAVERSAL_BLOCKED_PATHS = [
    ".aws/credentials",
    "~/.aws/credentials",
    "config/credentials.yml",
    "credentials/prod.json",
    "src/../.env",
    "a/b/../../secrets/prod.json",
    "src\\..\\.env",
]

# MUST stay allowed: the old unanchored `credentials` substring match used to
# deny all three of these.
CREDENTIALS_FALSE_POSITIVE_PATHS = [
    "docs/credentials-design.md",
    "tests/test_credentials_helper.py",
    "src/credentialsProvider.ts",
]


def _claude_edit_payload(path: str) -> str:
    return json.dumps({"tool_input": {"file_path": path}})


def _codex_edit_payload(path: str) -> str:
    return json.dumps(
        {
            "hook_event_name": "PreToolUse",
            "tool_name": "apply_patch",
            "tool_input": {"file_path": path},
        }
    )


def _run_edit_guard(hook: Path, payload: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(hook)],
        input=payload,
        capture_output=True,
        text=True,
        check=False,
    )


class CredentialsPathGuardTests(unittest.TestCase):
    def test_claude_denies_blocked_paths(self):
        for path in CREDENTIALS_TRAVERSAL_BLOCKED_PATHS:
            with self.subTest(path=path):
                result = _run_edit_guard(EDIT_GUARD_CLAUDE, _claude_edit_payload(path))
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn(path, result.stderr)
                self.assertEqual(result.stdout, "")

    def test_claude_allows_false_positive_paths(self):
        for path in CREDENTIALS_FALSE_POSITIVE_PATHS:
            with self.subTest(path=path):
                result = _run_edit_guard(EDIT_GUARD_CLAUDE, _claude_edit_payload(path))
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, "")

    def test_codex_denies_blocked_paths(self):
        for path in CREDENTIALS_TRAVERSAL_BLOCKED_PATHS:
            with self.subTest(path=path):
                result = _run_edit_guard(EDIT_GUARD_CODEX, _codex_edit_payload(path))
                self.assertEqual(result.returncode, 0, result.stderr)
                response = json.loads(result.stdout)
                decision = response["hookSpecificOutput"]
                self.assertEqual(decision["hookEventName"], "PreToolUse")
                self.assertEqual(decision["permissionDecision"], "deny")
                self.assertIn(path, decision["permissionDecisionReason"])

    def test_codex_allows_false_positive_paths(self):
        for path in CREDENTIALS_FALSE_POSITIVE_PATHS:
            with self.subTest(path=path):
                result = _run_edit_guard(EDIT_GUARD_CODEX, _codex_edit_payload(path))
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, "")


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
    before trusting it to validate the real hooks.json (issue #129).
    """

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


# --- Claude hook interpreter resolution ----------------------------------
#
# .claude/settings.json launched every hook with a bare `python`. On a machine
# that ships only `python3` -- the default on macOS and most Linux
# distributions -- that name resolves to nothing and every hook silently stops
# running. The hooks are deliberately fail-open, so there is no signal at all
# when it happens.
#
# The Codex side cannot use this shim: per CANONICAL_CODEX_LAUNCHER above, a
# Codex hook may run with a cwd outside the project, so nothing repo-relative
# can be located until the payload has been parsed. The Claude side has
# $CLAUDE_PROJECT_DIR, which is why a shim works here and not there.
CLAUDE_RUN_HOOK = REPO_ROOT / "common" / ".claude" / "hooks" / "raven-run-hook.sh"


class ClaudeHookLauncherTests(unittest.TestCase):
    def _commands(self) -> list[str]:
        config = json.loads(
            (REPO_ROOT / "common" / ".claude" / "settings.json").read_text(encoding="utf-8")
        )
        return list(_iter_command_strings(config))

    def test_the_shim_ships_in_the_template(self):
        self.assertTrue(CLAUDE_RUN_HOOK.is_file())

    def test_every_hook_command_goes_through_the_shim(self):
        commands = self._commands()

        self.assertTrue(commands)
        for command in commands:
            self.assertIn("raven-run-hook.sh", command, command)

    def test_no_hook_command_invokes_a_bare_interpreter(self):
        """The defect this guards is a command that starts with `python `."""
        for command in self._commands():
            self.assertFalse(command.startswith("python "), command)

    def test_every_referenced_script_exists(self):
        for command in self._commands():
            relative = command.rsplit(" ", 1)[-1].strip('"')
            self.assertTrue((REPO_ROOT / "common" / relative).is_file(), relative)

    def test_shim_resolves_a_relative_script_from_an_unrelated_cwd(self):
        """A hook's process cwd is not reliably the project."""
        with tempfile.TemporaryDirectory() as outside:
            result = subprocess.run(
                ["sh", str(CLAUDE_RUN_HOOK), ".claude/scripts/raven-skeleton.py"],
                cwd=outside,
                capture_output=True,
                text=True,
            )

        # raven-skeleton.py with no file argument is a usage error, which is
        # proof it was found and executed rather than silently skipped.
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("usage", result.stderr.lower())

    def test_shim_fails_open_but_reports_a_missing_interpreter(self):
        with tempfile.TemporaryDirectory() as empty_bin:
            shell = shutil.which("sh")
            self.assertIsNotNone(shell)
            result = subprocess.run(
                [str(shell), str(CLAUDE_RUN_HOOK), ".claude/hooks/raven-pre-bash-guard.py"],
                capture_output=True,
                text=True,
                env={"PATH": empty_bin},
            )

        self.assertEqual(result.returncode, 0)
        self.assertIn("no working Python launcher", result.stderr)

    #: The launchers duplicate this resolution deliberately -- a hook must not
    #: depend on a sibling file surviving a partial checkout -- so pin them
    #: together rather than trusting the copies to stay in step by hand.
    LAUNCHERS = (CLAUDE_RUN_HOOK,)

    def test_launchers_verify_the_interpreter_executes(self):
        """`command -v` finding a name is not proof it runs.

        `python3` on Windows is normally the WindowsApps App Execution Alias: it
        opens the Microsoft Store and runs nothing, while `command -v` reports it
        present. Selecting on presence alone therefore picks a launcher that
        silently does nothing -- and these hooks are fail-open, so nothing says
        so. `py -3` is the reliable launcher there.
        """
        for launcher in self.LAUNCHERS:
            source = launcher.read_text(encoding="utf-8")
            with self.subTest(launcher=launcher.name):
                self.assertIn('-c ""', source)
                self.assertIn("MINGW*|MSYS*|CYGWIN*", source)
                self.assertIn('py|python|python3"', source)

    def test_launchers_resolve_an_interpreter_on_this_platform(self):
        """Run the shipped resolution block verbatim rather than a copy of it."""
        start = 'case "$(uname -s 2>/dev/null)" in'
        end = "\ndone\n"
        for launcher in self.LAUNCHERS:
            source = launcher.read_text(encoding="utf-8")
            block = start + source.split(start, 1)[1].split(end, 1)[0] + end
            result = subprocess.run(
                ["sh", "-c", block + 'printf "%s" "$RAVEN_PY"'],
                capture_output=True,
                text=True,
                check=False,
            )
            with self.subTest(launcher=launcher.name):
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertTrue(result.stdout.strip(), "resolved no launcher")

    def test_installed_claude_settings_matches_canonical(self):
        """Same manual-merge drift risk as the Codex copy above (issue #97)."""
        canonical = (REPO_ROOT / "common" / ".claude" / "settings.json").read_text(encoding="utf-8")
        installed = (REPO_ROOT / ".claude" / "settings.json").read_text(encoding="utf-8")
        self.assertEqual(installed, canonical)


# Every hook that reads a JSON payload from stdin. Each is fail-open by
# design, so anything it cannot evaluate must be waved through *quietly* --
# a traceback on every tool call is its own kind of breakage.
PAYLOAD_READING_HOOKS = (
    "raven-pre-bash-guard.py",
    "raven-pre-edit-guard.py",
    "raven-skeleton-read-guard.py",
    "raven-post-bash-summarize.py",
    "raven-post-edit-format.py",
    "raven-session-checkpoint.py",
)

# Valid JSON that is not an object. `json.load` returns each of these happily,
# and every hook then calls `.get` on it. Malformed *text* was already handled;
# well-formed JSON of the wrong shape is the one parseable input that raised
# instead of failing open.
NON_OBJECT_PAYLOADS = ('["a", "list"]', '"a bare string"', "42", "null", "true")


class HookPayloadFailOpenTests(unittest.TestCase):
    def _run(self, hook: str, payload: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(REPO_ROOT / "common" / ".claude" / "hooks" / hook)],
            input=payload,
            capture_output=True,
            text=True,
        )

    def test_every_hook_survives_a_non_object_payload(self):
        for hook in PAYLOAD_READING_HOOKS:
            for payload in NON_OBJECT_PAYLOADS:
                with self.subTest(hook=hook, payload=payload):
                    result = self._run(hook, payload)

                    self.assertNotIn("Traceback", result.stderr)
                    self.assertNotEqual(result.returncode, 2, "must not deny on unusable input")
                    self.assertEqual(result.returncode, 0)

    def test_every_hook_still_survives_malformed_text(self):
        """The case that was already handled, kept so a fix cannot regress it."""
        for hook in PAYLOAD_READING_HOOKS:
            with self.subTest(hook=hook):
                result = self._run(hook, "{not json at all")

                self.assertNotIn("Traceback", result.stderr)
                self.assertEqual(result.returncode, 0)


class CodexSessionCheckpointPayloadFailOpenTests(unittest.TestCase):
    """Same guarantee as HookPayloadFailOpenTests, proved against the Codex-side
    path too (issue #195). `raven-session-checkpoint.py` used to be a second, real
    file under `.codex/hooks/` that had fallen behind the Claude copy's
    `isinstance(payload, dict)` guard and tracebacked on well-formed non-dict JSON.
    It is now a template-internal symlink to the Claude copy (like its unified
    siblings), so this is also a regression test against that class of drift: if
    the symlink or the underlying guard is ever removed, this fails again.
    """

    def _run(self, payload: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [
                sys.executable,
                str(REPO_ROOT / "common" / ".codex" / "hooks" / "raven-session-checkpoint.py"),
            ],
            input=payload,
            capture_output=True,
            text=True,
        )

    def test_survives_a_non_object_payload(self):
        for payload in NON_OBJECT_PAYLOADS:
            with self.subTest(payload=payload):
                result = self._run(payload)

                self.assertNotIn("Traceback", result.stderr)
                self.assertNotEqual(result.returncode, 2, "must not deny on unusable input")
                self.assertEqual(result.returncode, 0)

    def test_still_survives_malformed_text(self):
        result = self._run("{not json at all")

        self.assertNotIn("Traceback", result.stderr)
        self.assertEqual(result.returncode, 0)


# --- Session checkpoint hook: cwd-independent root resolution (issue #196) --
#
# Every repo-relative lookup in raven-session-checkpoint.py used to resolve
# against Path(".raven/...") -- the process cwd -- including the validator
# script path (only the ".claude" vs ".codex" segment of that path was fixed
# by #195). A hook's process cwd is not reliably the project root: the Codex
# launcher (CANONICAL_CODEX_LAUNCHER above) locates the hook *file* through a
# resolved repo root but never calls os.chdir(), so the actual OS-level cwd
# when the hook body runs can be anywhere, including outside the repo
# entirely. These tests drive the hook through a real subprocess invocation
# with a real stdin payload -- not by calling internals -- against a real
# temp git repo, with `cwd=` deliberately pointed elsewhere.
SESSION_CHECKPOINT_HOOK = REPO_ROOT / "common" / ".claude" / "hooks" / "raven-session-checkpoint.py"


def _checkpoint_payload(command: str) -> str:
    return json.dumps({"tool_input": {"command": command}})


class SessionCheckpointRootResolutionTests(unittest.TestCase):
    """The hook must find its own install root regardless of process cwd."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name) / "repo"
        self.repo.mkdir()
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)

        hooks_dir = self.repo / ".claude" / "hooks"
        hooks_dir.mkdir(parents=True)
        shutil.copy(SESSION_CHECKPOINT_HOOK, hooks_dir / "raven-session-checkpoint.py")

        scripts_dir = self.repo / ".claude" / "scripts"
        scripts_dir.mkdir(parents=True)
        # A stub validator: these tests are about root resolution, not
        # raven-session.py's own --validate business logic, so a script that
        # simply succeeds is sufficient to prove the hook located and ran it.
        (scripts_dir / "raven-session.py").write_text(
            "#!/usr/bin/env python3\nimport sys\nsys.exit(0)\n", encoding="utf-8"
        )

        raven_dir = self.repo / ".raven"
        raven_dir.mkdir()
        (raven_dir / "session.md").write_text("# active session\n", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def _run_hook(self, cwd: Path) -> subprocess.CompletedProcess:
        payload = _checkpoint_payload("python .claude/scripts/raven-session.py --complete unit-a")
        return subprocess.run(
            [sys.executable, str(self.repo / ".claude" / "hooks" / "raven-session-checkpoint.py")],
            input=payload,
            cwd=str(cwd),
            capture_output=True,
            text=True,
        )

    def test_finds_the_hook_from_a_subdirectory_of_the_repo(self):
        subdir = self.repo / "src" / "nested"
        subdir.mkdir(parents=True)

        result = self._run_hook(cwd=subdir)

        self.assertEqual(result.returncode, 0, f"stdout={result.stdout!r} stderr={result.stderr!r}")

    def test_finds_the_hook_from_a_cwd_outside_the_repo(self):
        with tempfile.TemporaryDirectory() as outside:
            result = self._run_hook(cwd=Path(outside))

        self.assertEqual(result.returncode, 0, f"stdout={result.stdout!r} stderr={result.stderr!r}")

    def test_missing_validator_script_fails_open_with_a_diagnostic(self):
        (self.repo / ".claude" / "scripts" / "raven-session.py").unlink()

        result = self._run_hook(cwd=self.repo)

        self.assertEqual(result.returncode, 0, f"stdout={result.stdout!r} stderr={result.stderr!r}")
        self.assertIn("cannot find", result.stderr)
        self.assertIn("raven-session.py", result.stderr)
        self.assertIn("skipping checkpoint validation", result.stderr)
        self.assertIn("failing open", result.stderr)

    def test_validation_failure_still_denies(self):
        """No change to deny behavior when validation genuinely fails."""
        (self.repo / ".claude" / "scripts" / "raven-session.py").write_text(
            "#!/usr/bin/env python3\nimport sys\n"
            'print("unit not ready", file=sys.stderr)\nsys.exit(1)\n',
            encoding="utf-8",
        )

        result = self._run_hook(cwd=self.repo)

        self.assertEqual(result.returncode, 2, f"stdout={result.stdout!r} stderr={result.stderr!r}")
        self.assertIn("unit not ready", result.stderr)


class CatastrophicRmTargetTests(unittest.TestCase):
    """The guard has to see the spellings a shell would have expanded.

    Nothing expands them before it runs -- shlex does not glob and no shell is
    involved -- so `rm -rf /*` and `rm -rf $HOME` arrive as those literal
    tokens. Comparing operands to "/" and "~" by equality let both straight
    through.
    """

    GUARD = REPO_ROOT / "common" / ".claude" / "hooks" / "raven-pre-bash-guard.py"

    def _run(self, command: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(self.GUARD)],
            input=json.dumps(
                {
                    "hook_event_name": "PreToolUse",
                    "tool_name": "Bash",
                    "tool_input": {"command": command},
                }
            ),
            capture_output=True,
            text=True,
        )

    def test_catastrophic_deletes_are_denied(self):
        for command in (
            "rm -rf /",
            "rm -rf ~",
            "rm -rf /*",
            "rm -rf ~/*",
            "rm -rf $HOME",
            "rm -fr ${HOME}",
            "rm -rf $HOME/work",  # raven-hygiene: allow (unexpanded token under test)
        ):
            with self.subTest(command=command):
                result = self._run(command)
                decision = json.loads(result.stdout)["hookSpecificOutput"]

                self.assertEqual(decision["permissionDecision"], "deny")

    def test_scoped_deletes_are_still_allowed(self):
        """A guard that fires on routine paths gets switched off, which helps nobody."""
        for command in (
            "rm -rf build/",
            "rm -rf ./dist",
            "rm -rf /tmp/scratch",
            "rm -rf $HOMEBREW_PREFIX/var",
        ):
            with self.subTest(command=command):
                result = self._run(command)

                self.assertEqual(result.returncode, 0)
                self.assertEqual(result.stdout.strip(), "")


class NoisyCommandMatchingTests(unittest.TestCase):
    """The RTK nudge matched by plain substring, so an entry fired on any command
    merely containing its letters -- `aws` inside "draws", `go test` never, but
    `docker` inside a path. The hint is advisory, which is exactly why a false
    positive is corrosive: it trains people to ignore hook output.
    """

    HOOK = REPO_ROOT / "common" / ".claude" / "hooks" / "raven-post-bash-summarize.py"

    def _hint(self, command: str) -> str:
        result = subprocess.run(
            [sys.executable, str(self.HOOK)],
            input=json.dumps(
                {
                    "hook_event_name": "PostToolUse",
                    "tool_name": "Bash",
                    "tool_input": {"command": command},
                }
            ),
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0)
        return result.stdout

    def test_a_word_inside_another_word_is_not_a_tool(self):
        """Word-boundary matching fixes substring collisions, and only those.

        A command that mentions a tool as a genuine word -- `git commit -m
        "switch to kubectl"` -- still nudges, and deliberately so: nothing at
        this level can tell that apart from running it, and the hint is
        advisory. The bug worth fixing was `aws` matching inside "draws".
        """
        for command in (
            'git commit -m "fix draws bug"',
            "echo pytestable",
            "ls ./dockerfiles",
            "cd swift-testing-notes",
        ):
            with self.subTest(command=command):
                self.assertEqual(self._hint(command), "")

    def test_real_invocations_are_still_nudged(self):
        for command in ("pytest -q", "cargo test", "kubectl get pods", "aws s3 ls"):
            with self.subTest(command=command):
                self.assertIn("RTK", self._hint(command))

    def test_a_command_already_using_rtk_is_left_alone(self):
        self.assertEqual(self._hint("rtk pytest -q"), "")


if __name__ == "__main__":
    unittest.main()
