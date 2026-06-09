from __future__ import annotations

import filecmp
import hashlib
import os
from pathlib import Path

from .constants import KIND_FILE, KIND_SYMLINK
from .models import TemplateEntry


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _symlink_fingerprint(target: str) -> dict[str, str]:
    return {
        "kind": KIND_SYMLINK,
        "target": target,
        "sha256": sha256_bytes(f"symlink:{target}".encode()),
    }


def entry_fingerprint(entry: TemplateEntry) -> dict[str, str]:
    if entry.copy_as_symlink:
        return _symlink_fingerprint(os.readlink(entry.source))
    return {
        "kind": KIND_FILE,
        "sha256": file_sha256(entry.source),
    }


def destination_fingerprint(path: Path) -> dict[str, str] | None:
    if path.is_symlink():
        return _symlink_fingerprint(os.readlink(path))
    if path.is_file():
        return {
            "kind": KIND_FILE,
            "sha256": file_sha256(path),
        }
    return None


def same_content(entry: TemplateEntry, target: Path) -> bool:
    if entry.copy_as_symlink:
        return target.is_symlink() and os.readlink(target) == os.readlink(entry.source)
    if not target.is_file():
        return False
    return filecmp.cmp(entry.source, target, shallow=False)
