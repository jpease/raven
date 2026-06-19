import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from helpers import RavenTestCase
from raven_lib.findings import Severity
from raven_lib.gate_run import gate_compliance_findings
from raven_lib.runner import RunResult


def _runner(outcomes):
    """outcomes: dict mapping the joined command string -> RunResult."""

    def runner(command, cwd):
        key = " ".join(command)
        for needle, result in outcomes.items():
            if needle in key:
                return result
        return RunResult(ok=True, code=0, stdout="", stderr="", found=True, timed_out=False)

    return runner


class GateRunTests(RavenTestCase):
    def _python_config_with_justfile(self):
        (self.destination / ".raven").mkdir()
        (self.destination / ".raven" / "config.toml").write_text(
            'schema = 1\ntemplate = "python"\n', encoding="utf-8"
        )
        (self.destination / "justfile").write_text(
            "lint:\n    ruff check .\nformat:\n    ruff format .\n"
            "typecheck:\n    pyright\ntest:\n    python -m pytest\n",
            encoding="utf-8",
        )

    def test_passing_gate_is_ok(self):
        self._python_config_with_justfile()
        runner = _runner({"just --version": RunResult(True, 0, "", "", True, False)})
        findings = gate_compliance_findings(self.destination, runner)
        lint = next(f for f in findings if f.id == "assess.gates.lint")
        self.assertEqual(lint.severity, Severity.OK)

    def test_failing_gate_is_error(self):
        self._python_config_with_justfile()
        runner = _runner(
            {
                "just --version": RunResult(True, 0, "", "", True, False),
                "just lint": RunResult(False, 1, "", "E501", True, False),
            }
        )
        findings = gate_compliance_findings(self.destination, runner)
        lint = next(f for f in findings if f.id == "assess.gates.lint")
        self.assertEqual(lint.severity, Severity.ERROR)

    def test_missing_just_falls_back_and_warns(self):
        self._python_config_with_justfile()
        runner = _runner({"just --version": RunResult(False, 127, "", "", False, False)})
        findings = gate_compliance_findings(self.destination, runner)
        self.assertIn("assess.gates.just", {f.id for f in findings})


if __name__ == "__main__":
    unittest.main()
