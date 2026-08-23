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
from raven_lib.constants import CONFIG_PATH, LANE_CLAIMS, claude_config_dir
from raven_lib.doctor import (
    FOUND,
    NOT_FOUND,
    UNDETERMINABLE,
    build_doctor_findings,
    detect_plugin,
    drift_findings,
    hook_integrity_findings,
    integrity_findings,
    sources_findings,
)
from raven_lib.findings import Severity, exit_code
from raven_lib.models import Classification
from raven_lib.runner import RunResult


def _classification(needs_merge, local_only=(), will_copy=(), needs_adoption=()):
    return Classification(
        will_copy=list(will_copy),
        will_upgrade=[],
        identical=[],
        needs_merge=list(needs_merge),
        unknown_existing=[],
        excluded=[],
        local_only=list(local_only),
        needs_adoption=list(needs_adoption),
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

    def test_dotfiles_template_is_not_unsupported_error(self):
        # Issue #187 -- dotfiles is a real template directory (per
        # list_language_templates()) that just ships no gate tooling. It must
        # not be reported as an unsupported/unknown template name.
        (self.destination / ".raven").mkdir()
        (self.destination / ".raven" / "config.toml").write_text(
            'schema = 1\ntemplate = "dotfiles"\n', encoding="utf-8"
        )
        ids = self._ids(integrity_findings(self.destination))
        template_finding = ids.get("doctor.install.template")
        self.assertTrue(template_finding is None or template_finding.severity != Severity.ERROR)

    def test_generic_template_is_not_unsupported_error(self):
        # #224 -- same class as #187's dotfiles case. `generic` ships no gate
        # tooling by design, so the gate table cannot be the test for whether
        # the template name is real.
        (self.destination / ".raven").mkdir()
        (self.destination / ".raven" / "config.toml").write_text(
            'schema = 1\ntemplate = "generic"\n', encoding="utf-8"
        )
        ids = self._ids(integrity_findings(self.destination))
        template_finding = ids.get("doctor.install.template")
        self.assertTrue(template_finding is None or template_finding.severity != Severity.ERROR)

    def test_template_switch_mismatch_is_warn(self):
        # Issue #188 -- config.template differs from the last-applied manifest
        # template, so `raven upgrade` will refuse until
        # --confirm-template-switch. doctor must surface this pending state
        # instead of reporting clean.
        (self.destination / ".raven").mkdir()
        (self.destination / ".raven" / "config.toml").write_text(
            'schema = 1\ntemplate = "go"\n', encoding="utf-8"
        )
        (self.destination / ".raven" / "manifest.json").write_text(
            json.dumps({"schema": 1, "template": "python", "files": {}}), encoding="utf-8"
        )
        ids = self._ids(integrity_findings(self.destination))
        self.assertIn("doctor.install.template_switch_pending", ids)
        finding = ids["doctor.install.template_switch_pending"]
        self.assertEqual(finding.severity, Severity.WARN)
        self.assertIn("go", finding.detail)
        self.assertIn("python", finding.detail)

    def test_template_switch_no_mismatch_produces_no_finding(self):
        (self.destination / ".raven").mkdir()
        (self.destination / ".raven" / "config.toml").write_text(
            'schema = 1\ntemplate = "python"\n', encoding="utf-8"
        )
        (self.destination / ".raven" / "manifest.json").write_text(
            json.dumps({"schema": 1, "template": "python", "files": {}}), encoding="utf-8"
        )
        ids = self._ids(integrity_findings(self.destination))
        self.assertNotIn("doctor.install.template_switch_pending", ids)

    def test_template_switch_fresh_install_no_manifest_produces_no_finding(self):
        # No manifest.json at all -- the normal pre-first-upgrade state, not a
        # mismatch.
        (self.destination / ".raven").mkdir()
        (self.destination / ".raven" / "config.toml").write_text(
            'schema = 1\ntemplate = "python"\n', encoding="utf-8"
        )
        ids = self._ids(integrity_findings(self.destination))
        self.assertNotIn("doctor.install.template_switch_pending", ids)

    def test_template_switch_manifest_without_template_key_produces_no_finding(self):
        (self.destination / ".raven").mkdir()
        (self.destination / ".raven" / "config.toml").write_text(
            'schema = 1\ntemplate = "python"\n', encoding="utf-8"
        )
        (self.destination / ".raven" / "manifest.json").write_text(
            json.dumps({"schema": 1, "files": {}}), encoding="utf-8"
        )
        ids = self._ids(integrity_findings(self.destination))
        self.assertNotIn("doctor.install.template_switch_pending", ids)


class DoctorDriftTests(RavenTestCase):
    def _config(self):
        (self.destination / ".raven").mkdir()
        (self.destination / ".raven" / "config.toml").write_text(
            'schema = 1\ntemplate = "python"\n', encoding="utf-8"
        )

    def _drift(self, *, needs_merge, pending, local_only=(), will_copy=(), needs_adoption=()):
        self._config()
        with (
            mock.patch(
                "raven_lib.doctor.classify",
                return_value=_classification(
                    needs_merge,
                    local_only=local_only,
                    will_copy=will_copy,
                    needs_adoption=needs_adoption,
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

    def test_needs_adoption_is_warn_not_modified_and_suppresses_ok(self):
        # #200: a file needing adoption consent (currently only ever
        # .claude/settings.json) is real, actionable drift -- it must get its
        # own WARN finding pointing at --adopt-settings-json, and must not be
        # silently absorbed into (or masked by) the generic "modified"/"no
        # drift" findings, which no longer see it since it left
        # unknown_existing for its own classification bucket.
        findings = self._drift(needs_merge=[], pending=[], needs_adoption=[".claude/settings.json"])
        self.assertIn("doctor.drift.needs_adoption", findings)
        finding = findings["doctor.drift.needs_adoption"]
        self.assertEqual(finding.severity, Severity.WARN)
        self.assertIn(".claude/settings.json", finding.detail)
        assert finding.fix is not None
        self.assertIn("--adopt-settings-json", finding.fix)
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

    def test_dotfiles_template_drift_is_not_error(self):
        # Issue #187 -- same conflation bug in drift_findings: dotfiles has no
        # gate spec but is a real template, so drift must still be evaluated
        # rather than short-circuiting with an "unsupported template" ERROR.
        (self.destination / ".raven").mkdir()
        (self.destination / ".raven" / "config.toml").write_text(
            'schema = 1\ntemplate = "dotfiles"\n', encoding="utf-8"
        )
        with (
            mock.patch(
                "raven_lib.doctor.classify",
                return_value=_classification([], local_only=[], will_copy=[]),
            ),
            mock.patch("raven_lib.doctor.pending_merge_paths", return_value=[]),
        ):
            findings = {f.id: f for f in drift_findings(self.destination)}
        self.assertFalse(any(f.severity == Severity.ERROR for f in findings.values()))

    def test_generic_template_drift_is_not_error(self):
        # #224 -- drift must still be evaluated for a gate-less template.
        (self.destination / ".raven").mkdir()
        (self.destination / ".raven" / "config.toml").write_text(
            'schema = 1\ntemplate = "generic"\n', encoding="utf-8"
        )
        with (
            mock.patch(
                "raven_lib.doctor.classify",
                return_value=_classification([], local_only=[], will_copy=[]),
            ),
            mock.patch("raven_lib.doctor.pending_merge_paths", return_value=[]),
        ):
            findings = {f.id: f for f in drift_findings(self.destination)}
        self.assertFalse(any(f.severity == Severity.ERROR for f in findings.values()))

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


class DoctorProberPathTests(RavenTestCase):
    """`components.claude.scripts` and `components.codex.scripts` toggle
    independently, so the prober can live under either adapter directory.
    Doctor used to look only under `.claude/`, which turned a Codex-only
    install's entire toolchain section into one warning telling the reader to
    reinstall a script that was already there.
    """

    def _config(self):
        (self.destination / ".raven").mkdir()
        (self.destination / ".raven" / "config.toml").write_text(
            'schema = 1\ntemplate = "python"\n', encoding="utf-8"
        )

    def _install_prober(self, adapter):
        scripts = self.destination / adapter / "scripts"
        scripts.mkdir(parents=True)
        (scripts / "raven-tool-check.py").write_text("", encoding="utf-8")

    def _recording_runner(self):
        seen = []
        payload = json.dumps({"os": "darwin", "results": []})

        def runner(command, cwd):
            seen.append(command)
            return RunResult(
                ok=True, code=0, stdout=payload, stderr="", found=True, timed_out=False
            )

        return runner, seen

    def _prober_argument(self, seen):
        for command in seen:
            for part in command:
                if "raven-tool-check.py" in part:
                    return part
        raise AssertionError(f"no tool-check invocation in {seen!r}")

    def test_codex_only_install_runs_the_codex_prober(self):
        from raven_lib.doctor import toolchain_findings

        self._config()
        self._install_prober(".codex")
        runner, seen = self._recording_runner()

        findings = toolchain_findings(self.destination, runner)

        self.assertIn(".codex", self._prober_argument(seen))
        self.assertEqual([f for f in findings if f.id == "doctor.tool.script"], [])

    def test_claude_wins_when_both_adapters_are_installed(self):
        from raven_lib.doctor import toolchain_findings

        self._config()
        self._install_prober(".claude")
        self._install_prober(".codex")
        runner, seen = self._recording_runner()

        toolchain_findings(self.destination, runner)

        self.assertIn(".claude", self._prober_argument(seen))

    def test_real_codex_only_install_leaves_doctor_a_prober_to_run(self):
        """End-to-end: the config toggle really does produce the layout above.

        The three tests around this one build the adapter tree by hand, so they
        prove the resolver without proving the layout is reachable. This one
        runs a real install with `[components.claude] scripts = false` and
        checks both halves -- that `.claude/scripts/` is absent while the
        prober is present under `.codex/`, and that doctor then runs it.
        """
        from raven_lib.doctor import toolchain_findings

        (self.destination / ".raven").mkdir()
        (self.destination / ".raven" / "config.toml").write_text(
            'schema = 1\ntemplate = "python"\n\n[components.claude]\nscripts = false\n',
            encoding="utf-8",
        )
        _install(self)

        self.assertFalse((self.destination / ".claude" / "scripts").exists())
        self.assertTrue(
            (self.destination / ".codex" / "scripts" / "raven-tool-check.py").exists(),
            "codex scripts stay installed when only the claude toggle is off",
        )

        runner, seen = self._recording_runner()
        findings = toolchain_findings(self.destination, runner)

        self.assertIn(".codex", self._prober_argument(seen))
        self.assertEqual([f for f in findings if f.id == "doctor.tool.script"], [])

    def test_warning_names_the_path_that_was_tried(self):
        from raven_lib.doctor import toolchain_findings

        self._config()
        self._install_prober(".codex")

        def runner(command, cwd):
            return RunResult(ok=False, code=1, stdout="", stderr="", found=True, timed_out=True)

        findings = toolchain_findings(self.destination, runner)

        warning = next(f for f in findings if f.id == "doctor.tool.script")
        # Naming `.claude/` here is what made the old warning unactionable on a
        # Codex install: the reader checks that path, finds nothing, and the
        # suggested `raven install` restores a file that is already present.
        self.assertIn(".codex/scripts/raven-tool-check.py", warning.detail)
        self.assertNotIn(".claude", warning.detail)


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


class DoctorHookIntegrityTests(RavenTestCase):
    """#222 -- doctor stayed silent when Raven's own hooks were missing or dangling."""

    def _git_init(self):
        subprocess.run(["git", "init", str(self.destination)], capture_output=True, check=True)

    def _write_hook(self, name: str, content: str = "#!/bin/sh\n", executable: bool = True) -> Path:
        src_dir = self.destination / ".raven" / "git-hooks"
        src_dir.mkdir(parents=True, exist_ok=True)
        hook = src_dir / name
        hook.write_text(content, encoding="utf-8")
        hook.chmod(0o755 if executable else 0o644)
        return hook

    def test_empty_when_no_git_hooks_src_dir(self):
        self._git_init()
        self.assertEqual(hook_integrity_findings(self.destination), [])

    def test_empty_when_hook_manager_owns_hooks_dir(self):
        self._git_init()
        (self.destination / ".husky" / "_").mkdir(parents=True)
        subprocess.run(
            ["git", "-C", str(self.destination), "config", "core.hooksPath", ".husky/_"],
            capture_output=True,
            check=True,
        )
        self._write_hook("pre-commit")
        self.assertEqual(hook_integrity_findings(self.destination), [])

    def test_ok_when_hook_correctly_symlinked(self):
        self._git_init()
        hook_src = self._write_hook("pre-commit")
        hooks_dir = self.destination / ".git" / "hooks"
        hooks_dir.mkdir(parents=True, exist_ok=True)
        (hooks_dir / "pre-commit").symlink_to(os.path.relpath(hook_src, hooks_dir))

        findings = hook_integrity_findings(self.destination)

        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].id, "doctor.hooks.pre-commit")
        self.assertEqual(findings[0].severity, Severity.OK)

    def test_warn_when_hook_missing_from_hooks_dir(self):
        self._git_init()
        self._write_hook("pre-commit")

        findings = hook_integrity_findings(self.destination)

        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].severity, Severity.WARN)
        self.assertIn("not installed", findings[0].title)
        self.assertEqual(findings[0].fix, "raven install")

    def test_warn_when_hook_link_dangling(self):
        self._git_init()
        self._write_hook("pre-commit")
        hooks_dir = self.destination / ".git" / "hooks"
        hooks_dir.mkdir(parents=True, exist_ok=True)
        (hooks_dir / "pre-commit").symlink_to("../../.raven/git-hooks/does-not-exist")

        findings = hook_integrity_findings(self.destination)

        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].severity, Severity.WARN)
        self.assertIn("dangling", findings[0].title)

    def test_warn_when_hook_resolves_elsewhere(self):
        self._git_init()
        self._write_hook("pre-commit")
        hooks_dir = self.destination / ".git" / "hooks"
        hooks_dir.mkdir(parents=True, exist_ok=True)
        other = self.destination / "elsewhere.sh"
        other.write_text("#!/bin/sh\n", encoding="utf-8")
        other.chmod(0o755)
        (hooks_dir / "pre-commit").symlink_to(other)

        findings = hook_integrity_findings(self.destination)

        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].severity, Severity.WARN)
        self.assertIn("resolves outside", findings[0].title)

    def test_warn_when_hook_replaced_by_regular_file(self):
        self._git_init()
        self._write_hook("pre-commit")
        hooks_dir = self.destination / ".git" / "hooks"
        hooks_dir.mkdir(parents=True, exist_ok=True)
        (hooks_dir / "pre-commit").write_text("# not raven's\n", encoding="utf-8")

        findings = hook_integrity_findings(self.destination)

        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].severity, Severity.WARN)
        self.assertIn("is not Raven's hook", findings[0].title)

    def test_warn_when_hook_target_not_executable(self):
        self._git_init()
        hook_src = self._write_hook("pre-commit", executable=False)
        hooks_dir = self.destination / ".git" / "hooks"
        hooks_dir.mkdir(parents=True, exist_ok=True)
        (hooks_dir / "pre-commit").symlink_to(os.path.relpath(hook_src, hooks_dir))

        findings = hook_integrity_findings(self.destination)

        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].severity, Severity.WARN)
        self.assertIn("not executable", findings[0].title)

    def test_included_in_build_doctor_findings(self):
        self._git_init()
        self._write_hook("pre-commit")
        config_dir = self.destination / ".raven"
        config_dir.mkdir(parents=True, exist_ok=True)

        findings = build_doctor_findings(self.destination)

        self.assertTrue(any(f.id == "doctor.hooks.pre-commit" for f in findings))


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


