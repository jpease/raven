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

    def test_invalid_utf8_hook_emits_error_finding(self):
        # Issue #51 — invalid UTF-8 in a managed hook must produce ERROR,
        # not a UnicodeDecodeError traceback.
        hooks = self.destination / ".git" / "hooks"
        hooks.mkdir(parents=True, exist_ok=True)
        (hooks / "pre-commit").write_bytes(b"\xff\xfe invalid utf-8")
        finding = self._hook_finding("pre-commit")
        self.assertEqual(finding.severity, Severity.ERROR)


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
