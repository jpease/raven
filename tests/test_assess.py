import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

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


if __name__ == "__main__":
    unittest.main()
