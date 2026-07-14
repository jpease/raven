from __future__ import annotations

import os
import shutil
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Literal

from .blocks import BlockState, block_managed_state, update_raven_block
from .constants import CLAUDE_BACKUP_PATH, CLAUDE_PATH, KIND_SYMLINK, _any_exists
from .hashing import destination_fingerprint, entry_fingerprint, same_content
from .manifest import load_manifest, parse_record
from .models import Classification, Fingerprint, ManifestRecord, RavenConfig, TemplateEntry
from .template import entries_for_destination, iter_template_entries

ClassifyState = Literal[
    "will_copy", "will_upgrade", "identical", "needs_merge", "unknown_existing", "local_only"
]


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
        # nothing to do. A later local edit has nothing upstream to merge against,
        # so it is "local_only": upgrade leaves it untouched without manufacturing
        # a guided merge, and doctor surfaces it informationally.
        return "local_only" if user_touched else "identical"
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
    record = parse_record(manifest.get("files", {}).get(entry.relative))
    if block_state == "modified":
        # A local edit inside the managed block normally means a guided merge.
        # But if `raven accept` already recorded this exact file as the
        # baseline and the template hasn't changed since, that acceptance
        # stands -- don't re-prompt on every upgrade (#63).
        if record is not None:
            reconciled = reconcile_state(record, fingerprint, template_fp)
            if reconciled in ("identical", "local_only"):
                return reconciled
        return "needs_merge"
    if record is None:
        return "unknown_existing"
    return reconcile_state(record, fingerprint, template_fp)


def _differs_only_by_final_newline(entry: TemplateEntry, target: Path) -> bool:
    """Whether ``target`` and the template differ only in trailing newline(s).

    A file installed by Raven that loses (or gains) its final newline -- a common
    editor/formatter artifact -- otherwise produces a guided merge with nothing
    substantive to resolve. When the content is identical apart from trailing
    newlines, upgrade can safely take the template instead of prompting.
    """
    if entry.copy_as_symlink or target.is_symlink():
        return False
    try:
        src = entry.source.read_bytes()
        dst = target.read_bytes()
    except OSError:
        return False
    return src != dst and src.rstrip(b"\n") == dst.rstrip(b"\n")


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
        "local_only": [],
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
            if not content_matches and block_state in (None, "modified"):
                # The 3-way reconcile path needs the template fingerprint --
                # for a "modified" block, to check whether an accepted
                # baseline already covers the current state (#63).
                template_fp = entry_fingerprint(entry)
        state = _classify_entry(
            entry,
            manifest,
            target_exists=target_exists,
            content_matches=content_matches,
            block_state=block_state,
            fingerprint=fingerprint,
            template_fp=template_fp,
        )
        # A merge whose only difference is the final newline has nothing to
        # resolve; take the template rather than forcing a guided merge.
        if state == "needs_merge" and _differs_only_by_final_newline(entry, target):
            state = "will_upgrade"
        groups[state].append(entry.relative)

    return Classification(
        **groups,
        excluded=sorted(set(excludes) | set(config.exclude_paths if config else [])),
    )


def find_path_collisions(destination: Path, relatives: Iterable[str]) -> list[str]:
    """Existing non-directory ancestors that block creating the given targets.

    ``copy_paths`` (and the manifest/merge writes) create each target's parent
    chain with ``mkdir(parents=True)``. If an ancestor that must become a
    directory already exists as a regular file, a broken symlink, or a symlink
    to a non-directory, that ``mkdir`` raises mid-copy and leaves a partial
    install. A symlinked ancestor that resolves to a real directory is worse: it
    silently redirects every nested write outside the destination tree, so a
    repository-controlled link such as ``.claude -> /outside`` escapes
    containment. Ancestors are never final template paths, so any symlink among
    them is unsafe. Returning every blocking ancestor up front lets callers
    preflight the whole write set and fail before touching the destination.
    """
    collisions: set[str] = set()
    for relative in relatives:
        parts = Path(relative).parts
        for depth in range(1, len(parts)):
            ancestor_rel = "/".join(parts[:depth])
            ancestor = destination / ancestor_rel
            # A symlink ancestor would route writes through its target (escaping
            # the destination), and any non-directory ancestor would make the
            # parent mkdir fail. Both are collisions; a real directory is fine.
            if _any_exists(ancestor) and (ancestor.is_symlink() or not ancestor.is_dir()):
                collisions.add(ancestor_rel)
    return sorted(collisions)


def find_state_symlink_collisions(destination: Path, relatives: Iterable[str]) -> list[str]:
    """State-file targets whose final component is a symlink (broken ones too).

    Unlike ``find_path_collisions``, which inspects only ancestor directories,
    this checks each *final* path itself. A ``.raven/config.toml`` or
    ``.raven/manifest.json`` that is a symlink (while ``.raven`` is a real
    directory) would route the state read/write through the link to a file
    outside the destination tree, silently mutating it. These state files are
    always plain files Raven owns -- never a legitimate symlink -- so any symlink
    at the final path is a containment breach and is returned as a collision. A
    broken symlink is rejected the same way (``is_symlink`` is True regardless of
    whether the target resolves). This deliberately does not generalize to
    ``find_path_collisions``: managed copy targets may legitimately be symlinks
    that ``copy_paths`` unlink-replaces, and ``.claude`` symlink adoption creates
    one on purpose, so only these known state paths are checked here.
    """
    collisions: set[str] = set()
    for relative in relatives:
        if (destination / relative).is_symlink():
            collisions.add(relative)
    return sorted(collisions)


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
            if target.is_symlink():
                target.unlink()
            shutil.copy2(entry.source, target)


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
