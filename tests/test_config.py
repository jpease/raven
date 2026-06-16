import argparse
import contextlib
import io
import unittest

from helpers import REPO_ROOT, RavenTestCase, raven


class BuildConfigTests(unittest.TestCase):
    def test_empty_raw_yields_defaults(self):
        config = raven.build_config({}, exists=False)
        self.assertFalse(config.exists)
        self.assertIsNone(config.template)
        self.assertFalse(config.include_readme)
        self.assertEqual(config.platform, "none")
        self.assertEqual(config.exclude_paths, [])
        self.assertEqual(config.components, raven.DEFAULT_COMPONENTS)
        # Must not alias the module-level defaults.
        self.assertIsNot(config.components, raven.DEFAULT_COMPONENTS)

    def test_component_overrides_merge_over_defaults(self):
        config = raven.build_config(
            {"components": {"hooks": False, "unknown": True, "skills": "nope"}},
            exists=True,
        )
        self.assertFalse(config.components["hooks"])
        self.assertTrue(config.components["skills"])  # non-bool override ignored
        self.assertNotIn("unknown", config.components)  # unknown key ignored

    def test_platform_and_template_parsed(self):
        config = raven.build_config(
            {
                "template": "rust",
                "include_readme": True,
                "issue_tracker": {"platform": "github"},
                "exclude": {"paths": ["a/b", "c\\d"]},
            },
            exists=True,
        )
        self.assertEqual(config.template, "rust")
        self.assertTrue(config.include_readme)
        self.assertEqual(config.platform, "github")
        self.assertEqual(config.exclude_paths, ["a/b", "c/d"])


class PathWithinTests(unittest.TestCase):
    def test_matches_exact_and_descendants_only(self):
        self.assertTrue(raven.path_within(".claude/skills", ".claude/skills"))
        self.assertTrue(raven.path_within(".claude/skills/x/SKILL.md", ".claude/skills"))
        self.assertFalse(raven.path_within(".claude/skills-extra", ".claude/skills"))
        self.assertFalse(raven.path_within(".claude", ".claude/skills"))


class ReplacePlatformLineTests(unittest.TestCase):
    def test_replaces_only_active_line_in_issue_tracker_section(self):
        text = raven.default_config_text("python", False, "none")
        result = raven.replace_platform_line(text, "github")
        self.assertIn('platform = "github"', result)
        # Commented example lines like '# platform = "none"' stay untouched.
        self.assertNotIn('\nplatform = "none"', result)
        self.assertIn('# platform = "none"', result)

    def test_ignores_platform_line_outside_issue_tracker(self):
        text = 'platform = "decoy"\n\n[issue_tracker]\nplatform = "none"\n'
        result = raven.replace_platform_line(text, "gitlab")
        self.assertIn('platform = "decoy"', result)
        self.assertIn('platform = "gitlab"', result)
        self.assertNotIn('platform = "none"', result)

    def test_no_section_leaves_text_unchanged(self):
        text = 'template = "python"\n'
        self.assertEqual(raven.replace_platform_line(text, "github"), text)


class ConfigTests(RavenTestCase):
    def test_default_config_is_self_documenting(self):
        text = raven.default_config_text("rust", False)

        self.assertIn('template = "rust"', text)
        self.assertIn("# Language template", text)
        self.assertIn("[components.claude]", text)
        self.assertIn("[components.codex]", text)
        self.assertIn("# Codex project config", text)
        self.assertIn("tool_configs = true", text)
        self.assertIn("[exclude]", text)

    def test_default_config_includes_lifecycle_section(self):
        config = raven.default_config_text("python", False)
        self.assertIn("[lifecycle]", config)
        self.assertIn("checkpoint_enforcement = true", config)

    def test_default_config_includes_issue_tracker_section(self):
        config = raven.default_config_text("python", False)
        self.assertIn("[issue_tracker]", config)
        self.assertIn('platform = "none"', config)

    def test_default_config_embeds_github_platform(self):
        config = raven.default_config_text("python", False, "github")
        self.assertIn('platform = "github"', config)
        # The comment block contains "# platform = "none""; check the active (uncommented) line.
        self.assertNotIn('\nplatform = "none"', config)

    def test_default_config_embeds_gitlab_platform(self):
        config = raven.default_config_text("python", False, "gitlab")
        self.assertIn('platform = "gitlab"', config)

    def test_update_config_platform_replaces_platform_value(self):
        config_path = self.destination / ".raven" / "config.toml"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(raven.default_config_text("python", False, "none"), encoding="utf-8")

        raven._update_config_platform(config_path, "github")

        text = config_path.read_text(encoding="utf-8")
        self.assertIn('platform = "github"', text)
        self.assertNotIn('\nplatform = "none"', text)

    def test_init_with_platform_writes_platform_to_config(self):
        import argparse

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            rc = raven.cmd_init(
                argparse.Namespace(
                    destination=str(self.destination), language="python", platform="github"
                )
            )
        self.assertEqual(rc, 0)
        text = (self.destination / ".raven" / "config.toml").read_text(encoding="utf-8")
        self.assertIn('platform = "github"', text)

    def test_install_platform_flag_updates_existing_config(self):
        import argparse

        (self.destination / ".raven").mkdir(parents=True, exist_ok=True)
        config_path = self.destination / ".raven" / "config.toml"
        config_path.write_text(raven.default_config_text("python", False, "none"), encoding="utf-8")
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            rc = raven.cmd_install(
                argparse.Namespace(
                    destination=str(self.destination),
                    language=None,
                    args=None,
                    overrides=[],
                    dry_run=False,
                    include_readme=False,
                    adopt_claude_symlink=False,
                    platform="github",
                )
            )
        self.assertEqual(rc, 0)
        self.assertIn('platform = "github"', config_path.read_text(encoding="utf-8"))


