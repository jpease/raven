"""Behavioral tests for `scripts/check-staged-relaxation.py`.

Every test builds a real temporary git repository, commits a baseline, `git
add`s the relaxation into the index, and invokes the checker as a subprocess
against that staged state. The checker's whole contract is "what git has
staged compared with what is committed", so a test that feeds it a
hand-written diff string proves nothing about the real `git diff --cached`
path -- and two of the three detectors read blobs out of the index and HEAD
directly, which a synthetic diff cannot supply at all.

Each fixture is a relaxation that has actually been reported, not an invented
one: the report on the Aug 2026 HN thread that motivated issue #229 describes
an agent rewriting a mandatory policy into an advisory one; the suppression
and skip shapes below are the forms Raven's own guidance already names in
`raven-python.md` and `raven-write-tests`.

No fixture in this file is spelled literally. The suppression tokens and skip
decorators are assembled at runtime, the same tactic `helpers.attribution_line`
uses for the AI-attribution scan and for the same reason: this checker runs on
this repository's own commits, so a literal here would fail Raven's own gate.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from helpers import REPO_ROOT

CHECKER = REPO_ROOT / "scripts" / "check-staged-relaxation.py"

MARKER = "raven-hygiene: allow"

# Assembled, never written out -- see the module docstring.
_NOQA = "no" + "qa"
_TYPE_IGNORE = "type: " + "ignore"
_PYRIGHT_IGNORE = "pyright: " + "ignore"
_MARK_SKIP = "@pytest.mark." + "skip"
_MARK_SKIPIF = "@pytest.mark." + "skipif"
_UNITTEST_SKIP = "@unittest." + "skip"
_UNITTEST_SKIP_UNLESS = "@unittest." + "skipUnless"

_BASE_PYPROJECT = "\n".join(
    [
        "[tool.ruff.lint]",
        'select = ["B", "F"]',
        'ignore = ["D203"]',
        "",
        "[tool.pyright]",
        'typeCheckingMode = "standard"',
        "",
    ]
)


class RelaxationCheckerTestCase(unittest.TestCase):
    def setUp(self):
        # Same guard as tests/test_check_staged_hygiene.py: a hook-driven test
        # run may inherit GIT_DIR/GIT_INDEX_FILE, which would point git at the
        # outer repo instead of the temp repo these tests create.
        for var in [k for k in os.environ if k.startswith("GIT_")]:
            self.addCleanup(os.environ.__setitem__, var, os.environ[var])
            del os.environ[var]

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name)
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)

    def _git(self, *args: str) -> str:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(self.repo),
                "-c",
                "user.email=relaxation-test@example.com",
                "-c",
                "user.name=Relaxation Test",
                *args,
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout

    def _write(self, path: str, content: str) -> None:
        target = self.repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    def _commit(self, path: str, content: str) -> None:
        self._write(path, content)
        self._git("add", "--", path)
        self._git("commit", "-q", "-m", "baseline")

    def _stage(self, path: str, content: str) -> None:
        self._write(path, content)
        self._git("add", "--", path)

    def _run(self):
        return subprocess.run(
            [sys.executable, str(CHECKER)],
            cwd=self.repo,
            env=dict(os.environ),
            capture_output=True,
            text=True,
            check=False,
        )

    def _assert_blocks(self, *expected: str):
        result = self._run()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        for fragment in expected:
            self.assertIn(fragment, result.stderr)
        return result

    def _assert_clean(self):
        result = self._run()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result


class SuppressionCommentTests(RelaxationCheckerTestCase):
    def test_blanket_suppression_with_no_rule_code_blocks(self):
        self._stage("app.py", f"x = 1  # {_NOQA}\n")

        result = self._assert_blocks("app.py:1:", "no rule code", MARKER)
        self.assertIn("`noqa`", result.stderr)

    def test_rule_code_without_a_reason_blocks(self):
        self._stage("app.py", f"x = 1  # {_NOQA}: E501\n")

        self._assert_blocks("app.py:1:", "no reason")

    def test_rule_code_with_a_reason_passes(self):
        # The shape `.claude/scripts/raven-capability-roster.py` already uses.
        self._stage("app.py", f"x = 1  # {_NOQA}: BLE001 -- optional state, see main()\n")

        self._assert_clean()

    def test_bare_type_ignore_blocks(self):
        self._stage("app.py", f"x = 1  # {_TYPE_IGNORE}\n")

        self._assert_blocks("app.py:1:", "no rule code")

    def test_type_ignore_with_a_code_and_a_reason_passes(self):
        self._stage(
            "app.py", f"x = 1  # {_TYPE_IGNORE}[arg-type]  # payload shape is host-defined\n"
        )

        self._assert_clean()

    def test_pyright_ignore_without_a_reason_blocks(self):
        self._stage("app.py", f"x = 1  # {_PYRIGHT_IGNORE}[reportAny]\n")

        self._assert_blocks("app.py:1:", "no reason")

    def test_file_level_blanket_blocks_even_with_a_reason(self):
        self._stage("app.py", f"# ruff: {_NOQA}\nx = 1\n")

        self._assert_blocks("app.py:1:", "file-level")

    def test_allow_marker_on_the_same_line_passes(self):
        self._stage("app.py", f"x = 1  # {_NOQA}  {MARKER} -- reviewed\n")

        self._assert_clean()

    def test_a_non_python_file_is_not_scanned_for_suppressions(self):
        # The eight guidance files issue #229 lists quote these tokens as
        # prose; a doc that names a suppression is not one.
        self._stage("docs/rules.md", f"Do not add a bare `# {_NOQA}`.\n")

        self._assert_clean()

    def test_removing_a_suppression_is_never_a_finding(self):
        self._commit("app.py", f"x = 1  # {_NOQA}\n")
        self._stage("app.py", "x = 1\n")

        self._assert_clean()


class SuppressionComparisonTests(RelaxationCheckerTestCase):
    """The suppression detector compares the staged file against its committed self.

    Walking the diff's added lines instead reported every suppression a file
    already held the moment anything moved it -- a reformat, a reindent, a
    rename -- so adopting the checker on a codebase that has any suppressions
    was impossible (issue #233).
    """

    TWO_SUPPRESSED = f"x=1  # {_TYPE_IGNORE}[arg-type]\ny=2  # {_TYPE_IGNORE}[arg-type]\n"
    TWO_REFORMATTED = f"x = 1  # {_TYPE_IGNORE}[arg-type]\ny = 2  # {_TYPE_IGNORE}[arg-type]\n"

    #: Filler the rename cases need: git's similarity detection reports `D`
    #: plus `A` rather than `R` when the pair is only a couple of lines long,
    #: which would test the new-file path instead of the rename path.
    PADDING = "".join(f"pad_{n} = {n}\n" for n in range(12))

    def test_a_whitespace_only_reformat_passes(self):
        self._commit("app.py", self.TWO_SUPPRESSED)
        self._stage("app.py", self.TWO_REFORMATTED)

        self._assert_clean()

    def test_a_reformat_that_adds_one_suppression_reports_only_the_new_line(self):
        self._commit("app.py", self.TWO_SUPPRESSED)
        self._stage("app.py", self.TWO_REFORMATTED + f"z = 3  # {_TYPE_IGNORE}[arg-type]\n")

        result = self._assert_blocks("app.py:3:")
        self.assertEqual(result.stderr.count("app.py:"), 1, result.stderr)

    def test_deleting_the_reason_from_a_suppression_blocks(self):
        self._commit("app.py", f"x = 1  # {_NOQA}: E501 -- vendored URL, one line\n")
        self._stage("app.py", f"x = 1  # {_NOQA}: E501\n")

        self._assert_blocks("app.py:1:", "no reason")

    def test_moving_a_suppression_to_another_line_passes(self):
        # Moved far enough that git renders it as a removal and an addition,
        # not as context that happened to shift.
        body = "".join(f"pad_{n} = {n}\n" for n in range(6))
        self._commit("app.py", f"a = 1  # {_NOQA}: E501\n{body}")
        self._stage("app.py", f"{body}a = 1  # {_NOQA}: E501\n")

        self._assert_clean()

    def test_deleting_the_allow_marker_from_a_reasonless_suppression_blocks(self):
        # The marker is dropped from the committed side too, so a line that
        # was only exempt because of it starts reporting again.
        self._commit("app.py", f"x = 1  # {_NOQA}  {MARKER} -- reviewed\n")
        self._stage("app.py", f"x = 1  # {_NOQA}\n")

        self._assert_blocks("app.py:1:", "no rule code")

    def test_a_new_file_reports_every_suppression_it_introduces(self):
        self._commit("README.md", "start\n")
        self._stage("app.py", self.TWO_SUPPRESSED)

        result = self._assert_blocks("app.py:1:", "app.py:2:")
        self.assertEqual(result.stderr.count("app.py:"), 2, result.stderr)

    def test_a_second_copy_of_an_existing_suppression_blocks(self):
        self._commit("app.py", self.TWO_SUPPRESSED)
        self._stage("app.py", self.TWO_SUPPRESSED + f"z=3  # {_TYPE_IGNORE}[arg-type]\n")

        result = self._assert_blocks("app.py:3:")
        self.assertEqual(result.stderr.count("app.py:"), 1, result.stderr)

    def test_renaming_and_reformatting_a_file_keeps_its_suppressions_silent(self):
        # The committed content sits at the old path, so the comparison has to
        # read HEAD there; reading it at the new path finds nothing and reports
        # every suppression the file already had.
        self._commit("app.py", self.PADDING + self.TWO_SUPPRESSED)
        self._git("mv", "app.py", "lib.py")
        self._stage("lib.py", self.PADDING + self.TWO_REFORMATTED)
        status = self._git("diff", "--cached", "--name-status")
        self.assertTrue(status.startswith("R"), status)

        self._assert_clean()

    def test_a_suppression_added_while_renaming_blocks(self):
        self._commit("app.py", self.PADDING + self.TWO_SUPPRESSED)
        self._git("mv", "app.py", "lib.py")
        self._stage(
            "lib.py",
            self.PADDING + self.TWO_SUPPRESSED + f"z=3  # {_TYPE_IGNORE}[arg-type]\n",
        )

        result = self._assert_blocks("lib.py:15:")
        self.assertEqual(result.stderr.count("lib.py:"), 1, result.stderr)


class ConfigRelaxationTests(RelaxationCheckerTestCase):
    def test_widening_ruff_ignore_blocks_and_names_the_rule(self):
        self._commit("pyproject.toml", _BASE_PYPROJECT)
        self._stage("pyproject.toml", _BASE_PYPROJECT.replace('"D203"', '"D203", "B008"'))

        self._assert_blocks("pyproject.toml:", "B008", "ruff.lint.ignore")

    def test_adding_a_rule_to_select_passes(self):
        self._commit("pyproject.toml", _BASE_PYPROJECT)
        self._stage("pyproject.toml", _BASE_PYPROJECT.replace('"B", "F"', '"B", "F", "I"'))

        self._assert_clean()

    def test_dropping_a_rule_from_select_blocks(self):
        self._commit("pyproject.toml", _BASE_PYPROJECT)
        self._stage("pyproject.toml", _BASE_PYPROJECT.replace('"B", "F"', '"B"'))

        self._assert_blocks("pyproject.toml:", "drops 'F'", "ruff.lint.select")

    def test_lowering_pyright_strictness_blocks(self):
        self._commit("pyproject.toml", _BASE_PYPROJECT)
        self._stage("pyproject.toml", _BASE_PYPROJECT.replace('"standard"', '"basic"'))

        self._assert_blocks("pyproject.toml:", "typeCheckingMode", "basic")

    def test_raising_pyright_strictness_passes(self):
        self._commit("pyproject.toml", _BASE_PYPROJECT)
        self._stage("pyproject.toml", _BASE_PYPROJECT.replace('"standard"', '"strict"'))

        self._assert_clean()

    def test_a_blanket_per_file_ignore_blocks(self):
        self._commit("pyproject.toml", _BASE_PYPROJECT)
        self._stage(
            "pyproject.toml",
            _BASE_PYPROJECT + '\n[tool.ruff.lint.per-file-ignores]\n"*" = ["E501"]\n',
        )

        self._assert_blocks("pyproject.toml:", "per-file-ignores")

    def test_turning_on_mypy_ignore_errors_blocks(self):
        self._commit("mypy.ini", "[mypy]\nstrict = true\n")
        self._stage("mypy.ini", "[mypy]\nstrict = true\nignore_errors = true\n")

        self._assert_blocks("mypy.ini:", "ignore_errors")

    def test_a_marked_config_line_is_excluded_from_the_comparison(self):
        self._commit("pyproject.toml", _BASE_PYPROJECT)
        self._stage(
            "pyproject.toml",
            _BASE_PYPROJECT.replace(
                'ignore = ["D203"]',
                f'ignore = ["D203", "B008"]  # {MARKER} -- B008 is wrong for this codebase',
            ),
        )

        self._assert_clean()

    def test_a_brand_new_config_file_is_compared_against_nothing(self):
        # No HEAD version to compare with: everything the file declares is
        # "new", and only an added ignore entry -- never the select list it
        # arrives with -- can read as a relaxation.
        self._commit("README.md", "start\n")
        self._stage("pyproject.toml", _BASE_PYPROJECT)

        self._assert_blocks("pyproject.toml:", "D203")

    def test_an_unrelated_config_edit_passes(self):
        self._commit("pyproject.toml", _BASE_PYPROJECT)
        self._stage("pyproject.toml", _BASE_PYPROJECT + "\n[tool.ruff]\nline-length = 100\n")

        self._assert_clean()


class TestRemovalTests(RelaxationCheckerTestCase):
    TWO_TESTS = "def test_a():\n    pass\n\n\ndef test_b():\n    pass\n"

    def test_an_unconditional_pytest_skip_blocks(self):
        self._commit("tests/test_x.py", self.TWO_TESTS)
        self._stage("tests/test_x.py", f"{_MARK_SKIP}\n{self.TWO_TESTS}")

        self._assert_blocks("tests/test_x.py:1:", "unconditional")

    def test_a_conditional_skipif_passes(self):
        self._commit("tests/test_x.py", self.TWO_TESTS)
        self._stage("tests/test_x.py", f'{_MARK_SKIPIF}(True, reason="windows")\n{self.TWO_TESTS}')

        self._assert_clean()

    def test_an_unconditional_unittest_skip_blocks(self):
        self._commit("tests/test_x.py", self.TWO_TESTS)
        self._stage("tests/test_x.py", f'{_UNITTEST_SKIP}("later")\n{self.TWO_TESTS}')

        self._assert_blocks("tests/test_x.py:1:", "unconditional")

    def test_skip_unless_passes(self):
        # The shape this repository's own suite uses for a CI-only case: a
        # conditional skip states when the test does not apply.
        self._commit("tests/test_x.py", self.TWO_TESTS)
        self._stage(
            "tests/test_x.py", f'{_UNITTEST_SKIP_UNLESS}(True, "symlinks")\n{self.TWO_TESTS}'
        )

        self._assert_clean()

    def test_deleting_a_test_with_no_replacement_blocks(self):
        self._commit("tests/test_x.py", self.TWO_TESTS)
        self._stage("tests/test_x.py", "def test_a():\n    pass\n")

        self._assert_blocks("tests/test_x.py:", "test_b", "no replacement")

    def test_renaming_a_test_passes(self):
        self._commit("tests/test_x.py", self.TWO_TESTS)
        self._stage("tests/test_x.py", self.TWO_TESTS.replace("test_b", "test_b_renamed"))

        self._assert_clean()

    def test_a_skip_outside_a_test_file_is_not_scanned(self):
        self._commit("app.py", "x = 1\n")
        self._stage("app.py", f"x = 1\n{_MARK_SKIP}\n")

        self._assert_clean()

    def test_an_added_line_marker_suppresses_the_removal_finding(self):
        self._commit("tests/test_x.py", self.TWO_TESTS)
        self._stage(
            "tests/test_x.py",
            f"# {MARKER} -- test_b now lives in tests/test_y.py\ndef test_a():\n    pass\n",
        )

        self._assert_clean()


class CleanStateTests(RelaxationCheckerTestCase):
    def test_an_empty_index_passes(self):
        self._assert_clean()

    def test_an_ordinary_change_passes(self):
        self._commit("app.py", "x = 1\n")
        self._stage("app.py", "x = 1\ny = 2\n")

        self._assert_clean()


if __name__ == "__main__":
    unittest.main()
