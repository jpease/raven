from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path
from typing import ClassVar
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from helpers import REPO_ROOT, RavenTestCase
from raven_lib.assess import (
    _invokes_just_recipe,
    _recipe_graph,
    _recipes_reachable_from,
    build_assess_findings,
    template_fit_findings,
    wiring_findings,
)
from raven_lib.findings import Severity
from raven_lib.gates import load_gate_specs, recipe_present


class InvokesJustRecipeTests(unittest.TestCase):
    """Unit tests for `_invokes_just_recipe` directly (issue #108).

    Shell quoting doesn't change the argument `just` receives, so `just "check"`
    and `just 'check'` must be recognized the same as `just check`. Conversely,
    the recipe name appearing in a comment, an echo/printf argument, or as a
    longer recipe (`check-fast`) must never count as actually running `check`.
    """

    ACCEPT_CASES: ClassVar[list[tuple[str, str]]] = [
        ("plain", "just check\n"),
        ("double-quoted recipe", 'just "check"\n'),
        ("single-quoted recipe", "just 'check'\n"),
        ("leading env assignment", "RAVEN=1 just check\n"),
        ("exec wrapper", "exec just check\n"),
        ("trailing flag", "just check --verbose\n"),
        ("preceded by another command", "lint && just check\n"),
    ]

    REJECT_CASES: ClassVar[list[tuple[str, str]]] = [
        ("commented out", "# just check\n"),
        ("echoed double-quoted", 'echo "just check"\n'),
        ("echoed unquoted", "echo just check\n"),
        ("printf'd", "printf 'just check'\n"),
        ("longer recipe check-fast", "just check-fast\n"),
        ("longer recipe check-full", "just check-full\n"),
        ("empty", ""),
        ("unrelated command", "exit 0\n"),
    ]

    def test_accepts_real_just_check_invocations(self):
        for label, text in self.ACCEPT_CASES:
            with self.subTest(label):
                self.assertTrue(
                    _invokes_just_recipe(text, "check"),
                    f"expected {text!r} to be recognized as running `just check`",
                )

    def test_rejects_non_invocations_of_check(self):
        for label, text in self.REJECT_CASES:
            with self.subTest(label):
                self.assertFalse(
                    _invokes_just_recipe(text, "check"),
                    f"expected {text!r} to NOT be recognized as running `just check`",
                )

    def test_recognizes_check_fast_recipe_for_the_fast_subset_path(self):
        # The pre-push fast-subset warning path checks the recipe "check-fast"
        # directly; it must still be recognized when actually invoked.
        self.assertTrue(_invokes_just_recipe("just check-fast\n", "check-fast"))
        self.assertFalse(_invokes_just_recipe("just check\n", "check-fast"))


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

    def test_swift_missing_lint_format_recipe_warns(self):
        # Issue #53 — a Swift justfile without `lint-format` is missing the
        # format gate the template treats as standard verification.
        (self.destination / ".raven").mkdir()
        (self.destination / ".raven" / "config.toml").write_text(
            'schema = 1\ntemplate = "swift"\n', encoding="utf-8"
        )
        (self.destination / "justfile").write_text(
            "lint:\n    swiftlint lint\nbuild:\n    swift build\ntest:\n    swift test\n",
            encoding="utf-8",
        )
        findings = wiring_findings(self.destination)
        ids = {f.id: f for f in findings}
        self.assertEqual(ids["assess.wiring.recipe.lint-format"].severity, Severity.WARN)
        self.assertEqual(ids["assess.wiring.recipe.lint"].severity, Severity.OK)

    def test_unsupported_template_is_error_not_warn(self):
        # Issue #50 — wiring_findings must emit ERROR (not WARN) when the
        # template is explicitly set to an unsupported name.
        (self.destination / ".raven").mkdir()
        (self.destination / ".raven" / "config.toml").write_text(
            'schema = 1\ntemplate = "bogus"\n', encoding="utf-8"
        )
        findings = wiring_findings(self.destination)
        match = next(f for f in findings if f.id == "assess.wiring.template")
        self.assertEqual(match.severity, Severity.ERROR)

    def test_gateless_real_template_is_not_error(self):
        # Issue #191 — `dotfiles` is a real template (per list_language_templates())
        # that ships no gate recipes or tools at all. `gate_spec_for` returning None
        # for it means "no gate expectations", not "unsupported template name", so it
        # must not be graded as an ERROR the way "bogus" above is.
        (self.destination / ".raven").mkdir()
        (self.destination / ".raven" / "config.toml").write_text(
            'schema = 1\ntemplate = "dotfiles"\n', encoding="utf-8"
        )
        findings = wiring_findings(self.destination)
        match = next(f for f in findings if f.id == "assess.wiring.template")
        self.assertEqual(match.severity, Severity.INFO)
        # Nothing else in the wiring section may fail either: dotfiles ships no
        # justfile, so checking for gate recipes/hooks would be spurious.
        self.assertEqual([f for f in findings if f.severity is Severity.ERROR], [])

    def test_no_template_configured_is_warn(self):
        # The third state alongside unsupported (ERROR) and gateless-but-real
        # (INFO): no template set at all is a WARN, not an error.
        (self.destination / ".raven").mkdir()
        (self.destination / ".raven" / "config.toml").write_text("schema = 1\n", encoding="utf-8")
        findings = wiring_findings(self.destination)
        match = next(f for f in findings if f.id == "assess.wiring.template")
        self.assertEqual(match.severity, Severity.WARN)

    def test_invalid_utf8_justfile_emits_error_finding(self):
        # Issue #51 — invalid UTF-8 in justfile must produce a structured
        # ERROR finding, not a Python traceback.
        self._python_config()
        (self.destination / "justfile").write_bytes(b"\xff\xfe invalid utf-8")
        findings = wiring_findings(self.destination)
        match = next(f for f in findings if f.id == "assess.wiring.justfile")
        self.assertEqual(match.severity, Severity.ERROR)

    def test_oserror_justfile_emits_error_finding(self):
        # Issue #51 — an OSError reading justfile must produce ERROR, not traceback.
        self._python_config()
        (self.destination / "justfile").write_text("lint:\n", encoding="utf-8")
        original = Path.read_text

        def fail_for_justfile(self_path: Path, *args, **kwargs):
            if self_path.name == "justfile":
                raise OSError("Permission denied")
            return original(self_path, *args, **kwargs)

        with mock.patch.object(Path, "read_text", fail_for_justfile):
            findings = wiring_findings(self.destination)
        match = next(f for f in findings if f.id == "assess.wiring.justfile")
        self.assertEqual(match.severity, Severity.ERROR)

    def test_invalid_utf8_config_signal_emits_error_finding(self):
        # Issue #51 — invalid UTF-8 in a config signal file must produce
        # ERROR, not traceback.
        self._python_config()
        (self.destination / "justfile").write_text("lint:\n", encoding="utf-8")
        (self.destination / "pyproject.toml").write_bytes(b"\xff\xfe invalid utf-8")
        findings = wiring_findings(self.destination)
        match = next(f for f in findings if f.id == "assess.wiring.config.pyproject.toml")
        self.assertEqual(match.severity, Severity.ERROR)


