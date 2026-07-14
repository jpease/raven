from __future__ import annotations

import importlib.util
import io
import json
import sys
import tempfile
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path
from typing import cast
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "common" / ".claude" / "scripts" / "raven-session.py"
HOOK_PATH = REPO_ROOT / "common" / ".claude" / "hooks" / "raven-session-checkpoint.py"
CODEX_SCRIPT_PATH = REPO_ROOT / "common" / ".codex" / "scripts" / "raven-session.py"
CODEX_HOOK_PATH = REPO_ROOT / "common" / ".codex" / "hooks" / "raven-session-checkpoint.py"


def load_session():
    spec = importlib.util.spec_from_file_location("raven_session", SCRIPT_PATH)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    # spec_from_file_location yields a SourceFileLoader; cast past the
    # importlib.abc.Loader base, whose typeshed stub omits exec_module.
    cast(SourceFileLoader, spec.loader).exec_module(module)
    return module


class SessionInitTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.raven_dir = self.root / ".raven"
        self.raven_dir.mkdir()
        self.session_file = self.raven_dir / "session.md"

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, args: list[str]) -> int:
        mod = load_session()
        import os

        orig = os.getcwd()
        os.chdir(self.root)
        try:
            return mod.main(args)
        finally:
            os.chdir(orig)

    def test_init_creates_session_file(self):
        rc = self._run(["--init", "greenfield", "unit-a", "unit-b"])
        self.assertEqual(rc, 0)
        self.assertTrue(self.session_file.exists())

    def test_init_records_project_type(self):
        self._run(["--init", "brownfield", "unit-a"])
        content = self.session_file.read_text()
        self.assertIn("**Project Type:** brownfield", content)

    def test_init_records_units_with_first_as_current(self):
        self._run(["--init", "greenfield", "unit-a", "unit-b", "unit-c"])
        content = self.session_file.read_text()
        self.assertIn("- [ ] unit-a (current)", content)
        self.assertIn("- [ ] unit-b", content)
        self.assertIn("- [ ] unit-c", content)

    def test_init_fails_if_session_already_exists(self):
        self._run(["--init", "greenfield", "unit-a"])
        rc = self._run(["--init", "greenfield", "unit-b"])
        self.assertNotEqual(rc, 0)

    def test_status_prints_current_unit(self):
        self._run(["--init", "greenfield", "unit-a", "unit-b"])
        import io
        from contextlib import redirect_stdout

        f = io.StringIO()
        with redirect_stdout(f):
            self._run(["--status"])
        output = f.getvalue()
        self.assertIn("unit-a", output)
        self.assertIn("current", output.lower())


class SessionValidateCompleteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.raven_dir = self.root / ".raven"
        self.raven_dir.mkdir()
        self.session_file = self.raven_dir / "session.md"

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, args: list[str]) -> int:
        mod = load_session()
        import os

        orig = os.getcwd()
        os.chdir(self.root)
        try:
            return mod.main(args)
        finally:
            os.chdir(orig)

    def _init(self, *units: str) -> None:
        self._run(["--init", "greenfield", *list(units)])

    def test_validate_passes_for_current_unit(self):
        self._init("unit-a", "unit-b")
        rc = self._run(["--validate", "unit-a"])
        self.assertEqual(rc, 0)

    def test_validate_fails_for_wrong_unit(self):
        self._init("unit-a", "unit-b")
        rc = self._run(["--validate", "unit-b"])
        self.assertNotEqual(rc, 0)

    def test_validate_fails_for_already_completed_unit(self):
        self._init("unit-a", "unit-b")
        self._run(["--complete", "unit-a"])
        rc = self._run(["--validate", "unit-a"])
        self.assertNotEqual(rc, 0)

    def test_validate_fails_when_no_session(self):
        rc = self._run(["--validate", "unit-a"])
        self.assertNotEqual(rc, 0)

    def test_complete_marks_unit_done(self):
        self._init("unit-a", "unit-b")
        self._run(["--complete", "unit-a"])
        content = self.session_file.read_text()
        self.assertIn("- [x] unit-a", content)

    def test_complete_advances_current_to_next_unit(self):
        self._init("unit-a", "unit-b")
        self._run(["--complete", "unit-a"])
        content = self.session_file.read_text()
        self.assertIn("- [ ] unit-b (current)", content)

    def test_complete_records_timestamp(self):
        self._init("unit-a")
        self._run(["--complete", "unit-a"])
        content = self.session_file.read_text()
        self.assertRegex(content, r"completed \d{4}-\d{2}-\d{2}T")

    def test_complete_fails_for_wrong_unit(self):
        self._init("unit-a", "unit-b")
        rc = self._run(["--complete", "unit-b"])
        self.assertNotEqual(rc, 0)

    def test_complete_fails_when_no_session(self):
        rc = self._run(["--complete", "unit-a"])
        self.assertNotEqual(rc, 0)


class SessionArchiveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.raven_dir = self.root / ".raven"
        self.raven_dir.mkdir()
        self.session_file = self.raven_dir / "session.md"
        self.archive_file = self.raven_dir / "session-archive.md"

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, args: list[str]) -> int:
        mod = load_session()
        import os

        orig = os.getcwd()
        os.chdir(self.root)
        try:
            return mod.main(args)
        finally:
            os.chdir(orig)

    def test_archive_moves_completed_units_to_archive_file(self):
        self._run(["--init", "greenfield", "unit-a", "unit-b", "unit-c"])
        self._run(["--complete", "unit-a"])
        self._run(["--complete", "unit-b"])
        self._run(["--archive"])
        archive = self.archive_file.read_text()
        self.assertIn("unit-a", archive)
        self.assertIn("unit-b", archive)

    def test_archive_removes_completed_units_from_session(self):
        self._run(["--init", "greenfield", "unit-a", "unit-b", "unit-c"])
        self._run(["--complete", "unit-a"])
        self._run(["--archive"])
        session = self.session_file.read_text()
        self.assertNotIn("unit-a", session)
        self.assertIn("unit-b", session)

    def test_archive_preserves_pending_units_in_session(self):
        self._run(["--init", "greenfield", "unit-a", "unit-b"])
        self._run(["--complete", "unit-a"])
        self._run(["--archive"])
        session = self.session_file.read_text()
        self.assertIn("unit-b", session)

    def test_archive_appends_to_existing_archive(self):
        self._run(["--init", "greenfield", "unit-a", "unit-b"])
        self._run(["--complete", "unit-a"])
        self._run(["--archive"])
        self._run(["--complete", "unit-b"])
        self._run(["--archive"])
        archive = self.archive_file.read_text()
        self.assertIn("unit-a", archive)
        self.assertIn("unit-b", archive)


class ExistingIgnorePatternsTests(unittest.TestCase):
    def _patterns(self, text: str):
        return load_session()._existing_ignore_patterns(text)

    def test_comment_is_not_a_pattern(self):
        self.assertNotIn(".raven/session.md", self._patterns("# Example only: .raven/session.md\n"))

    def test_exact_entry_is_a_pattern(self):
        self.assertIn(".raven/session.md", self._patterns(".raven/session.md\n"))

    def test_surrounding_whitespace_is_ignored(self):
        self.assertIn(".raven/session.md", self._patterns("   .raven/session.md  \n"))

    def test_longer_path_is_not_the_entry(self):
        patterns = self._patterns("project/.raven/session.md.bak\n")
        self.assertNotIn(".raven/session.md", patterns)


class UpdateGitignoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.gitignore = self.root / ".gitignore"

    def tearDown(self):
        self.tmp.cleanup()

    def _run_update(self):
        import os

        mod = load_session()
        orig = os.getcwd()
        os.chdir(self.root)
        try:
            mod._update_gitignore()
        finally:
            os.chdir(orig)

    def _lines(self):
        return [
            line.strip()
            for line in self.gitignore.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]

    ENTRIES = (".raven/session.md", ".raven/session.lock", ".raven/session-archive.md")

    def test_adds_all_entries_when_missing(self):
        self._run_update()
        for entry in self.ENTRIES:
            self.assertIn(entry, self._lines())

    def test_comment_containing_entry_does_not_suppress_real_rule(self):
        # Regression for issue #43: a comment mentioning the path must not be
        # treated as the ignore rule via substring membership.
        self.gitignore.write_text("# Example only: .raven/session.md\n", encoding="utf-8")
        self._run_update()
        self.assertIn(".raven/session.md", self._lines())

    def test_longer_path_does_not_suppress_real_rule(self):
        self.gitignore.write_text(".raven/session.md.bak\n", encoding="utf-8")
        self._run_update()
        self.assertEqual(self._lines().count(".raven/session.md"), 1)

    def test_existing_exact_entry_is_not_duplicated(self):
        self.gitignore.write_text(
            ".raven/session.md\n.raven/session.lock\n.raven/session-archive.md\n",
            encoding="utf-8",
        )
        self._run_update()
        for entry in self.ENTRIES:
            self.assertEqual(self._lines().count(entry), 1)

    def test_whitespace_padded_existing_entry_is_not_duplicated(self):
        self.gitignore.write_text("   .raven/session.md  \n", encoding="utf-8")
        self._run_update()
        self.assertEqual(self._lines().count(".raven/session.md"), 1)


class SessionInitGitignoreTests(unittest.TestCase):
    """End-to-end: after --init, all three session-state paths are ignored even
    when .gitignore already contains a misleading comment (issue #43)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / ".raven").mkdir()
        self.gitignore = self.root / ".gitignore"

    def tearDown(self):
        self.tmp.cleanup()

    def test_init_ignores_all_session_paths(self):
        import os

        self.gitignore.write_text("# Example only: .raven/session.md\n", encoding="utf-8")
        mod = load_session()
        orig = os.getcwd()
        os.chdir(self.root)
        try:
            self.assertEqual(mod.main(["--init", "brownfield", "unit-a"]), 0)
        finally:
            os.chdir(orig)
        present = mod._existing_ignore_patterns(self.gitignore.read_text(encoding="utf-8"))
        for entry in (".raven/session.md", ".raven/session.lock", ".raven/session-archive.md"):
            self.assertIn(entry, present)


class MultiWordUnitNameTests(unittest.TestCase):
    """Regression for #34: unit names containing spaces must round-trip."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.raven_dir = self.root / ".raven"
        self.raven_dir.mkdir()
        self.session_file = self.raven_dir / "session.md"

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, args: list[str]) -> int:
        mod = load_session()
        import os

        orig = os.getcwd()
        os.chdir(self.root)
        try:
            return mod.main(args)
        finally:
            os.chdir(orig)

    def test_status_preserves_multi_word_unit_names(self):
        self._run(["--init", "brownfield", "first unit", "second unit"])
        from contextlib import redirect_stdout

        f = io.StringIO()
        with redirect_stdout(f):
            self._run(["--status"])
        out = f.getvalue()
        self.assertIn("Current unit : first unit", out)
        self.assertIn("Remaining    : second unit", out)

    def test_complete_accepts_multi_word_current_unit(self):
        self._run(["--init", "brownfield", "first unit", "second unit"])
        rc = self._run(["--complete", "first unit"])
        self.assertEqual(rc, 0)
        content = self.session_file.read_text()
        self.assertIn("- [x] first unit", content)
        self.assertIn("- [ ] second unit (current)", content)

    def test_render_parse_round_trip_with_issue_and_completion(self):
        mod = load_session()
        data = {
            "project_type": "brownfield",
            "started": "2026-01-01T00:00:00Z",
            "last_updated": "2026-01-01T00:00:00Z",
            "parent_issue": None,
            "units": [
                {
                    "name": "first unit",
                    "done": True,
                    "issue": "#12",
                    "completed_at": "2026-01-02T03:04:05Z",
                },
                {
                    "name": "second unit: add parser",
                    "done": False,
                    "issue": "#13",
                    "completed_at": None,
                },
            ],
            "context_lines": [""],
        }
        reparsed = mod._parse_session(mod._render_session(data))
        first, second = reparsed["units"]
        self.assertEqual(first["name"], "first unit")
        self.assertEqual(first["issue"], "#12")
        self.assertEqual(first["completed_at"], "2026-01-02T03:04:05Z")
        self.assertEqual(second["name"], "second unit: add parser")
        self.assertEqual(second["issue"], "#13")


