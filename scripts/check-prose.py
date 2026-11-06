#!/usr/bin/env python3
"""Prose budget gate for Raven's own tree.

Raven's prose rules were instructions an agent could read, agree with, and
write around. This script enforces the ones a machine can count. It runs in
`just check-fast` (so the pre-commit hook) and in CI.

A line carrying `raven-hygiene: allow` suppresses a line-level finding on that
line; for a paragraph or a comment block, on any of its lines. File and section
budgets take no marker: split the document instead.

Exit codes: 0 clean, 1 at least one finding, 2 git could not list the tree.
"""

from __future__ import annotations

import re
import subprocess
import sys
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"

if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from gate_limits import limit_lines  # noqa: E402 -- needs the sys.path insert above
from raven_lib.constants import NON_TEMPLATE_DIRS  # noqa: E402 -- needs the sys.path insert above
from staged_diff import has_marker  # noqa: E402 -- needs the sys.path insert above

PARAGRAPH_WORDS = 120
DOC_WORDS = 2_500
SKILL_WORDS = 1_200
AGENTS_SECTION_WORDS = 300
COMMENT_BLOCK_LINES = 10
#: Real `raven-hygiene: allow` markers allowed outside tests/. Lower it freely;
#: raising it is a limit change check-staged-relaxation.py reports.
MARKER_BUDGET = 9

MANAGED_BLOCK_START = "<!-- RAVEN:BEGIN"
REPO_ONLY_TOPS = NON_TEMPLATE_DIRS - {"common"}
REPO_DOCS = {"AGENTS.md", "README.md", "CONTRIBUTING.md", "SECURITY.md"}
SECTION_BUDGET_DOCS = {"AGENTS.md", "common/AGENTS.md"}
#: Shipped into destination repos from outside the template trees.
SHIPPED_EXTRA = {"scripts/raven_lib/data/config.toml.tmpl"}
PLAN_DIRS = ("docs/superpowers/", ".raven/plans/")

MSG_DOC = f"document is {{n}} words (limit {DOC_WORDS}); split or cut it"
MSG_SKILL = f"skill is {{n}} words (limit {SKILL_WORDS}); split or cut it"

MSG_PARAGRAPH = f"paragraph is {{n}} words (limit {PARAGRAPH_WORDS}); split or cut it"
MSG_SECTION = (
    f"section '{{title}}' is {{n}} words (limit {AGENTS_SECTION_WORDS}); keep the rule here "
    "and move mechanism detail into the file it describes"
)
MSG_CONTRAST = (
    "second 'X, not Y' contrast in this section (first at line {first}); state the claim directly"
)
MSG_ISSUE_REF = (
    "bare issue reference '{ref}' in shipped or agent-loaded text; a destination repo "
    "cannot resolve it, so link it or leave the history to the commit message"
)
MSG_COMMENT = (
    f"comment block is {{n}} lines (limit {COMMENT_BLOCK_LINES}); keep the why and move "
    "the history to the commit message"
)
MSG_EMPHASIS = (
    "capitalized '{word}' in shipped or agent-loaded text; shouting a rule signals it fights "
    "the model's training, so state it plainly or enforce it with a check"
)
MSG_REPEAT = (
    "sentence repeats line {first}; restating a rule signals it fights the model's training, "
    "so state it once or enforce it with a check"
)
MSG_PLAN = "agent plan or spec is tracked; keep these in the gitignored .raven/plans/"
MSG_MARKERS = (
    f"{{n}} allow markers outside tests/ (budget {MARKER_BUDGET}); fix the finding instead, "
    "or raise MARKER_BUDGET in a reviewed line"
)
#: A repeated sentence shorter than this is a stock phrase, not a restated rule.
REPEAT_MIN_WORDS = 8

#: One finding: (repo-relative path, 1-indexed line number, message).
Finding = tuple[str, int, str]

