from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Literal

from .blocks import BlockState, block_managed_state, update_raven_block
from .constants import CLAUDE_BACKUP_PATH, CLAUDE_PATH, KIND_SYMLINK, _any_exists
from .hashing import destination_fingerprint, entry_fingerprint, same_content
from .manifest import load_manifest, parse_record
from .models import Classification, Fingerprint, ManifestRecord, RavenConfig, TemplateEntry
from .template import entries_for_destination, iter_template_entries

ClassifyState = Literal["will_copy", "will_upgrade", "identical", "needs_merge", "unknown_existing"]


def _fingerprint_matches(fingerprint: Fingerprint | None, record: ManifestRecord) -> bool:
    """Whether the destination fingerprint equals the recorded installed baseline."""
    if fingerprint is None or fingerprint.kind != record.kind:
        return False
    if fingerprint.kind == KIND_SYMLINK and fingerprint.target != record.target:
        return False
    return fingerprint.sha256 == record.installed_sha256


def reconcile_state(
    record: ManifestRecord,
    fingerprint: Fingerprint | None,
    template_fp: Fingerprint | None,
) -> ClassifyState:
    """3-way reconcile of a tracked non-managed-block file against its baseline.

    ``record`` is the manifest baseline (the destination and template content
    Raven last reconciled), ``fingerprint`` is the current destination, and
    ``template_fp`` is the current template. A baseline where ``installed`` and
    ``source`` differ marks a file the user has customized (e.g. an accepted
    manual merge), which must be re-merged rather than overwritten.
    """
    if record.source_sha256 is None:
        # Legacy manifest predating sourceSha256: fall back to the 2-way rule.
        return "will_upgrade" if _fingerprint_matches(fingerprint, record) else "needs_merge"

    template_changed = template_fp is None or template_fp.sha256 != record.source_sha256
    user_touched = not _fingerprint_matches(fingerprint, record)
    if not template_changed:
        # Raven's template is unchanged since the baseline. If the file still
        # matches the recorded baseline (e.g. an accepted manual merge) there is
        # nothing to do; a later local edit is surfaced as before.
        return "needs_merge" if user_touched else "identical"
    if user_touched:
        return "needs_merge"
    # Untouched since the baseline: take the new template unless the baseline is a
    # customization (installed != source) that an overwrite would destroy.
    customized = record.installed_sha256 != record.source_sha256
    return "needs_merge" if customized else "will_upgrade"


def _classify_entry(
    entry: TemplateEntry,
    manifest: dict,
    *,
    target_exists: bool,
    content_matches: bool,
    block_state: BlockState | None,
    fingerprint: Fingerprint | None,
    template_fp: Fingerprint | None,
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
    record = parse_record(manifest.get("files", {}).get(entry.relative))
    if record is None:
        return "unknown_existing"
    return reconcile_state(record, fingerprint, template_fp)


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
        template_fp = None
        if target_exists:
            content_matches = same_content(entry, target)
            block_state = block_managed_state(entry, target)
            fingerprint = destination_fingerprint(target)
            if not content_matches and block_state is None:
                # Only the 3-way reconcile path needs the template fingerprint.
                template_fp = entry_fingerprint(entry)
        groups[
            _classify_entry(
                entry,
                manifest,
                target_exists=target_exists,
                content_matches=content_matches,
                block_state=block_state,
                fingerprint=fingerprint,
                template_fp=template_fp,
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
