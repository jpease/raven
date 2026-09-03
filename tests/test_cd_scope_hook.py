"""The leading-`cd` rewrite nudge: one advisory sentence, once per session."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from helpers import REPO_ROOT, RavenTestCase, load_script_module

HOOK = REPO_ROOT / "common" / ".claude" / "hooks" / "raven-pre-bash-cd-scope.py"


def _module():
    return load_script_module("raven_pre_bash_cd_scope", HOOK)


class ClassifyTests(RavenTestCase):
    def _assert_none(self, *commands):
        module = _module()
        for command in commands:
            with self.subTest(command=command):
                self.assertIsNone(module.classify(command))

    def _rewrite(self, command: str) -> str:
        verdict = _module().classify(command)
        self.assertIsNotNone(verdict, command)
        assert verdict is not None
        return verdict[1]

    def test_git_gets_the_exact_dash_c_rewrite(self):
        self.assertEqual(
            self._rewrite("cd /srv/app && git log --oneline -5"),
            "git -C /srv/app log --oneline -5",
        )

    def test_path_taking_tools_are_named_in_the_hint(self):
        for tool in ("rg", "grep", "fd", "find", "cat", "head", "tail", "wc", "ls"):
            with self.subTest(tool=tool):
                self.assertIn(tool, self._rewrite(f"cd /srv/app && {tool} pattern"))

    def test_semicolon_separates_too(self):
        self.assertEqual(
            self._rewrite("cd /srv/app; git status"),
            "git -C /srv/app status",
        )

    def test_a_directory_holding_a_space_is_re_quoted(self):
        # The directory is unquoted out of the source command, so the rewrite has
        # to put quoting back or it names a command that does not run.
        self.assertEqual(
            self._rewrite('cd "/srv/my app" && git status'),
            "git -C '/srv/my app' status",
        )

    def test_wrappers_do_not_hide_the_command(self):
        self.assertIn("rg", self._rewrite("cd /srv/app && rtk rg pattern"))

    def test_commands_that_need_a_working_directory_are_left_alone(self):
        # For these the `cd` is correct: they resolve config from the working
        # directory, so there is no mechanical rewrite to offer.
        self._assert_none(
            "cd /srv/app && just check",
            "cd /srv/app && pnpm test",
            "cd /srv/app && cargo build",
            "cd /srv/app && make",
            "cd /srv/app && ./scripts/thing.sh",
        )

    def test_writers_are_not_in_scope(self):
        self._assert_none("cd /srv/app && sed -i s/a/b/ f.txt", "cd /srv/app && tee out.txt")

    def test_no_leading_cd(self):
        self._assert_none("git status", "rg pattern .", "ls -la")

    def test_or_is_not_a_separator(self):
        # `cd d || exit 1` is error handling; the command that would run on
        # failure is not something the `cd` scopes.
        self._assert_none("cd /srv/app || exit 1")


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
        return sorted(self.destination.glob("raven-cd-scope-*"))

    def test_first_offender_gets_one_sentence_naming_the_rewrite(self):
        output = json.loads(self._run("cd /srv/app && git status"))["hookSpecificOutput"]
        self.assertEqual(output["hookEventName"], "PreToolUse")
        self.assertIn("git -C /srv/app status", output["additionalContext"])
        self.assertEqual(len(self._stamps()), 1)

    def test_nothing_is_said_a_second_time(self):
        self._run("cd /srv/app && git status")
        self.assertEqual(self._run("cd /srv/app && rg pattern"), "")

    def test_sessions_are_independent(self):
        self._run("cd /srv/app && git status", session_id="s-1")
        self.assertNotEqual(self._run("cd /srv/app && git status", session_id="s-2"), "")
        self.assertEqual(len(self._stamps()), 2)

    def test_no_session_id_means_no_nudge_and_no_stamp(self):
        self.assertEqual(self._run("cd /srv/app && git status", session_id=None), "")
        self.assertEqual(self._stamps(), [])

    def test_a_command_with_no_rewrite_leaves_no_stamp(self):
        self.assertEqual(self._run("cd /srv/app && just check"), "")
        self.assertEqual(self._stamps(), [])

    def test_malformed_payload_is_silent(self):
        result = subprocess.run(
            [sys.executable, str(HOOK)],
            input="not json",
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
