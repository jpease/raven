"""Opt-in MCP servers: `[mcp] optional` config, rendering, and the upgrade decision.

`gitnexus` used to ship to every repository. Raven owns the rendered MCP files
wholesale, so dropping it from the template would silently remove a working
server from every repository that never edited those files. These tests pin the
behaviour that prevents that: the config key records the decision, an undecided
repository is asked (or keeps the server when it cannot be asked), and nothing
is written on a dry run.
"""

from __future__ import annotations

import contextlib
import io
import json
import re
from pathlib import Path
from unittest import mock

from helpers import RavenTestCase, install_ns, raven, upgrade_ns
from raven_lib.config import (
    ConfigError,
    build_config,
    parse_simple_toml,
    replace_optional_mcp_line,
)
from raven_lib.doctor import optional_mcp_findings
from raven_lib.optional_mcp import decide_optional_mcp, servers_configured_in
from raven_lib.render import (
    load_mcp_servers,
    optional_mcp_catalog,
    render_codex_config_toml,
    render_gemini_settings,
    render_mcp_json,
)

CATALOG = ["gitnexus"]


def _config(text: str):
    return build_config(parse_simple_toml(text), exists=True)


class OptionalMcpConfigTests(RavenTestCase):
    def test_absent_key_is_undecided_and_empty_list_is_decided_none(self):
        self.assertIsNone(_config('template = "python"\n').optional_mcp)
        self.assertEqual(_config("[mcp]\noptional = []\n").optional_mcp, [])
        self.assertEqual(_config('[mcp]\noptional = ["gitnexus"]\n').optional_mcp, ["gitnexus"])

    def test_commented_example_does_not_count_as_a_decision(self):
        text = '# [mcp]\n# optional = ["gitnexus"]\n'
        self.assertIsNone(_config(text).optional_mcp)

    def test_wrong_shape_fails_closed(self):
        for text in ('[mcp]\noptional = "gitnexus"\n', "[mcp]\noptional = [1]\n"):
            with self.subTest(text=text), self.assertRaises(ConfigError):
                _config(text)

    def test_writer_appends_replaces_and_inserts_without_touching_comments(self):
        base = 'template = "python"\n# [mcp]\n# optional = ["gitnexus"]\n'
        appended = replace_optional_mcp_line(base, ["gitnexus"])
        self.assertEqual(_config(appended).optional_mcp, ["gitnexus"])
        self.assertIn('# optional = ["gitnexus"]', appended)  # the comment survives

        replaced = replace_optional_mcp_line(appended, [])
        self.assertEqual(_config(replaced).optional_mcp, [])
        self.assertEqual(replaced.count("[mcp]"), appended.count("[mcp]"))

        bare_header = "[mcp]\n[other]\nx = 1\n"
        inserted = replace_optional_mcp_line(bare_header, ["gitnexus"])
        self.assertTrue(inserted.startswith('[mcp]\noptional = ["gitnexus"]\n'))


class OptionalMcpRenderTests(RavenTestCase):
    def test_default_render_ships_no_gitnexus_in_any_renderer(self):
        self.assertNotIn("gitnexus", json.loads(render_mcp_json(self.template))["mcpServers"])
        self.assertNotIn("gitnexus", render_codex_config_toml(self.template))
        self.assertNotIn("gitnexus", render_gemini_settings(self.template))

    def test_opting_in_adds_the_server_after_semgrep_in_every_renderer(self):
        servers = json.loads(render_mcp_json(self.template, optional=["gitnexus"]))["mcpServers"]
        # Same order the template shipped before the demotion, so a repository that keeps
        # the server renders byte-identically to what it already has.
        self.assertEqual(list(servers)[:2], ["semgrep", "gitnexus"])
        self.assertIn(
            "[mcp_servers.gitnexus]", render_codex_config_toml(self.template, optional=["gitnexus"])
        )
        self.assertIn(
            "gitnexus",
            json.loads(render_gemini_settings(self.template, optional=["gitnexus"]))["mcpServers"],
        )

    def test_empty_optional_equals_the_default_render(self):
        self.assertEqual(
            render_mcp_json(self.template, optional=[]), render_mcp_json(self.template)
        )

    def test_unknown_optional_name_is_rejected_with_the_known_names(self):
        with self.assertRaises(ConfigError) as ctx:
            load_mcp_servers(self.template, optional=["nope"])
        self.assertIn("gitnexus", str(ctx.exception))

    def test_catalog_lists_gitnexus(self):
        self.assertEqual(list(optional_mcp_catalog(self.template)), CATALOG)


