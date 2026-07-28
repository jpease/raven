#!/usr/bin/env python3
"""Detect direct edits inside a RAVEN:BEGIN/RAVEN:END managed block.

AGENTS.md documents that the managed block is template content to be updated
via the source template, not edited in place -- but nothing enforced that in a
destination repository. Raven's own self-check catches this for its own
AGENTS.md; this is the same check (declared sha256 vs. recomputed hash),
reimplemented standalone since destination repos do not have scripts/raven_lib.

This is invoked from pre-commit, which gates the commit -- so it reads the
staged blob (the git index) for each instruction file, not the working tree.
Reading the working tree would let a tampered block slip through whenever the
worktree happens to be valid at commit time (e.g. an intervening `raven
upgrade` rewrote the file back to a valid block after the tamper was already
staged), even though the staged content -- what actually lands in history --
is still tampered. See check-ai-attribution-content.py's `_scan_staged`, which
reads `git diff --cached` for the same reason.
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


# Staged-file mode bits, as reported by `git ls-files --stage`. Only the
# symlink bit is checked; regular-file modes (100644/100755) are treated the
# same way.
_SYMLINK_MODE = "120000"


def _staged_mode(root: Path, name: str) -> str | None:
    """Return the staged file mode for `name`, or None if it is not staged.

    "Not staged" covers both a path that was never added to the index and a
    path staged for deletion (removed from the index): in either case there
    is nothing under `name` in what is about to be committed, so the caller
    should skip it rather than treat it as block-free.
    """
    result = subprocess.run(
        ["git", "ls-files", "--stage", "--", name],
        capture_output=True,
        cwd=str(root),
        check=False,
    )
    if result.returncode != 0:
        return None
    line = result.stdout.decode("utf-8", errors="replace").strip()
    if not line:
        return None
    # Format: "<mode> <blob-sha> <stage>\t<path>"
    return line.split()[0]


def _staged_text(root: Path, name: str) -> str | None:
    """Return the staged blob content for `name`, decoded as UTF-8.

    Returns None if the blob cannot be read (should not happen once
    `_staged_mode` has already confirmed the path is staged) or is not valid
    UTF-8, mirroring the working-tree read's (OSError, UnicodeDecodeError)
    skip behavior.
    """
    result = subprocess.run(
        ["git", "show", f":{name}"],
        capture_output=True,
        cwd=str(root),
        check=False,
    )
    if result.returncode != 0:
        return None
    try:
        return result.stdout.decode("utf-8")
    except UnicodeDecodeError:
        return None


def main() -> int:
    root = _repo_root()
    if root is None:
        return 0

    tampered: list[str] = []
    for name in _ROOT_INSTRUCTION_FILES:
        mode = _staged_mode(root, name)
        if mode is None or mode == _SYMLINK_MODE:
            # Not staged (untracked, or staged for deletion): nothing under
            # this name is being committed. Staged as a symlink: `git show
            # :name` on a symlink returns the link target text (e.g. literally
            # "AGENTS.md"), not the target file's content, so reading it here
            # would silently treat the symlink as a block-free file. Skip both
            # explicitly rather than relying on that incidental non-match.
            continue
        text = _staged_text(root, name)
        if text is None:
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
