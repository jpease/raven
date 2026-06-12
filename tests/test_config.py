import contextlib
import io
import unittest

from helpers import RavenTestCase, raven


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


if __name__ == "__main__":
    unittest.main()
