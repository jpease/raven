from __future__ import annotations

import difflib
import os
from contextlib import suppress
from pathlib import Path
from typing import Literal

from .constants import (
    MERGE_DIR,
    RAVEN_BLOCK_BEGIN_RE,
    RAVEN_BLOCK_END,
    ROOT_INSTRUCTION_FILES,
    _any_exists,
)
from .hashing import sha256_bytes
from .models import RavenBlock, TemplateEntry

BlockState = Literal["identical", "upgradeable", "modified"]


def normalized_block_content(text: str) -> str:
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
    normalized_cells: list[str] = []
    for cell in cells:
        value = cell.strip()
        left = ":" if value.startswith(":") else ""
        right = ":" if value.endswith(":") else ""
        normalized_cells.append(f"{left}---{right}")
    return "|" + "|".join(normalized_cells) + "|"


def comparison_block_content(text: str) -> str:
    normalized_lines: list[str] = []
    for line in normalized_block_content(text).split("\n"):
        table_separator = _normalize_markdown_table_separator(line)
        normalized_lines.append(table_separator if table_separator is not None else line)
    return " ".join(" ".join(normalized_lines).split())


def block_content_matches(left: str, right: str) -> bool:
    return comparison_block_content(left) == comparison_block_content(right)


def raven_block_sha256(text: str) -> str:
    return sha256_bytes(normalized_block_content(text).encode("utf-8"))


def raven_block_begin_for(text: str) -> str:
    return f"<!-- RAVEN:BEGIN sha256={raven_block_sha256(text)} -->"


def raven_managed_block(text: str) -> str:
    content = normalized_block_content(text)
    return "\n".join(["", raven_block_begin_for(content), *content.splitlines(), RAVEN_BLOCK_END])


def find_raven_block(text: str) -> RavenBlock | None:
    lines = text.splitlines()
    for start, line in enumerate(lines):
        match = RAVEN_BLOCK_BEGIN_RE.fullmatch(line.strip())
        if not match:
            continue
        for end in range(start + 1, len(lines)):
            if lines[end].strip() == RAVEN_BLOCK_END:
                return RavenBlock(
                    start=start,
                    end=end,
                    content="\n".join(lines[start + 1 : end]),
                    declared_sha256=match.group(1),
                )
        return None
    return None


def raven_block_is_unchanged(block: RavenBlock) -> bool:
    return block.declared_sha256 == raven_block_sha256(block.content)


def block_managed_state(entry: TemplateEntry, target: Path) -> BlockState | None:
    if (
        entry.relative not in ROOT_INSTRUCTION_FILES
        or entry.copy_as_symlink
        or not target.is_file()
    ):
        return None
    try:
        target_text = target.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        # An unreadable or non-UTF-8 destination file has no managed block we can
        # detect. Report "no block state" rather than crash; classify() falls back
        # to its hash-based/unknown_existing path for a file like this.
        return None
    block = find_raven_block(target_text)
    if block is None:
        return None
    source_text = normalized_block_content(entry.source.read_text(encoding="utf-8"))
    block_text = normalized_block_content(block.content)
    if block_text == source_text:
        return "identical" if raven_block_is_unchanged(block) else "upgradeable"
    if block_content_matches(block_text, source_text):
        return "upgradeable"
    if not raven_block_is_unchanged(block):
        return "modified"
    return "upgradeable"


def update_raven_block(entry: TemplateEntry, target: Path) -> None:
    text = target.read_text(encoding="utf-8")
    block = find_raven_block(text)
    source_text = normalized_block_content(entry.source.read_text(encoding="utf-8"))
    if block is None or (
        not raven_block_is_unchanged(block)
        and not block_content_matches(block.content, source_text)
    ):
        raise ValueError(f"cannot safely update modified or missing Raven block: {entry.relative}")
    lines = text.splitlines()
    replacement = raven_managed_block(entry.source.read_text(encoding="utf-8")).splitlines()[1:]
    updated = lines[: block.start] + replacement + lines[block.end + 1 :]
    trailing_newline = "\n" if text.endswith("\n") else ""
    final_content = "\n".join(updated) + trailing_newline
    if target.is_symlink():
        target.unlink()
    target.write_text(final_content, encoding="utf-8")


