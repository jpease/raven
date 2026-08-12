"""Coverage for issue #160: config-gated skills the template still ships.

``classify_deactivated`` is a distinct classification path from
``classify_orphans`` -- see ``scripts/raven_lib/deactivated.py``'s module
docstring for why folding the two together would regress #97. These tests
cover the pure classification function directly (fabricated template/dest
trees, no CLI), then drive the real ``cmd_install``/``cmd_upgrade`` entry
points (mirroring ``tests/test_upgrade_orphans.py``'s harness) for the four
required platform-transition regressions.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import re
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from helpers import RavenTestCase, raven
from raven_lib.deactivated import classify_deactivated
from raven_lib.hashing import file_sha256
from raven_lib.manifest import load_manifest
from raven_lib.models import DeactivatedClassification, RavenConfig


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _config(platform: str = "none", template: str | None = None) -> RavenConfig:
    return RavenConfig(
        template=template,
        include_readme=False,
        components={},
        claude_components={},
        codex_components={},
        exclude_paths=[],
        platform=platform,
    )


class ClassifyDeactivatedTests(unittest.TestCase):
    """Direct, filesystem-fabricated coverage of the pure classification function."""

    def _setup(self) -> tuple[Path, Path]:
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        template = Path(tmp.name) / "template"
        dest = Path(tmp.name) / "dest"
        template.mkdir()
        dest.mkdir()
        return template, dest

    def _install_skill(
        self, template: Path, dest: Path, name: str, content: str = "skill content\n"
    ) -> str:
        rel = f".agents/skills/{name}/SKILL.md"
        _write(template / rel, content)
        _write(dest / rel, content)
        return rel

    def test_gated_skill_matching_baseline_is_removable(self) -> None:
        template, dest = self._setup()
        rel = self._install_skill(template, dest, "raven-github-issues")
        sha = file_sha256(dest / rel)
        manifest = {
            "schema": 1,
            "files": {rel: {"kind": "file", "installedSha256": sha, "sourceSha256": sha}},
        }
        # platform=gitlab excludes raven-github-issues from new installs, but
        # it is still shipped -- so it must be classified as deactivated, not
        # an orphan, and its baseline-matching content makes it removable.
        result = classify_deactivated(template, dest, manifest, _config(platform="gitlab"))
        self.assertEqual(result.removable, [rel])
        self.assertEqual(result.preserved, [])
        self.assertEqual(result.absent, [])

    def test_gated_skill_locally_modified_is_preserved(self) -> None:
        template, dest = self._setup()
        rel = self._install_skill(template, dest, "raven-github-issues")
        sha = file_sha256(dest / rel)
        (dest / rel).write_text("edited locally\n", encoding="utf-8")
        manifest = {
            "schema": 1,
            "files": {rel: {"kind": "file", "installedSha256": sha, "sourceSha256": sha}},
        }
        result = classify_deactivated(template, dest, manifest, _config(platform="gitlab"))
        self.assertEqual(result.preserved, [rel])
        self.assertEqual(result.removable, [])
        self.assertEqual(result.absent, [])

    def test_gated_skill_customized_baseline_is_preserved(self) -> None:
        # installed != source: an accepted manual merge, same rule orphans use.
        template, dest = self._setup()
        rel = self._install_skill(template, dest, "raven-github-issues")
        sha = file_sha256(dest / rel)
        manifest = {
            "schema": 1,
            "files": {rel: {"kind": "file", "installedSha256": sha, "sourceSha256": "b" * 64}},
        }
        result = classify_deactivated(template, dest, manifest, _config(platform="gitlab"))
        self.assertEqual(result.preserved, [rel])
        self.assertEqual(result.removable, [])

    def test_gated_skill_legacy_record_without_source_sha_is_preserved(self) -> None:
        template, dest = self._setup()
        rel = self._install_skill(template, dest, "raven-github-issues")
        sha = file_sha256(dest / rel)
        manifest = {"schema": 1, "files": {rel: {"kind": "file", "installedSha256": sha}}}
        result = classify_deactivated(template, dest, manifest, _config(platform="gitlab"))
        self.assertEqual(result.preserved, [rel])
        self.assertEqual(result.removable, [])

    def test_gated_skill_missing_on_disk_is_absent(self) -> None:
        template, dest = self._setup()
        rel = self._install_skill(template, dest, "raven-github-issues")
        sha = file_sha256(dest / rel)
        (dest / rel).unlink()
        manifest = {
            "schema": 1,
            "files": {rel: {"kind": "file", "installedSha256": sha, "sourceSha256": sha}},
        }
        result = classify_deactivated(template, dest, manifest, _config(platform="gitlab"))
        self.assertEqual(result.absent, [rel])
        self.assertEqual(result.removable, [])
        self.assertEqual(result.preserved, [])

    def test_non_gated_skill_is_not_classified(self) -> None:
        # platform=github selects raven-github-issues, so it is not gated at
        # all -- it must not appear in any bucket.
        template, dest = self._setup()
        rel = self._install_skill(template, dest, "raven-github-issues")
        sha = file_sha256(dest / rel)
        manifest = {
            "schema": 1,
            "files": {rel: {"kind": "file", "installedSha256": sha, "sourceSha256": sha}},
        }
        result = classify_deactivated(template, dest, manifest, _config(platform="github"))
        self.assertEqual(result, DeactivatedClassification([], [], []))

    def test_project_owned_unmanifested_file_is_never_classified(self) -> None:
        # A file that exists on disk but was never installed by Raven (no
        # manifest record) must never be classified, regardless of config.
        template, dest = self._setup()
        rel = "docs/my-notes.md"
        _write(dest / rel, "not raven's business\n")
        manifest = {"schema": 1, "files": {}}
        result = classify_deactivated(template, dest, manifest, _config(platform="github"))
        self.assertEqual(result, DeactivatedClassification([], [], []))
        self.assertTrue((dest / rel).exists())

    def test_still_selected_and_shipped_file_untouched_regardless_of_manifest(self) -> None:
        # A manifest-tracked, currently-selected file (e.g. raven-commit,
        # gated by nothing) must never be classified even though it is both
        # tracked and shipped -- only the gated intersection counts.
        template, dest = self._setup()
        rel = self._install_skill(template, dest, "raven-commit")
        sha = file_sha256(dest / rel)
        manifest = {
            "schema": 1,
            "files": {rel: {"kind": "file", "installedSha256": sha, "sourceSha256": sha}},
        }
        for platform in ("github", "gitlab", "none"):
            with self.subTest(platform=platform):
                result = classify_deactivated(template, dest, manifest, _config(platform=platform))
                self.assertEqual(result, DeactivatedClassification([], [], []))

    def test_malformed_manifest_files_returns_empty(self) -> None:
        template, dest = self._setup()
        manifest = {"schema": 1, "files": "not-a-dict"}
        result = classify_deactivated(template, dest, manifest, _config(platform="github"))
        self.assertEqual(result, DeactivatedClassification([], [], []))

    def test_template_gated_skill_matching_baseline_is_removable(self) -> None:
        # #169 extends coverage from the platform axis to the template axis:
        # a template-gated-but-still-shipped file (raven-dotfiles, gated to
        # template="dotfiles") must now be classified through the same
        # unmodified_baseline safety gate as the platform-gated skills above,
        # even though template_excluded is a distinct config field from
        # platform_excluded.
        template, dest = self._setup()
        rel = self._install_skill(template, dest, "raven-dotfiles")
        sha = file_sha256(dest / rel)
        manifest = {
            "schema": 1,
            "files": {rel: {"kind": "file", "installedSha256": sha, "sourceSha256": sha}},
        }
        from raven_lib.config import template_excluded

        config = _config(template="python")
        self.assertTrue(template_excluded(rel, config))  # confirms the premise
        result = classify_deactivated(template, dest, manifest, config)
        self.assertEqual(result.removable, [rel])
        self.assertEqual(result.preserved, [])
        self.assertEqual(result.absent, [])

    def test_template_gated_skill_locally_modified_is_preserved(self) -> None:
        # Mirrors test_gated_skill_locally_modified_is_preserved for the
        # template axis: the shared unmodified_baseline gate must still
        # refuse to remove a locally edited template-gated file.
        template, dest = self._setup()
        rel = self._install_skill(template, dest, "raven-dotfiles")
        sha = file_sha256(dest / rel)
        (dest / rel).write_text("edited locally\n", encoding="utf-8")
        manifest = {
            "schema": 1,
            "files": {rel: {"kind": "file", "installedSha256": sha, "sourceSha256": sha}},
        }
        result = classify_deactivated(template, dest, manifest, _config(template="python"))
        self.assertEqual(result.preserved, [rel])
        self.assertEqual(result.removable, [])
        self.assertEqual(result.absent, [])

    def test_handles_both_agents_and_claude_skills_twins_for_template_gate(self) -> None:
        # judgment call: verify (not just assume) that the .claude/skills
        # twin handling #160 found "falls out for free" from the candidate
        # derivation also holds for the template axis, mirroring
        # test_handles_both_agents_and_claude_skills_twins_when_not_symlinked
        # above.
        template, dest = self._setup()
        rel = self._install_skill(template, dest, "raven-dotfiles")
        (template / ".claude").mkdir(parents=True, exist_ok=True)
        (template / ".claude" / "skills").symlink_to(
            Path("..") / ".agents" / "skills", target_is_directory=True
        )

        twin_rel = ".claude/skills/raven-dotfiles/SKILL.md"
        _write(dest / twin_rel, (dest / rel).read_text(encoding="utf-8"))

        sha = file_sha256(dest / rel)
        twin_sha = file_sha256(dest / twin_rel)
        manifest = {
            "schema": 1,
            "files": {
                rel: {"kind": "file", "installedSha256": sha, "sourceSha256": sha},
                twin_rel: {"kind": "file", "installedSha256": twin_sha, "sourceSha256": twin_sha},
            },
        }
        result = classify_deactivated(template, dest, manifest, _config(template="python"))
        self.assertEqual(sorted(result.removable), sorted([rel, twin_rel]))
        self.assertEqual(result.preserved, [])
        self.assertEqual(result.absent, [])

    def test_handles_both_agents_and_claude_skills_twins_when_not_symlinked(self) -> None:
        # judgment call: when the destination declined .claude/skills symlink
        # adoption, .agents/skills/<name> and .claude/skills/<name> are two
        # separate manifest-tracked entries. Both must be classified, and
        # neither logical skill may be reported twice under one path.
        template, dest = self._setup()
        rel = self._install_skill(template, dest, "raven-github-issues")
        (template / ".claude").mkdir(parents=True, exist_ok=True)
        (template / ".claude" / "skills").symlink_to(
            Path("..") / ".agents" / "skills", target_is_directory=True
        )

        twin_rel = ".claude/skills/raven-github-issues/SKILL.md"
        _write(dest / twin_rel, (dest / rel).read_text(encoding="utf-8"))

        sha = file_sha256(dest / rel)
        twin_sha = file_sha256(dest / twin_rel)
        manifest = {
            "schema": 1,
            "files": {
                rel: {"kind": "file", "installedSha256": sha, "sourceSha256": sha},
                twin_rel: {"kind": "file", "installedSha256": twin_sha, "sourceSha256": twin_sha},
            },
        }
        result = classify_deactivated(template, dest, manifest, _config(platform="gitlab"))
        self.assertEqual(sorted(result.removable), sorted([rel, twin_rel]))
        self.assertEqual(result.preserved, [])
        self.assertEqual(result.absent, [])


class OrphanBoundaryRegressionTest(unittest.TestCase):
    """Guard against classify_deactivated ever feeding classify_orphans (#97 shape)."""

    def test_deactivated_candidates_are_disjoint_from_the_orphan_computation(self) -> None:
        # The candidate set must be (tracked ∩ shipped ∩ gated), never derived
        # from (tracked - shipped) -- that is classify_orphans's computation.
        # This locks the derivation in by construction: every deactivated
        # candidate is, by definition, still in shipped_relatives.
        from raven_lib.orphans import shipped_relatives

        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        template = Path(tmp.name) / "template"
        dest = Path(tmp.name) / "dest"
        template.mkdir()
        dest.mkdir()
        rel = ".agents/skills/raven-github-issues/SKILL.md"
        _write(template / rel, "content\n")
        _write(dest / rel, "content\n")
        sha = file_sha256(dest / rel)
        manifest = {
            "schema": 1,
            "files": {rel: {"kind": "file", "installedSha256": sha, "sourceSha256": sha}},
        }
        result = classify_deactivated(template, dest, manifest, _config(platform="gitlab"))
        shipped = shipped_relatives(template, dest)
        for bucket in (result.removable, result.preserved, result.absent):
            for candidate in bucket:
                self.assertIn(candidate, shipped)


# ---------------------------------------------------------------------------
# End-to-end: the real cmd_install/cmd_upgrade entry points, mirroring
# tests/test_upgrade_orphans.py's harness, against a throwaway language
# template with the two real platform-gated skill names.
# ---------------------------------------------------------------------------


def _install_ns(destination: Path, *, language: str, platform: str | None) -> argparse.Namespace:
    return argparse.Namespace(
        destination=str(destination),
        language=language,
        args=None,
        overrides=[],
        dry_run=False,
        include_readme=False,
        adopt_claude_symlink=False,
        platform=platform,
    )


def _upgrade_ns(destination: Path, *, dry_run: bool = False) -> argparse.Namespace:
    return argparse.Namespace(
        destination=str(destination),
        overrides=[],
        dry_run=dry_run,
        include_readme=False,
        adopt_claude_symlink=False,
    )


class PlatformTransitionEndToEndTests(RavenTestCase):
    def setUp(self) -> None:
        super().setUp()
        self._fake_repo_tmp = TemporaryDirectory()
        self.addCleanup(self._fake_repo_tmp.cleanup)
        self.fake_repo_root = Path(self._fake_repo_tmp.name)
        self.template_dir = self.fake_repo_root / "lang"
        _write(self.template_dir / "AGENTS.md", "root instructions\n")
        _write(
            self.template_dir / ".agents" / "skills" / "raven-github-issues" / "SKILL.md",
            "github skill content\n",
        )
        _write(
            self.template_dir / ".agents" / "skills" / "raven-gitlab-issues" / "SKILL.md",
            "gitlab skill content\n",
        )
        patcher = mock.patch("raven_lib.cli.REPO_ROOT", self.fake_repo_root)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _install(self, platform: str) -> None:
        ns = _install_ns(self.destination, language="lang", platform=platform)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            rc = raven.cmd_install(ns)
        self.assertEqual(rc, 0)

    def _switch_platform(self, platform: str) -> None:
        from raven_lib.config import _update_config_platform
        from raven_lib.constants import CONFIG_PATH

        _update_config_platform(self.destination / CONFIG_PATH, platform)

    def _dry_run_upgrade(self) -> tuple[int, str]:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
            rc = raven.cmd_upgrade(_upgrade_ns(self.destination, dry_run=True))
        return rc, buf.getvalue()

    def _upgrade(self) -> tuple[int, str]:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
            rc = raven.cmd_upgrade(_upgrade_ns(self.destination))
        return rc, buf.getvalue()

    def _add_project_owned_skill(self) -> Path:
        path = self.destination / ".agents" / "skills" / "my-custom-skill" / "SKILL.md"
        _write(path, "project-owned, not raven's\n")
        return path

    def _assert_transition(
        self,
        *,
        from_platform: str,
        to_platform: str,
        deactivated_name: str,
        activated_name: str | None,
    ) -> None:
        self._install(from_platform)
        project_skill = self._add_project_owned_skill()
        project_content = project_skill.read_text(encoding="utf-8")

        deactivated_rel = f".agents/skills/{deactivated_name}/SKILL.md"
        deactivated_path = self.destination / deactivated_rel
        self.assertTrue(deactivated_path.exists())
        self.assertIn(deactivated_rel, load_manifest(self.destination)["files"])

        self._switch_platform(to_platform)

        rc, dry_output = self._dry_run_upgrade()
        self.assertEqual(rc, 0)
        self.assertIn("deactivated by config", dry_output)
        self.assertIn(deactivated_rel, dry_output)
        # dry-run must not touch the filesystem.
        self.assertTrue(deactivated_path.exists())

        rc, output = self._upgrade()
        self.assertEqual(rc, 0)
        self.assertFalse(deactivated_path.exists())
        self.assertNotIn(deactivated_rel, load_manifest(self.destination)["files"])
        self.assertIn("deactivated by config", output)
        self.assertIn(deactivated_rel, output)

        if activated_name:
            activated_rel = f".agents/skills/{activated_name}/SKILL.md"
            self.assertTrue((self.destination / activated_rel).exists())
            self.assertIn(activated_rel, load_manifest(self.destination)["files"])

        self.assertTrue(project_skill.exists())
        self.assertEqual(project_skill.read_text(encoding="utf-8"), project_content)

    def test_github_to_gitlab_deactivates_github_activates_gitlab(self) -> None:
        self._assert_transition(
            from_platform="github",
            to_platform="gitlab",
            deactivated_name="raven-github-issues",
            activated_name="raven-gitlab-issues",
        )

    def test_gitlab_to_github_deactivates_gitlab_activates_github(self) -> None:
        self._assert_transition(
            from_platform="gitlab",
            to_platform="github",
            deactivated_name="raven-gitlab-issues",
            activated_name="raven-github-issues",
        )

    def test_github_to_none_deactivates_github_activates_nothing(self) -> None:
        self._assert_transition(
            from_platform="github",
            to_platform="none",
            deactivated_name="raven-github-issues",
            activated_name=None,
        )

    def test_gitlab_to_none_deactivates_gitlab_activates_nothing(self) -> None:
        self._assert_transition(
            from_platform="gitlab",
            to_platform="none",
            deactivated_name="raven-gitlab-issues",
            activated_name=None,
        )

    def test_locally_modified_deactivated_skill_is_preserved_not_deleted(self) -> None:
        self._install("github")
        skill_path = self.destination / ".agents" / "skills" / "raven-github-issues" / "SKILL.md"
        skill_path.write_text("user edited this locally\n", encoding="utf-8")
        self._switch_platform("gitlab")

        rc, output = self._upgrade()
        self.assertEqual(rc, 0)
        self.assertTrue(skill_path.exists())
        self.assertEqual(skill_path.read_text(encoding="utf-8"), "user edited this locally\n")
        self.assertIn(
            ".agents/skills/raven-github-issues/SKILL.md", load_manifest(self.destination)["files"]
        )
        self.assertIn("Deactivated by config but left in place because you modified them", output)

    def test_malformed_config_never_deletes_a_deactivated_skill(self) -> None:
        # The config-read-failure guarantee: classify_deactivated is only ever
        # reached with a validated RavenConfig, because every call site
        # (cli._load_config_or_report, doctor.build_doctor_findings) reports
        # ConfigError and aborts before reaching it. Corrupting the config
        # after a successful install must not delete anything.
        self._install("github")
        skill_path = self.destination / ".agents" / "skills" / "raven-github-issues" / "SKILL.md"
        self.assertTrue(skill_path.exists())
        from raven_lib.constants import CONFIG_PATH

        (self.destination / CONFIG_PATH).write_text("this is not valid toml [[[", encoding="utf-8")

        buf_out, buf_err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(buf_out), contextlib.redirect_stderr(buf_err):
            rc = raven.cmd_upgrade(_upgrade_ns(self.destination))
        self.assertEqual(rc, 2)
        self.assertTrue(skill_path.exists())


# ---------------------------------------------------------------------------
# End-to-end: the template-axis sibling of PlatformTransitionEndToEndTests
# above. raven-dotfiles is gated to template="dotfiles"; in the real repo it
# is shipped by every language tree (via the common/ symlink) but only
# selected for install when that config value matches -- so the fake repo
# here mirrors that with two throwaway template dirs that both ship the same
# raven-dotfiles skill content, matching issue #169's required "template
# transition away from dotfiles" regression.
# ---------------------------------------------------------------------------


class TemplateTransitionEndToEndTests(RavenTestCase):
    def setUp(self) -> None:
        super().setUp()
        self._fake_repo_tmp = TemporaryDirectory()
        self.addCleanup(self._fake_repo_tmp.cleanup)
        self.fake_repo_root = Path(self._fake_repo_tmp.name)
        dotfiles_skill_rel = ".agents/skills/raven-dotfiles/SKILL.md"
        for template_name in ("dotfiles", "other"):
            _write(self.fake_repo_root / template_name / "AGENTS.md", "root instructions\n")
            _write(
                self.fake_repo_root / template_name / dotfiles_skill_rel,
                "dotfiles skill content\n",
            )
        patcher = mock.patch("raven_lib.cli.REPO_ROOT", self.fake_repo_root)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _install(self, template_name: str) -> None:
        ns = _install_ns(self.destination, language=template_name, platform=None)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            rc = raven.cmd_install(ns)
        self.assertEqual(rc, 0)

    def _switch_template(self, template_name: str) -> None:
        from raven_lib.constants import CONFIG_PATH

        config_path = self.destination / CONFIG_PATH
        text = config_path.read_text(encoding="utf-8")
        new_text = re.sub(
            r'(?m)^template\s*=\s*".*"$', f'template = "{template_name}"', text, count=1
        )
        self.assertNotEqual(text, new_text)  # confirms the substitution actually matched
        config_path.write_text(new_text, encoding="utf-8")

    def _dry_run_upgrade(self) -> tuple[int, str]:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
            rc = raven.cmd_upgrade(_upgrade_ns(self.destination, dry_run=True))
        return rc, buf.getvalue()

    def _upgrade(self) -> tuple[int, str]:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
            rc = raven.cmd_upgrade(_upgrade_ns(self.destination))
        return rc, buf.getvalue()

    def test_dotfiles_to_other_template_deactivates_raven_dotfiles(self) -> None:
        self._install("dotfiles")
        project_skill = self.destination / ".agents" / "skills" / "my-custom-skill" / "SKILL.md"
        _write(project_skill, "project-owned, not raven's\n")
        project_content = project_skill.read_text(encoding="utf-8")

        deactivated_rel = ".agents/skills/raven-dotfiles/SKILL.md"
        deactivated_path = self.destination / deactivated_rel
        self.assertTrue(deactivated_path.exists())
        self.assertIn(deactivated_rel, load_manifest(self.destination)["files"])

        self._switch_template("other")

        rc, dry_output = self._dry_run_upgrade()
        self.assertEqual(rc, 0)
        self.assertIn("deactivated by config", dry_output)
        self.assertIn(deactivated_rel, dry_output)
        # dry-run must not touch the filesystem.
        self.assertTrue(deactivated_path.exists())

        rc, output = self._upgrade()
        self.assertEqual(rc, 0)
        self.assertFalse(deactivated_path.exists())
        self.assertNotIn(deactivated_rel, load_manifest(self.destination)["files"])
        self.assertIn("deactivated by config", output)
        self.assertIn(deactivated_rel, output)

        self.assertTrue(project_skill.exists())
        self.assertEqual(project_skill.read_text(encoding="utf-8"), project_content)

    def test_locally_modified_template_gated_skill_is_preserved_not_deleted(self) -> None:
        self._install("dotfiles")
        skill_path = self.destination / ".agents" / "skills" / "raven-dotfiles" / "SKILL.md"
        skill_path.write_text("user edited this locally\n", encoding="utf-8")
        self._switch_template("other")

        rc, output = self._upgrade()
        self.assertEqual(rc, 0)
        self.assertTrue(skill_path.exists())
        self.assertEqual(skill_path.read_text(encoding="utf-8"), "user edited this locally\n")
        self.assertIn(
            ".agents/skills/raven-dotfiles/SKILL.md", load_manifest(self.destination)["files"]
        )
        self.assertIn("Deactivated by config but left in place because you modified them", output)


if __name__ == "__main__":
    unittest.main()
