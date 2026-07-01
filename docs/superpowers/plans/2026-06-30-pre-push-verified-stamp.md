# Pre-push Verified-Commit Stamp Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Raven's shipped pre-push hook skip `just check` when the current commit was already verified against a clean working tree, eliminating redundant full-gate runs on retry pushes.

**Architecture:** Add a marker/stamp file (HEAD SHA) under the git dir. The hook skips the gate when HEAD matches the stamp AND the tree is clean, and writes the stamp only after a clean pass. All logic lives in the one shared hook file `common/.raven/git-hooks/pre-push`, so it reaches every language tree at once. The stamp is a pure optimization: every failure mode falls through to running the gate.

**Tech Stack:** POSIX `sh` (the hook), Python `unittest` + `subprocess` (the tests, matching `tests/test_git_hooks.py`), `just` task runner, Raven's `scripts/self-check.py` for installed-tree propagation.

## Global Constraints

- **Hook must be POSIX `sh`** — no bashisms (no `[[ ]]`, no arrays, no `local`). Match the existing hook's style.
- **The stamp is never a correctness dependency** — a missing, unreadable, or unwritable stamp must always fall through to running the gate. Stamp-write failures are swallowed with `|| true`.
- **"Clean tree" = `git status --porcelain` is empty**, which counts untracked files as dirty (deliberate, conservative).
- **Stamp path:** `"$(git rev-parse --git-dir)/raven-pre-push-verified"` — per-worktree, never tracked.
- **Tests:** Python 3.9+ stdlib-only, `unittest`, follow the existing fake-`git` / fake-`just` / `_hook_env` patterns in `tests/test_git_hooks.py`.
- **Commits:** Conventional Commits format, no AI attribution footers (no `Co-Authored-By`).
- **Do not hand-edit the installed copy** `.raven/git-hooks/pre-push` — it is synced from `common/` via `scripts/self-check.py` (upgrade).
- **Out of scope:** the `install-hooks` justfile fallback recipe (one-liner `just check` hook).

## File Structure

- `common/.raven/git-hooks/pre-push` — the shared pre-push hook. Gains a skip block (read path) and a stamp-write block (write path).
- `tests/test_git_hooks.py` — the hook test suite. Gains one helper plus five tests.
- `.raven/git-hooks/pre-push`, `.raven/manifest.json` (and any other files the upgrade touches) — the installed tree, updated mechanically by `self-check.py`, committed as a separate `chore(self-install)` commit.

