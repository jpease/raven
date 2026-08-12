#!/usr/bin/env python3
"""Validate two narrow, high-signal claims that Raven's own Markdown docs make.

1. **Local Markdown links.** Every relative link (``[text](path)``) in tracked
   Markdown resolves to a file that actually exists. Anchor/heading resolution
   is deliberately out of scope -- a ``#fragment`` suffix is stripped and only
   the file part is checked (issue #164: the repo has only 4 relative links
   total, not enough surface to justify heading-derivation logic).
2. **Raven CLI subcommands and flags.** Every ``raven <subcommand> --flag`` (or
   ``python scripts/raven.py <subcommand> --flag``) example that appears in a
   fenced code block or inline code span is checked against the *real*
   argparse parser (`raven_lib.cli.build_parser`), not a hand-maintained list
   that could itself drift out of sync with the CLI.

Both checks scan `git ls-files '*.md'` rather than walking the filesystem.
That satisfies "symlinked trees are validated once, not once per symlink" by
construction: git records a symlinked directory (e.g. a language template's
`.agents/skills`) as a single symlink blob and does not track files beneath
it, so a shared doc never appears once per language tree, only once at its
canonical path.

Deliberately dropped (see issue #164's scope decisions, not revisited here):
Raven-owned path references (template- vs destination-relative resolution is
its own config surface) and anchor/heading resolution. There is no baseline
suppression list: the validator must pass clean on this repository with no
exclusions, and a real failure it finds is a real defect to fix, not a
candidate for an allowlist entry.

Exit codes: 0 (clean), 1 (at least one finding), 2 (a tooling/environment
problem, such as `git ls-files` failing, prevented the checks from running).
"""

from __future__ import annotations

import argparse
import re
import shlex
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"

if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from raven_lib.cli import build_parser  # noqa: E402

#: One finding: (repo-relative file path, 1-indexed line number, message).
Finding = tuple[str, int, str]


def _tracked_markdown_files(repo_root: Path = REPO_ROOT) -> list[str]:
    """Every tracked Markdown file, repo-relative, via `git ls-files '*.md'`.

    `git ls-files` (not a filesystem walk) is what makes a symlinked
    directory count once: git tracks a symlinked directory as a single
    symlink blob and does not enumerate files beneath it, so e.g.
    `python/.agents/skills/...` never shows up as a duplicate of
    `common/.agents/skills/...`. No manual dedup logic is needed.
    """
    result = subprocess.run(
        ["git", "-C", str(repo_root), "ls-files", "*.md"],
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in result.stdout.splitlines() if line]


# -- Category 1: local Markdown links ---------------------------------------

_LINK_RE = re.compile(r"\]\(([^)]+)\)")


def _is_relative_link(target: str) -> bool:
    """True if `target` is a same-repo relative path this check should validate.

    Excludes external links (http/https/mailto/protocol-relative), pure
    anchor links (`#section`), and root-absolute paths (`/foo`) -- the latter
    are ambiguous between "repo root" and "filesystem root" and are not what
    "relative link" means here.
    """
    if not target:
        return False
    if target.startswith(("http://", "https://", "mailto:", "//")):
        return False
    if target.startswith("#"):
        return False
    return not target.startswith("/")


def find_markdown_link_findings(repo_root: Path = REPO_ROOT) -> list[Finding]:
    """Return one finding per relative Markdown link that fails to resolve.

    Resolution is relative to the *linking file's* directory, matching how
    Markdown renderers (and GitHub) resolve relative links -- not repo root.
    A `#fragment` suffix is stripped before resolution and never validated
    (anchor resolution is out of scope; see the module docstring).
    """
    findings: list[Finding] = []
    for rel in _tracked_markdown_files(repo_root):
        abs_path = repo_root / rel
        try:
            text = abs_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        base_dir = abs_path.parent
        for line_no, line in enumerate(text.splitlines(), start=1):
            for match in _LINK_RE.finditer(line):
                raw = match.group(1).strip()
                # Drop an optional Markdown title, e.g. `path "title"` -- the
                # link target is always the first whitespace-delimited token.
                target = raw.split()[0] if raw.split() else raw
                if not _is_relative_link(target):
                    continue
                file_part = target.split("#", 1)[0]
                if not file_part:
                    continue
                resolved = base_dir / file_part
                if resolved.exists():
                    continue
                # A broken symlink and an outright-missing path are both
                # findings, but distinguished in the message: this repo uses
                # symlinks heavily, and "the file was never there" versus
                # "the file was there and the link rotted" point a maintainer
                # at different fixes.
                kind = "broken symlink" if resolved.is_symlink() else "missing file"
                findings.append(
                    (
                        rel,
                        line_no,
                        f"link target '{target}' does not resolve ({kind}: {file_part})",
                    )
                )
    return findings


