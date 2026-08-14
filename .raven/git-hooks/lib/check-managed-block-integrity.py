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
import importlib.util
import re
import subprocess
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path

_BLOCK_BEGIN_RE = re.compile(r"<!-- RAVEN:BEGIN(?: sha256=([a-f0-9]{64}))? -->")
_BLOCK_END = "<!-- RAVEN:END -->"
_ROOT_INSTRUCTION_FILES = ("AGENTS.md", "CLAUDE.md")


def _normalized_block_content(text: str) -> str:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    return "\n".join(line.rstrip() for line in lines).strip("\n")


def _is_markdown_table_separator_cell(cell: str) -> bool:
    stripped = cell.strip()
    if len(stripped) < 3:
        return False
    inner = stripped.strip(":")
    return bool(inner) and set(inner) == {"-"}


def _normalize_markdown_table_separator(line: str) -> str | None:
    stripped = line.strip()
    if not stripped.startswith("|") or not stripped.endswith("|"):
        return None
    cells = stripped.strip("|").split("|")
    if not cells or not all(_is_markdown_table_separator_cell(cell) for cell in cells):
        return None
    normalized_cells = []
    for cell in cells:
        value = cell.strip()
        left = ":" if value.startswith(":") else ""
        right = ":" if value.endswith(":") else ""
        normalized_cells.append(f"{left}---{right}")
    return "|" + "|".join(normalized_cells) + "|"


def _normalize_markdown_table_row(line: str) -> str | None:
    """Fold a markdown table row to one-space cell padding, or None if not a row.

    A line counts as a table row only if its stripped form both begins and ends
    with ``|`` -- the same judgment _normalize_markdown_table_separator makes,
    so prose containing a pipe (a shell pipeline in a code span, a regex
    alternation) is left alone. Cell text is stripped, never collapsed.
    """
    stripped = line.strip()
    if len(stripped) < 2 or not stripped.startswith("|") or not stripped.endswith("|"):
        return None
    cells = stripped.strip("|").split("|")
    return "| " + " | ".join(cell.strip() for cell in cells) + " |"


def _identity_block_content(text: str) -> str:
    """Whitespace- and table-style-invariant, newline-preserving (issue #118).

    Must stay byte-identical in behavior to ``identity_block_content`` in
    scripts/raven_lib/blocks.py; tests/test_managed_block_integrity_hook.py's
    HookLibraryNormalizationParityTests pins the two together.
    """
    normalized_lines = []
    for line in _normalized_block_content(text).split("\n"):
        folded = _normalize_markdown_table_separator(line)
        if folded is None:
            folded = _normalize_markdown_table_row(line)
        normalized_lines.append(folded if folded is not None else line)
    return "\n".join(normalized_lines)


def _block_sha256(content: str) -> str:
    return hashlib.sha256(_identity_block_content(content).encode("utf-8")).hexdigest()


def _legacy_block_sha256(content: str) -> str:
    """The pre-#118 hash, still accepted so blocks written before it stay valid."""
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


def _raven_config_module():
    """Import the ``raven_config.py`` sibling shipped in this same directory.

    This file already lives at ``.raven/git-hooks/lib/``, the same directory
    ``raven_config.py`` ships in -- a fixed, flat sibling resolution, the
    same one ``check-ai-attribution-content.py``'s own ``_raven_config_module``
    uses for the same reason (this file has no adapter-directory ambiguity
    to resolve, unlike ``raven-tool-check.py``). This script did not need
    the shared config parser before issue #202; it needs it now only for
    ``resolve_repo_root``. Same ``spec_from_file_location`` +
    ``SourceFileLoader`` mechanism used throughout the other rewired
    callers.
    """
    path = Path(__file__).resolve().parent / "raven_config.py"
    spec = importlib.util.spec_from_file_location(
        "raven_config_for_managed_block_integrity",
        path,
        loader=SourceFileLoader("raven_config_for_managed_block_integrity", str(path)),
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"could not load raven_config from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _repo_root() -> Path:
    """The project root for this checkout, via the shared parent-directory walk.

    This script always ships at ``<root>/.raven/git-hooks/lib/``, a fixed
    offset -- three parents up from this file's own directory is the
    candidate root. Passed as ``start`` to the shared
    ``raven_config.resolve_repo_root``, which confirms it (or walks further
    up, e.g. if the hook were relocated) rather than trusting the fixed
    offset blindly. Unlike the ``git rev-parse --show-toplevel`` subprocess
    this replaces, the shared walk never shells out to git, so it is immune
    to an inherited ``GIT_DIR``/``GIT_WORK_TREE`` corrupting the answer --
    see that function's own docstring for why that class of bug motivated
    dropping the subprocess call entirely (issue #202).
    """
    candidate = Path(__file__).resolve().parents[3]
    return _raven_config_module().resolve_repo_root(candidate)


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
    """Pre-commit entry point: fail if any staged root instruction file's managed block was hand-edited."""
    root = _repo_root()

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
        # Accept the legacy hash too: blocks written before the #118 identity
        # change declare it, and the hook has no template at commit time to
        # tell "stale marker" from "hand-edited". `raven upgrade` migrates the
        # marker to the current hash.
        if declared_sha256 is None or declared_sha256 not in (
            _block_sha256(content),
            _legacy_block_sha256(content),
        ):
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
