"""Codex ``apply_patch`` payloads in the post-edit formatter hook (issue #280).

Codex sends the patch text as ``tool_input.command``; the hook formats every
file the patch leaves behind and stays silent about the rest.
"""

from __future__ import annotations

import json
import subprocess
import sys
from io import StringIO
from pathlib import Path
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


class PostEditFormatLanguageTests(RavenTestCase):
    """Per-language dispatch, project roots, and the bounded ``run`` (issue #285)."""

    def _file(self, relative: str, text: str = "x\n") -> Path:
        path = self.destination / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def _run(self, path: Path, tools=("*",), monotonic=None, side_effect=None):
        module = load_script_module("raven_post_edit_format", HOOK)

        def which(name, path=None):
            if path is not None:
                return None
            return f"/bin/{name}" if "*" in tools or name in tools else None

        payload = {"tool_name": "Write", "tool_input": {"file_path": str(path)}}
        patches = [
            mock.patch.object(module.shutil, "which", side_effect=which),
            mock.patch.object(module.subprocess, "run", side_effect=side_effect),
            mock.patch.object(sys, "stdin", StringIO(json.dumps(payload))),
        ]
        if monotonic is not None:
            patches.append(mock.patch.object(module.time, "monotonic", side_effect=monotonic))
        with patches[0], patches[1] as sub, patches[2]:
            if monotonic is not None:
                with patches[3]:
                    code = module.main()
            else:
                code = module.main()
        self.assertEqual(code, 0)
        return sub.call_args_list

    def _argv_cwd(self, calls):
        return [(call.args[0], call.kwargs.get("cwd")) for call in calls]

    def test_go_runs_gofmt(self):
        path = self._file("main.go")
        self.assertEqual(self._argv_cwd(self._run(path)), [(["gofmt", "-w", str(path)], None)])

    def test_rust_passes_crate_edition(self):
        self._file("Cargo.toml", '[package]\nname = "a"\nedition = "2021"\n')
        path = self._file("src/lib.rs")
        (self.destination / ".git").mkdir()
        calls = self._run(path)
        self.assertEqual(
            self._argv_cwd(calls), [(["rustfmt", "--edition", "2021", str(path)], None)]
        )

    def test_rust_workspace_member_uses_root_edition(self):
        (self.destination / ".git").mkdir()
        self._file("Cargo.toml", '[workspace.package]\nedition = "2024"\n')
        self._file("crates/a/Cargo.toml", "[package]\nedition.workspace = true\n")
        path = self._file("crates/a/src/lib.rs")
        calls = self._run(path)
        self.assertEqual(
            self._argv_cwd(calls), [(["rustfmt", "--edition", "2024", str(path)], None)]
        )

    def test_rust_without_cargo_has_no_edition(self):
        (self.destination / ".git").mkdir()
        path = self._file("lone.rs")
        self.assertEqual(self._argv_cwd(self._run(path)), [(["rustfmt", str(path)], None)])

    def test_elixir_runs_from_mix_root(self):
        self._file("mix.exs")
        for name in ("lib/a.ex", "test/a_test.exs"):
            with self.subTest(name=name):
                path = self._file(name)
                calls = self._run(path)
                self.assertEqual(
                    self._argv_cwd(calls), [(["mix", "format", str(path)], self.destination)]
                )

    def test_elixir_without_mix_project_is_skipped(self):
        (self.destination / ".git").mkdir()
        path = self._file("lib/a.ex")
        self.assertEqual(self._run(path), [])

    def test_lua_runs_stylua_from_project_root(self):
        (self.destination / ".git").mkdir()
        path = self._file("src/init.lua")
        calls = self._run(path)
        self.assertEqual(self._argv_cwd(calls), [(["stylua", str(path)], self.destination)])

    def test_ruby_in_bundle_uses_bundle_exec(self):
        self._file("Gemfile")
        path = self._file("app/model.rb")
        calls = self._run(path)
        expected = ["bundle", "exec", "rubocop", "--fix-layout", "--force-exclusion", str(path)]
        self.assertEqual(self._argv_cwd(calls), [(expected, self.destination)])

    def test_ruby_in_bundle_without_bundle_is_skipped(self):
        self._file("Gemfile")
        path = self._file("model.rb")
        self.assertEqual(self._run(path, tools=("rubocop",)), [])

    def test_ruby_without_gemfile_uses_bare_rubocop(self):
        (self.destination / ".git").mkdir()
        path = self._file("model.rb")
        calls = self._run(path)
        expected = ["rubocop", "--fix-layout", "--force-exclusion", str(path)]
        self.assertEqual(self._argv_cwd(calls), [(expected, None)])

    def test_mjs_runs_prettier(self):
        path = self._file("prettier.config.mjs")
        self.assertEqual(
            self._argv_cwd(self._run(path)), [(["/bin/prettier", "--write", str(path)], None)]
        )

    def test_local_prettier_is_preferred_over_path(self):
        (self.destination / ".git").mkdir()
        path = self._file("web/src/a.ts")
        local_bin = str(self.destination / "web" / "node_modules" / ".bin")
        module = load_script_module("raven_post_edit_format", HOOK)

        def which(name, path=None):
            if path is not None:
                return "/local/prettier" if path == local_bin else None
            return "/bin/prettier"

        with (
            mock.patch.object(module.shutil, "which", side_effect=which),
            mock.patch.object(module.subprocess, "run") as sub,
            mock.patch.object(module, "_deadline", 1e18),
        ):
            self.assertEqual(module._prettier_cmd(path), "/local/prettier")
            module.run(["x"])
        self.assertEqual(sub.call_count, 1)

    def test_existing_argv_is_unchanged(self):
        cases = {
            "a.py": ["ruff", "format"],
            "a.ts": ["/bin/prettier", "--write"],
            "a.swift": ["swift-format", "format", "--in-place"],
        }
        for name, prefix in cases.items():
            with self.subTest(name=name):
                path = self._file(name)
                calls = self._run(path)
                self.assertEqual(self._argv_cwd(calls), [([*prefix, str(path)], None)])

    def test_timeout_and_oserror_are_swallowed(self):
        path = self._file("main.go")
        for error in (subprocess.TimeoutExpired("gofmt", 10), OSError("exec failed")):
            with self.subTest(error=type(error).__name__):
                self.assertEqual(len(self._run(path, side_effect=error)), 1)

    def test_every_call_is_bounded_by_the_per_command_timeout(self):
        path = self._file("main.go")
        for call in self._run(path):
            self.assertLessEqual(call.kwargs["timeout"], 10)

    def test_spent_budget_starts_no_formatter(self):
        path = self._file("main.go")
        # First reading sets the deadline; the next is past it.
        calls = self._run(path, monotonic=[0.0, 21.0, 21.0])
        self.assertEqual(calls, [])

    def test_remaining_budget_shrinks_the_timeout(self):
        path = self._file("main.go")
        calls = self._run(path, monotonic=[0.0, 15.0, 15.0])
        self.assertEqual(calls[0].kwargs["timeout"], 5.0)
