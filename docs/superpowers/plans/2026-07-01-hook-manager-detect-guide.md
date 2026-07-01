# Hook-manager Detect + Guide Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make raven detect a hook manager (husky) instead of silently mis-installing into it: skip the manager-owned hooks dir, reword the misleading regular-file warning, and print/surface guidance on how to wire the gate through the manager.

**Architecture:** Add three helpers to `git_hooks.py` (`_hooks_dir_manager`, `detect_hook_manager`, `hook_manager_guidance`); make `install_git_hooks` skip a manager-owned dir and reword its warning; print guidance from `cli._run`; add an INFO finding from `doctor.build_doctor_findings`. Husky-first; no user files modified.

**Tech Stack:** Python 3.9+ stdlib, `unittest` (`tests/test_git_hooks.py`, `tests/test_doctor.py`), `raven_lib.findings.{Finding, Severity}`.

## Global Constraints

- Python 3.9+, stdlib-only; `from __future__ import annotations` already in the touched files.
- Husky detection: the effective hooks dir is `.husky/_` (i.e. `hooks_dir.name == "_" and hooks_dir.parent.name == ".husky"`).
- No user hook files are created or modified (detect + guide only).
- The reworded regular-file warning **must keep the substring** `already exists as a regular file` (existing test relies on it) and must no longer imply "remove it" is the only option.
- Normal (non-manager) repos: behavior unchanged.
- Commits: Conventional Commits, no AI attribution.

## File Structure

- `scripts/raven_lib/git_hooks.py` — detection + guidance helpers; `install_git_hooks` skip + reworded warning. Owns all manager knowledge.
- `scripts/raven_lib/cli.py` (`_run`) — prints guidance during install/upgrade.
- `scripts/raven_lib/doctor.py` — `hook_manager_findings` + wired into `build_doctor_findings`.
- `tests/test_git_hooks.py`, `tests/test_doctor.py` — tests.

Task 1 is the reusable core; Tasks 2 and 3 are independent presentation surfaces (doctor finding, install output) that a reviewer could accept separately.

---

### Task 1: Detection helpers, skip, and reworded warning (`git_hooks.py`)

**Files:**
- Modify: `scripts/raven_lib/git_hooks.py`
- Test: `tests/test_git_hooks.py`

**Interfaces:**
- Produces:
  - `_hooks_dir_manager(hooks_dir: Path) -> str | None` — `"husky"` when `hooks_dir` is `.husky/_`, else `None`.
  - `detect_hook_manager(destination: Path) -> str | None`.
  - `hook_manager_guidance(manager: str) -> str`.
  - `install_git_hooks` returns `[]` under a manager and no longer symlinks into it.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_git_hooks.py` in `GitHookInstallerTests`:

```python
    def _set_husky(self):
        (self.destination / ".husky" / "_").mkdir(parents=True)
        subprocess.run(
            ["git", "-C", str(self.destination), "config", "core.hooksPath", ".husky/_"],
            capture_output=True,
            check=True,
        )

    def test_detect_hook_manager_identifies_husky(self):
        self._set_husky()
        self.assertEqual(raven.detect_hook_manager(self.destination), "husky")

    def test_detect_hook_manager_none_for_normal_and_githooks(self):
        self.assertIsNone(raven.detect_hook_manager(self.destination))
        (self.destination / ".githooks").mkdir()
        subprocess.run(
            ["git", "-C", str(self.destination), "config", "core.hooksPath", ".githooks"],
            capture_output=True,
            check=True,
        )
        self.assertIsNone(raven.detect_hook_manager(self.destination))

    def test_install_skips_and_writes_nothing_under_husky(self):
        self._write_hook("pre-push", "#!/bin/sh\njust check\n")
        self._set_husky()

        installed = raven.install_git_hooks(self.destination)

        self.assertEqual(installed, [])
        self.assertFalse((self.destination / ".husky" / "_" / "pre-push").exists())

    def test_hook_manager_guidance_husky_names_husky_hooks(self):
        text = raven.hook_manager_guidance("husky")
        self.assertIn(".husky/pre-commit", text)
        self.assertIn(".husky/pre-push", text)

    def test_regular_file_warning_points_to_wiring(self):
        self._write_hook("pre-commit")
        existing = self.git_hooks_dir / "pre-commit"
        existing.write_text("#!/bin/sh\nmy own hook\n", encoding="utf-8")
        stderr = io.StringIO()

        with contextlib.redirect_stderr(stderr):
            installed = raven.install_git_hooks(self.destination)

        self.assertEqual(installed, [])
        msg = stderr.getvalue()
        self.assertIn("already exists as a regular file", msg)  # preserved substring
        self.assertIn("add `just check`", msg)  # no longer just "remove it"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_git_hooks.py -k "detect_hook_manager or skips_and_writes_nothing or guidance_husky or warning_points_to_wiring" -v`
