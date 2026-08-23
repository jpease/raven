"""Build the `raven assess` report: whether gate wiring, template fit, and gate runs are healthy.

Unlike `doctor` (install integrity), this module judges whether the *project*
itself -- its git hooks, its detected language, its gate recipes -- lives up to
what Raven's template expects, optionally by actually running the gates.
"""

from __future__ import annotations

import re
import shlex
from pathlib import Path

from .config import ConfigError, load_config
from .findings import Finding, Severity
from .gate_run import gate_compliance_findings
from .gates import gate_spec_for, load_gate_specs, recipe_present
from .git_hooks import git_hooks_dir
from .runner import Runner, gate_runner
from .template import is_known_template

_WIRING = "Quality-gate wiring"
_FIT = "Template fit"
_GATES = "Gate compliance"

# Tokens made up solely of these characters are top-level shell operators that
# separate one simple command from the next.
_OPERATOR_CHARS = frozenset(";|&()<>")

# Commands that pass through to their argument list without changing what
# actually runs, so `exec just check` / `env just check` still count as `just`
# being the effective command.
_TRANSPARENT_WRAPPERS = frozenset({"exec", "command", "env", "sudo", "time", "nice", "builtin"})

_ENV_ASSIGNMENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")

# A just recipe header sits at column 0 and every body line is indented, so the
# pattern is anchored there: `recipe_present`'s looser `^\s*` tolerance would
# read a body line holding a colon (`echo "note: x"`) as a recipe declaration,
# which would corrupt the dependency graph below. `(?!=)` keeps `alias t := x`
# and `set shell := [...]` out.
_RECIPE_HEADER_RE = re.compile(r"^@?(?P<name>[A-Za-z0-9_-]+)(?:\s+[^:=]*?)?:(?!=)(?P<deps>.*)$")
_RECIPE_NAME_RE = re.compile(r"[A-Za-z][A-Za-z0-9_-]*")
# `just <recipe>` in a recipe body -- the other way one recipe reaches another
# when it is not declared as a dependency.
_JUST_CALL_RE = re.compile(r"\bjust\s+(?:-\S+\s+)*([A-Za-z][A-Za-z0-9_-]*)")


def _command_segments(text: str) -> list[list[str]]:
    """Split hook text into simple-command segments of tokens.

    Splits on top-level shell operators (``;`` ``|`` ``&`` ``(`` ``)`` ``<``
    ``>``) while respecting quotes, and drops ``#`` comments -- shlex handles
    both natively. On a lexer error such as unbalanced quotes, that line falls
    back to a whitespace split so a malformed-but-real invocation still has a
    chance (best effort -- err toward more checking).
    """
    segments: list[list[str]] = []
    for line in text.splitlines():
        try:
            lexer = shlex.shlex(line, posix=True, punctuation_chars=True)
            lexer.whitespace_split = True
            tokens = list(lexer)
        except ValueError:
            segments.append(line.split())
            continue

        current: list[str] = []
        for token in tokens:
            if token and all(ch in _OPERATOR_CHARS for ch in token):
                segments.append(current)
                current = []
            else:
                current.append(token)
        segments.append(current)

    return [segment for segment in segments if segment]


def _effective_command(segment: list[str]) -> tuple[str, str | None]:
    """Return (command, arg-right-after-command) for one simple-command segment.

    Skips leading environment assignments (``RAVEN=1``) and transparent
    wrappers (``exec``, ``sudo``, ...) so ``exec just check`` still resolves to
    the command ``just``.
    """
    index = 0
    while index < len(segment):
        token = segment[index]
        if token in _TRANSPARENT_WRAPPERS or _ENV_ASSIGNMENT_RE.match(token):
            index += 1
            continue
        break
    if index >= len(segment):
        return "", None
    command = segment[index]
    arg = segment[index + 1] if index + 1 < len(segment) else None
    return command, arg


