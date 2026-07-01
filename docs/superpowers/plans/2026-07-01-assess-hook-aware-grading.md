# assess Hook-Aware Grading Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `raven assess` grade git hooks correctly for husky-managed repos (follow the wrapper to the real hook) and for hand-rolled/custom gates (report INFO "present (non-canonical)" instead of a false "not installed" WARN).

**Architecture:** Two focused changes to `scripts/raven_lib/assess.py`: a pure `resolve_manager_hook` helper that maps a husky wrapper path to the real user hook, wired into `wiring_findings`; and a rewritten `_hook_finding` with a four-state grade (OK / WARN-fast-subset / INFO-non-canonical / WARN-not-installed). No config, no new files.

**Tech Stack:** Python 3.9+ stdlib, `unittest` (`tests/test_assess.py`), `raven_lib.findings.Severity` (has INFO/OK/WARN/ERROR).

## Global Constraints

- Python 3.9+, stdlib-only; `from __future__ import annotations` already in `assess.py`.
- `Severity` values: `INFO`, `OK`, `WARN`, `ERROR` (all already imported in `assess.py`).
- Grading order (first match wins): absent-or-trivial → OK(accepted recipe) → #52 pre-push-fast-subset → INFO(non-canonical).
- **Preserve issue #52:** a pre-push that runs only `just check-fast` (not `just check`) stays WARN.
- **Preserve the ERROR path** for unreadable / invalid-UTF-8 hooks, unchanged.
- Husky-only resolution: `.husky/_/<name>` → `.husky/<name>` when the real hook exists.
- Do not suggest `just install-hooks` when a substantive hook already exists.
- Commits: Conventional Commits, no AI attribution.

## File Structure

- `scripts/raven_lib/assess.py` — gains `resolve_manager_hook` + `_hook_is_trivial` helpers; `_hook_finding` rewritten; `wiring_findings` calls the resolver. One file; both concerns live together because they share the hook-grading path.
- `tests/test_assess.py` — new tests in `AssessWiringTests` (the class holding `_hook_finding`) and reuse of existing patterns.

Task 1 (resolver + wiring) and Task 2 (grading) are separable: Task 1 is testable with today's binary grading (a husky hook running `just check` grades OK), and a reviewer could accept husky resolution while questioning the grade taxonomy, or vice versa.

---

### Task 1: Husky-aware hook resolution (#58)

**Files:**
- Modify: `scripts/raven_lib/assess.py` (add `resolve_manager_hook`; call it in `wiring_findings`)
- Test: `tests/test_assess.py`

**Interfaces:**
- Produces: `resolve_manager_hook(hooks_dir: Path, name: str) -> Path` — the path to grade for hook `name`, following husky's wrapper.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_assess.py` in the `AssessHookPathTests` class (the one with `_hook_finding` helper and the `core.hooksPath` fixture):

```python
    def test_husky_grades_real_hook_not_wrapper(self):
        # #58: under husky, core.hooksPath is .husky/_ and the file there is a thin
        # wrapper. The real gate lives in .husky/<name>; assess must grade that.
        husky = self.destination / ".husky"
        (husky / "_").mkdir(parents=True)
        subprocess.run(
            ["git", "-C", str(self.destination), "config", "core.hooksPath", ".husky/_"],
            capture_output=True,
            check=True,
        )
        (husky / "_" / "pre-push").write_text('#!/usr/bin/env sh\n. "$(dirname "$0")/h"\n', encoding="utf-8")
        (husky / "pre-push").write_text("#!/bin/sh\njust check\n", encoding="utf-8")
        self.assertEqual(self._hook_finding("pre-push").severity, Severity.OK)

    def test_husky_missing_real_hook_is_not_installed(self):
        # Husky wrapper present but no .husky/pre-push -> the gate hook is absent.
        husky = self.destination / ".husky"
        (husky / "_").mkdir(parents=True)
        subprocess.run(
            ["git", "-C", str(self.destination), "config", "core.hooksPath", ".husky/_"],
            capture_output=True,
            check=True,
        )
        (husky / "_" / "pre-push").write_text('#!/usr/bin/env sh\n. "$(dirname "$0")/h"\n', encoding="utf-8")
        finding = self._hook_finding("pre-push")
        self.assertEqual(finding.severity, Severity.WARN)
        self.assertIn("not installed", finding.title)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_assess.py -k "husky_grades_real_hook or husky_missing_real_hook" -v`
