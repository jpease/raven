#!/usr/bin/env python3

from __future__ import annotations

import datetime
import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RAVEN_SCRIPT = REPO_ROOT / "scripts" / "raven.py"


def run(label: str, args: list[str]) -> subprocess.CompletedProcess[str]:
    print(f"==> {label}")
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    result = subprocess.run(
        args,
        cwd=REPO_ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    print(result.stdout, end="")
    if result.returncode != 0:
        raise SystemExit(result.returncode)
    return result


def load_raven_module():
    scripts_dir = str(RAVEN_SCRIPT.parent)
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    import raven_lib

    return raven_lib


def validate_shared_docs_sync() -> None:
    print("==> validate shared docs are in sync with common/")
    non_template_dirs = load_raven_module().NON_TEMPLATE_DIRS
    common_docs = REPO_ROOT / "common" / ".claude" / "docs"
    language_dirs = [
        d
        for d in REPO_ROOT.iterdir()
        if d.is_dir() and not d.name.startswith(".") and d.name not in non_template_dirs
    ]
    mismatches: list[str] = []
    for lang_dir in sorted(language_dirs):
        lang_docs = lang_dir / ".claude" / "docs"
        if not lang_docs.is_dir():
            continue
        for doc in lang_docs.iterdir():
            common_copy = common_docs / doc.name
            if not common_copy.exists():
                continue
            if doc.read_bytes() != common_copy.read_bytes():
                mismatches.append(
                    f"{doc.relative_to(REPO_ROOT)} differs from common/.claude/docs/{doc.name}"
                )
    if mismatches:
        for m in mismatches:
            print(f"  MISMATCH: {m}")
        raise SystemExit("Shared docs are out of sync with common/. Update both copies.")
    print("shared docs sync ok")


def validate_context_budget() -> None:
    # always-loaded tier — raise thresholds only with deliberate justification
    THRESHOLDS: dict[str, int] = {
        "common/AGENTS.md": 1110,
        # language-specific rules files
        "python/.claude/rules/raven-python.md": 760,
        "elixir/.claude/rules/raven-elixir.md": 890,
        "rust/.claude/rules/raven-rust.md": 820,
        "swift/.claude/rules/raven-swift.md": 640,
        "typescript/.claude/rules/raven-typescript.md": 660,
        # shared rules files (symlinked from language dirs)
        "common/.claude/rules/raven-security.md": 70,
        "common/.claude/rules/raven-tests.md": 70,
    }
    print("==> validate context budget for always-loaded guidance")
    offenders: list[str] = []
    for rel, limit in THRESHOLDS.items():
        path = REPO_ROOT / rel
        if not path.exists():
            print(f"  WARNING: {rel} not found, skipping budget check")
            continue
        text = path.read_text(encoding="utf-8")
        count = len(text.split())
        if count > limit:
            offenders.append(f"  {rel}: {count} words (limit {limit})")
    if offenders:
        for line in offenders:
            print(line)
        raise SystemExit(
            "Context budget exceeded. Trim always-loaded guidance or raise thresholds with justification."
        )
    print("context budget ok")


def validate_installed_shape() -> None:
    print("==> validate installed RAVEN shape")
    raven = load_raven_module()
    agents = REPO_ROOT / "AGENTS.md"
    claude = REPO_ROOT / "CLAUDE.md"
    claude_skills = REPO_ROOT / ".claude" / "skills"

    if not agents.is_file():
        raise SystemExit("AGENTS.md is missing")
    block = raven.find_raven_block(agents.read_text(encoding="utf-8"))
    if block is None:
        raise SystemExit("AGENTS.md is missing a RAVEN-managed block")
    if not raven.raven_block_is_unchanged(block):
        raise SystemExit("AGENTS.md RAVEN-managed block was edited directly")
    if not claude.is_symlink() or os.readlink(claude) != "AGENTS.md":
        raise SystemExit("CLAUDE.md must be a symlink to AGENTS.md")
    if not claude_skills.is_symlink() or os.readlink(claude_skills) != "../.agents/skills":
        raise SystemExit(".claude/skills must be a symlink to ../.agents/skills")
    print("installed shape ok")


_LAST_VERIFIED_RE = re.compile(r"Last verified:\s*(\d{4}-\d{2}-\d{2})")
_FRESHNESS_MAX_DAYS = 180
_FRESHNESS_REQUIRED = {
    "raven-lsp-mcp.md",
    "raven-semgrep.md",
}


def warn_stale_docs() -> None:
    """Non-fatal: warn if third-party setup docs are missing or stale freshness markers."""
    docs_dir = REPO_ROOT / "common" / ".claude" / "docs"
    today = datetime.date.today()
    warnings: list[str] = []

    for doc in sorted(docs_dir.glob("*.md")):
        text = doc.read_text(encoding="utf-8")
        m = _LAST_VERIFIED_RE.search(text)
        if m:
            try:
                verified = datetime.date.fromisoformat(m.group(1))
                age = (today - verified).days
                if age > _FRESHNESS_MAX_DAYS:
                    warnings.append(
                        f"  STALE: {doc.name} — last verified {m.group(1)} ({age} days ago)"
                    )
            except ValueError:
                warnings.append(
                    f"  WARN: {doc.name} — unparseable Last verified date: {m.group(1)!r}"
                )
        elif doc.name in _FRESHNESS_REQUIRED:
            warnings.append(f"  MISSING: {doc.name} — no 'Last verified:' marker found")

    if warnings:
        print("==> freshness warnings (non-fatal)")
        for w in warnings:
            print(w)
    else:
        print("==> freshness check ok")


def main() -> int:
    validate_shared_docs_sync()
    validate_context_budget()
    warn_stale_docs()
    validate_installed_shape()
    run(
        "RAVEN self-upgrade dry run",
        [sys.executable, str(RAVEN_SCRIPT), "--destination", ".", "upgrade", "--dry-run"],
    )
    run(
        "RAVEN self-upgrade apply",
        [sys.executable, str(RAVEN_SCRIPT), "--destination", ".", "upgrade"],
    )
    validate_installed_shape()
    run("ruff format check", [sys.executable, "-m", "ruff", "format", "--check", "."])
    run("ruff lint", [sys.executable, "-m", "ruff", "check", "."])
    run("unit tests", [sys.executable, "-m", "unittest", "discover", "-s", "tests"])
    print("RAVEN self-check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
