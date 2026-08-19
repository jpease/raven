import json
import os
import subprocess
import sys
import unittest

from helpers import REPO_ROOT, RavenTestCase, load_script_module

GUARD_SCRIPT = REPO_ROOT / "common" / ".claude" / "hooks" / "raven-skeleton-read-guard.py"


def _module():
    return load_script_module("raven_skeleton_read_guard", GUARD_SCRIPT)


# The gate denies only when a backend the raven-skeleton helper can use is on
# PATH -- pointing a reader at a helper that cannot run would be worse than
# allowing the read. Asked of the guard module rather than restated here, so
# the two cannot drift. The end-to-end deny case therefore has a precondition
# the machine may not meet: CI's self-check job installs neither ast-grep nor
# ripgrep, and the test failed there on every run while passing on any
# developer machine that happens to have one.
HAVE_SKELETON_BACKEND = _module().skeleton_backend_available()


class IsUnboundedReadTests(RavenTestCase):
    def test_no_offset_or_limit_is_unbounded(self):
        module = _module()
        self.assertTrue(module.is_unbounded_read({"file_path": "/a.py"}))

    def test_offset_or_limit_makes_it_bounded(self):
        module = _module()
        self.assertFalse(module.is_unbounded_read({"file_path": "/a.py", "offset": 10}))
        self.assertFalse(module.is_unbounded_read({"file_path": "/a.py", "limit": 50}))


class ShouldGateTests(RavenTestCase):
    def _gate(self, **kw):
        defaults = {
            "tool_input": {"file_path": "/a.py"},
            "line_count": 2000,
            "enabled": True,
            "threshold": 500,
            "supported": True,
        }
        defaults.update(kw)
        return _module().should_gate(**defaults)

    def test_gates_large_unbounded_supported_read(self):
        self.assertTrue(self._gate())

    def test_does_not_gate_when_disabled(self):
        self.assertFalse(self._gate(enabled=False))

    def test_does_not_gate_unsupported_language(self):
        self.assertFalse(self._gate(supported=False))

    def test_does_not_gate_bounded_read(self):
        self.assertFalse(self._gate(tool_input={"file_path": "/a.py", "offset": 1, "limit": 100}))

    def test_does_not_gate_small_file(self):
        self.assertFalse(self._gate(line_count=120))

    def test_gates_exactly_at_threshold(self):
        self.assertTrue(self._gate(line_count=500))

    def test_does_not_gate_without_a_skeleton_backend(self):
        """Denying is only useful when the helper it points at can answer.

        With neither ast-grep nor rg installed, raven-skeleton returns
        "No skeleton available", so a denial would send the reader to a dead end
        rather than a cheaper path.
        """
        self.assertFalse(self._gate(backend_available=False))

    def test_backend_detection_reflects_what_is_on_path(self):
        module = _module()
        self.assertEqual(module.SKELETON_BACKENDS, ("ast-grep", "rg"))
        self.assertIsInstance(module.skeleton_backend_available(), bool)


