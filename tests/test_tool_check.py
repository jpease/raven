import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from helpers import REPO_ROOT, RavenTestCase, load_script_module

TOOL_CHECK_SCRIPT = REPO_ROOT / "common" / ".claude" / "scripts" / "raven-tool-check.py"


class ToolCheckTests(RavenTestCase):
    def test_tool_check_script_imports_without_name_error(self):
        module = load_script_module("raven_tool_check", TOOL_CHECK_SCRIPT)

        self.assertEqual(module._DO_NOT_REMIND_KEY, "doNotRemind")

    def test_tool_check_includes_optional_gap_tools(self):
        module = load_script_module("raven_tool_check_tools", TOOL_CHECK_SCRIPT)

        tool_ids = {tool["id"] for tool in module.TOOLS}
        self.assertIn("gitleaks", tool_ids)
        self.assertIn("jq", tool_ids)
        self.assertIn("yq", tool_ids)

    def test_astgrep_probe_never_invokes_sg(self):
        # On some Linux systems /usr/bin/sg is the unrelated setgroups utility, so
        # probing `sg --version` risks a false positive (or an interactive hang).
        # Raven always invokes ast-grep as `ast-grep`, so the alias must not be
        # probed.
        module = load_script_module("raven_tool_check_astgrep", TOOL_CHECK_SCRIPT)
        astgrep = next(tool for tool in module.TOOLS if tool["id"] == "ast-grep")
        probed = {command[0] for command in astgrep["commands"]}
        self.assertEqual(probed, {"ast-grep"})

    def test_tool_check_parses_claude_mcp_server_names(self):
        module = load_script_module("raven_tool_check_parser", TOOL_CHECK_SCRIPT)
        output = """Checking MCP server health...

semble: uvx --from semble[mcp] semble - ✗ Failed to connect
gitnexus: gitnexus mcp - ✓ Connected
[Conflicting scopes]
 └ [Warning] Server "gitnexus" is defined in multiple scopes
"""

        self.assertIn("semble", module._configured_mcp_server_names(output))
        self.assertIn("gitnexus", module._configured_mcp_server_names(output))

    def test_claude_mcp_config_files_are_parsed_without_cli(self):
        module = load_script_module("raven_tool_check_config", TOOL_CHECK_SCRIPT)

        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / ".claude.json"
            config.write_text(
                json.dumps({"mcpServers": {"semble": {"command": "uvx"}}}), encoding="utf-8"
            )
            module._claude_mcp_config_paths = lambda: [config]
            module._claude_mcp_server_names_from_config.cache_clear()
            try:
                self.assertEqual(module.claude_mcp_server_status("semble"), "configured")
            finally:
                module._claude_mcp_server_names_from_config.cache_clear()

    def test_semble_can_be_available_from_claude_mcp_config_without_cli(self):
        module = load_script_module("raven_tool_check_semble", TOOL_CHECK_SCRIPT)
        tool = next(tool for tool in module.TOOLS if tool["id"] == "semble")
        original_command_status = module.command_status
        original_status = module.claude_mcp_server_status
        module.command_status = lambda _command: "missing"
        module.claude_mcp_server_status = lambda name: (
            "configured" if name == "semble" else "not_configured"
        )
        try:
            available, source = module.check_tool_with_source(tool)
        finally:
            module.command_status = original_command_status
            module.claude_mcp_server_status = original_status

        self.assertTrue(available)
        self.assertEqual(source, "claude-mcp-config")

    def test_semble_can_be_available_from_codex_mcp_config_without_cli(self):
        module = load_script_module("raven_tool_check_semble_codex", TOOL_CHECK_SCRIPT)
        tool = next(tool for tool in module.TOOLS if tool["id"] == "semble")
        original_command_status = module.command_status
        original_claude_status = module.claude_mcp_server_status
        original_codex_config = module._codex_mcp_server_names_from_config
        module.command_status = lambda _command: "missing"
        module.claude_mcp_server_status = lambda _name: "not_configured"
        module._codex_mcp_server_names_from_config = lambda: frozenset({"semble"})
        try:
            available, source = module.check_tool_with_source(tool)
        finally:
            module.command_status = original_command_status
            module.claude_mcp_server_status = original_claude_status
            module._codex_mcp_server_names_from_config = original_codex_config

        self.assertTrue(available)
        self.assertEqual(source, "codex-mcp-config")

    def test_slow_claude_mcp_check_does_not_crash_tool_check(self):
        module = load_script_module("raven_tool_check_timeout", TOOL_CHECK_SCRIPT)

        original_which = module.shutil.which
        original_run = module.subprocess.run
        module.shutil.which = lambda name: (
            "/usr/bin/claude" if name == "claude" else original_which(name)
        )

        def timeout_run(*_args, **_kwargs):
            raise module.subprocess.TimeoutExpired(["claude", "mcp", "list"], timeout=3)

        module.subprocess.run = timeout_run
        module.RUN_CLAUDE_MCP_CLI = True
        module._claude_mcp_server_names.cache_clear()
        module._claude_mcp_server_names_from_config.cache_clear()
        module._claude_mcp_server_names_from_cli.cache_clear()
        module._claude_mcp_config_paths = list
        try:
            self.assertEqual(module.claude_mcp_server_status("semble"), "timed_out")
            self.assertFalse(module.claude_mcp_server_configured("semble"))
        finally:
            module._claude_mcp_server_names.cache_clear()
            module._claude_mcp_server_names_from_config.cache_clear()
            module._claude_mcp_server_names_from_cli.cache_clear()
            module.shutil.which = original_which
            module.subprocess.run = original_run

    def test_command_timeout_counts_as_unavailable(self):
        module = load_script_module("raven_tool_check_command_timeout", TOOL_CHECK_SCRIPT)

        original_which = module.shutil.which
        original_run = module.subprocess.run
        module.shutil.which = lambda name: f"/usr/bin/{name}"
        module.RUN_COMMAND_PROBES = True

        def timeout_run(*_args, **_kwargs):
            raise module.subprocess.TimeoutExpired(["tool", "--version"], timeout=3)

        module.subprocess.run = timeout_run
        try:
            self.assertEqual(module.command_status(["tool", "--version"]), "timed_out")
            self.assertFalse(module.command_works(["tool", "--version"]))
        finally:
            module.shutil.which = original_which
            module.subprocess.run = original_run


