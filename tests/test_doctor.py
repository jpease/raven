import argparse
import contextlib
import io
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from helpers import RavenTestCase, raven
from raven_lib.doctor import build_doctor_findings, drift_findings, integrity_findings
from raven_lib.findings import Severity, exit_code
from raven_lib.models import Classification
from raven_lib.runner import RunResult


def _classification(needs_merge, local_only=(), will_copy=()):
    return Classification(
        will_copy=list(will_copy),
        will_upgrade=[],
        identical=[],
        needs_merge=list(needs_merge),
        unknown_existing=[],
        excluded=[],
        local_only=list(local_only),
    )


def _install(testcase):
    """Perform a real Raven install of the python template into the temp dir."""
    ns = argparse.Namespace(
        destination=str(testcase.destination),
        language="python",
        args=None,
        overrides=[],
        dry_run=False,
        include_readme=False,
        adopt_claude_symlink=False,
        platform=None,
    )
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        rc = raven.cmd_install(ns)
    testcase.assertEqual(rc, 0)


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

    def test_unsupported_template_is_error(self):
        # Issue #50 — a configured but unsupported template must surface as ERROR
        # so a corrupted or mistyped template name cannot appear healthy.
        (self.destination / ".raven").mkdir()
        (self.destination / ".raven" / "config.toml").write_text(
            'schema = 1\ntemplate = "bogus"\n', encoding="utf-8"
        )
        ids = self._ids(integrity_findings(self.destination))
        self.assertIn("doctor.install.template", ids)
        self.assertEqual(ids["doctor.install.template"].severity, Severity.ERROR)


class DoctorDriftTests(RavenTestCase):
    def _config(self):
        (self.destination / ".raven").mkdir()
        (self.destination / ".raven" / "config.toml").write_text(
            'schema = 1\ntemplate = "python"\n', encoding="utf-8"
        )

    def _drift(self, *, needs_merge, pending, local_only=(), will_copy=()):
        self._config()
        with (
            mock.patch(
                "raven_lib.doctor.classify",
                return_value=_classification(
                    needs_merge, local_only=local_only, will_copy=will_copy
                ),
            ),
            mock.patch("raven_lib.doctor.pending_merge_paths", return_value=list(pending)),
        ):
            return {f.id: f for f in drift_findings(self.destination)}

    def test_complete_install_reports_ok_modified(self):
        _install(self)
        findings = drift_findings(self.destination)
        ids = {f.id for f in findings}
        self.assertIn("doctor.drift.modified", ids)

    def test_missing_files_reported_and_suppress_ok(self):
        # will_copy holds template entries absent from the destination -- i.e.
        # individually deleted managed files. They must surface as drift, not be
        # masked by a "no drift detected" OK finding.
        findings = self._drift(
            needs_merge=[],
            pending=[],
            will_copy=[".claude/docs/raven-authority-map.md"],
        )
        self.assertIn("doctor.drift.missing", findings)
        self.assertEqual(findings["doctor.drift.missing"].severity, Severity.WARN)
        self.assertIn("raven-authority-map.md", findings["doctor.drift.missing"].detail)
        self.assertNotIn("doctor.drift.modified", findings)

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

    def test_unsupported_template_drift_returns_error_not_false_ok(self):
        # Issue #50 — drift with an unsupported template must emit an ERROR and
        # must never produce a false "No Raven-owned drift detected" OK finding.
        (self.destination / ".raven").mkdir()
        (self.destination / ".raven" / "config.toml").write_text(
            'schema = 1\ntemplate = "bogus"\n', encoding="utf-8"
        )
        findings = {f.id: f for f in drift_findings(self.destination)}
        # Must not report a healthy "no drift" OK
        ok_modified = findings.get("doctor.drift.modified")
        self.assertFalse(ok_modified and ok_modified.severity == Severity.OK)
        # Must surface an ERROR that explains the unusable template
        self.assertTrue(any(f.severity == Severity.ERROR for f in findings.values()))


