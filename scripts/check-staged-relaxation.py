#!/usr/bin/env python3
r"""Block a staged change that quietly relaxes a quality gate.

Raven's guidance tells an agent not to weaken a gate in eight places -- the
python rules file, the python quality doc, `raven-write-tests`,
`raven-dependency-update`, and `raven-guardrails` -- and until this script
none of them was enforceable. Every one is prose an agent can read, agree
with, and then edit the config anyway (issue #229). This is the enforcement:
the relaxation still lands if it is meant to, but only as a line a reviewer
can see someone chose.

It is the sibling of the gate checks that already exist mechanically: a hook
that does nothing (`assess._hook_is_trivial`), a recipe nothing reaches
(`assess._recipes_reachable_from`), a recipe that cannot fail
(`assess._unfailable_reason`), and a gate that runs over no files
(`gate_evidence`). Config relaxation is the case where the gate is wired,
reachable, and able to fail, and has been configured not to look.

Three detectors run over the staged index:

1. **An unexplained suppression comment** added to a `.py` file. A
   suppression with no rule code silences everything on its line; one with a
   code and no reason leaves the next reader no way to tell a considered
   exception from a shortcut. Raven's own python rules ask for "the narrowest
   scoped suppression with a reason comment", and
   `.claude/scripts/raven-capability-roster.py` shows the shape that passes:
   a single code followed by why. File-level blanket forms
   (`ruff: noqa` with no code, `mypy: ignore-errors`) are always reported --
   there is no narrow version of them.

2. **A linter config edit that loosens the gate**, found by parsing the
   committed and staged versions of the same file and comparing them through
   `raven_lib.gate_config.relaxations`. Widening ruff's `ignore`, adding a
   `per-file-ignores` entry, dropping a rule from `select`, lowering
   pyright's `typeCheckingMode`, or setting mypy's `ignore_errors` all
   report; adding a rule to `select`, or removing one from `ignore`, never
   does. Only the config files `gate_config` can read are compared -- see its
   docstring for why ESLint and RuboCop are not among them.

3. **A test removed or switched off.** An added unconditional skip
   (`@pytest.mark.skip`, `@unittest.skip`, `self.skipTest`) reports;
   `skipif`/`skipIf`/`skipUnless` never does, because a conditional skip
   states the condition under which the test does not apply and is how this
   repo's own suite handles a platform-specific case. A file that ends the
   diff with fewer test functions than it started with reports the net loss:
   renaming or replacing a test adds one back and stays silent.

A line carrying the literal marker `raven-hygiene: allow` is exempt -- the
same single-line, diff-visible escape hatch `check-staged-hygiene.py`
established, and for the same reason: a legitimate relaxation must stay
possible without a file- or directory-level exclusion that would hide the
next one. For a config file the marker is applied before parsing, so a
marked line is simply not part of the comparison. A test-count finding has
no line of its own to mark; a marker on any added line in the same file
suppresses it.

This script is repo-owned, not shipped: it lives in `scripts/`, not
`common/` or `.raven/git-hooks/`, so installing or upgrading a downstream
project from this template never pulls it in. It is wired into this repo's
own gate via the root `justfile`'s `relaxation` recipe.

Exit codes: 0 (clean, including an empty staged diff), 1 (a finding was
reported -- blocks the commit), 2 (the staged diff could not be read due to
a tooling/environment problem, not a content finding).
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from raven_lib.gate_config import (  # noqa: E402 -- needs the sys.path insert above
    is_known_config,
    read_config_text,
    relaxations,
)
from staged_diff import (  # noqa: E402 -- needs the sys.path insert above
    ALLOW_MARKER,
    head_blob,
    index_blob,
    iter_added_lines,
    iter_changed_paths,
    iter_removed_lines,
    staged_diff,
)

#: One finding: (path, line number in the new file, content, reason, hint).
#: `line_no == 0` means the finding is about the file as a whole -- a config
#: comparison or a test count -- and has no single line to point at, so its
#: `hint` says where the escape marker goes instead.
Finding = tuple[str, int, str, str, str]

#: Where to put the marker for a finding that has no line of its own.
_CONFIG_HINT = (
    "Restore the setting, or mark the config line that changed with a trailing "
    f"`{ALLOW_MARKER}` comment."
)
_TEST_HINT = (
    "Restore the test or add its replacement, or mark any added line in this file with a "
    f"trailing `{ALLOW_MARKER}` comment."
)
_LINE_HINT = (
    "Fix the code instead, narrow the suppression to one rule code and say why, or "
    f"suppress a reviewed line with a trailing `{ALLOW_MARKER}` comment."
)

# A suppression comment's rule codes, then whatever follows them. Each
# pattern is written so this file does not match itself: the literal text
# below is a backslash-s, never a space, where a real suppression has one.
_CODE = r"[A-Za-z]+[0-9]+"
_NOQA_RE = re.compile(
    rf"#\s*noqa(?::\s*(?P<codes>{_CODE}(?:\s*,\s*{_CODE})*))?(?P<rest>.*)$",
    re.IGNORECASE,
)
_TYPE_IGNORE_RE = re.compile(r"#\s*type:\s*ignore(?:\[(?P<codes>[^\]]*)\])?(?P<rest>.*)$")
_PYRIGHT_IGNORE_RE = re.compile(r"#\s*pyright:\s*ignore(?:\[(?P<codes>[^\]]*)\])?(?P<rest>.*)$")

_SUPPRESSIONS = (
    (_NOQA_RE, "`noqa`"),
    (_TYPE_IGNORE_RE, "`type: ignore`"),
    (_PYRIGHT_IGNORE_RE, "`pyright: ignore`"),
)

#: File-level blankets. Neither has a narrow form, so both always report.
_FILE_BLANKETS = (
    (re.compile(r"#\s*ruff\s*:\s*noqa\s*$", re.IGNORECASE), "a file-level `ruff: noqa`"),
    (re.compile(r"#\s*mypy\s*:\s*ignore-errors\b", re.IGNORECASE), "a file-level mypy ignore"),
)

#: Characters a reason may be introduced by; stripped before measuring it.
_REASON_LEAD = " \t-\u2013\u2014:#"

#: A reason shorter than this is not one. Three characters admits an issue
#: number and rejects a stray separator left behind.
_MIN_REASON_LENGTH = 3

_TEST_DEF_RE = re.compile(r"^\s*(?:async\s+)?def\s+(test_[A-Za-z0-9_]*)")

#: Unconditional skips. `\b` after `skip` is what excludes `skipif`,
#: `skipIf`, and `skipUnless`: a conditional skip names the condition under
#: which the test does not apply, which is a scoped statement about the
#: environment, not a gate being switched off.
_SKIP_RES = (
    (re.compile(r"@\s*pytest\.mark\.skip\b"), "an unconditional `@pytest.mark.skip`"),
    (re.compile(r"@\s*pytest\.mark\.xfail\b"), "an `@pytest.mark.xfail`"),
    (re.compile(r"@\s*unittest\.skip\b"), "an unconditional `@unittest.skip`"),
    (re.compile(r"\bself\.skipTest\s*\("), "a `self.skipTest(...)` call"),
    (re.compile(r"(?<!\w)pytest\.skip\s*\("), "a `pytest.skip(...)` call"),
)


def _is_python(path: str) -> bool:
    return path.endswith(".py")


def _is_test_file(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    return _is_python(path) and (
        name.startswith("test_") or name.endswith("_test.py") or "/tests/" in f"/{path}"
    )


def _suppression_reason(content: str) -> str | None:
    """Why this line's suppression comment is a finding, or None when it is fine.

    Two triggers, both from `raven-python.md`'s "narrowest scoped suppression
    with a reason comment": no rule code means the line is silenced wholesale,
    and no reason means the next reader cannot tell a considered exception
    from a shortcut.
    """
    for pattern, label in _FILE_BLANKETS:
        if pattern.search(content):
            return f"{label}, which no rule code can narrow"

    for pattern, label in _SUPPRESSIONS:
        match = pattern.search(content)
        if match is None:
            continue
        if not (match.group("codes") or "").strip():
            return f"a blanket {label} with no rule code"
        if len(match.group("rest").strip(_REASON_LEAD).strip()) < _MIN_REASON_LENGTH:
            return f"a {label} with a rule code but no reason"
        return None
    return None


def _config_findings() -> list[Finding]:
    """Compare each staged config file against its committed self."""
    findings: list[Finding] = []
    for path in sorted(iter_changed_paths()):
        if not is_known_config(path):
            continue
        after_text = index_blob(path)
        if after_text is None:
            continue
        before_text = head_blob(path) or ""
        before = read_config_text(_without_marked_lines(before_text), path)
        after = read_config_text(_without_marked_lines(after_text), path)
        for _key, description in relaxations(before, after):
            findings.append(
                (path, 0, description, "staged edit loosens a quality gate", _CONFIG_HINT)
            )
    return findings


def _without_marked_lines(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if ALLOW_MARKER not in line)


def _test_findings(diff_text: str) -> list[Finding]:
    """Report an added unconditional skip, and a file that net-loses test functions."""
    findings: list[Finding] = []
    added_tests: dict[str, int] = {}
    removed_tests: dict[str, list[str]] = {}
    marked_files: set[str] = set()

    for path, line_no, content in iter_added_lines(diff_text):
        if line_no is None or not _is_test_file(path):
            continue
        if ALLOW_MARKER in content:
            marked_files.add(path)
            continue
        definition = _TEST_DEF_RE.match(content)
        if definition:
            added_tests[path] = added_tests.get(path, 0) + 1
        for pattern, label in _SKIP_RES:
            if pattern.search(content):
                findings.append((path, line_no, content, f"{label} on a test", _LINE_HINT))
                break

    for path, content in iter_removed_lines(diff_text):
        if not _is_test_file(path):
            continue
        definition = _TEST_DEF_RE.match(content)
        if definition:
            removed_tests.setdefault(path, []).append(definition.group(1))

    for path in sorted(removed_tests):
        if path in marked_files:
            continue
        lost = len(removed_tests[path]) - added_tests.get(path, 0)
        if lost <= 0:
            continue
        names = ", ".join(f"`{name}`" for name in sorted(removed_tests[path]))
        findings.append(
            (
                path,
                0,
                f"{lost} more test function(s) removed than added ({names})",
                "staged edit deletes a test with no replacement",
                _TEST_HINT,
            )
        )
    return findings


def find_findings(diff_text: str) -> list[Finding]:
    """Every relaxation the staged diff introduces, across all three detectors."""
    findings: list[Finding] = []
    for path, line_no, content in iter_added_lines(diff_text):
        if line_no is None or not _is_python(path) or ALLOW_MARKER in content:
            continue
        reason = _suppression_reason(content)
        if reason is not None:
            findings.append((path, line_no, content, reason, _LINE_HINT))
    findings.extend(_config_findings())
    findings.extend(_test_findings(diff_text))
    return findings


def _report(findings: list[Finding]) -> None:
    """Print one diagnostic block per finding to stderr."""
    for path, line_no, content, reason, hint in findings:
        if line_no == 0:
            print(f"{path}: {reason}", file=sys.stderr)
            print(f"    {content}", file=sys.stderr)
        else:
            print(f"{path}:{line_no}: staged line adds {reason}", file=sys.stderr)
            print(f"    + {content}", file=sys.stderr)
        print(f"  {hint}", file=sys.stderr)


def main() -> int:
    """Scan the staged diff, report findings on stderr, and return an exit code."""
    try:
        diff_text = staged_diff()
    except (subprocess.CalledProcessError, OSError) as exc:
        print(f"error: raven-relaxation: could not read the staged diff: {exc}", file=sys.stderr)
        return 2
    findings = find_findings(diff_text)
    if findings:
        _report(findings)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
