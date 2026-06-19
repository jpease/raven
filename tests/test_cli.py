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


import json as _json


class DoctorAssessCliTests(RavenTestCase):
    def _run(self, *cli_args):
        return subprocess.run(
            [sys.executable, str(RAVEN_PATH), "-d", str(self.destination), *cli_args],
            capture_output=True,
            text=True,
            check=False,
        )

    def test_doctor_help_lists_command(self):
        result = subprocess.run(
            [sys.executable, str(RAVEN_PATH), "--help"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertIn("doctor", result.stdout)
        self.assertIn("assess", result.stdout)

    def test_doctor_on_empty_dir_errors(self):
        result = self._run("doctor", "--json")
        self.assertEqual(result.returncode, 1)
        data = _json.loads(result.stdout)
        self.assertEqual(data["command"], "doctor")
        self.assertTrue(any(f["severity"] == "error" for f in data["findings"]))

    def test_assess_json_on_installed_repo_exits_zero(self):
        (self.destination / ".raven").mkdir()
        (self.destination / ".raven" / "config.toml").write_text(
            'schema = 1\ntemplate = "python"\n', encoding="utf-8"
        )
        (self.destination / "AGENTS.md").write_text("# A\n", encoding="utf-8")
        (self.destination / "justfile").write_text(
            "lint:\n    ruff check .\nformat:\n    ruff format .\n"
            "typecheck:\n    pyright\ntest:\n    python -m pytest\n",
            encoding="utf-8",
        )
        result = self._run("assess", "--json")
        self.assertEqual(result.returncode, 0)
        data = _json.loads(result.stdout)
        self.assertEqual(data["command"], "assess")


if __name__ == "__main__":
    unittest.main()
