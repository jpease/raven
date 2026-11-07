#!/usr/bin/env python3
"""Mechanical checks for the raven-review-prose skill.

Subcommands:

  scope --base REF FILE:LINE[-END]...  was each line written by this change?
  vale [--config INI] FILE...          Vale word pass, with unsynced packages named
  sweep [--only CHECK] FILE...         long-word, contrast, participle, essence, stakes
  subjects [-n N]                      the `X, not Y` tag in recent commit subjects

Exit codes: 0 clean, 1 at least one finding, 2 the check could not run;
`scope` reports verdicts, not findings, so it exits 0 or 2 and `vale` passes
Vale's own code through. Standard library only, Python 3.9+.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

#: Where the installed raven-write-prose skill keeps its Vale config, relative
#: to the repo root this script's adapter directory sits in.
DEFAULT_VALE_CONFIG = Path(".agents/skills/raven-write-prose/reference/vale/.vale.ini")

CONTRAST_TAIL = r",\s+(?:not|never|rather\s+than|instead\s+of)\b"

#: Phrase checks. All case-insensitive: "At its core" opens a sentence far
#: more often than it sits mid-line, and Title Case headings write ", Not".
PHRASE_CHECKS = {
    "contrast": re.compile(r"\b(?:rather\s+than|instead\s+of)\b", re.IGNORECASE),
    "participle": re.compile(
        r",\s+(?:ensuring|improving|enabling|allowing|reflecting|highlighting|making)\b",
        re.IGNORECASE,
    ),
    "essence": re.compile(
        r"\bwhat\s+(?:this|that|it)(?:['\u2019]s)?\s+(?:really|actually)\s+(?:means|is|matters)\b"
        r"|\bat\s+(?:its|their)\s+core\b"
        r"|\b(?:boils|comes)\s+down\s+to\b"
        r"|\bthe\s+real\s+(?:question|issue)\s+is\b",
        re.IGNORECASE,
    ),
    "stakes": re.compile(
        r"\bchanges\s+everything\b|\bcannot\s+be\s+overstated\b|\bprofound\s+implications\b"
        r"|\bwatershed\s+moment\b|\bgame-?changer\b|\bpivotal\s+moment\b"
        r"|\bmarks\s+a\s+turning\s+point\b",
        re.IGNORECASE,
    ),
}
HEADING_CONTRAST = re.compile(CONTRAST_TAIL, re.IGNORECASE)
SUBJECT_CONTRAST = re.compile(CONTRAST_TAIL, re.IGNORECASE)
#: Lowercase or Capitalized, nine letters or more. Capitals catch the
#: sentence-opening "Additionally"; ALLCAPS and camelCase identifiers stay out.
LONG_WORD = re.compile(r"\b[A-Za-z][a-z]{8,}\b")
#: Inline code, link targets, and bare URLs hold identifiers, not prose.
NOT_PROSE = re.compile(r"`[^`]*`|\]\([^)]*\)|https?://\S+")
INLINE_CODE = re.compile(r"`[^`]*`")
HEADING = re.compile(r"^\s{0,3}#{1,6}\s")
FENCE = re.compile(r"^\s*(`{3,}|~{3,})")
#: Front matter delimiters and thematic breaks end a paragraph.
BREAK = re.compile(r"^\s*(?:-{3,}|\*{3,}|_{3,})\s*$")
CHECKS = ("long-word", "contrast-heading", *PHRASE_CHECKS)
CONTEXT_CHARS = 40
BLAME_HEADER = re.compile(r"^([0-9a-f]{40,64}) \d+ (\d+)")


def prose_lines(text: str) -> list[tuple[int, str]]:
    """Return ``(line_no, line)`` for every line outside a fenced code block."""
    kept: list[tuple[int, str]] = []
    fence = ""
    for number, line in enumerate(text.splitlines(), start=1):
        match = FENCE.match(line)
        if fence:
            if match and match.group(1)[0] == fence[0] and len(match.group(1)) >= len(fence):
                fence = ""
            continue
        if match:
            fence = match.group(1)
            continue
        kept.append((number, "" if BREAK.match(line) else line))
    return kept


def mask_code(text: str) -> str:
    """Blank out inline code spans, keeping offsets, so quoted code never matches."""
    return INLINE_CODE.sub(lambda match: " " * len(match.group(0)), text)


def paragraphs(lines: list[tuple[int, str]]) -> list[tuple[str, list[tuple[int, int]]]]:
    """Join hard-wrapped lines so a phrase broken across them still matches.

    Each paragraph comes back as its joined text plus ``(offset, line_no)``
    starts, so a match offset maps back to the line it begins on. A heading is
    always a paragraph of its own.
    """
    result: list[tuple[str, list[tuple[int, int]]]] = []
    text = ""
    starts: list[tuple[int, int]] = []
    previous = 0

    def flush() -> None:
        nonlocal text, starts
        if text:
            result.append((text, starts))
        text, starts = "", []

    for number, line in lines:
        stripped = line.strip()
        if not stripped or number != previous + 1 or HEADING.match(line):
            flush()
        previous = number
        if not stripped:
            continue
        if text:
            text += " "
        starts.append((len(text), number))
        text += stripped
        if HEADING.match(line):
            flush()
    flush()
    return result


def line_at(starts: list[tuple[int, int]], offset: int) -> int:
    """Return the source line a joined-paragraph offset falls on."""
    number = starts[0][1]
    for start, line_no in starts:
        if start > offset:
            break
        number = line_no
    return number


def snippet(text: str, start: int, end: int) -> str:
    """Return the match with a little context either side."""
    left = max(0, start - CONTEXT_CHARS)
    right = min(len(text), end + CONTEXT_CHARS)
    return ("..." if left else "") + text[left:right] + ("..." if right < len(text) else "")


def sweep_text(text: str, only: tuple[str, ...] = CHECKS) -> list[tuple[int, str, str]]:
    """Return ``(line_no, check, detail)`` findings for one file's text."""
    lines = prose_lines(text)
    findings: list[tuple[int, str, str]] = []
    if "long-word" in only:
        seen: set[str] = set()
        for number, line in lines:
            for word in LONG_WORD.findall(NOT_PROSE.sub(" ", line)):
                if word.lower() not in seen:
                    seen.add(word.lower())
                    findings.append((number, "long-word", word.lower()))
    for joined, starts in paragraphs(lines):
        masked = mask_code(joined)
        heading = HEADING.match(joined) is not None
        if "contrast-heading" in only and heading and HEADING_CONTRAST.search(masked):
            findings.append((starts[0][1], "contrast-heading", joined))
        for name, pattern in PHRASE_CHECKS.items():
            if name in only:
                findings.extend(
                    (line_at(starts, match.start()), name, snippet(joined, *match.span()))
                    for match in pattern.finditer(masked)
                )
    findings.sort(key=lambda item: (item[0], CHECKS.index(item[1])))
    return findings


