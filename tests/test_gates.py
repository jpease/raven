import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from raven_lib import list_language_templates
from raven_lib.gates import GateSpec, gate_spec_for, load_gate_specs, recipe_present


class GatesTests(unittest.TestCase):
    def test_python_gate_spec_present(self):
        specs = load_gate_specs()
        self.assertIn("python", specs)
        spec = specs["python"]
        self.assertIsInstance(spec, GateSpec)

    def test_gate_data_recipes_present_in_justfile(self):
        # #89 -- generalizes the python-only justfile check across every
        # GATE_DATA language, so a recipe rename on one side can't go unnoticed.
        repo_root = Path(__file__).resolve().parents[1]
        for template, spec in load_gate_specs().items():
            with self.subTest(template=template):
                justfile_text = (repo_root / template / "justfile").read_text(encoding="utf-8")
                for recipe in spec.recipes:
                    self.assertTrue(
                        recipe_present(justfile_text, recipe),
                        f"{template}/justfile is missing recipe {recipe!r} declared in GATE_DATA",
                    )

    def test_gate_data_keys_match_shipped_justfiles(self):
        # #89 -- ties GATE_DATA to the shipped justfile set so a new language
        # tree (or a justfile added to dotfiles) can't silently leave `assess`
        # without a gate spec.
        repo_root = Path(__file__).resolve().parents[1]
        templates_with_justfile = {
            name for name in list_language_templates() if (repo_root / name / "justfile").is_file()
        }
        self.assertEqual(templates_with_justfile, set(load_gate_specs().keys()))
        # dotfiles deliberately ships no justfile and therefore no gate spec (v1).
        self.assertNotIn("dotfiles", templates_with_justfile)
        self.assertIsNone(gate_spec_for("dotfiles"))

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
        # spec must declare it alongside lint/build.
        spec = gate_spec_for("swift")
        assert spec is not None
        for recipe in ("lint-format", "lint", "build"):
            self.assertIn(recipe, spec.recipes)

    def test_swift_recipes_exclude_test(self):
        # Issue #62 — `swift/justfile`'s `check` is `check-fast build` (test is
        # deliberately excluded; UI tests are too heavy for every push), so the
        # spec must not require `test` either.
        spec = gate_spec_for("swift")
        assert spec is not None
        self.assertNotIn("test", spec.recipes)

    def test_rust_recipes_include_fmt_check(self):
        # Issue #62 — `rust/justfile`'s `check-fast` runs `fmt-check`, so the
        # spec must require it like any other gate recipe.
        spec = gate_spec_for("rust")
        assert spec is not None
        self.assertIn("fmt-check", spec.recipes)

    def test_rust_fmt_check_fallback_is_cargo_fmt(self):
        spec = gate_spec_for("rust")
        assert spec is not None
        self.assertEqual(spec.fallback_commands["fmt-check"], ("cargo", "fmt", "--check"))

    def test_typescript_recipes_include_fmt_check(self):
        # Issue #62 — `typescript/justfile`'s `check-fast` runs `fmt-check`, so
        # the spec must require it like any other gate recipe.
        spec = gate_spec_for("typescript")
        assert spec is not None
        self.assertIn("fmt-check", spec.recipes)

    def test_typescript_fmt_check_fallback_is_prettier(self):
        spec = gate_spec_for("typescript")
        assert spec is not None
        self.assertEqual(spec.fallback_commands["fmt-check"], ("npx", "prettier", "--check", "."))

    def test_elixir_recipes_include_fmt_check(self):
        # Issue #62 — `elixir/justfile`'s `check-fast` runs `fmt-check`, so the
        # spec must require it like any other gate recipe.
        spec = gate_spec_for("elixir")
        assert spec is not None
        self.assertIn("fmt-check", spec.recipes)

    def test_elixir_fmt_check_fallback_is_mix_format(self):
        spec = gate_spec_for("elixir")
        assert spec is not None
        self.assertEqual(
            spec.fallback_commands["fmt-check"], ("mix", "format", "--check-formatted")
        )

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
        # The scheme is resolved at runtime (no XcodeGen assumption, no
        # placeholder to fill in); a fresh repo with no build system skips
        # build/test cleanly instead of failing the push gate.
        self.assertNotIn("YourScheme", text)
        self.assertIn("_scheme:", text)
        self.assertIn("$SCHEME", text)
        self.assertIn("skipping build", text)
        # The destination is resolved per-scheme, not hardcoded to iPhone/iOS --
        # an Xcode scheme may target macOS, tvOS, watchOS, or visionOS, so a
        # hardcoded iOS-Simulator destination would break the build gate for
        # every non-iOS project.
        self.assertNotIn("iPhone 16", text)
        self.assertIn("_destination", text)
        self.assertIn("-showdestinations", text)
        self.assertIn("$DESTINATION", text)
        check_line = next(line for line in text.splitlines() if line.startswith("check:"))
        self.assertEqual(check_line.strip(), "check: check-fast build")

    def test_unknown_template_returns_none(self):
        self.assertIsNone(gate_spec_for("cobol"))