def load_hook():
    spec = importlib.util.spec_from_file_location("raven_session_checkpoint", HOOK_PATH)
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    # spec_from_file_location yields a SourceFileLoader; cast past the
    # importlib.abc.Loader base, whose typeshed stub omits exec_module.
    cast(SourceFileLoader, spec.loader).exec_module(mod)
    return mod


def _claude_payload(command: str) -> str:
    return json.dumps({"tool_input": {"command": command}})


class CheckpointHookTests(unittest.TestCase):
    def setUp(self):
        import shutil

        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.raven_dir = self.root / ".raven"
        self.raven_dir.mkdir()
        self.config_file = self.raven_dir / "config.toml"
        # Simulate an installed project: the hook calls the script at this path
        scripts_dir = self.root / ".claude" / "scripts"
        scripts_dir.mkdir(parents=True)
        shutil.copy(SCRIPT_PATH, scripts_dir / "raven-session.py")

    def tearDown(self):
        self.tmp.cleanup()

    def _run_hook(self, payload_str: str) -> int:
        mod = load_hook()
        import os

        orig = os.getcwd()
        os.chdir(self.root)
        try:
            with patch("sys.stdin", io.StringIO(payload_str)):
                return mod.main()
        finally:
            os.chdir(orig)

    def test_hook_allows_when_enforcement_disabled(self):
        self.config_file.write_text(
            "[lifecycle]\ncheckpoint_enforcement = false\n", encoding="utf-8"
        )
        rc = self._run_hook(
            _claude_payload("python .claude/scripts/raven-session.py --complete unit-a")
        )
        self.assertEqual(rc, 0)

    def test_hook_denies_when_no_session(self):
        self.config_file.write_text(
            "[lifecycle]\ncheckpoint_enforcement = true\n", encoding="utf-8"
        )
        rc = self._run_hook(
            _claude_payload("python .claude/scripts/raven-session.py --complete unit-a")
        )
        self.assertNotEqual(rc, 0)

    def test_hook_allows_valid_checkpoint(self):
        self.config_file.write_text(
            "[lifecycle]\ncheckpoint_enforcement = true\n", encoding="utf-8"
        )
        import os

        orig = os.getcwd()
        os.chdir(self.root)
        try:
            mod = load_session()
            mod.main(["--init", "greenfield", "unit-a", "unit-b"])
        finally:
            os.chdir(orig)
        rc = self._run_hook(
            _claude_payload("python .claude/scripts/raven-session.py --complete unit-a")
        )
        self.assertEqual(rc, 0)

    def test_hook_denies_wrong_unit(self):
        self.config_file.write_text(
            "[lifecycle]\ncheckpoint_enforcement = true\n", encoding="utf-8"
        )
        import os

        orig = os.getcwd()
        os.chdir(self.root)
        try:
            mod = load_session()
            mod.main(["--init", "greenfield", "unit-a", "unit-b"])
        finally:
            os.chdir(orig)
        rc = self._run_hook(
            _claude_payload("python .claude/scripts/raven-session.py --complete unit-b")
        )
        self.assertNotEqual(rc, 0)

    def test_hook_allows_unrelated_command_without_session(self):
        # Core fix for #104: an unrelated Bash command must not be denied just
        # because there is no active session. With enforcement ON and no
        # .raven/session.md, `git status` should pass through untouched.
        self.config_file.write_text(
            "[lifecycle]\ncheckpoint_enforcement = true\n", encoding="utf-8"
        )
        rc = self._run_hook(_claude_payload("git status"))
        self.assertEqual(rc, 0)

    def test_hook_allows_command_mentioning_complete_word(self):
        # A command that merely mentions --complete but does not invoke
        # raven-session.py must not be treated as a checkpoint completion.
        self.config_file.write_text(
            "[lifecycle]\ncheckpoint_enforcement = true\n", encoding="utf-8"
        )
        rc = self._run_hook(_claude_payload("echo --complete foo"))
        self.assertEqual(rc, 0)

    def test_completion_unit_handles_shell_quoted_name(self):
        mod = load_hook()
        unit = mod._completion_unit(
            'python .claude/scripts/raven-session.py --complete "first unit"'
        )
        self.assertEqual(unit, "first unit")

    def test_completion_unit_ignores_non_session_command(self):
        mod = load_hook()
        self.assertIsNone(mod._completion_unit("echo --complete foo"))
        self.assertIsNone(mod._completion_unit("git status"))

    def test_hook_allows_valid_multi_word_checkpoint(self):
        self.config_file.write_text(
            "[lifecycle]\ncheckpoint_enforcement = true\n", encoding="utf-8"
        )
        import os

        orig = os.getcwd()
        os.chdir(self.root)
        try:
            mod = load_session()
            mod.main(["--init", "greenfield", "first unit", "second unit"])
        finally:
            os.chdir(orig)
        rc = self._run_hook(
            _claude_payload('python .claude/scripts/raven-session.py --complete "first unit"')
        )
        self.assertEqual(rc, 0)


