"""Read, validate, and write ``.raven/manifest.json``, the record of what Raven installed.

Validation always degrades to a usable empty manifest rather than raising, so a
corrupt or missing manifest fails a diff safely instead of crashing the CLI; the
distinction is carried forward as ``ManifestStatus.state`` for callers that need
to report it.
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from .blocks import block_managed_state
from .constants import KIND_SYMLINK, MANIFEST_PATH, REPO_ROOT
from .gates import gate_spec_for
from .hashing import destination_fingerprint, entry_fingerprint
from .models import ManifestRecord, RavenConfig, TemplateEntry
from .template import entries_for_destination

SUPPORTED_MANIFEST_SCHEMAS = frozenset({1})

ManifestState = Literal[
    "ok", "missing", "unreadable", "not_object", "invalid_files", "unsupported_schema"
]


@dataclass(frozen=True)
class ManifestStatus:
    """Result of validating ``.raven/manifest.json`` without raising or printing.

    ``manifest`` is the parsed manifest when ``state == "ok"`` and an empty
    manifest otherwise, so callers can degrade gracefully while still reporting
    the precise failure via ``state``/``detail``. ``usable`` distinguishes states
    that should block "no drift" claims (a corrupt manifest) from a merely absent
    one, which is a known, recoverable shape.
    """

    state: ManifestState
    manifest: dict
    detail: str

    @property
    def usable(self) -> bool:
        """Whether ``manifest`` reflects a trustworthy state (present-and-valid, or absent)."""
        return self.state in ("ok", "missing")


def validate_manifest(destination: Path) -> ManifestStatus:
    """Parse and structurally validate the manifest, never printing or raising."""
    empty: dict = {"schema": 1, "files": {}}
    path = destination / MANIFEST_PATH
    if not path.exists():
        return ManifestStatus(
            "missing", dict(empty), f"{MANIFEST_PATH} not found; upgrade/accept state is unknown"
        )
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        return ManifestStatus("unreadable", dict(empty), f"could not read {MANIFEST_PATH}: {exc}")
    try:
        manifest = json.loads(raw)
    except ValueError as exc:
        return ManifestStatus("unreadable", dict(empty), f"invalid JSON in {MANIFEST_PATH}: {exc}")
    if not isinstance(manifest, dict):
        return ManifestStatus(
            "not_object", dict(empty), f"{MANIFEST_PATH} root is not a JSON object"
        )
    if not isinstance(manifest.get("files"), dict):
        return ManifestStatus(
            "invalid_files", dict(empty), f"{MANIFEST_PATH} 'files' is not a JSON object"
        )
    schema = manifest.get("schema")
    if schema not in SUPPORTED_MANIFEST_SCHEMAS:
        return ManifestStatus(
            "unsupported_schema",
            dict(empty),
            f"{MANIFEST_PATH} schema {schema!r} is unsupported "
            f"(expected one of {sorted(SUPPORTED_MANIFEST_SCHEMAS)})",
        )
    return ManifestStatus("ok", manifest, f"{MANIFEST_PATH} is valid")


def load_manifest(destination: Path) -> dict:
    """Return the usable manifest, warning on (and discarding) a corrupt one.

    Shares the single parse-and-validate path with ``validate_manifest`` so the
    two never drift. A missing manifest is a normal, silent empty baseline; any
    structurally invalid one (bad JSON, wrong shape, unsupported schema) is
    reported on stderr and treated as empty so callers fail closed rather than
    acting on records they cannot trust.
    """
    status = validate_manifest(destination)
    if status.state not in ("ok", "missing"):
        print(
            f"warning: {status.detail}; treating Raven manifest as empty.",
            file=sys.stderr,
        )
    return status.manifest


def git_ref() -> str:
    """Short HEAD sha of this Raven checkout, or ``"unknown"`` outside a git repo.

    Suffixed with ``-dirty`` when the checkout has uncommitted changes, so a
    manifest recorded from a locally modified template checkout is never
    mistaken for the clean commit it shares a sha with (#243) -- installing
    from a dirty checkout is normal while developing Raven itself, and the
    committed content at that sha is not what actually got installed.
    """
    result = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "rev-parse", "--short=12", "HEAD"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return "unknown"
    sha = result.stdout.strip()
    status = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "status", "--porcelain"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        check=False,
    )
    if status.returncode == 0 and status.stdout.strip():
        return f"{sha}-dirty"
    return sha


def save_manifest(destination: Path, manifest: dict) -> None:
    """Write ``manifest`` as sorted, indented JSON to ``.raven/manifest.json``."""
    path = destination / MANIFEST_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    # A symlinked manifest would route the write to a file outside the
    # destination. Replace it in place so the write lands on a real file inside
    # .raven/ -- durable containment for callers (e.g. cmd_accept) that do not go
    # through the _run preflight.
    if path.is_symlink():
        path.unlink()
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _make_manifest_record(
    entry: TemplateEntry,
    target: Path,
    *,
    existing_record: dict | None = None,
    preserve_identical_block: bool = False,
) -> dict[str, str] | None:
    if (
        preserve_identical_block
        and existing_record is not None
        and block_managed_state(entry, target) == "identical"
    ):
        # The automatic upgrade/apply path only ever writes the RAVEN block
        # itself (see update_raven_block); it never touches content outside
        # it. Recomputing installedSha256 from the whole file here would
        # silently absorb any outside-block drift into the baseline on every
        # upgrade, turning "upgrade" into an implicit, un-asked-for "accept"
        # for content the user never blessed (#139). Return the raw stored
        # record unchanged -- not round-tripped through parse_record -- to
        # avoid any reformatting risk.
        return existing_record
    installed = destination_fingerprint(target)
    if installed is None:
        return None
    base: dict[str, str] = {
        "kind": installed.kind,
        "sourceSha256": entry_fingerprint(entry).sha256,
        "installedSha256": installed.sha256,
    }
    if installed.kind == KIND_SYMLINK and installed.target is not None:
        return {**base, "target": installed.target}
    return base


def update_manifest(
    destination: Path,
    template_name: str,
    template: Path,
    excludes: set[str],
    config: RavenConfig,
    paths: list[str],
    manifest: dict | None = None,
    entries: dict[str, TemplateEntry] | None = None,
    remove: list[str] | None = None,
    preserve_identical_block_baseline: bool = False,
) -> None:
    """Record fresh fingerprints for ``paths`` and prune ``remove``, then save.

    Reloads the on-disk manifest when one is not passed in, so repeated calls
    within one command accumulate rather than clobber each other's writes.
    ``preserve_identical_block_baseline`` is threaded through to
    ``_make_manifest_record`` for the RAVEN-block special case: see its comment
    for why a content-identical block must keep its stored record verbatim.
    """
    if manifest is None:
        manifest = load_manifest(destination)
    manifest["schema"] = 1
    manifest["template"] = template_name
    # Resolved here so the shipped capability roster can read gate tools
    # without importing raven_lib, which does not install. GATE_DATA stays
    # the single source of truth; this is a derived artifact.
    spec = gate_spec_for(template_name)
    if spec is not None:
        manifest["gateTools"] = list(spec.tools)
    manifest["ravenVersion"] = git_ref()
    manifest["updatedAt"] = datetime.now(timezone.utc).isoformat()
    manifest.setdefault("files", {})

    if entries is None:
        entries = entries_for_destination(template, excludes, config, destination)
    existing_files = manifest.get("files", {})
    new_records = {
        relative: record
        for relative in sorted(set(paths))
        if (entry := entries.get(relative)) is not None
        if (
            record := _make_manifest_record(
                entry,
                destination / relative,
                existing_record=existing_files.get(relative),
                preserve_identical_block=preserve_identical_block_baseline,
            )
        )
        is not None
    }
    manifest["files"].update(new_records)
    for relative in remove or []:
        manifest["files"].pop(relative, None)

    save_manifest(destination, manifest)


def parse_record(raw: object) -> ManifestRecord | None:
    """Parse one raw files-map entry into a typed record, or None if malformed."""
    if not isinstance(raw, dict):
        return None
    kind = raw.get("kind")
    installed_sha256 = raw.get("installedSha256")
    if not isinstance(kind, str) or not isinstance(installed_sha256, str):
        return None
    target = raw.get("target")
    source_sha256 = raw.get("sourceSha256")
    return ManifestRecord(
        kind=kind,
        installed_sha256=installed_sha256,
        target=target if isinstance(target, str) else None,
        source_sha256=source_sha256 if isinstance(source_sha256, str) else None,
    )