# osv-scanner supports no manifest for these ecosystems (no Package.resolved,
# no LuaRocks rockspec), so their `audit` recipe reports the gap instead.
_NO_SCANNER_INPUT = frozenset({"swift", "lua"})


class AuditRecipeTests(unittest.TestCase):
    """#135 -- `audit` is a uniform reporting recipe, never a gate.

    It exists in every shipped justfile so `just audit` means the same thing
    everywhere, and it is excluded from `check` (and from GATE_DATA) because
    its findings vary with time rather than with the working tree.
    """

    repo_root = Path(__file__).resolve().parents[1]

    def _justfiles(self) -> dict[str, str]:
        return {
            name: (self.repo_root / name / "justfile").read_text(encoding="utf-8")
            for name in load_gate_specs()
        }

    def test_every_shipped_justfile_declares_audit(self):
        for template, text in self._justfiles().items():
            with self.subTest(template=template):
                self.assertTrue(
                    recipe_present(text, "audit"),
                    f"{template}/justfile is missing the `audit` recipe",
                )

    def test_audit_is_not_a_graded_gate_recipe(self):
        # An audit is not reproducible from the tree, so `assess` must not grade
        # it. Keeping it out of GATE_DATA is what makes that explicit.
        for template, spec in load_gate_specs().items():
            with self.subTest(template=template):
                self.assertNotIn("audit", spec.recipes)
                self.assertNotIn("audit", spec.fallback_commands)

    def test_audit_is_not_reachable_from_check(self):
        # `check` and `check-fast` are the gate chains (pre-push and pre-commit).
        # Neither may depend on `audit`, directly or through the other.
        for template, text in self._justfiles().items():
            with self.subTest(template=template):
                for gate in ("check", "check-fast"):
                    line = next(line for line in text.splitlines() if line.startswith(f"{gate}:"))
                    self.assertNotIn("audit", line.split(":", 1)[1].split())

    def test_scanning_templates_invoke_osv_scanner_without_failing_the_shell(self):
        # osv-scanner exits non-zero when it finds advisories; the recipe must
        # absorb that, or chaining it anywhere would make it a blocking gate.
        for template, text in self._justfiles().items():
            if template in _NO_SCANNER_INPUT:
                continue
            with self.subTest(template=template):
                self.assertIn("osv-scanner scan source -r .", text)
                self.assertIn("command -v osv-scanner", text)
                audit_body = text.split("\naudit:", 1)[1]
                self.assertIn("exit 0", audit_body)

    def test_templates_without_scanner_input_say_so(self):
        # Shipping a recipe that silently finds nothing is worse than shipping
        # none: it reads as "audited, clean". These must name the gap instead.
        for template in _NO_SCANNER_INPUT:
            with self.subTest(template=template):
                text = (self.repo_root / template / "justfile").read_text(encoding="utf-8")
                audit_body = text.split("\naudit:", 1)[1]
                self.assertNotIn("osv-scanner scan", audit_body)
                self.assertIn("NOT covered by 'just audit'", audit_body)


class RecipePresentTests(unittest.TestCase):
    def test_matches_plain_recipe(self):
        self.assertTrue(recipe_present("test:\n    pytest\n", "test"))

    def test_matches_recipe_with_dependencies(self):
        self.assertTrue(recipe_present("check: lint test\n", "check"))

    def test_matches_parameterized_recipe(self):
        # Issue #85 — `test *ARGS:` was missed by the old startswith("test:") check.
        self.assertTrue(recipe_present("test *ARGS:\n    pytest {{ARGS}}\n", "test"))

    def test_matches_quiet_recipe(self):
        # Issue #85 — `@check:` was missed by the old startswith("check:") check.
        self.assertTrue(recipe_present("@check:\n    just lint\n", "check"))

    def test_matches_quiet_parameterized_recipe(self):
        self.assertTrue(recipe_present("@test *ARGS:\n    pytest {{ARGS}}\n", "test"))

    def test_excludes_colon_equals_assignment(self):
        # Issue #85 — `test:="x"` false-positive matched startswith("test:").
        self.assertFalse(recipe_present('test:="x"\n', "test"))

    def test_excludes_colon_equals_assignment_with_space(self):
        self.assertFalse(recipe_present('test := "x"\n', "test"))

    def test_excludes_prefixed_recipe_name(self):
        self.assertFalse(recipe_present("test-unit:\n    pytest\n", "test"))

    def test_missing_recipe_returns_false(self):
        self.assertFalse(recipe_present("lint:\n    ruff check .\n", "test"))


if __name__ == "__main__":
    unittest.main()
