"""`raven doctor` reports whether Codex will load the installed `.codex/` layer.

Codex reads a project's `.codex/` directory -- config, hooks, rules, custom
agents -- only for a project its user config trusts, and says nothing when it
skips one. Before this check, a Codex install could pass every other doctor
finding while enforcing nothing.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from helpers import RavenTestCase
from raven_lib.codex_trust import codex_home, project_trust, trust_entries
from raven_lib.doctor import build_doctor_findings, codex_trust_findings
from raven_lib.findings import Severity


class TrustEntriesTests(RavenTestCase):
    """The scanner reads `[projects.<path>]` tables and nothing else."""

    def test_single_quoted_header_is_read(self):
        text = "[projects.'/srv/app']\ntrust_level = 'trusted'\n"
        self.assertEqual(trust_entries(text), {"/srv/app": "trusted"})

    def test_double_quoted_header_and_value_are_read(self):
        text = '[projects."/srv/app"]\ntrust_level = "trusted"\n'
        self.assertEqual(trust_entries(text), {"/srv/app": "trusted"})

    def test_commented_out_header_is_not_a_header(self):
        text = "# [projects.'/srv/app']\n# trust_level = 'trusted'\n"
        self.assertEqual(trust_entries(text), {})

    def test_trust_level_outside_a_projects_table_is_ignored(self):
        text = "[features]\ntrust_level = 'trusted'\n[projects.'/srv/app']\n"
        self.assertEqual(trust_entries(text), {"/srv/app": ""})

    def test_other_sections_end_the_projects_table(self):
        text = "[projects.'/srv/app']\n[mcp_servers.x]\ntrust_level = 'trusted'\n"
        self.assertEqual(trust_entries(text), {"/srv/app": ""})

    def test_unrelated_constructs_do_not_break_the_scan(self):
        # Codex's own config carries arrays and inline tables this
        # repository's TOML subset rejects; the scanner must read past them.
        text = (
            "model = 'o3'\n"
            "[features]\n"
            "hooks = true\n"
            "[[hooks.PreToolUse]]\n"
            "matcher = '^Bash$'\n"
            "[projects.'/srv/app']\n"
            "trust_level = 'untrusted'\n"
            "extra = { a = [1, 2] }\n"
        )
        self.assertEqual(trust_entries(text), {"/srv/app": "untrusted"})


class ProjectTrustTests(RavenTestCase):
    def setUp(self):
        super().setUp()
        self.home = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(self.home, ignore_errors=True))
        self.config = self.home / "config.toml"

    def _entry(self, path: Path, level: str = "trusted") -> str:
        return f"[projects.'{path}']\ntrust_level = '{level}'\n"

    def test_no_config_file_is_none(self):
        self.assertIsNone(project_trust(self.destination, self.config))

    def test_no_covering_entry_is_empty(self):
        self.config.write_text(self._entry(Path("/somewhere/else")), encoding="utf-8")
        self.assertEqual(project_trust(self.destination, self.config), "")

    def test_exact_path_is_trusted(self):
        self.config.write_text(self._entry(self.destination.resolve()), encoding="utf-8")
        self.assertEqual(project_trust(self.destination, self.config), "trusted")

    def test_unresolved_spelling_of_the_path_still_matches(self):
        # macOS hands out /var/... paths that resolve to /private/var/...;
        # Codex may record either spelling.
        self.config.write_text(self._entry(self.destination), encoding="utf-8")
        self.assertEqual(project_trust(self.destination, self.config), "trusted")

    def test_trusted_ancestor_covers_the_project(self):
        self.config.write_text(self._entry(self.destination.resolve().parent), encoding="utf-8")
        self.assertEqual(project_trust(self.destination, self.config), "trusted")

    def test_explicit_untrusted_is_reported(self):
        self.config.write_text(
            self._entry(self.destination.resolve(), "untrusted"), encoding="utf-8"
        )
        self.assertEqual(project_trust(self.destination, self.config), "untrusted")

    def test_nearest_entry_wins_over_a_trusted_ancestor(self):
        text = self._entry(self.destination.resolve().parent) + self._entry(
            self.destination.resolve(), "untrusted"
        )
        self.config.write_text(text, encoding="utf-8")
        self.assertEqual(project_trust(self.destination, self.config), "untrusted")

    def test_codex_home_honors_the_environment(self):
        with mock.patch.dict(os.environ, {"CODEX_HOME": str(self.home)}):
            self.assertEqual(codex_home(), self.home)
        with mock.patch.dict(os.environ, {"CODEX_HOME": ""}):
            self.assertEqual(codex_home(), Path.home() / ".codex")


class DoctorCodexTrustTests(RavenTestCase):
    def setUp(self):
        super().setUp()
        self.home = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(self.home, ignore_errors=True))
        patcher = mock.patch.dict(os.environ, {"CODEX_HOME": str(self.home)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def _install(self, *, codex_dir=True, codex_components=None):
        (self.destination / ".raven").mkdir()
        lines = ['schema = 1', 'template = "python"']
        if codex_components is not None:
            lines.append("[components.codex]")
            lines.extend(f"{name} = {'true' if on else 'false'}" for name, on in codex_components)
        (self.destination / ".raven" / "config.toml").write_text(
            "\n".join(lines) + "\n", encoding="utf-8"
        )
        (self.destination / "AGENTS.md").write_text("# A\n", encoding="utf-8")
        if codex_dir:
            (self.destination / ".codex").mkdir()
            (self.destination / ".codex" / "hooks.json").write_text("{}", encoding="utf-8")

    def _trust(self, path: Path, level: str = "trusted") -> None:
        (self.home / "config.toml").write_text(
            f"[projects.'{path}']\ntrust_level = '{level}'\n", encoding="utf-8"
        )

    def _by_id(self, findings):
        return {f.id: f for f in findings}

    def test_no_codex_directory_reports_nothing(self):
        self._install(codex_dir=False)
        self.assertEqual(codex_trust_findings(self.destination), [])

    def test_every_codex_component_disabled_reports_nothing(self):
        self._install(
            codex_components=[
                ("config", False),
                ("hooks", False),
                ("scripts", False),
                ("subagents", False),
                ("rules", False),
            ]
        )
        self.assertEqual(codex_trust_findings(self.destination), [])

    def test_no_codex_config_on_the_machine_is_info(self):
        self._install()
        findings = self._by_id(codex_trust_findings(self.destination))
        self.assertEqual(findings["doctor.codex.unconfigured"].severity, Severity.INFO)
        self.assertIn("inert", findings["doctor.codex.unconfigured"].detail)

    def test_untrusted_by_omission_is_warn(self):
        self._install()
        self._trust(Path("/somewhere/else"))
        findings = self._by_id(codex_trust_findings(self.destination))
        finding = findings["doctor.codex.untrusted"]
        self.assertEqual(finding.severity, Severity.WARN)
        self.assertIn("no [projects] entry", finding.detail)
        self.assertIn("/hooks", finding.fix or "")

    def test_explicitly_untrusted_is_warn_with_its_own_wording(self):
        self._install()
        self._trust(self.destination.resolve(), "untrusted")
        findings = self._by_id(codex_trust_findings(self.destination))
        finding = findings["doctor.codex.untrusted"]
        self.assertEqual(finding.severity, Severity.WARN)
        self.assertIn("untrusted", finding.title)

    def test_trusted_project_is_ok(self):
        self._install()
        self._trust(self.destination.resolve())
        findings = self._by_id(codex_trust_findings(self.destination))
        self.assertEqual(findings["doctor.codex.trusted"].severity, Severity.OK)
        self.assertNotIn("doctor.codex.untrusted", findings)

    def test_trusted_ancestor_is_ok(self):
        self._install()
        self._trust(self.destination.resolve().parent)
        findings = self._by_id(codex_trust_findings(self.destination))
        self.assertIn("doctor.codex.trusted", findings)

    def test_full_doctor_report_carries_the_check(self):
        self._install()
        self._trust(Path("/somewhere/else"))
        ids = {f.id for f in build_doctor_findings(self.destination)}
        self.assertIn("doctor.codex.untrusted", ids)
