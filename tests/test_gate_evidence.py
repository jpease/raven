import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from raven_lib.gate_evidence import no_work_evidence


class RuffEvidenceTests(unittest.TestCase):
    # Verified: `ruff check .` and `ruff format --check .` in a directory with
    # no Python files both print this warning and exit 0.
    NO_FILES = "warning: No Python files found under the given path(s)"

    def test_ruff_check_finding_no_files_is_evidence(self):
        stdout = "All checks passed!\n"
        self.assertIsNotNone(no_work_evidence(stdout, self.NO_FILES + "\n"))

    def test_ruff_evidence_names_the_tool(self):
        evidence = no_work_evidence("", self.NO_FILES + "\n")
        assert evidence is not None
        self.assertIn("ruff", evidence)

    def test_ruff_that_checked_files_is_not_evidence(self):
        self.assertIsNone(no_work_evidence("All checks passed!\n", ""))


class PytestEvidenceTests(unittest.TestCase):
    def test_zero_collection_is_evidence(self):
        stdout = "rootdir: /x\ncollected 0 items\n\nno tests ran in 0.00s\n"
        self.assertIsNotNone(no_work_evidence(stdout, ""))

    def test_collected_tests_are_not_evidence(self):
        stdout = "collected 41 items\n\n41 passed in 0.30s\n"
        self.assertIsNone(no_work_evidence(stdout, ""))

    def test_a_zero_inside_a_larger_count_is_not_evidence(self):
        # `collected 10 items` starts with the same characters as the zero case
        # only if the check is sloppy about the word boundary.
        self.assertIsNone(no_work_evidence("collected 10 items\n", ""))


class GoEvidenceTests(unittest.TestCase):
    # Verified: `go test ./...` over packages that exist but ship no tests
    # prints one `[no test files]` line per package and exits 0.
    def test_every_package_without_tests_is_evidence(self):
        stdout = "?   \ttmp.example/g\t[no test files]\n?   \ttmp.example/g/pkg\t[no test files]\n"
        self.assertIsNotNone(no_work_evidence(stdout, ""))

    def test_one_tested_package_is_not_evidence(self):
        stdout = "ok  \ttmp.example/g\t0.10s\n?   \ttmp.example/g/pkg\t[no test files]\n"
        self.assertIsNone(no_work_evidence(stdout, ""))

    def test_cached_pass_counts_as_work(self):
        stdout = "ok  \ttmp.example/g\t(cached)\n?   \ttmp.example/g/pkg\t[no test files]\n"
        self.assertIsNone(no_work_evidence(stdout, ""))


class CargoEvidenceTests(unittest.TestCase):
    # Verified: `cargo test` on a crate with no tests prints `running 0 tests`
    # for each test binary and exits 0.
    def test_all_binaries_running_zero_is_evidence(self):
        stdout = (
            "\nrunning 0 tests\n\ntest result: ok. 0 passed; 0 failed\n"
            "\nrunning 0 tests\n\ntest result: ok. 0 passed; 0 failed\n"
        )
        self.assertIsNotNone(no_work_evidence(stdout, ""))

    def test_an_empty_doctest_binary_alongside_real_tests_is_not_evidence(self):
        # The common shape: unit tests run, the doc-test binary has nothing.
        # Warning here would fire on most healthy Rust crates.
        stdout = (
            "\nrunning 12 tests\n\ntest result: ok. 12 passed; 0 failed\n"
            "\nrunning 0 tests\n\ntest result: ok. 0 passed; 0 failed\n"
        )
        self.assertIsNone(no_work_evidence(stdout, ""))

    def test_singular_one_test_is_not_evidence(self):
        self.assertIsNone(no_work_evidence("\nrunning 1 test\n", ""))


class LuacheckEvidenceTests(unittest.TestCase):
    # Verified: `luacheck .` over a tree with no Lua file prints a Total line
    # reading "in 0 files" and exits 0.
    def test_zero_files_checked_is_evidence(self):
        self.assertIsNotNone(no_work_evidence("Total: 0 warnings / 0 errors in 0 files\n", ""))

    def test_one_file_checked_is_not_evidence(self):
        stdout = "Checking ok.lua    OK\n\nTotal: 0 warnings / 0 errors in 1 file\n"
        self.assertIsNone(no_work_evidence(stdout, ""))

    def test_color_codes_do_not_hide_the_signature(self):
        # luacheck colors its counts; the runner captures output rather than
        # attaching a tty, but a tool that colors unconditionally must not slip
        # past for that reason alone.
        stdout = "Total: \x1b[1m0\x1b[0m warnings / \x1b[1m0\x1b[0m errors in 0 files\n"
        self.assertIsNotNone(no_work_evidence(stdout, ""))


class MixEvidenceTests(unittest.TestCase):
    # Verified: `mix test` in a project whose test directory holds no test file
    # prints this line and exits 0.
    def test_no_tests_to_run_is_evidence(self):
        stdout = "Compiling 1 file (.ex)\nGenerated demo app\nThere are no tests to run\n"
        self.assertIsNotNone(no_work_evidence(stdout, ""))

    def test_a_real_mix_run_is_not_evidence(self):
        self.assertIsNone(no_work_evidence("Finished in 0.02 seconds\n3 tests, 0 failures\n", ""))