Expected: `test_husky_grades_real_hook_not_wrapper` FAILS (the wrapper doesn't contain `just check`, so today's grading returns WARN). The missing-hook test may pass already; it locks in behavior.

- [ ] **Step 3: Add the resolver helper**

In `scripts/raven_lib/assess.py`, add this function immediately above `_hook_finding` (before line 28):

```python
def resolve_manager_hook(hooks_dir: Path, name: str) -> Path:
    """Path to inspect for hook ``name``, following husky's wrapper.

    Husky sets ``core.hooksPath`` to ``.husky/_`` and puts a thin wrapper there
    that dispatches to the real user hook one level up (``.husky/<name>``). Grade
    the real hook, not the wrapper. Any other layout is inspected as-is.
    """
    if hooks_dir.name == "_" and hooks_dir.parent.name == ".husky":
        real = hooks_dir.parent / name
        if real.exists():
            return real
    return hooks_dir / name
```

- [ ] **Step 4: Wire it into `wiring_findings`**

In `scripts/raven_lib/assess.py`, find the hook-spec loop (currently):

```python
    for name, expected, accept in hook_specs:
        findings.append(_hook_finding(destination, hooks_dir / name, name, expected, accept))
```

Replace `hooks_dir / name` with the resolver:

```python
    for name, expected, accept in hook_specs:
        hook_path = resolve_manager_hook(hooks_dir, name)
        findings.append(_hook_finding(destination, hook_path, name, expected, accept))
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_assess.py -k "husky_grades_real_hook or husky_missing_real_hook" -v`
Expected: both PASS.

- [ ] **Step 6: Run the full assess suite (no regressions)**

Run: `python -m pytest tests/test_assess.py -v`
Expected: all PASS (non-husky repos resolve to `hooks_dir / name` exactly as before).

- [ ] **Step 7: Export the helper (module API parity)**

`assess.py` symbols used by tests are imported via `from raven_lib.assess import ...`. `resolve_manager_hook` is called internally, so no `__init__.py` export is required. Confirm the test import line still reads `from raven_lib.assess import build_assess_findings, template_fit_findings, wiring_findings` (unchanged). No action if so.

- [ ] **Step 8: Commit**

```bash
git add scripts/raven_lib/assess.py tests/test_assess.py
git commit -m "fix(assess): follow husky wrapper to the real hook when grading (#58)"
```

---

### Task 2: Four-state, non-canonical-aware grading (#59)

**Files:**
- Modify: `scripts/raven_lib/assess.py` (add `_hook_is_trivial`; rewrite `_hook_finding` grading)
- Test: `tests/test_assess.py`

