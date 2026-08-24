"""Track which repositories have Raven installed, and report which ones are behind.

Raven's stated audience is someone maintaining more than one repository, and
every other command runs from inside exactly one of them. With no tagged
release -- an install pins the commit sha recorded in `.raven/manifest.json` --
answering "which of my repos are stale?" meant visiting each one and reading
its manifest by hand. This module keeps a registry so that question has an
answer.

The registry stores paths and nothing else. Template, pinned sha, and every
other fact is read live from each repository's own manifest, so the registry
cannot go stale about anything except which directories to look in -- and
`fleet --prune` fixes that.

Registry location is `~/.raven/repos.json`, beside the tool memory
`docs/tooling.md` describes. `RAVEN_HOME` overrides the directory, which is
what the tests use; nothing writes outside it.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from .findings import Finding, Severity
from .manifest import git_ref, load_manifest

#: Registry schema version. Bump only for a breaking shape change; an unknown
#: version is treated as unreadable rather than guessed at.
REGISTRY_SCHEMA = 1

_FLEET = "Fleet"


def raven_home() -> Path:
    """The directory holding Raven's user-level state, honoring ``RAVEN_HOME``."""
    override = os.environ.get("RAVEN_HOME")
    if override:
        return Path(override)
    return Path.home() / ".raven"


def registry_path() -> Path:
    """Path to the fleet registry JSON file."""
    return raven_home() / "repos.json"


def load_registry() -> list[Path]:
    """Every registered repository path, de-duplicated and sorted.

    Returns an empty list for a missing, unreadable, or unknown-schema file.
    A registry is a convenience, never a source of truth: failing to read one
    must never break `install`, and must never be reported as if the user had
    no Raven installs.
    """
    path = registry_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(payload, dict) or payload.get("schema") != REGISTRY_SCHEMA:
        return []
    repos = payload.get("repos")
    if not isinstance(repos, list):
        return []
    return sorted({Path(entry) for entry in repos if isinstance(entry, str) and entry})


def save_registry(paths: list[Path]) -> bool:
    """Write the registry, returning whether it was written.

    Best-effort by design: a read-only or missing home directory means no fleet
    view, not a failed install.
    """
    path = registry_path()
    payload = {
        "schema": REGISTRY_SCHEMA,
        "repos": sorted({str(p) for p in paths}),
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    except OSError:
        return False
    return True


def register(destination: Path) -> bool:
    """Record ``destination`` as a Raven install, returning whether the registry changed.

    Called after a successful `install` or `upgrade`. Idempotent, and silent on
    failure -- see `save_registry`.
    """
    try:
        resolved = destination.resolve()
    except OSError:
        return False
    existing = load_registry()
    if resolved in existing:
        return False
    return save_registry([*existing, resolved])


def _installed_version(destination: Path) -> str | None:
    """The Raven sha recorded in a repository's manifest, or None when unreadable."""
    manifest = load_manifest(destination)
    if not isinstance(manifest, dict):
        return None
    version = manifest.get("ravenVersion")
    if isinstance(version, str) and version not in ("", "unknown"):
        return version
    return None


def _template(destination: Path) -> str:
    """The template name a repository's manifest records, or ``"?"``."""
    manifest = load_manifest(destination)
    if isinstance(manifest, dict):
        template = manifest.get("template")
        if isinstance(template, str) and template:
            return template
    return "?"


def stale_paths() -> list[Path]:
    """Registered paths that no longer hold a Raven install, for ``--prune``."""
    return [path for path in load_registry() if not (path / ".raven" / "config.toml").is_file()]


def build_fleet_findings() -> list[Finding]:
    """One finding per registered repository, plus the empty-registry case.

    Read-only: nothing here upgrades, prunes, or writes. `fleet` reports what
    is behind and leaves acting on it to the reader, who is the only one who
    knows which of those repositories is safe to touch right now.
    """
    repos = load_registry()
    if not repos:
        return [
            Finding(
                id="fleet.empty",
                severity=Severity.INFO,
                category=_FLEET,
                title="No repositories registered yet",
                detail=(
                    f"{registry_path()} lists none; `raven install` and `raven upgrade` "
                    "record each repository they run in"
                ),
                fix="run `raven install` or `raven upgrade` in a repository to register it",
            )
        ]

    current = git_ref()
    findings: list[Finding] = []
    for path in repos:
        label = str(path)
        if not (path / ".raven" / "config.toml").is_file():
            findings.append(
                Finding(
                    id=f"fleet.gone.{label}",
                    severity=Severity.WARN,
                    category=_FLEET,
                    title=f"{label} is no longer a Raven install",
                    detail="the directory is missing, or its .raven/config.toml was removed",
                    fix="run `raven fleet --prune` to forget it",
                )
            )
            continue
        template = _template(path)
        installed = _installed_version(path)
        if installed is None:
            findings.append(
                Finding(
                    id=f"fleet.unknown.{label}",
                    severity=Severity.WARN,
                    category=_FLEET,
                    title=f"{label} ({template}) records no Raven version",
                    detail="its manifest has no usable ravenVersion, so staleness is unknown",
                    fix=f"run `raven upgrade` in {label} to re-record it",
                )
            )
        elif current == "unknown":
            findings.append(
                Finding(
                    id=f"fleet.unmeasured.{label}",
                    severity=Severity.INFO,
                    category=_FLEET,
                    title=f"{label} ({template}) pinned to {installed}",
                    detail="this Raven checkout is not a git repository, so there is nothing to compare against",
                )
            )
        elif installed == current:
            findings.append(
                Finding(
                    id=f"fleet.current.{label}",
                    severity=Severity.OK,
                    category=_FLEET,
                    title=f"{label} ({template}) up to date at {installed}",
                    detail="matches this Raven checkout",
                )
            )
        else:
            findings.append(
                Finding(
                    id=f"fleet.behind.{label}",
                    severity=Severity.WARN,
                    category=_FLEET,
                    title=f"{label} ({template}) is behind",
                    detail=f"installed {installed}, current {current}",
                    fix=f"cd {label} && raven upgrade --dry-run",
                )
            )
    return findings
