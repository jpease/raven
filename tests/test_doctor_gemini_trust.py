"""`raven doctor` reports whether Gemini CLI will load the installed `.gemini/` layer.

Gemini CLI skips a project's `.gemini/` directory -- settings, hooks, policies, custom
agents -- only for a project its trust store trusts, and records that in
`~/.gemini/trustedFolders.json`. This module lets `raven doctor` report trust status.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from helpers import RavenTestCase
from raven_lib.doctor import build_doctor_findings, gemini_trust_findings
from raven_lib.findings import Severity
from raven_lib.gemini_trust import (
    DO_NOT_TRUST,
    TRUST_FOLDER,
    TRUST_PARENT,
    gemini_home,
    gemini_trust_store_path,
    project_trust,
    trust_entries,
)


class TrustEntriesTests(RavenTestCase):
    """The parser reads the trustedFolders.json map."""

    def test_json_map_is_read(self):
        text = json.dumps({"/srv/app": TRUST_FOLDER})
        self.assertEqual(trust_entries(text), {"/srv/app": TRUST_FOLDER})

    def test_empty_invalid_or_non_object_json_is_rejected(self):
        for text in ("", "not json", "[]"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                trust_entries(text)

    def test_json_comments_are_accepted(self):
        text = '{\n  // selected in the Gemini prompt\n  "/srv/app": "TRUST_FOLDER"\n}\n'
        self.assertEqual(trust_entries(text), {"/srv/app": TRUST_FOLDER})


class ProjectTrustTests(RavenTestCase):
    def setUp(self):
        super().setUp()
        self.home = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(self.home, ignore_errors=True))
        (self.home / ".gemini").mkdir()
        self.store = self.home / ".gemini" / "trustedFolders.json"

    def _entry(self, path: Path, level: str = TRUST_FOLDER) -> str:
        return json.dumps({str(path): level})

    def test_no_config_file_is_none(self):
        self.assertIsNone(project_trust(self.destination, self.store))

    def test_no_covering_entry_is_empty(self):
        self.store.write_text(self._entry(Path("/somewhere/else")), encoding="utf-8")
        self.assertEqual(project_trust(self.destination, self.store), "")

    def test_exact_path_is_trusted(self):
        self.store.write_text(self._entry(self.destination.resolve()), encoding="utf-8")
        self.assertEqual(project_trust(self.destination, self.store), "trusted")

    def test_unresolved_spelling_of_the_path_still_matches(self):
        self.store.write_text(self._entry(self.destination), encoding="utf-8")
        self.assertEqual(project_trust(self.destination, self.store), "trusted")

    def test_macos_path_matching_is_case_insensitive(self):
        differently_cased = str(self.destination.resolve()).swapcase()
        self.store.write_text(json.dumps({differently_cased: TRUST_FOLDER}), encoding="utf-8")
        with mock.patch("raven_lib.gemini_trust.sys.platform", "darwin"):
            self.assertEqual(project_trust(self.destination, self.store), "trusted")

    def test_trust_parent_record_trusts_the_recorded_paths_parent_tree(self):
        recorded_path = self.destination.resolve().parent / "sibling-selected-in-prompt"
        self.store.write_text(self._entry(recorded_path, TRUST_PARENT), encoding="utf-8")
        self.assertEqual(project_trust(self.destination, self.store), "trusted")

    def test_longest_recorded_path_wins_when_symlinks_canonicalize_alike(self):
        real_parent = self.home / "r"
        real_parent.mkdir()
        target = real_parent / "project"
        target.mkdir()
        symlink_parent = self.home / "much-longer-symlink-spelling"
        symlink_parent.symlink_to(real_parent, target_is_directory=True)
        data = {
            str(real_parent): DO_NOT_TRUST,
            str(symlink_parent): TRUST_FOLDER,
        }
        self.store.write_text(json.dumps(data), encoding="utf-8")
        self.assertEqual(project_trust(target, self.store), "trusted")

    def test_explicit_untrusted_is_reported(self):
        self.store.write_text(
            self._entry(self.destination.resolve(), DO_NOT_TRUST), encoding="utf-8"
        )
        self.assertEqual(project_trust(self.destination, self.store), "untrusted")

    def test_longest_matching_recorded_path_wins(self):
        data = {
            str(self.destination.resolve().parent): TRUST_FOLDER,
            str(self.destination.resolve()): DO_NOT_TRUST,
        }
        self.store.write_text(json.dumps(data), encoding="utf-8")
        self.assertEqual(project_trust(self.destination, self.store), "untrusted")

    def test_invalid_trust_level_is_reported_as_invalid(self):
        self.store.write_text(
            self._entry(self.destination.resolve(), "trust_folder"), encoding="utf-8"
        )
        self.assertEqual(project_trust(self.destination, self.store), "invalid")

    def test_gemini_home_honors_the_environment(self):
        with mock.patch.dict(os.environ, {"GEMINI_CLI_HOME": str(self.home)}):
            self.assertEqual(gemini_home(), self.home / ".gemini")
        with (
            mock.patch.dict(os.environ, {"GEMINI_CLI_HOME": ""}),
            mock.patch("raven_lib.gemini_trust.Path.home", return_value=self.home),
        ):
            self.assertEqual(gemini_home(), self.home / ".gemini")

    def test_default_store_follows_gemini_home(self):
        self.store.write_text(self._entry(self.destination.resolve()), encoding="utf-8")
        with mock.patch.dict(
            os.environ,
            {
                "GEMINI_CLI_HOME": str(self.home),
                "GEMINI_CLI_TRUSTED_FOLDERS_PATH": "",
            },
        ):
            self.assertEqual(gemini_trust_store_path(), self.store)
            self.assertEqual(project_trust(self.destination), "trusted")

    def test_store_path_override_wins_over_gemini_home(self):
        override = self.home / "override.json"
        override.write_text(self._entry(self.destination.resolve()), encoding="utf-8")
        with mock.patch.dict(
            os.environ,
            {
                "GEMINI_CLI_HOME": str(self.home / "unused"),
                "GEMINI_CLI_TRUSTED_FOLDERS_PATH": str(override),
            },
        ):
            self.assertEqual(gemini_trust_store_path(), override)
            self.assertEqual(project_trust(self.destination), "trusted")


class DoctorGeminiTrustTests(RavenTestCase):
    def setUp(self):
        super().setUp()
        self.home = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(self.home, ignore_errors=True))
        (self.home / ".gemini").mkdir()
        self.store = self.home / ".gemini" / "trustedFolders.json"
        patcher = mock.patch.dict(
            os.environ,
            {
                "GEMINI_CLI_HOME": str(self.home),
                "GEMINI_CLI_TRUSTED_FOLDERS_PATH": "",
            },
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def _install(self, *, gemini_dir=True, gemini_components=None):
        (self.destination / ".raven").mkdir()
        lines = ["schema = 1", 'template = "python"']
        lines.append("[components.gemini]")
        if gemini_components is not None:
            lines.extend(f"{name} = {'true' if on else 'false'}" for name, on in gemini_components)
        else:
            lines.append("settings = true")
        (self.destination / ".raven" / "config.toml").write_text(
            "\n".join(lines) + "\n", encoding="utf-8"
        )
        (self.destination / "AGENTS.md").write_text("# A\n", encoding="utf-8")
        if gemini_dir:
            (self.destination / ".gemini").mkdir()
            (self.destination / ".gemini" / "settings.json").write_text("{}", encoding="utf-8")

    def _trust(self, path: Path, level: str = TRUST_FOLDER) -> None:
        self.store.write_text(json.dumps({str(path): level}), encoding="utf-8")

    def _by_id(self, findings):
        return {f.id: f for f in findings}

    def test_no_gemini_directory_reports_nothing(self):
        self._install(gemini_dir=False)
        self.assertEqual(gemini_trust_findings(self.destination), [])

    def test_every_gemini_component_disabled_reports_nothing(self):
        self._install(
            gemini_components=[
                ("root_instructions", False),
                ("settings", False),
                ("hooks", False),
                ("scripts", False),
                ("subagents", False),
                ("rules", False),
            ]
        )
        self.assertEqual(gemini_trust_findings(self.destination), [])

    def test_no_gemini_trust_store_on_the_machine_is_info(self):
        self._install()
        findings = self._by_id(gemini_trust_findings(self.destination))
        self.assertEqual(findings["doctor.gemini.unconfigured"].severity, Severity.INFO)
        self.assertIn("inert", findings["doctor.gemini.unconfigured"].detail)

    def test_untrusted_by_omission_is_warn(self):
        self._install()
        self._trust(Path("/somewhere/else"))
        findings = self._by_id(gemini_trust_findings(self.destination))
        finding = findings["doctor.gemini.untrusted"]
        self.assertEqual(finding.severity, Severity.WARN)
        self.assertIn("no trustedFolders.json entry", finding.detail)

    def test_explicitly_untrusted_is_warn_with_its_own_wording(self):
        self._install()
        self._trust(self.destination.resolve(), DO_NOT_TRUST)
        findings = self._by_id(gemini_trust_findings(self.destination))
        finding = findings["doctor.gemini.untrusted"]
        self.assertEqual(finding.severity, Severity.WARN)
        self.assertIn("untrusted", finding.title)
        self.assertIn("/permissions", finding.fix or "")

    def test_invalid_trust_store_is_error(self):
        self._install()
        self.store.write_text(
            json.dumps({str(self.destination.resolve()): "trust_folder"}),
            encoding="utf-8",
        )
        findings = self._by_id(gemini_trust_findings(self.destination))
        finding = findings["doctor.gemini.invalid"]
        self.assertEqual(finding.severity, Severity.ERROR)
        self.assertIn("invalid", finding.title.lower())

    def test_trusted_project_is_ok(self):
        self._install()
        self._trust(self.destination.resolve())
        findings = self._by_id(gemini_trust_findings(self.destination))
        self.assertEqual(findings["doctor.gemini.trusted"].severity, Severity.OK)
        self.assertNotIn("doctor.gemini.untrusted", findings)

    def test_trusted_ancestor_is_ok(self):
        self._install()
        self._trust(self.destination.resolve().parent)
        findings = self._by_id(gemini_trust_findings(self.destination))
        self.assertIn("doctor.gemini.trusted", findings)

    def test_full_doctor_report_carries_the_check(self):
        self._install()
        self._trust(Path("/somewhere/else"))
        ids = {f.id for f in build_doctor_findings(self.destination)}
        self.assertIn("doctor.gemini.untrusted", ids)


if __name__ == "__main__":
    import unittest

    unittest.main()
