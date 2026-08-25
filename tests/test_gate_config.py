"""Unit tests for `raven_lib.gate_config`: config parsing, relaxation, and gutting.

The parser is deliberately not a TOML implementation (Raven's runtime imports
on Python 3.9, which has no `tomllib`), so these tests pin the subset it does
claim: table headers, scalars, inline and multi-line arrays, quoted keys, and
comments holding a `#` inside a string. What it cannot read must yield nothing
rather than a wrong answer -- an unreadable key reports the config as fine,
and reporting a healthy config as fine is the safe direction for a check that
blocks commits.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from raven_lib.gate_config import (
    gutting_reasons,
    is_known_config,
    parse_json_config,
    parse_toml_like,
    read_config_text,
    relaxations,
)

PYTHON_TOOLS = ("ruff", "pyright")
PYTHON_RECIPES = ("lint", "fmt-check", "typecheck", "test")
TYPESCRIPT_TOOLS = ("npx",)
TYPESCRIPT_RECIPES = ("lint", "fmt-check", "typecheck", "test")
RUST_TOOLS = ("cargo",)
RUST_RECIPES = ("lint", "fmt-check", "typecheck", "test")


class ParseTomlLikeTests(unittest.TestCase):
    def test_sections_scalars_and_inline_arrays(self):
        settings = parse_toml_like(
            '[tool.ruff.lint]\nselect = ["B", "F"]\nline-length = 100\nstrict = true\n'
        )
        self.assertEqual(settings["tool.ruff.lint.select"], ["B", "F"])
        self.assertEqual(settings["tool.ruff.lint.line-length"], "100")
        self.assertEqual(settings["tool.ruff.lint.strict"], "true")

    def test_multi_line_array(self):
        settings = parse_toml_like('[lint]\nselect = [\n    "B",\n    "F",  # comment\n]\n')
        self.assertEqual(settings["lint.select"], ["B", "F"])

    def test_quoted_key_holding_a_glob(self):
        settings = parse_toml_like('[tool.ruff.lint.per-file-ignores]\n"tests/*.py" = ["D103"]\n')
        self.assertEqual(settings["tool.ruff.lint.per-file-ignores.tests/*.py"], ["D103"])

    def test_a_hash_inside_a_string_is_not_a_comment(self):
        settings = parse_toml_like('[tool.mypy]\nexclude = ["a#b"]\n')
        self.assertEqual(settings["tool.mypy.exclude"], ["a#b"])

    def test_a_trailing_comment_is_dropped(self):
        settings = parse_toml_like("[tool.ruff]\nline-length = 100  # house style\n")
        self.assertEqual(settings["tool.ruff.line-length"], "100")

    def test_unparseable_content_yields_nothing_rather_than_a_guess(self):
        self.assertEqual(parse_toml_like("this is not a config at all\n"), {})


class ParseJsonConfigTests(unittest.TestCase):
    def test_nested_keys_flatten(self):
        settings = parse_json_config('{"typeCheckingMode": "strict", "exclude": ["build"]}')
        self.assertEqual(settings["typeCheckingMode"], "strict")
        self.assertEqual(settings["exclude"], ["build"])

    def test_booleans_render_as_toml_spelling(self):
        self.assertEqual(parse_json_config('{"reportAny": true}')["reportAny"], "true")

    def test_malformed_json_yields_nothing(self):
        self.assertEqual(parse_json_config("{not json"), {})


class NormalizationTests(unittest.TestCase):
    def test_pyproject_and_ruff_toml_land_on_the_same_key(self):
        from_pyproject = read_config_text('[tool.ruff.lint]\nignore = ["E501"]\n', "pyproject.toml")
        from_ruff_toml = read_config_text('[lint]\nignore = ["E501"]\n', "ruff.toml")
        self.assertEqual(from_pyproject["ruff.lint.ignore"], from_ruff_toml["ruff.lint.ignore"])

    def test_pyrightconfig_keys_are_namespaced(self):
        settings = read_config_text('{"typeCheckingMode": "off"}', "pyrightconfig.json")
        self.assertEqual(settings["pyright.typeCheckingMode"], "off")

    def test_a_nested_path_still_resolves_the_file_name(self):
        self.assertTrue(is_known_config("sub/project/pyproject.toml"))
        self.assertFalse(is_known_config("package.json"))

    def test_tsconfig_and_cargo_toml_are_known_configs(self):
        # #245
        self.assertTrue(is_known_config("tsconfig.json"))
        self.assertTrue(is_known_config("sub/project/tsconfig.json"))
        self.assertTrue(is_known_config("Cargo.toml"))
        self.assertTrue(is_known_config("sub/project/Cargo.toml"))

    def test_tsconfig_compiler_options_are_namespaced(self):
        settings = read_config_text('{"compilerOptions": {"strict": true}}', "tsconfig.json")
        self.assertEqual(settings["tsconfig.compilerOptions.strict"], "true")

    def test_cargo_toml_lints_need_no_prefix(self):
        settings = read_config_text('[lints.clippy]\nall = "warn"\n', "Cargo.toml")
        self.assertEqual(settings["lints.clippy.all"], "warn")

    def test_an_unknown_config_name_parses_to_nothing(self):
        self.assertEqual(read_config_text("[lint]\nignore = []\n", ".eslintrc"), {})


class RelaxationTests(unittest.TestCase):
    def _pair(self, before: str, after: str):
        return relaxations(
            read_config_text(before, "pyproject.toml"), read_config_text(after, "pyproject.toml")
        )

    def test_widening_ignore_reports_the_added_code(self):
        found = self._pair(
            '[tool.ruff.lint]\nignore = ["D203"]\n', '[tool.ruff.lint]\nignore = ["D203", "B008"]\n'
        )
        self.assertEqual(len(found), 1)
        self.assertIn("B008", found[0][1])

    def test_narrowing_ignore_reports_nothing(self):
        found = self._pair(
            '[tool.ruff.lint]\nignore = ["D203", "B008"]\n', '[tool.ruff.lint]\nignore = ["D203"]\n'
        )
        self.assertEqual(found, [])

    def test_adding_to_select_reports_nothing(self):
        found = self._pair(
            '[tool.ruff.lint]\nselect = ["B"]\n', '[tool.ruff.lint]\nselect = ["B", "F"]\n'
        )
        self.assertEqual(found, [])

    def test_dropping_from_select_reports_the_lost_rule(self):
        found = self._pair(
            '[tool.ruff.lint]\nselect = ["B", "F"]\n', '[tool.ruff.lint]\nselect = ["B"]\n'
        )
        self.assertEqual(len(found), 1)
        self.assertIn("F", found[0][1])

    def test_reordering_a_list_reports_nothing(self):
        found = self._pair(
            '[tool.ruff.lint]\nselect = ["B", "F"]\n', '[tool.ruff.lint]\nselect = ["F", "B"]\n'
        )
        self.assertEqual(found, [])

    def test_lowering_type_checking_mode_reports(self):
        found = self._pair(
            '[tool.pyright]\ntypeCheckingMode = "strict"\n',
            '[tool.pyright]\ntypeCheckingMode = "standard"\n',
        )
        self.assertEqual(len(found), 1)
        self.assertIn("lowers", found[0][1])

    def test_raising_type_checking_mode_reports_nothing(self):
        found = self._pair(
            '[tool.pyright]\ntypeCheckingMode = "basic"\n',
            '[tool.pyright]\ntypeCheckingMode = "strict"\n',
        )
        self.assertEqual(found, [])

    def test_turning_off_a_pyright_report_rule_reports(self):
        found = self._pair(
            "[tool.pyright]\nreportUnnecessaryTypeIgnoreComment = true\n",
            "[tool.pyright]\nreportUnnecessaryTypeIgnoreComment = false\n",
        )
        self.assertEqual(len(found), 1)

    def test_turning_on_a_pyright_report_rule_reports_nothing(self):
        found = self._pair(
            "[tool.pyright]\nreportUnnecessaryTypeIgnoreComment = false\n",
            "[tool.pyright]\nreportUnnecessaryTypeIgnoreComment = true\n",
        )
        self.assertEqual(found, [])

    def test_turning_off_a_mypy_strictness_flag_reports(self):
        found = relaxations(
            read_config_text("[mypy]\nwarn_unused_ignores = true\n", "mypy.ini"),
            read_config_text("[mypy]\nwarn_unused_ignores = false\n", "mypy.ini"),
        )
        self.assertEqual(len(found), 1)

    def test_turning_on_mypy_ignore_errors_reports(self):
        found = relaxations(
            read_config_text("[mypy]\nstrict = true\n", "mypy.ini"),
            read_config_text("[mypy]\nstrict = true\nignore_errors = true\n", "mypy.ini"),
        )
        self.assertEqual(len(found), 1)
        self.assertIn("ignore_errors", found[0][0])

    def test_an_unrelated_setting_reports_nothing(self):
        found = self._pair("[tool.ruff]\nline-length = 100\n", "[tool.ruff]\nline-length = 120\n")
        self.assertEqual(found, [])


class TsconfigAndCargoRelaxationTests(unittest.TestCase):
    """#245: tsconfig.json's strict flags and Cargo.toml's lint levels."""

    def _tsconfig_pair(self, before: str, after: str):
        return relaxations(
            read_config_text(before, "tsconfig.json"), read_config_text(after, "tsconfig.json")
        )

    def _cargo_pair(self, before: str, after: str):
        return relaxations(
            read_config_text(before, "Cargo.toml"), read_config_text(after, "Cargo.toml")
        )

    def test_turning_off_strict_reports(self):
        found = self._tsconfig_pair(
            '{"compilerOptions": {"strict": true}}', '{"compilerOptions": {"strict": false}}'
        )
        self.assertEqual(len(found), 1)
        self.assertIn("turns off", found[0][1])

    def test_turning_on_strict_reports_nothing(self):
        found = self._tsconfig_pair(
            '{"compilerOptions": {"strict": false}}', '{"compilerOptions": {"strict": true}}'
        )
        self.assertEqual(found, [])

    def test_turning_off_no_implicit_any_reports(self):
        found = self._tsconfig_pair(
            '{"compilerOptions": {"noImplicitAny": true}}',
            '{"compilerOptions": {"noImplicitAny": false}}',
        )
        self.assertEqual(len(found), 1)

    def test_turning_off_strict_null_checks_reports(self):
        found = self._tsconfig_pair(
            '{"compilerOptions": {"strictNullChecks": true}}',
            '{"compilerOptions": {"strictNullChecks": false}}',
        )
        self.assertEqual(len(found), 1)

    def test_an_unrelated_tsconfig_setting_reports_nothing(self):
        found = self._tsconfig_pair(
            '{"compilerOptions": {"target": "ES2020"}}', '{"compilerOptions": {"target": "ES2022"}}'
        )
        self.assertEqual(found, [])

    def test_moving_a_clippy_lint_from_deny_to_warn_reports(self):
        found = self._cargo_pair('[lints.clippy]\nall = "deny"\n', '[lints.clippy]\nall = "warn"\n')
        self.assertEqual(len(found), 1)
        self.assertIn("lowers", found[0][1])

    def test_moving_a_clippy_lint_from_deny_to_allow_reports(self):
        found = self._cargo_pair(
            '[lints.clippy]\nall = "deny"\n', '[lints.clippy]\nall = "allow"\n'
        )
        self.assertEqual(len(found), 1)

    def test_moving_a_rust_lint_from_warn_to_deny_reports_nothing(self):
        # Tightening -- the same direction ruff's select/ignore never reports.
        found = self._cargo_pair(
            '[lints.rust]\nunused = "warn"\n', '[lints.rust]\nunused = "deny"\n'
        )
        self.assertEqual(found, [])

    def test_an_unrelated_cargo_setting_reports_nothing(self):
        found = self._cargo_pair('[package]\nversion = "0.1.0"\n', '[package]\nversion = "0.2.0"\n')
        self.assertEqual(found, [])