_FENCE_RE = re.compile(r"^\s*(```|~~~)")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)")
_LIST_ITEM_RE = re.compile(r"^\s*([-*+]|\d+[.)])\s+")
_QUOTE_RE = re.compile(r"^\s*(>\s?)+")
_RULE_RE = re.compile(r"[-*_]{3,}")
_INLINE_CODE_RE = re.compile(r"`[^`]*`")
_URL_LINK_RE = re.compile(r"\[[^\]]*\]\(https?://[^)]*\)")
_CONTRAST_RE = re.compile(r"[^\s,], not \S")
_ISSUE_REF_RE = re.compile(r"(?<![\w&/#])#\d+\b|\b[Ii]ssues? #?\d+\b")
_WORD_RE = re.compile(r"\S+")
# Hyphen guards keep a description like `MUST-style` from counting as shouting.
_EMPHASIS_RE = re.compile(
    r"(?<![\w-])(MUST|NEVER|ALWAYS|IMPORTANT|CRITICAL|REQUIRED|SHALL|DO NOT)(?![\w-])"
)
_SENTENCE_END_RE = re.compile(r"(?<=[.!?])\s+")
_NON_WORD_RE = re.compile(r"[^\w\s]")


@dataclass
class TrackedFile:
    """One index entry; `regular` is False for a symlink, which shares another file's text."""

    path: str
    regular: bool
    sha: str


def tracked_files(repo_root: Path = REPO_ROOT) -> list[TrackedFile]:
    """Every index entry, so a staged addition is seen before it is committed."""
    out = subprocess.run(
        ["git", "-C", str(repo_root), "ls-files", "-s", "-z"],
        capture_output=True,
        check=True,
    ).stdout.decode("utf-8")
    files = []
    for entry in filter(None, out.split("\0")):
        meta, path = entry.split("\t", 1)
        mode, sha, _stage = meta.split()
        files.append(TrackedFile(path, regular=mode.startswith("100"), sha=sha))
    return files


def staged_texts(repo_root: Path, shas: list[str]) -> dict[str, str | None]:
    """Staged blob text by sha, so the check sees what is being committed; None if not UTF-8."""
    if not shas:
        return {}
    out = subprocess.run(
        ["git", "-C", str(repo_root), "cat-file", "--batch"],
        input="".join(f"{sha}\n" for sha in shas).encode(),
        capture_output=True,
        check=True,
    ).stdout
    texts: dict[str, str | None] = {}
    pos = 0
    for sha in shas:
        header_end = out.index(b"\n", pos)
        size = int(out[pos:header_end].split()[2])
        body = out[header_end + 1 : header_end + 1 + size]
        pos = header_end + 1 + size + 1
        try:
            texts[sha] = body.decode("utf-8")
        except UnicodeDecodeError:
            texts[sha] = None
    return texts


def counts_toward_marker_budget(path: str) -> bool:
    """Test fixtures need markers to exercise detectors; root dot-dirs are install copies."""
    return (not path.startswith(("tests/", ".")) and "/" in path) or path in REPO_DOCS


def _top(path: str) -> str | None:
    return path.split("/", 1)[0] if "/" in path else None


def is_shipped(path: str) -> bool:
    """Template content copied into destination repos: `common/` and each language tree."""
    top = _top(path)
    return top is not None and not top.startswith(".") and top not in REPO_ONLY_TOPS


def is_covered_markdown(path: str) -> bool:
    """Shipped guidance plus the repo's own front-door docs.

    `docs/research/` and `docs/evaluation/` hold dated records and generated
    results; rewriting them to a budget would falsify the record.
    """
    if not path.endswith(".md"):
        return False
    if is_shipped(path) or path in REPO_DOCS or path.startswith("project-skills/"):
        return True
    return path.startswith("docs/") and path.count("/") == 1


def is_covered_python(path: str) -> bool:
    """Shipped hooks and scripts plus Raven's own runtime; tests are out of scope."""
    if not path.endswith(".py"):
        return False
    return is_shipped(path) or _top(path) in {"scripts", "evals", "project-skills"}


@dataclass
class Section:
    """Text under one heading, up to the next heading of any level."""

    title: str
    line: int
    level: int
    words: int = 0
    contrasts: list[int] = field(default_factory=list)


@dataclass
class MarkdownShape:
    """What the budgets measure in one Markdown file."""

    paragraphs: list[tuple[list[int], int]] = field(default_factory=list)
    sections: list[Section] = field(default_factory=list)
    words: int = 0
    issue_refs: list[tuple[int, str]] = field(default_factory=list)
    emphasis: list[tuple[int, str]] = field(default_factory=list)
    #: (first line, paragraph text with inline code masked) for repeat detection.
    texts: list[tuple[int, str]] = field(default_factory=list)


def _prose_lines(lines: list[str]) -> Iterator[tuple[int, str]]:
    """(line_no, text) for lines outside fences and YAML front matter."""
    in_fence = False
    in_front_matter = bool(lines) and lines[0].strip() == "---"
    for line_no, line in enumerate(lines, start=1):
        if in_front_matter:
            if line_no > 1 and line.strip() == "---":
                in_front_matter = False
            continue
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if not in_fence:
            yield line_no, line


