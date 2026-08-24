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
  ruff     -- `ruff check .` over a tree holding no Python file
  pytest   -- `collected 0 items` (pytest itself exits 5; the line only
              reaches here when a recipe swallowed that code, which is the
              case worth catching)
  go       -- `go test ./...` where every package prints `[no test files]`
  cargo    -- `cargo test` where every test binary prints `running 0 tests`
  luacheck -- a `Total:` line reading `in 0 files`
  mix      -- `There are no tests to run`
  vitest   -- `No test files found, exiting with code 0`, which only `vitest
              run --passWithNoTests` can reach: plain `vitest run` exits 1,
              so the flag is what turns the gate green
  rubocop  -- `0 files inspected, no offenses detected`
  minitest -- a `0 runs, 0 assertions` summary from `rake test`
  credo    -- `No files found!` and an Analysis line reading `on 0 files`
  jest     -- `No tests found, exiting with code 0`, the `--passWithNoTests`
              form; plain `jest` says `code 1` and exits 1
  pyright  -- `Total files checked: 0`. Plain `pyright` prints the same
              `0 errors, 0 warnings, 0 informations` whether it analyzed five
              hundred files or none, so the python template's `typecheck`
              recipe runs `pyright --stats` to make the count observable
  swift    -- the swift template's own `lint` and `build` recipes echo a skip
              line when no Swift file is tracked and when neither
              `Package.swift` nor an Xcode project exists. Raven writes those
              strings, so unlike every other entry here they cannot drift

No detector, because the tool's output is the same either way: `eslint`,
`xcrun swift-format lint`, `mix format --check-formatted`, `stylua --check`,
`cargo fmt --check`, `cargo clippy`, and `gofmt -l .` print nothing at all on
success, matched files or not, and
`rake test` over an empty `test_files` list prints nothing either -- not even
minitest's summary, so only a test file that defines no tests leaves the
`0 runs` evidence below. A silent gate is graded OK.

No detector needed, because the tool already fails: `tsc` exits 2 (TS18003),
`prettier --check` exits 2, `busted` exits 1, `golangci-lint run` exits 5 (`no
go files to analyze`), `swift test` over an empty `Tests` directory exits 1
(`no tests found`), and `go test ./...` over zero packages exits 1. `gate_run`
reports each of those as a failing gate already.

One string that looks like evidence and is not: `swift test` on a package
using swift-testing prints XCTest's `Executed 0 tests, with 0 failures` in the
same run where swift-testing reports the tests it actually ran. Matching it
would flag a healthy suite, so nothing does -- see the test pinning that.

Everything the templates run has now been probed against a tree with nothing
to check. Nothing is left unverified.
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
# luacheck reports its file count on a summary line; zero files is a no-op.
_LUACHECK_TOTAL_RE = re.compile(r"^Total:.*\bin 0 files?$")
_MIX_NO_TESTS = "There are no tests to run"
_RUBOCOP_ZERO_RE = re.compile(r"^0 files inspected\b")
_MINITEST_RUNS_RE = re.compile(r"^(\d+) runs, \d+ assertions\b")
# credo's Analysis line: "... running 57 checks on 0 files)". The file count is
# the reliable half -- its "0 mods/funs" line also appears for files it did read.
_CREDO_ZERO_RE = re.compile(r"\bchecks on 0 files\b")
_JEST_NO_TESTS = "No tests found, exiting with code 0"
# `pyright --stats` reports its file count; plain `pyright` does not, which is
# why the python template's `typecheck` recipe passes the flag.
_PYRIGHT_ZERO_RE = re.compile(r"^Total files checked: 0$")
# Two skips the swift template's own recipes print. Unlike every other entry
# here these strings are Raven's, so they cannot drift under us -- and a
# recipe that skips is the same green no-op as a tool that finds no files.
_SWIFT_SKIPS = (
    (
        "No Swift files tracked; skipping swiftlint.",
        "no Swift files are tracked, so `just lint` skipped swiftlint",
    ),
    (
        "No Package.swift or Xcode project found yet; skipping build.",
        "no Package.swift or Xcode project exists yet, so `just build` skipped",
    ),
)
_VITEST_NO_TESTS = "No test files found, exiting with code 0"
# Some tools color unconditionally rather than only for a tty.
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


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