def template_entry_text(entry: TemplateEntry) -> str:
    if entry.copy_as_symlink:
        target = os.readlink(entry.source)
        return (
            f"# Raven suggested handling for `{entry.relative}`\n\n"
            f"Raven normally installs `{entry.relative}` as a symlink to `{target}`.\n\n"
            "Because this file already exists in the destination repository, Raven did not replace it. "
            "Review the existing file and decide whether to keep it, merge guidance from AGENTS.md, "
            "or manually convert it to the symlink/pointer your agent tooling expects.\n"
        )
    return entry.source.read_text(encoding="utf-8")


def append_patch_text(relative: str, existing_text: str, raven_text: str) -> str:
    """Build a ``patch``-appliable hunk that installs the current Raven block.

    If the file already contains a managed block, the hunk **replaces** that block
    in place; appending a second one would leave two ``RAVEN:BEGIN`` blocks (#55).
    Only a file with no block yet gets an append hunk.
    """
    existing_lines = existing_text.splitlines()
    block = find_raven_block(existing_text)
    if block is not None:
        # Replace the existing block region (BEGIN..END inclusive) in place. Drop
        # the leading blank separator that ``raven_managed_block`` prepends -- the
        # blank already precedes the existing block in the file.
        new_lines = raven_managed_block(raven_text).splitlines()[1:]
        old_lines = existing_lines[block.start : block.end + 1]
        start = block.start + 1
        patch_lines = [
            f"--- a/{relative}",
            f"+++ b/{relative}",
            f"@@ -{start},{len(old_lines)} +{start},{len(new_lines)} @@",
            *[f"-{line}" for line in old_lines],
            *[f"+{line}" for line in new_lines],
            "",
        ]
        return "\n".join(patch_lines)
    block_lines = raven_managed_block(raven_text).splitlines()
    start = len(existing_lines) + 1
    count = len(block_lines)
    patch_lines = [
        f"--- a/{relative}",
        f"+++ b/{relative}",
        f"@@ -{len(existing_lines)},0 +{start},{count} @@",
        *[f"+{line}" for line in block_lines],
        "",
    ]
    return "\n".join(patch_lines)


def unified_diff_text(relative: str, existing_text: str, template_text: str) -> str:
    """Build a review-only unified diff from the local file to the template version.

    Unlike ``append_patch_text``, this is informational: it shows how the existing
    file differs from the Raven template version. It is not meant to be applied
    with ``patch`` -- arbitrary JSON/TOML/etc. files have no managed block to
    append to, so the user merges by hand.
    """
    diff = difflib.unified_diff(
        existing_text.splitlines(keepends=True),
        template_text.splitlines(keepends=True),
        fromfile=f"{relative} (your version)",
        tofile=f"{relative} (Raven template)",
    )
    return "".join(diff)