Tasks 1 and 2 both edit the same hook file but are split by concern: Task 1 is the read path (risk: skipping when it should run), Task 2 is the write path (risk: stamping when it shouldn't). Each maps to a distinct failure mode a reviewer may want to reject independently.

---

### Task 1: Skip the gate when HEAD is verified and the tree is clean (read path)

**Files:**
- Modify: `common/.raven/git-hooks/pre-push` (insert skip block after the delete-only short-circuit)
- Test: `tests/test_git_hooks.py` (add helper `_prepare_verified_repo` + 3 tests)

**Interfaces:**
- Consumes: existing hook structure (the `has_work` delete-only short-circuit at the top).
- Produces: a stamp file convention — a single-line file at `<git-dir>/raven-pre-push-verified` containing a HEAD SHA. The shell variables `stamp` and `head_sha` are defined here and reused by Task 2.

- [ ] **Step 1: Add the shared test helper**

Add this method to `GitHookInstallerTests` in `tests/test_git_hooks.py` (place it after `_hook_env`):

```python
    def _prepare_verified_repo(self, just_exit: int):
        # Make an initial commit so HEAD resolves, and put the fake `git`/`just`
        # in a bin dir OUTSIDE the repo so they do not show up as untracked files
        # that would dirty the tree (the skip path requires a clean tree). Returns
        # (env, head_sha, stamp_path).
        subprocess.run(
            [
                "git",
                "-C",
                str(self.destination),
                "-c",
                "user.email=raven@example.com",
                "-c",
                "user.name=Raven Test",
                "commit",
                "--allow-empty",
                "-m",
                "init",
            ],
            capture_output=True,
            check=True,
        )
        head = subprocess.run(
            ["git", "-C", str(self.destination), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        bin_tmp = tempfile.TemporaryDirectory()
        self.addCleanup(bin_tmp.cleanup)
        bin_dir = Path(bin_tmp.name)
        git_path = subprocess.run(
            ["which", "git"], capture_output=True, text=True, check=True
        ).stdout.strip()
        (bin_dir / "git").symlink_to(git_path)
        fake_just = bin_dir / "just"
        fake_just.write_text(f"#!/bin/sh\nexit {just_exit}\n", encoding="utf-8")
        fake_just.chmod(0o755)
        env = self._hook_env(bin_dir)
        stamp = self.destination / ".git" / "raven-pre-push-verified"
        return env, head, stamp
```

- [ ] **Step 2: Write the three failing read-path tests**

Add these three tests to `GitHookInstallerTests` (after `test_pre_push_hook_skips_heavy_checks_when_nothing_to_push`). `_HOOK` is defined inline in each to keep tasks readable:

```python
    def test_pre_push_skips_when_head_verified_and_tree_clean(self):
        # Stamp records the current HEAD and the tree is clean, so the hook must
        # skip the gate entirely -- even a `just` rigged to fail is never run.
        hook = raven.REPO_ROOT / "common" / ".raven" / "git-hooks" / "pre-push"
        env, head, stamp = self._prepare_verified_repo(just_exit=1)
        stamp.write_text(head + "\n", encoding="utf-8")

        result = subprocess.run(
            ["/bin/sh", str(hook)],
            cwd=self.destination,
            env=env,
            input=self._PUSH_STDIN,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_pre_push_reruns_when_tree_dirty_despite_matching_stamp(self):
        # Stamp matches HEAD, but an uncommitted (untracked) change dirties the
        # tree, so the cached pass is invalid and the failing gate must run.
        hook = raven.REPO_ROOT / "common" / ".raven" / "git-hooks" / "pre-push"
        env, head, stamp = self._prepare_verified_repo(just_exit=1)
        stamp.write_text(head + "\n", encoding="utf-8")
        (self.destination / "scratch.txt").write_text("dirty\n", encoding="utf-8")

        result = subprocess.run(
            ["/bin/sh", str(hook)],
            cwd=self.destination,
            env=env,
            input=self._PUSH_STDIN,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertNotEqual(result.returncode, 0)

    def test_pre_push_reruns_when_head_differs_from_stamp(self):
        # Stamp holds a different SHA (e.g. a new commit since verification), so
        # the failing gate must run rather than skip.
        hook = raven.REPO_ROOT / "common" / ".raven" / "git-hooks" / "pre-push"
        env, _head, stamp = self._prepare_verified_repo(just_exit=1)
        stamp.write_text("0" * 40 + "\n", encoding="utf-8")

        result = subprocess.run(
            ["/bin/sh", str(hook)],
            cwd=self.destination,
            env=env,
            input=self._PUSH_STDIN,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertNotEqual(result.returncode, 0)
```

- [ ] **Step 3: Run the new tests to verify they fail**

Run: `python -m pytest tests/test_git_hooks.py -k "verified or dirty or head_differs" -v`
Expected: `test_pre_push_skips_when_head_verified_and_tree_clean` FAILS (returncode is non-zero because the current hook has no skip block and runs the failing `just`). The other two happen to pass already (the current hook always runs the gate), which is fine — they lock in behavior that must survive Task 2.

- [ ] **Step 4: Add the skip block to the hook**

Edit `common/.raven/git-hooks/pre-push`. Immediately after the line `[ "$has_work" -eq 0 ] && exit 0` (the delete-only short-circuit), insert:

```sh

# The gate runs against the working tree, so a commit is only safely "already
# verified" if the tree is also clean. The stamp records the HEAD SHA that last
# passed `just check` with a clean tree; if HEAD still matches and the tree is
# still clean, re-running is pure waste. A new commit, amend, or any uncommitted
# change alters HEAD or dirties the tree and invalidates the stamp. The stamp
# lives in the (per-worktree) git dir, so it is never committed and is wiped on
# re-clone. A missing or unreadable stamp simply falls through to the gate.
stamp="$(git rev-parse --git-dir)/raven-pre-push-verified"
head_sha=$(git rev-parse HEAD 2>/dev/null)
if [ -n "$head_sha" ] && [ -z "$(git status --porcelain 2>/dev/null)" ] \
    && [ "$head_sha" = "$(cat "$stamp" 2>/dev/null)" ]; then
    exit 0
fi
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/test_git_hooks.py -k "verified or dirty or head_differs" -v`
Expected: all three PASS.

- [ ] **Step 6: Run the full hook suite to verify no regressions**

Run: `python -m pytest tests/test_git_hooks.py -v`
Expected: all tests PASS (existing delete-only, empty-stdin, just-missing, and failing-gate tests are unaffected — none seed a stamp, so the skip branch is inert for them).

- [ ] **Step 7: Commit**

```bash
git add common/.raven/git-hooks/pre-push tests/test_git_hooks.py
git commit -m "feat(hooks): skip pre-push gate when HEAD verified against clean tree"
```

---

### Task 2: Stamp the verified commit after a clean pass (write path)

**Files:**
- Modify: `common/.raven/git-hooks/pre-push` (extend the `just`-present gate block to write the stamp)
- Test: `tests/test_git_hooks.py` (add 2 tests)

**Interfaces:**
- Consumes: `stamp` and `head_sha` shell variables defined by Task 1's skip block.
- Produces: the stamp file is now written by the hook itself (Task 1 only read it). This closes the loop so real pushes populate the cache.

- [ ] **Step 1: Write the two failing write-path tests**

Add these tests to `GitHookInstallerTests` (after the Task 1 tests):

```python
    def test_pre_push_writes_stamp_after_clean_pass(self):
        # A clean tree and a passing gate must record HEAD in the stamp so the
        # next push of the same commit can skip.
        hook = raven.REPO_ROOT / "common" / ".raven" / "git-hooks" / "pre-push"
        env, head, stamp = self._prepare_verified_repo(just_exit=0)
        self.assertFalse(stamp.exists())

        result = subprocess.run(
            ["/bin/sh", str(hook)],
            cwd=self.destination,
            env=env,
            input=self._PUSH_STDIN,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(stamp.exists())
        self.assertEqual(stamp.read_text(encoding="utf-8").strip(), head)

    def test_pre_push_does_not_write_stamp_when_gate_fails(self):
        # A failing gate must not stamp -- a cached "pass" would let unverified
        # code push on the next attempt.
        hook = raven.REPO_ROOT / "common" / ".raven" / "git-hooks" / "pre-push"
        env, _head, stamp = self._prepare_verified_repo(just_exit=1)

        result = subprocess.run(
            ["/bin/sh", str(hook)],
            cwd=self.destination,
            env=env,
            input=self._PUSH_STDIN,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(stamp.exists())
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `python -m pytest tests/test_git_hooks.py -k "writes_stamp or does_not_write_stamp" -v`
Expected: `test_pre_push_writes_stamp_after_clean_pass` FAILS (the hook does not yet write the stamp, so `stamp.exists()` is False). `test_pre_push_does_not_write_stamp_when_gate_fails` passes already (no write exists), and must stay passing.

- [ ] **Step 3: Add the stamp-write to the gate block**

Edit `common/.raven/git-hooks/pre-push`. Replace the existing `just`-present block:

```sh
if command -v just >/dev/null 2>&1; then
    just check || exit 1
fi
```

with:

```sh
if command -v just >/dev/null 2>&1; then
    just check || exit 1
    # Record the verified commit only when the tree is still clean, so a cached
    # pass can never vouch for uncommitted work. If the gate dirtied the tree
    # (e.g. build artifacts), skip stamping this run rather than caching a lie.
    # The stamp is an optimization, so a failed write is swallowed.
    if [ -n "$head_sha" ] && [ -z "$(git status --porcelain 2>/dev/null)" ]; then
        printf '%s\n' "$head_sha" > "$stamp" 2>/dev/null || true
    fi
fi
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_git_hooks.py -k "writes_stamp or does_not_write_stamp" -v`
Expected: both PASS.

- [ ] **Step 5: Run the full hook suite to verify no regressions**

Run: `python -m pytest tests/test_git_hooks.py -v`
Expected: all tests PASS. In particular `test_pre_push_hook_is_optional_when_just_missing` still passes (the write is inside the `just`-present branch, so a missing `just` writes nothing) and `test_pre_push_hook_blocks_when_just_check_fails` still passes (a failing `just check` exits before the write).

- [ ] **Step 6: Commit**

```bash
git add common/.raven/git-hooks/pre-push tests/test_git_hooks.py
git commit -m "feat(hooks): stamp verified commit after clean pre-push gate pass"
```

---

### Task 3: Propagate the hook change to the installed tree and run the full self-check

**Files:**
- Modify (mechanical, via `self-check.py` upgrade): `.raven/git-hooks/pre-push`, `.raven/manifest.json`, and any other installed-tree files the upgrade touches.

**Interfaces:**
- Consumes: the edited `common/.raven/git-hooks/pre-push` from Tasks 1–2.
- Produces: the installed tree (`.raven/git-hooks/pre-push`) matches `common/`, and the full self-check (upgrade dry-run → upgrade → ruff format check → ruff lint → pytest) passes.

- [ ] **Step 1: Run the self-check**

Run: `python scripts/self-check.py`
Expected: prints `RAVEN self-check passed`. This applies the upgrade, which copies the updated hook from `common/.raven/git-hooks/pre-push` into the installed `.raven/git-hooks/pre-push` and refreshes `.raven/manifest.json` hashes, then runs ruff and the full pytest suite.

If the self-check fails, stop and inspect only the failing output (do not proceed to commit).

- [ ] **Step 2: Confirm the installed hook now matches the source**

Run: `git diff --stat; diff .raven/git-hooks/pre-push common/.raven/git-hooks/pre-push && echo IDENTICAL`
Expected: `IDENTICAL`, and `git diff --stat` shows only installed-tree files (e.g. `.raven/git-hooks/pre-push`, `.raven/manifest.json`) as modified — no unexpected files.

- [ ] **Step 3: Commit the installed-tree sync**

```bash
git add -A
git commit -m "chore(self-install): apply raven upgrade to installed tree"
```

---

## Self-Review

**1. Spec coverage:**
- Cache key (HEAD SHA + clean-tree guard) → Task 1 skip block + Task 2 write block. ✓
- Stamp location (`<git-dir>/raven-pre-push-verified`, per-worktree, untracked) → Task 1 Step 4. ✓
- Write only on clean pass; never on fail/dirty → Task 2 Step 3 + tests `writes_stamp` / `does_not_write_stamp` / `dirty`. ✓
- Skip only when HEAD matches and tree clean → Task 1 tests (skip / dirty / head_differs). ✓
- Failure modes fall through to gate (missing/corrupt stamp, `just` absent, unborn branch) → covered by existing suite (Task 1 Step 6, Task 2 Step 5) plus the `|| true` swallow. ✓
- Untracked-as-dirty → `test_pre_push_reruns_when_tree_dirty_despite_matching_stamp` uses an untracked file. ✓
- Installed-tree propagation via self-check → Task 3. ✓
- `install-hooks` fallback out of scope → not touched. ✓

**2. Placeholder scan:** No TBD/TODO; every code and command step shows exact content. ✓

**3. Type/name consistency:** `stamp` and `head_sha` shell vars defined in Task 1, reused in Task 2. Helper `_prepare_verified_repo(just_exit)` returns `(env, head, stamp)` and is called consistently. Stamp path `.git/raven-pre-push-verified` matches `$(git rev-parse --git-dir)/raven-pre-push-verified` (git-dir is `.git` in the non-worktree temp repos). Test names referenced in `-k` filters match the `def` names. ✓