Expected: `detect_hook_manager` and `guidance` tests FAIL with `AttributeError` (functions don't exist yet); `skips_and_writes_nothing` FAILS (install writes into `.husky/_` / warns); `warning_points_to_wiring` FAILS (message lacks "add `just check`"). `test_detect_hook_manager_none_for_normal_and_githooks` cannot pass until the function exists — it fails too.

- [ ] **Step 3: Add the detection + guidance helpers**

In `scripts/raven_lib/git_hooks.py`, add above `install_git_hooks` (after `git_hooks_dir`):

```python
def _hooks_dir_manager(hooks_dir: Path) -> str | None:
    """Name of the hook manager that owns ``hooks_dir``, or None.

    Husky sets ``core.hooksPath`` to ``.husky/_``; that directory is husky's,
    not Raven's. This is the single seam where other managers can be recognized.
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

- [ ] **Step 4: Make `install_git_hooks` skip a manager dir and reword the warning**

In `install_git_hooks`, right after `hooks_dir = git_hooks_dir(destination)` and its `None` guard, add the skip:

```python
    hooks_dir = git_hooks_dir(destination)
    if hooks_dir is None:
        return []
    if _hooks_dir_manager(hooks_dir) is not None:
        # A hook manager (e.g. husky) owns this directory; do not symlink into it.
        return []
```

And replace the regular-file warning block:

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

- [ ] **Step 5: Export the new helpers from the package**

`tests` call `raven.detect_hook_manager` / `raven.hook_manager_guidance`. In `scripts/raven_lib/__init__.py`, find the `from .git_hooks import install_git_hooks` line and extend it, and add the names to `__all__` next to `"install_git_hooks"`:

```python
from .git_hooks import detect_hook_manager, hook_manager_guidance, install_git_hooks
```

(Locate `"install_git_hooks",` in the `__all__` list and add `"detect_hook_manager",` and `"hook_manager_guidance",` beside it.)

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python -m pytest tests/test_git_hooks.py -k "detect_hook_manager or skips_and_writes_nothing or guidance_husky or warning_points_to_wiring" -v`
Expected: all PASS.

- [ ] **Step 7: Run the full hook suite (no regressions)**

Run: `python -m pytest tests/test_git_hooks.py -v`
Expected: all PASS. In particular `test_does_not_overwrite_existing_regular_file` still passes (its `already exists as a regular file` assertion is preserved), and the custom-`core.hooksPath=.githooks` install test still installs (that dir is not a manager).

- [ ] **Step 8: Commit**

```bash
git add scripts/raven_lib/git_hooks.py scripts/raven_lib/__init__.py tests/test_git_hooks.py
git commit -m "feat(hooks): detect husky and skip installing into a manager-owned hooks dir (#57)"
```

---

### Task 2: doctor INFO finding

**Files:**
- Modify: `scripts/raven_lib/doctor.py`
- Test: `tests/test_doctor.py`

**Interfaces:**
- Consumes: `detect_hook_manager`, `hook_manager_guidance` from `git_hooks`.
- Produces: `hook_manager_findings(destination: Path) -> list[Finding]`; composed into `build_doctor_findings`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_doctor.py` (import `hook_manager_findings` at the top: change the doctor import line to include it):

```python
    def test_hook_manager_finding_for_husky(self):
        from raven_lib.doctor import hook_manager_findings

        (self.destination / ".husky" / "_").mkdir(parents=True)
        subprocess.run(
            ["git", "-C", str(self.destination), "config", "core.hooksPath", ".husky/_"],
            capture_output=True,
            check=True,
        )
        findings = hook_manager_findings(self.destination)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].id, "doctor.hooks.manager")
        self.assertEqual(findings[0].severity, Severity.INFO)
        self.assertIn("husky", findings[0].title)

    def test_hook_manager_finding_absent_for_normal_repo(self):
        from raven_lib.doctor import hook_manager_findings

        self.assertEqual(hook_manager_findings(self.destination), [])
```

These need a git repo at `self.destination`. If the `test_doctor.py` `RavenTestCase` does not already `git init` the destination, add at the start of both tests:

```python
        subprocess.run(["git", "init", str(self.destination)], capture_output=True, check=True)
```

(and ensure `import subprocess` is present at the top of `tests/test_doctor.py`; it is already imported.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_doctor.py -k "hook_manager_finding" -v`
Expected: FAIL with `ImportError: cannot import name 'hook_manager_findings'`.

- [ ] **Step 3: Add `hook_manager_findings` and a category constant**

In `scripts/raven_lib/doctor.py`, add the import near the other `raven_lib` imports:

```python
from .git_hooks import detect_hook_manager, hook_manager_guidance
```

Add a category constant next to `_INTEGRITY`/`_DRIFT`/`_TOOLCHAIN`:

```python
_HOOKS = "Git hooks"
```

Add the function (place it just above `build_doctor_findings`):

