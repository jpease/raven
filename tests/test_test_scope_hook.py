"""The first-test-run scope nudge: one advisory sentence, once per session."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from helpers import REPO_ROOT, RavenTestCase, load_script_module

HOOK = REPO_ROOT / "common" / ".claude" / "hooks" / "raven-pre-bash-test-scope.py"


def _module():
    return load_script_module("raven_pre_bash_test_scope", HOOK)


class ClassifyTests(RavenTestCase):
    def _assert(self, expected, *commands):
        module = _module()
        for command in commands:
            with self.subTest(command=command):
                self.assertEqual(module.classify(command), expected)

    def test_whole_suite_runs(self):
        self._assert(
            "whole",
            "pytest",
            "pytest -q",
            "python -m pytest -q --tb=short",
            "uv run --group dev python -m pytest",
            "rtk pytest",
            "just test",
            "just check",
            "cargo test",
            "go test ./...",
            "npm test",
            "pnpm test",
            "swift test",
            "mix test",
            "bundle exec rspec",
            "FOO=1 pytest -x",
        )

    def test_narrowed_runs(self):
        self._assert(
            "narrow",
            "pytest tests/test_app.py",
            "pytest -k parse",
            "pytest -m slow",
            "pytest tests/test_app.py::test_a",
            "rtk pytest -q tests/test_x.py",
            "just test tests/a.py",
            "cargo test parse_",
            "cargo test -p mycrate",
            "go test ./pkg/...",
            "go test -run TestX ./...",
            "npm test -- src/a.test.ts",
            "swift test --filter ParserTests",
            "mix test test/parser_test.exs",
            "rspec spec/parser_spec.rb",
        )

    def test_non_test_commands(self):
        self._assert(None, "ls -la", "git status", "python -m build", "just lint", "npm run build")

    def test_only_the_first_simple_command_is_read(self):
        # `cd x && pytest` starts with `cd`, so it is not a test command here;
        # a stricter reading would have to reason about every segment.
        self.assertIsNone(_module().classify("git status && pytest"))


class EndToEndTests(RavenTestCase):
    def _run(self, command: str, session_id: str | None = "s-1") -> str:
        payload: dict = {
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": command},
        }
        if session_id is not None:
            payload["session_id"] = session_id
        env = dict(os.environ, TMPDIR=str(self.destination))
        result = subprocess.run(
            [sys.executable, str(HOOK)],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def _stamps(self) -> list[Path]:
        return sorted(self.destination.glob("raven-test-scope-*"))

    def test_first_whole_suite_run_gets_one_sentence(self):
        output = json.loads(self._run("pytest -q"))["hookSpecificOutput"]
        self.assertEqual(output["hookEventName"], "PreToolUse")
        self.assertIn("narrowest", output["additionalContext"])
        self.assertEqual(len(self._stamps()), 1)

    def test_nothing_is_said_a_second_time(self):
        self._run("pytest -q")
        self.assertEqual(self._run("pytest -q"), "")
        self.assertEqual(self._run("just check"), "")

    def test_a_narrow_first_run_silences_the_later_broad_one(self):
        self.assertEqual(self._run("pytest tests/test_app.py"), "")
        self.assertEqual(self._run("pytest -q"), "")
        self.assertEqual(len(self._stamps()), 1)

    def test_sessions_are_independent(self):
        self._run("pytest -q", session_id="one")
        self.assertNotEqual(self._run("pytest -q", session_id="two"), "")

    def test_no_session_id_means_no_nudge_and_no_stamp(self):
        self.assertEqual(self._run("pytest -q", session_id=None), "")
        self.assertEqual(self._stamps(), [])

    def test_non_test_commands_leave_no_stamp(self):
        self.assertEqual(self._run("git status"), "")
        self.assertEqual(self._stamps(), [])
        # The session's first *test* command is still to come.
        self.assertNotEqual(self._run("pytest"), "")