class DecideOptionalMcpTests(RavenTestCase):
    def _configure_server(self):
        (self.destination / ".mcp.json").write_text(
            json.dumps({"mcpServers": {"semgrep": {}, "gitnexus": {}}}), encoding="utf-8"
        )

    def test_no_prompt_and_no_write_when_no_server_is_configured(self):
        asked = []
        decision = decide_optional_mcp(
            self.destination,
            _config('template = "python"\n'),
            CATALOG,
            dry_run=False,
            interactive=True,
            ask=lambda name: asked.append(name) or True,
        )
        self.assertEqual((decision.names, decision.write, asked), ([], False, []))

    def test_detects_servers_in_all_three_rendered_files(self):
        (self.destination / ".codex").mkdir()
        (self.destination / ".codex" / "config.toml").write_text(
            '[agents]\nx = 1\n\n[mcp_servers.gitnexus]\ncommand = "gitnexus"\n', encoding="utf-8"
        )
        (self.destination / ".gemini").mkdir()
        (self.destination / ".gemini" / "settings.json").write_text(
            json.dumps({"mcpServers": {"other": {}}}), encoding="utf-8"
        )
        self.assertEqual(servers_configured_in(self.destination), {"gitnexus", "other"})

    def test_interactive_answer_decides_and_is_recorded(self):
        self._configure_server()
        for answer, expected in ((True, ["gitnexus"]), (False, [])):
            with self.subTest(keep=answer):
                decision = decide_optional_mcp(
                    self.destination,
                    _config('template = "python"\n'),
                    CATALOG,
                    dry_run=False,
                    interactive=True,
                    ask=lambda name, a=answer: a,
                )
                self.assertEqual(decision.names, expected)
                self.assertTrue(decision.write)
                self.assertEqual(decision.kept_unasked, [])

    def test_without_a_terminal_the_server_is_kept_not_removed(self):
        self._configure_server()
        decision = decide_optional_mcp(
            self.destination,
            _config('template = "python"\n'),
            CATALOG,
            dry_run=False,
            interactive=False,
            ask=lambda name: self.fail("must not ask without a terminal"),
        )
        self.assertEqual(decision.names, ["gitnexus"])
        self.assertTrue(decision.write)
        self.assertEqual(decision.kept_unasked, ["gitnexus"])

    def test_dry_run_never_asks_and_never_asks_to_write(self):
        self._configure_server()
        decision = decide_optional_mcp(
            self.destination,
            _config('template = "python"\n'),
            CATALOG,
            dry_run=True,
            interactive=True,
            ask=lambda name: self.fail("a dry run must not prompt"),
        )
        self.assertEqual(
            (decision.names, decision.write, decision.pending), (["gitnexus"], False, ["gitnexus"])
        )

    def test_a_recorded_decision_is_honoured_and_never_asked_again(self):
        self._configure_server()
        decision = decide_optional_mcp(
            self.destination,
            _config("[mcp]\noptional = []\n"),
            CATALOG,
            dry_run=False,
            interactive=True,
            ask=lambda name: self.fail("already decided"),
        )
        self.assertEqual((decision.names, decision.write, decision.pending), ([], False, []))

    def test_flags_decide_without_asking_and_win_over_the_recorded_list(self):
        self._configure_server()
        kept = decide_optional_mcp(
            self.destination,
            _config("[mcp]\noptional = []\n"),
            CATALOG,
            keep=["gitnexus"],
            dry_run=False,
            interactive=True,
            ask=lambda n: self.fail("flag decides"),
        )
        dropped = decide_optional_mcp(
            self.destination,
            _config('[mcp]\noptional = ["gitnexus"]\n'),
            CATALOG,
            drop=["gitnexus"],
            dry_run=False,
            interactive=True,
            ask=lambda n: self.fail("flag decides"),
        )
        self.assertEqual((kept.names, kept.write), (["gitnexus"], True))
        self.assertEqual((dropped.names, dropped.write), ([], True))


