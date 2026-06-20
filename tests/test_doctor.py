import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from helpers import RavenTestCase
from raven_lib.doctor import drift_findings, integrity_findings
from raven_lib.findings import Severity
from raven_lib.models import Classification
from raven_lib.runner import RunResult


def _classification(needs_merge, local_only=()):
    return Classification(
        will_copy=[],
        will_upgrade=[],
        identical=[],
        needs_merge=list(needs_merge),
        unknown_existing=[],
        excluded=[],
        local_only=list(local_only),
    )


class DoctorIntegrityTests(RavenTestCase):
    def _ids(self, findings):
        return {f.id: f for f in findings}

    def test_missing_config_is_single_error(self):
        findings = integrity_findings(self.destination)
        ids = self._ids(findings)
        self.assertIn("doctor.install.config", ids)
        self.assertEqual(ids["doctor.install.config"].severity, Severity.ERROR)

    def test_missing_agents_md_is_error_when_config_exists(self):
        (self.destination / ".raven").mkdir()
        (self.destination / ".raven" / "config.toml").write_text(
            'schema = 1\ntemplate = "python"\n', encoding="utf-8"
        )
        findings = integrity_findings(self.destination)
        ids = self._ids(findings)
        self.assertEqual(ids["doctor.install.config"].severity, Severity.OK)
        self.assertIn("doctor.install.agents", ids)
        self.assertEqual(ids["doctor.install.agents"].severity, Severity.ERROR)

    def test_disabled_root_instructions_skips_agents_and_symlink(self):
        (self.destination / ".raven").mkdir()
        (self.destination / ".raven" / "config.toml").write_text(
            'schema = 1\ntemplate = "python"\n\n[components]\nroot_instructions = false\n',
            encoding="utf-8",
        )
        findings = integrity_findings(self.destination)
        ids = self._ids(findings)
        self.assertNotIn("doctor.install.agents", ids)
        self.assertNotIn("doctor.install.symlink", ids)
        self.assertFalse(any(f.severity == Severity.ERROR for f in findings))

    def test_enabled_root_instructions_still_errors_when_missing(self):
        (self.destination / ".raven").mkdir()
        (self.destination / ".raven" / "config.toml").write_text(
            'schema = 1\ntemplate = "python"\n\n[components]\nroot_instructions = true\n',
            encoding="utf-8",
        )
        findings = integrity_findings(self.destination)
        ids = self._ids(findings)
        self.assertIn("doctor.install.agents", ids)
        self.assertEqual(ids["doctor.install.agents"].severity, Severity.ERROR)
        self.assertIn("doctor.install.symlink", ids)

    def test_correct_claude_symlink_is_ok(self):
        (self.destination / ".raven").mkdir()
        (self.destination / ".raven" / "config.toml").write_text(
            'schema = 1\ntemplate = "python"\n', encoding="utf-8"
        )
        (self.destination / "AGENTS.md").write_text("# A\n", encoding="utf-8")
        (self.destination / "CLAUDE.md").symlink_to("AGENTS.md")
        findings = integrity_findings(self.destination)
        ids = self._ids(findings)
        self.assertEqual(ids["doctor.install.symlink"].severity, Severity.OK)

    def test_claude_regular_file_is_warn(self):
        (self.destination / ".raven").mkdir()
        (self.destination / ".raven" / "config.toml").write_text(
            'schema = 1\ntemplate = "python"\n', encoding="utf-8"
        )
        (self.destination / "AGENTS.md").write_text("# A\n", encoding="utf-8")
        (self.destination / "CLAUDE.md").write_text("not a symlink\n", encoding="utf-8")
        findings = integrity_findings(self.destination)
        ids = self._ids(findings)
        self.assertEqual(ids["doctor.install.symlink"].severity, Severity.WARN)


