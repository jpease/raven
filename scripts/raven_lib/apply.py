from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Literal

from .blocks import BlockState, block_managed_state, update_raven_block
from .constants import CLAUDE_BACKUP_PATH, CLAUDE_PATH, _any_exists
from .hashing import destination_fingerprint, same_content
from .manifest import load_manifest, manifest_allows_upgrade
from .models import Classification, RavenConfig, TemplateEntry
from .template import entries_for_destination, iter_template_entries

ClassifyState = Literal["will_copy", "will_upgrade", "identical", "needs_merge", "unknown_existing"]


def _classify_entry(
    entry: TemplateEntry,
    manifest: dict,
    *,
    target_exists: bool,
    content_matches: bool,
    block_state: BlockState | None,
    fingerprint: dict | None,
) -> ClassifyState:
    if not target_exists:
        return "will_copy"
    if content_matches:
        return "identical"
    if block_state == "identical":
        return "identical"
    if block_state == "upgradeable":
        return "will_upgrade"
    if block_state == "modified":
        return "needs_merge"
    if manifest_allows_upgrade(manifest, entry.relative, fingerprint):
        return "will_upgrade"
    if entry.relative in manifest.get("files", {}):
        return "needs_merge"
    return "unknown_existing"


def classify(
    template: Path,
    destination: Path,
    excludes: set[str],
    config: RavenConfig | None = None,
    manifest: dict | None = None,
    entries: dict[str, TemplateEntry] | None = None,
) -> Classification:
    if manifest is None:
        manifest = load_manifest(destination)

    entry_iter = (
        entries.values()
        if entries is not None
        else iter_template_entries(template, excludes, config)
    )
    groups: dict[ClassifyState, list[str]] = {
        "will_copy": [],
        "will_upgrade": [],
        "identical": [],
        "needs_merge": [],
        "unknown_existing": [],
    }
    for entry in entry_iter:
        target = destination / entry.relative
        target_exists = _any_exists(target)
        content_matches = False
        block_state = None
        fingerprint = None
        if target_exists:
            content_matches = same_content(entry, target)
            block_state = block_managed_state(entry, target)
            fingerprint = destination_fingerprint(target)
        groups[
            _classify_entry(
                entry,
                manifest,
                target_exists=target_exists,
                content_matches=content_matches,
                block_state=block_state,
                fingerprint=fingerprint,
            )
        ].append(entry.relative)

    return Classification(
        **groups,
        excluded=sorted(set(excludes) | set(config.exclude_paths if config else [])),
    )


def copy_paths(
    template: Path,
    destination: Path,
    paths: list[str],
    config: RavenConfig | None = None,
    entries: dict[str, TemplateEntry] | None = None,
    update_managed_blocks: bool = False,
) -> None:
    if entries is None:
        entries = entries_for_destination(template, set(), config, destination)
    for relative in paths:
        entry = entries[relative]
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if update_managed_blocks and block_managed_state(entry, target) == "upgradeable":
            update_raven_block(entry, target)
        elif entry.copy_as_symlink:
            if _any_exists(target):
                target.unlink()
            target.symlink_to(os.readlink(entry.source))
        else:
            shutil.copy2(entry.source, target, follow_symlinks=True)


def claude_symlink_adoption_needed(destination: Path, entries: dict[str, TemplateEntry]) -> bool:
    entry = entries.get(CLAUDE_PATH)
    target = destination / CLAUDE_PATH
    if entry is None or not entry.copy_as_symlink or not _any_exists(target):
        return False
    return not (target.is_symlink() and os.readlink(target) == os.readlink(entry.source))


def adopt_claude_symlink(destination: Path, entries: dict[str, TemplateEntry]) -> list[str]:
    entry = entries.get(CLAUDE_PATH)
    if entry is None or not entry.copy_as_symlink:
        raise ValueError("CLAUDE.md is not configured as a Raven symlink in this template")
    target = destination / CLAUDE_PATH
    backup = destination / CLAUDE_BACKUP_PATH
    if not _any_exists(target):
        target.symlink_to(os.readlink(entry.source))
        return [CLAUDE_PATH]
    if target.is_symlink() and os.readlink(target) == os.readlink(entry.source):
        return []
    if _any_exists(backup):
        raise FileExistsError(
            f"refusing to adopt CLAUDE.md because {CLAUDE_BACKUP_PATH} already exists"
        )
    target.rename(backup)
    target.symlink_to(os.readlink(entry.source))
    return [CLAUDE_BACKUP_PATH, CLAUDE_PATH]


def prompt_for_claude_symlink_adoption(destination: Path) -> bool:
    if not sys.stdin.isatty():
        return False
    print(
        "Raven uses AGENTS.md as the canonical agent instructions file and normally installs "
        "CLAUDE.md as a symlink to AGENTS.md."
    )
    print(f"This repository already has {destination / CLAUDE_PATH}.")
    print(
        f"Choose whether to leave it untouched or move it to {CLAUDE_BACKUP_PATH} and create the symlink."
    )
    while True:
        try:
            answer = input("Adopt CLAUDE.md symlink? [y/N]: ").strip().lower()
        except EOFError:
            return False
        if answer in {"", "n", "no"}:
            return False
        if answer in {"y", "yes"}:
            return True
        print("  Enter y or n.")
