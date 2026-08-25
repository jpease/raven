#!/usr/bin/env python3
r"""Read the staged index the way this repository's commit-time checkers need it.

Two repo-owned pre-commit checkers read the same thing -- what `git diff
--cached` holds right now -- and disagree only about what counts as a
finding: `check-staged-hygiene.py` blocks a leaked home path or private repo
name, `check-staged-relaxation.py` blocks a change that quietly relaxes a
quality gate. This module is the half they share: running git, walking the
unified diff, and the single-line escape marker both honor.

Nothing here is shipped. Like both callers, it lives in `scripts/`, not
`common/` or `.raven/git-hooks/`, so installing or upgrading a downstream
project from this template never pulls it in.
"""

from __future__ import annotations

import io
import re
import subprocess
import tokenize

#: Literal token that suppresses a finding for the line it appears on.
#: Single-line scope only -- deliberately no file- or directory-level escape,
#: so every suppression stays visible in the diff a reviewer reads. In a
#: `.py` file the line a marker sits on can reach back over the construct a
#: closing bracket ends; see `marker_covered_lines`.
ALLOW_MARKER = "raven-hygiene: allow"

#: Token types that say nothing about what a line holds: comments, both
#: newline forms, and the block-structure tokens carrying an empty string.
_UNINFORMATIVE_TOKENS = frozenset(
    {
        tokenize.COMMENT,
        tokenize.NL,
        tokenize.NEWLINE,
        tokenize.INDENT,
        tokenize.DEDENT,
        tokenize.ENDMARKER,
    }
)

_OPENING_BRACKETS = "([{"
_CLOSING_BRACKETS = ")]}"

#: Matches a standard unified-diff hunk header, e.g. `@@ -1,2 +1,3 @@`
#: (an optional trailing function-context suffix like ` def foo():` is fine
#: -- `.match` only anchors the start). Deliberately does NOT match a git
#: "combined diff" header (`@@@ -a,b -c,d +e,f @@@`, emitted when a
#: diff-generating command shows a merge -- see `iter_added_lines`): no
#: known real invocation of `git diff --cached` (what this module actually
#: runs) produces that shape, and parsing multi-parent combined-diff line
#: prefixes correctly is real complexity for a case no caller can observe
#: in practice (#193). A hunk header this pattern doesn't match is
#: therefore treated as unscannable, not silently skipped -- see
#: `iter_added_lines`.
HUNK_HEADER_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def staged_diff() -> str:
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


def changed_paths_raw() -> bytes:
    """Raw NUL-delimited output of `git diff --cached --name-status -z`.

    `-z` disables path quoting entirely, unlike the default `diff --git a/X
    b/Y` header path discovery used to parse: that header quotes X/Y (as a
    C-style backslash-escaped string wrapped in `"..."`) whenever a path
    holds a byte >= 0x80 (subject to `core.quotePath`; true is the default)
    or a literal `"`/backslash/control character (always, regardless of
    `core.quotePath` -- the header syntax needs it to stay unambiguous). A
    path holding only a plain space is never quoted either way, but was
    already handled correctly by the old parsing; the quoted forms were not
    (#193) -- `-z` sidesteps the whole class of gap by never quoting
    anything. `--name-status` also reports a status letter
    (`A`/`M`/`D`/`R100`/`C100`/...) directly, which is what lets
    `iter_changed_paths` drop a pure deletion without a second pass scanning
    the diff body for a `deleted file mode` line.
    """
    result = subprocess.run(
        ["git", "diff", "--cached", "--no-color", "--name-status", "-z"],
        capture_output=True,
        check=True,
    )
    return result.stdout


