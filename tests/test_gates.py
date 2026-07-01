import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from raven_lib.gates import GateSpec, gate_spec_for, load_gate_specs


class GatesTests(unittest.TestCase):
    def test_python_gate_spec_present(self):
        specs = load_gate_specs()
        self.assertIn("python", specs)
        spec = specs["python"]
        self.assertIsInstance(spec, GateSpec)

    def test_python_recipes_match_justfile(self):
        spec = gate_spec_for("python")
        assert spec is not None
        for recipe in ("lint", "fmt-check", "typecheck", "test"):
            self.assertIn(recipe, spec.recipes)

    def test_python_detect_signals_include_pyproject(self):
        spec = gate_spec_for("python")
        assert spec is not None
        self.assertIn("pyproject.toml", spec.detect_signals)

    def test_python_fallback_for_lint_is_ruff(self):
        spec = gate_spec_for("python")
        assert spec is not None
        self.assertEqual(spec.fallback_commands["lint"], ("ruff", "check", "."))

    def test_swift_recipes_include_lint_format(self):
        # Issue #53 — the Swift template's `check` runs `lint-format`, so the gate
        # spec must declare it alongside lint/build/test.
        spec = gate_spec_for("swift")
        assert spec is not None
        for recipe in ("lint-format", "lint", "build", "test"):
            self.assertIn(recipe, spec.recipes)

    def test_swift_lint_format_fallback_runs_swift_format(self):
        spec = gate_spec_for("swift")
        assert spec is not None
        fallback = spec.fallback_commands["lint-format"]
        self.assertEqual(fallback[:3], ("xcrun", "swift-format", "lint"))

    def test_swift_tools_account_for_xcrun(self):
        # swift-format is reached via `xcrun`, so that is the probeable executable.
        spec = gate_spec_for("swift")
        assert spec is not None
        self.assertIn("xcrun", spec.tools)

    def test_swift_detect_signals_cover_package_and_xcode_app(self):
        # #60: the swift template serves SwiftPM packages (Package.swift) and Xcode
        # app targets (project.yml/xcodegen), so both must register as a fit.
        spec = gate_spec_for("swift")
        assert spec is not None
        self.assertIn("Package.swift", spec.detect_signals)
        self.assertIn("project.yml", spec.detect_signals)

    def test_swift_justfile_build_and_test_dispatch_on_package_swift(self):
        # #60: build/test must dispatch between `swift` (SwiftPM) and `xcodebuild`
        # (Xcode app), and the push gate (`check`) must not run the heavy test.
        repo_root = Path(__file__).resolve().parents[1]
        text = (repo_root / "swift" / "justfile").read_text(encoding="utf-8")
        self.assertIn("Package.swift", text)
        self.assertIn("swift build", text)
        self.assertIn("swift test", text)
        self.assertIn("xcodebuild", text)
        self.assertIn('SCHEME := "YourScheme"', text)
        check_line = next(line for line in text.splitlines() if line.startswith("check:"))
        self.assertEqual(check_line.strip(), "check: check-fast build")

    def test_unknown_template_returns_none(self):
        self.assertIsNone(gate_spec_for("cobol"))


if __name__ == "__main__":
    unittest.main()
