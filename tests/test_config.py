import contextlib
import io
import unittest
from pathlib import Path

from helpers import REPO_ROOT, RavenTestCase, raven


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
        self.assertFalse(raven.platform_excluded(".agents/skills/raven-github-issues/SKILL.md", config_github))
        self.assertTrue(raven.platform_excluded(".agents/skills/raven-github-issues/SKILL.md", config_gitlab))
        self.assertTrue(raven.platform_excluded(".agents/skills/raven-github-issues/SKILL.md", config_none))

        # gitlab skill gating
        self.assertTrue(raven.platform_excluded(".agents/skills/raven-gitlab-issues/SKILL.md", config_github))
        self.assertFalse(raven.platform_excluded(".agents/skills/raven-gitlab-issues/SKILL.md", config_gitlab))
        self.assertTrue(raven.platform_excluded(".agents/skills/raven-gitlab-issues/SKILL.md", config_none))

        # unrelated skills are never excluded by platform
        self.assertFalse(raven.platform_excluded(".agents/skills/raven-commit/SKILL.md", config_none))


if __name__ == "__main__":
    unittest.main()