class GuttingReasonTests(unittest.TestCase):
    def _reasons(self, text: str, name: str = "pyproject.toml"):
        return gutting_reasons(read_config_text(text, name), PYTHON_TOOLS, PYTHON_RECIPES)

    def test_a_healthy_config_reports_nothing(self):
        self.assertEqual(
            self._reasons(
                '[tool.ruff.lint]\nselect = ["B", "D"]\nignore = ["D203"]\n'
                '\n[tool.pyright]\ntypeCheckingMode = "standard"\n'
            ),
            [],
        )

    def test_selecting_a_family_and_ignoring_all_of_it_reports(self):
        reasons = self._reasons('[tool.ruff.lint]\nselect = ["B", "F"]\nignore = ["B"]\n')
        self.assertEqual([r[0] for r in reasons], ["ruff.cancelled"])
        self.assertIn("B", reasons[0][2])

    def test_ignoring_all_reports(self):
        reasons = self._reasons('[tool.ruff.lint]\nselect = ["B"]\nignore = ["ALL"]\n')
        self.assertIn("ruff.ignore-all", [r[0] for r in reasons])

    def test_a_project_wide_per_file_ignore_reports(self):
        reasons = self._reasons(
            '[tool.ruff.lint]\nselect = ["B"]\n[tool.ruff.lint.per-file-ignores]\n"*" = ["B008"]\n'
        )
        self.assertIn("ruff.per-file-ignores", [r[0] for r in reasons])

    def test_a_scoped_per_file_ignore_reports_nothing(self):
        reasons = self._reasons(
            '[tool.ruff.lint]\nselect = ["D"]\n'
            '[tool.ruff.lint.per-file-ignores]\n"tests/*.py" = ["D103"]\n'
        )
        self.assertEqual(reasons, [])

    def test_excluding_the_whole_tree_reports(self):
        reasons = self._reasons('[tool.ruff]\nexclude = ["."]\n[tool.ruff.lint]\nselect = ["B"]\n')
        self.assertIn("ruff.exclude", [r[0] for r in reasons])

    def test_type_check_mode_below_the_template_floor_reports(self):
        reasons = self._reasons('[tool.pyright]\ntypeCheckingMode = "basic"\n')
        self.assertIn("pyright.mode", [r[0] for r in reasons])

    def test_strict_mode_reports_nothing(self):
        reasons = self._reasons('[tool.pyright]\ntypeCheckingMode = "strict"\n')
        self.assertEqual(reasons, [])

    def test_mypy_ignore_errors_reports(self):
        reasons = gutting_reasons(
            read_config_text("[mypy]\nignore_errors = true\n", "mypy.ini"),
            PYTHON_TOOLS,
            PYTHON_RECIPES,
        )
        self.assertIn("mypy.ignore-errors", [r[0] for r in reasons])

    def test_a_template_declaring_no_lint_recipe_is_not_graded_on_lint_config(self):
        # A gate spec drives what gets judged: `gutting_reasons` must never
        # tell a template its lint config is too permissive when the template
        # declares no lint gate at all.
        reasons = gutting_reasons(
            read_config_text(
                '[tool.ruff.lint]\nselect = ["B"]\nignore = ["B"]\n', "pyproject.toml"
            ),
            ("ruff",),
            ("test",),
        )
        self.assertEqual(reasons, [])

    def test_a_narrower_ignore_than_the_selection_reports_nothing(self):
        # This repository's own shape: `select = ["D"]` with the style-only
        # `D203`/`D401` ignored. Scoping inside a family is not gutting it.
        reasons = self._reasons(
            '[tool.ruff.lint]\nselect = ["D"]\nignore = ["D203", "D401"]\n',
        )
        self.assertEqual(reasons, [])


