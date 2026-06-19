import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from helpers import RavenTestCase
from raven_lib.assess import build_assess_findings, template_fit_findings, wiring_findings
from raven_lib.findings import Severity


class AssessWiringTests(RavenTestCase):
    def _python_config(self):
        (self.destination / ".raven").mkdir()
        (self.destination / ".raven" / "config.toml").write_text(
            'schema = 1\ntemplate = "python"\n', encoding="utf-8"
        )

    def test_missing_justfile_warns(self):
        self._python_config()
        findings = wiring_findings(self.destination)
        match = next(f for f in findings if f.id == "assess.wiring.justfile")
        self.assertEqual(match.severity, Severity.WARN)

    def test_present_recipes_are_ok(self):
        self._python_config()
        (self.destination / "justfile").write_text(
            "lint:\n    ruff check .\nformat:\n    ruff format .\n"
            "typecheck:\n    pyright\ntest:\n    python -m pytest\n",
            encoding="utf-8",
        )
        findings = wiring_findings(self.destination)
        ids = {f.id: f for f in findings}
        self.assertEqual(ids["assess.wiring.recipe.lint"].severity, Severity.OK)
        self.assertEqual(ids["assess.wiring.recipe.test"].severity, Severity.OK)

    def test_ruff_config_signal_detected(self):
        self._python_config()
        (self.destination / "pyproject.toml").write_text(
            "[tool.ruff]\nline-length = 100\n", encoding="utf-8"
        )
        findings = wiring_findings(self.destination)
        match = next(f for f in findings if f.id == "assess.wiring.config.pyproject.toml")
        self.assertEqual(match.severity, Severity.OK)


class AssessFitTests(RavenTestCase):
    def test_matching_signal_is_ok(self):
        (self.destination / ".raven").mkdir()
        (self.destination / ".raven" / "config.toml").write_text(
            'schema = 1\ntemplate = "python"\n', encoding="utf-8"
        )
        (self.destination / "pyproject.toml").write_text("[tool.ruff]\n", encoding="utf-8")
        findings = template_fit_findings(self.destination)
        match = next(f for f in findings if f.id == "assess.fit.signal")
        self.assertEqual(match.severity, Severity.OK)


class AssessBuildTests(RavenTestCase):
    def test_without_run_gates_are_skipped(self):
        (self.destination / ".raven").mkdir()
        (self.destination / ".raven" / "config.toml").write_text(
            'schema = 1\ntemplate = "python"\n', encoding="utf-8"
        )
        findings = build_assess_findings(self.destination, run=False)
        self.assertIn("assess.gates.skipped", {f.id for f in findings})


if __name__ == "__main__":
    unittest.main()
