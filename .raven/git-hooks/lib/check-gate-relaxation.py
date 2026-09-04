#!/usr/bin/env python3
r"""Block a staged change that adds a blanket lint suppression, in any language.

A blanket suppression turns a quality gate off for a line, a file, or a whole
crate without naming a rule. It is the cheapest way to make a red gate green,
and Raven's shipped guidance asks for the opposite -- the narrowest scoped
suppression -- in the python rules file, the python quality doc,
``raven-write-tests``, ``raven-dependency-update``, and ``raven-guardrails``.
Prose an agent can read, agree with, and then edit around. This is the part
that runs at commit time, where an agent cannot route around it.

Nine detectors across the eight languages Raven declares gates for, each
dispatched by the staged file's own extension. Python has two, since its
file-level blankets have no narrow form and its line-level ones do:

===========  ==========================================================
``.py``      a ruff/flake8, mypy, or pyright suppression naming no rule
             code, and the two file-level blankets that have no narrow
             form
``.ts`` &c   ``@ts-nocheck``, ``@ts-ignore``, and an ESLint disable
             naming no rule
``.go``      a golangci-lint directive with no linter name, or ``:all``
``.rs``      an ``allow`` attribute naming a whole lint group
``.rb``      a RuboCop directive disabling every cop
``.swift``   a SwiftLint directive disabling every rule
``.ex``      a Credo config comment naming no check
``.lua``     a Luacheck inline option ignoring every warning
===========  ==========================================================

Each syntax was run against the real linter before earning a detector, with a
fixture that violates two rules: the narrow form leaves one reporting, the
blanket form silences both. The upstream reference and the observed behavior
sit beside each pattern below. A syntax that could not be confirmed that way
gets no detector, because a missing detector reports a file as fine -- which
is where the check already stood -- while a guessed one blocks commits in a
language nobody tested.

Grandfathering, not diff-walking. For each staged file the committed and
staged blobs are each reduced to a multiset of the suppressions that would
report, and only a staged one with no committed counterpart is a finding.
Reading added diff lines instead would make a whitespace-only reformat report
every suppression the file already had, which is what made the repo-owned
checker impossible to adopt on a codebase that has any (#233). A suppression
that only moved, or was reindented, or travelled through a rename matches
itself and stays silent; a second copy of one does not.

A line carrying ``raven-hygiene: allow`` is passed over, on the committed side
as well as the staged one -- deleting the marker from a still-blanket
suppression has to start reporting it, which only happens if the committed
side never counted it either.

What this deliberately does NOT do, relative to Raven's own repo-only
``scripts/check-staged-relaxation.py`` and ``scripts/raven_lib/gate_config.py``
-- the same shape of narrowing ``raven_config.py`` documents for its own
smaller parser:

* **No config-file comparison.** ``gate_config`` reads ``pyproject.toml``,
  ``ruff.toml``, ``pyrightconfig.json``, ``mypy.ini``, ``setup.cfg``,
  ``tsconfig.json``, and ``Cargo.toml``, and reports a widened ``ignore``, a
  lowered ``typeCheckingMode``, a disabled ``strict``/``noImplicitAny``/
  ``strictNullChecks``, or a Cargo lint moved to ``warn``/``allow`` (#245).
  This shipped checker still does none of that for any language, deliberately
  -- config comparison stays repo-only, in ``gate_config.py``. What has no
  rules at all, in that module or here, is ESLint (a JS file, not a static
  config) and whichever of the other six templates' gate config is YAML
  (``.golangci.yml``, ``.swiftlint.yml``, ``.rubocop.yml``) or executable
  source (``.credo.exs``, ``.luacheckrc``); a stdlib-only runtime on a 3.9
  floor cannot read the first without a dependency or a parser whose failure
  mode is a false accusation, and the second means running it.
* **No test-deletion detector.** ``def test_`` is Python. The equivalent for
  eight toolchains is its own piece of work (#231's own "out of scope").
* **No reason requirement.** The repo-owned checker also reports a suppression
  that names a rule code but gives no reason, because that is Raven's own
  house rule. Only Python has a settled place to put one; requiring a reason
  in eight languages would mean eight guesses about what a reason looks like.
  Blanket-versus-narrow is the property each linter above actually
  demonstrates.
* **No bracket-reaching marker.** ``staged_diff.marker_covered_lines`` extends
  a marker on a closing bracket back over the call it closes, because
  ``ruff format`` splits a long decorator and strands the marker (#237). That
  applies to the test-skip detector, which is not shipped here, and every
  suppression this file reports is a comment that cannot be split across
  lines by any of the nine formatters. A plain substring rule is what the
  shipped AI-attribution scanner already uses.

Config-gated: ``[git_hooks] block_gate_relaxation`` in ``.raven/config.toml``
(default on) turns the check off for a repository that wants it off, matching
how ``block_ai_attribution_content`` gates its neighbour.

Exit codes: 0 (clean, including an empty staged index or a disabled check),
1 (a finding was reported -- blocks the commit), 2 (git could not be read,
which is a tooling problem, not a content finding).
"""

