from __future__ import annotations

from pathlib import Path

from .apply import classify
from .blocks import pending_merge_paths
from .config import load_config
from .constants import (
    CLAUDE_PATH,
    COMPONENT_PATHS,
    DEFAULT_EXCLUDES,
    REPO_ROOT,
    _any_exists,
)
from .findings import Finding, Severity
from .manifest import git_ref, load_manifest

_INTEGRITY = "Install integrity"
_DRIFT = "Drift & freshness"


def integrity_findings(destination: Path) -> list[Finding]:
    config = load_config(destination)
    if not config.exists:
        return [
            Finding(
                id="doctor.install.config",
                severity=Severity.ERROR,
                category=_INTEGRITY,
                title="Raven config missing or unreadable",
                detail=f"No usable .raven/config.toml under {destination}.",
                fix="run `raven install <language>` to set up Raven",
            )
        ]

    findings: list[Finding] = [
        Finding(
            id="doctor.install.config",
            severity=Severity.OK,
            category=_INTEGRITY,
            title="Raven config present",
            detail=f"template = {config.template!r}",
        )
    ]

    manifest_path = destination / ".raven" / "manifest.json"
    if manifest_path.exists():
        findings.append(
            Finding(
                id="doctor.install.manifest",
                severity=Severity.OK,
                category=_INTEGRITY,
                title="Manifest present",
                detail=".raven/manifest.json found",
            )
        )
    else:
        findings.append(
            Finding(
                id="doctor.install.manifest",
                severity=Severity.WARN,
                category=_INTEGRITY,
                title="Manifest missing",
                detail=".raven/manifest.json not found; upgrade/accept state is unknown",
                fix="run `raven install` or `raven upgrade` to regenerate it",
            )
        )

    for name, enabled in config.components.items():
        if not enabled:
            continue
        paths = COMPONENT_PATHS.get(name, [])
        if paths and not any(_any_exists(destination / rel) for rel in paths):
            findings.append(
                Finding(
                    id=f"doctor.install.component.{name}",
                    severity=Severity.WARN,
                    category=_INTEGRITY,
                    title=f"Component '{name}' enabled but absent",
                    detail=f"None of {paths} exist though [components].{name} = true",
                    fix="run `raven upgrade` to restore missing component files",
                )
            )

    agents = destination / "AGENTS.md"
    if _any_exists(agents):
        findings.append(
            Finding(
                id="doctor.install.agents",
                severity=Severity.OK,
                category=_INTEGRITY,
                title="AGENTS.md present",
                detail="root instruction file found",
            )
        )
    else:
        findings.append(
            Finding(
                id="doctor.install.agents",
                severity=Severity.ERROR,
                category=_INTEGRITY,
                title="AGENTS.md missing",
                detail="the canonical root instruction file is absent",
                fix="run `raven install` to create AGENTS.md",
            )
        )

    findings.append(_symlink_finding(destination))
    return findings


def _symlink_finding(destination: Path) -> Finding:
    claude = destination / CLAUDE_PATH
    if not claude.exists() and not claude.is_symlink():
        return Finding(
            id="doctor.install.symlink",
            severity=Severity.OK,
            category=_INTEGRITY,
            title="CLAUDE.md absent",
            detail="no CLAUDE.md; AGENTS.md is used directly",
        )
    if claude.is_symlink():
        target = claude.readlink().as_posix()
        if target == "AGENTS.md":
            return Finding(
                id="doctor.install.symlink",
                severity=Severity.OK,
                category=_INTEGRITY,
                title="CLAUDE.md -> AGENTS.md",
                detail="symlink target is correct",
            )
        return Finding(
            id="doctor.install.symlink",
            severity=Severity.WARN,
            category=_INTEGRITY,
            title="CLAUDE.md points elsewhere",
            detail=f"symlink target is {target!r}, expected 'AGENTS.md'",
            fix="re-point CLAUDE.md at AGENTS.md (see `raven upgrade --adopt-claude-symlink`)",
        )
    return Finding(
        id="doctor.install.symlink",
        severity=Severity.WARN,
        category=_INTEGRITY,
        title="CLAUDE.md is a regular file",
        detail="CLAUDE.md should be a symlink to AGENTS.md",
        fix="run `raven upgrade --adopt-claude-symlink`",
    )


def drift_findings(destination: Path) -> list[Finding]:
    config = load_config(destination)
    if config.template is None:
        return [
            Finding(
                id="doctor.drift.template",
                severity=Severity.WARN,
                category=_DRIFT,
                title="No template configured",
                detail="config has no template; drift cannot be evaluated",
                fix="set `template` in .raven/config.toml",
            )
        ]

    findings: list[Finding] = []
    template = REPO_ROOT / config.template
    classification = classify(template, destination, set(DEFAULT_EXCLUDES), config)
    modified = sorted(set(classification.needs_merge) | set(classification.unknown_existing))
    if modified:
        findings.append(
            Finding(
                id="doctor.drift.modified",
                severity=Severity.WARN,
                category=_DRIFT,
                title=f"{len(modified)} Raven-owned file(s) locally modified",
                detail=", ".join(modified),
                fix="review and `raven upgrade` or `raven accept`",
            )
        )
    else:
        findings.append(
            Finding(
                id="doctor.drift.modified",
                severity=Severity.OK,
                category=_DRIFT,
                title="No Raven-owned drift detected",
                detail="installed Raven files match their templates",
            )
        )

    pending = pending_merge_paths(destination)
    if pending:
        findings.append(
            Finding(
                id="doctor.drift.pending",
                severity=Severity.WARN,
                category=_DRIFT,
                title=f"{len(pending)} pending guided merge(s)",
                detail=", ".join(pending),
                fix="resolve and run `raven accept`",
            )
        )

    manifest = load_manifest(destination)
    installed_version = manifest.get("ravenVersion")
    current = git_ref()
    if (
        isinstance(installed_version, str)
        and installed_version not in ("", "unknown")
        and current != "unknown"
        and installed_version != current
    ):
        findings.append(
            Finding(
                id="doctor.drift.version",
                severity=Severity.WARN,
                category=_DRIFT,
                title="Raven templates may be out of date",
                detail=f"installed {installed_version}, current {current}",
                fix="run `raven upgrade --dry-run` to preview updates",
            )
        )
    return findings