class DoctorPluginRegistryTests(RavenTestCase):
    """`detect_plugin` reads Claude Code's installed-plugin registry.

    Every case writes a real registry file into the temp directory and passes
    its path. Nothing here patches ``Path.home`` or the environment: the path
    is a parameter precisely so it does not have to be.
    """

    def _registry(self, text):
        path = self.destination / "installed_plugins.json"
        path.write_text(text, encoding="utf-8")
        return path

    def _registry_json(self, payload):
        return self._registry(json.dumps(payload))

    def _one_record(self, install_path="/plugins/superpowers/6.3.0", version="6.3.0", scope="user"):
        return {
            "scope": scope,
            "installPath": install_path,
            "version": version,
        }

    def test_registry_absent_is_undeterminable_not_missing(self):
        # The distinction the whole check rests on: a machine with no registry
        # tells Raven nothing, and answering "not installed" there would be a
        # confident wrong answer.
        status = detect_plugin(self.destination / "nope.json", "superpowers")
        self.assertEqual(status.state, UNDETERMINABLE)
        self.assertNotEqual(status.state, NOT_FOUND)

    def test_registry_that_is_a_directory_is_undeterminable(self):
        # Portable stand-in for an unreadable file: chmod is a no-op as root
        # and meaningless on Windows, a directory is neither.
        path = self.destination / "installed_plugins.json"
        path.mkdir()
        self.assertEqual(detect_plugin(path, "superpowers").state, UNDETERMINABLE)

    def test_registry_with_invalid_json_is_undeterminable(self):
        path = self._registry("{not json")
        self.assertEqual(detect_plugin(path, "superpowers").state, UNDETERMINABLE)

    def test_registry_with_non_dict_root_is_undeterminable(self):
        path = self._registry_json([1, 2, 3])
        self.assertEqual(detect_plugin(path, "superpowers").state, UNDETERMINABLE)

    def test_registry_with_non_dict_plugins_is_undeterminable(self):
        path = self._registry_json({"version": 1, "plugins": ["superpowers"]})
        self.assertEqual(detect_plugin(path, "superpowers").state, UNDETERMINABLE)

    def test_registry_without_the_plugin_is_not_found(self):
        path = self._registry_json(
            {"version": 1, "plugins": {"other@market": [self._one_record()]}}
        )
        self.assertEqual(detect_plugin(path, "superpowers").state, NOT_FOUND)

    def test_registry_with_one_record_is_found_with_version_and_path(self):
        path = self._registry_json(
            {"version": 1, "plugins": {"superpowers@claude-plugins-official": [self._one_record()]}}
        )
        status = detect_plugin(path, "superpowers")
        self.assertEqual(status.state, FOUND)
        self.assertEqual(status.versions, ("6.3.0",))
        self.assertEqual(status.install_paths, (Path("/plugins/superpowers/6.3.0"),))
        self.assertEqual(status.registry, path)

    def test_registry_with_three_records_reports_all_of_them(self):
        # A plugin installed at several scopes gets no tie-break: every
        # recorded installPath is a place worth looking.
        records = [
            self._one_record("/a", "6.1.0", "user"),
            self._one_record("/b", "6.2.0", "project"),
            self._one_record("/c", "6.3.0", "local"),
        ]
        path = self._registry_json({"version": 1, "plugins": {"superpowers@market": records}})
        status = detect_plugin(path, "superpowers")
        self.assertEqual(status.state, FOUND)
        self.assertEqual(status.versions, ("6.1.0", "6.2.0", "6.3.0"))
        self.assertEqual(status.install_paths, (Path("/a"), Path("/b"), Path("/c")))

    def test_registry_version_unknown_is_found_and_carried_verbatim(self):
        path = self._registry_json(
            {"version": 1, "plugins": {"superpowers@market": [self._one_record(version="unknown")]}}
        )
        status = detect_plugin(path, "superpowers")
        self.assertEqual(status.state, FOUND)
        self.assertEqual(status.versions, ("unknown",))

    def test_registry_key_without_a_marketplace_suffix_still_matches(self):
        path = self._registry_json({"version": 1, "plugins": {"superpowers": [self._one_record()]}})
        self.assertEqual(detect_plugin(path, "superpowers").state, FOUND)

    def test_registry_key_prefix_must_match_whole_segment(self):
        path = self._registry_json(
            {"version": 1, "plugins": {"superpowers-x@m": [self._one_record()]}}
        )
        self.assertEqual(detect_plugin(path, "superpowers").state, NOT_FOUND)


