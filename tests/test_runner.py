import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from raven_lib.runner import run_command


class RunnerTests(unittest.TestCase):
    def test_missing_executable_reports_not_found(self):
        result = run_command(["definitely-not-a-real-binary-xyz"], Path.cwd())
        self.assertFalse(result.found)
        self.assertFalse(result.ok)
        self.assertEqual(result.code, 127)

    def test_true_command_succeeds(self):
        result = run_command([sys.executable, "-c", "pass"], Path.cwd())
        self.assertTrue(result.found)
        self.assertTrue(result.ok)
        self.assertEqual(result.code, 0)

    def test_nonzero_command_reports_failure(self):
        result = run_command([sys.executable, "-c", "import sys; sys.exit(3)"], Path.cwd())
        self.assertTrue(result.found)
        self.assertFalse(result.ok)
        self.assertEqual(result.code, 3)


if __name__ == "__main__":
    unittest.main()
