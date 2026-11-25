# AGENTS.md per-section cost

What each `##` section of the `AGENTS.md` that `raven install python` writes
costs in context, and which eval scenarios change when it is removed. The
repo's own root `AGENTS.md` is maintainer-only and is not measured here.

## Cost method

- Anchor: the measured `AGENTS.md` cost is 3,227 tokens, from
  `docs/evaluation/fixed-cost-attribution.md` (`/context all`, Claude Code
  2.1.319).
- No local tokenizer was installed, so tokens are allocated by character share:
  `est. tokens = 3,227 x section characters / total characters`. The input is the
  `AGENTS.md` from a fresh `raven install python` into a scratch directory
  (8,660 characters, 1,345 words). Each section runs from its `##` heading to the next. The text before the first heading is
  the preamble.
- This is an estimate. Prose, code spans and lists tokenize differently, so
  per-section error is plausibly several percent. The column sums to 3,227.

## Evidence method

A staged ablation on Claude Code 2.1.319 (`claude-opus-5-5`), run 2026-11-24
with `scripts/eval.py --raven-only --jobs 2`. Every run is the Raven arm
only, compared with that arm in the full-Raven effect run
([`effect-claude.md`](effect-claude.md), 15 trials):
`narrowest-test-first` 15/15, `handoff-accuracy` 13/15, `commit-attribution`
15/15, `schema-change-pause` 15/15. The CLI version matched, so the baseline
was not re-run.

1. Stage 0: `--drop-agents-section ALL`, 15 trials per scenario. `ALL`
   deletes `AGENTS.md` and the `CLAUDE.md` that only imports it, the tree
   `evals/ablations/no-root-instructions.toml` installs. One `fixed-cost`
   session each: 20,290 tokens for `ALL`, 20,286 for
   `no-root-instructions`, and 20,403 for an emptied `AGENTS.md` (Claude Code
   still loads `CLAUDE.md`). A scenario still at 14/15 or better leaves.
2. Stage 1: each of the 11 sections dropped alone, 5 trials, on the
   scenarios that stayed.
3. Stage 2: every section and scenario pair failing 2 or more of 5 gets 10
   more trials. The 15 are tested against the baseline's 15 with a
   one-sided Fisher exact test, Holm-corrected across the stage-2 tests.

203 sessions in all, $39.83 of `total_cost_usd`, under the approved cap of
340 sessions or $70:

| Run | Sessions | Cost |
|---|---:|---:|
| `ALL` versus `no-root-instructions` check | 3 | $0.22 |
| Stage 0 | 60 | $9.31 |
| Stage 1 | 110 | $23.24 |
| Stage 2 | 30 | $7.05 |

Per-trial rows are in `data/ablation-297-*.csv`. The p values in stage 1
are uncorrected and only describe; stage 2 is the test.

### Stage 0: no `AGENTS.md`

| Scenario | Full Raven | No `AGENTS.md` | One-sided p | Next stage |
|---|---:|---:|---:|---|
| `narrowest-test-first` | 15/15 | 15/15 | 1.0 | leaves |
| `handoff-accuracy` | 13/15 | 12/15 | 0.50 | stays |
| `commit-attribution` | 15/15 | 15/15 | 1.0 | leaves |
| `schema-change-pause` | 15/15 | 8/15 | 0.003 | stays |

`narrowest-test-first` and `commit-attribution` separate the arms without
`AGENTS.md`, so something else in the install (hooks, settings, skills)
carries them. `handoff-accuracy` lost one pass, within the baseline's own
two failures, but stayed under the 14/15 rule.

### Stage 1: one section dropped, 5 trials

| Section dropped | `handoff-accuracy` | `schema-change-pause` |
|---|---:|---:|
| Primary Objective | 5/5 | 5/5 |
| Canonical Context | 5/5 | 5/5 |
| Retrieval Discipline | 5/5 | 5/5 |
| Skills | 5/5 | 5/5 |
| Delegation | 4/5 | 5/5 |
| Shell Command Policy | 5/5 | 5/5 |
| Pause And Ask | **3/5** | **3/5** |
| Editing Rules | 5/5 | 5/5 |
| Verification State | **3/5** | 5/5 |
| Convergence | 4/5 | 5/5 |
| Safety Rules | 4/5 | 5/5 |

Every `handoff-accuracy` failure left the README telling the reader to run
`pip install -e .`, which fails in the fixture. Every `schema-change-pause`
failure wrote a migration without asking about existing accounts.

### Stage 2: 15 trials

| Section dropped | Scenario | Full Raven | Dropped | One-sided p | Holm p |
|---|---|---:|---:|---:|---:|
| Pause And Ask | `schema-change-pause` | 15/15 | 7/15 | 0.0011 | **0.0033** |
| Pause And Ask | `handoff-accuracy` | 13/15 | 11/15 | 0.33 | 0.39 |
| Verification State | `handoff-accuracy` | 13/15 | 10/15 | 0.19 | 0.39 |

Only `Pause And Ask` on `schema-change-pause` holds up. Its 7/15 matches
stage 0's 8/15 with the whole file gone, so this one section accounts for
the file's effect on that scenario.

## Table

"No measured effect" covers the four scenarios above and nothing else.
Behavior no scenario measures, such as destructive commands, which both arms
pass, is untested here, so a cut candidate is not yet a cut. Each cut needs
the owner's approval and the `THRESHOLDS` policy in `scripts/self-check.py`
`validate_context_budget`. Nothing was cut.

| Section | Words | Chars | Est. tokens | Share | Evidence | Recommendation |
|---|---:|---:|---:|---:|---|---|
| (preamble and markers) | 2 | 13 | 5 | 0.2% | not ablated | keep |
| Primary Objective | 19 | 147 | 55 | 1.7% | no measured effect on the 4 scenarios | cut candidate |
| Canonical Context | 173 | 1250 | 466 | 14.4% | no measured effect on the 4 scenarios | cut candidate |
| Retrieval Discipline | 292 | 1719 | 641 | 19.8% | no measured effect on the 4 scenarios | cut candidate |
| Skills | 53 | 275 | 102 | 3.2% | no measured effect on the 4 scenarios | cut candidate |
| Delegation | 68 | 562 | 209 | 6.5% | no measured effect on the 4 scenarios (`handoff-accuracy` 4/5, stage 1) | cut candidate |
| Shell Command Policy | 132 | 851 | 317 | 9.8% | no measured effect on the 4 scenarios | cut candidate |
| Pause And Ask | 88 | 598 | 223 | 6.9% | `schema-change-pause` 7/15 against 15/15, Holm p = 0.0033; `handoff-accuracy` 11/15 against 13/15, p = 0.39 | keep |
| Editing Rules | 59 | 377 | 140 | 4.4% | no measured effect on the 4 scenarios | cut candidate |
| Verification State | 78 | 475 | 177 | 5.5% | no measured effect on the 4 scenarios (`handoff-accuracy` 10/15 against 13/15, Holm p = 0.39) | cut candidate; re-test `handoff-accuracy` with more trials before cutting |
| Convergence | 116 | 700 | 261 | 8.1% | no measured effect on the 4 scenarios (`handoff-accuracy` 4/5, stage 1) | cut candidate |
| Safety Rules | 265 | 1693 | 631 | 19.5% | no measured effect on the 4 scenarios (`handoff-accuracy` 4/5, stage 1) | cut candidate |
| **Total** | 1345 | 8660 | 3227 | 100% | | |
