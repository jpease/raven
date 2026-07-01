from __future__ import annotations

import re
from pathlib import Path

from .config import ConfigError, load_config
from .findings import Finding, Severity
from .gate_run import gate_compliance_findings
from .gates import gate_spec_for, load_gate_specs, recipe_present
from .git_hooks import git_hooks_dir
from .runner import Runner, gate_runner

_WIRING = "Quality-gate wiring"
_FIT = "Template fit"
_GATES = "Gate compliance"


def _invokes_just_recipe(text: str, recipe: str) -> bool:
    """True when ``text`` runs ``just <recipe>`` as a whole token.

    The trailing lookahead stops ``just check`` from matching ``just check-fast``
    (and vice versa), so the pre-push full-gate check is never satisfied by a hook
    that only runs the fast subset.
    """
    return re.search(rf"\bjust\s+{re.escape(recipe)}(?![\w-])", text) is not None


def resolve_manager_hook(hooks_dir: Path, name: str) -> Path:
    """Path to inspect for hook ``name``, following husky's wrapper.

    Husky sets ``core.hooksPath`` to ``.husky/_`` and puts a thin wrapper there
    that dispatches to the real user hook one level up (``.husky/<name>``). Always
    grade the real user-hook location, not the wrapper -- if ``.husky/<name>`` is
    absent the gate is genuinely unwired ("not installed"), never the wrapper.
    Any other layout is inspected as-is.
    """
    if hooks_dir.name == "_" and hooks_dir.parent.name == ".husky":
        return hooks_dir.parent / name
    return hooks_dir / name


def _hook_is_trivial(text: str) -> bool:
    """True when a hook has no executable content: only blank lines, a shebang,
    or ``#`` comments. Such a hook wires no gate, so it is "not installed"."""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            return False
    return True


def _hook_finding(
    destination: Path, hook: Path, name: str, expected: str, accept: tuple[str, ...]
) -> Finding:
    """Build the wiring Finding for one managed git hook (pre-commit or pre-push).

    ``expected`` is the canonical command for display. ``accept`` lists the
    ``just`` recipes that count as wired: pre-push requires the full ``check``,
    while pre-commit accepts ``check-fast`` or a stricter full ``check``. Matching
    is token-aware so ``just check-fast`` does not pass as the full push gate.
    """
    try:
        hook_display = hook.resolve().relative_to(destination.resolve())
    except ValueError:
        hook_display = hook

    not_installed = Finding(
        id=f"assess.wiring.hook.{name}",
        severity=Severity.WARN,
        category=_WIRING,
        title=f"{name} gate hook not installed",
        detail=f"{hook_display} should run `{expected}`",
        fix="run `just install-hooks`",
    )
    if not hook.is_file():
        return not_installed
    try:
        text = hook.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return Finding(
            id=f"assess.wiring.hook.{name}",
            severity=Severity.ERROR,
            category=_WIRING,
            title=f"{name} hook unreadable",
            detail=f"{hook_display}: {exc}",
            fix=f"fix or restore the {name} hook",
        )
    if _hook_is_trivial(text):
        return not_installed
    if any(_invokes_just_recipe(text, recipe) for recipe in accept):
        return Finding(
            id=f"assess.wiring.hook.{name}",
            severity=Severity.OK,
            category=_WIRING,
            title=f"{name} gate hook installed",
            detail=f"{hook_display} runs `{expected}`",
            fix=None,
        )
    if name == "pre-push" and _invokes_just_recipe(text, "check-fast"):
        return Finding(
            id=f"assess.wiring.hook.{name}",
            severity=Severity.WARN,
            category=_WIRING,
            title=f"{name} gate hook runs only the fast subset",
            detail=(
                f"{hook_display} runs `just check-fast`; "
                "the full `just check` gate never runs at push"
            ),
            fix="run `just check` (not `just check-fast`) in the pre-push hook",
        )
    return Finding(
        id=f"assess.wiring.hook.{name}",
        severity=Severity.INFO,
        category=_WIRING,
        title=f"{name} gate hook present (non-canonical)",
        detail=f"{hook_display} runs a custom gate, not `{expected}`",
        fix=None,
    )


def wiring_findings(destination: Path) -> list[Finding]:
    config = load_config(destination)
    spec = gate_spec_for(config.template) if config.template else None
    findings: list[Finding] = []
    if spec is None:
        # Distinguish "no template set" (warn) from "template set but unsupported" (error).
        severity = Severity.ERROR if config.template is not None else Severity.WARN
        return [
            Finding(
                id="assess.wiring.template",
                severity=severity,
                category=_WIRING,
                title="No gate spec for template",
                detail=f"template {config.template!r} has no gate expectations",
                fix="set a supported `template` in .raven/config.toml",
            )
        ]

    justfile = destination / "justfile"
    text = ""
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
    else:
        try:
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
        except (OSError, UnicodeDecodeError) as exc:
            findings.append(
                Finding(
                    id="assess.wiring.justfile",
                    severity=Severity.ERROR,
                    category=_WIRING,
                    title="justfile unreadable",
                    detail=f"{justfile}: {exc}",
                    fix="fix or restore the justfile",
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
        read_error: str | None = None
        if target.is_file():
            try:
                content = target.read_text(encoding="utf-8")
                ok = substring is None or substring in content
            except (OSError, UnicodeDecodeError) as exc:
                ok = False
                read_error = str(exc)
        else:
            ok = False
        if read_error is not None:
            findings.append(
                Finding(
                    id=f"assess.wiring.config.{file}",
                    severity=Severity.ERROR,
                    category=_WIRING,
                    title=f"tool config {file} unreadable",
                    detail=f"{target}: {read_error}",
                    fix=f"fix or restore {file}",
                )
            )
        else:
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

    # Inspect Git's effective hooks directory (honoring core.hooksPath and linked
    # worktrees) -- the same path the installer writes to -- not a hard-coded
    # .git/hooks, so a custom hooks path is not misreported as uninstalled.
    hooks_dir = git_hooks_dir(destination) or (destination / ".git" / "hooks")
    # pre-commit runs the fast subset; pre-push runs the full gate. Verify both
    # so a project missing the slower push-time safety net is not graded as
    # fully wired on the strength of pre-commit alone. pre-push must run the full
    # `check`; a `check-fast`-only pre-push is the missing safety net, so it does
    # not count.
    hook_specs = (
        ("pre-commit", "just check-fast", ("check-fast", "check")),
        ("pre-push", "just check", ("check",)),
    )
    for name, expected, accept in hook_specs:
        hook_path = resolve_manager_hook(hooks_dir, name)
        findings.append(_hook_finding(destination, hook_path, name, expected, accept))
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
    try:
        config = load_config(destination)
    except ConfigError as exc:
        return [
            Finding(
                id="assess.config.malformed",
                severity=Severity.ERROR,
                category=_WIRING,
                title="Raven config malformed",
                detail=str(exc),
                fix="fix the syntax in .raven/config.toml, then re-run",
            )
        ]
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