class TsconfigAndCargoGuttingReasonTests(unittest.TestCase):
    """#245: the standing-state judgment `raven assess` reports."""

    def test_a_healthy_tsconfig_reports_nothing(self):
        reasons = gutting_reasons(
            read_config_text(
                '{"compilerOptions": {"strict": true, "noImplicitAny": true, '
                '"strictNullChecks": true}}',
                "tsconfig.json",
            ),
            TYPESCRIPT_TOOLS,
            TYPESCRIPT_RECIPES,
        )
        self.assertEqual(reasons, [])

    def test_strict_false_reports(self):
        reasons = gutting_reasons(
            read_config_text('{"compilerOptions": {"strict": false}}', "tsconfig.json"),
            TYPESCRIPT_TOOLS,
            TYPESCRIPT_RECIPES,
        )
        self.assertEqual([r[0] for r in reasons], ["tsconfig.strict"])
        self.assertIn("strict", reasons[0][2])

    def test_no_implicit_any_false_reports_even_with_strict_true(self):
        # TypeScript lets an explicit flag override the `strict` umbrella, so
        # `strict: true` must not mask a `noImplicitAny: false` sitting beside it.
        reasons = gutting_reasons(
            read_config_text(
                '{"compilerOptions": {"strict": true, "noImplicitAny": false}}', "tsconfig.json"
            ),
            TYPESCRIPT_TOOLS,
            TYPESCRIPT_RECIPES,
        )
        self.assertEqual([r[0] for r in reasons], ["tsconfig.strict"])
        self.assertIn("noImplicitAny", reasons[0][2])

    def test_a_template_declaring_no_typecheck_recipe_is_not_graded_on_tsconfig(self):
        reasons = gutting_reasons(
            read_config_text('{"compilerOptions": {"strict": false}}', "tsconfig.json"),
            TYPESCRIPT_TOOLS,
            ("lint",),
        )
        self.assertEqual(reasons, [])

    def test_a_healthy_cargo_toml_reports_nothing(self):
        reasons = gutting_reasons(
            read_config_text('[lints.clippy]\nall = "warn"\n', "Cargo.toml"),
            RUST_TOOLS,
            RUST_RECIPES,
        )
        self.assertEqual(reasons, [])

    def test_clippy_all_set_to_allow_reports(self):
        reasons = gutting_reasons(
            read_config_text('[lints.clippy]\nall = "allow"\n', "Cargo.toml"),
            RUST_TOOLS,
            RUST_RECIPES,
        )
        self.assertEqual([r[0] for r in reasons], ["cargo.lints-allow-all"])
        self.assertIn("clippy.all", reasons[0][2])

    def test_a_single_clippy_lint_set_to_allow_reports_nothing(self):
        # Allowing one specific lint is an ordinary, scoped choice -- not the
        # whole-family shape `clippy::all`/`warnings` set to `allow` is.
        reasons = gutting_reasons(
            read_config_text('[lints.clippy]\nmodule_name_repetitions = "allow"\n', "Cargo.toml"),
            RUST_TOOLS,
            RUST_RECIPES,
        )
        self.assertEqual(reasons, [])

    def test_rust_warnings_set_to_allow_reports(self):
        reasons = gutting_reasons(
            read_config_text('[lints.rust]\nwarnings = "allow"\n', "Cargo.toml"),
            RUST_TOOLS,
            RUST_RECIPES,
        )
        self.assertEqual([r[0] for r in reasons], ["cargo.lints-allow-all"])

    def test_a_template_declaring_no_lint_recipe_is_not_graded_on_cargo_toml(self):
        reasons = gutting_reasons(
            read_config_text('[lints.clippy]\nall = "allow"\n', "Cargo.toml"), RUST_TOOLS, ("test",)
        )
        self.assertEqual(reasons, [])