class DoctorDriftTests(RavenTestCase):
    def _config(self):
        (self.destination / ".raven").mkdir()
        (self.destination / ".raven" / "config.toml").write_text(
            'schema = 1\ntemplate = "python"\n', encoding="utf-8"
        )

    def _drift(self, *, needs_merge, pending, local_only=()):
        self._config()
        with (
            mock.patch(
                "raven_lib.doctor.classify",
                return_value=_classification(needs_merge, local_only=local_only),
            ),
            mock.patch("raven_lib.doctor.pending_merge_paths", return_value=list(pending)),
        ):
            return {f.id: f for f in drift_findings(self.destination)}

    def test_clean_destination_reports_ok_modified(self):
        self._config()
        findings = drift_findings(self.destination)
        ids = {f.id for f in findings}
        self.assertIn("doctor.drift.modified", ids)

    def test_pending_files_excluded_from_modified_count(self):
        shared = ".claude/rules/raven-python.md"
        only_modified = "pyproject.toml"
        findings = self._drift(needs_merge=[shared, only_modified], pending=[shared])
        modified = findings["doctor.drift.modified"]
        self.assertEqual(modified.severity, Severity.WARN)
        self.assertIn("1 Raven-owned file", modified.title)
        self.assertEqual(modified.detail, only_modified)
        self.assertNotIn(shared, modified.detail)
        self.assertIn("1 pending guided merge", findings["doctor.drift.pending"].title)

    def test_all_modified_are_pending_suppresses_modified_finding(self):
        shared = ".claude/rules/raven-python.md"
        findings = self._drift(needs_merge=[shared], pending=[shared])
        # Nothing is modified-without-a-merge, so no modified finding at all --
        # and no spurious "no drift detected" OK while a merge is still pending.
        self.assertNotIn("doctor.drift.modified", findings)
        self.assertIn("doctor.drift.pending", findings)

    def test_no_drift_and_no_pending_reports_ok(self):
        findings = self._drift(needs_merge=[], pending=[])
        self.assertEqual(findings["doctor.drift.modified"].severity, Severity.OK)
        self.assertNotIn("doctor.drift.pending", findings)

    def test_local_only_is_info_not_modified_warning(self):
        findings = self._drift(needs_merge=[], pending=[], local_only=["justfile"])
        # A locally customized file with no upstream change is informational,
        # never a WARN, and does not trigger the "no drift" OK either.
        self.assertIn("doctor.drift.local", findings)
        self.assertEqual(findings["doctor.drift.local"].severity, Severity.INFO)
        self.assertIn("justfile", findings["doctor.drift.local"].detail)
        self.assertNotIn("doctor.drift.modified", findings)


def _fake_toolcheck_runner(results):
    payload = json.dumps({"os": "darwin", "results": results})

    def runner(command, cwd):
        if any("raven-tool-check.py" in part for part in command):
            return RunResult(
                ok=True, code=0, stdout=payload, stderr="", found=True, timed_out=False
            )
        return RunResult(ok=True, code=0, stdout="1.0\n", stderr="", found=True, timed_out=False)

    return runner


class DoctorToolchainTests(RavenTestCase):
    def _config(self):
        (self.destination / ".raven").mkdir()
        (self.destination / ".raven" / "config.toml").write_text(
            'schema = 1\ntemplate = "python"\n', encoding="utf-8"
        )

    def test_available_tool_is_ok(self):
        from raven_lib.doctor import toolchain_findings
        from raven_lib.findings import Severity

        self._config()
        results = [
            {
                "id": "rg",
                "name": "ripgrep",
                "available": True,
                "purpose": "search",
                "optionalWhen": None,
            }
        ]
        findings = toolchain_findings(self.destination, _fake_toolcheck_runner(results))
        match = next(f for f in findings if f.id == "doctor.tool.rg")
        self.assertEqual(match.severity, Severity.OK)

    def test_missing_tool_is_warn_never_error(self):
        from raven_lib.doctor import toolchain_findings
        from raven_lib.findings import Severity

        self._config()
        results = [
            {"id": "fd", "name": "fd", "available": False, "purpose": "find", "optionalWhen": None}
        ]
        findings = toolchain_findings(self.destination, _fake_toolcheck_runner(results))
        match = next(f for f in findings if f.id == "doctor.tool.fd")
        self.assertEqual(match.severity, Severity.WARN)
        self.assertFalse(any(f.severity == Severity.ERROR for f in findings))


if __name__ == "__main__":
    unittest.main()
