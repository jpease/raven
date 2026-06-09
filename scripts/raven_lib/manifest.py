from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from .constants import KIND_SYMLINK, MANIFEST_PATH, REPO_ROOT
from .hashing import destination_fingerprint, entry_fingerprint
from .models import RavenConfig, TemplateEntry


def load_manifest(destination: Path) -> dict:
    path = destination / MANIFEST_PATH
    if not path.exists():
        return {"schema": 1, "files": {}}
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"schema": 1, "files": {}}
    if not isinstance(manifest, dict):
        return {"schema": 1, "files": {}}
    if not isinstance(manifest.get("files"), dict):
        manifest["files"] = {}
    return manifest


def git_ref() -> str:
    result = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "rev-parse", "--short=12", "HEAD"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        return result.stdout.strip()
    return "unknown"


def save_manifest(destination: Path, manifest: dict) -> None:
    path = destination / MANIFEST_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _make_manifest_record(entry: TemplateEntry, target: Path) -> dict[str, str] | None:
    installed = destination_fingerprint(target)
    if installed is None:
        return None
    base: dict[str, str] = {
        "kind": installed["kind"],
        "sourceSha256": entry_fingerprint(entry)["sha256"],
        "installedSha256": installed["sha256"],
    }
    return {**base, "target": installed["target"]} if installed["kind"] == KIND_SYMLINK else base


def update_manifest(
    destination: Path,
    template_name: str,
    template: Path,
    excludes: set[str],
    config: RavenConfig,
    paths: list[str],
    manifest: dict | None = None,
    entries: dict[str, TemplateEntry] | None = None,
) -> None:
    from .template import (
        entries_for_destination,
    )  # avoid circular: template → config → (no manifest)

    if manifest is None:
        manifest = load_manifest(destination)
    manifest["schema"] = 1
    manifest["template"] = template_name
    manifest["ravenVersion"] = git_ref()
    manifest["updatedAt"] = datetime.now(timezone.utc).isoformat()
    manifest.setdefault("files", {})

    if entries is None:
        entries = entries_for_destination(template, excludes, config, destination)
    new_records = {
        relative: record
        for relative in sorted(set(paths))
        if (entry := entries.get(relative)) is not None
        if (record := _make_manifest_record(entry, destination / relative)) is not None
    }
    manifest["files"].update(new_records)

    save_manifest(destination, manifest)


def manifest_allows_upgrade(manifest: dict, relative: str, fingerprint: dict | None) -> bool:
    record = manifest.get("files", {}).get(relative)
    if not isinstance(record, dict):
        return False
    if not fingerprint:
        return False
    if fingerprint.get("kind") != record.get("kind"):
        return False
    if fingerprint["kind"] == KIND_SYMLINK and fingerprint.get("target") != record.get("target"):
        return False
    return fingerprint["sha256"] == record.get("installedSha256")