def parse_markdown(text: str) -> MarkdownShape:
    """Split prose into paragraphs (a list item is its own) and heading sections."""
    shape = MarkdownShape()
    section = Section(title="(top)", line=1, level=0)
    shape.sections.append(section)
    block_lines: list[int] = []
    block_words = 0
    block_text: list[str] = []

    def flush() -> None:
        nonlocal block_lines, block_words, block_text
        if block_lines:
            shape.paragraphs.append((block_lines, block_words))
            shape.texts.append((block_lines[0], " ".join(block_text)))
        block_lines, block_words, block_text = [], 0, []

    for line_no, raw in _prose_lines(text.splitlines()):
        line = _QUOTE_RE.sub("", raw)
        stripped = line.strip()
        words = len(_WORD_RE.findall(stripped))
        shape.words += words
        heading = _HEADING_RE.match(stripped)
        if heading:
            flush()
            section = Section(heading.group(2).strip(), line_no, len(heading.group(1)))
            shape.sections.append(section)
            continue
        section.words += words
        code_free = _INLINE_CODE_RE.sub("`x`", stripped)
        section.contrasts.extend(line_no for _ in _CONTRAST_RE.finditer(code_free))
        unlinked = _URL_LINK_RE.sub("", code_free)
        shape.issue_refs.extend((line_no, m.group(0)) for m in _ISSUE_REF_RE.finditer(unlinked))
        shape.emphasis.extend((line_no, m.group(0)) for m in _EMPHASIS_RE.finditer(unlinked))
        if not stripped or stripped.startswith(("|", "<")) or _RULE_RE.fullmatch(stripped):
            flush()
            continue
        if _LIST_ITEM_RE.match(line):
            flush()
        block_lines.append(line_no)
        block_words += words
        block_text.append(_LIST_ITEM_RE.sub("", code_free))
    flush()
    return shape


def _allowed(lines: list[str], line_nos: list[int]) -> bool:
    return any(has_marker(lines[n - 1]) for n in line_nos)


def _section_budget_findings(path: str, sections: list[Section]) -> list[Finding]:
    """Budget each `#`/`##` section of an always-loaded instruction file, subsections included."""
    totals: list[tuple[Section, int]] = []
    for section in sections:
        if 1 <= section.level <= 2:
            totals.append((section, 0))
        if totals:
            head, total = totals[-1]
            totals[-1] = (head, total + section.words)
    return [
        (path, head.line, MSG_SECTION.format(title=head.title, n=total))
        for head, total in totals
        if total > AGENTS_SECTION_WORDS
    ]


def _issue_ref_findings(path: str, lines: list[str], refs: list[tuple[int, str]]) -> list[Finding]:
    return [
        (path, line_no, MSG_ISSUE_REF.format(ref=ref))
        for line_no, ref in refs
        if not _allowed(lines, [line_no])
    ]


def _emphasis_findings(path: str, lines: list[str], hits: list[tuple[int, str]]) -> list[Finding]:
    return [
        (path, line_no, MSG_EMPHASIS.format(word=word))
        for line_no, word in hits
        if not _allowed(lines, [line_no])
    ]


def _repeat_findings(path: str, lines: list[str], texts: list[tuple[int, str]]) -> list[Finding]:
    """Flag a sentence of REPEAT_MIN_WORDS+ words that appears again in the same file."""
    first_seen: dict[str, int] = {}
    findings: list[Finding] = []
    for line_no, text in texts:
        for sentence in _SENTENCE_END_RE.split(text):
            key = " ".join(_NON_WORD_RE.sub("", sentence).lower().split())
            if len(key.split()) < REPEAT_MIN_WORDS:
                continue
            if key not in first_seen:
                first_seen[key] = line_no
            elif not _allowed(lines, [line_no]):
                findings.append((path, line_no, MSG_REPEAT.format(first=first_seen[key])))
    return findings


