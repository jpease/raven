import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from typing import ClassVar

from helpers import REPO_ROOT, RavenTestCase, install_raven_config_lib, load_script_module
from raven_lib.template import should_preserve_symlink

TOOL_CHECK_SCRIPT = REPO_ROOT / "common" / ".claude" / "scripts" / "raven-tool-check.py"
CODEX_TOOL_CHECK_SCRIPT = REPO_ROOT / "common" / ".codex" / "scripts" / "raven-tool-check.py"
CODEX_ROSTER_SCRIPT = REPO_ROOT / "common" / ".codex" / "scripts" / "raven-capability-roster.py"


class CodexMcpServerNamesFromTomlTests(RavenTestCase):
    """Direct tests for `_codex_mcp_server_names_from_toml`, which now routes
    through the shared .raven/git-hooks/lib/raven_config.py parser instead of
    its own bespoke per-line header scan (issue #201, parser 5).
    """

    def setUp(self):
        super().setUp()
        self.module = load_script_module("raven_tool_check_codex_names", TOOL_CHECK_SCRIPT)

    def test_finds_a_simple_server_name(self):
        names = self.module._codex_mcp_server_names_from_toml(
            '[mcp_servers.semgrep]\ncommand = "semgrep"\n'
        )
        self.assertEqual(names, {"semgrep"})

    def test_finds_multiple_servers(self):
        text = '[mcp_servers.semgrep]\ncommand = "semgrep"\n\n[mcp_servers.gitnexus]\ncommand = "gitnexus"\n'
        self.assertEqual(
            self.module._codex_mcp_server_names_from_toml(text), {"semgrep", "gitnexus"}
        )

    def test_excludes_nested_dotted_headers(self):
        # [mcp_servers.semgrep.tools.search] is per-tool config, not a server.
        text = '[mcp_servers.semgrep]\ncommand = "semgrep"\n[mcp_servers.semgrep.tools.search]\napproval_mode = "approve"\n'
        self.assertEqual(self.module._codex_mcp_server_names_from_toml(text), {"semgrep"})

    def test_unquotes_a_quoted_server_name(self):
        text = '[mcp_servers."my server"]\ncommand = "x"\n'
        self.assertEqual(self.module._codex_mcp_server_names_from_toml(text), {"my server"})

    def test_ignores_unrelated_sections(self):
        text = "[agents]\nmax_threads = 4\n\n[mcp_servers.semgrep]\ncommand = \"semgrep\"\n"
        self.assertEqual(self.module._codex_mcp_server_names_from_toml(text), {"semgrep"})

    def test_a_hash_in_a_value_line_does_not_disrupt_later_header_parsing(self):
        # A value containing '#' must not be misread as starting a comment
        # that swallows a later real header -- the shared parser strips
        # comments per line, quote-aware.
        text = '[mcp_servers.semgrep]\ncommand = "se#mgrep"  # note\n\n[mcp_servers.gitnexus]\ncommand = "y"\n'
        self.assertEqual(
            self.module._codex_mcp_server_names_from_toml(text), {"semgrep", "gitnexus"}
        )

    def test_empty_text_yields_no_servers(self):
        self.assertEqual(self.module._codex_mcp_server_names_from_toml(""), set())

    def test_real_shipped_codex_config_parses(self):
        # Pinned against the real template file so the reader and the
        # shipped config cannot drift.
        text = (REPO_ROOT / "python" / ".codex" / "config.toml").read_text(encoding="utf-8")
        names = self.module._codex_mcp_server_names_from_toml(text)
        self.assertIn("semgrep", names)
        self.assertIn("gitnexus", names)
        self.assertIn("lsp", names)


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

    def test_osv_scanner_is_registered_as_optional(self):
        # #135 -- osv-scanner backs `just audit`, which is deliberately not a
        # gate. It must be reported like the other gap tools, and it must carry
        # an `optionalWhen` note so a repo covered by Dependabot or a platform
        # scanner is not nagged to install a second one.
        module = load_script_module("raven_tool_check_osv", TOOL_CHECK_SCRIPT)
        tool = next(tool for tool in module.TOOLS if tool["id"] == "osv-scanner")
        self.assertTrue(tool["optionalWhen"])
        self.assertEqual({command[0] for command in tool["commands"]}, {"osv-scanner"})

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