def _invokes_just_recipe(text: str, recipe: str) -> bool:
    """True when ``text`` actually runs ``just <recipe>`` as a command.

    Tokenizes with shell semantics (quotes, comments, escapes) instead of
    substring-matching, so quoting the recipe (``just "check"``) does not
    hide it (#108) and an echoed/printed/commented-out reference (``echo "just
    check"``, ``# just check``) is never mistaken for the gate actually
    running (#72). The recipe must be the exact token right after ``just``, so
    ``just check-fast`` never satisfies a check for ``check`` (and vice versa).
    """
    for segment in _command_segments(text):
        command, arg = _effective_command(segment)
        if command == "just" and arg == recipe:
            return True
    return False


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
    or ``#`` comments. Such a hook wires no gate, so it is "not installed".
    """
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


def _recipe_graph(text: str) -> dict[str, set[str]]:
    """Map each justfile recipe to the recipes it reaches.

    A recipe reaches its declared dependencies plus anything its body runs as
    `just <recipe>`. Tokens inside a parameterized dependency (`(build mode)`)
    are collected too; a name that matches no recipe only adds an unreachable
    node, and callers ask about membership rather than reading the set back.
    """
    graph: dict[str, set[str]] = {}
    current: str | None = None
    for line in text.splitlines():
        header = _RECIPE_HEADER_RE.match(line)
        if header:
            name = header.group("name")
            current = name
            graph.setdefault(name, set()).update(_RECIPE_NAME_RE.findall(header.group("deps")))
            continue
        if current is None:
            continue
        if line.strip() and not line[:1].isspace():
            # An unindented non-header line (a setting, an alias, an export)
            # ends the body; anything after it belongs to no recipe.
            current = None
            continue
        graph[current].update(_JUST_CALL_RE.findall(line))
    return graph


# just's per-line body prefixes: `@` quiets the echo, `-` ignores that line's
# exit status. Both may appear, in either order.
_LINE_PREFIX_CHARS = "@-"
# The right-hand side of a `||` that turns any failure into success.
_ALWAYS_TRUE = frozenset({"true", ":"})


def _line_tokens(line: str) -> list[str]:
    """Tokenize one recipe body line, keeping shell operators as their own tokens.

    Unlike `_command_segments`, which drops the operators after splitting on
    them, this keeps `||` and `;` -- telling `cmd || true` from `cmd && true`
    is the whole point here. posix-mode shlex also drops `#` comments and
    keeps a quoted string as one token, so a printed or commented-out
    construct is never read as a real one (the rule `_invokes_just_recipe`
    already follows for `just check`).
    """
    try:
        lexer = shlex.shlex(line, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        return list(lexer)
    except ValueError:
        return line.split()


def _swallows_failure(tokens: list[str], *, ignore_prefix: bool) -> str | None:
    """Name the construct that discards this line's exit status, or None."""
    if ignore_prefix:
        return "the `-` prefix"
    for index, token in enumerate(tokens[:-1]):
        if token == "||" and tokens[index + 1] in _ALWAYS_TRUE:
            return f"`|| {tokens[index + 1]}`"
    if tokens[-2:] == ["exit", "0"]:
        return "`exit 0`"
    return None


def _recipe_body(text: str, recipe: str) -> list[str] | None:
    """The body lines of one recipe, or None when the justfile does not declare it.

    Same walk `_recipe_graph` uses: the body is every line after the header
    until an unindented non-blank line, so a blank line inside a body does not
    end it.
    """
    body: list[str] | None = None
    for line in text.splitlines():
        header = _RECIPE_HEADER_RE.match(line)
        if header:
            if body is not None:
                return body
            if header.group("name") == recipe:
                body = []
            continue
        if body is None:
            continue
        if line.strip() and not line[:1].isspace():
            return body
        body.append(line)
    return body


def _unfailable_reason(body: list[str]) -> str | None:
    """Name why this recipe body can never report a failure, or None if it can.

    Two shapes, because `just` runs a body two different ways. An ordinary
    recipe runs each line as its own command and aborts at the first failure,
    so it stays a real gate as long as *any* line can still fail -- only a
    body where every line is swallowed is inert. A shebang recipe runs as one
    script, where the last command decides the status; `set -e` puts every
    earlier line back in play, so a body carrying it is left alone.
    """
    commands: list[tuple[list[str], bool]] = []
    shebang = False
    for index, line in enumerate(body):
        stripped = line.strip()
        if not stripped:
            continue
        if not commands and not shebang and index == _first_content_index(body):
            shebang = stripped.startswith("#!")
            if shebang:
                continue
        rest = stripped.lstrip(_LINE_PREFIX_CHARS)
        prefix = stripped[: len(stripped) - len(rest)]
        tokens = _line_tokens(rest)
        if not tokens:
            continue
        commands.append((tokens, "-" in prefix))
    if not commands:
        return None
    if shebang:
        if any(tokens[:2] == ["set", "-e"] for tokens, _ in commands):
            return None
        tokens, ignore_prefix = commands[-1]
        return _swallows_failure(tokens, ignore_prefix=ignore_prefix)
    reasons = [_swallows_failure(t, ignore_prefix=p) for t, p in commands]
    return reasons[0] if all(reasons) else None


def _first_content_index(body: list[str]) -> int:
    """Index of the first non-blank body line, or -1 when the body is empty."""
    for index, line in enumerate(body):
        if line.strip():
            return index
    return -1


def _recipes_reachable_from(text: str, root: str) -> set[str] | None:
    """Every recipe `just <root>` ends up running, or None when `root` is undeclared."""
    graph = _recipe_graph(text)
    if root not in graph:
        return None
    seen: set[str] = set()
    queue = [root]
    while queue:
        for dep in graph.get(queue.pop(), ()):
            if dep not in seen:
                seen.add(dep)
                queue.append(dep)
    return seen