class RecipeGraphTests(unittest.TestCase):
    """Unit tests for the justfile recipe graph `check` reachability is read from.

    The header pattern is anchored at column 0 because a recipe body line can
    hold a colon; if such a line parsed as a declaration, the recipe it sits in
    would lose the rest of its body and `check` would look like it reaches less
    than it does.
    """

    def test_dependencies_and_body_invocations_both_count(self):
        text = "check: check-fast\n    just test\ncheck-fast: lint\nlint:\n    ruff check .\n"
        self.assertEqual(_recipes_reachable_from(text, "check"), {"check-fast", "lint", "test"})

    def test_absent_root_is_none_not_an_empty_set(self):
        # None ("no `check` recipe") and set() ("`check` runs nothing") are
        # different findings, so the caller must be able to tell them apart.
        self.assertIsNone(_recipes_reachable_from("lint:\n    ruff check .\n", "check"))
        self.assertEqual(_recipes_reachable_from("check:\n    true\n", "check"), set())

    def test_body_colons_and_assignments_are_not_recipe_headers(self):
        text = (
            'set shell := ["bash", "-c"]\n'
            "alias t := test\n"
            "# check: not a recipe\n"
            "check: lint\n"
            '    echo "note: still the check body"\n'
            "    just test\n"
        )
        graph = _recipe_graph(text)
        self.assertEqual(sorted(graph), ["check"])
        self.assertEqual(graph["check"], {"lint", "test"})


