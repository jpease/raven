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


class QuietOutputTests(unittest.TestCase):
    def test_no_output_at_all_is_not_evidence(self):
        # A silent, genuinely passing gate (gofmt -l, tsc --noEmit) must stay OK:
        # absence of a known signature is not proof of no work.
        self.assertIsNone(no_work_evidence("", ""))


if __name__ == "__main__":
    unittest.main()
