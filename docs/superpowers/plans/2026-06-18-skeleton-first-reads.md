# Plan: Skeleton-first reads (rungs 1-3)

Status: Rung 1 core complete (generator + tests + cross-template install).
Rungs 2-3 pending. Exposure/guidance for the rung-1 helper still open.

Source research: `docs/research/hook-read-interception.md`.

## Progress (2026-06-18)

Rung 1 core landed via TDD (`tests/test_skeleton.py`, 21 tests; all 181 pass):

- `common/.claude/scripts/raven-skeleton.py` (+ byte-identical Codex copy):
  ast-grep backend with verified node-kind table for python, typescript, tsx,
  javascript, go, rust, swift, lua. Emits `start-end<TAB>header` rows; exact
  exclusive-range -> 1-based-inclusive conversion; sort/dedup; output cap; clean
  CLI with graceful "no skeleton" messaging.
- Node kinds were verified empirically against ast-grep 0.43.0; Python and
  TypeScript have end-to-end golden tests.
- **Elixir deferred from the ast-grep backend** (its def/defp are `call` nodes
  needing a structural rule). Elixir is still detected, so it falls through to
  the degraded ladder. Follow-up below.

Installer bug found and fixed (the reason for the self-test workflow): language
templates link Claude scripts **per-file** (`<lang>/.claude/scripts/*.py` ->
`common/...`), unlike the Codex **whole-directory** symlink. A new Claude script
is silently dropped from installs until linked into every template. Fixed by
adding the per-file symlink to all 8 templates, guarded by a new parity test
(`tests/test_claude_script_symlinks.py`).

Still open in rung 1: ctags/rg fallback backends (deferred — safe degradation
already works via the "no skeleton" message), and exposure/guidance so agents
discover the helper.

## Goal

Reduce tokens spent on full-file reads by letting agents see a structural
*skeleton* (symbols with exact start/end line ranges) first, then read only the
ranges they need — Maki's `index` idea, expressed within Raven's constraints.

Deliver three rungs:

- **Rung 1 (portable):** a callable ast-grep-based skeleton generator with a
  documented backend ladder, usable on both Claude and Codex.
- **Rung 2 (Claude-only):** a `PreToolUse` gate on `Read` that denies unbounded
  reads of large files and points at the rung-1 helper.
- **Rung 3 (Claude-only):** a `PostToolUse` transform on `Read` that substitutes
  the skeleton via `updatedToolOutput`. Gated by gap #2 (Read output schema).

## Scope

- Skeleton generator: backend ladder ast-grep -> Universal Ctags -> running LSP
  (only if explicitly configured) -> `rg` degraded mode, with a runtime
  empty-result sanity check that degrades instead of emitting a bad skeleton.
- Per-language node-kind table + structural rules, scoped to Raven's shipped
  stacks only.
- Golden-file tests per language, wired into the suite `self-check.py` runs.
- Claude `PreToolUse` and `PostToolUse` hooks on `Read`, shipped via `common/`
  templates and validated through the self-test workflow.
- Config to enable/disable and set the size threshold.

## Non-Goals

- **The complex Codex path:** no Bash-command rewriting, no MCP-mediated read
  interception. Codex stays at rung 0 (advisory, already shipped) plus rung 1
  (callable helper). Rungs 2-3 are Claude-only.
- Custom (non-built-in) ast-grep language grammars.
- Covering every ast-grep language — only stacks Raven already supports.
- Replacing the shipped rung-0 advisory guidance; it remains the portable floor.

## Assumptions

- ast-grep is already tracked by `raven-tool-check.py`; no new dependency.
- The rung-0 skeleton-first bullet already shipped in `common/AGENTS.md`.
- `common/` is the template source; `.claude`/`.codex` copies regenerate via
  `upgrade`; `python scripts/self-check.py` is the gate after template edits.
- Direct `ast-grep` binary only (~130 ms); never `npx`/`npm exec` (~2.5 s) and
  never invoke as `sg` (Linux `setgroups` collision).