**Interfaces:**
- Consumes: `resolve_manager_hook` from Task 1 (already wired).
- Produces: `_hook_finding` now returns one of four grades: OK, WARN (fast-subset, #52), INFO (present non-canonical), WARN (not installed). `_hook_is_trivial(text: str) -> bool`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_assess.py` in `AssessHookPathTests`:

```python
    def test_custom_hand_rolled_hook_is_info_not_warn(self):
        # #59: a substantive hook running a real gate a non-canonical way
        # (swiftlint directly) is INFO "present (non-canonical)", not a WARN.
        hooks = self.destination / ".git" / "hooks"
        hooks.mkdir(parents=True, exist_ok=True)
        (hooks / "pre-commit").write_text(
            "#!/bin/sh\nset -e\nswiftlint lint --strict\n", encoding="utf-8"
        )
        finding = self._hook_finding("pre-commit")
        self.assertEqual(finding.severity, Severity.INFO)
        self.assertIn("non-canonical", finding.title)
        self.assertIsNone(finding.fix)  # never suggests just install-hooks
        self.assertNotIn("not installed", finding.title)

    def test_custom_pre_push_gate_is_info(self):
        # A pre-push running a custom `just` recipe (check-full) is non-canonical
        # INFO, not the fast-subset WARN and not "not installed".
        hooks = self.destination / ".git" / "hooks"
        hooks.mkdir(parents=True, exist_ok=True)
        (hooks / "pre-push").write_text("#!/bin/sh\njust check-full\n", encoding="utf-8")
        finding = self._hook_finding("pre-push")
        self.assertEqual(finding.severity, Severity.INFO)

    def test_trivial_hook_is_not_installed(self):
        # A hook that is only a shebang/comments has no gate -> WARN not installed.
        hooks = self.destination / ".git" / "hooks"
        hooks.mkdir(parents=True, exist_ok=True)
        (hooks / "pre-commit").write_text("#!/bin/sh\n# nothing here\n", encoding="utf-8")
        finding = self._hook_finding("pre-commit")
        self.assertEqual(finding.severity, Severity.WARN)
        self.assertIn("not installed", finding.title)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_assess.py -k "hand_rolled_hook or custom_pre_push or trivial_hook" -v`
Expected: `test_custom_hand_rolled_hook_is_info_not_warn` and `test_custom_pre_push_gate_is_info` FAIL (today they grade WARN "not installed"). `test_trivial_hook_is_not_installed` passes already (WARN today).

- [ ] **Step 3: Add the trivial-content helper**

In `scripts/raven_lib/assess.py`, add above `_hook_finding`:

```python
def _hook_is_trivial(text: str) -> bool:
    """True when a hook has no executable content: only blank lines, a shebang,
    or ``#`` comments. Such a hook wires no gate, so it is "not installed"."""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            return False
    return True
```

- [ ] **Step 4: Rewrite `_hook_finding` grading**

In `scripts/raven_lib/assess.py`, replace the whole body of `_hook_finding` (the part from `try:`/`hook_display` through the final `return Finding(...)`) with:

```python
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
            detail=f"{hook_display} runs `just check-fast`; the full `just check` gate never runs at push",
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
```

Keep the function signature and docstring; only the body below the docstring changes.

- [ ] **Step 5: Run the new tests**

Run: `python -m pytest tests/test_assess.py -k "hand_rolled_hook or custom_pre_push or trivial_hook" -v`
Expected: all PASS.

- [ ] **Step 6: Run the full assess suite (regression guard for #52 and existing grades)**

Run: `python -m pytest tests/test_assess.py -v`
Expected: all PASS. In particular `test_pre_push_running_only_check_fast_warns` (issue #52) still WARN, `test_active_hooks_in_custom_hooks_path_are_ok` still OK, `test_missing_hooks_in_normal_repo_warn` still WARN, `test_invalid_utf8_hook_emits_error_finding` still ERROR, and the Task 1 husky tests still pass.

- [ ] **Step 7: Commit**

```bash
git add scripts/raven_lib/assess.py tests/test_assess.py
git commit -m "feat(assess): grade custom hooks as INFO present (non-canonical) instead of not-installed (#59)"
```

---

### Task 3: Full self-check

**Files:** none (validation only).

**Interfaces:** Consumes Tasks 1–2.

- [ ] **Step 1: Run the self-check**

Run: `python scripts/self-check.py`
Expected: prints `RAVEN self-check passed` (assess.py is under `scripts/`, not a template, so the upgrade step changes nothing; this validates ruff + the full pytest suite including `test_doctor.py`, which also renders findings).

If it fails, inspect only the failing output before proceeding.

- [ ] **Step 2: Commit any installed-tree sync (if the upgrade touched the manifest)**

```bash
git status --short
# If only .raven/manifest.json changed:
git add .raven/manifest.json && git commit -m "chore(self-install): apply raven upgrade to installed tree"
# If nothing changed, skip.
```

---

## Self-Review

**1. Spec coverage:**
- Husky resolution (#58) → Task 1 (`resolve_manager_hook` + wiring + 2 tests). ✓
- Four-state grading (#59) → Task 2 (`_hook_is_trivial` + rewrite + 3 tests). ✓
- Preserve #52 WARN → Task 2 grading branch + Step 6 regression check. ✓
- Preserve ERROR path → Task 2 rewrite keeps the unreadable branch. ✓
- No `install-hooks` suggestion for substantive hooks → INFO branch has `fix=None`; asserted in `test_custom_hand_rolled_hook_is_info_not_warn`. ✓
- Trivial = shebang/comments/blank → `_hook_is_trivial` + `test_trivial_hook_is_not_installed`. ✓
- Husky-only, single seam → Task 1 helper. ✓

**2. Placeholder scan:** No TBD/TODO; every code and command step is complete. ✓

**3. Type/name consistency:** `resolve_manager_hook(hooks_dir, name) -> Path`, `_hook_is_trivial(text) -> bool`, `_hook_finding(destination, hook, name, expected, accept)` used consistently. Test helper `self._hook_finding(name)` (existing) returns the finding for `assess.wiring.hook.{name}`. Grade order (absent/trivial → OK → #52 → INFO) matches the spec table. ✓
