# Orphaned-Managed-File Removal in `raven upgrade` (+ `doctor`)

Tracks GitHub issue #97 (follow-up to #91, audit initiative #95).

## Problem

`raven upgrade` never removes a file that is in `.raven/manifest.json` but no
longer shipped by the current template. The upgrade path iterates **only current
template entries** (`classify`/`apply_plan` in `apply.py`), `update_manifest`
(`manifest.py`) only `.update()`s records and never deletes, and `doctor` has no
extra-file detection. Net effect: delete a shipped template file and every
existing install keeps a stale copy forever after `raven upgrade` — no removal,
no report. This blocks #91 Part A (deleting `common/.claude/rules/raven-tests.md`),
which is only safe once upgrade cleans up dropped files.

## Goal

Detect files present in the manifest but no longer shipped, and either remove
them (when provably unmodified) or report-and-keep them (when the user touched
them) — **never silently orphan, never delete something the user modified.**

## Trust model (why zero-risk is achievable)

Every managed record carries two hashes: `installedSha256` (what Raven last wrote)
and `sourceSha256` (the template content at that baseline). `reconcile_state`
(`apply.py:31`) already uses these for the 3-way merge on surviving files. Orphan
handling reuses the **same predicate**: if a file wouldn't be safe to *overwrite*
on upgrade, it isn't safe to *remove* on drop. No new judgment about "did the user
modify this" is introduced.

## Design

### Orphan classification

Compute the orphan set as `manifest.files − currently-shipped template relatives`
and bucket each orphan:

| Bucket | Condition | Action |
|---|---|---|
| `will_remove` | on-disk hash == `installedSha256` **and** `installedSha256 == sourceSha256` **and** `kind` matches | delete installed file, prune record, report |
| `orphan_modified` | on-disk differs, **or** baseline is a customization (`installed != source`) | keep file, keep record, report |
| `already_gone` | file absent on disk | prune stale record silently |

### Three correctness guards (where accidental-deletion risk lives)

1. **"Orphan" means the template dropped the file — not that a destination/config
   policy excluded it.** `entries_for_destination` pops `STARTER_TOOL_CONFIG_PATHS`
   that already exist and drops config-excluded paths; those are *non-shipping-for-
   policy*, not *removed-from-template*. The orphan candidate set MUST be built
   against what the template **still ships at all** (`iter_template_entries`), so a
   user's starter config or an opted-out language file is never a deletion
   candidate. This is the single most important call.

2. **Skills remap.** Manifest keys are source-relative (`.agents/skills/...`) but
   the installed file may live at a remapped path (`.claude/skills/...`). Orphan
   *matching* is source-relative; the file that is hashed and deleted is the
   *installed* path. These must not be conflated.

3. **Strict hashing, no tolerances.** Unlike upgrade, do NOT apply the
   trailing-newline tolerance (`_differs_only_by_final_newline`) — a newline-only
   diff routes to `orphan_modified`, not `will_remove`. Only remove a now-empty
   parent directory if it is actually empty; never a directory with residue.
   Reuse existing destination-root / symlink-escape path safety.

### Surfacing

- **Dry-run plan:** new sections `Will remove orphaned Raven files:` and
  `Orphaned but locally modified (left in place):`.
- **Apply summary:** counts of removed vs. reported-and-kept.
- **`doctor`:** a shared orphan helper feeds a read-only `Finding` covering both
  clean and modified orphans, kept disjoint from existing drift findings.
- **Manifest:** extend the manifest update to prune removed and already-gone
  records (currently it only `.update()`s).

### Component boundaries

- Orphan computation is a pure function: `(manifest, shipped relatives, destination)
  → list of classified orphans`. It has no I/O beyond hashing the destination and
  can be unit-tested in isolation. Both `upgrade` (acts) and `doctor` (reports)
  call it.
- Removal execution stays in the apply path next to the existing copy/upgrade
  steps, gated on the `will_remove` bucket.

## Testing

- **Orphan classification unit tests:** clean → `will_remove`; modified content →
  `orphan_modified`; customization (`installed != source`) → `orphan_modified`;
  missing on disk → `already_gone`; kind mismatch → kept.
- **Upgrade-path regression:** install a prior shape into a temp dir, drop a file
  from the template, run upgrade, and assert: clean file removed + record pruned;
  a modified orphan kept + reported; a `STARTER_TOOL_CONFIG_PATHS` / config-excluded
  file **never** touched (guard #1).
- **doctor:** asserts orphans surface as findings without an upgrade.

## Build order

1. Orphan classification + manifest pruning + tests (scope items 1–2).
2. Wire into `doctor` (shared helper).
3. Execute #91 Part A on top of the mechanism (scope item 3): fold `raven-tests.md`
   bullet (b) into each language rules `## Testing` section where missing; delete
   `common/.claude/rules/raven-tests.md` and the per-tree symlinks; remove it from
   self-check `THRESHOLDS`/`PROFILES` and adjust per-language aggregate budgets
   **downward** by the removed word count; update `tests/test_self_check.py`.
   Confirm this repo's own install upgrades cleanly (removed file cleaned up, not
   orphaned).

## Acceptance criteria (from #97)

- `raven upgrade` removes or explicitly reports a managed file dropped from the
  template; never silently orphans it.
- Upgrade-path regression test covers the removal/report behavior.
- `raven-tests.md` gone from `common/` and all trees; unique bullet preserved in
  each language rules `## Testing`.
- self-check `THRESHOLDS`/`PROFILES` adjusted downward only; budget checks pass.
- `python -m pytest` and `python scripts/self-check.py` pass; this repo's own
  install upgrades cleanly.
