#!/usr/bin/env python3
r"""Block staged content that leaks a home-directory path or a private repo name.

Enforces AGENTS.md's "Public Repository Hygiene" section: this repo is
public, so a staged doc, spec, or plan that names a private downstream repo,
or spells out a contributor's home-directory absolute path, must not land.
Scans the *added* lines of `git diff --cached` -- a line being removed (e.g.
the commit that cleans up a leak) is never a reason to block -- plus, since
#181, the destination *path* of every new, modified, or renamed staged entry
(a pure rename's path is otherwise invisible: it has no `+++`/hunk body at
all).

Two independent checks run per added line and per changed path:

1. A home-directory absolute path: `/Users/<x>`, `/home/<x>`, `~/<x>`,
   `$HOME/<x>`, `C:\\Users\\<x>`, `C:/Users/<x>`, or the WSL
   `/mnt/c/Users/<x>` form. Matching is case-insensitive and tolerates a
   doubled path separator, e.g. two slashes in a row (raven-hygiene:
   allow -- documentation about the pattern, not a real path). A
   known-shared, non-personal segment right after the prefix (`Shared`,
   `Public` -- e.g. `/Users/Shared/...`, `C:\Users\Public\...`) is exempt,
   as is the documented placeholder (`<name>`, `<downstream-repo>`, ...).
   This is a narrow, explicit skip-list, not general path/URL
   disambiguation -- a path whose final segment merely *looks like* a web
   route (raven-hygiene: allow -- documentation about the pattern, not a
   real path) still matches; that ambiguity is a known, accepted residual
   limitation.
2. A name from an optional local denylist of private repository names (see
   `load_denylist`). No denylist present means this half is skipped, not an
   error -- most contributors never create one. Matching is whole-word
   (`\b<name>\b`, case-insensitive) so a denylisted name does not fire
   inside an unrelated longer word (`core` no longer matches `hardcore`).
   Word boundaries alone do not stop a short, common English word from
   matching a genuine, unrelated standalone use (`app`, `web`, `api`), so
   entries shorter than `MIN_DENYLIST_ENTRY_LENGTH` are also rejected at
   load time, individually, with a warning -- the rest of the denylist
   still applies.

Two closely related evasions are also covered:

- A name or path split across exactly two consecutive added lines (no
  context/removed line between them, same file): each added line is joined
  with the immediately preceding added line -- both with no separator and
  with a single space inserted -- and the join is checked too. This is a
  narrow, targeted fix for the specific two-line-split gap, not a switch to
  scanning a file's full post-image; content in an added line that is not
  adjacent to another added line is only ever checked on its own.
- A binary file's content is never scanned -- a binary diff shows no line
  content at all, so there is nothing for a text-pattern checker to see.
  This is an accepted, permanent gap; what *does* get checked is the
  binary file's own *path*, per the path-scanning behavior above.

A line carrying the literal marker `raven-hygiene: allow` anywhere on it is
exempt from both checks. There is no file- or directory-level suppression --
only this single-line, diff-visible marker (see AGENTS.md's escape-hatch
rationale). A path-level finding has no line to carry that marker; the
offending path must be renamed instead.

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
#: Kept tiny and explicit: excluding docs/specs/plans is exactly what the
#: escape-hatch design forbids, so nothing doc/spec/plan-shaped belongs in
#: this set. `uv.lock` was removed from this set by #181: word-boundary +
#: minimum-length denylist matching (see `_denylist_hit`) already makes
#: routine hash/version-bump noise very unlikely to false-positive, so the
#: exclusion's only remaining effect was a real gap -- a `uv.lock`
#: git-source dependency URL can legitimately leak a private repo name.
EXCLUDED_PATHS = frozenset(
    {
        # Symlink to a file shared across repos (not this repo's content to
        # police) -- ruff's extend-exclude skips it for the same reason.
        "scripts/list_open_issues.py",
    }
)

#: Denylist entries shorter than this are dropped at load time (see
#: `load_denylist`). Word-boundary matching alone does not stop a short,
#: common English word from matching a genuine, unrelated standalone use
#: (e.g. "app", "web", "api", "core", "site" -- all 3-4 characters); a
#: length floor of 5 rejects exactly those without affecting realistic
#: project/repo names, which are essentially never this short.
MIN_DENYLIST_ENTRY_LENGTH = 5

_PLACEHOLDER_SEG = r"<[^>]+>"
# Real path segments: must start with a letter or digit (real usernames do),
# then allow underscore/dot/hyphen too. Requiring an alnum lead deliberately
# excludes punctuation-only "segments" -- a closing backtick and sentence
# period (AGENTS.md's own "`/Users/`." prose), or a bare ellipsis ("/Users/...")
# used to gesture at "and so on" -- so prose about the pattern never itself
# supplies a match.
_NAME_SEG = r"[A-Za-z0-9][A-Za-z0-9_.\-]*"
_SEG = rf"(?:{_PLACEHOLDER_SEG}|{_NAME_SEG})"

# Home-directory absolute-path prefixes, each requiring one-or-more path
# separators (tolerating a doubled separator -- two slashes in a row)
# followed by a real segment (see _SEG). Covers macOS, Linux, both Windows
# slash styles, the WSL form, and the `~`/`$HOME` shorthands. Case-
# insensitive throughout (re.IGNORECASE), so any capitalization of the
# prefix keyword matches alike. A bare prefix with nothing (or only
# punctuation, or no separator at all -- e.g. "~30 users" in prose) does
# not match, by construction of _SEG and the required separator.
_HOME_PATH_RE = re.compile(
    rf"(?:~|\$HOME|/mnt/[A-Za-z]/users|[A-Za-z]:[\\/]users|/users|/home)[\\/]+({_SEG})",
    re.IGNORECASE,
)

# Known-shared, non-personal account/folder names that immediately follow a
# home-path prefix and are therefore not a real user's home directory: macOS
# `/Users/Shared`, the Windows convention `C:\Users\Public`. Matched
# case-insensitively. This is a narrow, explicit skip-list, not a general
# "is this really a home path" heuristic -- see the module docstring.
_KNOWN_SHARED_SEGMENTS = frozenset({"shared", "public"})

_HUNK_HEADER_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")

# Matches a `diff --git a/X b/Y` header line, capturing the destination path
# Y. This is the *same* path for a new file, a modified file, and a rename
# (including a 100%-similarity rename with no `+++`/hunk body at all) -- see
# `_iter_changed_paths`.
_DIFF_HEADER_RE = re.compile(r"^diff --git a/(.+) b/(.+)$")

#: One offending line or path: (path, line number in the new file, content,
#: reason). `line_no == 0` is a sentinel meaning "the path itself, not a
#: line" -- there is no line number for a path-level finding.
Finding = tuple[str, int, str, str]


def _is_placeholder(segment: str) -> bool:
    """True if `segment` is the documented `<...>` placeholder form."""
    return segment.startswith("<") and segment.endswith(">")


def _home_path_hit(line: str) -> bool:
    """True if `line` contains a real (non-placeholder) home-directory path.

    A segment that is the documented `<...>` placeholder, or a known-shared
    non-personal segment (`_KNOWN_SHARED_SEGMENTS`), does not count.
    """
    for match in _HOME_PATH_RE.finditer(line):
        segment = match.group(1)
        if _is_placeholder(segment):
            continue
        if segment.lower() in _KNOWN_SHARED_SEGMENTS:
            continue
        return True
    return False


def _denylist_hit(line: str, denylist: list[str]) -> bool:
    """True if `line` contains any denylisted name as a whole word, case-insensitively.

    Word-boundary matching stops a denylisted name from firing inside an
    unrelated longer word (e.g. "core" no longer matches "hardcore"). Every
    `denylist` entry is already at least `MIN_DENYLIST_ENTRY_LENGTH` long
    (see `load_denylist`), which is what stops a short, common English word
    from matching a genuine, unrelated standalone use -- boundaries alone
    would not.
    """
    lowered = line.lower()
    return any(re.search(rf"\b{re.escape(name)}\b", lowered) for name in denylist)


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
        lowered = stripped.lower()
        if len(lowered) < MIN_DENYLIST_ENTRY_LENGTH:
            print(
                f"warning: raven-hygiene: denylist entry {lowered!r} is shorter than "
                f"{MIN_DENYLIST_ENTRY_LENGTH} characters and is too likely to false-positive "
                "on ordinary prose/code; skipping it (the rest of the denylist still applies)",
                file=sys.stderr,
            )
            continue
        names.append(lowered)
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


def _iter_changed_paths(diff_text: str):
    """Yield the destination path of every diff entry that is not a pure deletion.

    `diff --git a/X b/Y`'s Y names the destination uniformly for a new file,
    a modified file, and a rename -- including a 100%-similarity rename,
    which has no `+++`/`---`/hunk lines at all and would otherwise be
    invisible to `_iter_added_lines`. A deletion's destination is nothing to
    scan -- detected via a `deleted file mode` line in the entry's body --
    and is never yielded, matching "removing something is never a reason to
    block" (see `_iter_added_lines`, #181).
    """
    pending: str | None = None
    is_deletion = False
    for raw in diff_text.splitlines():
        if raw.startswith("diff --git "):
            if pending is not None and not is_deletion:
                yield pending
            match = _DIFF_HEADER_RE.match(raw)
            pending = match.group(2) if match else None
            is_deletion = False
        elif raw.startswith("deleted file mode"):
            is_deletion = True
    if pending is not None and not is_deletion:
        yield pending


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
    """Return every offending added line or changed path in `diff_text`.

    `denylist` is the return of `load_denylist`: None skips the name check
    entirely; an empty list is a denylist that legitimately matches nothing.

    Two passes: changed *paths* (new files, modified files, renames -- see
    `_iter_changed_paths`), reported with the `line_no == 0` sentinel; then
    added *lines*, each checked alone and, when it is immediately adjacent
    to the previous added line in the same file (no context/removed line
    between them), also checked jointly with it -- closing a name or path
    split across exactly two consecutive added lines (#181). A line that
    already fired on its own is not also reported via a join, to avoid a
    triplicate finding for the same leak.
    """
    findings: list[Finding] = []

    for path in _iter_changed_paths(diff_text):
        if path in EXCLUDED_PATHS:
            continue
        if _home_path_hit(path):
            findings.append((path, 0, path, "a home-directory absolute path"))
            continue
        if denylist and _denylist_hit(path, denylist):
            findings.append((path, 0, path, "a denylisted private repository name"))

    prev: tuple[str, int, str, bool] | None = None
    for path, line_no, content in _iter_added_lines(diff_text):
        if path in EXCLUDED_PATHS or ALLOW_MARKER in content:
            prev = None
            continue

        fired_alone = False
        if _home_path_hit(content):
            findings.append((path, line_no, content, "a home-directory absolute path"))
            fired_alone = True
        elif denylist and _denylist_hit(content, denylist):
            findings.append((path, line_no, content, "a denylisted private repository name"))
            fired_alone = True

        if (
            prev is not None
            and not fired_alone
            and not prev[3]
            and prev[0] == path
            and prev[1] + 1 == line_no
        ):
            _, _, prev_content, _ = prev
            joined_no_sep = prev_content + content
            joined_spaced = prev_content + " " + content
            reason = None
            if _home_path_hit(joined_no_sep) or _home_path_hit(joined_spaced):
                reason = "a home-directory absolute path"
            elif denylist and (
                _denylist_hit(joined_no_sep, denylist) or _denylist_hit(joined_spaced, denylist)
            ):
                reason = "a denylisted private repository name"
            if reason is not None:
                findings.append(
                    (
                        path,
                        line_no,
                        joined_no_sep,
                        f"{reason}, split across two added lines",
                    )
                )

        prev = (path, line_no, content, fired_alone)
    return findings


def _report(findings: list[Finding]) -> None:
    """Print one diagnostic block per finding to stderr.

    Each block shows only the matched staged line (or path) itself -- never
    a denylist name (or any other private detail) reproduced a second time
    outside it. `line_no == 0` marks a path-level finding, which has no
    line to show and no line to carry the `raven-hygiene: allow` marker.
    """
    for path, line_no, content, reason in findings:
        if line_no == 0:
            print(f"{path}: staged path contains {reason}", file=sys.stderr)
            print(
                "  Rename the path before staging -- a path-level finding has no "
                f"line to carry a `{ALLOW_MARKER}` comment.",
                file=sys.stderr,
            )
            continue
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
