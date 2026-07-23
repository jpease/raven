#!/usr/bin/env python3
"""Detect direct edits inside a RAVEN:BEGIN/RAVEN:END managed block.

AGENTS.md documents that the managed block is template content to be updated
via the source template, not edited in place -- but nothing enforced that in a
destination repository. Raven's own self-check catches this for its own
AGENTS.md; this is the same check (declared sha256 vs. recomputed hash),
reimplemented standalone since destination repos do not have scripts/raven_lib.
"""

from __future__ import annotations

import hashlib
import re
import subprocess
import sys
from pathlib import Path

_BLOCK_BEGIN_RE = re.compile(r"<!-- RAVEN:BEGIN(?: sha256=([a-f0-9]{64}))? -->")
_BLOCK_END = "<!-- RAVEN:END -->"
_ROOT_INSTRUCTION_FILES = ("AGENTS.md", "CLAUDE.md")


def _normalized_block_content(text: str) -> str:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    return "\n".join(line.rstrip() for line in lines).strip("\n")


def _block_sha256(content: str) -> str:
    return hashlib.sha256(_normalized_block_content(content).encode("utf-8")).hexdigest()


def _find_block(text: str) -> tuple[str | None, str] | None:
    """Return (declared_sha256, content) for the first RAVEN block, if any."""
    lines = text.splitlines()
    for start, line in enumerate(lines):
        match = _BLOCK_BEGIN_RE.fullmatch(line.strip())
        if not match:
            continue
        for end in range(start + 1, len(lines)):
            if lines[end].strip() == _BLOCK_END:
                return match.group(1), "\n".join(lines[start + 1 : end])
        return None
    return None


def _repo_root() -> Path | None:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=False
    )
    return Path(result.stdout.strip()) if result.returncode == 0 else None


def main() -> int:
    root = _repo_root()
    if root is None:
        return 0

    tampered: list[str] = []
    for name in _ROOT_INSTRUCTION_FILES:
        path = root / name
        if path.is_symlink() or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        block = _find_block(text)
        if block is None:
            continue
        declared_sha256, content = block
        if declared_sha256 is None or declared_sha256 != _block_sha256(content):
            tampered.append(name)

    if not tampered:
        return 0

    for name in tampered:
        print(
            f"{name}: the RAVEN:BEGIN/RAVEN:END managed block was edited directly.",
            file=sys.stderr,
        )
    print(
        "Update the source template instead, then run `raven upgrade` to "
        "regenerate the block (see AGENTS.md's Local Instruction Boundary).",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