```python
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
```

- [ ] **Step 4: Wire it into `build_doctor_findings`**

In `build_doctor_findings`, after `findings.extend(integrity)` (before the `config = load_config(...)` line), add:

```python
    findings.extend(hook_manager_findings(destination))
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/test_doctor.py -k "hook_manager_finding" -v`
Expected: both PASS.

- [ ] **Step 6: Run the full doctor suite (no regressions)**

Run: `python -m pytest tests/test_doctor.py -v`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add scripts/raven_lib/doctor.py tests/test_doctor.py
git commit -m "feat(doctor): surface an INFO finding when a hook manager owns the hooks dir (#57)"
```

---

### Task 3: install/upgrade prints guidance (`cli._run`)

**Files:**
- Modify: `scripts/raven_lib/cli.py`

**Interfaces:**
- Consumes: `detect_hook_manager`, `hook_manager_guidance` from `git_hooks`.

This is a thin presentation wire (calls Task 1's already-tested functions); it is verified by the real-world validation in Task 4 rather than a dedicated unit test, because exercising `_run` requires a full template install.

- [ ] **Step 1: Extend the git_hooks import in cli.py**

Change `scripts/raven_lib/cli.py` line 32:

```python
from .git_hooks import detect_hook_manager, hook_manager_guidance, install_git_hooks
```

- [ ] **Step 2: Print guidance after the install-hooks section**

In `_run`, immediately after the existing block:

```python
    if git_hooks_installed:
        print()
        print_section("Installed git hooks:", [f".git/hooks/{h}" for h in git_hooks_installed])
```

add:

```python
    else:
        manager = detect_hook_manager(destination)
        if manager:
            print()
            print_section(
                f"Hook manager detected ({manager}) -- Raven's hooks were not installed:",
                [hook_manager_guidance(manager)],
            )
```

- [ ] **Step 3: Verify it parses / imports cleanly**

Run: `python -c "import sys; sys.path.insert(0, 'scripts'); import raven_lib.cli"`
Expected: no output, exit 0 (module imports).

- [ ] **Step 4: Run the CLI and installer suites (no regressions)**

Run: `python -m pytest tests/test_cli.py tests/test_installer_safety.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/raven_lib/cli.py
git commit -m "feat(cli): print hook-manager guidance during install/upgrade when hooks are skipped (#57)"
```

---

### Task 4: Full self-check and real-world validation

**Files:** none (validation only).

- [ ] **Step 1: Run the self-check**

Run: `python scripts/self-check.py`
Expected: `RAVEN self-check passed` (assess/doctor/git_hooks are under `scripts/`, not templates; this validates ruff + the full pytest suite). Revert any incidental GitNexus-block / manifest churn (`git checkout -- AGENTS.md .raven/manifest.json`) if it appears, as in prior tasks — no template changed here.

- [ ] **Step 2: Real-world validation in a husky repo**

Run: `cd /Users/jpease/Developer/github/creativestack-org/timogin && raven doctor 2>&1 | rg -i "hook manager|husky"`
Expected: an INFO line reporting `hook manager detected (husky)` with the wiring guidance. (Confirms Task 2 end-to-end; timogin uses `core.hooksPath=.husky/_`.)

- [ ] **Step 3: Confirm normal repos are unaffected**

Run: `python -m pytest tests -q 2>&1 | tail -2`
Expected: full suite green.

---

## Self-Review

**1. Spec coverage:**
- `_hooks_dir_manager` / `detect_hook_manager` / `hook_manager_guidance` → Task 1. ✓
- `install_git_hooks` skips manager dir → Task 1 Step 4 + `test_install_skips_and_writes_nothing_under_husky`. ✓
- Reworded regular-file warning (keeps substring; adds wiring advice) → Task 1 Step 4 + `test_regular_file_warning_points_to_wiring` + Step 7 preserves `test_does_not_overwrite_existing_regular_file`. ✓
- doctor INFO finding → Task 2. ✓
- cli install/upgrade guidance → Task 3 (+ Task 4 real-world). ✓
- Normal repos unchanged → `test_detect_hook_manager_none_for_normal_and_githooks`, Step 7 regression, Task 4 Step 3. ✓
- Husky-first, no user-file modification → detection is the only manager; no writes to `.husky/*` (asserted in `test_install_skips_and_writes_nothing_under_husky`). ✓

**2. Placeholder scan:** No TBD/TODO; every code and command step is complete. The one conditional ("if RavenTestCase doesn't already git-init") gives the exact fallback line. ✓

**3. Type/name consistency:** `_hooks_dir_manager(hooks_dir)->str|None`, `detect_hook_manager(destination)->str|None`, `hook_manager_guidance(manager)->str`, `hook_manager_findings(destination)->list[Finding]`, finding id `doctor.hooks.manager`, category `_HOOKS="Git hooks"` — used consistently across tasks and tests. ✓