def run_sweep(paths: list[str], only: tuple[str, ...]) -> int:
    """Print sweep findings for each path."""
    found = False
    for path in paths:
        try:
            text = Path(path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            print(f"error: {path}: {exc}", file=sys.stderr)
            return 2
        for number, check, detail in sweep_text(text, only):
            found = True
            print(f"{path}:{number}: {check}: {detail}")
    return 1 if found else 0


def git(*args: str) -> subprocess.CompletedProcess[str]:
    """Run git, capturing text output; never raises on a nonzero exit."""
    return subprocess.run(["git", *args], capture_output=True, text=True, check=False)


def run_subjects(count: int) -> int:
    """Print recent commit subjects carrying the `X, not Y` tag."""
    result = git("log", "--format=%h%x09%s", "-n", str(count))
    if result.returncode != 0:
        print(f"error: git log: {result.stderr.strip()}", file=sys.stderr)
        return 2
    found = False
    for row in result.stdout.splitlines():
        sha, _, subject = row.partition("\t")
        if SUBJECT_CONTRAST.search(subject):
            found = True
            print(f"{sha}: {subject}")
    return 1 if found else 0


def parse_target(target: str) -> tuple[str, int, int]:
    """Split ``FILE:LINE`` or ``FILE:START-END`` into its parts."""
    path, sep, span = target.rpartition(":")
    first, _, last = span.partition("-")
    if not sep or not path or not first.isdigit() or (last and not last.isdigit()):
        raise ValueError(f"expected FILE:LINE or FILE:START-END, got {target!r}")
    start, end = int(first), int(last or first)
    if start < 1 or end < start:
        raise ValueError(f"bad line range in {target!r}")
    return path, start, end


def blame_lines(path: str, start: int, end: int, rev: str) -> dict[int, str]:
    """Map each line in the range to the commit that last wrote it.

    Blames the working tree unless ``rev`` is set, so line numbers are the ones
    in the file being read and an uncommitted line maps to the all-zero sha.
    ``-M -C`` follow moved and copied lines back to the commit that wrote them.
    """
    args = ["blame", "-M", "-C", "--porcelain", "-L", f"{start},{end}"]
    if rev:
        args.append(rev)
    result = git(*args, "--", path)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "git blame failed")
    owners: dict[int, str] = {}
    for row in result.stdout.splitlines():
        match = BLAME_HEADER.match(row)
        if match:
            owners[int(match.group(2))] = match.group(1)
    return owners


def new_since_head(path: str) -> bool:
    """True for a working-tree file that HEAD does not track, which blame rejects."""
    return Path(path).is_file() and not git("ls-tree", "HEAD", "--", path).stdout.strip()


def report_new_file(path: str, start: int, end: int) -> None:
    """Every line of a file HEAD lacks came with the change."""
    with open(path, encoding="utf-8", errors="replace") as handle:
        total = sum(1 for _ in handle)
    if end > total:
        raise ValueError(f"line {end} is past the end of {path} ({total} lines)")
    for number in range(start, end + 1):
        print(f"{path}:{number}: in scope (not committed yet)")


