"""Classify and remove manifest-tracked files the current template no longer ships.

An orphan is only ever deleted when it still matches its recorded baseline exactly;
anything customized or already gone is reported instead, never silently dropped.
"""

from __future__ import annotations

import sys
from pathlib import Path

from .constants import KIND_SYMLINK, STARTER_TOOL_CONFIG_PATHS
from .hashing import destination_fingerprint
from .manifest import parse_record
from .models import Fingerprint, ManifestRecord, OrphanClassification
from .template import entries_for_destination


def shipped_relatives(template: Path, destination: Path) -> set[str]:
    """Destination-relative paths the current template could install here.

    Computed policy-neutral (empty excludes, no config) so a file the template
    still ships is never treated as an orphan just because config gating or a
    starter-config existence check would skip re-copying it. ``entries_for_
    destination`` still pops existing starter configs, so every starter-config
    path is added back unconditionally: their presence on disk must not make
    them deletion targets.

    Unconditionally, not intersected with what *this* template ships (#175):
    switching ``template`` in the config is a supported workflow, and after a
    python -> dotfiles switch the new template ships no ``pyproject.toml``, so
    an intersection dropped the user's starter config out of the shipped set
    and -- because an untouched starter config still matches its recorded
    baseline exactly -- made it a removable orphan. A starter tool config is
    project-owned once created; it is only ever removed on explicit request.
    """
    resolved = set(entries_for_destination(template, set(), None, destination))
    resolved |= set(STARTER_TOOL_CONFIG_PATHS)
    return resolved


def is_canonical_manifest_key(relative: object) -> bool:
    """Whether a manifest file key is a canonical destination-relative POSIX path.

    Pure: the syntactic half of ``_safe_relative``'s check, split out so the
    rules can be enumerated in tests without a filesystem. Rejects anything that
    is not a plain relative path -- a non-string, a backslash (a Windows
    separator would not split into segments here), an absolute path, and any
    empty, ``.`` or ``..`` segment, which covers a leading ``./``, a bare ``.``,
    the empty string, a trailing slash, and a doubled slash.

    A true result means the *spelling* is safe, not that the path stays inside
    the destination: a symlinked ancestor can still escape, which only a
    filesystem check can see. ``_safe_relative`` does that second half.
    """
    if not isinstance(relative, str) or "\\" in relative:
        return False
    if any(segment in ("", ".", "..") for segment in relative.split("/")):
        return False
    return not Path(relative).is_absolute()


def _safe_relative(destination: Path, relative: object) -> Path | None:
    """Resolve a manifest file key to its in-destination target, or None if unsafe.

    A valid Raven manifest key is a canonical, destination-relative POSIX path.
    Anything else is rejected (with a stderr warning) so orphan classification
    and removal can never name or mutate a file outside ``destination``:

    - a non-string key, or one containing a backslash;
    - a non-canonical form: an absolute path, a ``..`` traversal, a ``.`` or
      empty segment (leading ``./``, a bare ``.``, an empty string, a trailing
      slash, or a doubled slash);
    - a path whose parent directory escapes ``destination`` through a symlinked
      ancestor. The leaf itself may legitimately be a managed symlink that
      ``remove_orphans`` unlinks without following, so only the parent is
      resolved. A not-yet-created parent is not an escape: the nearest existing
      ancestor is resolved instead.
    """
    if not is_canonical_manifest_key(relative):
        return _reject(relative)
    assert isinstance(relative, str)  # narrowed by is_canonical_manifest_key
    target = destination / relative
    probe = target.parent
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    try:
        resolved_parent = probe.resolve()
        resolved_dest = destination.resolve()
    except OSError:
        return _reject(relative)
    if not resolved_parent.is_relative_to(resolved_dest):
        return _reject(relative)
    return target


def _reject(relative: object) -> None:
    """Warn that a manifest key is unsafe and skip it; returns None for callers."""
    print(
        f"warning: ignoring unsafe Raven manifest path {relative!r} "
        "(not a canonical path inside the destination); skipping it.",
        file=sys.stderr,
    )


def unmodified_baseline(record: ManifestRecord, fingerprint: Fingerprint) -> bool:
    """Whether the on-disk file still matches its recorded, non-customized baseline.

    The shared safety gate behind every destructive decision that reuses this
    module: `classify_orphans` uses it to separate `will_remove` from
    `orphan_modified`, and `raven_lib.deactivated.classify_deactivated` reuses
    this exact function (not a copy) to separate its own ``removable`` from
    ``preserved`` bucket, so the rule can never drift between the two paths.
    """
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
        target = _safe_relative(destination, relative)
        if target is None:
            continue
        record = parse_record(tracked.get(relative))
        fingerprint = destination_fingerprint(target)
        if fingerprint is None:
            already_gone.append(relative)
        elif record is not None and unmodified_baseline(record, fingerprint):
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
        target = _safe_relative(destination, relative)
        if target is None:
            continue
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