class UpgradeKeepOrRemoveTests(RavenTestCase):
    """End to end: a repository installed when Raven still shipped `gitnexus`."""

    def _run(self, fn, ns):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            rc = fn(ns)
        return rc, out.getvalue()

    def _config_path(self) -> Path:
        return self.destination / ".raven" / "config.toml"

    def _servers(self) -> list[str]:
        data = json.loads((self.destination / ".mcp.json").read_text(encoding="utf-8"))
        return list(data["mcpServers"])

    def _install_as_if_gitnexus_were_still_the_default(self):
        """Install, opt in to render gitnexus, then forget the decision (a pre-change install)."""
        rc, _ = self._run(raven.cmd_install, install_ns(self.destination))
        self.assertEqual(rc, 0)
        text = self._config_path().read_text(encoding="utf-8")
        self._config_path().write_text(
            replace_optional_mcp_line(text, ["gitnexus"]), encoding="utf-8"
        )
        rc, _ = self._run(raven.cmd_upgrade, upgrade_ns(self.destination))
        self.assertEqual(rc, 0)
        self.assertIn("gitnexus", self._servers())
        undecided = re.sub(
            r"\n\[mcp\]\noptional = \[.*?\]\n",
            "\n",
            self._config_path().read_text(encoding="utf-8"),
        )
        self._config_path().write_text(undecided, encoding="utf-8")
        self.assertIsNone(_config(undecided).optional_mcp)

    def test_non_interactive_upgrade_keeps_the_server_records_it_and_says_so(self):
        self._install_as_if_gitnexus_were_still_the_default()
        rc, out = self._run(raven.cmd_upgrade, upgrade_ns(self.destination))
        self.assertEqual(rc, 0)
        self.assertIn("gitnexus", self._servers())
        self.assertEqual(
            _config(self._config_path().read_text(encoding="utf-8")).optional_mcp, ["gitnexus"]
        )
        self.assertIn("Kept without asking", out)
        self.assertNotIn("Upgraded 2 unchanged", out)  # the MCP files did not change

    def test_drop_flag_removes_the_server_from_pristine_files_and_records_none(self):
        self._install_as_if_gitnexus_were_still_the_default()
        ns = upgrade_ns(self.destination)
        ns.drop_mcp = ["gitnexus"]
        rc, _ = self._run(raven.cmd_upgrade, ns)
        self.assertEqual(rc, 0)
        self.assertNotIn("gitnexus", self._servers())
        self.assertNotIn(
            "gitnexus", (self.destination / ".codex" / "config.toml").read_text(encoding="utf-8")
        )
        self.assertEqual(_config(self._config_path().read_text(encoding="utf-8")).optional_mcp, [])

    def test_dry_run_reports_the_decision_and_writes_nothing(self):
        self._install_as_if_gitnexus_were_still_the_default()
        before_config = self._config_path().read_text(encoding="utf-8")
        before_mcp = (self.destination / ".mcp.json").read_text(encoding="utf-8")
        rc, out = self._run(raven.cmd_upgrade, upgrade_ns(self.destination, dry_run=True))
        self.assertEqual(rc, 0)
        self.assertIn("Decision needed", out)
        self.assertEqual(self._config_path().read_text(encoding="utf-8"), before_config)
        self.assertEqual((self.destination / ".mcp.json").read_text(encoding="utf-8"), before_mcp)

    def test_edited_mcp_json_is_never_rewritten_even_when_the_server_is_dropped(self):
        self._install_as_if_gitnexus_were_still_the_default()
        path = self.destination / ".mcp.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["mcpServers"]["myserver"] = {"command": "echo"}
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        ns = upgrade_ns(self.destination)
        ns.drop_mcp = ["gitnexus"]
        rc, _ = self._run(raven.cmd_upgrade, ns)
        self.assertEqual(rc, 0)
        self.assertEqual(self._servers(), ["semgrep", "gitnexus", "myserver"])
        self.assertTrue((self.destination / ".raven" / "merge" / ".mcp.json.diff").is_file())

    def test_unknown_or_contradictory_flags_fail_before_writing_anything(self):
        self._install_as_if_gitnexus_were_still_the_default()
        before = self._config_path().read_text(encoding="utf-8")
        for keep, drop in ((["nope"], []), (["gitnexus"], ["gitnexus"])):
            with self.subTest(keep=keep, drop=drop):
                ns = upgrade_ns(self.destination)
                ns.keep_mcp, ns.drop_mcp = keep, drop
                rc, _ = self._run(raven.cmd_upgrade, ns)
                self.assertEqual(rc, 2)
                self.assertEqual(self._config_path().read_text(encoding="utf-8"), before)

    def test_interactive_remove_answer_removes_and_is_not_asked_again(self):
        self._install_as_if_gitnexus_were_still_the_default()
        with (
            mock.patch("sys.stdin.isatty", return_value=True),
            mock.patch("builtins.input", return_value="n"),
        ):
            rc, _ = self._run(raven.cmd_upgrade, upgrade_ns(self.destination))
        self.assertEqual(rc, 0)
        self.assertNotIn("gitnexus", self._servers())
        with (
            mock.patch("sys.stdin.isatty", return_value=True),
            mock.patch("builtins.input", side_effect=AssertionError("asked twice")),
        ):
            rc, _ = self._run(raven.cmd_upgrade, upgrade_ns(self.destination))
        self.assertEqual(rc, 0)


