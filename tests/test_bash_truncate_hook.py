"""The Bash result truncator: head, tail, and a path to the whole.

Unit tests drive the pure functions from the template file. End-to-end tests
copy the hook into a temporary *installed* layout -- `<root>/.claude/hooks/`
beside `<root>/.raven/` -- because the hook finds its config and its shared
TOML reader by walking up from its own install path, and in the template
tree that walk lands in `common/`, which has no `.raven/config.toml`.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from helpers import REPO_ROOT, RavenTestCase, load_script_module

HOOK = REPO_ROOT / "common" / ".claude" / "hooks" / "raven-post-bash-truncate.py"
RAVEN_CONFIG = REPO_ROOT / "common" / ".raven" / "git-hooks" / "lib" / "raven_config.py"


def _module():
    return load_script_module("raven_post_bash_truncate", HOOK)


class TruncateTests(RavenTestCase):
    def test_output_within_the_limit_is_left_alone(self):
        text = "\n".join(f"line {i}" for i in range(150)) + "\n"
        self.assertIsNone(_module().truncate(text, 150, "/tmp/x.log"))

    def test_oversized_output_keeps_head_tail_and_names_the_file(self):
        module = _module()
        text = "\n".join(f"line {i}" for i in range(400)) + "\n"
        result = module.truncate(text, 150, "/tmp/full.log")
        assert result is not None
        lines = result.splitlines()
        self.assertEqual(lines[0], "line 0")
        self.assertEqual(lines[39], "line 39")
        self.assertIn("250 of 400 lines omitted", lines[40])
        self.assertIn("/tmp/full.log", lines[40])
        self.assertEqual(lines[41], "line 290")
        self.assertEqual(lines[-1], "line 399")
        self.assertEqual(len(lines), 151)

    def test_the_tail_gets_what_the_head_leaves(self):
        # A test runner prints its verdict last; the tail must never be
        # squeezed out by the head when the limit is small.
        result = _module().truncate("\n".join(str(i) for i in range(100)), 20, "/tmp/f")
        assert result is not None
        lines = result.splitlines()
        self.assertEqual(lines[:10], [str(i) for i in range(10)])
        self.assertEqual(lines[-10:], [str(i) for i in range(90, 100)])

    def test_zero_limit_means_off(self):
        self.assertIsNone(_module().truncate("a\nb\nc", 0, "/tmp/f"))


class ParseMaxLinesTests(RavenTestCase):
    def test_default_when_section_absent(self):
        module = _module()
        self.assertEqual(module.parse_max_lines("[skeleton]\nread_gate = true\n"), 150)

    def test_reads_the_configured_value(self):
        self.assertEqual(_module().parse_max_lines("[bash_output]\nmax_lines = 80\n"), 80)

    def test_zero_is_honored_as_off(self):
        self.assertEqual(_module().parse_max_lines("[bash_output]\nmax_lines = 0\n"), 0)

    def test_garbage_keeps_the_default_rather_than_disabling(self):
        module = _module()
        self.assertEqual(module.parse_max_lines("[bash_output]\nmax_lines = lots\n"), 150)
        self.assertEqual(module.parse_max_lines("[bash_output]\nmax_lines = -5\n"), 150)


class EndToEndTests(RavenTestCase):
    """Run the hook from an installed layout with a private temp directory."""

    def _install(self, config: str) -> Path:
        hooks = self.destination / ".claude" / "hooks"
        hooks.mkdir(parents=True, exist_ok=True)
        shutil.copy(HOOK, hooks / HOOK.name)
        lib = self.destination / ".raven" / "git-hooks" / "lib"
        lib.mkdir(parents=True, exist_ok=True)
        shutil.copy(RAVEN_CONFIG, lib / RAVEN_CONFIG.name)
        (self.destination / ".raven" / "config.toml").write_text(config, encoding="utf-8")
        (self.destination / "tmp").mkdir(exist_ok=True)
        return hooks / HOOK.name

    def _run(self, hook: Path, payload: object) -> subprocess.CompletedProcess:
        env = dict(os.environ, TMPDIR=str(self.destination / "tmp"))
        return subprocess.run(
            [sys.executable, str(hook)],
            input=payload if isinstance(payload, str) else json.dumps(payload),
            capture_output=True,
            text=True,
            cwd=self.destination,
            env=env,
            check=False,
        )

    def _payload(self, lines: int, command: str = "pytest -q") -> dict:
        return {
            "session_id": "abc-123",
            "hook_event_name": "PostToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": command},
            "tool_response": {
                "stdout": "".join(f"out {i}\n" for i in range(lines)),
                "stderr": "warn\n",
                "interrupted": False,
                "isImage": False,
            },
        }

    def test_replaces_an_oversized_result_and_spills_the_whole(self):
        hook = self._install("[bash_output]\nmax_lines = 50\n")
        result = self._run(hook, self._payload(300))
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)["hookSpecificOutput"]
        self.assertEqual(output["hookEventName"], "PostToolUse")
        updated = output["updatedToolOutput"]
        # The rest of the result shape is carried through untouched.
        self.assertEqual(updated["stderr"], "warn\n")
        self.assertFalse(updated["interrupted"])
        self.assertFalse(updated["isImage"])
        self.assertEqual(len(updated["stdout"].splitlines()), 51)
        spill = next(line for line in updated["stdout"].splitlines() if "Full output:" in line)
        path = spill.split("Full output: ", 1)[1].split(" -- ", 1)[0]
        self.assertTrue(path.startswith(str(self.destination / "tmp")), path)
        self.assertEqual(
            Path(path).read_text(encoding="utf-8"), self._payload(300)["tool_response"]["stdout"]
        )

    def test_default_limit_applies_without_a_section(self):
        hook = self._install("[skeleton]\n")
        self.assertEqual(self._run(hook, self._payload(150)).stdout, "")
        self.assertNotEqual(self._run(hook, self._payload(151)).stdout, "")

    def test_zero_turns_it_off(self):
        hook = self._install("[bash_output]\nmax_lines = 0\n")
        self.assertEqual(self._run(hook, self._payload(5000)).stdout, "")

    def test_a_command_already_through_rtk_is_left_alone(self):
        hook = self._install("[bash_output]\nmax_lines = 10\n")
        self.assertEqual(self._run(hook, self._payload(500, "rtk pytest -q")).stdout, "")

    def test_a_result_without_stdout_is_left_alone(self):
        hook = self._install("[bash_output]\nmax_lines = 10\n")
        payload = self._payload(500)
        payload["tool_response"] = "plain text"
        result = self._run(hook, payload)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")

    def test_malformed_payload_fails_open(self):
        hook = self._install("[bash_output]\nmax_lines = 10\n")
        for payload in ("not json", "[]", '{"tool_input": null}'):
            with self.subTest(payload=payload):
                result = self._run(hook, payload)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, "")
