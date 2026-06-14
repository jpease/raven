import os
import subprocess
import sys
import unittest

from helpers import RAVEN_PATH, REPO_ROOT, RavenTestCase


class CliTests(RavenTestCase):
    def test_self_check_script_exists_and_is_executable(self):
        script = REPO_ROOT / "scripts" / "self-check.py"

        self.assertTrue(script.is_file())
        self.assertTrue(os.access(script, os.X_OK))

    def test_raven_wrapper_exists_and_delegates_to_cli(self):
        script = REPO_ROOT / "scripts" / "raven"

        self.assertTrue(script.is_file())
        self.assertTrue(os.access(script, os.X_OK))
        result = subprocess.run(
            [str(script), "--help"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("Raven", result.stdout)
        self.assertIn("install", result.stdout)
        self.assertIn("usage: raven [OPTIONS] COMMAND [ARGS]...", result.stdout)
        self.assertIn("--destination DESTINATION", result.stdout)
        self.assertIn("raven install <language> --dry-run", result.stdout)
        self.assertIn("raven install go --dry-run", result.stdout)
        self.assertIn("raven upgrade .claude/scripts/raven-tool-check.py", result.stdout)
        self.assertIn("Explicit override paths force-copy Raven-owned files.", result.stdout)
        self.assertIn("Supported languages:", result.stdout)
        self.assertIn("File safety:", result.stdout)
        self.assertNotIn("Safety model:", result.stdout)

    def test_install_help_names_language_and_overrides(self):
        result = subprocess.run(
            [sys.executable, str(RAVEN_PATH), "install", "--help"],
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0)
        self.assertIn("usage: raven install [OPTIONS] [language] [override ...]", result.stdout)
        self.assertIn("language template to install", result.stdout)
        self.assertIn("template-relative file paths to force-copy", result.stdout)
        self.assertIn("Supported languages:", result.stdout)
        self.assertNotIn("language_or_path", result.stdout)


if __name__ == "__main__":
    unittest.main()