class AssessCheckReachTests(RavenTestCase):
    """A declared gate recipe that `just check` never reaches enforces nothing.

    `assess.wiring.recipe.<name>` grades whether a recipe exists; both git hooks
    run `just check`, so existence alone leaves a suite that no commit and no
    push can fail on graded as fully wired.
    """

    def _config(self, template: str) -> None:
        (self.destination / ".raven").mkdir(exist_ok=True)
        (self.destination / ".raven" / "config.toml").write_text(
            f'schema = 1\ntemplate = "{template}"\n', encoding="utf-8"
        )

    def _justfile(self, text: str) -> None:
        (self.destination / "justfile").write_text(text, encoding="utf-8")

    _PYTHON_RECIPES = (
        "lint:\n    ruff check .\n"
        "fmt-check:\n    ruff format --check .\n"
        "typecheck:\n    pyright\n"
        "test:\n    python -m pytest\n"
    )

    def test_every_declared_gate_recipe_reachable_is_ok(self):
        self._config("python")
        self._justfile(
            self._PYTHON_RECIPES + "check-fast: lint fmt-check\ncheck: check-fast typecheck test\n"
        )
        match = next(f for f in wiring_findings(self.destination) if f.id == "assess.wiring.check")
        self.assertEqual(match.severity, Severity.OK)
        self.assertIn("4 of 4", match.title)

    def test_declared_but_ungated_recipe_warns_and_is_named(self):
        self._config("python")
        self._justfile(self._PYTHON_RECIPES + "check-fast: lint fmt-check\ncheck: check-fast\n")
        match = next(f for f in wiring_findings(self.destination) if f.id == "assess.wiring.check")
        self.assertEqual(match.severity, Severity.WARN)
        self.assertIn("2 of 4", match.title)
        self.assertIn("`test`", match.detail)
        self.assertIn("`typecheck`", match.detail)

    def test_missing_check_recipe_warns(self):
        self._config("python")
        self._justfile(self._PYTHON_RECIPES)
        match = next(f for f in wiring_findings(self.destination) if f.id == "assess.wiring.check")
        self.assertEqual(match.severity, Severity.WARN)
        self.assertIn("check", match.title)

    def test_no_justfile_reports_nothing_here(self):
        # `assess.wiring.justfile` already warns; a second finding saying the
        # missing file declares no `check` is noise, not information.
        self._config("python")
        ids = {f.id for f in wiring_findings(self.destination)}
        self.assertNotIn("assess.wiring.check", ids)

    def test_test_excluded_by_the_template_is_info_not_warn(self):
        # The swift template keeps `test` out of `check` deliberately (an Xcode
        # UI suite is too heavy for every push), so the exclusion is reported
        # rather than graded as a defect -- but it is reported.
        self._config("swift")
        self._justfile(
            "lint-format:\n    xcrun swift-format lint .\n"
            "lint:\n    swiftlint lint\n"
            "build:\n    swift build\n"
            "test:\n    swift test\n"
            "check-fast: lint-format lint\ncheck: check-fast build\n"
        )
        ids = {f.id: f for f in wiring_findings(self.destination)}
        self.assertEqual(ids["assess.wiring.check"].severity, Severity.OK)
        self.assertEqual(ids["assess.wiring.check.test"].severity, Severity.INFO)

    def test_gated_test_reports_no_exclusion_finding(self):
        self._config("python")
        self._justfile(
            self._PYTHON_RECIPES + "check-fast: lint fmt-check\ncheck: check-fast typecheck test\n"
        )
        ids = {f.id for f in wiring_findings(self.destination)}
        self.assertNotIn("assess.wiring.check.test", ids)


