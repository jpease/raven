from __future__ import annotations

from pathlib import Path

from .constants import KIND_SYMLINK, STARTER_TOOL_CONFIG_PATHS
from .hashing import destination_fingerprint
from .manifest import parse_record
from .models import Fingerprint, ManifestRecord, OrphanClassification
from .template import entries_for_destination, iter_template_entries


def shipped_relatives(template: Path, destination: Path) -> set[str]:
    """Destination-relative paths the current template could install here.

    Computed policy-neutral (empty excludes, no config) so a file the template
    still ships is never treated as an orphan just because config gating or a
    starter-config existence check would skip re-copying it. ``entries_for_
    destination`` still pops existing starter configs, so add those back from the
    raw shipped set: their presence on disk must not make them deletion targets.
    """
    resolved = set(entries_for_destination(template, set(), None, destination))
    raw = {entry.relative for entry in iter_template_entries(template, set(), None)}
    resolved |= raw & set(STARTER_TOOL_CONFIG_PATHS)
    return resolved


def _unmodified_baseline(record: ManifestRecord, fingerprint: Fingerprint) -> bool:
    """Whether the on-disk file still matches its recorded, non-customized baseline."""
    if record.source_sha256 is None:
        # Legacy record predating sourceSha256: no baseline to trust, never delete.
        return False
    if record.installed_sha256 != record.source_sha256:
        # A customization (e.g. accepted manual merge) that removal would destroy.
        return False
    if fingerprint.kind != record.kind:
        return False
    if fingerprint.kind == KIND_SYMLINK and fingerprint.target != record.target:
        return False
    return fingerprint.sha256 == record.installed_sha256


def classify_orphans(template: Path, destination: Path, manifest: dict) -> OrphanClassification:
    """Bucket manifest files the current template no longer ships.

    Non-orphans (still shipped) are ignored. Each orphan is classified strictly:
    an exact, non-customized baseline match is removable; anything else is
    reported and kept; an absent file only needs its record pruned.
    """
    tracked = manifest.get("files", {})
    if not isinstance(tracked, dict):
        return OrphanClassification([], [], [])
    shipped = shipped_relatives(template, destination)
    orphans = sorted(set(tracked) - shipped)

    will_remove: list[str] = []
    orphan_modified: list[str] = []
    already_gone: list[str] = []
    for relative in orphans:
        record = parse_record(tracked.get(relative))
        fingerprint = destination_fingerprint(destination / relative)
        if fingerprint is None:
            already_gone.append(relative)
        elif record is not None and _unmodified_baseline(record, fingerprint):
            will_remove.append(relative)
        else:
            orphan_modified.append(relative)
    return OrphanClassification(will_remove, orphan_modified, already_gone)


def remove_orphans(destination: Path, relatives: list[str]) -> list[str]:
    """Delete each managed orphan file/symlink and prune now-empty parents.

    Only the exact paths passed in are removed; parent directories are removed
    only when they become empty, and the destination root is never touched.
    """
    removed: list[str] = []
    for relative in relatives:
        if ".." in Path(relative).parts:
            continue
        target = destination / relative
        if target.is_symlink() or target.exists():
            target.unlink()
        else:
            continue
        removed.append(relative)
        # Prune empty parents, stopping before the destination root.
        parent = target.parent
        while parent != destination and parent.is_dir():
            try:
                parent.rmdir()
            except OSError:
                break  # not empty (or race) -- leave it and everything above.
            parent = parent.parent
    return removed
