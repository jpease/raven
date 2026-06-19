import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from raven_lib.findings import Finding, Severity, exit_code, summarize


class FindingsTests(unittest.TestCase):
    def _f(self, severity: Severity) -> Finding:
        return Finding(id="x", severity=severity, category="C", title="t", detail="d")

    def test_exit_code_zero_when_no_errors(self):
        findings = [self._f(Severity.OK), self._f(Severity.WARN)]
        self.assertEqual(exit_code(findings), 0)

    def test_exit_code_one_when_any_error(self):
        findings = [self._f(Severity.OK), self._f(Severity.ERROR)]
        self.assertEqual(exit_code(findings), 1)

    def test_summarize_counts_by_severity(self):
        findings = [
            self._f(Severity.OK),
            self._f(Severity.WARN),
            self._f(Severity.ERROR),
            self._f(Severity.OK),
        ]
        self.assertEqual(summarize(findings), {"errors": 1, "warnings": 1, "ok": 2})

    def test_severity_value_is_lowercase_string(self):
        self.assertEqual(Severity.WARN.value, "warn")


if __name__ == "__main__":
    unittest.main()
