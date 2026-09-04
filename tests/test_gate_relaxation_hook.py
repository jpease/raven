"""Tests for #231: the gate-relaxation check shipped into installed projects.

`scripts/check-staged-relaxation.py` is repo-owned and Python-only. This suite
covers its shipped counterpart, `.raven/git-hooks/lib/check-gate-relaxation.py`,
which every template receives through the `hooks` component and which reports a
blanket suppression in any of the eight languages Raven declares gates for.

Every suppression token is assembled at runtime from parts rather than written
as one literal. This repository's own pre-commit runs both relaxation checks
over its staged diff, and a test file spelling a blanket suppression outright
would report itself.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import NamedTuple

from helpers import REPO_ROOT, RavenTestCase, install_raven_config_lib, load_script_module, raven

SCRIPT_PATH = REPO_ROOT / "common" / ".raven" / "git-hooks" / "lib" / "check-gate-relaxation.py"
PRE_COMMIT_PATH = REPO_ROOT / "common" / ".raven" / "git-hooks" / "pre-commit"

#: The per-line escape a finding may carry. Spelled out here rather than
#: imported, so a drifted shipped copy fails the marker tests instead of
#: silently agreeing with itself.
ALLOW_MARKER = "raven-hygiene: allow"


def _token(*parts: str) -> str:
    """Join a suppression token from parts, so no line of this file spells one."""
    return "".join(parts)


class Case(NamedTuple):
    """One language's clean, blanket-suppressed, and narrowly-suppressed source."""

    language: str
    path: str
    clean: str
    blanket: str
    narrow: str


#: Every language with a shipped detector. The blanket form of each was
#: confirmed against the real linter (ruff, tsc, eslint, golangci-lint, clippy,
#: rubocop, swiftlint, credo, luacheck): it silences rules the narrow form
#: leaves reporting.
CASES = (
    Case(
        "python",
        "src/app.py",
        "value = compute()\n",
        "value = compute()  " + _token("# no", "qa") + "\n",
        "value = compute()  " + _token("# no", "qa", ": F821 compute is injected") + "\n",
    ),
    Case(
        "typescript",
        "src/app.ts",
        "const n: number = load();\n",
        "// " + _token("@ts-", "ignore") + "\nconst n: number = load();\n",
        "// " + _token("@ts-", "expect-error load() is untyped") + "\nconst n: number = load();\n",
    ),
    Case(
        "typescript-eslint",
        "src/util.js",
        "const unused = 1;\n",
        "/* " + _token("eslint-", "disable") + " */\nconst unused = 1;\n",
        "/* " + _token("eslint-", "disable no-unused-vars") + " */\nconst unused = 1;\n",
    ),
    Case(
        "go",
        "pkg/read.go",
        "\tdefer f.Close()\n",
        "\tdefer f.Close() " + _token("//no", "lint") + "\n",
        "\tdefer f.Close() " + _token("//no", "lint:errcheck") + " // read-only handle\n",
    ),
    Case(
        "rust",
        "src/lib.rs",
        "pub fn f(v: &Vec<i32>) -> usize { v.len() }\n",
        _token("#![", "allow(warnings)]") + "\npub fn f(v: &Vec<i32>) -> usize { v.len() }\n",
        _token("#[", "allow(clippy::ptr_arg)]") + "\npub fn f(v: &Vec<i32>) -> usize { v.len() }\n",
    ),
    Case(
        "ruby",
        "lib/app.rb",
        "x = compute\n",
        "x = compute " + _token("# ru", "bocop:disable all") + "\n",
        "x = compute " + _token("# ru", "bocop:disable Style/NilComparison") + "\n",
    ),
    Case(
        "swift",
        "Sources/App.swift",
        "let a = 1 ;\n",
        _token("// swift", "lint:disable all") + "\nlet a = 1 ;\n",
        _token("// swift", "lint:disable:this trailing_semicolon") + "\nlet a = 1 ;\n",
    ),
    Case(
        "elixir",
        "lib/app.ex",
        "defmodule App do\nend\n",
        _token("# cre", "do:disable-for-this-file") + "\ndefmodule App do\nend\n",
        _token("# cre", "do:disable-for-this-file Credo.Check.Readability.ModuleDoc")
        + "\ndefmodule App do\nend\n",
    ),
    Case(
        "lua",
        "src/app.lua",
        "local unused = 1\n",
        "local unused = 1 " + _token("-- lua", "check: ignore") + "\n",
        "local unused = 1 " + _token("-- lua", "check: ignore unused") + "\n",
    ),
)