def load_codex_hook():
    spec = importlib.util.spec_from_file_location("raven_session_checkpoint_codex", CODEX_HOOK_PATH)
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    # spec_from_file_location yields a SourceFileLoader; cast past the
    # importlib.abc.Loader base, whose typeshed stub omits exec_module.
    cast(SourceFileLoader, spec.loader).exec_module(mod)
    return mod


def _codex_payload(command: str) -> str:
    return json.dumps(
        {
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": command},
        }
    )


class CodexCheckpointHookTests(unittest.TestCase):
    """Regression for #105: the Codex checkpoint hook must resolve
    ``.codex/scripts/raven-session.py``, not the Claude adapter's path, in a
    Codex-only install (one without a ``.claude`` tree)."""

    def setUp(self):
        import shutil

        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.raven_dir = self.root / ".raven"
        self.raven_dir.mkdir()
        self.config_file = self.raven_dir / "config.toml"
        # Simulate a Codex-only installed project: no .claude tree at all, the
        # session CLI lives only under .codex/scripts.
        scripts_dir = self.root / ".codex" / "scripts"
        scripts_dir.mkdir(parents=True)
        shutil.copy(CODEX_SCRIPT_PATH, scripts_dir / "raven-session.py")

    def tearDown(self):
        self.tmp.cleanup()

    def _run_hook(self, payload_str: str) -> tuple[int, str]:
        # A Codex PreToolUse hook always exits 0: an allow is silent, a deny
        # is signaled via a "permissionDecision": "deny" JSON payload on
        # stdout rather than a nonzero return code. So callers must inspect
        # stdout, not just the return code, to tell allow from deny.
        mod = load_codex_hook()
        import os

        orig = os.getcwd()
        os.chdir(self.root)
        try:
            with patch("sys.stdin", io.StringIO(payload_str)):
                f = io.StringIO()
                with patch("sys.stdout", f):
                    rc = mod.main()
                return rc, f.getvalue()
        finally:
            os.chdir(orig)

    def test_hook_allows_valid_checkpoint(self):
        self.config_file.write_text(
            "[lifecycle]\ncheckpoint_enforcement = true\n", encoding="utf-8"
        )
        import os

        orig = os.getcwd()
        os.chdir(self.root)
        try:
            mod = load_session()
            mod.main(["--init", "greenfield", "unit-a", "unit-b"])
        finally:
            os.chdir(orig)
        rc, output = self._run_hook(
            _codex_payload("python .codex/scripts/raven-session.py --complete unit-a")
        )
        self.assertEqual(rc, 0)
        self.assertNotIn("deny", output, output)

    def test_claude_hook_source_references_claude_scripts_path(self):
        source = HOOK_PATH.read_text(encoding="utf-8")
        self.assertIn(".claude/scripts/raven-session.py", source)

    def test_codex_hook_source_references_codex_scripts_path(self):
        source = CODEX_HOOK_PATH.read_text(encoding="utf-8")
        self.assertIn(".codex/scripts/raven-session.py", source)
        self.assertNotIn(".claude/scripts/raven-session.py", source)