semgrep: semgrep mcp - ✗ Failed to connect
gitnexus: gitnexus mcp - ✓ Connected
[Conflicting scopes]
 └ [Warning] Server "gitnexus" is defined in multiple scopes
"""

        self.assertIn("semgrep", module._configured_mcp_server_names(output))
        self.assertIn("gitnexus", module._configured_mcp_server_names(output))

    def test_claude_mcp_config_files_are_parsed_without_cli(self):
        module = load_script_module("raven_tool_check_config", TOOL_CHECK_SCRIPT)

        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / ".claude.json"
            config.write_text(
                json.dumps({"mcpServers": {"semgrep": {"command": "semgrep"}}}), encoding="utf-8"
            )
            module._claude_mcp_config_paths = lambda _root=None: [config]
            module._claude_mcp_server_names_from_config.cache_clear()
            try:
                self.assertEqual(module.claude_mcp_server_status("semgrep"), "configured")
            finally:
                module._claude_mcp_server_names_from_config.cache_clear()

    #: No shipped tool sets ``claudeMcpServer``/``codexMcpServer`` any more --
    #: every tool Raven recommends needs its CLI on PATH even when it also runs
    #: as an MCP server. The branches stay for the next MCP-only tool, so these
    #: two tests drive them from a synthetic entry rather than a real one.
    MCP_ONLY_TOOL: ClassVar[dict] = {
        "id": "mcp-only",
        "name": "MCP Only",
        "commands": [["mcp-only", "--version"]],
        "purpose": "stand-in for a tool reachable only as an MCP server",
        "install": "n/a",
        "claudeMcpServer": "mcp-only",
        "codexMcpServer": "mcp-only",
    }

    def test_a_tool_can_be_available_from_claude_mcp_config_without_cli(self):
        module = load_script_module("raven_tool_check_mcp_only", TOOL_CHECK_SCRIPT)
        original_command_status = module.command_status
        original_status = module.claude_mcp_server_status
        module.command_status = lambda _command: "missing"
        module.claude_mcp_server_status = lambda name, _root=None: (
            "configured" if name == "mcp-only" else "not_configured"
        )
        try:
            available, source = module.check_tool_with_source(self.MCP_ONLY_TOOL)
        finally:
            module.command_status = original_command_status
            module.claude_mcp_server_status = original_status

        self.assertTrue(available)
        self.assertEqual(source, "claude-mcp-config")

    def test_a_tool_can_be_available_from_codex_mcp_config_without_cli(self):
        module = load_script_module("raven_tool_check_mcp_only_codex", TOOL_CHECK_SCRIPT)
        original_command_status = module.command_status
        original_claude_status = module.claude_mcp_server_status
        original_codex_config = module._codex_mcp_server_names_from_config
        module.command_status = lambda _command: "missing"
        module.claude_mcp_server_status = lambda _name, _root=None: "not_configured"
        module._codex_mcp_server_names_from_config = lambda _root=None: frozenset({"mcp-only"})
        try:
            available, source = module.check_tool_with_source(self.MCP_ONLY_TOOL)
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
        module._claude_mcp_config_paths = lambda _root=None: []
        try:
            self.assertEqual(module.claude_mcp_server_status("semgrep"), "timed_out")
            self.assertFalse(module.claude_mcp_server_configured("semgrep"))
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


class ClaudeJsonProjectScopeTests(RavenTestCase):
    """Regression for #194: ``~/.claude.json`` nests MCP config per project

    under ``projects.<absolute-path>.mcpServers``. A server configured only
    for another project on the machine must never be reported as configured
    for this repo; a server configured for *this* repo's project entry, or
    in the file's top-level ``mcpServers``, must be.
    """

    def _write_claude_json(self, tmp: str, projects: dict, top_level_servers=None) -> Path:
        config = Path(tmp) / ".claude.json"
        payload: dict = {"projects": projects}
        if top_level_servers is not None:
            payload["mcpServers"] = top_level_servers
        config.write_text(json.dumps(payload), encoding="utf-8")
        return config

    def test_server_configured_only_for_another_project_is_not_reported(self):
        module = load_script_module("raven_tool_check_claude_json_other", TOOL_CHECK_SCRIPT)
        with tempfile.TemporaryDirectory() as tmp:
            this_repo = Path(tmp) / "this-repo"
            this_repo.mkdir()
            config = self._write_claude_json(
                tmp,
                {
                    str(Path(tmp) / "other-repo-a"): {
                        "mcpServers": {"other-only-a": {"command": "x"}}
                    },
                    str(Path(tmp) / "other-repo-b"): {
                        "mcpServers": {"other-only-b": {"command": "y"}}
                    },
                    str(this_repo): {"mcpServers": {"semgrep": {"command": "semgrep"}}},
                },
            )
            module._claude_mcp_config_paths = lambda _root=None: [config]
            module._claude_mcp_server_names_from_config.cache_clear()
            try:
                self.assertEqual(
                    module.claude_mcp_server_status("other-only-a", this_repo), "not_configured"
                )
                self.assertEqual(
                    module.claude_mcp_server_status("other-only-b", this_repo), "not_configured"
                )
            finally:
                module._claude_mcp_server_names_from_config.cache_clear()

    def test_server_configured_for_this_project_is_reported(self):
        # The "other-only" distractor is what makes this fail pre-fix: the
        # path-blind recursion reports it as configured for this_repo too, so
        # asserting it is *not* is what proves this test exercises the fix
        # rather than passing vacuously.
        module = load_script_module("raven_tool_check_claude_json_this", TOOL_CHECK_SCRIPT)
        with tempfile.TemporaryDirectory() as tmp:
            this_repo = Path(tmp) / "this-repo"
            this_repo.mkdir()
            config = self._write_claude_json(
                tmp,
                {
                    str(Path(tmp) / "other-repo"): {"mcpServers": {"other-only": {"command": "x"}}},
                    str(this_repo): {"mcpServers": {"semgrep": {"command": "semgrep"}}},
                },
            )
            module._claude_mcp_config_paths = lambda _root=None: [config]
            module._claude_mcp_server_names_from_config.cache_clear()
            try:
                self.assertEqual(
                    module.claude_mcp_server_status("semgrep", this_repo), "configured"
                )
                self.assertEqual(
                    module.claude_mcp_server_status("other-only", this_repo), "not_configured"
                )
            finally:
                module._claude_mcp_server_names_from_config.cache_clear()

    def test_top_level_mcp_server_is_reported_for_every_project(self):
        module = load_script_module("raven_tool_check_claude_json_top", TOOL_CHECK_SCRIPT)
        with tempfile.TemporaryDirectory() as tmp:
            this_repo = Path(tmp) / "this-repo"
            this_repo.mkdir()
            config = self._write_claude_json(
                tmp,
                {
                    str(Path(tmp) / "other-repo"): {"mcpServers": {"other-only": {"command": "x"}}},
                },
                top_level_servers={"gitnexus": {"command": "gitnexus"}},
            )
            module._claude_mcp_config_paths = lambda _root=None: [config]
            module._claude_mcp_server_names_from_config.cache_clear()
            try:
                self.assertEqual(
                    module.claude_mcp_server_status("gitnexus", this_repo), "configured"
                )
                self.assertEqual(
                    module.claude_mcp_server_status("other-only", this_repo), "not_configured"
                )
            finally:
                module._claude_mcp_server_names_from_config.cache_clear()

    def test_symlinked_repo_root_and_trailing_separator_are_tolerated(self):
        # A distractor project ("other-only") sits alongside the symlinked
        # entry: on the pre-fix, path-blind recursion this distractor is
        # (wrongly) reported as configured for any root, which is what makes
        # this test actually fail before the fix rather than passing
        # vacuously because path matching was never exercised.
        module = load_script_module("raven_tool_check_claude_json_symlink", TOOL_CHECK_SCRIPT)
        with tempfile.TemporaryDirectory() as tmp:
            real_repo = Path(tmp) / "real-repo"
            real_repo.mkdir()
            linked_repo = Path(tmp) / "linked-repo"
            linked_repo.symlink_to(real_repo, target_is_directory=True)
            other_repo = Path(tmp) / "other-repo"
            config = self._write_claude_json(
                tmp,
                {
                    # The config key is spelled through the symlink and with a
                    # trailing separator; the lookup root below is the plain
                    # real path with no trailing separator.
                    str(linked_repo) + os.sep: {"mcpServers": {"semgrep": {"command": "semgrep"}}},
                    str(other_repo): {"mcpServers": {"other-only": {"command": "y"}}},
                },
            )
            module._claude_mcp_config_paths = lambda _root=None: [config]
            module._claude_mcp_server_names_from_config.cache_clear()
            try:
                self.assertEqual(
                    module.claude_mcp_server_status("semgrep", real_repo), "configured"
                )
                self.assertEqual(
                    module.claude_mcp_server_status("other-only", real_repo), "not_configured"
                )
                # And the reverse direction: the lookup root itself goes
                # through the symlink and carries a trailing separator, while
                # the config key is the plain real path.
                config.write_text(
                    json.dumps({"projects": {str(real_repo): {"mcpServers": {"semgrep": {}}}}}),
                    encoding="utf-8",
                )
                module._claude_mcp_server_names_from_config.cache_clear()
                trailing_symlink_root = Path(str(linked_repo) + os.sep)
                self.assertEqual(
                    module.claude_mcp_server_status("semgrep", trailing_symlink_root), "configured"
                )
            finally:
                module._claude_mcp_server_names_from_config.cache_clear()

    def test_malformed_claude_json_shapes_do_not_raise_or_report_configured(self):
        # Each malformed shape below is paired with a validly-shaped, but
        # non-matching, project entry exposing a real server ("leaked"). The
        # pre-fix, path-blind recursion finds "leaked" no matter which
        # project it belongs to or how mangled this project's own entry is;
        # the fix must not, which is what makes these subtests fail before
        # the fix instead of passing vacuously.
        module = load_script_module("raven_tool_check_claude_json_malformed", TOOL_CHECK_SCRIPT)
        this_repo_marker = "/this/repo"
        other_project_marker = "/other/repo"
        malformed_cases_with_a_leak = [
            {
                "projects": {
                    this_repo_marker: "not-a-dict",
                    other_project_marker: {"mcpServers": {"leaked": {"command": "x"}}},
                }
            },
            {
                "projects": {
                    this_repo_marker: {"mcpServers": ["semgrep"]},
                    other_project_marker: {"mcpServers": {"leaked": {"command": "x"}}},
                }
            },
            {
                "mcpServers": ["semgrep"],
                "projects": {other_project_marker: {"mcpServers": {"leaked": {"command": "x"}}}},
            },
        ]
        for payload in malformed_cases_with_a_leak:
            with self.subTest(payload=payload), tempfile.TemporaryDirectory() as tmp:
                config = Path(tmp) / ".claude.json"
                config.write_text(json.dumps(payload), encoding="utf-8")
                module._claude_mcp_config_paths = lambda _root=None, _c=config: [_c]
                module._claude_mcp_server_names_from_config.cache_clear()
                try:
                    own_status = module.claude_mcp_server_status("semgrep", Path(this_repo_marker))
                    leaked_status = module.claude_mcp_server_status(
                        "leaked", Path(this_repo_marker)
                    )
                finally:
                    module._claude_mcp_server_names_from_config.cache_clear()
                self.assertEqual(own_status, "not_configured")
                self.assertEqual(leaked_status, "not_configured")

        # Structurally invalid outer shapes -- nothing to leak, just must not
        # raise and must not manufacture a "configured" result out of thin air.
        structurally_invalid_cases = [{"projects": ["not", "a", "dict"]}, ["not", "a", "dict"]]
        for payload in structurally_invalid_cases:
            with self.subTest(payload=payload), tempfile.TemporaryDirectory() as tmp:
                config = Path(tmp) / ".claude.json"
                config.write_text(json.dumps(payload), encoding="utf-8")
                module._claude_mcp_config_paths = lambda _root=None, _c=config: [_c]
                module._claude_mcp_server_names_from_config.cache_clear()
                try:
                    status = module.claude_mcp_server_status("semgrep", Path(this_repo_marker))
                finally:
                    module._claude_mcp_server_names_from_config.cache_clear()
                self.assertEqual(status, "not_configured")


class LoadMemoryRecoveryTests(RavenTestCase):
    """Structurally invalid local tool memory must recover to a clean versioned
    object instead of crashing callers that assume a dict (issue #42).
    """

    def _module_with_memory(self, contents: str):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        memory_path = Path(tmp.name) / "tool-memory.json"
        memory_path.write_text(contents, encoding="utf-8")
        module = load_script_module(f"raven_tool_check_mem_{id(tmp)}", TOOL_CHECK_SCRIPT)
        module.MEMORY_PATH = memory_path
        return module, memory_path

    def test_malformed_json_falls_back_to_default(self):
        # Issue #152: load_memory()'s except clause must stay narrowed to
        # (ValueError, OSError) -- json.loads raises JSONDecodeError (a
        # ValueError) on unparseable text, and this must still fail open.
        module, _ = self._module_with_memory("not json{{{")
        self.assertEqual(module.load_memory(), {"version": 1, "tools": {}, "preferences": {}})

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
    traceback to --json or --session-start invocations.
    """

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


class ProjectRootResolutionTests(RavenTestCase):
    """Regression for #147: project-scoped MCP config is found from the script's
    install location, not the process working directory.

    A hook's cwd is not reliably the project. Codex Desktop can invoke a hook
    from outside the worktree, and its launcher runs the script through
    ``runpy`` without changing directory, so a cwd-anchored lookup silently
    misses the project's ``.mcp.json`` / ``.codex/config.toml`` and reports an
    MCP-configured tool as missing.
    """

    def test_project_root_ignores_the_process_working_directory(self):
        module = load_script_module("raven_tool_check_root", TOOL_CHECK_SCRIPT)
        module.project_root.cache_clear()
        self.addCleanup(module.project_root.cache_clear)
        original_cwd = Path.cwd()
        os.chdir(self.destination)
        try:
            self.assertEqual(module.project_root(), REPO_ROOT / "common")
        finally:
            os.chdir(original_cwd)

    def test_config_path_helpers_accept_an_explicit_root(self):
        module = load_script_module("raven_tool_check_explicit_root", TOOL_CHECK_SCRIPT)
        root = self.destination

        self.assertEqual(module._claude_mcp_config_paths(root)[0], root / ".mcp.json")
        self.assertEqual(module._codex_mcp_config_paths(root)[0], root / ".codex" / "config.toml")

    def _install_project(self, adapter: str, script: Path) -> Path:
        """Install one adapter's prober into a throwaway project worktree."""
        project = self.destination / f"project{adapter}"
        (project / ".git").mkdir(parents=True)
        scripts = project / adapter / "scripts"
        scripts.mkdir(parents=True)
        shutil.copy2(script, scripts / "raven-tool-check.py")
        # project_root() (and this prober's _raven_config_module()) resolves
        # from the script's own installed location, so a fabricated project
        # needs the shared config lib at its real installed path too.
        install_raven_config_lib(project)
        return project

    def _isolated_env(self) -> dict[str, str]:
        """Environment with no user config and no tools other than python.

        ``HOME`` is redirected so a globally configured MCP server on the
        machine running the tests cannot mask a cwd bug, and ``PATH`` holds
        only the interpreter so every probed CLI reports missing.
        """
        home = self.destination / "home"
        bin_dir = self.destination / "bin"
        home.mkdir(exist_ok=True)
        bin_dir.mkdir(exist_ok=True)
        python = bin_dir / "python"
        if not python.exists():
            python.symlink_to(sys.executable)
        return {
            "HOME": str(home),
            "PATH": str(bin_dir),
            "RAVEN_TOOL_MEMORY": str(home / "tool-memory.json"),
        }

    def test_claude_adapter_reads_project_mcp_json_from_outside_the_worktree(self):
        project = self._install_project(".claude", TOOL_CHECK_SCRIPT)
        (project / ".mcp.json").write_text(
            json.dumps({"mcpServers": {"projectprobe": {"command": "x"}}}), encoding="utf-8"
        )
        outside = self.destination / "outside"
        outside.mkdir()
        script = project / ".claude" / "scripts" / "raven-tool-check.py"
        probe = (
            "import importlib.util;"
            f"spec = importlib.util.spec_from_file_location('prober', {json.dumps(str(script))});"
            "mod = importlib.util.module_from_spec(spec);"
            "spec.loader.exec_module(mod);"
            "print(mod.claude_mcp_server_status('projectprobe'))"
        )

        result = subprocess.run(
            [sys.executable, "-c", probe],
            cwd=outside,
            env=self._isolated_env(),
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        # `projectprobe` is named only in <project>/.mcp.json, and HOME is
        # isolated, so a "configured" answer is only reachable by deriving the
        # root from the script's own install path -- cwd is outside the
        # worktree entirely.
        self.assertEqual(result.stdout.strip(), "configured")

    def test_codex_launcher_reads_project_config_from_outside_the_worktree(self):
        # The SessionStart hook now launches raven-capability-roster.py, not
        # raven-tool-check.py directly; the roster imports the prober as a
        # sibling module, so both must be installed.
        project = self._install_project(".codex", CODEX_TOOL_CHECK_SCRIPT)
        shutil.copy2(CODEX_ROSTER_SCRIPT, project / ".codex" / "scripts" / CODEX_ROSTER_SCRIPT.name)
        (project / ".codex" / "config.toml").write_text(
            '[mcp_servers.projectprobe]\ncommand = "x"\n', encoding="utf-8"
        )
        outside = self.destination / "outside"
        outside.mkdir()
        hooks = json.loads(
            (REPO_ROOT / "common" / ".codex" / "hooks.json").read_text(encoding="utf-8")
        )
        command = hooks["hooks"]["SessionStart"][0]["hooks"][0]["command"]
        payload = {"cwd": str(project), "hook_event_name": "SessionStart", "source": "startup"}

        result = subprocess.run(
            command,
            cwd=outside,
            input=json.dumps(payload),
            env=self._isolated_env(),
            capture_output=True,
            text=True,
            shell=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        # ripgrep is CLI-only and absent under the isolated PATH, so the roster
        # really did probe. `projectprobe` reaches the MCP line only from the
        # project's .codex/config.toml, which is only readable if the root
        # resolved correctly from the payload cwd.
        self.assertIn("ripgrep —", result.stdout)
        mcp_line = next(
            (line for line in result.stdout.splitlines() if line.strip().startswith("MCP (cfg)")),
            "",
        )
        self.assertIn("projectprobe", mcp_line)


class AdapterDirectoryDerivationTests(RavenTestCase):
    """The two adapters ship one shared file (issue #165), so the adapter
    directory named in user-facing command examples has to be derived from the
    install layout at runtime rather than embedded as a literal.

    These tests load the *same bytes* from two different install locations and
    require two different answers -- the property a byte-comparison between the
    two trees can no longer express now that they are one file.
    """

    def _module_installed_at(self, relative: Path, name: str):
        """Load the prober from a synthetic install path under a temp root."""
        target = self.destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(TOOL_CHECK_SCRIPT, target)
        return load_script_module(name, target)

    def test_adapter_name_follows_the_install_layout(self):
        claude = self._module_installed_at(
            Path("proj/.claude/scripts/raven-tool-check.py"), "raven_tc_layout_claude"
        )
        codex = self._module_installed_at(
            Path("proj/.codex/scripts/raven-tool-check.py"), "raven_tc_layout_codex"
        )

        self.assertEqual(claude.adapter_directory_name(), ".claude")
        self.assertEqual(codex.adapter_directory_name(), ".codex")

    def test_adapter_name_falls_back_outside_the_install_layout(self):
        stray = self._module_installed_at(
            Path("elsewhere/raven-tool-check.py"), "raven_tc_layout_stray"
        )

        self.assertEqual(stray.adapter_directory_name(), ".claude")

    def test_project_root_still_agrees_with_the_adapter_directory(self):
        # The name and the root are derived from one helper; a refactor that
        # splits them would let the two disagree about which tree is in play.
        codex = self._module_installed_at(
            Path("proj/.codex/scripts/raven-tool-check.py"), "raven_tc_layout_root"
        )
        codex.project_root.cache_clear()
        self.addCleanup(codex.project_root.cache_clear)

        self.assertEqual(codex.project_root(), self.destination / "proj")

    def test_source_embeds_no_adapter_script_path_literal(self):
        # The criterion is that the literal is *gone*, not merely unused: a
        # future edit that reintroduces one would silently be wrong in the
        # other adapter, exactly as it was before unification.
        source = TOOL_CHECK_SCRIPT.read_text(encoding="utf-8")

        for literal in (
            ".claude/scripts/raven-tool-check.py",
            ".codex/scripts/raven-tool-check.py",
        ):
            with self.subTest(literal=literal):
                self.assertNotIn(literal, source)


class AdapterHelpPathTests(unittest.TestCase):
    """Regression for #105: a Codex-only install (no .claude tree) must
    advertise `.codex/scripts/raven-tool-check.py`, not the Claude adapter's
    path, in its --help output and remediation guidance.
    """

    def _help_output(self, script: Path) -> str:
        result = subprocess.run(
            [sys.executable, str(script), "--help"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def test_codex_help_advertises_codex_script_path(self):
        output = self._help_output(CODEX_TOOL_CHECK_SCRIPT)
        self.assertIn(".codex/scripts/raven-tool-check.py", output)
        self.assertNotIn(".claude/scripts/raven-tool-check.py", output)

    def test_claude_help_advertises_claude_script_path(self):
        output = self._help_output(TOOL_CHECK_SCRIPT)
        self.assertIn(".claude/scripts/raven-tool-check.py", output)
        self.assertNotIn(".codex/scripts/raven-tool-check.py", output)

    def _session_start_prompt(self, script: Path) -> str:
        module = load_script_module(f"raven_tool_check_prompt_{script.parent.parent.name}", script)
        missing = [
            {
                "name": "example-tool",
                "purpose": "example purpose",
                "install": "example install guidance",
            }
        ]
        buf = io.StringIO()
        with redirect_stdout(buf):
            module.print_session_start_prompt(missing, Path("/tmp/tool-memory.json"))
        return buf.getvalue()

    def test_codex_remediation_advertises_codex_script_path(self):
        output = self._session_start_prompt(CODEX_TOOL_CHECK_SCRIPT)
        self.assertIn(".codex/scripts/raven-tool-check.py", output)
        self.assertNotIn(".claude/scripts/raven-tool-check.py", output)

    def test_claude_remediation_advertises_claude_script_path(self):
        output = self._session_start_prompt(TOOL_CHECK_SCRIPT)
        self.assertIn(".claude/scripts/raven-tool-check.py", output)
        self.assertNotIn(".codex/scripts/raven-tool-check.py", output)

    def test_codex_docs_install_guidance_still_points_at_claude_docs(self):
        # The `docs` component always installs to .claude/docs (there is no
        # .codex/docs), so the mcp-language-server install guidance must keep
        # referencing .claude/docs even in the Codex adapter copy.
        module = load_script_module("raven_tool_check_codex_docs", CODEX_TOOL_CHECK_SCRIPT)
        tool = next(tool for tool in module.TOOLS if tool["id"] == "mcp-language-server")
        self.assertIn(".claude/docs/raven-lsp-mcp.md", tool["install"]["darwin"])
        self.assertIn(".claude/docs/raven-lsp-mcp.md", tool["install"]["linux"])

    def test_both_adapters_share_one_tools_registry(self):
        # Replaces `test_both_adapters_register_the_same_tools` (issue #165).
        # Comparing the two TOOLS registries now compares a file to itself
        # through a symlink, so it can no longer detect the drift it was written
        # for. The guarantee moved from "the two lists match" to "there is only
        # one list", which is what this asserts instead.
        self.assertTrue(CODEX_TOOL_CHECK_SCRIPT.is_symlink())
        self.assertEqual(
            os.path.realpath(CODEX_TOOL_CHECK_SCRIPT),
            os.path.realpath(TOOL_CHECK_SCRIPT),
        )
        self.assertFalse(should_preserve_symlink(CODEX_TOOL_CHECK_SCRIPT))

    def test_codex_claude_app_detection_paths_are_unchanged(self):
        # _claude_mcp_config_paths() detects the globally-installed Claude
        # Code app under $HOME, unrelated to which project adapter is
        # installed, so it must keep referencing ~/.claude.json and
        # ~/.claude/settings.json even in the Codex adapter copy.
        module = load_script_module("raven_tool_check_codex_claude_app", CODEX_TOOL_CHECK_SCRIPT)
        home = Path.home()
        paths = module._claude_mcp_config_paths()
        self.assertIn(home / ".claude.json", paths)
        self.assertIn(home / ".claude" / "settings.json", paths)


if __name__ == "__main__":
    unittest.main()
