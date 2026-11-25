"""Codex ``apply_patch`` payloads in the post-edit formatter hook (issue #280).

Codex sends the patch text as ``tool_input.command``; the hook formats every
file the patch leaves behind and stays silent about the rest.
"""

from __future__ import annotations

import json
import sys
from io import StringIO
from unittest import mock

from helpers import REPO_ROOT, RavenTestCase, load_script_module

HOOK = REPO_ROOT / "common" / ".claude" / "hooks" / "raven-post-edit-format.py"


def _patch(*lines: str) -> str:
    return "\n".join(["*** Begin Patch", *lines, "*** End Patch"])


class PostEditFormatApplyPatchTests(RavenTestCase):
    def _run(self, payload: dict) -> tuple[int, list[list[str]]]:
        module = load_script_module("raven_post_edit_format", HOOK)
        with (
            mock.patch.object(module.shutil, "which", return_value="/bin/tool"),
            mock.patch.object(module, "run") as run,
            mock.patch.object(sys, "stdin", StringIO(json.dumps(payload))),
        ):
            code = module.main()
        return code, [call.args[0] for call in run.call_args_list]

    def _payload(self, command: str, **extra: object) -> dict:
        return {
            "hook_event_name": "PostToolUse",
            "tool_name": "apply_patch",
            "tool_input": {"command": command},
            **extra,
        }

    def test_multi_file_patch_formats_each_surviving_file(self):
        first = self.destination / "a.py"
        second = self.destination / "b.py"
        first.write_text("x=1\n", encoding="utf-8")
        second.write_text("y=2\n", encoding="utf-8")
        command = _patch(
            f"*** Update File: {first}", "@@", "-a", "+b", f"*** Add File: {second}", "+y=2"
        )
        code, calls = self._run(self._payload(command))
        self.assertEqual(code, 0)
        self.assertEqual(calls, [["ruff", "format", str(first)], ["ruff", "format", str(second)]])

    def test_deleted_file_and_move_source_are_skipped(self):
        target = self.destination / "new.py"
        target.write_text("x=1\n", encoding="utf-8")
        command = _patch(
            f"*** Delete File: {self.destination / 'old.py'}",
            f"*** Update File: {self.destination / 'moved_from.py'}",
            f"*** Move to: {target}",
        )
        code, calls = self._run(self._payload(command))
        self.assertEqual(code, 0)
        self.assertEqual(calls, [["ruff", "format", str(target)]])

    def test_environment_id_patch_is_skipped(self):
        existing = self.destination / "a.py"
        existing.write_text("x=1\n", encoding="utf-8")
        command = (
            "*** Begin Patch\n*** Environment ID: remote\n"
            f"*** Update File: {existing}\n@@\n-a\n+b\n*** End Patch"
        )
        code, calls = self._run(self._payload(command))
        self.assertEqual(code, 0)
        self.assertEqual(calls, [])

    def test_relative_path_is_resolved_against_payload_cwd(self):
        (self.destination / "pkg").mkdir()
        existing = self.destination / "pkg" / "mod.py"
        existing.write_text("x=1\n", encoding="utf-8")
        command = _patch("*** Update File: pkg/mod.py", "@@", "-a", "+b")
        code, calls = self._run(self._payload(command, cwd=str(self.destination)))
        self.assertEqual(code, 0)
        self.assertEqual(calls, [["ruff", "format", str(self.destination / "pkg" / "mod.py")]])

    def test_legacy_file_path_payload_still_formats(self):
        existing = self.destination / "a.py"
        existing.write_text("x=1\n", encoding="utf-8")
        payload = {"tool_name": "Write", "tool_input": {"file_path": str(existing)}}
        code, calls = self._run(payload)
        self.assertEqual(code, 0)
        self.assertEqual(calls, [["ruff", "format", str(existing)]])