def _luacheck_checked_no_files(lines: list[str]) -> str | None:
    for line in lines:
        if _LUACHECK_TOTAL_RE.match(line):
            return "luacheck checked 0 files"
    return None


def _mix_had_no_tests(lines: list[str]) -> str | None:
    return "`mix test` reported no tests to run" if _MIX_NO_TESTS in lines else None


def _vitest_found_no_tests(lines: list[str]) -> str | None:
    """Evidence that `--passWithNoTests` turned an empty suite green.

    Without that flag vitest exits 1 on an empty suite, so this line reaching
    a passing gate means someone asked for the pass.
    """
    return (
        "vitest found no test files and was told to pass anyway"
        if _VITEST_NO_TESTS in lines
        else None
    )


def _credo_analyzed_no_files(lines: list[str]) -> str | None:
    for line in lines:
        if _CREDO_ZERO_RE.search(line):
            return "credo analyzed 0 files"
    return None


def _jest_found_no_tests(lines: list[str]) -> str | None:
    """Evidence that `--passWithNoTests` turned an empty jest suite green.

    Plain `jest` prints the same sentence ending in `code 1` and exits 1, so
    only the flag brings this line to a passing gate.
    """
    return "jest found no tests and was told to pass anyway" if _JEST_NO_TESTS in lines else None


def _rubocop_inspected_no_files(lines: list[str]) -> str | None:
    for line in lines:
        if _RUBOCOP_ZERO_RE.match(line):
            return "rubocop inspected 0 files"
    return None


def _minitest_ran_no_tests(lines: list[str]) -> str | None:
    """Evidence only when every minitest summary reports zero runs.

    A Rakefile that drives several suites prints one summary each, so a single
    empty suite says nothing about the rest -- the same rule
    `_cargo_ran_no_tests` follows for per-binary counts.
    """
    counts = [int(m.group(1)) for m in (_MINITEST_RUNS_RE.match(line) for line in lines) if m]
    if counts and not any(counts):
        return "the test run executed 0 tests"
    return None


def _pyright_checked_nothing(lines: list[str]) -> str | None:
    """Evidence from `pyright --stats`, which plain `pyright` cannot give.

    Plain `pyright` prints `0 errors, 0 warnings, 0 informations` whether it
    analyzed every file or none, so the python template runs it with `--stats`
    for the `Total files checked:` line this reads.
    """
    for line in lines:
        if _PYRIGHT_ZERO_RE.match(line):
            return "pyright checked 0 files"
    return None


def _swift_recipe_skipped(lines: list[str]) -> str | None:
    """Evidence that a swift gate recipe skipped its tool instead of running it."""
    for line in lines:
        for marker, evidence in _SWIFT_SKIPS:
            if marker in line:
                return evidence
    return None


_DETECTORS = (
    _ruff_saw_no_files,
    _pytest_collected_nothing,
    _go_found_no_test_files,
    _cargo_ran_no_tests,
    _luacheck_checked_no_files,
    _mix_had_no_tests,
    _vitest_found_no_tests,
    _rubocop_inspected_no_files,
    _minitest_ran_no_tests,
    _credo_analyzed_no_files,
    _jest_found_no_tests,
    _pyright_checked_nothing,
    _swift_recipe_skipped,
)


def no_work_evidence(stdout: str, stderr: str) -> str | None:
    """One phrase naming why this gate's output shows it checked nothing, or None.

    The phrase completes the sentence "`just test` exited 0 but ...", so it
    reads as the observation it is and points at the tool that made it.
    """
    lines = [_ANSI_RE.sub("", line).strip() for line in (stdout + "\n" + stderr).splitlines()]
    for detector in _DETECTORS:
        evidence = detector(lines)
        if evidence is not None:
            return evidence
    return None
