from __future__ import annotations

import json
import sys
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
from .gates import gate_spec_for
from .manifest import git_ref, load_manifest
from .runner import Runner, probe_runner

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
    pending = pending_merge_paths(destination)
    # Files with a pending guided merge are, by construction, also classified as
    # needs_merge. Subtract them so each finding is disjoint: "locally modified"
    # surfaces only drift that has no merge artifact yet, while "pending guided
    # merge" owns the rest. Reporting both sets in full double-counts the same
    # files and offers contradictory fixes for them.
    modified = sorted(
        (set(classification.needs_merge) | set(classification.unknown_existing)) - set(pending)
    )
    # Files the user changed locally where the template is unchanged from the
    # baseline: nothing upstream to merge, so these are informational, not drift
    # that needs action (e.g. an editor reformatting an installed file).
    local_only = sorted(set(classification.local_only) - set(pending))
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
    elif not pending and not local_only:
        findings.append(
            Finding(
                id="doctor.drift.modified",
                severity=Severity.OK,
                category=_DRIFT,
                title="No Raven-owned drift detected",
                detail="installed Raven files match their templates",
            )
        )

    if local_only:
        findings.append(
            Finding(
                id="doctor.drift.local",
                severity=Severity.INFO,
                category=_DRIFT,
                title=f"{len(local_only)} Raven-owned file(s) customized locally",
                detail=", ".join(local_only),
                fix="no action needed; the template is unchanged, so Raven leaves these as-is",
            )
        )

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


_TOOLCHAIN = "Toolchain"


def _tool_check_results(destination: Path, runner: Runner) -> list[dict[str, object]] | None:
    script = destination / ".claude" / "scripts" / "raven-tool-check.py"
    result = runner([sys.executable, str(script), "--json"], destination)
    if result.timed_out:
        return None
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
    results = data.get("results")
    return results if isinstance(results, list) else None


def toolchain_findings(destination: Path, runner: Runner = probe_runner) -> list[Finding]:
    findings: list[Finding] = []
    results = _tool_check_results(destination, runner)
    if results is None:
        findings.append(
            Finding(
                id="doctor.tool.script",
                severity=Severity.WARN,
                category=_TOOLCHAIN,
                title="Tool-check script unavailable",
                detail="could not run .claude/scripts/raven-tool-check.py --json",
                fix="run `raven install` to restore Raven scripts, then re-run",
            )
        )
        return findings

    seen_ids: set[str] = set()
    for result in results:
        if not isinstance(result, dict):
            continue
        tool_id = str(result.get("id", "unknown"))
        seen_ids.add(tool_id)
        name = str(result.get("name", tool_id))
        available = bool(result.get("available"))
        optional_when = result.get("optionalWhen")
        if available:
            findings.append(
                Finding(
                    id=f"doctor.tool.{tool_id}",
                    severity=Severity.OK,
                    category=_TOOLCHAIN,
                    title=f"{name} present",
                    detail=str(result.get("purpose", "")),
                )
            )
        else:
            detail = f"{name} not installed or configured"
            if isinstance(optional_when, str) and optional_when:
                detail += f" (optional when {optional_when})"
            findings.append(
                Finding(
                    id=f"doctor.tool.{tool_id}",
                    severity=Severity.WARN,
                    category=_TOOLCHAIN,
                    title=f"{name} missing",
                    detail=detail,
                    fix="see `raven-tool-bootstrap` skill for install guidance",
                )
            )

    config = load_config(destination)
    spec = gate_spec_for(config.template) if config.template else None
    if spec is not None:
        for tool in spec.tools:
            if tool in seen_ids:
                continue
            probe = runner([tool, "--version"], destination)
            severity = Severity.OK if probe.found and probe.ok else Severity.WARN
            findings.append(
                Finding(
                    id=f"doctor.gate-tool.{tool}",
                    severity=severity,
                    category=_TOOLCHAIN,
                    title=f"{tool} {'present' if severity is Severity.OK else 'missing'}",
                    detail=f"gate tool for the {config.template} template",
                    fix=None
                    if severity is Severity.OK
                    else f"install {tool} to run the template's gates",
                )
            )
    return findings


def build_doctor_findings(destination: Path, runner: Runner = probe_runner) -> list[Finding]:
    findings = toolchain_findings(destination, runner)
    integrity = integrity_findings(destination)
    findings.extend(integrity)
    config = load_config(destination)
    if config.exists:
        findings.extend(drift_findings(destination))
    return findings