if __name__ == "__main__":
    unittest.main()


class ShippedTemplateConfigTests(unittest.TestCase):
    """The configs Raven ships must pass the check Raven ships.

    A template whose own `pyproject.toml` tripped `gutting_reasons` would put
    every project installed from it into a warning state on day one.
    """

    def test_every_template_pyproject_passes_its_own_gate_spec(self):
        from raven_lib.gates import load_gate_specs

        repo_root = Path(__file__).resolve().parents[1]
        checked = 0
        for name, spec in load_gate_specs().items():
            pyproject = repo_root / name / "pyproject.toml"
            if not pyproject.is_file():
                continue
            checked += 1
            settings = read_config_text(pyproject.read_text(encoding="utf-8"), "pyproject.toml")
            self.assertEqual(
                gutting_reasons(settings, spec.tools, spec.recipes),
                [],
                f"{name}/pyproject.toml disables the substance of a gate it declares",
            )
        self.assertGreater(checked, 0, "no template pyproject.toml was found to check")

    def test_this_repositorys_own_config_passes(self):
        from raven_lib.gate_config import read_project_settings
        from raven_lib.gates import gate_spec_for

        repo_root = Path(__file__).resolve().parents[1]
        spec = gate_spec_for("python")
        assert spec is not None
        self.assertEqual(
            gutting_reasons(read_project_settings(repo_root), spec.tools, spec.recipes), []
        )