class PlatformGatingTests(RavenTestCase):
    """Issue-tracker skills are gated by the platform field in config."""

    def _make_config(self, platform: str) -> raven.RavenConfig:
        config_path = self.destination / ".raven" / "config.toml"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(
            raven.default_config_text("python", False, platform), encoding="utf-8"
        )
        return raven.load_config(self.destination)

    def _skill_entries(self, platform: str) -> set[str]:
        config = self._make_config(platform)
        template = REPO_ROOT / "python"
        entries = raven.iter_template_entries(template, self.excludes, config)
        return {e.relative for e in entries}

    def test_load_config_parses_platform_github(self):
        config = self._make_config("github")
        self.assertEqual(config.platform, "github")

    def test_load_config_parses_platform_gitlab(self):
        config = self._make_config("gitlab")
        self.assertEqual(config.platform, "gitlab")

    def test_load_config_parses_platform_none(self):
        config = self._make_config("none")
        self.assertEqual(config.platform, "none")

    def test_load_config_default_platform_is_none(self):
        # No config file present
        config = raven.load_config(self.destination)
        self.assertEqual(config.platform, "none")

    def test_load_config_warns_and_defaults_on_unreadable_file(self):
        config_path = self.destination / ".raven" / "config.toml"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_bytes(b"\xff\xfe not valid utf-8")
        err = io.StringIO()

        with contextlib.redirect_stderr(err):
            config = raven.load_config(self.destination)

        self.assertTrue(config.exists)
        self.assertIsNone(config.template)
        self.assertIn("warning", err.getvalue())

    def test_github_platform_includes_github_skill(self):
        entries = self._skill_entries("github")
        self.assertTrue(
            any("raven-github-issues" in e for e in entries),
            f"raven-github-issues not found in entries: {sorted(entries)[:10]}",
        )

    def test_github_platform_excludes_gitlab_skill(self):
        entries = self._skill_entries("github")
        self.assertFalse(
            any("raven-gitlab-issues" in e for e in entries),
            "raven-gitlab-issues should be excluded when platform=github",
        )

    def test_gitlab_platform_includes_gitlab_skill(self):
        entries = self._skill_entries("gitlab")
        self.assertTrue(
            any("raven-gitlab-issues" in e for e in entries),
            f"raven-gitlab-issues not found in entries: {sorted(entries)[:10]}",
        )

    def test_gitlab_platform_excludes_github_skill(self):
        entries = self._skill_entries("gitlab")
        self.assertFalse(
            any("raven-github-issues" in e for e in entries),
            "raven-github-issues should be excluded when platform=gitlab",
        )

    def test_none_platform_excludes_both_issue_skills(self):
        entries = self._skill_entries("none")
        self.assertFalse(
            any("raven-github-issues" in e for e in entries),
            "raven-github-issues should be excluded when platform=none",
        )
        self.assertFalse(
            any("raven-gitlab-issues" in e for e in entries),
            "raven-gitlab-issues should be excluded when platform=none",
        )

    def test_platform_excluded_helper_directly(self):
        config_github = self._make_config("github")
        config_gitlab = self._make_config("gitlab")
        config_none = self._make_config("none")

        # github skill gating
        self.assertFalse(
            raven.platform_excluded(".agents/skills/raven-github-issues/SKILL.md", config_github)
        )
        self.assertTrue(
            raven.platform_excluded(".agents/skills/raven-github-issues/SKILL.md", config_gitlab)
        )
        self.assertTrue(
            raven.platform_excluded(".agents/skills/raven-github-issues/SKILL.md", config_none)
        )

        # gitlab skill gating
        self.assertTrue(
            raven.platform_excluded(".agents/skills/raven-gitlab-issues/SKILL.md", config_github)
        )
        self.assertFalse(
            raven.platform_excluded(".agents/skills/raven-gitlab-issues/SKILL.md", config_gitlab)
        )
        self.assertTrue(
            raven.platform_excluded(".agents/skills/raven-gitlab-issues/SKILL.md", config_none)
        )

        # unrelated skills are never excluded by platform
        self.assertFalse(
            raven.platform_excluded(".agents/skills/raven-commit/SKILL.md", config_none)
        )