from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from collections import Counter
from importlib.machinery import SourceFileLoader
from pathlib import Path

#: Per-line escape, matched as a substring anywhere on the line. Deliberately
#: a copy of the literal in ``check-ai-attribution-content.py`` and in Raven's
#: repo-only ``scripts/staged_diff.py`` rather than an import: neither is a
#: dependency this file may take, and ``test_allow_marker_matches_the_
#: documented_literal`` pins them together. The name stays ``raven-hygiene``
#: because it already ships in ``python/pyproject.toml`` and in the
#: attribution scanner; renaming it would silently drop those exemptions.
ALLOW_MARKER = "raven-hygiene: allow"

#: One finding: (path, line number in the staged file, content, reason).
Finding = tuple[str, int, str, str]

_HINT = (
    "Fix the code, narrow the suppression to the rule it is for, or mark a reviewed "
    f"line with a trailing `{ALLOW_MARKER}` comment."
)

# --- Python -----------------------------------------------------------------
# ruff 0.14 (checked 2026-08-25): https://docs.astral.sh/ruff/linter/#error-suppression
# Observed: a two-violation line (S307 + E711) reports both with no suppression,
# reports E711 under `noqa: S307`, and reports nothing under a code-less `noqa`.
# A file-level `ruff: noqa` with no codes silenced both; with a code it did not.
# mypy: https://mypy.readthedocs.io/en/stable/inline_config.html
# pyright: https://microsoft.github.io/pyright/#/comments
_PY_FILE_BLANKETS = (
    (re.compile(r"^\s*#\s*ruff\s*:\s*noqa\s*$", re.IGNORECASE), "a file-level ruff blanket"),
    (re.compile(r"#\s*mypy\s*:\s*ignore-errors\b"), "a file-level mypy ignore"),
)
_PY_LINE_BLANKETS = (
    (
        re.compile(r"#\s*noqa(?!\s*:\s*[A-Za-z]+[0-9])", re.IGNORECASE),
        "a ruff/flake8 suppression naming no rule code",
    ),
    (re.compile(r"#\s*type\s*:\s*ignore(?!\s*\[)"), "a mypy suppression naming no rule code"),
    (re.compile(r"#\s*pyright\s*:\s*ignore(?!\s*\[)"), "a pyright suppression naming no rule"),
)
_PYTHON = _PY_FILE_BLANKETS + _PY_LINE_BLANKETS

