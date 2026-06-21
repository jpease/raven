import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from helpers import RavenTestCase
from raven_lib.findings import Severity
from raven_lib.gate_run import gate_compliance_findings
from raven_lib.runner import RunResult


def _runner(outcomes, *, calls=None):
    """outcomes: dict mapping the joined command string -> RunResult.

    When ``calls`` is provided it records each joined command string invoked.
    """

    def runner(command, cwd):
        key = " ".join(command)
        if calls is not None:
            calls.append(key)
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

    def test_failed_just_version_uses_fallback_and_warns(self):
        # `just` is on PATH but `just --version` exits non-zero: treat it as
        # unusable, run the configured fallbacks (which pass), and never invoke
        # the broken `just <recipe>`.
        self._python_config_with_justfile()
        calls: list[str] = []
        runner = _runner({"just --version": RunResult(False, 1, "", "", True, False)}, calls=calls)
        findings = gate_compliance_findings(self.destination, runner)

        warning = next(f for f in findings if f.id == "assess.gates.just")
        self.assertEqual(warning.severity, Severity.WARN)
        self.assertNotIn("just lint", calls)
        lint = next(f for f in findings if f.id == "assess.gates.lint")
        self.assertEqual(lint.severity, Severity.OK)

    def test_timed_out_just_version_uses_fallback_and_warns(self):
        self._python_config_with_justfile()
        calls: list[str] = []
        runner = _runner({"just --version": RunResult(False, 124, "", "", True, True)}, calls=calls)
        findings = gate_compliance_findings(self.destination, runner)

        warning = next(f for f in findings if f.id == "assess.gates.just")
        self.assertEqual(warning.severity, Severity.WARN)
        self.assertIn("timed out", warning.title.lower() + " " + warning.detail.lower())
        self.assertNotIn("just lint", calls)

    def test_successful_just_version_does_not_warn(self):
        self._python_config_with_justfile()
        runner = _runner({"just --version": RunResult(True, 0, "", "", True, False)})
        findings = gate_compliance_findings(self.destination, runner)
        self.assertNotIn("assess.gates.just", {f.id for f in findings})


if __name__ == "__main__":
    unittest.main()
