"""Build the read-only `raven doctor` health report: install integrity, drift, hooks, toolchain.

Every check here only reads state and returns `Finding`s -- it never writes to
the destination -- so `doctor` is always safe to run, including against an
install `raven` did not create.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

from .apply import classify
from .blocks import pending_merge_paths
from .codex_trust import TRUSTED, UNTRUSTED, codex_home, project_trust
from .config import ConfigError, load_config
from .constants import (
    CLAUDE_PATH,
    COMPONENT_PATHS,
    DEFAULT_EXCLUDES,
    KIND_SYMLINK,
    LANE_CLAIMS,
    REPO_ROOT,
    STARTER_TOOL_CONFIG_PATHS,
    SYMLINK_CHECKOUT_FIX,
    _any_exists,
    claude_config_dir,
)
from .deactivated import classify_deactivated
from .findings import Finding, Severity
from .gates import gate_spec_for
from .git_hooks import (
    GATE_RELAXATION_SCRIPT,
    GATE_RELAXATION_SUFFIXES,
    detect_hook_manager,
    git_hooks_dir,
    hook_manager_guidance,
)
from .manifest import ManifestStatus, git_ref, validate_manifest
from .models import RavenConfig, SourceSpec
from .orphans import classify_orphans
from .runner import Runner, probe_runner
from .template import (
    broken_template_symlinks,
    entries_for_destination,
    is_known_template,
    iter_template_entries,
)
from .tracking import untracked_merge_only_paths

_INTEGRITY = "Install integrity"
_DRIFT = "Drift & freshness"
_HOOKS = "Git hooks"

# Adapter script directories, in the order `_tool_check_script` prefers them.
_ADAPTER_DIRS = (".claude", ".codex")
_PROBER_FILENAME = "raven-tool-check.py"

# Gate tools with no reliable --version flag: probing them with --version
# exits non-zero even when the binary is installed and working (e.g. gofmt
# exits 2 with "flag provided but not defined: -version"). For these, being
# found on PATH is sufficient evidence of availability.
_NO_VERSION_FLAG = {"gofmt"}


def _checkout_symlink_findings() -> list[Finding]:
    """ERROR if the Raven checkout doctor runs from flattened its template symlinks.

    This is about `REPO_ROOT`, not the destination: a checkout made without
    symlink support holds placeholder text where `common/`'s hooks and scripts
    should be, so every install or upgrade from it produces a broken
    destination. Empty (not an OK finding) for a healthy checkout, which is the
    overwhelmingly common case and needs no line in the report.
    """
    broken = broken_template_symlinks(REPO_ROOT / "common")
    if not broken:
        return []
    return [
        Finding(
            id="doctor.checkout.symlinks",
            severity=Severity.ERROR,
            category=_INTEGRITY,
            title=f"Raven checkout flattened {len(broken)} template symlink(s)",
            detail=(
                f"under {REPO_ROOT / 'common'}: {', '.join(broken)} -- each is a regular "
                "file holding its symlink target text, so installing or upgrading from "
                "this checkout copies placeholder text in place of real content"
            ),
            fix=SYMLINK_CHECKOUT_FIX,
        )
    ]


def _flattened_install_findings(destination: Path, manifest: dict) -> list[Finding]:
    """ERROR for installed files the manifest records as symlinks but that are now regular files.

    Generalizes `_claude_finding`'s CLAUDE.md-only check to every symlink-kind
    manifest entry, so an already-corrupted destination cannot report `0 errors`
    (#177). A manifest ``kind`` is recorded from what was actually written to the
    destination, so "manifest says symlink, disk says regular file" is always a
    change made after the install, never the install's own doing.

    An *absent* path is deliberately not reported here: `drift_findings` already
    reports it as missing, and the fix differs.
    """
    files = manifest.get("files")
    if not isinstance(files, dict):
        return []
    flattened = sorted(
        relative
        for relative, record in files.items()
        if isinstance(record, dict)
        and record.get("kind") == KIND_SYMLINK
        and _any_exists(destination / relative)
        and not (destination / relative).is_symlink()
    )
    if not flattened:
        return []
    return [
        Finding(
            id="doctor.install.flattened",
            severity=Severity.ERROR,
            category=_INTEGRITY,
            title=f"{len(flattened)} installed symlink(s) are now regular files",
            detail=(
                f"{', '.join(flattened)} -- the manifest records these as symlinks, so "
                "their current contents are almost certainly the symlink target text "
                "rather than the file Raven installed"
            ),
            fix="restore them with `raven upgrade <path>` from a checkout that preserves symlinks",
        )
    ]


def _shipped_relatives(manifest: dict) -> set[str]:
    """Every relative path this install recorded, or an empty set when unrecorded."""
    files = manifest.get("files")
    return set(files) if isinstance(files, dict) else set()


def _shipped_component_path(shipped: set[str], relative: str) -> bool:
    """True when the manifest records ``relative`` itself or anything beneath it.

    A `COMPONENT_PATHS` entry names either a file (`.mcp.json`) or a directory
    (`.claude/docs`), while the manifest records individual files, so a
    directory matches by prefix.
    """
    prefix = relative + "/"
    return relative in shipped or any(key.startswith(prefix) for key in shipped)


def integrity_findings(destination: Path) -> list[Finding]:
    """Check that a Raven install's own bookkeeping (config, template) is coherent."""
    # Checked before the config gate: a flattened Raven checkout is broken
    # whether or not the destination has been installed into yet.
    findings: list[Finding] = _checkout_symlink_findings()
    config = load_config(destination)
    if not config.exists:
        findings.append(
            Finding(
                id="doctor.install.config",
                severity=Severity.ERROR,
                category=_INTEGRITY,
                title="Raven config missing or unreadable",
                detail=f"No usable .raven/config.toml under {destination}.",
                fix="run `raven install <language>` to set up Raven",
            )
        )
        return findings

    findings.append(
        Finding(
            id="doctor.install.config",
            severity=Severity.OK,
            category=_INTEGRITY,
            title="Raven config present",
            detail=f"template = {config.template!r}",
        )
    )

    if config.template is not None and not is_known_template(config.template):
        findings.append(
            Finding(
                id="doctor.install.template",
                severity=Severity.ERROR,
                category=_INTEGRITY,
                title="Unsupported template configured",
                detail=f"template {config.template!r} is not a supported Raven template",
                fix="set `template` in .raven/config.toml to a supported value",
            )
        )
        return findings

    manifest_status = validate_manifest(destination)

    if config.template is not None:
        from .cli import _template_switch_decision  # local: cli.py imports doctor.py at top level

        switch = _template_switch_decision(
            prior_template=manifest_status.manifest.get("template"),
            template_name=config.template,
            requested=False,
        )
        if switch == "prompt":
            findings.append(
                Finding(
                    id="doctor.install.template_switch_pending",
                    severity=Severity.WARN,
                    category=_INTEGRITY,
                    title="Template switch pending confirmation",
                    detail=(
                        f"config.template = {config.template!r} differs from the last-applied "
                        f"template {manifest_status.manifest.get('template')!r}"
                    ),
                    fix="run `raven upgrade --confirm-template-switch` to apply it, "
                    "or set `template` back in .raven/config.toml",
                )
            )

    findings.append(_manifest_finding(manifest_status))
    findings.extend(_flattened_install_findings(destination, manifest_status.manifest))

    shipped = _shipped_relatives(manifest_status.manifest)
    for name, enabled in config.components.items():
        if not enabled:
            continue
        paths = COMPONENT_PATHS.get(name, [])
        if shipped:
            # Grade a component against what THIS install shipped, not against
            # the union of every template's paths. `COMPONENT_PATHS` lists all
            # of them, so a template shipping no starter tool config could
            # never satisfy `tool_configs` and reported a correct install as
            # incomplete, with a fix that had no file to restore (#226).
            # Falling back to the unscoped list when the manifest records no
            # files keeps a genuinely broken install reportable, rather than
            # reading an empty record as "this template ships nothing".
            paths = [rel for rel in paths if _shipped_component_path(shipped, rel)]
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

    # Root-instruction and symlink checks apply only when the root_instructions
    # component is enabled. A repository that owns its own AGENTS.md/CLAUDE.md
    # sets root_instructions = false, so their absence is the configured shape,
    # not an integrity error.
    if config.components.get("root_instructions", True):
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

        findings.append(_claude_finding(destination))
    return findings


_MANIFEST_FINDINGS: dict[str, tuple[Severity, str, str | None]] = {
    "ok": (Severity.OK, "Manifest present", None),
    "missing": (
        Severity.WARN,
        "Manifest missing",
        "run `raven install` or `raven upgrade` to regenerate it",
    ),
    "unreadable": (
        Severity.ERROR,
        "Manifest unreadable",
        "fix or regenerate .raven/manifest.json (e.g. `raven upgrade`)",
    ),
    "not_object": (
        Severity.ERROR,
        "Manifest malformed",
        "fix or regenerate .raven/manifest.json (e.g. `raven upgrade`)",
    ),
    "invalid_files": (
        Severity.ERROR,
        "Manifest malformed",
        "fix or regenerate .raven/manifest.json (e.g. `raven upgrade`)",
    ),
    "unsupported_schema": (
        Severity.WARN,
        "Manifest schema unsupported",
        "upgrade Raven to a version that understands this manifest schema",
    ),
}


def _manifest_finding(status: ManifestStatus) -> Finding:
    severity, title, fix = _MANIFEST_FINDINGS[status.state]
    return Finding(
        id="doctor.install.manifest",
        severity=severity,
        category=_INTEGRITY,
        title=title,
        detail=status.detail,
        fix=fix,
    )


def _claude_finding(destination: Path) -> Finding:
    """OK/WARN on whether CLAUDE.md correctly imports AGENTS.md (#253).

    Raven installs CLAUDE.md as a plain one-line file containing the Claude
    Code import directive ``@AGENTS.md``, not a symlink -- a symlink breaks on
    a Windows checkout without symlink support, materializing as a regular
    file whose entire content is the literal target path string. A leftover
    symlink (from a pre-#253 install) is therefore itself a WARN, alongside a
    real file whose content doesn't carry the import line.
    """
    claude = destination / CLAUDE_PATH
    if not _any_exists(claude):
        return Finding(
            id="doctor.install.claude",
            severity=Severity.OK,
            category=_INTEGRITY,
            title="CLAUDE.md absent",
            detail="no CLAUDE.md; AGENTS.md is used directly",
        )
    if claude.is_symlink():
        return Finding(
            id="doctor.install.claude",
            severity=Severity.WARN,
            category=_INTEGRITY,
            title="CLAUDE.md is a symlink",
            detail=(
                "Raven now installs CLAUDE.md as a plain file importing AGENTS.md "
                "(`@AGENTS.md`), not a symlink -- a symlink breaks on a Windows "
                "checkout without symlink support (#253)"
            ),
            fix="run `raven upgrade` to convert it",
        )
    try:
        content = claude.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return Finding(
            id="doctor.install.claude",
            severity=Severity.WARN,
            category=_INTEGRITY,
            title="CLAUDE.md is unreadable",
            detail=str(exc),
        )
    if any(line.strip() == "@AGENTS.md" for line in content.splitlines()):
        return Finding(
            id="doctor.install.claude",
            severity=Severity.OK,
            category=_INTEGRITY,
            title="CLAUDE.md imports AGENTS.md",
            detail="contains the `@AGENTS.md` import directive",
        )
    return Finding(
        id="doctor.install.claude",
        severity=Severity.WARN,
        category=_INTEGRITY,
        title="CLAUDE.md does not import AGENTS.md",
        detail="expected a line containing `@AGENTS.md`",
        fix="run `raven upgrade --adopt-claude` (or accept the interactive prompt)",
    )


def drift_findings(destination: Path) -> list[Finding]:
    """Classify installed files against the current template and report anything not identical."""
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

    if not is_known_template(config.template):
        return [
            Finding(
                id="doctor.drift.template",
                severity=Severity.ERROR,
                category=_DRIFT,
                title="Unsupported template; drift cannot be evaluated",
                detail=f"template {config.template!r} is not a supported Raven template",
                fix="set a supported `template` in .raven/config.toml",
            )
        ]

    findings: list[Finding] = []
    template = REPO_ROOT / config.template
    # Validate the manifest once and reuse it: this avoids the stderr warnings
    # load_manifest emits (which would otherwise fire twice, once here and once
    # inside classify) and lets an unusable manifest block a "no drift" claim.
    manifest_status = validate_manifest(destination)
    manifest = manifest_status.manifest
    entries = entries_for_destination(template, set(DEFAULT_EXCLUDES), config, destination)
    # entries_for_destination drops a starter tool config the moment the
    # destination has one, so install/upgrade never overwrite a project's own
    # file. That drop is keyed on filesystem existence alone, which after a
    # normal install is always true -- Raven's own copy is sitting right
    # there. Re-add any such path the manifest already tracks (installed by
    # Raven, or later `raven accept`ed), so classify keeps evaluating drift on
    # it instead of silently dropping it from every future doctor run (#239).
    manifest_files = manifest.get("files", {})
    tracked_starter_configs = STARTER_TOOL_CONFIG_PATHS & manifest_files.keys() - entries.keys()
    if tracked_starter_configs:
        all_entries = {
            entry.relative: entry
            for entry in iter_template_entries(template, set(DEFAULT_EXCLUDES), config)
        }
        for relative in tracked_starter_configs:
            if relative in all_entries:
                entries[relative] = all_entries[relative]
    classification = classify(
        template, destination, set(DEFAULT_EXCLUDES), config, manifest=manifest, entries=entries
    )
    orphans = classify_orphans(template, destination, manifest)
    deactivated = classify_deactivated(template, destination, manifest, config)
    pending = pending_merge_paths(destination)
    # Template entries absent from the destination -- individually deleted (or
    # never installed) managed files. They are drift the user must restore, and
    # their presence forbids the "no drift detected" OK finding below.
    missing = sorted(set(classification.will_copy) - set(pending))
    # Files with a pending guided merge are, by construction, also classified as
    # needs_merge. Subtract them so each finding is disjoint: "locally modified"
    # reports only drift that has no merge artifact yet, while "pending guided
    # merge" owns the rest. Reporting both sets in full double-counts the same
    # files and offers contradictory fixes for them.
    modified = sorted(
        (set(classification.needs_merge) | set(classification.unknown_existing)) - set(pending)
    )
    # Files the user changed locally where the template is unchanged from the
    # baseline: nothing upstream to merge, so these are informational, not drift
    # that needs action (e.g. an editor reformatting an installed file).
    local_only = sorted(set(classification.local_only) - set(pending))
    # Files needing adoption consent (#200, currently only ever
    # .claude/settings.json) never get a pending guided-merge artifact, so no
    # `- set(pending)` subtraction is needed here, but it is harmless and kept
    # for symmetry with the other buckets above.
    needs_adoption = sorted(set(classification.needs_adoption) - set(pending))
    if missing:
        findings.append(
            Finding(
                id="doctor.drift.missing",
                severity=Severity.WARN,
                category=_DRIFT,
                title=f"{len(missing)} expected Raven file(s) missing",
                detail=", ".join(missing),
                fix="run `raven upgrade` to restore missing files",
            )
        )

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
    elif (
        not pending
        and not local_only
        and not missing
        and not needs_adoption
        and manifest_status.usable
        and not orphans.will_remove
        and not orphans.orphan_modified
        and not deactivated.removable
        and not deactivated.preserved
    ):
        findings.append(
            Finding(
                id="doctor.drift.modified",
                severity=Severity.OK,
                category=_DRIFT,
                title="No Raven-owned drift detected",
                detail="installed Raven files match their templates",
            )
        )

    if needs_adoption:
        findings.append(
            Finding(
                id="doctor.drift.needs_adoption",
                severity=Severity.WARN,
                category=_DRIFT,
                title=f"{len(needs_adoption)} file(s) need consent to become Raven-managed",
                detail=", ".join(needs_adoption),
                fix=(
                    "run `raven upgrade --adopt-settings-json` (or accept the interactive "
                    "prompt) to let Raven manage it"
                ),
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

    if orphans.will_remove:
        findings.append(
            Finding(
                id="doctor.orphan.removable",
                severity=Severity.WARN,
                category=_DRIFT,
                title=f"{len(orphans.will_remove)} orphaned Raven file(s) the template no longer ships",
                detail=", ".join(orphans.will_remove),
                fix="run `raven upgrade` to remove them",
            )
        )
    if orphans.orphan_modified:
        findings.append(
            Finding(
                id="doctor.orphan.modified",
                severity=Severity.WARN,
                category=_DRIFT,
                title=f"{len(orphans.orphan_modified)} orphaned + locally modified Raven file(s)",
                detail=", ".join(orphans.orphan_modified),
                fix="template no longer ships these; review and delete manually if unwanted",
            )
        )

    if deactivated.removable:
        findings.append(
            Finding(
                id="doctor.deactivated.removable",
                severity=Severity.WARN,
                category=_DRIFT,
                title=(f"{len(deactivated.removable)} Raven-owned skill(s) deactivated by config"),
                detail=", ".join(deactivated.removable),
                fix="run `raven upgrade` to remove them",
            )
        )
    # #179: `deactivated.preserved` folds three distinct dispositions
    # together -- a genuine local edit, a stale-but-pristine baseline, and an
    # accepted customization. `doctor.deactivated.preserved` keeps its id and
    # WARN severity, but its id now covers only the genuinely-modified
    # subset (a strict narrowing, not a behavior change for anything already
    # watching this id against a real local edit). Stale and customized get
    # their own, new ids and wording so neither is ever accused of "you
    # modified it".
    deactivated_modified = sorted(
        set(deactivated.preserved) - set(deactivated.stale) - set(deactivated.customized)
    )
    if deactivated_modified:
        findings.append(
            Finding(
                id="doctor.deactivated.preserved",
                severity=Severity.WARN,
                category=_DRIFT,
                title=(
                    f"{len(deactivated_modified)} deactivated-by-config + locally "
                    "modified Raven skill(s)"
                ),
                detail=", ".join(deactivated_modified),
                fix="no longer selected by platform/template config; review and delete manually if unwanted",
            )
        )
    if deactivated.stale:
        findings.append(
            Finding(
                id="doctor.deactivated.stale",
                severity=Severity.WARN,
                category=_DRIFT,
                title=(
                    f"{len(deactivated.stale)} deactivated-by-config Raven skill(s) "
                    "with a stale recorded baseline"
                ),
                detail=", ".join(deactivated.stale),
                fix="on-disk content matches the current template exactly; "
                "run `raven accept <path>` to refresh the baseline, then "
                "`raven upgrade` will remove it",
            )
        )
    if deactivated.customized:
        findings.append(
            Finding(
                id="doctor.deactivated.customized",
                severity=Severity.INFO,
                category=_DRIFT,
                title=(
                    f"{len(deactivated.customized)} deactivated-by-config Raven "
                    "skill(s) kept as an accepted customization"
                ),
                detail=", ".join(deactivated.customized),
                fix="no action needed; recorded via `raven accept`, so Raven leaves these as-is",
            )
        )
    return findings


_TOOLCHAIN = "Toolchain"


def _tool_check_script(destination: Path) -> Path:
    """Locate the tool-check prober in whichever adapter directory this install has.

    `components.claude.scripts` and `components.codex.scripts` toggle
    independently, so a destination can carry `.claude/scripts/`,
    `.codex/scripts/`, or both. Hardcoding the Claude path made `raven doctor`
    on a Codex-only install collapse its whole toolchain section into an
    unavailable-script warning whose fix (`raven install`) could not help,
    since the prober was installed -- just under the other adapter.

    Prefer the Claude copy when both exist; the two are byte-identical (see
    `.claude/docs/raven-agent-compatibility.md`). Fall back to it when neither
    does, so the warning names a path the reader recognizes.
    """
    candidates = [destination / name / "scripts" / _PROBER_FILENAME for name in _ADAPTER_DIRS]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def _tool_check_results(
    destination: Path, runner: Runner, script: Path
) -> list[dict[str, object]] | None:
    result = runner([sys.executable, str(script), "--json"], destination)
    if result.timed_out:
        return None
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    results = data.get("results")
    return results if isinstance(results, list) else None


def _gate_tool_found(tool: str, runner: Runner, destination: Path) -> bool:
    """Whether ``tool`` (one of `GateSpec.tools`) is usable, probed the way gates run it."""
    probe = runner([tool, "--version"], destination)
    if tool in _NO_VERSION_FLAG:
        return probe.found
    return probe.found and probe.ok


def missing_gate_tools(
    config: RavenConfig, destination: Path, runner: Runner = probe_runner
) -> list[str]:
    """Names of the configured template's gate tools not found on PATH.

    Reuses the same probe `toolchain_findings` performs for `doctor.gate-tool.*`
    findings, so `raven install`/`raven upgrade` can warn the moment they wire
    up a push gate instead of leaving the first push to find out (#242).
    """
    spec = gate_spec_for(config.template) if config.template else None
    if spec is None:
        return []
    return [tool for tool in spec.tools if not _gate_tool_found(tool, runner, destination)]


def toolchain_findings(destination: Path, runner: Runner = probe_runner) -> list[Finding]:
    """Report tool-check results (found/missing recommended tools), or warn if the script failed."""
    findings: list[Finding] = []
    script = _tool_check_script(destination)
    results = _tool_check_results(destination, runner, script)
    if results is None:
        try:
            shown = script.relative_to(destination).as_posix()
        except ValueError:  # pragma: no cover -- script is built from destination
            shown = script.as_posix()
        findings.append(
            Finding(
                id="doctor.tool.script",
                severity=Severity.WARN,
                category=_TOOLCHAIN,
                title="Tool-check script unavailable",
                detail=f"could not run {shown} --json",
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
            severity = Severity.OK if _gate_tool_found(tool, runner, destination) else Severity.WARN
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


def hook_manager_findings(destination: Path) -> list[Finding]:
    """INFO when a hook manager owns the hooks dir, so Raven's hooks are not installed."""
    manager = detect_hook_manager(destination)
    if manager is None:
        return []
    return [
        Finding(
            id="doctor.hooks.manager",
            severity=Severity.INFO,
            category=_HOOKS,
            title=f"hook manager detected ({manager})",
            detail=hook_manager_guidance(manager),
            fix=None,
        )
    ]


def hook_integrity_findings(destination: Path) -> list[Finding]:
    """Report each hook shipped in .raven/git-hooks/ that isn't correctly wired.

    Only runs in the ordinary symlink-install case -- when a hook manager or an
    external `core.hooksPath` owns the hooks dir, `hook_manager_findings` already
    covers it, and Raven deliberately leaves its hooks unlinked there. `.git/hooks/`
    is per-clone and never committed, so a missing or dangling link left this
    category silent (#222): the guardrails it protects (managed-block integrity,
    AI-attribution) stop running with nothing in the report to say so.
    """
    git_hooks_src = destination / ".raven" / "git-hooks"
    if not git_hooks_src.is_dir():
        return []
    manager = detect_hook_manager(destination)
    if manager is not None:
        return _inert_vendored_hook_findings(git_hooks_src, destination, manager)
    hooks_dir = git_hooks_dir(destination)
    if hooks_dir is None:
        return []
    return [
        _hook_link_finding(hook_src, hooks_dir / hook_src.name)
        for hook_src in sorted(git_hooks_src.iterdir())
        if not hook_src.name.startswith(".") and hook_src.is_file()
    ]


def _inert_vendored_hook_findings(
    git_hooks_src: Path, destination: Path, manager: str
) -> list[Finding]:
    """Name the vendored hooks a hook manager has made inert, rather than saying nothing.

    Deferring to a hook manager is supported, so this is not a failure. But the
    report used to go completely silent about hooks, which hid two real states
    observed downstream: a leftover `.git/hooks/<name>` symlink into
    `.raven/git-hooks/` that no longer runs (git reads only the manager's
    directory), and the fact that a `raven upgrade` fixing a bug in a vendored
    hook lands with no effect because nothing invokes it. Both read as "fine"
    when the category prints nothing at all.

    A leftover symlink is reported at WARN because it actively misleads -- it is
    the first thing anyone inspecting "the commit-msg hook" finds, and it can
    describe behavior opposite to the hook that actually runs. The inert-copy
    note is INFO: it is the documented consequence of the deferral, not a defect.
    """
    vendored = sorted(
        hook for hook in git_hooks_src.iterdir() if not hook.name.startswith(".") and hook.is_file()
    )
    if not vendored:
        return []

    findings: list[Finding] = []
    stale = []
    for hook in vendored:
        link = destination / ".git" / "hooks" / hook.name
        if link.is_symlink():
            try:
                resolved = (link.parent / link.readlink()).resolve()
            except OSError:  # pragma: no cover - unreadable link
                continue
            if resolved == hook.resolve():
                stale.append(hook.name)
    if stale:
        findings.append(
            Finding(
                id="doctor.hooks.inert_symlink",
                severity=Severity.WARN,
                category=_HOOKS,
                title=f"{len(stale)} Raven hook symlink(s) in .git/hooks/ never run",
                detail=(
                    f"{', '.join(stale)} still link into .raven/git-hooks/, but {manager} owns "
                    "the effective hooks directory, so git never reads them. Anyone inspecting "
                    "these files sees behavior that is not what runs on commit."
                ),
                fix=f"remove .git/hooks/{stale[0]} (and the others listed) to leave one answer",
            )
        )

    findings.append(
        Finding(
            id="doctor.hooks.vendored_inert",
            severity=Severity.INFO,
            category=_HOOKS,
            title=f"{len(vendored)} vendored hook(s) are not invoked",
            detail=(
                f"{manager} owns the hooks directory, so .raven/git-hooks/ "
                f"({', '.join(h.name for h in vendored)}) is reference material here. A "
                "`raven upgrade` that fixes a bug in one of them changes nothing until the "
                "fix is carried into whatever the manager actually runs."
            ),
            fix=None,
        )
    )
    return findings


def _hook_link_finding(hook_src: Path, hook_link: Path) -> Finding:
    name = hook_src.name
    base_id = f"doctor.hooks.{name}"

    def warn(title: str, detail: str, fix: str = "raven install") -> Finding:
        return Finding(
            id=base_id, severity=Severity.WARN, category=_HOOKS, title=title, detail=detail, fix=fix
        )

    if not hook_link.is_symlink():
        if hook_link.exists():
            return warn(
                f"{name} is not Raven's hook",
                f"{hook_link} is a regular file, not a symlink into .raven/git-hooks/",
                fix=f"remove {hook_link} to let `raven install` manage it, or wire it manually",
            )
        return warn(
            f"{name} not installed", f"{hook_link} is missing, so this guardrail does not run"
        )

    target = hook_link.readlink()
    resolved = (hook_link.parent / target).resolve()
    hook_src_resolved = hook_src.resolve()
    if resolved != hook_src_resolved:
        if not hook_link.exists():
            return warn(
                f"{name} is a dangling symlink",
                f"{hook_link} -> {target}, but the target is missing",
            )
        return warn(
            f"{name} resolves outside .raven/git-hooks/",
            f"{hook_link} -> {resolved}, not {hook_src_resolved}",
        )
    if not resolved.stat().st_mode & 0o111:
        return warn(f"{name} is not executable", f"{resolved} is missing the executable bit")
    return Finding(
        id=base_id,
        severity=Severity.OK,
        category=_HOOKS,
        title=f"{name} installed",
        detail=f"{hook_link} -> {hook_src_resolved}",
    )


def _uncovered_gate_suffixes(suffixes: tuple[str, ...]) -> tuple[str, ...]:
    """The template's source extensions the shipped relaxation checker cannot read."""
    return tuple(s for s in suffixes if s not in GATE_RELAXATION_SUFFIXES)


def gate_relaxation_findings(destination: Path) -> list[Finding]:
    """Report the shipped blanket-suppression checker, and any language it misses (#231).

    A checker that runs, exits 0, and has checked nothing is the failure
    `gate_evidence` exists to catch, so a template whose own source extensions
    have no detector is named here rather than left to look clean. Only the
    configured template's extensions are compared: the detectors dispatch per
    file, so a Go file in a Python repo is still covered, but what the report
    can promise is the language the project declared.
    """
    git_hooks_src = destination / ".raven" / "git-hooks"
    if not git_hooks_src.is_dir():
        return []
    checker = git_hooks_src / "lib" / GATE_RELAXATION_SCRIPT
    if not checker.is_file():
        return [
            Finding(
                id="doctor.hooks.gate_relaxation",
                severity=Severity.WARN,
                category=_HOOKS,
                title="blanket-suppression check not installed",
                detail=f"{checker} is missing, so a staged blanket suppression is not reported",
                fix="raven upgrade",
            )
        ]
    spec = gate_spec_for(load_config(destination).template or "")
    if spec is None or not spec.source_suffixes:
        return [
            Finding(
                id="doctor.hooks.gate_relaxation",
                severity=Severity.OK,
                category=_HOOKS,
                title="blanket-suppression check installed",
                detail="this template declares no gate, so no source extension needs a detector",
            )
        ]
    uncovered = _uncovered_gate_suffixes(spec.source_suffixes)
    if uncovered:
        return [
            Finding(
                id="doctor.hooks.gate_relaxation",
                severity=Severity.WARN,
                category=_HOOKS,
                title="blanket-suppression check covers only part of this template",
                detail=f"no detector for {', '.join(uncovered)}; those files are never reported",
                fix="open an issue: this template's language needs a verified detector",
            )
        ]
    return [
        Finding(
            id="doctor.hooks.gate_relaxation",
            severity=Severity.OK,
            category=_HOOKS,
            title="blanket-suppression check installed",
            detail=f"detectors cover {', '.join(spec.source_suffixes)}",
        )
    ]


def merge_only_tracking_findings(destination: Path) -> list[Finding]:
    """WARN when a merge-only path exists on disk but git does not track it (#216).

    One finding covering every such path rather than one per path: they share a
    single cause and a single fix, and the set is small.
    """
    untracked = untracked_merge_only_paths(destination)
    if not untracked:
        return []
    listed = ", ".join(untracked)
    return [
        Finding(
            id="doctor.install.merge_only_untracked",
            severity=Severity.WARN,
            category=_INTEGRITY,
            title=f"merge-only path not tracked by git: {listed}",
            detail=(
                "Raven wrote this into the repository but git does not track it. It "
                "applies in this working tree, so it looks correct here while reaching "
                "no other clone -- the .gitattributes eol=lf rules that exist to protect "
                "a Windows checkout, and the .ignore negations that make installed "
                "guidance searchable, both cover only the clone that generated them."
            ),
            fix=f"git add {listed}, then commit",
        )
    ]


_SOURCES = "Sources"

# Where Claude Code records the plugins it has installed, relative to the
# Claude config directory.
_REGISTRY_RELATIVE = Path("plugins") / "installed_plugins.json"

# `detect_plugin` outcomes. UNDETERMINABLE is not a soft NOT_FOUND: it means
# Raven could not read the registry at all, so it knows nothing about the
# plugin either way.
FOUND = "found"
NOT_FOUND = "not-found"
UNDETERMINABLE = "undeterminable"


@dataclass(frozen=True)
class PluginStatus:
    """What `detect_plugin` could establish about one plugin from the registry.

    ``registry`` echoes back the file that was read (or attempted) so a finding
    can name the exact path rather than re-deriving it. ``versions`` and
    ``install_paths`` are the values read across every install record for the
    plugin, in file order, deliberately not reduced to a single winner: a plugin
    can be installed at several scopes, and Raven has no trustworthy way to pick
    the live one (the `.in_use` marker is undocumented).
    """

    state: str
    versions: tuple[str, ...]
    install_paths: tuple[Path, ...]
    registry: Path


def detect_plugin(registry: Path, plugin: str) -> PluginStatus:
    """Read ``registry`` and report whether ``plugin`` is installed. Pure I/O + parse.

    Registry keys are ``<plugin>@<marketplace>``; the marketplace name varies,
    so the match is on the segment before the first ``@`` (a key with no ``@``
    matches on the whole key).

    Only a registry that parsed cleanly and did not mention the plugin is
    `NOT_FOUND`. Anything Raven cannot see through -- the file absent, a
    directory in its place, invalid JSON, or a ``plugins`` value that is not a
    mapping -- is `UNDETERMINABLE`. On a machine where Claude Code has never
    written a registry, "not installed" would be a confident wrong answer, and
    the caller needs to be able to say "I could not tell" instead.
    """
    unknown = PluginStatus(UNDETERMINABLE, (), (), registry)
    try:
        raw = registry.read_text(encoding="utf-8")
    except (OSError, ValueError):
        return unknown
    try:
        data = json.loads(raw)
    except ValueError:
        return unknown
    if not isinstance(data, dict):
        return unknown
    plugins = data.get("plugins")
    if not isinstance(plugins, dict):
        return unknown

    matched = False
    versions: list[str] = []
    install_paths: list[Path] = []
    for key, records in plugins.items():
        if not isinstance(key, str) or key.split("@", 1)[0] != plugin:
            continue
        matched = True
        if not isinstance(records, list):
            continue
        for record in records:
            if not isinstance(record, dict):
                continue
            version = record.get("version")
            if isinstance(version, str) and version:
                # Carried verbatim, "unknown" included: this plan compares no
                # versions, it only reports what the registry claims.
                versions.append(version)
            install_path = record.get("installPath")
            if isinstance(install_path, str) and install_path:
                install_paths.append(Path(install_path))
    if not matched:
        return PluginStatus(NOT_FOUND, (), (), registry)
    return PluginStatus(FOUND, tuple(versions), tuple(install_paths), registry)


def _status_finding(name: str, spec: SourceSpec, status: PluginStatus) -> Finding:
    """One status finding for a declared source, by what `detect_plugin` established.

    Every wording here says "installed", never "active" or "available": a
    plugin the registry records as installed can still be blocklisted or
    disabled per project, and Raven reads neither of those.
    """
    if status.state == FOUND:
        versions = ", ".join(status.versions) if status.versions else "version not recorded"
        return Finding(
            id=f"doctor.sources.{name}",
            severity=Severity.OK,
            category=_SOURCES,
            title=f"{name} installed ({versions})",
            detail=f"read from {status.registry}",
        )
    if status.state == NOT_FOUND:
        return Finding(
            id=f"doctor.sources.{name}",
            severity=Severity.ERROR if spec.required else Severity.WARN,
            category=_SOURCES,
            title=f"{name} not installed",
            detail=(
                f"declared in .raven/config.toml as a {spec.kind} source, but "
                f"{status.registry} records no plugin named {name}"
            ),
            fix=(f"install the {name} plugin, or remove [sources.{name}] from .raven/config.toml"),
        )
    # UNDETERMINABLE never escalates to ERROR, `required` or not: "Raven cannot
    # tell" is a different claim from "the dependency is missing", and a
    # machine whose registry Raven could not read must not fail a build over it.
    return Finding(
        id=f"doctor.sources.{name}",
        severity=Severity.WARN,
        category=_SOURCES,
        title=f"{name} install state undeterminable",
        detail=(
            f"could not read the plugin registry at {status.registry}, so Raven "
            f"cannot tell whether {name} is installed"
        ),
        fix=f"check that {status.registry} exists and is readable, then re-run",
    )


def collision_findings(destination: Path, statuses: dict[str, PluginStatus]) -> list[Finding]:
    """One INFO finding per `LANE_CLAIMS` row whose two skills are both installed here.

    "Installed" is the whole test, on both sides: the Raven skill directory
    exists in the destination, and the upstream skill directory exists under at
    least one recorded ``installPath``. No file inside either is opened,
    `SKILL.md` included, and the destination's own `AGENTS.md` is not read --
    which of the two a repository actually prefers is the static `prefer` field,
    not something inferred from prose.

    A row whose source is undeclared, `NOT_FOUND`, or `UNDETERMINABLE` is
    skipped: there is no second skill to collide with, or no way to tell.

    Findings follow `LANE_CLAIMS` order and are not deduplicated. Two rows
    sharing a lane slug produce two findings with the same id, and that
    duplicate id is the signal that the table needs fixing.
    """
    findings: list[Finding] = []
    for claim in LANE_CLAIMS:
        status = statuses.get(claim.source)
        if status is None or status.state != FOUND:
            continue
        if not (destination / ".agents" / "skills" / claim.raven_skill).is_dir():
            continue
        upstream_installed = any(
            (path / "skills" / claim.upstream_skill).is_dir() for path in status.install_paths
        )
        if not upstream_installed:
            continue
        findings.append(
            Finding(
                id=f"doctor.sources.collision.{claim.lane}",
                severity=Severity.INFO,
                category=_SOURCES,
                title=(
                    f"{claim.lane} lane: {claim.raven_skill} and "
                    f"{claim.upstream_skill} ({claim.source}) are both installed"
                ),
                detail=f"prefer the {claim.prefer} skill: {claim.reason}",
            )
        )
    return findings


def sources_findings(
    destination: Path, config: RavenConfig, *, registry: Path | None = None
) -> list[Finding]:
    """Report each declared `[sources.<name>]` dependency, and any skill-lane collisions.

    `config` is passed in rather than re-loaded: `build_doctor_findings` has
    already loaded it behind the config-first short-circuit, so loading it
    again here would duplicate that read and diverge from its error handling.

    The `registry` default is a ``None`` sentinel resolved in the body, never an
    evaluated default in the signature -- the latter would freeze
    `claude_config_dir()` at import time, which the CLI would never notice
    (fresh process per run) while every in-process test saw the importing
    process's environment.
    """
    if not config.sources:
        return []
    # No `.claude/` means a Codex-only install: no Claude plugin is reachable
    # from this destination, so neither the status nor the collision half of
    # this section has anything to say. `[components.claude]` is a table of
    # independent per-component toggles, not one adapter-enabled boolean, so
    # the directory itself is the test.
    if not (destination / ".claude").is_dir():
        return []
    if registry is None:
        registry = claude_config_dir() / _REGISTRY_RELATIVE

    findings: list[Finding] = []
    statuses: dict[str, PluginStatus] = {}
    for name, spec in config.sources.items():
        statuses[name] = detect_plugin(registry, name)
        findings.append(_status_finding(name, spec, statuses[name]))
    findings.extend(collision_findings(destination, statuses))
    return findings


_CODEX = "Codex adapter"


def codex_trust_findings(destination: Path) -> list[Finding]:
    """INFO/WARN/OK on whether Codex will load the installed `.codex/` layer at all.

    Codex loads a project's `.codex/` layer -- config, hooks, rules, custom
    agents -- only for a project the user has trusted, recorded in Codex's own
    `$CODEX_HOME/config.toml`. An untrusted project's hooks are parsed and then
    skipped without any message (verified live, 2026-09-02), so a Raven install
    can look complete and enforce nothing. Empty when the destination has no
    Codex adapter to speak of: no `.codex/` directory, or every Codex component
    switched off in `.raven/config.toml`.

    Hook trust is a second, per-hook gate (`/hooks` in the Codex TUI) that
    lives in Codex's state database rather than its config, so it is named in
    the fix text but not checked here.
    """
    config = load_config(destination)
    if not (destination / ".codex").is_dir():
        return []
    if config.codex_components and not any(config.codex_components.values()):
        return []

    trust = project_trust(destination)
    config_path = codex_home() / "config.toml"
    if trust is None:
        return [
            Finding(
                id="doctor.codex.unconfigured",
                severity=Severity.INFO,
                category=_CODEX,
                title="Codex has no config on this machine",
                detail=(
                    f"{config_path} is absent; the installed .codex/ layer stays inert "
                    "until Codex trusts this project"
                ),
            )
        ]
    if trust == TRUSTED:
        return [
            Finding(
                id="doctor.codex.trusted",
                severity=Severity.OK,
                category=_CODEX,
                title="Codex trusts this project",
                detail="the .codex/ layer (config, hooks, rules, agents) is live",
            )
        ]
    if trust == UNTRUSTED:
        title = "Codex marks this project untrusted"
        detail = (
            f"{config_path} records trust_level = \"untrusted\" for this project or a "
            "parent, so Codex skips the installed .codex/ layer entirely"
        )
    else:
        title = "Codex has not trusted this project"
        detail = (
            f"no [projects] entry in {config_path} covers this repository, so Codex "
            "skips the installed .codex/ layer (config, hooks, rules, agents) without "
            "saying so"
        )
    return [
        Finding(
            id="doctor.codex.untrusted",
            severity=Severity.WARN,
            category=_CODEX,
            title=title,
            detail=detail,
            fix=(
                "run `codex` in this repository once and accept the trust prompt, "
                "then review Raven's hooks in `/hooks`; hooks stay skipped until reviewed"
            ),
        )
    ]


def build_doctor_findings(destination: Path, runner: Runner = probe_runner) -> list[Finding]:
    """Assemble the full `raven doctor` findings list: config sanity, then every other check.

    Config is validated first and, if malformed, short-circuits the rest --
    every other check assumes a loadable config and would otherwise raise or
    produce misleading findings from a config it cannot trust.
    """
    try:
        load_config(destination)
    except ConfigError as exc:
        return [
            Finding(
                id="doctor.install.config",
                severity=Severity.ERROR,
                category=_INTEGRITY,
                title="Raven config malformed",
                detail=str(exc),
                fix="fix the syntax in .raven/config.toml, then re-run",
            )
        ]
    findings = toolchain_findings(destination, runner)
    integrity = integrity_findings(destination)
    findings.extend(integrity)
    findings.extend(hook_manager_findings(destination))
    findings.extend(hook_integrity_findings(destination))
    findings.extend(gate_relaxation_findings(destination))
    findings.extend(merge_only_tracking_findings(destination))
    findings.extend(codex_trust_findings(destination))
    config = load_config(destination)
    if config.exists:
        findings.extend(drift_findings(destination))
    findings.extend(sources_findings(destination, config))
    return findings