def iter_changed_entries():
    r"""Yield (status, old_path, new_path) for every staged entry, deletions included.

    Parses `git diff --cached --name-status -z` (see `changed_paths_raw` for
    why) rather than `diff --git a/X b/Y` headers out of the full diff text.
    Each record is NUL-delimited: `status\0path\0` for an add, modify, or
    delete; `status\0old_path\0new_path\0` for a rename or copy (status
    `R.../C...`). For every status but those two the old and new paths are
    the same value.

    A caller that compares a staged file against its committed self needs the
    old path: after a rename, HEAD holds the content at the path the file
    used to have, and reading HEAD at the new path finds nothing. Callers that
    only need somewhere to look for a finding want the new path and use
    `iter_changed_paths`.
    """
    fields = changed_paths_raw().decode("utf-8", errors="replace").split("\0")
    i = 0
    n = len(fields)
    while i < n:
        status = fields[i]
        if not status:
            i += 1
            continue
        if status[0] in ("R", "C"):
            if i + 2 >= n:
                break
            yield status, fields[i + 1], fields[i + 2]
            i += 3
        else:
            if i + 1 >= n:
                break
            yield status, fields[i + 1], fields[i + 1]
            i += 2


def iter_changed_paths():
    r"""Yield the destination path of every staged entry that is not a pure deletion.

    For a rename or copy only `new_path` is yielded -- this is the *same* path
    a rename/copy header's `b/Y` used to give, including a 100%-similarity
    rename, which has no `+++`/hunk body at all and would otherwise be
    invisible to `iter_added_lines`. A deletion (status `D`) is never yielded,
    matching "removing something is never a reason to block" (see
    `iter_added_lines`, #181).
    """
    for status, _old_path, path in iter_changed_entries():
        if status[0] != "D":
            yield path