class ClaudeConfigDirTests(unittest.TestCase):
    """`claude_config_dir` is the one place `raven_lib` reads CLAUDE_CONFIG_DIR."""

    def test_env_override_is_used_when_set(self):
        with mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": "/tmp/claude-elsewhere"}):
            self.assertEqual(claude_config_dir(), Path("/tmp/claude-elsewhere"))

    def test_empty_env_value_falls_back_to_the_home_default(self):
        # An empty value in a shell profile means "unset", not "the filesystem
        # root". Asserted by shape, so no test has to patch ``Path.home``.
        with mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": ""}):
            self.assertEqual(claude_config_dir().name, ".claude")

    def test_doctor_module_reads_no_environment_of_its_own(self):
        source = (Path(__file__).resolve().parents[1] / "scripts/raven_lib/doctor.py").read_text()
        self.assertNotIn("os.environ", source)
        self.assertNotIn("expanduser", source)
        self.assertNotIn("Path.home", source)


class DoctorSourcesTests(RavenTestCase):
    """The `Sources` section: one status finding per declared source.

    Fixtures are hand-built rather than installed: `sources_findings` reads a
    `.claude/` directory, a config object, and a registry path, so a real
    install would add cost without adding coverage.
    """

    def setUp(self):
        super().setUp()
        self.dest = self.destination / "dest"
        (self.dest / ".claude").mkdir(parents=True)

    def _config(self, required=False, name="superpowers"):
        return raven.build_config(
            {f"sources.{name}": {"kind": "claude-plugin", "required": required}}, exists=True
        )

    def _registry_with(self, *, plugin="superpowers", install_path="/plugins/sp/6.3.0"):
        path = self.destination / "installed_plugins.json"
        path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "plugins": {
                        f"{plugin}@claude-plugins-official": [
                            {"scope": "user", "installPath": install_path, "version": "6.3.0"}
                        ]
                    },
                }
            ),
            encoding="utf-8",
        )
        return path

    def _missing_registry(self):
        return self.destination / "absent.json"

    def _empty_registry(self):
        path = self.destination / "empty.json"
        path.write_text(json.dumps({"version": 1, "plugins": {}}), encoding="utf-8")
        return path

    def test_sources_installed_source_is_ok(self):
        findings = sources_findings(self.dest, self._config(), registry=self._registry_with())
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].id, "doctor.sources.superpowers")
        self.assertEqual(findings[0].severity, Severity.OK)
        self.assertEqual(findings[0].category, "Sources")
        self.assertIn("6.3.0", findings[0].title)

    def test_sources_missing_source_is_warn_when_not_required(self):
        findings = sources_findings(self.dest, self._config(), registry=self._empty_registry())
        self.assertEqual([f.severity for f in findings], [Severity.WARN])
        self.assertEqual(exit_code(findings), 0)

    def test_sources_missing_required_source_is_error(self):
        findings = sources_findings(
            self.dest, self._config(required=True), registry=self._empty_registry()
        )
        self.assertEqual([f.severity for f in findings], [Severity.ERROR])
        self.assertEqual(exit_code(findings), 1)

    def test_sources_undeterminable_stays_warn_even_when_required(self):
        # "Raven cannot tell" is not "the dependency is missing". A machine
        # whose registry Raven could not read must not fail a build over it.
        findings = sources_findings(
            self.dest, self._config(required=True), registry=self._missing_registry()
        )
        self.assertEqual([f.severity for f in findings], [Severity.WARN])
        self.assertIn("undeterminable", findings[0].title)
        self.assertIn(str(self._missing_registry()), findings[0].detail)

    def test_sources_codex_only_destination_gets_no_section(self):
        codex_only = self.destination / "codex-only"
        (codex_only / ".codex").mkdir(parents=True)
        self.assertEqual(
            sources_findings(codex_only, self._config(), registry=self._registry_with()), []
        )

    def test_sources_undeclared_config_gets_no_section(self):
        empty = raven.build_config({}, exists=True)
        self.assertEqual(sources_findings(self.dest, empty, registry=self._registry_with()), [])

    def test_sources_two_declared_sources_get_one_status_finding_each(self):
        config = raven.build_config(
            {
                "sources.superpowers": {"kind": "claude-plugin"},
                "sources.other": {"kind": "claude-plugin"},
            },
            exists=True,
        )
        findings = sources_findings(self.dest, config, registry=self._registry_with())
        self.assertEqual(
            [f.id for f in findings],
            ["doctor.sources.superpowers", "doctor.sources.other"],
        )

    def test_sources_wording_never_claims_the_plugin_is_active(self):
        # An installed plugin can still be blocklisted or disabled per project,
        # neither of which Raven reads. "session" is the specific word to keep
        # out of these strings.
        registries = [self._registry_with(), self._empty_registry(), self._missing_registry()]
        for registry in registries:
            with self.subTest(registry=registry.name):
                for finding in sources_findings(self.dest, self._config(), registry=registry):
                    text = f"{finding.title} {finding.detail} {finding.fix or ''}".lower()
                    self.assertNotIn("active", text)
                    self.assertNotIn("session", text)
                    self.assertNotIn("available", text)

    def test_sources_section_appears_in_a_real_doctor_run(self):
        _install(self)
        config_path = self.destination / CONFIG_PATH
        config_path.write_text(
            config_path.read_text(encoding="utf-8")
            + '\n[sources.superpowers]\nkind = "claude-plugin"\n',
            encoding="utf-8",
        )
        findings = build_doctor_findings(self.destination, _fake_toolcheck_runner([]))
        sources = [f for f in findings if f.category == "Sources"]
        # Exactly one *status* finding. Collisions share the category and are
        # machine-dependent (they need the plugin actually installed here), so
        # this asserts the status half only.
        status_ids = [f.id for f in sources if not f.id.startswith("doctor.sources.collision.")]
        self.assertEqual(status_ids, ["doctor.sources.superpowers"])