# -- Category 2: Raven CLI subcommands and flags -----------------------------

_FENCE_RE = re.compile(r"^\s*```")
_INLINE_CODE_RE = re.compile(r"`([^`]+)`")
# A '#' that starts a shell comment: not immediately preceded by a non-space
# character, so it can't fire mid-token (e.g. inside a URL fragment).
_COMMENT_RE = re.compile(r"(?<!\S)#")
_ENV_ASSIGNMENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")


def _strip_shell_comment(line: str) -> str:
    """Drop a trailing `# comment` from a shell-style line, if present."""
    match = _COMMENT_RE.search(line)
    return line[: match.start()] if match else line


def _iter_candidate_texts(text: str):
    """Yield (line_no, candidate_text) for every place an invocation could live.

    Two recognized forms, matching how this repo actually writes examples:
    fenced code blocks (```sh ... ```, scanned line by line) and inline code
    spans (`` `raven doctor --json` ``) outside of a fence. Inline spans
    inside a fence are not scanned separately -- the whole-line scan already
    covers that text, and re-scanning would only produce duplicate findings.
    Prose that merely *mentions* a flag or subcommand without backticks (or a
    fence) is never a candidate at all, by construction.
    """
    in_fence = False
    for line_no, raw_line in enumerate(text.splitlines(), start=1):
        if _FENCE_RE.match(raw_line):
            in_fence = not in_fence
            continue
        if in_fence:
            yield line_no, raw_line
        else:
            for match in _INLINE_CODE_RE.finditer(raw_line):
                yield line_no, match.group(1)


def _extract_invocation_args(candidate: str) -> list[str] | None:
    """Tokenize `candidate`; return the raven argv (after the program name), or None.

    Recognizes three spellings seen in this repo's docs: `raven ...`,
    `python scripts/raven.py ...` (any path ending `raven.py`, matching the
    `"$RAVEN_TEMPLATE/scripts/raven.py"` form language READMEs use), and
    either spelling prefixed by shell `VAR=value` assignments (e.g.
    `PYTHONDONTWRITEBYTECODE=1 python scripts/raven.py ...`, used in
    project-skills/template-verifier/SKILL.md). A leading `$ ` shell prompt
    and a trailing `# comment` are stripped first. Returns None (not a raven
    invocation, or unparseable shell text) rather than raising -- this
    function must never be the reason the checker crashes on a doc file.
    """
    text = _strip_shell_comment(candidate).strip()
    if text.startswith("$ "):
        text = text[2:].strip()
    if not text:
        return None
    try:
        tokens = shlex.split(text)
    except ValueError:
        return None
    while tokens and _ENV_ASSIGNMENT_RE.match(tokens[0]):
        tokens = tokens[1:]
    if not tokens:
        return None
    if tokens[0] == "raven":
        return tokens[1:]
    if tokens[0] in ("python", "python3") and len(tokens) > 1 and tokens[1].endswith("raven.py"):
        return tokens[2:]
    return None


def _nargs_count(action: argparse.Action) -> int:
    """How many following tokens `action`'s flag consumes: 0 for store_true, else 1.

    Every optional flag this CLI defines is either a `store_true` switch
    (`action.nargs == 0`) or a single-value store (`action.nargs is None`,
    consuming exactly one token, e.g. `--platform github`). No flag here uses
    `nargs='*'`/`'+'`/`'?'`, so those are not specially handled.
    """
    if action.nargs is None:
        return 1
    if isinstance(action.nargs, int):
        return action.nargs
    return 1