class GateRelaxationHookTests(unittest.TestCase):
    """The shipped checker, run as a subprocess against a real staged index."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name)
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        subprocess.run(
            ["git", "-C", str(self.repo), "config", "user.email", "t@example.com"], check=True
        )
        subprocess.run(["git", "-C", str(self.repo), "config", "user.name", "Test"], check=True)
        # The checker resolves the repo root from its own __file__, the way
        # every other shipped hook lib does, so it has to be installed at the
        # offset a real install uses or it would scan this checkout instead.
        lib_dir = self.repo / ".raven" / "git-hooks" / "lib"
        lib_dir.mkdir(parents=True)
        self.installed_script = lib_dir / SCRIPT_PATH.name
        shutil.copy2(SCRIPT_PATH, self.installed_script)
        install_raven_config_lib(self.repo)
        self._commit("README.md", "# repo\n")

    def _write(self, path: str, content: str) -> None:
        target = self.repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    def _commit(self, path: str, content: str, message: str = "commit") -> None:
        self._write(path, content)
        subprocess.run(["git", "-C", str(self.repo), "add", path], check=True)
        subprocess.run(["git", "-C", str(self.repo), "commit", "-q", "-m", message], check=True)

    def _stage(self, path: str, content: str) -> None:
        self._write(path, content)
        subprocess.run(["git", "-C", str(self.repo), "add", path], check=True)

    def _run(self, config_text: str | None = None) -> tuple[int, str]:
        if config_text is not None:
            raven_dir = self.repo / ".raven"
            raven_dir.mkdir(exist_ok=True)
            (raven_dir / "config.toml").write_text(config_text, encoding="utf-8")
        result = subprocess.run(
            [sys.executable, str(self.installed_script)],
            capture_output=True,
            text=True,
            cwd=str(self.repo),
        )
        return result.returncode, result.stderr

    # ---- per language: blanket blocks, narrow passes, marker passes ----

    def test_blanket_suppression_blocks_the_commit(self):
        for case in CASES:
            with self.subTest(language=case.language):
                self._stage(case.path, case.blanket)
                rc, err = self._run()
                self.assertEqual(rc, 1, f"{case.language}: expected a finding\n{err}")
                self.assertIn(case.path, err)

    def test_narrow_suppression_passes(self):
        for case in CASES:
            with self.subTest(language=case.language):
                self._stage(case.path, case.narrow)
                rc, err = self._run()
                self.assertEqual(rc, 0, f"{case.language}: unexpected finding\n{err}")

    def test_clean_source_passes(self):
        for case in CASES:
            with self.subTest(language=case.language):
                self._stage(case.path, case.clean)
                rc, err = self._run()
                self.assertEqual(rc, 0, f"{case.language}: unexpected finding\n{err}")

    def test_blanket_suppression_with_allow_marker_passes(self):
        for case in CASES:
            with self.subTest(language=case.language):
                marked = case.blanket.replace("\n", f" {ALLOW_MARKER}\n", 1)
                self._stage(case.path, marked)
                rc, err = self._run()
                self.assertEqual(rc, 0, f"{case.language}: marker ignored\n{err}")

    # ---- grandfathering (#233): a pre-existing suppression never reports ----

    def test_reformat_of_a_file_holding_blanket_suppressions_passes(self):
        for case in CASES:
            with self.subTest(language=case.language):
                body = case.blanket + case.blanket
                self._commit(case.path, body, message=f"seed {case.language}")
                self._stage(case.path, body.replace("\n", "\n\n"))
                rc, err = self._run()
                self.assertEqual(rc, 0, f"{case.language}: reformat reported\n{err}")

    def test_moving_a_suppression_within_a_file_passes(self):
        case = CASES[0]
        self._commit(case.path, case.clean + case.blanket)
        self._stage(case.path, case.blanket + case.clean)
        rc, err = self._run()
        self.assertEqual(rc, 0, err)

    def test_renaming_a_file_carrying_a_suppression_passes(self):
        case = CASES[0]
        self._commit(case.path, case.blanket)
        subprocess.run(["git", "-C", str(self.repo), "mv", case.path, "src/renamed.py"], check=True)
        rc, err = self._run()
        self.assertEqual(rc, 0, err)

    def test_a_second_copy_of_an_existing_suppression_reports(self):
        case = CASES[0]
        self._commit(case.path, case.blanket)
        self._stage(case.path, case.blanket + case.blanket)
        rc, err = self._run()
        self.assertEqual(rc, 1, err)

    def test_deleting_the_marker_from_a_suppressed_line_reports(self):
        case = CASES[0]
        self._commit(case.path, case.blanket.replace("\n", f" {ALLOW_MARKER}\n", 1))
        self._stage(case.path, case.blanket)
        rc, err = self._run()
        self.assertEqual(rc, 1, err)

    def test_deleting_a_file_that_holds_a_suppression_passes(self):
        case = CASES[0]
        self._commit(case.path, case.blanket)
        subprocess.run(["git", "-C", str(self.repo), "rm", "-q", case.path], check=True)
        rc, err = self._run()
        self.assertEqual(rc, 0, err)

    # ---- forms that must not report ----

    def test_ts_expect_error_is_not_reported_but_ts_ignore_is(self):
        # tsc reports TS2578 "Unused '@ts-expect-error' directive" when the
        # error goes away; the ignore form stays silent forever.
        self._stage("a.ts", "// " + _token("@ts-", "expect-error why") + "\nconst n = 1;\n")
        self.assertEqual(self._run()[0], 0)
        self._stage("b.ts", "// " + _token("@ts-", "ignore") + "\nconst n = 1;\n")
        self.assertEqual(self._run()[0], 1)

    def test_ts_directive_named_in_prose_is_not_reported(self):
        # #127: a comment that merely *mentions* the directive, rather than
        # opening with it, is not recognized by tsc as a suppression -- so
        # flagging it is a false accusation. Verified against tsc 5.9.3: a
        # comment reading "// `@ts-nocheck`; explanation" still reports the
        # file's type error, while "// @ts-nocheck" alone does not.
        self._stage(
            "a.ts",
            "// `" + _token("@ts-", "nocheck") + "`; explained here, not enabled\n"
            "const n: number = 1;\n",
        )
        self.assertEqual(self._run()[0], 0)
        self._stage(
            "b.ts",
            "const a: number = 1;\n"
            "// see `" + _token("@ts-", "ignore") + "` for details\n"
            "const n: number = 1;\n",
        )
        self.assertEqual(self._run()[0], 0)
        # The real directive, anchored right after `//`, still reports.
        self._stage("c.ts", "// " + _token("@ts-", "nocheck") + "\nconst n: number = 1;\n")
        self.assertEqual(self._run()[0], 1)

    def test_bare_rubocop_disable_is_not_reported(self):
        # Verified against rubocop 1.89: a disable naming no cop suppresses
        # nothing, so reporting it would be a false accusation.
        self._stage("lib/a.rb", "x = compute " + _token("# ru", "bocop:disable") + "\n")
        rc, err = self._run()
        self.assertEqual(rc, 0, err)

    def test_bare_swiftlint_disable_is_not_reported(self):
        # Verified against swiftlint 0.65.1: it reports the command as invalid
        # ("does not specify any rules") and suppresses nothing.
        self._stage("A.swift", _token("// swift", "lint:disable") + "\nlet a = 1 ;\n")
        rc, err = self._run()
        self.assertEqual(rc, 0, err)

    def test_file_with_no_covered_suffix_passes(self):
        self._stage("NOTES.md", "- " + _token("# no", "qa") + " in prose\n")
        rc, err = self._run()
        self.assertEqual(rc, 0, err)

    def test_empty_staged_index_passes(self):
        rc, err = self._run()
        self.assertEqual(rc, 0, err)

    # ---- config opt-out, matching block_ai_attribution_content ----

    def test_config_opt_out_disables_the_check(self):
        case = CASES[0]
        self._stage(case.path, case.blanket)
        rc, _ = self._run(config_text="[git_hooks]\nblock_gate_relaxation = false\n")
        self.assertEqual(rc, 0)

    def test_config_default_is_enabled(self):
        case = CASES[0]
        self._stage(case.path, case.blanket)
        rc, _ = self._run(config_text='template = "python"\n')
        self.assertEqual(rc, 1)

    # ---- the report itself ----

    def test_report_names_the_line_and_the_escape(self):
        case = CASES[0]
        self._stage(case.path, case.blanket)
        _, err = self._run()
        self.assertIn(f"{case.path}:1:", err)
        self.assertIn(ALLOW_MARKER, err)


class GateRelaxationCoverageTests(unittest.TestCase):
    """Coverage of the eight gated templates, and the doctor-side copy of it."""

    def setUp(self):
        self.module = load_script_module("check_gate_relaxation", SCRIPT_PATH)

    def test_every_gated_template_source_suffix_has_a_detector(self):
        from raven_lib.gates import load_gate_specs

        covered = set(self.module.COVERED_SUFFIXES)
        for name, spec in load_gate_specs().items():
            with self.subTest(template=name):
                missing = [s for s in spec.source_suffixes if s not in covered]
                self.assertEqual(
                    missing, [], f"{name} declares gates but {missing} has no detector"
                )

    def test_doctor_copy_of_the_suffix_table_matches_the_shipped_one(self):
        from raven_lib.git_hooks import GATE_RELAXATION_SUFFIXES

        self.assertEqual(tuple(self.module.COVERED_SUFFIXES), GATE_RELAXATION_SUFFIXES)

    def test_allow_marker_matches_the_documented_literal(self):
        self.assertEqual(self.module.ALLOW_MARKER, ALLOW_MARKER)


class GateRelaxationWiringTests(unittest.TestCase):
    """The pre-commit hook invokes the checker the way its neighbours are invoked."""

    def setUp(self):
        self.text = PRE_COMMIT_PATH.read_text(encoding="utf-8")

    def test_pre_commit_invokes_the_checker(self):
        self.assertIn(".raven/git-hooks/lib/check-gate-relaxation.py", self.text)

    def test_pre_commit_skips_a_missing_checker_rather_than_failing(self):
        # Same shape as the attribution and managed-block calls: a partial
        # install skips the script instead of blocking every commit.
        index = self.text.index("check-gate-relaxation.py")
        tail = self.text[index : index + 400]
        self.assertIn('if [ -f "$', tail)
        self.assertIn("|| exit 1", tail)

    def test_gitattributes_covers_the_new_lib_file(self):
        text = (REPO_ROOT / "common" / ".gitattributes").read_text(encoding="utf-8")
        self.assertIn(".raven/git-hooks/lib/check-gate-relaxation.py text eol=lf", text)


class GateRelaxationDoctorTests(RavenTestCase):
    """`raven doctor` reports the checker as part of the install shape."""

    def _config(self, template: str = "python") -> None:
        raven_dir = self.destination / ".raven"
        raven_dir.mkdir(parents=True, exist_ok=True)
        (raven_dir / "config.toml").write_text(f'template = "{template}"\n', encoding="utf-8")

    def _install_checker(self) -> Path:
        lib_dir = self.destination / ".raven" / "git-hooks" / "lib"
        lib_dir.mkdir(parents=True, exist_ok=True)
        target = lib_dir / "check-gate-relaxation.py"
        shutil.copy2(SCRIPT_PATH, target)
        return target

    def test_no_finding_when_the_hooks_tree_is_absent(self):
        from raven_lib.doctor import gate_relaxation_findings

        self._config()
        self.assertEqual(gate_relaxation_findings(self.destination), [])

    def test_warns_when_the_checker_is_missing(self):
        from raven_lib.doctor import gate_relaxation_findings

        self._config()
        (self.destination / ".raven" / "git-hooks").mkdir(parents=True, exist_ok=True)
        findings = gate_relaxation_findings(self.destination)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].id, "doctor.hooks.gate_relaxation")
        self.assertEqual(findings[0].severity, raven.Severity.WARN)

    def test_ok_when_the_checker_covers_the_template(self):
        from raven_lib.doctor import gate_relaxation_findings

        self._config("python")
        self._install_checker()
        findings = gate_relaxation_findings(self.destination)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].severity, raven.Severity.OK)
        self.assertIn(".py", findings[0].detail)

    def test_says_so_when_the_template_declares_no_gates(self):
        from raven_lib.doctor import gate_relaxation_findings

        self._config("dotfiles")
        self._install_checker()
        findings = gate_relaxation_findings(self.destination)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].severity, raven.Severity.OK)
        self.assertIn("no gate", findings[0].detail)

    def test_uncovered_suffixes_are_named_rather_than_passing_silently(self):
        from raven_lib.doctor import _uncovered_gate_suffixes

        self.assertEqual(_uncovered_gate_suffixes((".py", ".pyi")), ())
        self.assertEqual(_uncovered_gate_suffixes((".py", ".zig")), (".zig",))

    def test_build_doctor_findings_includes_the_checker(self):
        from raven_lib.doctor import build_doctor_findings

        self._config("python")
        self._install_checker()
        ids = {f.id for f in build_doctor_findings(self.destination)}
        self.assertIn("doctor.hooks.gate_relaxation", ids)


if __name__ == "__main__":
    unittest.main()
