#!/usr/bin/env python3
"""Block AI attribution mentions from leaking into staged/outbound file content.

The commit-msg hook only cleans commit *message* trailers -- an AI-authorship
credit left in a source file or README (an AI tool named as the generator)
would still reach history untouched. Unlike commit-msg, this fails the
commit/push rather than silently editing tracked file content: there is no
safe way to auto-rewrite an arbitrary line inside a source file.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

_CONTENT_PATTERN = re.compile(
    r"(?:generated|written|authored|implemented|drafted)\s+(?:by|with)\s+.*"
    r"(?:claude|copilot|codex|chatgpt|gpt-[0-9]+|gemini|llama|mistral"
    r"|@anthropic\.com|@openai\.com)",
    re.IGNORECASE,
)

_SECTION_RE = re.compile(r"^\s*\[([^\]]+)\]")
_BOOL_RE = re.compile(r"^\s*(\w+)\s*=\s*(true|false)\b", re.IGNORECASE)


def _read_config_bool(config_path: Path, section: str, key: str, default: bool) -> bool:
    if not config_path.exists():
        return default
    in_section = False
    for line in config_path.read_text(encoding="utf-8").splitlines():
        m = _SECTION_RE.match(line)
        if m:
            in_section = m.group(1).strip() == section
            continue
        if in_section:
            m = _BOOL_RE.match(line)
            if m and m.group(1) == key:
                return m.group(2).lower() == "true"
    return default


def _repo_root() -> Path | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
        )
        return Path(result.stdout.strip())
    except subprocess.CalledProcessError:
        return None


def _git(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], capture_output=True, text=True)


def _added_lines(diff_text: str) -> list[str]:
    # Unified diff: "+++ " is the new-file header, not an added line; every
    # other "+"-prefixed line is content actually entering the tree.
    return [
        line
        for line in diff_text.splitlines()
        if line.startswith("+") and not line.startswith("+++")
    ]


def _scan(added_lines: list[str], label: str) -> int:
    hits = [line for line in added_lines if _CONTENT_PATTERN.search(line)]
    if not hits:
        return 0
    print(f"Forbidden AI attribution content found in {label}:", file=sys.stderr)
    for hit in hits:
        print(hit, file=sys.stderr)
    print(
        "remove generated-attribution mentions from newly added repository text",
        file=sys.stderr,
    )
    return 1


def _scan_staged() -> int:
    diff = _git(["diff", "--cached", "--no-color", "--unified=0", "--", "."])
    return _scan(_added_lines(diff.stdout), "staged diff")


def _outbound_range() -> str | None:
    upstream = _git(["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"])
    if upstream.returncode == 0 and upstream.stdout.strip():
        return f"{upstream.stdout.strip()}..HEAD"
    if _git(["show-ref", "--verify", "--quiet", "refs/remotes/origin/main"]).returncode == 0:
        return "origin/main..HEAD"
    return None


def _scan_outbound() -> int:
    range_spec = _outbound_range()
    if range_spec is None:
        # No upstream and no origin/main to diff against; nothing to compare, so
        # skip rather than block a push this hook cannot meaningfully evaluate.
        return 0
    diff = _git(["diff", "--no-color", "--unified=0", range_spec, "--", "."])
    return _scan(_added_lines(diff.stdout), f"git diff ({range_spec})")


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode not in ("staged", "outbound"):
        print("usage: check-ai-attribution-content.py {staged|outbound}", file=sys.stderr)
        return 1

    root = _repo_root()
    if root is not None:
        config = root / ".raven" / "config.toml"
        if not _read_config_bool(config, "git_hooks", "block_ai_attribution_content", default=True):
            return 0

    return _scan_staged() if mode == "staged" else _scan_outbound()


if __name__ == "__main__":
    sys.exit(main())