def run_scope(base: str, targets: list[str], rev: str) -> int:
    """Print whether each target line predates ``base`` or came with the change."""
    verified = git("rev-parse", "--verify", "--quiet", f"{base}^{{commit}}")
    if verified.returncode != 0:
        print(f"error: base {base!r} does not name a commit", file=sys.stderr)
        return 2
    base_sha = verified.stdout.strip()
    ancestry: dict[str, bool] = {}
    failed = False
    for target in targets:
        try:
            path, start, end = parse_target(target)
            if not rev and new_since_head(path):
                report_new_file(path, start, end)
                continue
            owners = blame_lines(path, start, end, rev)
        except (ValueError, RuntimeError) as exc:
            print(f"error: {target}: {exc}", file=sys.stderr)
            failed = True
            continue
        for number in range(start, end + 1):
            sha = owners.get(number, "")
            if not sha:
                print(f"error: {path}:{number}: no blame entry", file=sys.stderr)
                failed = True
                continue
            if not sha.strip("0"):
                print(f"{path}:{number}: in scope (not committed yet)")
                continue
            if sha not in ancestry:
                check = git("merge-base", "--is-ancestor", sha, base_sha)
                if check.returncode not in (0, 1):
                    print(f"error: {path}:{number}: {check.stderr.strip()}", file=sys.stderr)
                    failed = True
                    continue
                ancestry[sha] = check.returncode == 0
            verdict = "pre-existing" if ancestry[sha] else "in scope"
            print(f"{path}:{number}: {verdict} ({sha[:12]})")
    return 2 if failed else 0


def default_vale_config() -> Path:
    """The Vale config of the repo this script is installed in.

    ``absolute()`` rather than ``resolve()``: in Raven's own tree the Codex and
    Gemini copies are symlinks, and the walk up must start from the link.
    """
    return Path(__file__).absolute().parent.parent.parent / DEFAULT_VALE_CONFIG


def unsynced_packages(config: Path) -> list[str]:
    """Return packages the config declares that are missing from its StylesPath."""
    top: dict[str, str] = {}
    for line in config.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("["):
            break
        key, sep, value = line.partition("=")
        if sep and not line.startswith(("#", ";")):
            top[key.strip()] = value.strip()
    styles = config.parent / top.get("StylesPath", "styles")
    missing = []
    for entry in top.get("Packages", "").split(","):
        name = entry.strip().rstrip("/").rsplit("/", 1)[-1]
        if name.endswith(".zip"):
            name = name[: -len(".zip")]
        if name and not (styles / name).is_dir():
            missing.append(name)
    return missing


def run_vale(config_arg: str, paths: list[str]) -> int:
    """Run Vale when installed, after naming any package whose rules are off."""
    vale = shutil.which("vale")
    if vale is None:
        print("vale not installed; skipping the word pass")
        return 0
    config = Path(config_arg) if config_arg else default_vale_config()
    if not config.is_file():
        print(f"error: no Vale config at {config}; pass --config", file=sys.stderr)
        return 2
    missing = unsynced_packages(config)
    for name in missing:
        print(f"vale: package {name} is declared but not synced; its rules are off")
    if missing:
        print(f"vale: run `vale sync` in {config.parent} to turn them on")
    sys.stdout.flush()
    return subprocess.run(
        [vale, f"--config={config}", "--output=line", *paths], check=False
    ).returncode


def build_parser() -> argparse.ArgumentParser:
    """The command-line interface."""
    parser = argparse.ArgumentParser(
        prog="raven-review-prose.py", description="Mechanical checks for raven-review-prose."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    scope = sub.add_parser("scope", help="was each line written by this change?")
    scope.add_argument("--base", required=True, help="the branch point, e.g. main")
    scope.add_argument("--rev", default="", help="blame this commit instead of the working tree")
    scope.add_argument("targets", nargs="+", metavar="FILE:LINE[-END]")

    vale = sub.add_parser("vale", help="Vale word pass, if installed")
    vale.add_argument("--config", default="", help="Vale config; defaults to raven-write-prose's")
    vale.add_argument("paths", nargs="+", metavar="FILE")

    sweep = sub.add_parser("sweep", help="pattern checks over prose, skipping fenced code")
    sweep.add_argument("--only", action="append", choices=CHECKS, help="repeatable")
    sweep.add_argument("paths", nargs="+", metavar="FILE")

    subjects = sub.add_parser("subjects", help="`X, not Y` in recent commit subjects")
    subjects.add_argument("-n", type=int, default=400, dest="count")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Dispatch a subcommand and return its exit code."""
    args = build_parser().parse_args(argv)
    if args.command == "scope":
        return run_scope(args.base, args.targets, args.rev)
    if args.command == "vale":
        return run_vale(args.config, args.paths)
    if args.command == "sweep":
        return run_sweep(args.paths, tuple(args.only or CHECKS))
    return run_subjects(args.count)


if __name__ == "__main__":
    sys.exit(main())
