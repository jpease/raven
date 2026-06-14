import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from helpers import REPO_ROOT, RavenTestCase


class ToolCheckTests(RavenTestCase):
    def test_tool_check_script_imports_without_name_error(self):
        path = REPO_ROOT / "common" / ".claude" / "scripts" / "raven-tool-check.py"
        spec = importlib.util.spec_from_file_location("raven_tool_check", path)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None

        spec.loader.exec_module(module)

        self.assertEqual(module._DO_NOT_REMIND_KEY, "doNotRemind")

    def test_tool_check_includes_optional_gap_tools(self):
        path = REPO_ROOT / "common" / ".claude" / "scripts" / "raven-tool-check.py"
        spec = importlib.util.spec_from_file_location("raven_tool_check_tools", path)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None

        spec.loader.exec_module(module)

        tool_ids = {tool["id"] for tool in module.TOOLS}
        self.assertIn("gitleaks", tool_ids)
        self.assertIn("jq", tool_ids)
        self.assertIn("yq", tool_ids)

    def test_tool_check_parses_claude_mcp_server_names(self):
        path = REPO_ROOT / "common" / ".claude" / "scripts" / "raven-tool-check.py"
        spec = importlib.util.spec_from_file_location("raven_tool_check_parser", path)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        output = """Checking MCP server health...

semble: uvx --from semble[mcp] semble - ✗ Failed to connect
gitnexus: gitnexus mcp - ✓ Connected
[Conflicting scopes]
 └ [Warning] Server "gitnexus" is defined in multiple scopes
"""

        self.assertIn("semble", module._configured_mcp_server_names(output))
        self.assertIn("gitnexus", module._configured_mcp_server_names(output))

    def test_claude_mcp_config_files_are_parsed_without_cli(self):
        path = REPO_ROOT / "common" / ".claude" / "scripts" / "raven-tool-check.py"
        spec = importlib.util.spec_from_file_location("raven_tool_check_config", path)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)

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
        path = REPO_ROOT / "common" / ".claude" / "scripts" / "raven-tool-check.py"
        spec = importlib.util.spec_from_file_location("raven_tool_check_semble", path)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
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
        path = REPO_ROOT / "common" / ".claude" / "scripts" / "raven-tool-check.py"
        spec = importlib.util.spec_from_file_location("raven_tool_check_semble_codex", path)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
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
        path = REPO_ROOT / "common" / ".claude" / "scripts" / "raven-tool-check.py"
        spec = importlib.util.spec_from_file_location("raven_tool_check_timeout", path)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)

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
        module._claude_mcp_config_paths = lambda: []
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
        path = REPO_ROOT / "common" / ".claude" / "scripts" / "raven-tool-check.py"
        spec = importlib.util.spec_from_file_location("raven_tool_check_command_timeout", path)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)

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


if __name__ == "__main__":
    unittest.main()
