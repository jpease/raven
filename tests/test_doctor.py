import argparse
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from helpers import RavenTestCase, raven
from raven_lib.config import _update_config_platform
from raven_lib.constants import CONFIG_PATH
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


def _install(testcase, platform=None):
    """Perform a real Raven install of the python template into the temp dir."""
    ns = argparse.Namespace(
        destination=str(testcase.destination),
        language="python",
        args=None,
        overrides=[],
        dry_run=False,
        include_readme=False,
        adopt_claude_symlink=False,
        platform=platform,
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

    def test_invalid_platform_value_is_error_not_clean(self):
        # #173: a typo'd `[issue_tracker].platform` value (e.g. "gihtub") must
        # surface as a `build_doctor_findings` ERROR, not report the
        # destination clean -- doctor.install.config already short-circuits
        # the rest of the findings on a malformed config, matching the
        # existing missing-config-file behavior above.
        _install(self, platform="github")
        _update_config_platform(self.destination / CONFIG_PATH, "gihtub")
        findings = build_doctor_findings(self.destination)
        self.assertTrue(any(f.severity == Severity.ERROR for f in findings))
        ids = self._ids(findings)
        self.assertIn("doctor.install.config", ids)
        self.assertEqual(ids["doctor.install.config"].severity, Severity.ERROR)
        self.assertEqual(len(findings), 1)

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

    def _add_orphan_record(self, *, installed_sha256, source_sha256):
        # docs/dropped.md is not shipped anywhere in the python template, so
        # classify_orphans always treats it as an orphan once it is manifest-tracked.
        manifest = raven.load_manifest(self.destination)
        manifest["files"]["docs/dropped.md"] = {
            "kind": "file",
            "installedSha256": installed_sha256,
            "sourceSha256": source_sha256,
        }
        raven.save_manifest(self.destination, manifest)

    def test_doctor_reports_removable_orphan(self) -> None:
        # An orphan whose on-disk content still matches its recorded,
        # non-customized baseline is safe to remove automatically.
        _install(self)
        orphan_file = self.destination / "docs" / "dropped.md"
        orphan_file.parent.mkdir(parents=True, exist_ok=True)
        orphan_file.write_text("dropped content\n", encoding="utf-8")
        sha = raven.file_sha256(orphan_file)
        self._add_orphan_record(installed_sha256=sha, source_sha256=sha)
        findings = {f.id: f for f in drift_findings(self.destination)}
        self.assertIn("doctor.orphan.removable", findings)
        self.assertEqual(findings["doctor.orphan.removable"].severity, Severity.WARN)
        self.assertIn("docs/dropped.md", findings["doctor.orphan.removable"].detail)
        self.assertNotIn("doctor.orphan.modified", findings)

    def test_removable_orphan_suppresses_no_drift_ok(self) -> None:
        # A removable orphan is real drift the user should act on (or let
        # `raven upgrade` clean up); it must not be masked by a "no drift
        # detected" OK finding just because everything else is pristine.
        _install(self)
        orphan_file = self.destination / "docs" / "dropped.md"
        orphan_file.parent.mkdir(parents=True, exist_ok=True)
        orphan_file.write_text("dropped content\n", encoding="utf-8")
        sha = raven.file_sha256(orphan_file)
        self._add_orphan_record(installed_sha256=sha, source_sha256=sha)
        findings = {f.id: f for f in drift_findings(self.destination)}
        self.assertIn("doctor.orphan.removable", findings)
        self.assertNotIn("doctor.drift.modified", findings)

    def test_clean_install_with_no_orphans_still_reports_ok(self) -> None:
        # Regression guard: a genuinely clean install (no orphans at all) must
        # still emit the "no drift detected" OK finding.
        _install(self)
        findings = {f.id: f for f in drift_findings(self.destination)}
        self.assertIn("doctor.drift.modified", findings)
        self.assertEqual(findings["doctor.drift.modified"].severity, Severity.OK)

    def test_doctor_reports_modified_orphan(self) -> None:
        # An orphan whose on-disk content diverges from its recorded baseline
        # must be reported for manual review, never auto-removed.
        _install(self)
        orphan_file = self.destination / "docs" / "dropped.md"
        orphan_file.parent.mkdir(parents=True, exist_ok=True)
        orphan_file.write_text("dropped content\n", encoding="utf-8")
        self._add_orphan_record(installed_sha256="a" * 64, source_sha256="a" * 64)
        findings = {f.id: f for f in drift_findings(self.destination)}
        self.assertIn("doctor.orphan.modified", findings)
        self.assertEqual(findings["doctor.orphan.modified"].severity, Severity.WARN)
        self.assertIn("docs/dropped.md", findings["doctor.orphan.modified"].detail)
        self.assertNotIn("doctor.orphan.removable", findings)


class DoctorDeactivatedTests(RavenTestCase):
    """#160 -- doctor must report config-gated-but-still-shipped skills distinctly from orphans."""

    def _switch_platform(self, platform: str) -> None:
        from raven_lib.config import _update_config_platform
        from raven_lib.constants import CONFIG_PATH

        _update_config_platform(self.destination / CONFIG_PATH, platform)

    def test_doctor_reports_removable_deactivated_skill(self) -> None:
        _install(self, platform="github")
        self._switch_platform("gitlab")
        findings = {f.id: f for f in drift_findings(self.destination)}
        self.assertIn("doctor.deactivated.removable", findings)
        self.assertEqual(findings["doctor.deactivated.removable"].severity, Severity.WARN)
        self.assertIn(
            ".agents/skills/raven-github-issues/SKILL.md",
            findings["doctor.deactivated.removable"].detail,
        )
        self.assertNotIn("doctor.deactivated.preserved", findings)
        # Never labeled as an orphan: the template still ships this file.
        self.assertNotIn("doctor.orphan.removable", findings)
        self.assertNotIn("doctor.orphan.modified", findings)

    def test_removable_deactivated_skill_suppresses_no_drift_ok(self) -> None:
        _install(self, platform="github")
        self._switch_platform("gitlab")
        findings = {f.id: f for f in drift_findings(self.destination)}
        self.assertIn("doctor.deactivated.removable", findings)
        ok_modified = findings.get("doctor.drift.modified")
        self.assertFalse(ok_modified and ok_modified.severity == Severity.OK)

    def test_doctor_reports_preserved_deactivated_skill(self) -> None:
        _install(self, platform="github")
        skill_path = self.destination / ".agents" / "skills" / "raven-github-issues" / "SKILL.md"
        skill_path.write_text("edited locally\n", encoding="utf-8")
        self._switch_platform("gitlab")
        findings = {f.id: f for f in drift_findings(self.destination)}
        self.assertIn("doctor.deactivated.preserved", findings)
        self.assertEqual(findings["doctor.deactivated.preserved"].severity, Severity.WARN)
        self.assertIn(
            ".agents/skills/raven-github-issues/SKILL.md",
            findings["doctor.deactivated.preserved"].detail,
        )
        self.assertNotIn("doctor.deactivated.removable", findings)

    def test_matching_platform_reports_no_deactivation(self) -> None:
        _install(self, platform="github")
        findings = {f.id: f for f in drift_findings(self.destination)}
        self.assertNotIn("doctor.deactivated.removable", findings)
        self.assertNotIn("doctor.deactivated.preserved", findings)
        self.assertEqual(findings["doctor.drift.modified"].severity, Severity.OK)

    def test_doctor_reports_stale_baseline_deactivated_skill_distinctly(self) -> None:
        # #179: a recorded baseline from an older template version, but
        # pristine on-disk content matching the *current* template, must be
        # its own WARN finding -- distinct id from doctor.deactivated.
        # preserved, and distinct wording naming `raven accept` as the fix
        # rather than accusing the user of modifying the file.
        _install(self, platform="github")
        skill_path = self.destination / ".agents" / "skills" / "raven-github-issues" / "SKILL.md"
        self.assertTrue(skill_path.exists())
        manifest_path = self.destination / ".raven" / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        rel = ".agents/skills/raven-github-issues/SKILL.md"
        stale_hash = "a" * 64
        manifest["files"][rel] = {
            "kind": "file",
            "installedSha256": stale_hash,
            "sourceSha256": stale_hash,
        }
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        self._switch_platform("gitlab")

        findings = {f.id: f for f in drift_findings(self.destination)}
        self.assertIn("doctor.deactivated.stale", findings)
        self.assertEqual(findings["doctor.deactivated.stale"].severity, Severity.WARN)
        self.assertIn(rel, findings["doctor.deactivated.stale"].detail)
        assert findings["doctor.deactivated.stale"].fix is not None
        self.assertIn("raven accept", findings["doctor.deactivated.stale"].fix)
        self.assertNotIn("doctor.deactivated.preserved", findings)
        self.assertNotIn("doctor.deactivated.removable", findings)
        self.assertNotIn("doctor.deactivated.customized", findings)

    def test_doctor_reports_customized_deactivated_skill_as_info_not_warn(self) -> None:
        # #179: an accepted customization (installed != source) on a
        # deactivated skill is a deliberate, acknowledged state -- INFO, not
        # WARN, mirroring the doctor.drift.local precedent for accepted
        # local customizations elsewhere in this module.
        _install(self, platform="github")
        skill_path = self.destination / ".agents" / "skills" / "raven-github-issues" / "SKILL.md"
        rel = ".agents/skills/raven-github-issues/SKILL.md"
        manifest_path = self.destination / ".raven" / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        sha = manifest["files"][rel]["installedSha256"]
        manifest["files"][rel] = {
            "kind": "file",
            "installedSha256": sha,
            "sourceSha256": "b" * 64,
        }
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        self._switch_platform("gitlab")

        findings = {f.id: f for f in drift_findings(self.destination)}
        self.assertIn("doctor.deactivated.customized", findings)
        self.assertEqual(findings["doctor.deactivated.customized"].severity, Severity.INFO)
        self.assertIn(rel, findings["doctor.deactivated.customized"].detail)
        self.assertNotIn("doctor.deactivated.preserved", findings)
        self.assertNotIn("doctor.deactivated.removable", findings)
        self.assertNotIn("doctor.deactivated.stale", findings)
        self.assertTrue(skill_path.exists())

    def test_customized_deactivated_skill_does_not_block_matching_ok(self) -> None:
        # An INFO-only customized finding must not itself count as an ERROR,
        # matching the existing doctor.drift.local OK-suppression contract:
        # OK is suppressed by anything in `deactivated.preserved` (the
        # customized path is still part of that aggregate), but no ERROR
        # severity should ever result from an accepted customization alone.
        _install(self, platform="github")
        rel = ".agents/skills/raven-github-issues/SKILL.md"
        manifest_path = self.destination / ".raven" / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        sha = manifest["files"][rel]["installedSha256"]
        manifest["files"][rel] = {
            "kind": "file",
            "installedSha256": sha,
            "sourceSha256": "b" * 64,
        }
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        self._switch_platform("gitlab")

        findings = drift_findings(self.destination)
        self.assertFalse(any(f.severity == Severity.ERROR for f in findings))


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

    def test_gofmt_present_is_ok_despite_unsupported_version_flag(self):
        # gofmt has no --version flag: it exits 2 with "flag provided but not
        # defined: -version" even when the binary is installed and working.
        from raven_lib.doctor import toolchain_findings
        from raven_lib.findings import Severity

        (self.destination / ".raven").mkdir()
        (self.destination / ".raven" / "config.toml").write_text(
            'schema = 1\ntemplate = "go"\n', encoding="utf-8"
        )
        payload = json.dumps({"os": "darwin", "results": []})

        def runner(command, cwd):
            if any("raven-tool-check.py" in part for part in command):
                return RunResult(
                    ok=True, code=0, stdout=payload, stderr="", found=True, timed_out=False
                )
            if command[0] == "gofmt":
                return RunResult(
                    ok=False,
                    code=2,
                    stdout="",
                    stderr="flag provided but not defined: -version",
                    found=True,
                    timed_out=False,
                )
            return RunResult(
                ok=True, code=0, stdout="1.0\n", stderr="", found=True, timed_out=False
            )

        findings = toolchain_findings(self.destination, runner)
        match = next(f for f in findings if f.id == "doctor.gate-tool.gofmt")
        self.assertEqual(match.severity, Severity.OK)

    def test_non_object_json_returns_degraded_warning(self):
        """Test that invalid top-level JSON (non-object) returns degraded path with warning."""
        from raven_lib.doctor import toolchain_findings

        self._config()

        # Test cases: (raw_json_string, description)
        test_cases = [
            ("[]", "list"),
            ('"a string"', "string"),
            ("123", "number"),
            ("true", "boolean"),
            ("null", "null"),
            ('{"results": "notalist"}', "object with non-list results"),
        ]

        for raw_json, description in test_cases:
            with self.subTest(json_type=description):

                def runner(command, cwd, _raw_json=raw_json):
                    if any("raven-tool-check.py" in part for part in command):
                        return RunResult(
                            ok=True,
                            code=0,
                            stdout=_raw_json,
                            stderr="",
                            found=True,
                            timed_out=False,
                        )
                    return RunResult(
                        ok=True,
                        code=0,
                        stdout="1.0\n",
                        stderr="",
                        found=True,
                        timed_out=False,
                    )

                # Should not raise AttributeError
                findings = toolchain_findings(self.destination, runner)

                # Should contain the degraded warning
                warning_findings = [f for f in findings if f.id == "doctor.tool.script"]
                self.assertEqual(len(warning_findings), 1, f"Failed for {description}")
                self.assertEqual(
                    warning_findings[0].severity,
                    Severity.WARN,
                    f"Failed for {description}",
                )
                self.assertEqual(
                    warning_findings[0].title,
                    "Tool-check script unavailable",
                    f"Failed for {description}",
                )


class DoctorHookManagerTests(RavenTestCase):
    def _git_init(self):
        subprocess.run(["git", "init", str(self.destination)], capture_output=True, check=True)

    def test_hook_manager_finding_for_husky(self):
        from raven_lib.doctor import hook_manager_findings

        self._git_init()
        (self.destination / ".husky" / "_").mkdir(parents=True)
        subprocess.run(
            ["git", "-C", str(self.destination), "config", "core.hooksPath", ".husky/_"],
            capture_output=True,
            check=True,
        )
        findings = hook_manager_findings(self.destination)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].id, "doctor.hooks.manager")
        self.assertEqual(findings[0].severity, Severity.INFO)
        self.assertIn("husky", findings[0].title)

    def test_hook_manager_finding_absent_for_normal_repo(self):
        from raven_lib.doctor import hook_manager_findings

        self._git_init()
        self.assertEqual(hook_manager_findings(self.destination), [])

    def test_hook_manager_finding_for_external_hooks_path(self):
        from raven_lib.doctor import hook_manager_findings

        self._git_init()
        global_hooks = self.destination.parent / "global-githooks-doctor"
        global_hooks.mkdir()
        self.addCleanup(shutil.rmtree, global_hooks, True)
        subprocess.run(
            ["git", "-C", str(self.destination), "config", "core.hooksPath", str(global_hooks)],
            capture_output=True,
            check=True,
        )
        findings = hook_manager_findings(self.destination)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].id, "doctor.hooks.manager")
        self.assertEqual(findings[0].severity, Severity.INFO)
        self.assertIn("external-hooks-path", findings[0].title)


