from __future__ import annotations

from pathlib import Path

from .config import load_config
from .findings import Finding, Severity
from .gates import gate_spec_for
from .runner import RunResult, Runner

_GATES = "Gate compliance"


def _recipe_present(justfile_text: str, recipe: str) -> bool:
    return any(line.rstrip().startswith(f"{recipe}:") for line in justfile_text.splitlines())


def gate_compliance_findings(destination: Path, runner: Runner) -> list[Finding]:
    config = load_config(destination)
    spec = gate_spec_for(config.template) if config.template else None
    if spec is None:
        return []

    just_available = runner(["just", "--version"], destination).found
    justfile = destination / "justfile"
    justfile_text = justfile.read_text(encoding="utf-8") if justfile.is_file() else ""

    findings: list[Finding] = []
    used_fallback = False
    for recipe in spec.recipes:
        use_just = just_available and _recipe_present(justfile_text, recipe)
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
        findings.insert(
            0,
            Finding(
                id="assess.gates.just",
                severity=Severity.WARN,
                category=_GATES,
                title="just not available; used fallback commands",
                detail="install just to run Raven's canonical gate recipes",
                fix="install just (https://just.systems)",
            ),
        )
    return findings


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