def markdown_findings(path: str, text: str) -> list[Finding]:
    """Budget findings for one Markdown file; root AGENTS.md stops at the managed block."""
    if path == "AGENTS.md":
        text = text.split(MANAGED_BLOCK_START, 1)[0]
    lines = text.splitlines()
    shape = parse_markdown(text)
    findings: list[Finding] = []
    if shape.words > DOC_WORDS:
        findings.append((path, 1, MSG_DOC.format(n=shape.words)))
    elif is_shipped(path) and path.endswith("/SKILL.md") and shape.words > SKILL_WORDS:
        findings.append((path, 1, MSG_SKILL.format(n=shape.words)))
    findings.extend(
        (path, line_nos[0], MSG_PARAGRAPH.format(n=words))
        for line_nos, words in shape.paragraphs
        if words > PARAGRAPH_WORDS and not _allowed(lines, line_nos)
    )
    if path in SECTION_BUDGET_DOCS:
        findings.extend(_section_budget_findings(path, shape.sections))
    for section in shape.sections:
        first, *extra = section.contrasts or [0]
        findings.extend(
            (path, line_no, MSG_CONTRAST.format(first=first))
            for line_no in extra
            if not _allowed(lines, [line_no])
        )
    # Root AGENTS.md is loaded by every agent session, where an issue number is history.
    if is_shipped(path) or path == "AGENTS.md":
        findings.extend(_issue_ref_findings(path, lines, shape.issue_refs))
        findings.extend(_emphasis_findings(path, lines, shape.emphasis))
        findings.extend(_repeat_findings(path, lines, shape.texts))
    return findings


def shipped_text_issue_refs(path: str, text: str) -> list[Finding]:
    """Bare issue references anywhere in a shipped non-Markdown file: comments, docstrings, strings."""
    lines = text.splitlines()
    refs = [
        (line_no, m.group(0))
        for line_no, line in enumerate(lines, start=1)
        for m in _ISSUE_REF_RE.finditer(_URL_LINK_RE.sub("", _INLINE_CODE_RE.sub("`x`", line)))
    ]
    return _issue_ref_findings(path, lines, refs)


def python_findings(path: str, text: str) -> list[Finding]:
    """One finding per run of consecutive comment lines longer than the limit."""
    lines = text.splitlines()
    findings: list[Finding] = []
    block: list[int] = []
    for line_no, line in enumerate([*lines, ""], start=1):
        if line.lstrip().startswith("#") and not (line_no == 1 and line.startswith("#!")):
            block.append(line_no)
            continue
        if len(block) > COMMENT_BLOCK_LINES and not _allowed(lines, block):
            findings.append((path, block[0], MSG_COMMENT.format(n=len(block))))
        block = []
    return findings


def _checks_for(path: str) -> list[Callable[[str, str], list[Finding]]]:
    if is_covered_markdown(path):
        return [markdown_findings]
    checks: list[Callable[[str, str], list[Finding]]] = []
    if is_covered_python(path):
        checks.append(python_findings)
    if is_shipped(path) or path in SHIPPED_EXTRA:
        checks.append(shipped_text_issue_refs)
    return checks


def find_findings(repo_root: Path = REPO_ROOT) -> list[Finding]:
    """Every finding in the staged tree under `repo_root`."""
    findings: list[Finding] = []
    entries = [e for e in tracked_files(repo_root) if not e.path.startswith(PLAN_DIRS)]
    findings.extend(
        (e.path, 1, MSG_PLAN) for e in tracked_files(repo_root) if e.path.startswith(PLAN_DIRS)
    )
    wanted = [
        e
        for e in entries
        if e.regular and (_checks_for(e.path) or counts_toward_marker_budget(e.path))
    ]
    texts = staged_texts(repo_root, list(dict.fromkeys(e.sha for e in wanted)))
    markers = 0
    for entry in wanted:
        text = texts[entry.sha]
        if text is None:
            continue
        if counts_toward_marker_budget(entry.path):
            exempt = limit_lines(entry.path, text)
            markers += sum(
                has_marker(line)
                for line_no, line in enumerate(text.splitlines(), start=1)
                if line_no not in exempt
            )
        for check in _checks_for(entry.path):
            findings.extend(check(entry.path, text))
    if markers > MARKER_BUDGET:
        findings.append(("(tree)", 0, MSG_MARKERS.format(n=markers)))
    return findings


def main() -> int:
    """Report findings on stderr and return the exit code."""
    try:
        findings = find_findings()
    except (subprocess.CalledProcessError, OSError) as exc:
        print(f"error: check-prose: could not run: {exc}", file=sys.stderr)
        return 2
    for path, line_no, message in findings:
        print(f"{path}:{line_no}: {message}", file=sys.stderr)
    if findings:
        print(f"check-prose: {len(findings)} finding(s)", file=sys.stderr)
        return 1
    print("check-prose: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
