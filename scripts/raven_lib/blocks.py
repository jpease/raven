from __future__ import annotations

import os
from pathlib import Path

from .constants import (
    MERGE_DIR,
    RAVEN_BLOCK_BEGIN_RE,
    RAVEN_BLOCK_END,
    ROOT_INSTRUCTION_FILES,
    _any_exists,
)
from .hashing import sha256_bytes
from .models import RavenBlock, TemplateEntry


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
    return "".join("".join(normalized_lines).split())


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


def block_managed_state(entry: TemplateEntry, target: Path) -> str | None:
    if (
        entry.relative not in ROOT_INSTRUCTION_FILES
        or entry.copy_as_symlink
        or not target.is_file()
    ):
        return None
    block = find_raven_block(target.read_text(encoding="utf-8"))
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
    target.write_text("\n".join(updated) + trailing_newline, encoding="utf-8")


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
    existing_lines = existing_text.splitlines()
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


def write_guided_merge_artifacts(
    destination: Path, entries: dict[str, TemplateEntry], paths: list[str]
) -> list[str]:
    written: list[str] = []
    merge_dir = destination / MERGE_DIR
    for relative in sorted(set(paths) & ROOT_INSTRUCTION_FILES):
        entry = entries.get(relative)
        target = destination / relative
        if entry is None or not _any_exists(target):
            continue
        merge_dir.mkdir(parents=True, exist_ok=True)
        raven_path = merge_dir / f"{relative}.raven"
        raven_text = template_entry_text(entry)
        raven_path.write_text(raven_text, encoding="utf-8")
        written.append(raven_path.relative_to(destination).as_posix())

        patch_path = merge_dir / f"{relative}.patch"
        patch_written = False
        if not entry.copy_as_symlink and target.is_file():
            patch_path.write_text(
                append_patch_text(relative, target.read_text(encoding="utf-8"), raven_text),
                encoding="utf-8",
            )
            patch_written = True

        instructions_path = merge_dir / f"{relative}.instructions.md"
        suggestion = raven_path.relative_to(destination).as_posix()
        patch = patch_path.relative_to(destination).as_posix()
        if patch_written:
            body = (
                f"# Guided Raven merge for `{relative}`\n\n"
                f"Raven found an existing `{relative}` and did not modify it.\n\n"
                f"- Existing file: `{relative}`\n"
                f"- Raven suggestion for review: `{suggestion}`\n"
                f"- Append-only patch: `{patch}`\n\n"
                "## Recommended automatic merge\n\n"
                "From the destination repository root, inspect the patch first:\n\n"
                f"```sh\npatch --dry-run -p1 < {patch}\n```\n\n"
                "If the dry run succeeds and the appended Raven guidance is appropriate, apply it:\n\n"
                f"```sh\npatch -p1 < {patch}\n```\n\n"
                "This appends a `RAVEN:BEGIN` / `RAVEN:END` managed block to the existing file. "
                "Future Raven upgrades can update that block automatically as long as it is not edited directly.\n\n"
                "## Manual merge option\n\n"
                f"Review `{suggestion}` and copy only the guidance that applies. If you do this without "
                "the managed block markers, "
                "Raven will not be able to upgrade that content automatically later.\n\n"
                "Do not apply the suggestion blindly if the repository already has stronger local instructions.\n"
            )
        else:
            body = (
                f"# Guided Raven merge for `{relative}`\n\n"
                f"Raven found an existing `{relative}` and did not modify it.\n\n"
                f"- Existing file: `{relative}`\n"
                f"- Raven suggestion for review: `{suggestion}`\n\n"
                "Raven could not generate an automatic text patch for this file. Review the suggestion "
                "and manually merge the guidance that applies.\n\n"
                "Do not apply the suggestion blindly if the repository already has stronger local instructions.\n"
            )
        instructions_path.write_text(body, encoding="utf-8")
        written.append(instructions_path.relative_to(destination).as_posix())
        if patch_written:
            written.append(patch_path.relative_to(destination).as_posix())
    return written