# --- TypeScript and JavaScript ----------------------------------------------
# tsc 5 (checked 2026-08-25, re-verified 2026-09-03 for #127):
#   https://www.typescriptlang.org/docs/handbook/release-notes/typescript-3-9.html
#   https://www.typescriptlang.org/docs/handbook/release-notes/typescript-3-7.html
# Observed: on a line with a type error, the ignore and expect-error forms are
# both quiet. On a line with no error, expect-error raises TS2578 ("Unused
# '@ts-expect-error' directive") and the ignore form stays silent -- so only
# the ignore form can rot unnoticed, and only it is reported here.
# `@ts-nocheck` silenced the whole file.
# #127, tsc 5.9.3: tsc recognizes the directive only when it is the first
# thing in a `//` line comment (mod leading whitespace) -- trailing text after
# it is fine, but any character before it, or a `/* */` block form, is not.
# `// `@ts-nocheck`; explained here` still reported the file's type error, so
# both patterns require the token to sit immediately after `//`, the same
# marker-then-token adjacency every other detector below already requires.
# ESLint 9: https://eslint.org/docs/latest/use/configure/rules
# Observed on a file violating no-unused-vars and eqeqeq: the file-level
# `eslint-disable` with no rule names reported 0 problems, while the same
# comment naming one rule still reported eqeqeq. `eslint-disable-next-line`
# with no rule name silences everything on the following line. A trailing
# `-- description` is part of the directive, so it does not make one narrow.
_TYPESCRIPT = (
    (re.compile(r"//\s*@ts-nocheck\b"), "a file-level TypeScript check disable"),
    (
        re.compile(r"//\s*@ts-ignore\b"),
        "a TypeScript suppression that stays silent once it is no longer needed",
    ),
    (
        re.compile(r"/\*\s*eslint-disable(?:-next-line|-line)?\s*(?:--[^*]*)?\*/"),
        "an ESLint disable naming no rule",
    ),
    (
        re.compile(r"//\s*eslint-disable(?:-next-line|-line)?\s*(?:--.*)?$"),
        "an ESLint disable naming no rule",
    ),
)

# --- Go ---------------------------------------------------------------------
# golangci-lint 2.13 (checked 2026-08-25):
#   https://golangci-lint.run/docs/linters/false-positives/
# Observed on a file violating errcheck and ineffassign: `//nolint:errcheck`
# left ineffassign reporting; a bare `//nolint` and `//nolint:all` behaved the
# same as each other and disable every linter for their scope.
_GO = (
    (re.compile(r"//nolint:all\b"), "a golangci-lint directive disabling every linter"),
    (re.compile(r"//nolint(?![:\w-])"), "a golangci-lint directive naming no linter"),
)

# --- Rust -------------------------------------------------------------------
# clippy 0.1.98 (checked 2026-08-25):
#   https://doc.rust-lang.org/rustc/lints/levels.html
# Observed on a file warning for ptr_arg and needless_range_loop:
# `#[allow(clippy::ptr_arg)]` left needless_range_loop reporting, while
# `#![allow(clippy::all)]`, `#![allow(warnings)]`, `#[allow(warnings)]` and
# `#[allow(clippy::all)]` each silenced both. Rust has no rule-less allow, so
# the group name is what separates blanket from narrow -- a file-scoped
# `#![allow(one_lint)]` still names its lint and is not reported.
_RUST = (
    (
        re.compile(r"#!?\[\s*allow\s*\([^)]*(?<![\w:])(?:warnings|clippy::all)\b"),
        "a Rust allow attribute naming a whole lint group",
    ),
)

# --- Ruby -------------------------------------------------------------------
# RuboCop 1.89 (checked 2026-08-25):
#   https://docs.rubocop.org/rubocop/latest/usage/source_code_directives.html
# Observed: `rubocop:disable Style/NilComparison` silenced that cop;
# `rubocop:disable all` silenced everything. A directive naming no cop at all
# is not valid syntax and suppressed nothing in the run, so it gets no
# detector -- reporting it would be a false accusation. `rubocop:todo` is
# documented as an alias of `disable`.
_RUBY = (
    (
        re.compile(r"#\s*rubocop\s*:\s*(?:disable|todo)\s+all\b", re.IGNORECASE),
        "a RuboCop directive disabling every cop",
    ),
)