class ShippedJustfileGateReachTests(unittest.TestCase):
    """Every shipped template must gate the gate recipes it declares.

    This is the check the assess finding performs, run against the templates
    Raven itself ships: a template whose `check` stops reaching `test` would
    otherwise ship a repo whose tests cannot fail a push.
    """

    def test_every_gate_recipe_is_reachable_from_check(self):
        specs = load_gate_specs()
        # A walk that finds nothing passes every per-template assertion below,
        # so the count is asserted against the roster's floor first.
        self.assertGreaterEqual(len(specs), 8, sorted(specs))
        for template, spec in sorted(specs.items()):
            justfile = REPO_ROOT / template / "justfile"
            with self.subTest(template=template):
                self.assertTrue(justfile.is_file(), f"{template} ships no justfile")
                text = justfile.read_text(encoding="utf-8")
                reachable = _recipes_reachable_from(text, "check")
                self.assertIsNotNone(reachable, f"{template}/justfile declares no `check` recipe")
                ungated = [
                    recipe
                    for recipe in spec.recipes
                    if recipe_present(text, recipe) and recipe not in (reachable or set())
                ]
                self.assertEqual(ungated, [], f"{template}: `check` never runs {ungated}")


class AssessHookPathTests(RavenTestCase):
    """Regression for #36: assess inspects Git's effective hooks path."""

    def setUp(self):
        super().setUp()
        # Hooks run with GIT_* exported; strip them so git resolves the temp repo
        # rather than the outer repo (mirrors test_git_hooks setup).
        for var in [k for k in os.environ if k.startswith("GIT_")]:
            self.addCleanup(os.environ.__setitem__, var, os.environ[var])
            del os.environ[var]
        subprocess.run(["git", "init", str(self.destination)], capture_output=True, check=True)
        (self.destination / ".raven").mkdir(exist_ok=True)
        (self.destination / ".raven" / "config.toml").write_text(
            'schema = 1\ntemplate = "python"\n', encoding="utf-8"
        )

    def _hook_finding(self, name="pre-commit"):
        findings = wiring_findings(self.destination)
        return next(f for f in findings if f.id == f"assess.wiring.hook.{name}")

    def test_active_hooks_in_custom_hooks_path_are_ok(self):
        custom = self.destination / ".githooks"
        custom.mkdir()
        subprocess.run(
            ["git", "-C", str(self.destination), "config", "core.hooksPath", ".githooks"],
            capture_output=True,
            check=True,
        )
        (custom / "pre-commit").write_text("#!/bin/sh\njust check-fast\n", encoding="utf-8")
        (custom / "pre-push").write_text("#!/bin/sh\njust check\n", encoding="utf-8")
        pre_commit = self._hook_finding("pre-commit")
        pre_push = self._hook_finding("pre-push")
        self.assertEqual(pre_commit.severity, Severity.OK)
        self.assertIn(".githooks/pre-commit", pre_commit.detail)
        self.assertEqual(pre_push.severity, Severity.OK)
        self.assertIn(".githooks/pre-push", pre_push.detail)

    def test_missing_hooks_in_normal_repo_warn(self):
        pre_commit = self._hook_finding("pre-commit")
        pre_push = self._hook_finding("pre-push")
        self.assertEqual(pre_commit.severity, Severity.WARN)
        self.assertIn(".git/hooks/pre-commit", pre_commit.detail)
        self.assertEqual(pre_push.severity, Severity.WARN)
        self.assertIn(".git/hooks/pre-push", pre_push.detail)

    def test_pre_push_missing_warns_even_when_pre_commit_present(self):
        # The whole point of verifying both: a project wired for commit-time
        # checks but missing the push-time gate must not pass as fully wired.
        hooks = self.destination / ".git" / "hooks"
        hooks.mkdir(parents=True, exist_ok=True)
        (hooks / "pre-commit").write_text("#!/bin/sh\njust check-fast\n", encoding="utf-8")
        self.assertEqual(self._hook_finding("pre-commit").severity, Severity.OK)
        self.assertEqual(self._hook_finding("pre-push").severity, Severity.WARN)

    def test_pre_push_running_only_check_fast_warns(self):
        # Issue #52 — `just check-fast` contains the substring `just check`, so a
        # lenient match graded a fast-only pre-push as the full push gate. The
        # token-aware check must WARN: the slow type-check/test gate is missing.
        hooks = self.destination / ".git" / "hooks"
        hooks.mkdir(parents=True, exist_ok=True)
        (hooks / "pre-commit").write_text("#!/bin/sh\njust check-fast\n", encoding="utf-8")
        (hooks / "pre-push").write_text("#!/bin/sh\njust check-fast\n", encoding="utf-8")
        self.assertEqual(self._hook_finding("pre-commit").severity, Severity.OK)
        self.assertEqual(self._hook_finding("pre-push").severity, Severity.WARN)

    def test_pre_commit_running_full_check_is_still_ok(self):
        # A pre-commit hook customized to run the full `just check` is stricter
        # than the shipped fast hook, so it must still grade as wired.
        hooks = self.destination / ".git" / "hooks"
        hooks.mkdir(parents=True, exist_ok=True)
        (hooks / "pre-commit").write_text("#!/bin/sh\njust check\n", encoding="utf-8")
        self.assertEqual(self._hook_finding("pre-commit").severity, Severity.OK)

    def test_invalid_utf8_hook_emits_error_finding(self):
        # Issue #51 — invalid UTF-8 in a managed hook must produce ERROR,
        # not a UnicodeDecodeError traceback.
        hooks = self.destination / ".git" / "hooks"
        hooks.mkdir(parents=True, exist_ok=True)
        (hooks / "pre-commit").write_bytes(b"\xff\xfe invalid utf-8")
        finding = self._hook_finding("pre-commit")
        self.assertEqual(finding.severity, Severity.ERROR)

    def test_not_installed_detail_does_not_claim_the_hook_runs(self):
        # A "not installed" finding must not read as though the hook already runs
        # the gate. The detail describes the target wiring ("should run"), not a
        # false present-tense assertion that contradicts the title.
        finding = self._hook_finding("pre-commit")
        self.assertEqual(finding.severity, Severity.WARN)
        self.assertIn("should run `just check-fast`", finding.detail)
        self.assertNotIn("runs `just check-fast`", finding.detail)

    def test_installed_detail_states_the_hook_runs(self):
        # A wired hook reads in the present tense: it runs the gate.
        hooks = self.destination / ".git" / "hooks"
        hooks.mkdir(parents=True, exist_ok=True)
        (hooks / "pre-commit").write_text("#!/bin/sh\njust check-fast\n", encoding="utf-8")
        finding = self._hook_finding("pre-commit")
        self.assertEqual(finding.severity, Severity.OK)
        self.assertIn("runs `just check-fast`", finding.detail)

    def test_husky_grades_real_hook_not_wrapper(self):
        # #58: under husky, core.hooksPath is .husky/_ and the file there is a thin
        # wrapper. The real gate lives in .husky/<name>; assess must grade that.
        husky = self.destination / ".husky"
        (husky / "_").mkdir(parents=True)
        subprocess.run(
            ["git", "-C", str(self.destination), "config", "core.hooksPath", ".husky/_"],
            capture_output=True,
            check=True,
        )
        (husky / "_" / "pre-push").write_text(
            '#!/usr/bin/env sh\n. "$(dirname "$0")/h"\n', encoding="utf-8"
        )
        (husky / "pre-push").write_text("#!/bin/sh\njust check\n", encoding="utf-8")
        self.assertEqual(self._hook_finding("pre-push").severity, Severity.OK)

    def test_husky_missing_real_hook_is_not_installed(self):
        # Husky wrapper present but no .husky/pre-push -> the gate hook is absent.
        husky = self.destination / ".husky"
        (husky / "_").mkdir(parents=True)
        subprocess.run(
            ["git", "-C", str(self.destination), "config", "core.hooksPath", ".husky/_"],
            capture_output=True,
            check=True,
        )
        (husky / "_" / "pre-push").write_text(
            '#!/usr/bin/env sh\n. "$(dirname "$0")/h"\n', encoding="utf-8"
        )
        finding = self._hook_finding("pre-push")
        self.assertEqual(finding.severity, Severity.WARN)
        self.assertIn("not installed", finding.title)

    def test_custom_hand_rolled_hook_is_info_not_warn(self):
        # #59: a substantive hook running a real gate a non-canonical way
        # (swiftlint directly) is INFO "present (non-canonical)", not a WARN.
        hooks = self.destination / ".git" / "hooks"
        hooks.mkdir(parents=True, exist_ok=True)
        (hooks / "pre-commit").write_text(
            "#!/bin/sh\nset -e\nswiftlint lint --strict\n", encoding="utf-8"
        )
        finding = self._hook_finding("pre-commit")
        self.assertEqual(finding.severity, Severity.INFO)
        self.assertIn("non-canonical", finding.title)
        self.assertIsNone(finding.fix)  # never suggests just install-hooks
        self.assertNotIn("not installed", finding.title)

    def test_custom_pre_push_gate_is_info(self):
        # A pre-push running a custom `just` recipe (check-full) is non-canonical
        # INFO, not the fast-subset WARN and not "not installed".
        hooks = self.destination / ".git" / "hooks"
        hooks.mkdir(parents=True, exist_ok=True)
        (hooks / "pre-push").write_text("#!/bin/sh\njust check-full\n", encoding="utf-8")
        finding = self._hook_finding("pre-push")
        self.assertEqual(finding.severity, Severity.INFO)

    def test_trivial_hook_is_not_installed(self):
        # A hook that is only a shebang/comments has no gate -> WARN not installed.
        hooks = self.destination / ".git" / "hooks"
        hooks.mkdir(parents=True, exist_ok=True)
        (hooks / "pre-commit").write_text("#!/bin/sh\n# nothing here\n", encoding="utf-8")
        finding = self._hook_finding("pre-commit")
        self.assertEqual(finding.severity, Severity.WARN)
        self.assertIn("not installed", finding.title)

    def test_commented_out_recipe_is_not_graded_as_wired(self):
        # #72 — a disabled `# just check` line is not executable content, so it
        # must not grade as the gate being wired (Severity.OK) even though
        # `exit 0` keeps the hook non-trivial. Falls through to the generic
        # non-canonical bucket, same as any other hook whose content assess
        # cannot otherwise recognize as the expected recipe.
        hooks = self.destination / ".git" / "hooks"
        hooks.mkdir(parents=True, exist_ok=True)
        (hooks / "pre-push").write_text(
            "#!/bin/sh\n# just check   (disabled while debugging)\nexit 0\n",
            encoding="utf-8",
        )
        finding = self._hook_finding("pre-push")
        self.assertEqual(finding.severity, Severity.INFO)
        self.assertNotIn("runs `just check`", finding.detail)

    def test_echoed_recipe_reference_is_not_graded_as_wired(self):
        # #72 — a recipe name inside an echoed string is never actually invoked,
        # so it must not grade as the gate being wired (Severity.OK).
        hooks = self.destination / ".git" / "hooks"
        hooks.mkdir(parents=True, exist_ok=True)
        (hooks / "pre-push").write_text(
            '#!/bin/sh\necho "run just check manually"\nexit 0\n',
            encoding="utf-8",
        )
        finding = self._hook_finding("pre-push")
        self.assertEqual(finding.severity, Severity.INFO)
        self.assertNotIn("runs `just check`", finding.detail)


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

    def test_swift_xcode_app_project_yml_is_ok(self):
        # #60: an Xcode app (project.yml, no Package.swift) configured as `swift`
        # must register as a fit, not warn "no language signal".
        (self.destination / ".raven").mkdir()
        (self.destination / ".raven" / "config.toml").write_text(
            'schema = 1\ntemplate = "swift"\n', encoding="utf-8"
        )
        (self.destination / "project.yml").write_text("name: MyApp\n", encoding="utf-8")
        findings = template_fit_findings(self.destination)
        match = next(f for f in findings if f.id == "assess.fit.signal")
        self.assertEqual(match.severity, Severity.OK)

    def test_swift_config_signal_is_swiftlint_not_package_swift(self):
        # #60: the swift tool-config signal must be .swiftlint.yml (present in both
        # SwiftPM and Xcode-app repos), not Package.swift -- so an Xcode app is not
        # falsely told "tool config Package.swift missing".
        (self.destination / ".raven").mkdir()
        (self.destination / ".raven" / "config.toml").write_text(
            'schema = 1\ntemplate = "swift"\n', encoding="utf-8"
        )
        (self.destination / "project.yml").write_text("name: MyApp\n", encoding="utf-8")
        (self.destination / ".swiftlint.yml").write_text("disabled_rules: []\n", encoding="utf-8")
        findings = wiring_findings(self.destination)
        config_findings = [f for f in findings if f.id.startswith("assess.wiring.config.")]
        self.assertTrue(config_findings)
        self.assertTrue(all(f.severity == Severity.OK for f in config_findings), config_findings)
        self.assertFalse(
            any("Package.swift" in (f.detail or "") for f in config_findings), config_findings
        )