def guided_merge_instructions(
    relative: str,
    suggestion: str,
    patch: str | None,
    diff: str | None = None,
    *,
    replaces_block: bool = False,
) -> str:
    """Build the guided-merge instructions body for an existing file.

    Pure. At most one of ``patch``/``diff`` is set:
    ``patch`` is the relative path of a managed-block patch (instruction files
    only); ``diff`` is the relative path of a review-only unified diff (all other
    files); both ``None`` means only a fully manual merge is possible.
    ``replaces_block`` is True when the file already has a managed block the patch
    replaces in place (vs appending a new one).
    """
    header = (
        f"# Guided Raven merge for `{relative}`\n\n"
        f"Raven found an existing `{relative}` and did not modify it.\n\n"
    )
    if patch is None and diff is not None:
        return (
            header + f"- Existing file: `{relative}`\n"
            f"- Raven template version for review: `{suggestion}`\n"
            f"- What differs from the template: `{diff}`\n\n"
            "## Manual merge\n\n"
            f"`{relative}` is not a managed-block instruction file, so Raven cannot apply an "
            "automatic patch. Review the diff to see exactly what changed:\n\n"
            f"```sh\ncat {diff}\n```\n\n"
            f"Then copy whatever applies from `{suggestion}` into `{relative}` manually.\n\n"
            f"When done, run `raven accept {relative}` (or `raven accept` to accept every "
            "pending merge). This records your merged file as the new baseline and removes "
            "these artifacts, so future upgrades will not prompt again until the template "
            "changes.\n\n"
            "Do not apply the template blindly if the repository already has stronger local settings.\n"
        )
    if patch is not None:
        patch_label = "Block-update patch" if replaces_block else "Append-only patch"
        effect = (
            "This replaces the existing `RAVEN:BEGIN` / `RAVEN:END` managed block in place."
            if replaces_block
            else "This appends a `RAVEN:BEGIN` / `RAVEN:END` managed block to the existing file."
        )
        return (
            header + f"- Existing file: `{relative}`\n"
            f"- Raven suggestion for review: `{suggestion}`\n"
            f"- {patch_label}: `{patch}`\n\n"
            "## Recommended automatic merge\n\n"
            "From the destination repository root, inspect the patch first:\n\n"
            f"```sh\npatch --dry-run -p1 < {patch}\n```\n\n"
            "If the dry run succeeds and the Raven guidance is appropriate, apply it:\n\n"
            f"```sh\npatch -p1 < {patch}\n```\n\n"
            f"{effect} "
            "Future Raven upgrades can update that block automatically as long as it is not edited directly.\n\n"
            "## Manual merge option\n\n"
            f"Review `{suggestion}` and copy only the guidance that applies. If you do this without "
            "the managed block markers, "
            "Raven will not be able to upgrade that content automatically later.\n\n"
            f"Either way, run `raven accept {relative}` (or `raven accept`) afterwards to remove "
            "these artifacts.\n\n"
            "Do not apply the suggestion blindly if the repository already has stronger local instructions.\n"
        )
    return (
        header + f"- Existing file: `{relative}`\n"
        f"- Raven suggestion for review: `{suggestion}`\n\n"
        "Raven could not generate an automatic text patch for this file. Review the suggestion "
        "and manually merge the guidance that applies.\n\n"
        "Do not apply the suggestion blindly if the repository already has stronger local instructions.\n"
    )


def _existing_ignore_patterns(text: str) -> set[str]:
    """Effective ignore patterns from .gitignore text.

    Compares by exact pattern, not substring, so a comment or a longer path
    that merely contains an entry does not count as the entry (see #43).
    """
    patterns = set()
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        patterns.add(line)
    return patterns


def _ensure_merge_dir_gitignored(destination: Path) -> None:
    """Ignore MERGE_DIR in the destination's .gitignore.

    Guided-merge scratch artifacts are transient review material, not
    something meant to be committed. Without this, a broad `git add` run
    before `raven accept` picks them up as ordinary untracked files.
    """
    entry = f"{MERGE_DIR.as_posix()}/"
    gitignore = destination / ".gitignore"
    existing = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
    if entry in _existing_ignore_patterns(existing):
        return
    prefix = "" if not existing or existing.endswith("\n") else "\n"
    block = f"{prefix}\n# Raven guided-merge scratch artifacts\n{entry}\n"
    with gitignore.open("a", encoding="utf-8") as f:
        f.write(block)


def _write_merge_artifact(path: Path, text: str) -> None:
    """Write a merge artifact, replacing a symlink in place.

    A merge-state path that is a symlink would route the write outside the
    destination. Unlinking it first keeps every guided-merge write inside
    ``.raven/merge/``.
    """
    if path.is_symlink():
        path.unlink()
    path.write_text(text, encoding="utf-8")