# --- Swift ------------------------------------------------------------------
# SwiftLint 0.65.1 (checked 2026-08-25):
#   https://realm.github.io/SwiftLint/blanket_disable_command.html
# Observed: `swiftlint:disable all` silenced every rule in the file and left
# only SwiftLint's own default `blanket_disable_command` warning. A directive
# naming no rule reported "swiftlint command does not specify any rules" and
# suppressed nothing, so it gets no detector. An unbounded `disable <rule>` is
# file-scoped but names its rule, and SwiftLint's own default rule already
# reports it.
_SWIFT = (
    (
        re.compile(r"//\s*swiftlint\s*:\s*disable(?::(?:this|next|previous))?\s+all\b"),
        "a SwiftLint directive disabling every rule",
    ),
)

# --- Elixir -----------------------------------------------------------------
# Credo 1.7 (checked 2026-08-25): https://hexdocs.pm/credo/config_comments.html
# Observed on modules violating ModuleDoc and LargeNumbers:
# `credo:disable-for-this-file Credo.Check.Readability.ModuleDoc` left
# LargeNumbers reporting, while the same comment with no check name silenced
# both. `disable-for-next-line` behaves the same way for its line.
_ELIXIR = (
    (
        re.compile(
            r"#\s*credo\s*:\s*disable-for-"
            r"(?:this-file|next-line|previous-line|lines:-?\d+)\s*$"
        ),
        "a Credo config comment naming no check",
    ),
)

# --- Lua --------------------------------------------------------------------
# Luacheck 1.2.0 (checked 2026-08-25):
#   https://luacheck.readthedocs.io/en/stable/inline.html
# Documented as "without arguments everything is ignored"; observed silencing
# the unused-variable warning both inline and as a first-line file comment.
_LUA = (
    (
        re.compile(r"--\s*luacheck\s*:\s*ignore\s*$"),
        "a Luacheck inline option ignoring every warning",
    ),
)

_DETECTORS_BY_SUFFIX = {
    ".py": _PYTHON,
    ".pyi": _PYTHON,
    ".ts": _TYPESCRIPT,
    ".tsx": _TYPESCRIPT,
    ".js": _TYPESCRIPT,
    ".jsx": _TYPESCRIPT,
    ".mts": _TYPESCRIPT,
    ".cts": _TYPESCRIPT,
    ".go": _GO,
    ".rs": _RUST,
    ".rb": _RUBY,
    ".rake": _RUBY,
    ".swift": _SWIFT,
    ".ex": _ELIXIR,
    ".exs": _ELIXIR,
    ".lua": _LUA,
}

#: Every file extension a detector fires on. `raven doctor` keeps its own copy
#: (``raven_lib.git_hooks.GATE_RELAXATION_SUFFIXES``) so it can report coverage
#: without importing a destination file into its own process; a test pins the
#: two together.
COVERED_SUFFIXES = tuple(sorted(_DETECTORS_BY_SUFFIX))


def _raven_config_module():
    """Import the ``raven_config.py`` sibling shipped in this same directory.

    Same flat-sibling resolution the AI-attribution scanner uses: this file
    ships at ``.raven/git-hooks/lib/``, the directory ``raven_config.py``
    ships in.
    """
    path = Path(__file__).resolve().parent / "raven_config.py"
    spec = importlib.util.spec_from_file_location(
        "raven_config_for_gate_relaxation",
        path,
        loader=SourceFileLoader("raven_config_for_gate_relaxation", str(path)),
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"could not load raven_config from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _repo_root() -> Path:
    """The project root, via the shared parent-directory walk in ``raven_config``.

    Three parents up from this file's own directory is the install-layout
    candidate; the shared walk confirms it or climbs further. Never shells out
    to git, so an inherited ``GIT_DIR`` cannot corrupt the answer (#202).
    """
    candidate = Path(__file__).resolve().parents[3]
    return _raven_config_module().resolve_repo_root(candidate)


def _enabled(root: Path) -> bool:
    """Whether ``[git_hooks] block_gate_relaxation`` leaves this check on.

    Anything short of a clean read of an explicit ``false`` leaves it on: a
    missing, unreadable, or silent config is not a decision to stop checking.
    """
    raven_config = _raven_config_module()
    try:
        parsed = raven_config.read_config(root / ".raven" / "config.toml")
    except raven_config.RavenConfigError:
        return True
    if parsed is None:
        return True
    raw_value = parsed.get("git_hooks", {}).get("block_gate_relaxation")
    if raw_value is None:
        return True
    parsed_value = raven_config.parse_bool(raw_value)
    return True if parsed_value is None else parsed_value


def _git(root: Path, args: list[str]) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True)


