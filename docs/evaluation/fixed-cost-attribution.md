# Fixed-cost attribution -- claude

Run 2026-11-24 at commit `50e1f04` with Claude Code 2.1.319 and
`claude-opus-5-5` (from `system/init`), on the `python` template.

This file is the source of record for the Claude `fixed-cost` ceiling in
`FIXED_COST_OVERHEAD_CEILINGS` (`evals/scenarios.py`). The full
`results-claude.md` was not republished with it.

## Method

Each config in `evals/ablations/` switches one Raven component off. Every
config ran 5 `fixed-cost` trials per arm:

```sh
python scripts/eval.py --agent claude --scenario fixed-cost --trials 5 \
  --raven-config "evals/ablations/$c.toml" --transcripts "$TMPDIR/raven-ablation/$c"
```

- Δ is the raven arm's total tokens minus the control arm's, compared within
  the same trial.
- A component's cost is mean Δ(`baseline`) minus mean Δ(config).
- The residual is mean Δ(`baseline`) minus the summed component costs.
- Every trial made 0 tool calls. In every `system/init`, `mcp_servers` listed
  only `semgrep` with source `project`, and none listed one in the `no-mcp` run.
- Both arms ran with `ENABLE_CLAUDEAI_MCP_SERVERS=false`.
- The `/context` column comes from `claude -p "/context all" --setting-sources
  project` on a freshly built fixture for each config. It makes no model call
  and is a cross-check, not the measurement.

## Results

| Config | Mean Δ | Min Δ | Max Δ | Component cost | `/context` estimate |
|---|---|---|---|---|---|
| `baseline` | 5,508 | 5,495 | 5,544 | -- | 17.1k vs 13.2k control (+3.9k) |
| `no-root-instructions` (`AGENTS.md`, `CLAUDE.md`) | 2,281 | 2,276 | 2,288 | 3,227 | `AGENTS.md` 3.1k, `CLAUDE.md` 16 |
| `no-skills` | 4,552 | 4,524 | 4,573 | 955 | skills 3.2k vs 2.3k (+0.9k) |
| `no-claude-rules` | 5,013 | 4,980 | 5,024 | 495 | 345 (`raven-prose.md` 197, `raven-comments.md` 148) |
| `no-claude-subagents` | 5,061 | 5,052 | 5,066 | 446 | 275 (6 agents) |
| `no-mcp` (`semgrep`) | 5,353 | 5,346 | 5,360 | 155 | 2.8k of deferred schemas, not loaded |
| `no-claude-settings` (hooks, roster) | 5,556 | 5,554 | 5,560 | < 100 (measured -48) | 0 |
| residual | | | | 277 | |

The baseline arms' means were 23,556 (raven) and 18,049 (control). The
per-trial spread within a config was at most 49 tokens.

## Reduction candidates

These follow the rule set on 2026-11-24: a component is a candidate at 500
tokens or more of 5-trial mean cost. Nothing is cut here; each candidate needs
owner confirmation.

- **Root instructions (`AGENTS.md`), 3,227.** This is the largest item. A cut
  has to go through the `THRESHOLDS` policy in `validate_context_budget` as its
  own issue.
- **Skills, 955.** `scripts/self-check.py` already caps the descriptions, so
  this is recorded, not cut.

Below the threshold, kept, with the number recorded: Claude rules at 495 (just
under), subagents at 446, `semgrep` MCP at 155, and settings and hooks at
under 100.

## Ceiling

The Claude ceiling is mean Δ(`baseline`) × 1.15 rounded to the nearest 100:
5,508 × 1.15 = 6,334, so 6,300. That lowers it from 10,100. The 2026-10-16
figure of 8,815 included an unknown share from the operator's claude.ai
connectors, which the harness now switches off.

## Codex check (unpublished)

Codex CLI 0.172.0, 5 trials: mean Δ is 3,671 (min 3,669, max 3,674), with
20,366 for raven and 16,695 for control. All five trials pass the 3,900
ceiling. The ceiling rule, though, gives 3,671 × 1.15 = 4,222, so 4,200, which
is above 3,900. That is reported to the owner, and the ceiling is not raised.