class LoadMemoryRecoveryTests(RavenTestCase):
    """Structurally invalid local tool memory must recover to a clean versioned
    object instead of crashing callers that assume a dict (issue #42)."""

    def _module_with_memory(self, contents: str):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        memory_path = Path(tmp.name) / "tool-memory.json"
        memory_path.write_text(contents, encoding="utf-8")
        module = load_script_module(f"raven_tool_check_mem_{id(tmp)}", TOOL_CHECK_SCRIPT)
        module.MEMORY_PATH = memory_path
        return module, memory_path

    def test_list_root_falls_back_to_default(self):
        module, _ = self._module_with_memory("[]")
        self.assertEqual(module.load_memory(), {"version": 1, "tools": {}, "preferences": {}})

    def test_null_root_falls_back_to_default(self):
        module, _ = self._module_with_memory("null")
        self.assertEqual(module.load_memory(), {"version": 1, "tools": {}, "preferences": {}})

    def test_string_root_falls_back_to_default(self):
        module, _ = self._module_with_memory('"corrupted"')
        self.assertEqual(module.load_memory(), {"version": 1, "tools": {}, "preferences": {}})

    def test_non_object_tools_is_reset(self):
        module, _ = self._module_with_memory('{"version": 1, "tools": [], "preferences": {}}')
        memory = module.load_memory()
        self.assertEqual(memory["tools"], {})
        # The bad container is replaced but unrelated keys are preserved.
        self.assertEqual(memory["preferences"], {})

    def test_non_object_preferences_is_reset(self):
        module, _ = self._module_with_memory('{"tools": {"jq": {}}, "preferences": "nope"}')
        memory = module.load_memory()
        self.assertEqual(memory["preferences"], {})
        self.assertEqual(memory["tools"], {"jq": {}})

    def test_main_setdefault_survives_list_root(self):
        # main() immediately calls memory.setdefault(...); a list root previously
        # raised AttributeError. With recovery it must run cleanly.
        module, _ = self._module_with_memory("[]")
        original_argv = sys.argv
        sys.argv = ["raven-tool-check.py", "--no-reminder"]
        try:
            rc = module.main()
        finally:
            sys.argv = original_argv
        self.assertEqual(rc, 0)


class ToolCheckJsonEndToEndTests(RavenTestCase):
    """End-to-end reproduction of issue #42: a damaged cache must not add a
    traceback to --json or --session-start invocations."""

    def _run(self, memory_contents: str, args: list[str]) -> subprocess.CompletedProcess:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        memory_path = Path(tmp.name) / "tool-memory.json"
        memory_path.write_text(memory_contents, encoding="utf-8")
        env = {**os.environ, "RAVEN_TOOL_MEMORY": str(memory_path)}
        return subprocess.run(
            [sys.executable, str(TOOL_CHECK_SCRIPT), *args],
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )

    def test_json_with_list_root_exits_clean_and_emits_valid_json(self):
        result = self._run("[]", ["--json"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        json.loads(result.stdout)  # must be valid JSON

    def test_session_start_with_list_root_exits_clean(self):
        result = self._run("[]", ["--session-start"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