def _changed_entries(root: Path):
    r"""Yield (staged path, committed path) for each staged entry that still exists.

    Parses ``git diff --cached --name-status -z``: ``status\0path\0`` for an
    add, modify or delete, ``status\0old\0new\0`` for a rename or copy. The old
    path is what makes a rename grandfather correctly -- HEAD holds the content
    where the file used to be. A deletion is skipped: removing a suppression is
    never a reason to block.
    """
    result = _git(root, ["diff", "--cached", "--no-color", "--name-status", "-z"])
    if result.returncode != 0:
        raise OSError(result.stderr.decode("utf-8", errors="replace").strip())
    fields = result.stdout.decode("utf-8", errors="replace").split("\0")
    index = 0
    while index < len(fields):
        status = fields[index]
        if not status:
            break
        if status[0] in ("R", "C"):
            if index + 2 >= len(fields):
                break
            yield fields[index + 2], fields[index + 1]
            index += 3
            continue
        if index + 1 >= len(fields):
            break
        if status[0] != "D":
            yield fields[index + 1], fields[index + 1]
        index += 2


def _blob(root: Path, spec: str) -> str:
    """The content of a git object, or "" when there is none to read."""
    result = _git(root, ["show", spec])
    if result.returncode != 0:
        return ""
    return result.stdout.decode("utf-8", errors="replace")


def _suffix(path: str) -> str:
    name = path.rsplit("/", 1)[-1]
    dot = name.rfind(".")
    return name[dot:].lower() if dot > 0 else ""


def _blanket_suppressions(text: str, detectors):
    """Yield (line_no, content, reason) for each reportable line of ``text``.

    A line carrying the marker is dropped before anything else looks at it.
    Detector order decides the label when more than one matches: the
    file-level blankets come first, so ``ruff: noqa`` is reported as the
    file-level form rather than as a line-level one.
    """
    for line_no, content in enumerate(text.splitlines(), start=1):
        if ALLOW_MARKER in content:
            continue
        for pattern, reason in detectors:
            if pattern.search(content):
                yield line_no, content, reason
                break


def find_findings(root: Path) -> list[Finding]:
    """Every blanket suppression the staged index adds that HEAD did not have."""
    findings: list[Finding] = []
    for path, source_path in sorted(_changed_entries(root)):
        detectors = _DETECTORS_BY_SUFFIX.get(_suffix(path))
        if detectors is None:
            continue
        staged = list(_blanket_suppressions(_blob(root, f":{path}"), detectors))
        if not staged:
            continue
        # HEAD is only read for a file that would otherwise report, which
        # keeps the extra `git show` off every other file in the commit.
        committed = Counter(
            reason
            for _line_no, _content, reason in _blanket_suppressions(
                _blob(root, f"HEAD:{source_path}"), detectors
            )
        )
        for line_no, content, reason in staged:
            if committed[reason] > 0:
                committed[reason] -= 1
                continue
            findings.append((path, line_no, content.strip(), reason))
    return findings


def _report(findings: list[Finding]) -> None:
    for path, line_no, content, reason in findings:
        print(f"{path}:{line_no}: staged line adds {reason}", file=sys.stderr)
        print(f"    + {content}", file=sys.stderr)
    print(f"  {_HINT}", file=sys.stderr)


def main() -> int:
    """Scan the staged index, report findings on stderr, and return an exit code."""
    root = _repo_root()
    if not _enabled(root):
        return 0
    try:
        findings = find_findings(root)
    except OSError as exc:
        print(
            f"error: raven-gate-relaxation: could not read the staged index: {exc}",
            file=sys.stderr,
        )
        return 2
    if findings:
        _report(findings)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