def write_guided_merge_artifacts(
    destination: Path, entries: dict[str, TemplateEntry], paths: list[str]
) -> list[str]:
    written: list[str] = []
    merge_dir = destination / MERGE_DIR
    for relative in sorted(set(paths)):
        entry = entries.get(relative)
        target = destination / relative
        if entry is None or not _any_exists(target):
            continue
        raven_path = merge_dir / f"{relative}.raven"
        raven_path.parent.mkdir(parents=True, exist_ok=True)
        raven_text = template_entry_text(entry)
        _write_merge_artifact(raven_path, raven_text)
        written.append(raven_path.relative_to(destination).as_posix())

        suggestion = raven_path.relative_to(destination).as_posix()
        patch_rel: str | None = None
        diff_rel: str | None = None
        replaces_block = False
        existing_text: str | None = None
        if not entry.copy_as_symlink and target.is_file():
            try:
                existing_text = target.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                # Unreadable or non-UTF-8 existing file: fall through to the
                # manual-merge-only instructions below rather than crash mid-apply.
                existing_text = None
        if existing_text is not None:
            # Instruction files use RAVEN managed blocks, so a managed-block patch
            # merges cleanly. Any other file gets a review-only diff instead --
            # appending a managed block would corrupt arbitrary JSON/TOML/etc.
            if relative in ROOT_INSTRUCTION_FILES:
                # A file that already has a block gets a replace patch, not an
                # append (which would duplicate the block, #55).
                replaces_block = find_raven_block(existing_text) is not None
                patch_path = merge_dir / f"{relative}.patch"
                _write_merge_artifact(
                    patch_path, append_patch_text(relative, existing_text, raven_text)
                )
                patch_rel = patch_path.relative_to(destination).as_posix()
            else:
                diff_path = merge_dir / f"{relative}.diff"
                _write_merge_artifact(
                    diff_path, unified_diff_text(relative, existing_text, raven_text)
                )
                diff_rel = diff_path.relative_to(destination).as_posix()

        instructions_path = merge_dir / f"{relative}.instructions.md"
        body = guided_merge_instructions(
            relative, suggestion, patch_rel, diff_rel, replaces_block=replaces_block
        )
        _write_merge_artifact(instructions_path, body)
        written.append(instructions_path.relative_to(destination).as_posix())
        if patch_rel:
            written.append(patch_rel)
        if diff_rel:
            written.append(diff_rel)
    if written:
        _ensure_merge_dir_gitignored(destination)
    return written


_MERGE_ARTIFACT_SUFFIXES = (".raven", ".diff", ".patch", ".instructions.md")


def pending_merge_paths(destination: Path) -> list[str]:
    """Destination-relative paths with guided-merge artifacts awaiting acceptance.

    Each merged file has exactly one ``<path>.instructions.md`` artifact, so the
    instruction files are the canonical record of what is still pending.
    """
    merge_dir = destination / MERGE_DIR
    if not merge_dir.is_dir():
        return []
    suffix = ".instructions.md"
    paths = [
        artifact.relative_to(merge_dir).as_posix()[: -len(suffix)]
        for artifact in merge_dir.rglob(f"*{suffix}")
    ]
    return sorted(paths)


def remove_merge_artifacts(destination: Path, paths: list[str]) -> list[str]:
    """Delete the guided-merge artifacts for ``paths`` and prune empty dirs."""
    merge_dir = destination / MERGE_DIR
    removed: list[str] = []
    for relative in paths:
        for suffix in _MERGE_ARTIFACT_SUFFIXES:
            artifact = merge_dir / f"{relative}{suffix}"
            if artifact.exists() or artifact.is_symlink():
                artifact.unlink()
                removed.append(artifact.relative_to(destination).as_posix())
    if merge_dir.is_dir():
        for directory in sorted((p for p in merge_dir.rglob("*") if p.is_dir()), reverse=True):
            with suppress(OSError):
                directory.rmdir()
        with suppress(OSError):
            merge_dir.rmdir()
    return sorted(removed)
