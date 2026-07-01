# Hook-manager coexistence: detect + guide (#57)

**Date:** 2026-07-01
**Status:** Approved (design)
**Issue:** #57 — Hook-manager (husky/lefthook/pre-commit) coexistence: raven hooks silently bypassed
**Scope:** `scripts/raven_lib/git_hooks.py`, `scripts/raven_lib/cli.py` (`_run`), `scripts/raven_lib/doctor.py`, tests

## Problem

`install_git_hooks` symlinks `.raven/git-hooks/*` into the effective hooks dir (honoring `core.hooksPath`). Under a hook manager this misfires silently:

- **husky** sets `core.hooksPath=.husky/_`, so raven would try to symlink into husky's *internal* wrapper dir. The wrapper files are regular files, so raven skips them and prints `warning: … already exists as a regular file; remove it to let Raven manage it` — advice that, if followed, breaks husky. Raven's own hook never runs.
- **lefthook / pre-commit / beads** install regular-file hooks into `.git/hooks`; raven skips each with the same misleading "remove it" warning.

Net: raven either does nothing useful or gives advice that would damage the manager's setup, and never tells the user how to actually wire the gate.

## Decision

**Detect + guide, husky-first, no user-file modification.** Raven stops fighting the manager and tells the user how to wire the gate. Chosen over block-injection (modifies user hooks; bigger, riskier) and over per-manager detection (only husky mis-targets; a generic warning fix covers the rest).

## Design

### `git_hooks.py`

```python
def _hooks_dir_manager(hooks_dir: Path) -> str | None:
    """Name of the hook manager that owns ``hooks_dir``, or None.

    Husky sets ``core.hooksPath`` to ``.husky/_``; that directory is husky's,
    not Raven's. The single seam where other managers can be recognized later.
    """
    if hooks_dir.name == "_" and hooks_dir.parent.name == ".husky":
        return "husky"
    return None


def detect_hook_manager(destination: Path) -> str | None:
    """The hook manager owning ``destination``'s effective hooks dir, or None."""
    hooks_dir = git_hooks_dir(destination)
    return _hooks_dir_manager(hooks_dir) if hooks_dir is not None else None


def hook_manager_guidance(manager: str) -> str:
    """Human guidance for wiring Raven's gate through ``manager``."""
    if manager == "husky":
        return (
            "Detected husky (core.hooksPath). Raven does not install its own git "
            "hooks under a hook manager. To run Raven's gate, add `just check-fast` "
            "to .husky/pre-commit and `just check` to .husky/pre-push. Your hooks "
            "were left untouched."
        )
    return ""
```

`install_git_hooks` changes:
- After resolving `hooks_dir`, if `_hooks_dir_manager(hooks_dir) is not None`, `return []` (never symlink into a manager-owned dir).
- Reword the regular-file warning, preserving the `already exists as a regular file` substring:

```python
        if hook_link.exists() and not hook_link.is_symlink():
            print(
                f"warning: {hook_link} already exists as a regular file and was left "
                "untouched. To run Raven's gate, add `just check` / `just check-fast` "
                "to it, or remove it to let Raven manage the hook.",
                file=sys.stderr,
            )
            continue
```

### `cli.py` (`_run`)

After `git_hooks_installed = install_git_hooks(destination)` and the existing "Installed git hooks:" section, add:

```python
    manager = detect_hook_manager(destination)
    if manager and not git_hooks_installed:
        print()
        print_section(f"Hook manager detected ({manager}):", [hook_manager_guidance(manager)])
```

`detect_hook_manager` and `hook_manager_guidance` are imported from `git_hooks` (like `install_git_hooks`).

### `doctor.py`

Add a finding (INFO) when a manager is detected — a new small `hook_manager_findings(destination) -> list[Finding]` composed into doctor's finding list:

```python
def hook_manager_findings(destination: Path) -> list[Finding]:
    manager = detect_hook_manager(destination)
    if manager is None:
        return []
    return [
        Finding(
            id="doctor.hooks.manager",
            severity=Severity.INFO,
            category="Git hooks",
            title=f"hook manager detected ({manager})",
            detail=hook_manager_guidance(manager),
            fix=None,
        )
    ]
```

Wire it into wherever doctor aggregates its finding groups (mirroring the existing `integrity_findings` composition).

## Behavior changes

- **husky repos:** `raven install`/`upgrade` no longer attempts to symlink into `.husky/_`; prints the husky guidance instead; `raven doctor` shows an INFO "hook manager detected (husky)". No `.husky/_` files are written.
- **lefthook / pre-commit / beads / custom regular-file hooks:** unchanged behavior except the warning no longer tells the user to delete a hook they may need — it points them to wire `just check` instead.
- **Normal repos (no manager):** completely unchanged — `_hooks_dir_manager` returns None, install proceeds as before.

## Testing (tests/test_git_hooks.py + tests/test_doctor.py)

1. `detect_hook_manager` returns `"husky"` for a repo with `core.hooksPath=.husky/_`, `None` for a normal repo and for a `.githooks` custom-hooks repo.
2. `install_git_hooks` under husky: with `.raven/git-hooks/pre-push` present and `core.hooksPath=.husky/_`, returns `[]` and creates **no** file at `.husky/_/pre-push`.
3. Reworded regular-file warning: an existing `.git/hooks/pre-commit` regular file → returns `[]`, stderr contains both `already exists as a regular file` and `add \`just check\``.
4. `hook_manager_guidance("husky")` mentions `.husky/pre-commit` and `.husky/pre-push`.
5. `doctor` (or `hook_manager_findings`) on a husky repo yields an INFO `doctor.hooks.manager` finding; a normal repo yields none.
6. Existing hook-install tests continue to pass (normal repo, custom `core.hooksPath=.githooks` non-manager path, worktree install), and `test_does_not_overwrite_existing_regular_file` updated for the new wording (keeps its `already exists as a regular file` assertion).

## Out of scope

- Injecting a raven-managed block into user hooks (block-injection integration).
- Per-manager detection/guidance for lefthook, pre-commit, beads (the reworded warning covers them; husky is the only mis-targeting case).
- An assess-side finding (doctor is the chosen persistent surface; `wiring_findings` already grades the real hooks via #58).
