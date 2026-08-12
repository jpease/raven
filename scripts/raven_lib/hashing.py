"""Content fingerprints for files and symlinks, used to detect drift and dedupe copies.

A symlink's "content" is its target string, not the bytes it resolves to, so a
symlink and a regular file can never fingerprint as equal even if their targets
happen to coincide byte-for-byte with a file's contents -- ``kind`` is always part
of the identity, not just the hash.
"""

from __future__ import annotations

import filecmp
import hashlib
import os
from pathlib import Path

from .constants import KIND_FILE, KIND_SYMLINK
from .models import Fingerprint, TemplateEntry


def sha256_bytes(value: bytes) -> str:
    """Hex sha256 digest of raw bytes."""
    return hashlib.sha256(value).hexdigest()


def file_sha256(path: Path) -> str:
    """Hex sha256 digest of a file's contents, streamed in 1 MiB chunks."""
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _symlink_fingerprint(target: str) -> Fingerprint:
    return Fingerprint(
        kind=KIND_SYMLINK,
        target=target,
        sha256=sha256_bytes(f"symlink:{target}".encode()),
    )


def entry_fingerprint(entry: TemplateEntry) -> Fingerprint:
    """Fingerprint a template entry as it would be copied: its symlink target or file hash."""
    if entry.copy_as_symlink:
        return _symlink_fingerprint(os.readlink(entry.source))
    return Fingerprint(kind=KIND_FILE, sha256=file_sha256(entry.source))


def destination_fingerprint(path: Path) -> Fingerprint | None:
    """Fingerprint whatever is on disk at ``path``, or None if nothing is there."""
    if path.is_symlink():
        return _symlink_fingerprint(os.readlink(path))
    if path.is_file():
        return Fingerprint(kind=KIND_FILE, sha256=file_sha256(path))
    return None


def same_content(entry: TemplateEntry, target: Path) -> bool:
    """Whether ``target`` already holds the same content the template entry would install.

    Compares symlink targets directly rather than hashing, and uses a non-shallow
    ``filecmp`` for regular files so a size/mtime match alone cannot pass.
    """
    if entry.copy_as_symlink:
        return target.is_symlink() and os.readlink(target) == os.readlink(entry.source)
    if not target.is_file():
        return False
    return filecmp.cmp(entry.source, target, shallow=False)