# ---------------------------------------------------------------------------
# #177 -- doctor reported "0 errors" against a .codex tree whose hooks and
# scripts were placeholder text, because nothing checked symlink-ness. Two
# checks: the Raven checkout doctor is running from, and the destination.
# ---------------------------------------------------------------------------
class DoctorFlattenedSymlinkTests(RavenTestCase):
    def _ids(self, findings):
        return {f.id: f for f in findings}

    def test_healthy_checkout_and_install_report_no_symlink_errors(self):
        _install(self)
        ids = self._ids(build_doctor_findings(self.destination, _fake_toolcheck_runner([])))
        self.assertNotIn("doctor.checkout.symlinks", ids)
        self.assertNotIn("doctor.install.flattened", ids)
        self.assertEqual(exit_code(list(ids.values())), 0)

    def test_flattened_symlink_in_the_checkout_is_an_error(self):
        _install(self)
        before = self._ids(integrity_findings(self.destination))
        self.assertNotIn("doctor.checkout.symlinks", before)

        # A stand-in Raven checkout whose common/CLAUDE.md is a regular file
        # holding its target text -- exactly what git writes when the checkout
        # cannot create symlinks.
        fake_root = self.destination.parent / "fake-raven-checkout"
        (fake_root / "common").mkdir(parents=True)
        (fake_root / "common" / "CLAUDE.md").write_text("AGENTS.md\n", encoding="utf-8")
        self.addCleanup(shutil.rmtree, fake_root, True)

        with mock.patch("raven_lib.doctor.REPO_ROOT", fake_root):
            findings = integrity_findings(self.destination)

        ids = self._ids(findings)
        self.assertIn("doctor.checkout.symlinks", ids)
        finding = ids["doctor.checkout.symlinks"]
        self.assertEqual(finding.severity, Severity.ERROR)
        self.assertIn("CLAUDE.md", finding.detail)
        self.assertIn("core.symlinks", finding.fix)

    def test_flattened_installed_symlink_is_an_error(self):
        _install(self)
        before = self._ids(build_doctor_findings(self.destination, _fake_toolcheck_runner([])))
        self.assertNotIn("doctor.install.flattened", before)
        self.assertEqual(exit_code(list(before.values())), 0)

        manifest = json.loads(
            (self.destination / ".raven" / "manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(manifest["files"]["CLAUDE.md"]["kind"], "symlink")

        # Corrupt the destination the way a symlink-unaware copy would: replace
        # the installed symlink with a regular file holding its target text.
        # The manifest still records it as a symlink.
        claude = self.destination / "CLAUDE.md"
        target = os.readlink(claude)
        claude.unlink()
        claude.write_text(target + "\n", encoding="utf-8")

        findings = build_doctor_findings(self.destination, _fake_toolcheck_runner([]))
        ids = self._ids(findings)
        self.assertIn("doctor.install.flattened", ids)
        self.assertEqual(ids["doctor.install.flattened"].severity, Severity.ERROR)
        self.assertIn("CLAUDE.md", ids["doctor.install.flattened"].detail)
        self.assertEqual(exit_code(findings), 1)

    def test_flattened_installed_directory_symlink_is_an_error(self):
        _install(self)
        skills = self.destination / ".claude" / "skills"
        self.assertTrue(skills.is_symlink())
        target = os.readlink(skills)
        skills.unlink()
        skills.write_text(target + "\n", encoding="utf-8")

        ids = self._ids(build_doctor_findings(self.destination, _fake_toolcheck_runner([])))
        self.assertIn("doctor.install.flattened", ids)
        self.assertIn(".claude/skills", ids["doctor.install.flattened"].detail)

    def test_deleted_symlink_is_missing_drift_not_a_flattening_error(self):
        # An absent path is already reported as missing drift; reporting it as
        # corruption too would double-count and offer the wrong fix.
        _install(self)
        (self.destination / "CLAUDE.md").unlink()

        ids = self._ids(build_doctor_findings(self.destination, _fake_toolcheck_runner([])))
        self.assertNotIn("doctor.install.flattened", ids)
        self.assertIn("doctor.drift.missing", ids)


if __name__ == "__main__":
    unittest.main()