class AssessBuildTests(RavenTestCase):
    def test_without_run_gates_are_skipped(self):
        (self.destination / ".raven").mkdir()
        (self.destination / ".raven" / "config.toml").write_text(
            'schema = 1\ntemplate = "python"\n', encoding="utf-8"
        )
        findings = build_assess_findings(self.destination, run=False)
        self.assertIn("assess.gates.skipped", {f.id for f in findings})


class UnfailableRecipeTests(RavenTestCase):
    """A gate recipe whose body throws away the tool's exit status.

    The third way a gate stops being a constraint, after a recipe `check`
    never reaches and a recipe whose tool checks nothing. No output betrays
    it: the tool prints its findings and the recipe exits 0 anyway.
    """

    def _assess(self, justfile_body):
        (self.destination / ".raven").mkdir(exist_ok=True)
        (self.destination / ".raven" / "config.toml").write_text(
            'schema = 1\ntemplate = "python"\n', encoding="utf-8"
        )
        (self.destination / "justfile").write_text(justfile_body, encoding="utf-8")
        return wiring_findings(self.destination)

    def _finding(self, findings, recipe):
        return next(
            (f for f in findings if f.id == f"assess.wiring.failable.{recipe}"),
            None,
        )

    BASE = (
        "lint:\n    ruff check .\n"
        "fmt-check:\n    ruff format --check .\n"
        "typecheck:\n    pyright\n"
        "test:\n    python -m pytest\n"
        "check: lint fmt-check typecheck test\n"
    )

    def test_or_true_makes_a_recipe_unfailable(self):
        findings = self._assess(
            self.BASE.replace("    ruff check .\n", "    ruff check . || true\n")
        )
        finding = self._finding(findings, "lint")
        self.assertIsNotNone(finding)
        assert finding is not None
        self.assertEqual(finding.severity, Severity.WARN)
        self.assertIn("|| true", finding.detail)

    def test_just_ignore_error_prefix_makes_a_recipe_unfailable(self):
        findings = self._assess(
            self.BASE.replace("    python -m pytest\n", "    -python -m pytest\n")
        )
        finding = self._finding(findings, "test")
        assert finding is not None
        self.assertEqual(finding.severity, Severity.WARN)

    def test_trailing_exit_zero_makes_a_recipe_unfailable(self):
        findings = self._assess(self.BASE.replace("    pyright\n", "    pyright; exit 0\n"))
        finding = self._finding(findings, "typecheck")
        assert finding is not None
        self.assertEqual(finding.severity, Severity.WARN)

    def test_an_ordinary_recipe_is_not_flagged(self):
        findings = self._assess(self.BASE)
        for recipe in ("lint", "fmt-check", "typecheck", "test"):
            self.assertIsNone(self._finding(findings, recipe))

    def test_one_swallowed_line_beside_a_failable_one_is_not_flagged(self):
        # `just` aborts a recipe at the first failing line, so a recipe stays a
        # real gate as long as any one line can still propagate a failure.
        findings = self._assess(
            self.BASE.replace("    ruff check .\n", "    rm -f .cache || true\n    ruff check .\n")
        )
        self.assertIsNone(self._finding(findings, "lint"))

    def test_an_echoed_or_true_is_not_a_swallow(self):
        # Same tokenizer rule `_invokes_just_recipe` follows: a quoted or
        # printed construct is text, not a command.
        findings = self._assess(
            self.BASE.replace(
                "    ruff check .\n", '    echo "run: ruff check . || true"\n    ruff check .\n'
            )
        )
        self.assertIsNone(self._finding(findings, "lint"))

    def test_a_commented_out_swallow_is_not_a_swallow(self):
        findings = self._assess(
            self.BASE.replace(
                "    ruff check .\n", "    # ruff check . || true\n    ruff check .\n"
            )
        )
        self.assertIsNone(self._finding(findings, "lint"))

    def test_the_audit_recipe_is_never_graded(self):
        # Every template justfile ships an `audit` recipe that ends in `exit 0`
        # on purpose: it is report-only and deliberately absent from
        # GATE_DATA.recipes. Grading only declared gate recipes keeps it out.
        findings = self._assess(
            self.BASE
            + "audit:\n    #!/usr/bin/env sh\n    osv-scanner scan source -r .\n    exit 0\n"
        )
        self.assertIsNone(self._finding(findings, "audit"))

    def test_a_shebang_recipe_ending_in_exit_zero_is_unfailable(self):
        findings = self._assess(
            self.BASE.replace(
                "    python -m pytest\n",
                "    #!/usr/bin/env sh\n    python -m pytest\n    exit 0\n",
            )
        )
        finding = self._finding(findings, "test")
        assert finding is not None
        self.assertEqual(finding.severity, Severity.WARN)

    def test_a_shebang_recipe_with_set_e_is_not_flagged(self):
        # Under `set -e` an earlier failure exits the script non-zero, so the
        # last line no longer decides whether the recipe can fail.
        findings = self._assess(
            self.BASE.replace(
                "    python -m pytest\n",
                "    #!/usr/bin/env sh\n    set -e\n    python -m pytest\n    echo done\n",
            )
        )
        self.assertIsNone(self._finding(findings, "test"))

    def test_a_missing_recipe_is_not_graded_as_unfailable(self):
        # `assess.wiring.recipe.lint` already reports the absence; a second
        # finding about a recipe that does not exist would be noise.
        findings = self._assess(self.BASE.replace("lint:\n    ruff check .\n", ""))
        self.assertIsNone(self._finding(findings, "lint"))


