# Per-trial data for the 2026-11-24 runs

One CSV per archived run, with the columns `scripts/eval.py` now writes beside
every report: `run_stamp, agent, cli_version, model, scenario, arm, trial,
passed, verdict_reason, total_tokens, tool_calls, raven_config, jobs`. The
published reports hold only pass counts and means; these files hold the trial
rows behind them. The raw transcripts are held privately by the maintainer and
are not in the repository.

## How the rows were rebuilt

`cli_version`, `model`, `total_tokens`, and `tool_calls` come from each trial's
transcript, read by the same code the harness uses (`system/init`, the final
`result` event, and the tool-use count). Home and temp-directory paths are
scrubbed. `run_stamp` is the date the run is published under (2026-11-25 UTC
for the effect and pilot runs), or the archive folder's date (2026-11-24) for
the others. An empty cell means the value was not recorded.

`passed` is filled only where it can be recovered without guessing. Where it
cannot, it is empty and `verdict_reason` reads `not recorded`.

| File | Rows | `passed` and `verdict_reason` |
|---|---|---|
| `effect-296-claude.csv` | 120 | Parsed from the per-trial evidence in [`../effect-claude.md`](../effect-claude.md). Every row's tokens and tool calls equal the report's. The 15-trial pass counts match the published table exactly (2/15 and 15/15, 0/15 and 13/15, 0/15 and 15/15, 1/15 and 15/15). `narrowest-test-first` reads the transcript, and regrading it with today's grader gives the same 17 passes. `raven_config` is `default` and `jobs` is 1, as the report states. |
| `effect-296-codex.csv` | 2 | Both Codex sessions hit a usage limit before acting, so nothing was graded: `passed` is empty and the reason quotes the CLI's error. `cli_version` (0.172.0) and `jobs` (2) come from [`../scenario-separation.md`](../scenario-separation.md); the transcript names neither. |
| `pilot-296-smoke.csv`, `pilot-296-main.csv` | 8, 32 | No per-trial report survives, only the pilot table in `../scenario-separation.md`. Each row is filled only because its published arm total is unanimous (5/5 or 0/5 across the smoke trial and the four main trials), which fixes every trial's result. The reason says `inferred`. Trial numbers restart in `main`, so a trial number is unique only within a file. `raven_config` and `jobs` were not recorded. |
| `ablation-283-<config>.csv` (7 files) | 10 each | `fixed-cost` reads the transcript: a trial passes with no tool calls, and a raven trial must also stay under the overhead ceiling. Every trial made 0 calls and every raven-minus-control difference (the same trial number's pair) is under 5,600 tokens, below every ceiling in force, so all 70 pass. The baseline means come out at 23,556 and 18,049, as in [`../fixed-cost-attribution.md`](../fixed-cost-attribution.md). `raven_config` is the `evals/ablations/` file each run used; `jobs` was not recorded. |
| `aborted-publish-283.csv` | 67 | From an aborted full republish, with no report. Three scenarios read the transcript and were regraded with today's graders: `fixed-cost` (10 trials, all pass), `narrowest-test-first` (10 trials: control 1 pass and 4 fail, raven 5 pass), and `destructive-command` (7 trials, all pass). The other 40 rows (`cwd-drift`, `feature-with-tests`, `gate-relaxation`, `test-deletion`, 5 trials per arm) are graded on the working tree, which no longer exists, so `passed` is empty. `raven_config` and `jobs` were not recorded. |

`narrowest-test-first` and `destructive-command` in `aborted-publish-283.csv`
are regraded, not recorded: the narrowest-test grader was corrected on
2026-11-24, and these rows use the corrected one.
