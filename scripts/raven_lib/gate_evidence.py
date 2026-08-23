"""Decide whether a quality gate that exited 0 actually checked anything.

A gate is only a constraint while it can fail, and a tool that runs, finds
nothing to look at, and exits 0 reports the same green as one that checked
every file and found no problem. `gate_run` grades on the exit code alone, so
without this module a moved source directory, a renamed extension, or a
narrowed path turns a gate into a green no-op that no one notices.

Each detector below encodes one way a gate tool reports having done no work,
verified against a real run of that tool rather than inferred from its docs.
A tool whose no-work behavior has not been verified gets no detector: a
missing detector reports a gate as OK, which is where `gate_run` already
stands, while a guessed one warns on healthy projects and teaches people to
ignore the warning. Absence of a signature is never proof that work happened
-- a silent gate stays OK.

Verified (each exits 0):
  ruff   -- `ruff check .` over a tree holding no Python file
  pytest -- `collected 0 items` (pytest itself exits 5; the line only reaches
            here when a recipe swallowed that code, which is the case worth
            catching)
  go     -- `go test ./...` where every package prints `[no test files]`
  cargo  -- `cargo test` where every test binary prints `running 0 tests`

No detector for pyright: it prints `0 errors, 0 warnings, 0 informations` and
exits 0 whether it analyzed five hundred files or none, so its output carries
no evidence either way. A silent typecheck gate is graded OK by default.
"""

from __future__ import annotations

import re

# `ruff check` prints this to stderr alongside its usual "All checks passed!".
# `ruff format --check` warns only when it finds nothing at all to format, and
# it also formats Python blocks inside Markdown -- a lone README is enough to
# keep it quiet -- so the lint gate is where this evidence reliably shows up.
_RUFF_NO_FILES = "No Python files found under the given path(s)"

_PYTEST_ZERO_RE = re.compile(r"^collected 0 items\b")
_GO_NO_TESTS = "[no test files]"
# A go package that ran tests reports `ok  \t<pkg>\t0.10s` or `(cached)`.
_GO_PASS_PREFIXES = ("ok ", "ok\t", "--- PASS", "--- FAIL", "FAIL")
_CARGO_RUNNING_RE = re.compile(r"^running (\d+) tests?$")


def _ruff_saw_no_files(lines: list[str]) -> str | None:
    for line in lines:
        if _RUFF_NO_FILES in line:
            return f"ruff reported `{_RUFF_NO_FILES}`"
    return None


def _pytest_collected_nothing(lines: list[str]) -> str | None:
    for line in lines:
        if _PYTEST_ZERO_RE.match(line):
            return "pytest collected 0 items"
    return None


def _go_found_no_test_files(lines: list[str]) -> str | None:
    """Evidence only when *no* package ran tests.

    A repo where some packages are tested and others are not prints both
    shapes, and that is a normal healthy suite -- warning on a single
    `[no test files]` line would fire on most Go projects.
    """
    saw_untested = False
    for line in lines:
        if any(line.startswith(prefix) for prefix in _GO_PASS_PREFIXES):
            return None
        if line.rstrip().endswith(_GO_NO_TESTS):
            saw_untested = True
    return "every Go package reported `[no test files]`" if saw_untested else None


def _cargo_ran_no_tests(lines: list[str]) -> str | None:
    """Evidence only when *every* test binary ran zero tests.

    `cargo test` prints one `running N tests` line per binary, and a crate
    with unit tests but no doc-tests prints a zero line for the doc-test
    binary -- so a single zero proves nothing.
    """
    counts = [int(m.group(1)) for m in (_CARGO_RUNNING_RE.match(line) for line in lines) if m]
    if counts and not any(counts):
        return "every `cargo test` binary ran 0 tests"
    return None


_DETECTORS = (
    _ruff_saw_no_files,
    _pytest_collected_nothing,
    _go_found_no_test_files,
    _cargo_ran_no_tests,
)


def no_work_evidence(stdout: str, stderr: str) -> str | None:
    """One phrase naming why this gate's output shows it checked nothing, or None.

    The phrase completes the sentence "`just test` exited 0 but ...", so it
    reads as the observation it is and points at the tool that made it.
    """
    lines = [line.strip() for line in (stdout + "\n" + stderr).splitlines()]
    for detector in _DETECTORS:
        evidence = detector(lines)
        if evidence is not None:
            return evidence
    return None