class NewlyPinnedLooseSettingTests(unittest.TestCase):
    """A setting that was never declared and now pins the gate off (issue #229)."""

    def _pair(self, before: str, after: str):
        return relaxations(
            read_config_text(before, "pyproject.toml"), read_config_text(after, "pyproject.toml")
        )

    def test_newly_disabling_a_pyright_report_rule_reports(self):
        found = self._pair(
            '[tool.pyright]\ntypeCheckingMode = "standard"\n',
            '[tool.pyright]\ntypeCheckingMode = "standard"\nreportMissingImports = false\n',
        )
        self.assertEqual(len(found), 1)
        self.assertIn("loosest", found[0][1])

    def test_newly_enabling_a_pyright_report_rule_reports_nothing(self):
        found = self._pair(
            '[tool.pyright]\ntypeCheckingMode = "standard"\n',
            '[tool.pyright]\ntypeCheckingMode = "standard"\nreportMissingImports = true\n',
        )
        self.assertEqual(found, [])

    def test_a_fresh_config_declaring_a_middle_value_reports_nothing(self):
        found = self._pair("", '[tool.pyright]\ntypeCheckingMode = "standard"\n')
        self.assertEqual(found, [])

    def test_a_fresh_config_declaring_the_loosest_value_reports(self):
        found = self._pair("", '[tool.pyright]\ntypeCheckingMode = "off"\n')
        self.assertEqual(len(found), 1)
