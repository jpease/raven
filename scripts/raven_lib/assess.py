from __future__ import annotations

from pathlib import Path

from .config import load_config
from .findings import Finding, Severity
from .gate_run import gate_compliance_findings
from .gates import gate_spec_for, load_gate_specs, recipe_present
from .runner import Runner, gate_runner

_WIRING = "Quality-gate wiring"
_FIT = "Template fit"
_GATES = "Gate compliance"


def wiring_findings(destination: Path) -> list[Finding]:
    config = load_config(destination)
    spec = gate_spec_for(config.template) if config.template else None
    findings: list[Finding] = []
    if spec is None:
        return [
            Finding(
                id="assess.wiring.template",
                severity=Severity.WARN,
                category=_WIRING,
                title="No gate spec for template",
                detail=f"template {config.template!r} has no gate expectations",
                fix="set a supported `template` in .raven/config.toml",
            )
        ]

    justfile = destination / "justfile"
    if not justfile.is_file():
        findings.append(
            Finding(
                id="assess.wiring.justfile",
                severity=Severity.WARN,
                category=_WIRING,
                title="No justfile",
                detail="Raven's quality gates are defined in a justfile",
                fix="run `raven install` / `raven upgrade` to add the template justfile",
            )
        )
        text = ""
    else:
        text = justfile.read_text(encoding="utf-8")
        findings.append(
            Finding(
                id="assess.wiring.justfile",
                severity=Severity.OK,
                category=_WIRING,
                title="justfile present",
                detail="quality-gate recipes can be defined here",
            )
        )

    for recipe in spec.recipes:
        present = recipe_present(text, recipe)
        findings.append(
            Finding(
                id=f"assess.wiring.recipe.{recipe}",
                severity=Severity.OK if present else Severity.WARN,
                category=_WIRING,
                title=f"gate recipe '{recipe}' {'defined' if present else 'missing'}",
                detail=f"justfile recipe `{recipe}`",
                fix=None if present else f"add a `{recipe}:` recipe to the justfile",
            )
        )

    for file, substring in spec.config_signals:
        target = destination / file
        ok = target.is_file() and (
            substring is None or substring in target.read_text(encoding="utf-8")
        )
        findings.append(
            Finding(
                id=f"assess.wiring.config.{file}",
                severity=Severity.OK if ok else Severity.WARN,
                category=_WIRING,
                title=f"tool config {file} {'present' if ok else 'missing'}",
                detail=f"expected {substring!r} in {file}" if substring else f"expected {file}",
                fix=None if ok else f"configure the gate tools in {file}",
            )
        )

    hook = destination / ".git" / "hooks" / "pre-commit"
    hook_ok = hook.is_file() and "just check" in hook.read_text(encoding="utf-8")
    findings.append(
        Finding(
            id="assess.wiring.hook",
            severity=Severity.OK if hook_ok else Severity.WARN,
            category=_WIRING,
            title=f"pre-commit gate hook {'installed' if hook_ok else 'not installed'}",
            detail=".git/hooks/pre-commit running `just check`",
            fix=None if hook_ok else "run `just install-hooks`",
        )
    )
    return findings


def template_fit_findings(destination: Path) -> list[Finding]:
    config = load_config(destination)
    spec = gate_spec_for(config.template) if config.template else None
    if spec is None:
        return []
    present = [s for s in spec.detect_signals if (destination / s).exists()]
    if present:
        return [
            Finding(
                id="assess.fit.signal",
                severity=Severity.OK,
                category=_FIT,
                title="Template matches project signals",
                detail=f"found {', '.join(present)} for template {config.template}",
            )
        ]

    findings: list[Finding] = [
        Finding(
            id="assess.fit.signal",
            severity=Severity.WARN,
            category=_FIT,
            title="No language signal for configured template",
            detail=f"none of {list(spec.detect_signals)} found; cannot confirm template fit",
            fix="confirm `template` in .raven/config.toml matches this project",
        )
    ]
    for other_name, other_spec in load_gate_specs().items():
        if other_name == config.template:
            continue
        hit = [s for s in other_spec.detect_signals if (destination / s).exists()]
        if hit:
            findings.append(
                Finding(
                    id="assess.fit.mismatch",
                    severity=Severity.WARN,
                    category=_FIT,
                    title="Different language detected",
                    detail=f"found {', '.join(hit)} suggesting template {other_name}",
                    fix=f"consider `raven install {other_name}` if that is correct",
                )
            )
            break
    return findings


def build_assess_findings(
    destination: Path, run: bool, runner: Runner = gate_runner
) -> list[Finding]:
    config = load_config(destination)
    if not config.exists:
        return [
            Finding(
                id="assess.config.missing",
                severity=Severity.ERROR,
                category=_WIRING,
                title="Raven not installed here",
                detail="no .raven/config.toml; cannot assess against a template",
                fix="run `raven install <language>` first",
            )
        ]

    findings = wiring_findings(destination)
    if run:
        findings.extend(gate_compliance_findings(destination, runner))
    else:
        findings.append(
            Finding(
                id="assess.gates.skipped",
                severity=Severity.INFO,
                category=_GATES,
                title="Gates not executed (use --run)",
                detail="static checks only; pass --run for a true pass/fail verdict",
            )
        )
    findings.extend(template_fit_findings(destination))
    return findings