def iter_added_lines(diff_text: str):
    """Yield (path, line_no, content) for each added line of a staged diff.

    Only lines git marks with a leading `+` (excluding the `+++` file
    header) are yielded. Removed (`-`) and context lines are tracked only to
    keep the new-file line numbering correct -- this is what makes "a
    removed line never fails the commit that removes it" true by
    construction rather than by a special case.

    A hunk header that does not match the standard unified-diff shape
    `HUNK_HEADER_RE` expects (in practice: only a git "combined diff"
    header, `@@@ ... @@@`, though no known real `git diff --cached`
    invocation produces one -- see `HUNK_HEADER_RE`) is never silently
    treated as "nothing to scan under it": it is yielded once as
    `(path, None, raw_header_line)` so a caller can raise an explicit
    "could not scan" finding instead of every added line under that hunk
    simply vanishing from the scan the way it used to (#193).
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
            match = HUNK_HEADER_RE.match(raw)
            if match:
                line_no = int(match.group(1))
            else:
                line_no = None
                if path is not None:
                    yield path, None, raw
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


def iter_removed_lines(diff_text: str):
    """Yield (path, content) for each removed line of a staged diff.

    The mirror of `iter_added_lines`, and the reason it exists: a gate is
    also relaxed by taking something away -- deleting a test, dropping a
    rule from a `select` list -- which no added line records. No line number
    is yielded because a removed line has none in the new file; the finding
    it feeds names the path and the removed text.

    File headers are only read between a `diff --git` line and the first
    `@@` hunk of that file. Inside a hunk, `--- ` and `+++ ` are ordinary
    removed/added content (a removed line reading `-- x` is emitted by git
    as `--- x`), so reading them as headers there would both misattribute
    the path and swallow real removed content. A whole-file deletion
    (`+++ /dev/null`) keeps the path from its `--- a/<path>` header.
    """
    path: str | None = None
    in_header = False
    for raw in diff_text.splitlines():
        if raw.startswith("diff --git "):
            path = None
            in_header = True
        elif raw.startswith("@@"):
            in_header = False
        elif in_header and raw.startswith("--- "):
            source = raw[len("--- ") :]
            path = (
                None if source == "/dev/null" else source[2:] if source.startswith("a/") else source
            )
        elif in_header and raw.startswith("+++ "):
            target = raw[len("+++ ") :]
            # A rename shows the destination here; prefer it, but keep the
            # `--- a/<path>` fallback for a pure deletion (`+++ /dev/null`).
            if target.startswith("b/"):
                path = target[2:]
            elif target != "/dev/null":
                path = target
        elif not in_header and path is not None and raw.startswith("-"):
            yield path, raw[1:]


def index_blob(path: str) -> str | None:
    """The staged (index) content of `path`, or None when it is not in the index.

    `git show :<path>` reads stage 0 of the index -- the content the commit
    would record -- not the working tree, which may have moved on since
    `git add`. Returns None rather than raising when the path is absent
    (a pure deletion) so a caller can treat "no staged content" as a
    normal state.
    """
    return _show(f":{path}")


def head_blob(path: str) -> str | None:
    """The committed content of `path` at HEAD, or None on an unborn branch or new file."""
    return _show(f"HEAD:{path}")


def marker_covered_lines(text: str, path: str) -> set[int]:
    """1-based line numbers a `raven-hygiene: allow` marker covers in `text`.

    A marked line always covers itself. In a `.py` file a marker on a line
    holding nothing but closing brackets and commas also covers back to the
    line its outermost bracket opened on: `ruff format` splits a call that
    ran past the line length and carries the trailing marker down to the
    closing bracket, stranding the text the marker was written for on a line
    of its own (#237). Reach stops at that construct -- a marker on `)` says
    nothing about the line after it.

    Bracket pairing runs over `tokenize`'s `OP` tokens rather than a
    backwards scan of the characters, so a bracket inside a string literal
    or a comment never pairs with a real one. A marker that silently covered
    the wrong range would be worse than one that covered nothing. When
    `tokenize` cannot read the text (a syntax error, a file staged
    mid-merge) or the path is not Python, only the marked lines themselves
    come back -- the behavior every caller had before this expansion, which
    can only ever under-suppress.
    """
    covered = {
        line_no for line_no, line in enumerate(text.splitlines(), start=1) if ALLOW_MARKER in line
    }
    if not covered or not path.endswith(".py"):
        return covered
    scan = _scan_brackets(text)
    if scan is None:
        return covered
    opener_of, bracket_only = scan
    for line_no in sorted(covered):
        opener = opener_of.get(line_no)
        if opener is None or opener >= line_no or line_no not in bracket_only:
            continue
        covered.update(range(opener, line_no))
    return covered


def _scan_brackets(text: str):
    """Pair closing brackets with their openers, or None if `text` will not tokenize.

    Returns two things: the line each closing-bracket line's outermost
    bracket opened on, and the set of lines holding only closing brackets
    and commas. "Outermost" is the earliest opener among the brackets that
    close on that line, so a marker on `))` covers the outer call, not just
    the inner one.

    A line is bracket-only when every token on it is `)`, `]`, `}`, or `,`.
    An opening bracket, a name, or a `:` on the same line disqualifies it:
    `) + second(` continues the statement, so a marker there covers its own
    line and nothing above it.
    """
    opener_of: dict[int, int] = {}
    closing_lines: set[int] = set()
    other_lines: set[int] = set()
    stack: list[int] = []
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
    except (tokenize.TokenError, SyntaxError, ValueError):
        return None
    for token in tokens:
        if token.type in _UNINFORMATIVE_TOKENS:
            continue
        start_line = token.start[0]
        if token.type == tokenize.OP and token.string in _CLOSING_BRACKETS:
            if stack:
                opener = stack.pop()
                known = opener_of.get(start_line)
                if known is None or opener < known:
                    opener_of[start_line] = opener
            closing_lines.add(start_line)
            continue
        if token.type == tokenize.OP and token.string == ",":
            closing_lines.add(start_line)
            continue
        if token.type == tokenize.OP and token.string in _OPENING_BRACKETS:
            stack.append(start_line)
        other_lines.update(range(start_line, token.end[0] + 1))
    return opener_of, closing_lines - other_lines


def covered_index_lines(path: str, cache: dict[str, frozenset[int]]) -> frozenset[int]:
    """Lines of staged `path` a marker covers, reading its blob at most once.

    The expansion in `marker_covered_lines` needs the whole staged file, not
    the added lines of a diff: a marker can sit on a closing bracket the
    commit never touched while the line it covers is the one being added.
    Only a `.py` path is read for it, since no other path can expand, which
    keeps the extra `git show` off binary blobs and off every doc in a
    commit. `cache` is the caller's dict, held across one scan.
    """
    if path not in cache:
        text = index_blob(path) if path.endswith(".py") else None
        cache[path] = (
            frozenset(marker_covered_lines(text, path)) if text is not None else frozenset()
        )
    return cache[path]


def _show(spec: str) -> str | None:
    result = subprocess.run(
        ["git", "show", spec],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    return result.stdout.decode("utf-8", errors="replace")