class TemplateGatingTests(RavenTestCase):
    """The raven-dotfiles skill is gated to template=dotfiles."""

    def _make_config(self, template: str) -> raven.RavenConfig:
        config_path = self.destination / ".raven" / "config.toml"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(raven.default_config_text(template, False), encoding="utf-8")
        return raven.load_config(self.destination)

    def _skill_entries(self, template: str) -> set[str]:
        config = self._make_config(template)
        template_dir = REPO_ROOT / template
        entries = raven.iter_template_entries(template_dir, self.excludes, config)
        return {e.relative for e in entries}

    def test_dotfiles_template_includes_dotfiles_skill(self):
        entries = self._skill_entries("dotfiles")
        self.assertTrue(
            any("raven-dotfiles" in e for e in entries),
            f"raven-dotfiles not found in entries: {sorted(entries)[:10]}",
        )

    def test_python_template_excludes_dotfiles_skill(self):
        entries = self._skill_entries("python")
        self.assertFalse(
            any("raven-dotfiles" in e for e in entries),
            "raven-dotfiles should be excluded when template=python",
        )

    def test_template_excluded_helper_directly(self):
        config_dotfiles = self._make_config("dotfiles")
        config_python = self._make_config("python")

        self.assertFalse(
            raven.template_excluded(".agents/skills/raven-dotfiles/SKILL.md", config_dotfiles)
        )
        self.assertTrue(
            raven.template_excluded(".agents/skills/raven-dotfiles/SKILL.md", config_python)
        )
        # .claude/skills twin is also gated
        self.assertTrue(
            raven.template_excluded(".claude/skills/raven-dotfiles/SKILL.md", config_python)
        )
        # unrelated skills are never excluded by template
        self.assertFalse(
            raven.template_excluded(".agents/skills/raven-commit/SKILL.md", config_python)
        )

    def test_template_excluded_when_template_is_none(self):
        config_no_template = raven.build_config({}, exists=False)
        self.assertTrue(
            raven.template_excluded(".agents/skills/raven-dotfiles/SKILL.md", config_no_template)
        )


class PlatformDryRunTests(RavenTestCase):
    """Fresh-install dry runs must preview --platform gating without writing config."""

    def _install_args(self, dry_run: bool) -> argparse.Namespace:
        return argparse.Namespace(
            destination=str(self.destination),
            args=["python"],
            language=None,
            overrides=[],
            dry_run=dry_run,
            include_readme=False,
            adopt_claude_symlink=False,
            platform="github",
        )

    def test_fresh_install_dry_run_previews_platform_gating(self):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            rc = raven.cmd_install(self._install_args(dry_run=True))

        self.assertEqual(rc, 0)
        output = buffer.getvalue()
        self.assertIn("raven-github-issues", output)
        self.assertNotIn("raven-gitlab-issues", output)

    def test_fresh_install_dry_run_writes_no_config(self):
        with contextlib.redirect_stdout(io.StringIO()):
            raven.cmd_install(self._install_args(dry_run=True))

        self.assertFalse((self.destination / ".raven" / "config.toml").exists())

    def test_existing_config_dry_run_does_not_persist_platform(self):
        config_path = self.destination / ".raven" / "config.toml"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(
            raven.default_config_text("python", False, "gitlab"), encoding="utf-8"
        )
        before = config_path.read_text(encoding="utf-8")

        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            rc = raven.cmd_install(self._install_args(dry_run=True))

        self.assertEqual(rc, 0)
        self.assertEqual(config_path.read_text(encoding="utf-8"), before)
        output = buffer.getvalue()
        self.assertIn("raven-github-issues", output)
        self.assertNotIn("raven-gitlab-issues", output)


if __name__ == "__main__":
    unittest.main()