def _parser_maps(
    parser: argparse.ArgumentParser,
) -> tuple[set[str], dict[str, set[str]], set[str], dict[str, int]]:
    """Derive (subcommands, per-subcommand flags, global flags, flag nargs) from `parser`.

    Subcommand names come from the subparsers action's `choices`; each
    subparser's flags come from its own `_actions` -- both are the parser's
    own ground truth, not a restatement of it, so this can never drift from
    what `raven` actually accepts the way a hand-written manifest could.
    """
    global_flags: set[str] = set()
    flag_nargs: dict[str, int] = {}
    subparsers_action: argparse._SubParsersAction | None = None
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            subparsers_action = action
            continue
        for opt in action.option_strings:
            global_flags.add(opt)
            flag_nargs[opt] = _nargs_count(action)
    if subparsers_action is None:
        raise RuntimeError("raven's parser has no subcommands action")

    subcommands = set(subparsers_action.choices.keys())
    per_command_flags: dict[str, set[str]] = {}
    for name, subparser in subparsers_action.choices.items():
        flags: set[str] = set()
        for action in subparser._actions:
            for opt in action.option_strings:
                flags.add(opt)
                flag_nargs[opt] = _nargs_count(action)
        per_command_flags[name] = flags
    return subcommands, per_command_flags, global_flags, flag_nargs


def _validate_invocation(
    args: list[str],
    subcommands: set[str],
    per_command_flags: dict[str, set[str]],
    global_flags: set[str],
    flag_nargs: dict[str, int],
) -> list[str]:
    """Validate one already-tokenized raven invocation; return problem messages.

    Global flags (e.g. `--destination`) are accepted before the subcommand,
    matching `python scripts/raven.py --destination ... install ...`.
    Positionals (language names, `<placeholder>` notation, override paths)
    are never validated -- that is the dropped "Raven-owned path references"
    category, not this one. A flag documented against the wrong subcommand
    (e.g. `raven doctor --dry-run`, real flag, wrong subcommand) is reported
    distinctly from a flag that does not exist anywhere in the parser.
    """
    all_subcommand_flags: set[str] = set()
    for flags in per_command_flags.values():
        all_subcommand_flags |= flags

    problems: list[str] = []
    subcommand: str | None = None
    i = 0
    while i < len(args):
        token = args[i]
        if token.startswith("-"):
            if subcommand is None:
                if token not in global_flags:
                    problems.append(f"unknown global flag '{token}'")
                i += 1 + flag_nargs.get(token, 0)
                continue
            allowed = global_flags | per_command_flags.get(subcommand, set())
            if token not in allowed:
                if token in all_subcommand_flags:
                    problems.append(
                        f"flag '{token}' is not valid for 'raven {subcommand}' "
                        "(defined for a different subcommand)"
                    )
                else:
                    problems.append(f"unknown flag '{token}' for 'raven {subcommand}'")
            i += 1 + flag_nargs.get(token, 0)
            continue
        if subcommand is None:
            if token not in subcommands:
                problems.append(f"unknown subcommand '{token}'")
                return problems
            subcommand = token
        i += 1
    return problems


def find_cli_doc_findings(repo_root: Path = REPO_ROOT) -> list[Finding]:
    """Return one finding per documented `raven`/`raven.py` example that misuses the CLI.

    Validates against the real parser returned by `raven_lib.cli.build_parser`,
    never a restated list of subcommands/flags -- see that function's
    docstring for why.
    """
    subcommands, per_command_flags, global_flags, flag_nargs = _parser_maps(build_parser())
    findings: list[Finding] = []
    for rel in _tracked_markdown_files(repo_root):
        abs_path = repo_root / rel
        try:
            text = abs_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for line_no, candidate in _iter_candidate_texts(text):
            args = _extract_invocation_args(candidate)
            if not args:
                continue
            problems = _validate_invocation(
                args, subcommands, per_command_flags, global_flags, flag_nargs
            )
            findings.extend((rel, line_no, problem) for problem in problems)
    return findings


# -- Reporting ----------------------------------------------------------------


def _report(findings: list[Finding]) -> None:
    """Print one `file:line: message` diagnostic per finding, to stderr."""
    for path, line_no, message in findings:
        print(f"{path}:{line_no}: {message}", file=sys.stderr)


def main() -> int:
    """Run both checks, report findings on stderr, and return an exit code."""
    try:
        findings = find_markdown_link_findings() + find_cli_doc_findings()
    except (subprocess.CalledProcessError, OSError) as exc:
        print(f"error: check-guidance: could not run: {exc}", file=sys.stderr)
        return 2
    if findings:
        _report(findings)
        print(f"check-guidance: {len(findings)} finding(s)", file=sys.stderr)
        return 1
    print("check-guidance: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