def _find_checkpoint_entry(config: dict) -> dict:
    for entry in config["hooks"]["PreToolUse"]:
        for hook in entry.get("hooks", []):
            if "raven-session-checkpoint.py" in hook.get("command", ""):
                return entry
    raise AssertionError("no PreToolUse entry invokes raven-session-checkpoint.py")


class CheckpointConfigTests(unittest.TestCase):
    """The installed configs must invoke the checkpoint hook for Bash calls.

    Hook matchers select tools, not Bash command text, so the old
    ``raven-session.*--complete`` matcher never fired (issue #104).
    """

    def test_claude_settings_matcher_targets_bash(self):
        config = json.loads(
            (REPO_ROOT / "common" / ".claude" / "settings.json").read_text(encoding="utf-8")
        )
        entry = _find_checkpoint_entry(config)
        self.assertEqual(entry["matcher"], "Bash")

    def test_codex_hooks_matcher_targets_bash(self):
        config = json.loads(
            (REPO_ROOT / "common" / ".codex" / "hooks.json").read_text(encoding="utf-8")
        )
        entry = _find_checkpoint_entry(config)
        self.assertEqual(entry["matcher"], "^Bash$")


class EnforcementEnabledTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.raven_dir = self.root / ".raven"
        self.raven_dir.mkdir()
        self.config_file = self.raven_dir / "config.toml"

    def tearDown(self):
        self.tmp.cleanup()

    def _enabled(self, config_text: str | None) -> bool:
        if config_text is not None:
            self.config_file.write_text(config_text, encoding="utf-8")
        mod = load_hook()
        import os

        orig = os.getcwd()
        os.chdir(self.root)
        try:
            return mod._enforcement_enabled()
        finally:
            os.chdir(orig)

    def test_absent_config_defaults_enabled(self):
        self.assertTrue(self._enabled(None))

    def test_active_true_with_commented_false_stays_enabled(self):
        self.assertTrue(
            self._enabled(
                "[lifecycle]\n"
                "checkpoint_enforcement = true\n"
                "# checkpoint_enforcement = false  # old example\n"
            )
        )

    def test_active_false_disables(self):
        self.assertFalse(self._enabled("[lifecycle]\ncheckpoint_enforcement = false\n"))

    def test_absent_key_defaults_enabled(self):
        self.assertTrue(self._enabled("[lifecycle]\n"))

    def test_false_in_other_section_does_not_disable(self):
        self.assertTrue(
            self._enabled(
                "[lifecycle]\ncheckpoint_enforcement = true\n"
                "\n[other]\ncheckpoint_enforcement = false\n"
            )
        )

    def test_similarly_named_key_does_not_disable(self):
        self.assertTrue(
            self._enabled(
                "[lifecycle]\n"
                "checkpoint_enforcement_legacy = false\n"
                "checkpoint_enforcement = true\n"
            )
        )

    def test_malformed_value_fails_safe_enabled(self):
        self.assertTrue(self._enabled('[lifecycle]\ncheckpoint_enforcement = "maybe"\n'))
