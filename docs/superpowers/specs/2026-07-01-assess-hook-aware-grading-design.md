# assess: hook-manager-aware, non-canonical-aware gate grading (#58, #59)

**Date:** 2026-07-01
**Status:** Approved (design)
**Issues:** #58 (husky wrapper graded as unwired), #59 (custom / hand-rolled gates graded "not installed")
**Scope:** `scripts/raven_lib/assess.py` (`wiring_findings`, `_hook_finding`, a new resolver helper), tests

## Problem

`raven assess` grades a git hook by grepping the file at `<effective-hooks-dir>/<name>` for `just check` / `just check-fast`. Two real-world shapes are misgraded as WARN "not installed":

- **#58 husky:** under husky, `core.hooksPath=.husky/_`, so assess reads `.husky/_/pre-push` — a 39-byte wrapper (`. "$(dirname "$0")/h"`) — instead of `.husky/pre-push`, where the real gate lives.
- **#59 custom / hand-rolled:** a hook that runs a real gate a different way — `swiftlint lint --strict`, `./fjcheck`, `just check-full`, `just build` + checks — doesn't match the canonical recipe, so it is flagged "not installed" and told to `run just install-hooks`, even though a substantive (sometimes stronger) gate already exists.

## Decision

Two focused changes to `assess.py`, no config (YAGNI):

1. **Husky-aware hook resolution** (#58): before grading, resolve a husky wrapper to the real user hook.
2. **Three-state grading** (#59): distinguish absent/trivial (WARN) from wired (OK) from substantive-but-non-canonical (INFO), and stop recommending `just install-hooks` when a real hook exists. Preserve issue #52's WARN for a pre-push that runs only the fast subset.

## Design

### Husky-aware resolution (#58)

New pure helper:

```python
def resolve_manager_hook(hooks_dir: Path, name: str) -> Path:
    """The path to inspect for a given hook, following husky's wrapper.

    Husky sets core.hooksPath to `.husky/_` and puts a thin wrapper there that
    dispatches to the real user hook one level up (`.husky/<name>`). Grade the
    real hook, not the wrapper. Any other layout is inspected as-is.
    """
    if hooks_dir.name == "_" and hooks_dir.parent.name == ".husky":
        real = hooks_dir.parent / name
        if real.exists():
            return real
    return hooks_dir / name
```

`wiring_findings` calls `resolve_manager_hook(hooks_dir, name)` and passes the result to `_hook_finding`. If the resolved husky hook does not exist, the path falls through to `.husky/_/<name>`... which also may not carry the gate — but the common case (real hook absent) is that `.husky/<name>` is missing, so grading reports "not installed" against the resolved path, which is correct.

Husky-only by choice; the helper is the single seam where lefthook/pre-commit resolution could be added later.

### Three-state grading (#59) in `_hook_finding`

Replace the binary OK/WARN with:

| State | Severity | When | Fix |
|---|---|---|---|
| installed | OK | hook invokes an accepted recipe (`just check` for pre-push; `just check-fast`/`just check` for pre-commit) | — |
| runs only the fast subset | WARN | **pre-push** invokes `just check-fast` but not `just check` (issue #52) | run the full `just check` in pre-push |
| present (non-canonical) | INFO | hook has substantive content but no accepted recipe (and not the #52 case) — a custom/hand-rolled gate | — (do **not** suggest install-hooks) |
| not installed | WARN | hook file absent, or trivial (only shebang / comments / blank lines) | run `just install-hooks` |

"Trivial" = after dropping blank lines, `#!`-shebang, and `#`-comment lines, nothing remains.

Grading order (first match wins): absent/trivial → OK(accepted) → #52 WARN → INFO(non-canonical).

Wording:
- OK: title `{name} gate hook installed`, detail `` {path} runs `{expected}` ``
- #52 WARN: title `{name} gate hook runs only the fast subset`, detail `` runs `just check-fast`; the full `just check` gate never runs at push ``, fix `run `just check` (not `just check-fast`) in the pre-push hook`
- INFO: title `{name} gate hook present (non-canonical)`, detail `` {path} runs a custom gate, not `{expected}` ``, fix `None`
- not installed WARN: unchanged from current (`should run` wording + `run just install-hooks`)

### Unreadable-hook handling

The existing ERROR path (unreadable / invalid-UTF-8 hook) is preserved unchanged.

## Behavior changes

- husky repos: pre-push/pre-commit graded against the real `.husky/<name>` hook.
- `.githooks`/`.git/hooks` repos with hand-rolled gates (swiftlint, fjcheck, `just build`, `just check-full`): now INFO "present (non-canonical)" instead of WARN "not installed"; no more misleading `just install-hooks` suggestion.
- **Unchanged:** absent hooks still WARN "not installed"; canonical hooks still OK; issue #52 (pre-push runs only `check-fast`) still WARN.

## Testing

New/updated tests in `tests/test_assess.py`:

1. **Husky resolution (#58):** temp repo, `core.hooksPath=.husky/_`, `.husky/_/pre-push` = husky wrapper, `.husky/pre-push` = `#!/bin/sh\njust check` → pre-push finding is OK (grades the real hook, not the wrapper).
2. **Husky real hook missing:** `.husky/_/pre-push` exists but no `.husky/pre-push` → WARN "not installed".
3. **Non-canonical is INFO (#59):** `.git/hooks/pre-commit` = `#!/bin/sh\nswiftlint lint --strict` (template swift) → INFO "present (non-canonical)", `fix is None`, and detail does not say "not installed".
4. **Non-canonical does not suggest install-hooks:** the INFO finding's fix is None.
5. **Absent/trivial stays WARN:** empty hook and shebang-only hook → WARN "not installed".
6. **#52 preserved:** pre-push running only `just check-fast` → WARN "runs only the fast subset" (regression guard for `test_pre_push_running_only_check_fast_warns`).
7. **Canonical stays OK:** unchanged existing tests pass.

## Out of scope

- `[gates]` config to promote a declared custom recipe to OK (deferred; INFO is the ceiling without config).
- lefthook / pre-commit-framework resolution (#57 territory).
- Changing how hooks are *installed* under a manager (#57).
