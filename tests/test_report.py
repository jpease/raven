import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from raven_lib.findings import Finding, Severity
from raven_lib.report import render_human, render_json, supports_unicode_marks


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
        self.assertIn("Summary: 1 errors, 1 warnings, 0 info, 1 ok", out)

    def test_human_omits_fix_for_ok(self):
        out = render_human("doctor", "darwin", _findings())
        # The OK line has no "fix:" immediately associated; fix only appears for warn/error.
        self.assertEqual(out.count("fix:"), 2)

    def test_json_is_machine_readable(self):
        out = render_json("assess", "linux", _findings())
        data = json.loads(out)
        self.assertEqual(data["command"], "assess")
        self.assertEqual(data["os"], "linux")
        self.assertEqual(data["summary"], {"errors": 1, "warnings": 1, "info": 0, "ok": 1})
        self.assertEqual(data["findings"][1]["severity"], "warn")
        self.assertEqual(data["findings"][2]["fix"], "run raven install")

    def test_human_ascii_marks_fallback_avoids_unicode(self):
        out = render_human("doctor", "darwin", _findings(), ascii_marks=True)
        self.assertIn("ok ripgrep present", out)
        self.assertIn("! fd missing", out)
        self.assertIn("x config missing", out)
        # No non-ASCII characters should appear anywhere in the output.
        out.encode("ascii")


class SupportsUnicodeMarksTests(unittest.TestCase):
    def test_utf8_supports_marks(self):
        self.assertTrue(supports_unicode_marks("utf-8"))

    def test_legacy_codepage_does_not_support_marks(self):
        self.assertFalse(supports_unicode_marks("cp1252"))

    def test_missing_encoding_assumes_no_support(self):
        self.assertFalse(supports_unicode_marks(None))

    def test_unknown_encoding_assumes_no_support(self):
        self.assertFalse(supports_unicode_marks("not-a-real-codec"))


if __name__ == "__main__":
    unittest.main()