class DoctorCollisionTests(RavenTestCase):
    """`LANE_CLAIMS` rows become INFO findings when both skills are installed.

    The fixture builds all three halves of a collision -- the Raven skill
    directory, the upstream skill directory under a temp installPath, and the
    config declaration -- so each can be removed independently.
    """

    def setUp(self):
        super().setUp()
        self.dest = self.destination / "dest"
        (self.dest / ".claude").mkdir(parents=True)
        self.install_path = self.destination / "plugins" / "superpowers" / "6.3.0"

    def _raven_skill(self, name="raven-debug-failure"):
        (self.dest / ".agents" / "skills" / name).mkdir(parents=True, exist_ok=True)

    def _upstream_skill(self, name="systematic-debugging"):
        (self.install_path / "skills" / name).mkdir(parents=True, exist_ok=True)

    def _registry(self, *, install_paths=None):
        paths = [self.install_path] if install_paths is None else install_paths
        path = self.destination / "installed_plugins.json"
        path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "plugins": {
                        "superpowers@claude-plugins-official": [
                            {"scope": "user", "installPath": str(p), "version": "6.3.0"}
                            for p in paths
                        ]
                    },
                }
            ),
            encoding="utf-8",
        )
        return path

    def _declared(self):
        return raven.build_config({"sources.superpowers": {"kind": "claude-plugin"}}, exists=True)

    def _collisions(self, config=None, registry=None):
        findings = sources_findings(
            self.dest,
            self._declared() if config is None else config,
            registry=self._registry() if registry is None else registry,
        )
        return [f for f in findings if f.id.startswith("doctor.sources.collision.")]

    def test_collision_reported_when_both_skills_are_installed(self):
        self._raven_skill()
        self._upstream_skill()
        collisions = self._collisions()
        self.assertEqual([f.id for f in collisions], ["doctor.sources.collision.debugging"])
        finding = collisions[0]
        self.assertEqual(finding.severity, Severity.INFO)
        self.assertEqual(finding.category, "Sources")
        self.assertIn("raven-debug-failure", finding.title)
        self.assertIn("systematic-debugging", finding.title)
        self.assertIn("debugging", finding.title)
        self.assertIn("raven", finding.detail)

    def test_collision_absent_without_the_raven_skill_directory(self):
        self._upstream_skill()
        self.assertEqual(self._collisions(), [])

    def test_collision_absent_without_the_upstream_skill_directory(self):
        self._raven_skill()
        self.assertEqual(self._collisions(), [])

    def test_collision_absent_when_the_source_is_undeclared(self):
        # The table is machine-global; the report is not. A repo that never
        # opted in gets nothing, however many plugins the machine has.
        self._raven_skill()
        self._upstream_skill()
        self.assertEqual(self._collisions(config=raven.build_config({}, exists=True)), [])

    def test_collision_absent_when_the_plugin_is_not_installed(self):
        self._raven_skill()
        self._upstream_skill()
        empty = self.destination / "empty.json"
        empty.write_text(json.dumps({"version": 1, "plugins": {}}), encoding="utf-8")
        self.assertEqual(self._collisions(registry=empty), [])

    def test_collision_absent_when_the_registry_is_undeterminable(self):
        self._raven_skill()
        self._upstream_skill()
        self.assertEqual(self._collisions(registry=self.destination / "absent.json"), [])

    def test_collision_found_under_any_recorded_install_path(self):
        # Several install records get no tie-break: every recorded path is a
        # place worth looking, and the upstream tree sits under only one here.
        self._raven_skill()
        self._upstream_skill()
        other = self.destination / "plugins" / "superpowers" / "6.2.0"
        other.mkdir(parents=True)
        registry = self._registry(install_paths=[other, self.install_path])
        self.assertEqual(
            [f.id for f in self._collisions(registry=registry)],
            ["doctor.sources.collision.debugging"],
        )

    def test_collision_reports_every_matching_lane_in_table_order(self):
        for claim in LANE_CLAIMS:
            self._raven_skill(claim.raven_skill)
            self._upstream_skill(claim.upstream_skill)
        self.assertEqual(
            [f.id for f in self._collisions()],
            [f"doctor.sources.collision.{claim.lane}" for claim in LANE_CLAIMS],
        )

    def test_collision_never_fails_a_gate(self):
        for claim in LANE_CLAIMS:
            self._raven_skill(claim.raven_skill)
            self._upstream_skill(claim.upstream_skill)
        findings = sources_findings(self.dest, self._declared(), registry=self._registry())
        self.assertEqual(exit_code(findings), 0)

    def test_collision_suppressed_entirely_on_a_codex_only_destination(self):
        codex_only = self.destination / "codex-only"
        (codex_only / ".codex").mkdir(parents=True)
        (codex_only / ".agents" / "skills" / "raven-debug-failure").mkdir(parents=True)
        self._upstream_skill()
        self.assertEqual(
            sources_findings(codex_only, self._declared(), registry=self._registry()), []
        )

    def test_collision_opens_no_file_inside_either_skill_directory(self):
        # Directory existence is the whole test: an empty directory on both
        # sides still collides, so nothing can be reading SKILL.md.
        self._raven_skill()
        self._upstream_skill()
        self.assertEqual(list((self.dest / ".agents/skills/raven-debug-failure").iterdir()), [])
        self.assertEqual([f.id for f in self._collisions()], ["doctor.sources.collision.debugging"])


