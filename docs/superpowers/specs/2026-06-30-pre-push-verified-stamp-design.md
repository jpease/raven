# Pre-push verified-commit stamp: skip redundant gate runs

**Date:** 2026-06-30
**Status:** Approved (design)
**Scope:** `common/.raven/git-hooks/pre-push` + tests

## Problem

Raven's shipped pre-push hook (`common/.raven/git-hooks/pre-push`, symlinked into
`.git/hooks/pre-push` by `raven.install_git_hooks()`) runs the full local gate
`just check` (lint + format + type-check + tests) on every push that carries any
non-deletion ref. The hook is stateless: it has no memory that a given commit
already passed. So a common sequence —

1. `git push` → hook runs `just check` → passes, but push rejected (remote moved)
2. `git pull --rebase`
3. `git push` (retry) → hook runs `just check` **again from scratch**

re-runs the entire gate against a tree that hasn't changed since the last green
run. Same commit, same tree, same result — pure wasted wall-clock. The redundancy
is structural: Git re-invokes the hook per push attempt and the hook can't tell
the prior run already validated this exact state.

## Goal

Skip `just check` in the pre-push hook when *this exact commit was already
verified against a clean working tree*, while never letting a cached "pass" vouch
for state it did not actually verify.

Non-goals: caching partial/incremental results, caching dirty-tree passes,
per-file test selection, or changing the `just check` recipe itself.

## Prior art considered

- **Hook managers (lefthook, husky, pre-commit.com):** none ship a "commit
  already verified, skip" cache. lefthook's `skip: - run:` is a hand-rolled
  shell condition — it hosts our logic but supplies none of it. pre-commit.com
  runs hooks on *changed files*, a different, Python-centric model that would
  require restructuring gates around it.
- **Build/task caches (Turborepo, Nx, Bazel, Gradle build cache, pytest-testmon):**
  the rigorous, input-hashing version of this idea. Rejected: each is
  ecosystem-specific and heavyweight; adopting one would violate Raven's
  "templates ship self-contained, portable POSIX, no heavy deps" constraint and
  would have to run across the Python/Go/Rust/Swift/Lua/Elixir/dotfiles trees
  that all share this one hook.
- **Marker/stamp file idiom (Make targets, `.stamp` files):** the classic
  idempotency guard — "input fingerprint unchanged → skip the recipe." This is
  the right-sized, well-known pattern for a portable shell hook. We adopt it at
  the coarsest safe granularity.

## Design

### Cache key: HEAD SHA + clean-tree guard

The gate runs against the **working tree**, not the committed state, so a HEAD
SHA alone is not a safe key — uncommitted edits since the stamp would make a
cached pass a lie. The stamp is therefore valid only when paired with a clean
tree:

- **Write** the stamp (current HEAD SHA) only after `just check` passes **and**
  the working tree is clean. A pass against a dirty tree is never cached, because
  it can't be safely replayed for a later, possibly-different dirty tree.
- **Skip** the gate only when HEAD still matches the stamp **and** the tree is
  still clean.

Every way the verified state can change invalidates the stamp for free:
a new commit / amend / rebase changes HEAD; any staged, unstaged, or untracked
change makes `git status --porcelain` non-empty.

"Clean" here means `git status --porcelain` is empty, which **counts untracked
files as dirty**. This is deliberate and conservative: an untracked file can
change gate results (e.g. a linter that globs all source files), so a pristine
tree is the only state we cache. Consequence: keeping untracked scratch files in
the worktree disables the optimization. Accepted as a safe default; revisitable
if it proves annoying in practice.

### Stamp location

`"$(git rev-parse --git-dir)/raven-pre-push-verified"` — a single-line file
holding the verified SHA.

- Under the git dir, so it is **never tracked** and never committed (a tracked
  stamp would travel between machines/branches and vouch for state it never
  saw).
- `--git-dir` resolves to the **per-worktree** git dir for linked worktrees, so
  each worktree keeps its own stamp (each has its own HEAD and working tree).
  This matches the existing suite's care about linked worktrees.
- Wiped on re-clone → re-verify. Correct.

### Hook control flow