class ParseGateConfigTests(RavenTestCase):
    def test_default_is_disabled_with_default_threshold(self):
        module = _module()
        self.assertEqual(module.parse_gate_config(""), (False, 500))

    def test_enabled_when_read_gate_true(self):
        module = _module()
        self.assertEqual(module.parse_gate_config("[skeleton]\nread_gate = true\n"), (True, 500))

    def test_explicit_skeleton_false_stays_disabled(self):
        module = _module()
        self.assertEqual(module.parse_gate_config("[skeleton]\nread_gate = false\n"), (False, 500))

    def test_threshold_key_is_not_confused_with_gate_key(self):
        module = _module()
        # The threshold key shares the read_gate prefix; it must not enable the gate.
        self.assertEqual(
            module.parse_gate_config("[skeleton]\nread_gate_threshold_lines = 800\n"), (False, 800)
        )

    def test_reads_both_gate_and_threshold(self):
        module = _module()
        text = "[skeleton]\nread_gate = true\nread_gate_threshold_lines = 800\n"
        self.assertEqual(module.parse_gate_config(text), (True, 800))

    def test_keys_outside_skeleton_table_have_no_effect(self):
        module = _module()
        # The exact reproduction from issue #41: an unrelated table must not
        # enable the gate or override the skeleton threshold, and an explicit
        # [skeleton].read_gate = false must win.
        text = (
            "[unrelated]\n"
            "read_gate = true\n"
            "read_gate_threshold_lines = 1\n"
            "\n"
            "[skeleton]\n"
            "read_gate = false\n"
        )
        self.assertEqual(module.parse_gate_config(text), (False, 500))

    def test_root_table_keys_are_ignored(self):
        module = _module()
        # Keys before any table header live in the implicit root table, not
        # [skeleton], so they must not enable the gate.
        self.assertEqual(
            module.parse_gate_config("read_gate = true\nread_gate_threshold_lines = 10\n"),
            (False, 500),
        )

    def test_commented_skeleton_key_has_no_effect(self):
        module = _module()
        self.assertEqual(module.parse_gate_config("[skeleton]\n# read_gate = true\n"), (False, 500))

    def test_trailing_comment_does_not_break_parsing(self):
        module = _module()
        text = (
            "[skeleton]  # the gate\nread_gate = true  # on\nread_gate_threshold_lines = 42  # n\n"
        )
        self.assertEqual(module.parse_gate_config(text), (True, 42))

    def test_malformed_values_use_safe_defaults_without_raising(self):
        module = _module()
        text = "[skeleton]\nread_gate = maybe\nread_gate_threshold_lines = lots\n"
        self.assertEqual(module.parse_gate_config(text), (False, 500))

    def test_last_skeleton_assignment_wins(self):
        module = _module()
        text = "[skeleton]\nread_gate = true\nread_gate = false\n"
        self.assertEqual(module.parse_gate_config(text), (False, 500))

    def test_gate_re_enabled_after_other_section(self):
        module = _module()
        # A later [skeleton] re-entry still applies; section tracking resets on
        # each header rather than latching the first table seen.
        text = "[skeleton]\nread_gate = true\n[other]\nread_gate = false\n"
        self.assertEqual(module.parse_gate_config(text), (True, 500))


class GateConfigFileTests(RavenTestCase):
    """`_gate_config()` reads .raven/config.toml relative to cwd; these drive it
    through a real file (missing, unreadable, valid) rather than passing text
    directly, unlike ParseGateConfigTests above.
    """

    def _with_cwd(self, func):
        orig = os.getcwd()
        os.chdir(self.destination)
        try:
            return func()
        finally:
            os.chdir(orig)

    def test_missing_config_yields_safe_default(self):
        module = _module()
        self.assertEqual(self._with_cwd(module._gate_config), (False, module.DEFAULT_THRESHOLD))

    def test_valid_config_is_read(self):
        module = _module()
        (self.destination / ".raven").mkdir()
        (self.destination / ".raven" / "config.toml").write_text(
            "[skeleton]\nread_gate = true\nread_gate_threshold_lines = 42\n", encoding="utf-8"
        )
        self.assertEqual(self._with_cwd(module._gate_config), (True, 42))

    def test_unreadable_config_does_not_crash_and_yields_safe_default(self):
        # Pre-existing gap (issue #201): an unreadable-but-present config used
        # to propagate an uncaught OSError all the way out of the hook.
        # Fixed here to fail safe (gate off) like every other read failure in
        # this hook, rather than crashing the PreToolUse hook outright.
        module = _module()
        (self.destination / ".raven").mkdir()
        config = self.destination / ".raven" / "config.toml"
        config.write_text("[skeleton]\nread_gate = true\n", encoding="utf-8")
        config.chmod(0o000)
        try:
            self.assertEqual(self._with_cwd(module._gate_config), (False, module.DEFAULT_THRESHOLD))
        finally:
            config.chmod(0o644)