class LaneClaimsTableTests(unittest.TestCase):
    def test_prefer_is_one_of_exactly_two_values(self):
        for claim in LANE_CLAIMS:
            self.assertIn(claim.prefer, ("raven", "upstream"), claim.lane)

    def test_lane_slugs_are_unique(self):
        lanes = [claim.lane for claim in LANE_CLAIMS]
        self.assertEqual(sorted(lanes), sorted(set(lanes)))


class ComponentScopingTests(RavenTestCase):
    """A component check must grade what this template ships, not the union of all of them.

    `COMPONENT_PATHS["tool_configs"]` lists every template's starter tool
    config, so a template shipping none can never satisfy the check and
    reports a correct install as incomplete with a fix that restores nothing
    (#226).
    """

    def _install(self, language):
        ns = argparse.Namespace(
            destination=str(self.destination),
            language=language,
            args=None,
            overrides=[],
            dry_run=False,
            include_readme=False,
            adopt_claude_symlink=False,
            platform=None,
        )
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(raven.cmd_install(ns), 0)

    def _tool_configs_finding(self):
        return next(
            (
                f
                for f in integrity_findings(self.destination)
                if f.id == "doctor.install.component.tool_configs"
            ),
            None,
        )

    def test_template_shipping_no_tool_config_is_not_reported_absent(self):
        self._install("dotfiles")
        self.assertIsNone(self._tool_configs_finding())

    def test_template_shipping_a_tool_config_is_satisfied_by_it(self):
        self._install("python")
        self.assertTrue((self.destination / "pyproject.toml").exists())
        self.assertIsNone(self._tool_configs_finding())

    def test_a_deleted_tool_config_is_still_reported(self):
        # The scoping must not silence the case the check exists for: this
        # template did ship one, and it is gone.
        self._install("python")
        (self.destination / "pyproject.toml").unlink()
        finding = self._tool_configs_finding()
        self.assertIsNotNone(finding)
        assert finding is not None
        self.assertEqual(finding.severity, Severity.WARN)

    def test_the_detail_names_only_the_paths_this_template_ships(self):
        self._install("python")
        (self.destination / "pyproject.toml").unlink()
        finding = self._tool_configs_finding()
        assert finding is not None
        self.assertIn("pyproject.toml", finding.detail)
        self.assertNotIn(".rubocop.yml", finding.detail)

    def test_an_empty_manifest_keeps_the_unscoped_check(self):
        # A manifest with no file record is a broken install, not a template
        # that ships nothing; scoping there would silence every component.
        self._install("python")
        (self.destination / "pyproject.toml").unlink()
        manifest = self.destination / ".raven" / "manifest.json"
        data = json.loads(manifest.read_text(encoding="utf-8"))
        data["files"] = {}
        manifest.write_text(json.dumps(data), encoding="utf-8")
        self.assertIsNotNone(self._tool_configs_finding())


if __name__ == "__main__":
    unittest.main()
