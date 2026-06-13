from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class TemplateEntry:
    relative: str
    source: Path
    copy_as_symlink: bool = False


@dataclass(frozen=True)
class Fingerprint:
    """Content identity of a file or symlink: KIND_FILE/KIND_SYMLINK + hash."""

    kind: str
    sha256: str
    target: str | None = None


@dataclass(frozen=True)
class RavenConfig:
    template: str | None
    include_readme: bool
    components: dict[str, bool]
    claude_components: dict[str, bool]
    codex_components: dict[str, bool]
    exclude_paths: list[str]
    platform: str = "none"
    exists: bool = False


@dataclass(frozen=True)
class RavenBlock:
    start: int
    end: int
    content: str
    declared_sha256: str | None


@dataclass(frozen=True)
class Classification:
    will_copy: list[str]
    will_upgrade: list[str]
    identical: list[str]
    needs_merge: list[str]
    unknown_existing: list[str]
    excluded: list[str]


@dataclass(frozen=True)
class ApplyPlan:
    requested_overrides: list[str]
    overwritten: list[str]
    newly_copied_overrides: list[str]
    will_copy: list[str]
    will_upgrade: list[str]
    identical: list[str]
    needs_merge: list[str]
    unknown_existing: list[str]
    effective_classification: Classification
    adopt_claude_symlink: bool
    guided_merge_paths: list[str]

    @property
    def copied(self) -> list[str]:
        return self.will_copy + self.newly_copied_overrides