def wiring_findings(destination: Path) -> list[Finding]:
    """Check that pre-commit/pre-push hooks invoke the template's canonical gate recipes."""
    config = load_config(destination)
    spec = gate_spec_for(config.template) if config.template else None
    findings: list[Finding] = []
    if spec is None:
        # `gate_spec_for(name) is None` means only "this template ships no
        # GATE_DATA entry", not "this is not a real template" -- `dotfiles` is a
        # genuine template that legitimately has no gate recipes or tools. So the
        # template name is judged against the actual roster, not the gate table
        # (issue #191; the same conflation #187 fixed in `doctor`). Three distinct
        # states, no gate wiring to check in any of them:
        if config.template is None:
            return [
                Finding(
                    id="assess.wiring.template",
                    severity=Severity.WARN,
                    category=_WIRING,
                    title="No template configured",
                    detail="config has no template; gate expectations are unknown",
                    fix="set a supported `template` in .raven/config.toml",
                )
            ]
        if not is_known_template(config.template):
            return [
                Finding(
                    id="assess.wiring.template",
                    severity=Severity.ERROR,
                    category=_WIRING,
                    title="Unsupported template configured",
                    detail=f"template {config.template!r} is not a supported Raven template",
                    fix="set a supported `template` in .raven/config.toml",
                )
            ]
        return [
            Finding(
                id="assess.wiring.template",
                severity=Severity.INFO,
                category=_WIRING,
                title="Template ships no quality gates",
                detail=f"template {config.template!r} defines no gate recipes or tools to check",
                fix=None,
            )
        ]

    justfile = destination / "justfile"
    text = ""
    justfile_read = False
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
            justfile_read = True
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

    # A recipe that runs the tool but throws away its exit status is a third
    # way a gate stops being a constraint, and the only one no run can reveal:
    # the tool prints its findings and the recipe exits 0 regardless. Graded
    # over the template's declared gate recipes only, which is what keeps the
    # report-only `audit` recipe every template ships -- it ends in `exit 0`
    # deliberately -- out of this check.
    if justfile_read:
        for recipe in spec.recipes:
            body = _recipe_body(text, recipe)
            reason = _unfailable_reason(body) if body is not None else None
            if reason is None:
                continue
            findings.append(
                Finding(
                    id=f"assess.wiring.failable.{recipe}",
                    severity=Severity.WARN,
                    category=_WIRING,
                    title=f"gate recipe '{recipe}' cannot fail",
                    detail=f"`{recipe}` discards its exit status via {reason}",
                    fix=f"remove {reason} from the `{recipe}:` recipe",
                )
            )

    # A declared gate recipe is not yet a gate. Both hooks run `just check`, so
    # a recipe `check` never reaches is one no commit and no push can fail on --
    # the state a suite is in when every recipe above grades OK and nothing
    # enforces any of them.
    declared = [recipe for recipe in spec.recipes if recipe_present(text, recipe)]
    reachable = _recipes_reachable_from(text, "check") if justfile_read else set()
    if justfile_read and reachable is None:
        findings.append(
            Finding(
                id="assess.wiring.check",
                severity=Severity.WARN,
                category=_WIRING,
                title="no `check` recipe",
                detail="the pre-push hook runs `just check`, which this justfile does not declare",
                fix="add a `check:` recipe depending on the gate recipes",
            )
        )
    elif justfile_read and declared and reachable is not None:
        ungated = [recipe for recipe in declared if recipe not in reachable]
        findings.append(
            Finding(
                id="assess.wiring.check",
                severity=Severity.WARN if ungated else Severity.OK,
                category=_WIRING,
                title=f"`check` runs {len(declared) - len(ungated)} of "
                f"{len(declared)} declared gate recipes",
                detail=(
                    "declared but never run by `check`: " + ", ".join(f"`{r}`" for r in ungated)
                    if ungated
                    else "every declared gate recipe runs at push time"
                ),
                fix=(
                    "add " + ", ".join(f"`{r}`" for r in ungated) + " to the `check:` dependencies"
                    if ungated
                    else None
                ),
            )
        )
    # `test` outside the template's gate recipes is a deliberate exclusion (the
    # swift template keeps an Xcode UI suite off every push). Report it anyway:
    # a repo whose tests cannot fail a push should know that from the report
    # rather than from the first regression that ships.
    if (
        justfile_read
        and "test" not in spec.recipes
        and recipe_present(text, "test")
        and reachable is not None
        and "test" not in reachable
    ):
        findings.append(
            Finding(
                id="assess.wiring.check.test",
                severity=Severity.INFO,
                category=_WIRING,
                title="`test` is defined but the push gate never runs it",
                detail=f"template {config.template!r} keeps `test` out of `check` by design",
                fix=None,
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
    """Check the configured template's detect signals against the project, flagging a mismatch.

    On a miss, scans every *other* template's signals too and names the first
    one that hits, so the warning can suggest a likely correct template instead
    of only saying the configured one is wrong.
    """
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
    """Assemble wiring and template-fit findings, plus gate-compliance findings when ``run`` is set.

    Gates are only actually executed when ``run=True`` -- callers that just want
    the cheap, read-only checks (e.g. a fast `doctor` path) pass ``run=False``
    and skip invoking `gate_compliance_findings` entirely.
    """
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