if __name__ == "__main__":
    unittest.main()


class AssessGateConfigTests(RavenTestCase):
    """`assess` grades the linter configs the declared gates read (issue #229).

    The sibling of the wiring checks above: a gate can be declared, reachable
    from `check`, and able to fail, and still report nothing because its own
    configuration was edited to stop looking.
    """

    def _python_project(self, pyproject: str | None = None):
        (self.destination / ".raven").mkdir()
        (self.destination / ".raven" / "config.toml").write_text(
            'schema = 1\ntemplate = "python"\n', encoding="utf-8"
        )
        (self.destination / "justfile").write_text(
            "lint:\n    ruff check .\nfmt-check:\n    ruff format --check .\n"
            "typecheck:\n    pyright\ntest:\n    python -m pytest\n"
            "check: lint fmt-check typecheck test\n",
            encoding="utf-8",
        )
        if pyproject is not None:
            (self.destination / "pyproject.toml").write_text(pyproject, encoding="utf-8")

    def _config_findings(self):
        return [
            f
            for f in wiring_findings(self.destination)
            if f.id.startswith("assess.wiring.gateconfig")
        ]

    def test_a_healthy_config_grades_ok(self):
        self._python_project(
            '[tool.ruff.lint]\nselect = ["B", "D"]\nignore = ["D203"]\n'
            '\n[tool.pyright]\ntypeCheckingMode = "standard"\n'
        )
        findings = self._config_findings()
        self.assertEqual([f.severity for f in findings], [Severity.OK])

    def test_a_selected_and_wholly_ignored_family_warns(self):
        self._python_project('[tool.ruff.lint]\nselect = ["B", "F"]\nignore = ["B"]\n')
        findings = self._config_findings()
        self.assertEqual([f.id for f in findings], ["assess.wiring.gateconfig.ruff.cancelled"])
        self.assertEqual(findings[0].severity, Severity.WARN)
        self.assertIn("B", findings[0].detail)

    def test_a_type_check_gate_below_the_template_floor_warns(self):
        self._python_project('[tool.pyright]\ntypeCheckingMode = "off"\n')
        ids = [f.id for f in self._config_findings()]
        self.assertIn("assess.wiring.gateconfig.pyright.mode", ids)

    def test_no_readable_config_reports_nothing_here(self):
        # Absence is not a finding: a project with no linter config at all is
        # already covered by the `config_signals` check above.
        self._python_project()
        self.assertEqual(self._config_findings(), [])