class OptionalMcpDoctorTests(RavenTestCase):
    def _ids(self, config_text: str, *, servers=(), index=False) -> dict[str, str]:
        if servers:
            (self.destination / ".mcp.json").write_text(
                json.dumps({"mcpServers": {name: {} for name in servers}}), encoding="utf-8"
            )
        if index:
            (self.destination / ".gitnexus").mkdir()
        config = _config(f'template = "python"\n{config_text}')
        return {f.id: f.severity.value for f in optional_mcp_findings(self.destination, config)}

    def test_configured_server_with_no_recorded_decision_is_an_info_nudge(self):
        self.assertEqual(
            self._ids("", servers=["semgrep", "gitnexus"]),
            {"doctor.mcp.optional_undecided": "info"},
        )

    def test_opted_in_but_not_declared_anywhere_is_a_warning(self):
        ids = self._ids('[mcp]\noptional = ["gitnexus"]\n', servers=["semgrep"])
        self.assertEqual(ids, {"doctor.mcp.optional_not_rendered": "warn"})

    def test_index_without_any_config_is_an_info(self):
        self.assertEqual(
            self._ids("", servers=["semgrep"], index=True),
            {"doctor.mcp.index_without_server": "info"},
        )

    def test_an_explicit_none_stays_silent_even_with_an_index(self):
        self.assertEqual(self._ids("[mcp]\noptional = []\n", servers=["semgrep"], index=True), {})

    def test_a_consistent_opt_in_is_clean(self):
        ids = self._ids(
            '[mcp]\noptional = ["gitnexus"]\n', servers=["semgrep", "gitnexus"], index=True
        )
        self.assertEqual(ids, {})


class OptionalMcpCleanupTests(RavenTestCase):
    def test_new_mcp_section_is_written_with_an_explanatory_comment(self):
        text = replace_optional_mcp_line('template = "python"\n', [])
        self.assertIn("Opt-in MCP servers", text)
        self.assertEqual(_config(text).optional_mcp, [])

    def test_known_code_index_tools_all_exist_in_the_tool_check_list(self):
        from helpers import REPO_ROOT, load_script_module
        from raven_lib.optional_mcp import CODE_INDEX_DIRS

        script = REPO_ROOT / "common" / ".claude" / "scripts" / "raven-tool-check.py"
        module = load_script_module("raven_tool_check_cleanup", script)
        ids = {tool["id"] for tool in module.TOOLS}
        self.assertEqual(set(CODE_INDEX_DIRS) - ids, set())

    def test_doctor_flags_the_vendor_block_and_names_the_fix(self):
        (self.destination / "AGENTS.md").write_text(
            "# x\n<!-- gitnexus:start -->\nMUST run impact\n<!-- gitnexus:end -->\n",
            encoding="utf-8",
        )
        findings = {
            f.id: f
            for f in optional_mcp_findings(self.destination, _config('template = "python"\n'))
        }
        finding = findings["doctor.mcp.gitnexus_block"]
        self.assertEqual(finding.severity.value, "info")
        self.assertIn("skipContextFiles", finding.fix or "")

    def test_no_vendor_block_means_no_finding(self):
        (self.destination / "AGENTS.md").write_text("# x\n", encoding="utf-8")
        ids = {
            f.id for f in optional_mcp_findings(self.destination, _config('template = "python"\n'))
        }
        self.assertNotIn("doctor.mcp.gitnexus_block", ids)

    def test_deliberate_removal_gets_no_wire_it_up_hint(self):
        from raven_lib.doctor import _code_index_finding

        finding = _code_index_finding("gitnexus", "GitNexus", True, False, {}, decided_none=True)
        self.assertIn("removed by choice", finding.title)
        self.assertIsNone(finding.fix)

    def test_diff_instructions_warn_that_local_additions_look_like_removals(self):
        from raven_lib.blocks import guided_merge_instructions

        body = guided_merge_instructions(
            ".mcp.json", ".raven/merge/.mcp.json.raven", None, ".raven/merge/.mcp.json.diff"
        )
        self.assertIn("shows up as a removal", body)