- AGENTS.md additions must fit the always-loaded context budget (1110 words).

## Work Items

### Rung 1 — callable skeleton generator (unblocked; build first)

1. Decide helper location/form (shared script vs `raven` subcommand vs skill)
   so a Claude hook and an on-demand agent invocation can both reach it. Inspect
   how existing hooks/scripts are shared between `common/.claude` and
   `common/.codex` before choosing.
2. Implement the generator: input = file path (language by extension); output =
   compact list/hierarchy of `(kind, symbol, start_line, end_line)`. Apply the
   exclusive-range -> 1-based-inclusive conversion from the research doc.
3. Backend ladder with graceful fallback + runtime empty-result sanity check.
4. Binary resolution: resolve/verify `ast-grep` via `--version`; never `sg`.
5. Node-kind table + structural rules (arrow functions etc.) for shipped stacks;
   cap output by symbol count / byte size.
6. Golden-file tests per language (fixture + expected output); wire into suite.
7. Expose as a callable tool and reference it from the rung-0 retrieval guidance
   (within budget). Available to both harnesses.

### Rung 2 — Claude PreToolUse gate (unblocked)

8. Add `PreToolUse` hook matching `Read`: stat size/line count; if over threshold
   AND a supported language AND the read is unbounded (no `offset`/`limit`), deny
   with an actionable reason (run the skeleton helper, then read ranges).
9. Do NOT block ranged reads (`offset`/`limit` present) or small files — only
   unbounded large reads. Tune to avoid deny-loops.
10. Ship via `common/.claude` settings template; confirm Codex is unaffected.
11. Unit-test the guard as a pure function over the hook payload.

### Rung 3 — Claude PostToolUse transform (BLOCKED on gap #2)

12. **Checkpoint:** resolve gap #2 — pin the exact `Read` output schema that
    `updatedToolOutput` must match (research + empirical test). If it cannot be
    matched reliably, STOP at rung 2 and leave rung 3 unbuilt.
13. Resolve the gate-vs-transform interaction (rung 2 denies the reads rung 3
    would transform). Decide a default and make the other opt-in; do not run both
    on the same read.
14. Implement `PostToolUse` on `Read`: generate skeleton, return schema-valid
    `updatedToolOutput` for large discovery reads; pass through small/ranged ones.
15. Unit tests + self-check.

### Cross-cutting

16. Config (likely `.raven/config.toml`) for enable/disable + threshold.
17. Doc sync (raven-doc-sync): AGENTS.md, README, research doc cross-links.
18. Follow-up note: `raven-tool-check.py` probes `sg` as an ast-grep alias —
    revisit given the `setgroups` collision (separate small fix).

## Verification

- `python scripts/self-check.py` after each rung (validates shape, dry-run +
  apply upgrade, budget, ruff, unit tests).
- Golden tests for the generator; pure-function tests for guard/transform.
- Manual: confirm the hook fires in Claude; confirm Codex behavior unchanged.
- Token-savings benchmark (gap #4) folded into rung-1 validation — convert the
  imported Maki numbers into a measured local figure.

## Follow-Ups

- Elixir ast-grep support via a structural rule (def/defp/defmodule `call` nodes).
- ctags + `rg` degraded backends to round out the fallback ladder.
- Exposure: skill vs AGENTS.md pointer for the rung-1 helper (harness-path aware).
- Consider making `<lang>/.claude/scripts` a whole-directory symlink (like Codex)
  to remove per-file symlink maintenance and the class of bug fixed above.
- Gap #3 (does Codex route reads through MCP) — only relevant if we ever revisit
  the dropped Codex interception path.
- The `sg` probe fix in `raven-tool-check.py`.

## Open Questions

- Gap #2 (Read output schema) — gates rung 3.
- Gate (rung 2) vs transform (rung 3) as the default Claude behavior.
- Helper form: shared script, `raven` subcommand, or skill.
- Threshold: lines vs bytes, and the default value (rung-0 text says ~500 lines).
