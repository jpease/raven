import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from raven_lib.findings import Finding, Severity
from raven_lib.report import render_human, render_json


def _findings() -> list[Finding]:
    return [
        Finding(
            id="a.ok",
            severity=Severity.OK,
            category="Toolchain",
            title="ripgrep present",
            detail="found",
        ),
        Finding(
            id="a.warn",
            severity=Severity.WARN,
            category="Toolchain",
            title="fd missing",
            detail="not found",
            fix="install fd",
        ),
        Finding(
            id="b.err",
            severity=Severity.ERROR,
            category="Install integrity",
            title="config missing",
            detail="no config.toml",
            fix="run raven install",
        ),
    ]


class ReportTests(unittest.TestCase):
    def test_human_groups_by_category_and_marks_severity(self):
        out = render_human("doctor", "darwin", _findings())
        self.assertIn("Toolchain", out)
        self.assertIn("Install integrity", out)
        self.assertIn("✓ ripgrep present", out)
        self.assertIn("! fd missing", out)
        self.assertIn("✗ config missing", out)
        self.assertIn("fix: install fd", out)
        self.assertIn("Summary: 1 errors, 1 warnings, 1 ok", out)

    def test_human_omits_fix_for_ok(self):
        out = render_human("doctor", "darwin", _findings())
        # The OK line has no "fix:" immediately associated; fix only appears for warn/error.
        self.assertEqual(out.count("fix:"), 2)

    def test_json_is_machine_readable(self):
        out = render_json("assess", "linux", _findings())
        data = json.loads(out)
        self.assertEqual(data["command"], "assess")
        self.assertEqual(data["os"], "linux")
        self.assertEqual(data["summary"], {"errors": 1, "warnings": 1, "ok": 1})
        self.assertEqual(data["findings"][1]["severity"], "warn")
        self.assertEqual(data["findings"][2]["fix"], "run raven install")


if __name__ == "__main__":
    unittest.main()