# ---------------------------------------------------------------------------
# #39 -- doctor must report individually deleted managed files
# ---------------------------------------------------------------------------
class DoctorMissingFilesTests(RavenTestCase):
    def test_complete_install_reports_no_missing(self):
        _install(self)
        findings = {f.id: f for f in drift_findings(self.destination)}
        self.assertNotIn("doctor.drift.missing", findings)
        self.assertEqual(findings["doctor.drift.modified"].severity, Severity.OK)

    def test_deleted_file_from_multifile_component_is_reported(self):
        _install(self)
        deleted = self.destination / ".claude" / "docs" / "raven-authority-map.md"
        self.assertTrue(deleted.exists())
        deleted.unlink()
        findings = {f.id: f for f in drift_findings(self.destination)}
        self.assertIn("doctor.drift.missing", findings)
        self.assertEqual(findings["doctor.drift.missing"].severity, Severity.WARN)
        self.assertIn(
            ".claude/docs/raven-authority-map.md", findings["doctor.drift.missing"].detail
        )
        # The no-drift OK finding must not claim health while a file is missing.
        self.assertNotIn("doctor.drift.modified", findings)

    def test_deleted_expected_symlink_is_reported(self):
        _install(self)
        symlink = self.destination / ".claude" / "skills"
        self.assertTrue(symlink.is_symlink())
        symlink.unlink()
        findings = {f.id: f for f in drift_findings(self.destination)}
        self.assertIn("doctor.drift.missing", findings)
        self.assertIn(".claude/skills", findings["doctor.drift.missing"].detail)
        self.assertNotIn("doctor.drift.modified", findings)


# ---------------------------------------------------------------------------
# #40 -- doctor must validate the manifest before reporting it healthy
# ---------------------------------------------------------------------------
class DoctorManifestTests(RavenTestCase):
    def _config(self):
        (self.destination / ".raven").mkdir(parents=True, exist_ok=True)
        (self.destination / ".raven" / "config.toml").write_text(
            'schema = 1\ntemplate = "python"\n', encoding="utf-8"
        )

    def _write_manifest(self, text):
        (self.destination / ".raven").mkdir(parents=True, exist_ok=True)
        (self.destination / ".raven" / "manifest.json").write_text(text, encoding="utf-8")

    def _manifest_finding(self):
        self._config()
        ids = {f.id: f for f in integrity_findings(self.destination)}
        return ids["doctor.install.manifest"]

    def test_valid_manifest_is_ok(self):
        self._write_manifest(json.dumps({"schema": 1, "files": {}}))
        self.assertEqual(self._manifest_finding().severity, Severity.OK)

    def test_missing_manifest_is_warn(self):
        self._config()
        ids = {f.id: f for f in integrity_findings(self.destination)}
        self.assertEqual(ids["doctor.install.manifest"].severity, Severity.WARN)

    def test_malformed_json_is_error(self):
        self._write_manifest("{bad")
        self.assertEqual(self._manifest_finding().severity, Severity.ERROR)

    def test_non_object_root_is_error(self):
        self._write_manifest("[]")
        self.assertEqual(self._manifest_finding().severity, Severity.ERROR)

    def test_invalid_files_is_error(self):
        self._write_manifest(json.dumps({"schema": 1, "files": []}))
        self.assertEqual(self._manifest_finding().severity, Severity.ERROR)

    def test_unsupported_schema_is_warn(self):
        self._write_manifest(json.dumps({"schema": 99, "files": {}}))
        finding = self._manifest_finding()
        self.assertEqual(finding.severity, Severity.WARN)
        self.assertIsNotNone(finding.fix)

    def test_corrupt_manifest_suppresses_no_drift_ok_without_stderr(self):
        _install(self)
        self._write_manifest("{bad")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            drift = {f.id: f for f in drift_findings(self.destination)}
            integ = {f.id: f for f in integrity_findings(self.destination)}
        # An unusable manifest must block the "no drift detected" OK finding...
        self.assertNotIn("doctor.drift.modified", drift)
        # ...and the manifest finding must be a structured ERROR.
        self.assertEqual(integ["doctor.install.manifest"].severity, Severity.ERROR)
        # JSON/structured callers must not depend on stderr for the diagnosis.
        self.assertEqual(err.getvalue(), "")

    def test_corrupt_manifest_makes_doctor_exit_nonzero(self):
        _install(self)
        self._write_manifest("{bad")
        findings = build_doctor_findings(self.destination, _fake_toolcheck_runner([]))
        self.assertEqual(exit_code(findings), 1)
        # The manifest diagnostic is emitted exactly once across the invocation.
        manifest_findings = [f for f in findings if f.id == "doctor.install.manifest"]
        self.assertEqual(len(manifest_findings), 1)


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
