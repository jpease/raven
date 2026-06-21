from __future__ import annotations

from pathlib import Path

from .config import load_config
from .findings import Finding, Severity
from .gates import gate_spec_for, recipe_present
from .runner import Runner, RunResult

_GATES = "Gate compliance"


def gate_compliance_findings(destination: Path, runner: Runner) -> list[Finding]:
    config = load_config(destination)
    spec = gate_spec_for(config.template) if config.template else None
    if spec is None:
        return []

    # `just` is only usable when the version probe actually succeeds. A probe
    # that is found on PATH but exits non-zero or times out is broken, so fall
    # back to the direct commands rather than invoking the broken executable.
    probe = runner(["just", "--version"], destination)
    just_available = probe.ok
    justfile = destination / "justfile"
    justfile_text = justfile.read_text(encoding="utf-8") if justfile.is_file() else ""

    findings: list[Finding] = []
    used_fallback = False
    for recipe in spec.recipes:
        use_just = just_available and recipe_present(justfile_text, recipe)
        if use_just:
            command = ["just", recipe]
        else:
            fallback = spec.fallback_commands.get(recipe)
            if fallback is None:
                continue
            command = list(fallback)
            if not just_available:
                used_fallback = True
        result = runner(command, destination)
        findings.append(_recipe_finding(recipe, command, result))

    if used_fallback:
        findings.insert(0, _fallback_warning(probe))
    return findings


def _fallback_warning(probe: RunResult) -> Finding:
    """Warn that fallbacks ran, explaining why `just` was treated as unusable.

    Preserves the distinction between a missing, failed, and timed-out probe so
    the detail points at the real problem instead of always saying "install".
    """
    if not probe.found:
        title = "just not available; used fallback commands"
        detail = "install just to run Raven's canonical gate recipes"
        fix = "install just (https://just.systems)"
    elif probe.timed_out:
        title = "just probe timed out; used fallback commands"
        detail = "`just --version` did not finish in time; the install may be broken"
        fix = "run `just --version` manually to investigate"
    else:
        title = "just present but unusable; used fallback commands"
        detail = f"`just --version` exited {probe.code}"
        fix = "repair the just installation, then re-run"
    return Finding(
        id="assess.gates.just",
        severity=Severity.WARN,
        category=_GATES,
        title=title,
        detail=detail,
        fix=fix,
    )


def _recipe_finding(recipe: str, command: list[str], result: RunResult) -> Finding:
    label = " ".join(command)
    if not result.found:
        return Finding(
            id=f"assess.gates.{recipe}",
            severity=Severity.WARN,
            category=_GATES,
            title=f"gate '{recipe}' could not run",
            detail=f"command not found: {label}",
            fix=f"install the tool for `{label}`",
        )
    if result.timed_out:
        return Finding(
            id=f"assess.gates.{recipe}",
            severity=Severity.WARN,
            category=_GATES,
            title=f"gate '{recipe}' timed out",
            detail=f"`{label}` did not finish in time",
            fix="run the gate manually to investigate",
        )
    if result.ok:
        return Finding(
            id=f"assess.gates.{recipe}",
            severity=Severity.OK,
            category=_GATES,
            title=f"gate '{recipe}' passed",
            detail=f"`{label}` exited 0",
        )
    return Finding(
        id=f"assess.gates.{recipe}",
        severity=Severity.ERROR,
        category=_GATES,
        title=f"gate '{recipe}' failed",
        detail=f"`{label}` exited {result.code}",
        fix=f"fix the reported issues, then re-run `{label}`",
    )