class VitestEvidenceTests(unittest.TestCase):
    # Verified: `vitest run --passWithNoTests` with no test files prints this
    # line and exits 0. Without the flag vitest exits 1, so only the flag makes
    # this reachable -- which is exactly the configuration worth catching.
    def test_pass_with_no_tests_is_evidence(self):
        stdout = "RUN v4.1.11 /tmp/x\n\nNo test files found, exiting with code 0\n"
        self.assertIsNotNone(no_work_evidence(stdout, ""))

    def test_a_real_vitest_run_is_not_evidence(self):
        self.assertIsNone(no_work_evidence("Test Files  3 passed (3)\nTests  12 passed (12)\n", ""))


class RubocopEvidenceTests(unittest.TestCase):
    # Verified: `rubocop` over a tree with no Ruby file prints this summary and
    # exits 0. With one file it reads "1 file inspected".
    def test_zero_files_inspected_is_evidence(self):
        stdout = "Inspecting 0 files\n\n\n0 files inspected, no offenses detected\n"
        self.assertIsNotNone(no_work_evidence(stdout, ""))

    def test_one_file_inspected_is_not_evidence(self):
        stdout = "Inspecting 1 file\n.\n\n1 file inspected, no offenses detected\n"
        self.assertIsNone(no_work_evidence(stdout, ""))


class MinitestEvidenceTests(unittest.TestCase):
    # Verified: a `rake test` run over a test file that defines no test methods
    # prints this summary and exits 0.
    def test_zero_runs_is_evidence(self):
        stdout = "Finished in 0.000156s\n\n0 runs, 0 assertions, 0 failures, 0 errors, 0 skips\n"
        self.assertIsNotNone(no_work_evidence(stdout, ""))

    def test_a_real_run_is_not_evidence(self):
        stdout = "Finished in 0.0003s\n\n1 runs, 1 assertions, 0 failures, 0 errors, 0 skips\n"
        self.assertIsNone(no_work_evidence(stdout, ""))

    def test_one_empty_suite_beside_a_populated_one_is_not_evidence(self):
        # A Rakefile that runs several suites prints one summary each; a single
        # empty suite proves nothing about the others.
        stdout = (
            "0 runs, 0 assertions, 0 failures, 0 errors, 0 skips\n"
            "12 runs, 30 assertions, 0 failures, 0 errors, 0 skips\n"
        )
        self.assertIsNone(no_work_evidence(stdout, ""))


class CredoEvidenceTests(unittest.TestCase):
    # Verified: `mix credo` over a project with no source file prints
    # "No files found!" and an Analysis line reading "on 0 files", exit 0.
    def test_zero_files_analyzed_is_evidence(self):
        stdout = (
            "No files found!\n"
            "Analysis took 0.00 seconds (0.00s to load, 0.00s running 57 checks on 0 files)\n"
            "0 mods/funs, found no issues.\n"
        )
        self.assertIsNotNone(no_work_evidence(stdout, ""))

    def test_files_analyzed_is_not_evidence(self):
        stdout = (
            "Analysis took 0.00 seconds (0.00s to load, 0.00s running 57 checks on 2 files)\n"
            "2 mods/funs, found no issues.\n"
        )
        self.assertIsNone(no_work_evidence(stdout, ""))

    def test_zero_mods_funs_alone_is_not_evidence(self):
        # credo prints "0 mods/funs" whenever the files it read define no
        # module or function, including files it genuinely analyzed.
        stdout = (
            "Analysis took 0.00 seconds (0.00s to load, 0.00s running 57 checks on 1 file)\n"
            "0 mods/funs, found no issues.\n"
        )
        self.assertIsNone(no_work_evidence(stdout, ""))


class JestEvidenceTests(unittest.TestCase):
    # Verified: `jest --passWithNoTests` with no tests prints this and exits 0.
    # Plain `jest` prints "exiting with code 1" and exits 1.
    def test_pass_with_no_tests_is_evidence(self):
        self.assertIsNotNone(no_work_evidence("No tests found, exiting with code 0\n", ""))

    def test_the_failing_form_is_left_to_the_exit_code(self):
        self.assertIsNone(no_work_evidence("No tests found, exiting with code 1\n", ""))


class SwiftTestFalsePositiveTests(unittest.TestCase):
    def test_xctest_zero_executed_beside_a_swift_testing_pass_is_not_evidence(self):
        # `swift test` on a package using swift-testing prints XCTest's
        # "Executed 0 tests" *and* swift-testing's real result in the same run.
        # Reading the first line as no-work would flag a healthy suite, which
        # is why no detector matches it.
        stdout = (
            "Test Suite 'All tests' passed at 2026-08-23 11:27:01.052.\n"
            "\t Executed 0 tests, with 0 failures (0 unexpected) in 0.000 seconds\n"
            "Test run with 1 test in 0 suites passed after 0.001 seconds.\n"
        )
        self.assertIsNone(no_work_evidence(stdout, ""))


class QuietOutputTests(unittest.TestCase):
    def test_no_output_at_all_is_not_evidence(self):
        # A silent, genuinely passing gate (gofmt -l, tsc --noEmit) must stay OK:
        # absence of a known signature is not proof of no work.
        self.assertIsNone(no_work_evidence("", ""))


if __name__ == "__main__":
    unittest.main()