class IsSupportedTests(RavenTestCase):
    def test_supported_source_extensions(self):
        module = _module()
        for name in [
            "a.py",
            "a.ts",
            "a.tsx",
            "a.js",
            "a.jsx",
            "a.go",
            "a.rs",
            "a.swift",
            "a.lua",
            "a.ex",
            "a.exs",
        ]:
            with self.subTest(name=name):
                self.assertTrue(module.is_supported(f"/repo/{name}"))

    def test_unsupported_extensions(self):
        module = _module()
        for name in ["a.md", "a.txt", "Makefile"]:
            with self.subTest(name=name):
                self.assertFalse(module.is_supported(f"/repo/{name}"))


class GuardHookEndToEndTests(RavenTestCase):
    """Drive the hook as a subprocess with cwd at a temp project so it reads a
    temp .raven/config.toml, matching how Claude invokes it.
    """

    def _setup_project(self, *, gate_enabled: bool, lines: int, filename: str = "big.py"):
        (self.destination / ".raven").mkdir(parents=True, exist_ok=True)
        config = "[skeleton]\nread_gate = true\n" if gate_enabled else "[skeleton]\n"
        (self.destination / ".raven" / "config.toml").write_text(config, encoding="utf-8")
        body = "".join(f"x{i} = {i}\n" for i in range(lines))
        (self.destination / filename).write_text(body, encoding="utf-8")
        return self.destination / filename

    def _run(self, file_path) -> subprocess.CompletedProcess:
        payload = json.dumps({"tool_name": "Read", "tool_input": {"file_path": str(file_path)}})
        return subprocess.run(
            [sys.executable, str(GUARD_SCRIPT)],
            input=payload,
            capture_output=True,
            text=True,
            cwd=self.destination,
            check=False,
        )

    @unittest.skipUnless(HAVE_SKELETON_BACKEND, "no skeleton backend (ast-grep/rg) on PATH")
    def test_denies_large_unbounded_read_when_enabled(self):
        path = self._setup_project(gate_enabled=True, lines=2000)
        result = self._run(path)
        # Claude Read payloads carry tool_name, so the deny is the JSON
        # permissionDecision form (exit 0), which Claude honors.
        self.assertEqual(result.returncode, 0, result.stderr)
        decision = json.loads(result.stdout)["hookSpecificOutput"]
        self.assertEqual(decision["permissionDecision"], "deny")
        self.assertIn("raven-skeleton", decision["permissionDecisionReason"].lower())

    def test_allows_when_gate_disabled(self):
        path = self._setup_project(gate_enabled=False, lines=2000)
        result = self._run(path)
        self.assertEqual(result.returncode, 0)

    def test_allows_small_file_even_when_enabled(self):
        path = self._setup_project(gate_enabled=True, lines=100)
        result = self._run(path)
        self.assertEqual(result.returncode, 0)

    def test_allows_bounded_read_when_enabled(self):
        path = self._setup_project(gate_enabled=True, lines=2000)
        payload = json.dumps(
            {"tool_name": "Read", "tool_input": {"file_path": str(path), "offset": 1, "limit": 50}}
        )
        result = subprocess.run(
            [sys.executable, str(GUARD_SCRIPT)],
            input=payload,
            capture_output=True,
            text=True,
            cwd=self.destination,
            check=False,
        )
        self.assertEqual(result.returncode, 0)

    def test_unrelated_table_does_not_gate_small_file(self):
        # Regression for issue #41: a read_gate=true / threshold=1 in an unrelated
        # table, with [skeleton].read_gate = false, must not deny a tiny read.
        (self.destination / ".raven").mkdir(parents=True, exist_ok=True)
        config = (
            "[unrelated]\nread_gate = true\nread_gate_threshold_lines = 1\n\n"
            "[skeleton]\nread_gate = false\n"
        )
        (self.destination / ".raven" / "config.toml").write_text(config, encoding="utf-8")
        path = self.destination / "one_line.py"
        path.write_text("x = 1\n", encoding="utf-8")
        result = self._run(path)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")

    def test_tolerates_null_tool_input(self):
        result = subprocess.run(
            [sys.executable, str(GUARD_SCRIPT)],
            input=json.dumps({"tool_input": None}),
            capture_output=True,
            text=True,
            cwd=self.destination,
            check=False,
        )
        self.assertEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
