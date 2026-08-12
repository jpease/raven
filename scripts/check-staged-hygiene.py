#!/usr/bin/env python3
r"""Block staged content that leaks a home-directory path or a private repo name.

Enforces AGENTS.md's "Public Repository Hygiene" section: this repo is
public, so a staged doc, spec, or plan that names a private downstream repo,
or spells out a contributor's home-directory absolute path, must not land.
Scans only the *added* lines of `git diff --cached` -- a line being removed
(e.g. the commit that cleans up a leak) is never a reason to block.

Two independent checks run per added line:

1. A home-directory absolute path (`/Users/<x>`, `/home/<x>`, `C:\\Users\\<x>`,
   `C:/Users/<x>`, or the WSL `/mnt/c/Users/<x>` form) that is not the
   documented placeholder (`<name>`, `<downstream-repo>`, ...).
2. A name from an optional local denylist of private repository names (see
   `load_denylist`). No denylist present means this half is skipped, not an
   error -- most contributors never create one.

A line carrying the literal marker `raven-hygiene: allow` anywhere on it is
exempt from both checks. There is no file- or directory-level suppression --
only this single-line, diff-visible marker (see AGENTS.md's escape-hatch
rationale).

This script is repo-owned, not shipped: it lives in `scripts/`, not
`common/` or `.raven/git-hooks/`, so installing/upgrading a downstream
project from this template never pulls it in. It is wired into this repo's
own gate via the root `justfile`'s `hygiene` recipe.

Exit codes: 0 (clean, including an empty staged diff), 1 (a finding was
reported -- blocks the commit), 2 (the staged diff or denylist could not be
read due to a tooling/environment problem, not a content finding).
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

#: Literal token that suppresses hygiene findings for the line it appears on.
#: Single-line scope only -- deliberately no file- or directory-level escape.
ALLOW_MARKER = "raven-hygiene: allow"

#: Tracked paths this check does not scan even though they hold staged text.
#: Kept tiny and explicit: excluding a machine-generated lockfile is
#: legitimate; excluding docs/specs/plans is exactly what the escape-hatch
#: design forbids, so nothing doc/spec/plan-shaped belongs in this set.
EXCLUDED_PATHS = frozenset(
    {
        # Regenerating this lockfile churns lines unrelated to any real edit.
        "uv.lock",
        # Symlink to a file shared across repos (not this repo's content to
        # police) -- ruff's extend-exclude skips it for the same reason.
        "scripts/list_open_issues.py",
    }
)

_PLACEHOLDER_SEG = r"<[^>]+>"
# Real path segments: must start with a letter or digit (real usernames do),
# then allow underscore/dot/hyphen too. Requiring an alnum lead deliberately
# excludes punctuation-only "segments" -- a closing backtick and sentence
# period (AGENTS.md's own "`/Users/`." prose), or a bare ellipsis ("/Users/...")
# used to gesture at "and so on" -- so prose about the pattern never itself
# supplies a match.
_NAME_SEG = r"[A-Za-z0-9][A-Za-z0-9_.\-]*"
_SEG = rf"(?:{_PLACEHOLDER_SEG}|{_NAME_SEG})"

# Home-directory absolute-path prefixes, each requiring a following real
# segment (see _SEG). Covers macOS, Linux, both Windows slash styles, and
# the WSL form. A bare prefix with nothing (or only punctuation) after it
# does not match, by construction of _SEG.
_HOME_PATH_RE = re.compile(
    rf"(?:/mnt/[A-Za-z]/Users/|[A-Za-z]:[\\/]Users[\\/]|/Users/|/home/)({_SEG})"
)

_HUNK_HEADER_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")

#: One offending line: (path, line number in the new file, content, reason).
Finding = tuple[str, int, str, str]


def _is_placeholder(segment: str) -> bool:
    """True if `segment` is the documented `<...>` placeholder form."""
    return segment.startswith("<") and segment.endswith(">")


def _home_path_hit(line: str) -> bool:
    """True if `line` contains a real (non-placeholder) home-directory path."""
    return any(not _is_placeholder(match.group(1)) for match in _HOME_PATH_RE.finditer(line))


def _denylist_hit(line: str, denylist: list[str]) -> bool:
    """True if `line` contains any denylisted name, matched case-insensitively."""
    lowered = line.lower()
    return any(name in lowered for name in denylist)


def _default_denylist_path() -> Path:
    """The default local denylist location, resolved through git.

    `git rev-parse --git-path` (rather than a hand-built `.git/...` path)
    resolves correctly under a linked worktree, where `.git` is a file
    pointing elsewhere -- `info/` lives in the shared git dir, not the
    worktree-local one.
    """
    result = subprocess.run(
        ["git", "rev-parse", "--git-path", "info/raven-private-names"],
        capture_output=True,
        text=True,
        check=True,
    )
    return Path(result.stdout.strip())


def load_denylist() -> list[str] | None:
    """Load lowercase denylisted names, or None if the name check should be skipped.

    None (not an empty list) means "skip" -- callers must not conflate an
    absent denylist with a denylist that legitimately contains zero names.
    `RAVEN_HYGIENE_DENYLIST` overrides the default path, for tests and for
    contributors who keep it elsewhere.

    A missing file is treated as normal (silent skip): most contributors
    never create one, and warning on every commit would train people to
    ignore the output. A *present but unreadable* file (permissions,
    invalid UTF-8) is treated differently -- it warns on stderr and still
    skips the check, rather than either failing commits over a local dev
    file or staying silent about a denylist that silently is not applying.
    """
    override = os.environ.get("RAVEN_HYGIENE_DENYLIST")
    if override:
        path = Path(override)
    else:
        try:
            path = _default_denylist_path()
        except (subprocess.CalledProcessError, OSError):
            return None
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError) as exc:
        print(
            f"warning: raven-hygiene: could not read denylist at {path}: {exc}; "
            "skipping the name check",
            file=sys.stderr,
        )
        return None
    names: list[str] = []
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        names.append(stripped.lower())
    return names


def _iter_added_lines(diff_text: str):
    """Yield (path, line_no, content) for each added line of a staged diff.

    Only lines git marks with a leading `+` (excluding the `+++` file
    header) are yielded. Removed (`-`) and context lines are tracked only to
    keep the new-file line numbering correct -- this is what makes "a
    removed line never fails the commit that removes it" true by
    construction rather than by a special case.
    """
    path: str | None = None
    line_no: int | None = None
    for raw in diff_text.splitlines():
        if raw.startswith("diff --git "):
            path = None
            line_no = None
        elif raw.startswith("+++ "):
            target = raw[len("+++ ") :]
            if target == "/dev/null":
                path = None
            elif target.startswith("b/"):
                path = target[2:]
            else:
                path = target
        elif raw.startswith("@@"):
            match = _HUNK_HEADER_RE.match(raw)
            line_no = int(match.group(1)) if match else None
        elif path is None or line_no is None:
            continue
        elif raw.startswith("+"):
            yield path, line_no, raw[1:]
            line_no += 1
        elif raw.startswith("-"):
            continue
        elif raw.startswith("\\"):
            continue  # "\ No newline at end of file"
        else:
            line_no += 1  # context line (present if diff.context != 0)


def _staged_diff() -> str:
    """The staged diff (`git diff --cached`), tolerant of non-UTF-8 bytes.

    `--src-prefix=a/ --dst-prefix=b/` pins the canonical `a/`/`b/` prefixes
    the `+++` parsing below expects, regardless of a contributor's local
    `diff.mnemonicPrefix` setting (which would otherwise rewrite them to
    `i/`/`w/`/`c/` and break the path extraction).
    """
    result = subprocess.run(
        ["git", "diff", "--cached", "--no-color", "--src-prefix=a/", "--dst-prefix=b/"],
        capture_output=True,
        check=True,
    )
    return result.stdout.decode("utf-8", errors="replace")


def find_findings(diff_text: str, denylist: list[str] | None) -> list[Finding]:
    """Return every offending added line in `diff_text`.

    `denylist` is the return of `load_denylist`: None skips the name check
    entirely; an empty list is a denylist that legitimately matches nothing.
    """
    findings: list[Finding] = []
    for path, line_no, content in _iter_added_lines(diff_text):
        if path in EXCLUDED_PATHS:
            continue
        if ALLOW_MARKER in content:
            continue
        if _home_path_hit(content):
            findings.append((path, line_no, content, "a home-directory absolute path"))
            continue
        if denylist and _denylist_hit(content, denylist):
            findings.append((path, line_no, content, "a denylisted private repository name"))
    return findings


def _report(findings: list[Finding]) -> None:
    """Print one diagnostic block per finding to stderr.

    Each block shows only the matched staged line itself -- never a
    denylist name (or any other private detail) reproduced a second time
    outside that line.
    """
    for path, line_no, content, reason in findings:
        print(f"{path}:{line_no}: staged line contains {reason}", file=sys.stderr)
        print(f"    + {content}", file=sys.stderr)
        print(
            "  Use the placeholder form instead (e.g. `<downstream-repo>`, `<name>`), or "
            f"suppress a reviewed line with a trailing `{ALLOW_MARKER}` comment.",
            file=sys.stderr,
        )


def main() -> int:
    """Scan the staged diff, report findings on stderr, and return an exit code."""
    try:
        diff_text = _staged_diff()
    except (subprocess.CalledProcessError, OSError) as exc:
        print(f"error: raven-hygiene: could not read the staged diff: {exc}", file=sys.stderr)
        return 2
    denylist = load_denylist()
    findings = find_findings(diff_text, denylist)
    if findings:
        _report(findings)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