```sh
#!/usr/bin/env sh

repo_root=$(git rev-parse --show-toplevel 2>/dev/null) || exit 0
cd "$repo_root" || exit 0

# --- existing delete-only / empty-push short-circuit (unchanged) ---
has_work=0
while read -r _local_ref local_sha _remote_ref _remote_sha; do
    case "$local_sha" in
        "") ;;
        *[!0]*) has_work=1 ;;
    esac
done
[ "$has_work" -eq 0 ] && exit 0

# --- new: skip if this exact commit already passed against a clean tree ---
stamp="$(git rev-parse --git-dir)/raven-pre-push-verified"
head_sha=$(git rev-parse HEAD 2>/dev/null)
if [ -n "$head_sha" ] && [ -z "$(git status --porcelain 2>/dev/null)" ] \
    && [ "$head_sha" = "$(cat "$stamp" 2>/dev/null)" ]; then
    exit 0
fi

# --- existing gate (unchanged), plus stamp-on-pass ---
if command -v just >/dev/null 2>&1; then
    just check || exit 1
    # Record the verified commit only if the tree is still clean, so a cached
    # pass can never vouch for uncommitted work.
    if [ -n "$head_sha" ] && [ -z "$(git status --porcelain 2>/dev/null)" ]; then
        printf '%s\n' "$head_sha" > "$stamp" 2>/dev/null || true
    fi
fi
```

Notes:

- The stamp is written **only inside the `just`-present branch, after a pass** —
  if `just` is absent, no gate ran, so nothing is stamped and later runs still
  gate.
- Stamp-write failures are swallowed (`|| true`): the stamp is an optimization,
  never a correctness dependency. A missing/unreadable/unwritable stamp just
  means the gate runs, which is the safe direction.
- Unborn branch (no commits): `head_sha` is empty → never skips, never stamps.
  Safe.
- The clean check is re-run *after* the gate in case the gate writes artifacts;
  a tree the gate dirtied simply won't be stamped this run.

## Edge cases / failure modes

| Situation | Behavior | Safe? |
|---|---|---|
| Retry push, same clean commit | Skip (stamp hit) | ✓ intended win |
| New commit / amend / rebase | HEAD ≠ stamp → run | ✓ |
| Uncommitted staged/unstaged edit | tree dirty → run, no stamp write | ✓ |
| Untracked scratch file present | tree dirty → run, no stamp write | ✓ (conservative) |
| `just` not installed | exit 0, no stamp written | ✓ (unchanged) |
| Gate fails | exit 1, no stamp written | ✓ |
| Stamp file corrupt/unreadable | `cat` fails → no match → run | ✓ |
| Linked worktree | per-worktree stamp under its own git dir | ✓ |
| Delete-only / empty push | short-circuits before stamp logic | ✓ unchanged |

## Testing

Add to `tests/test_git_hooks.py`, following the existing fake-`git` /
fake-`just` / `_hook_env` pattern. New tests need a real commit in the temp repo
(so `HEAD` resolves) — reuse the inline-identity `git commit --allow-empty`
pattern already used by `test_linked_worktree_installs_into_shared_hooks_dir`.

1. **Skips when HEAD verified and tree clean:** commit, seed stamp with HEAD SHA,
   clean tree, rig `just` to `exit 1` → hook exits **0** (gate never ran).
2. **Re-runs when tree dirty despite matching stamp:** stamp = HEAD SHA, then
   create an untracked/modified file, rig `just` to `exit 1` → hook exits
   **non-zero** (gate ran).
3. **Re-runs when HEAD differs from stamp:** stamp holds a different SHA, clean
   tree, rig `just` to `exit 1` → hook exits **non-zero**.
4. **Writes stamp after a clean pass:** rig `just` to `exit 0`, clean tree, run
   hook → `.git/raven-pre-push-verified` exists and equals `git rev-parse HEAD`.
5. **No stamp written when gate fails:** rig `just` to `exit 1`, no prior stamp →
   hook exits non-zero and stamp file absent.

Existing pre-push tests (delete-only skip, empty stdin, just-missing,
failing-gate) must continue to pass unchanged — none seed a stamp, so the new
skip branch is inert for them (stamp absent → no match → falls through).

## Rollout

- Single change to one shared file (`common/.raven/git-hooks/pre-push`), so it
  reaches all language trees at once. Reconcile the installed copy via the normal
  Raven upgrade path (do not hand-edit `.raven/git-hooks/pre-push`).
- Out of scope: the `install-hooks` justfile fallback recipe (writes a one-liner
  `just check` hook). Rewiring it to the rich hook is a separate change.
- Validate with `python scripts/self-check.py` per the repo's self-test workflow,
  since this modifies shipped hook behavior.
