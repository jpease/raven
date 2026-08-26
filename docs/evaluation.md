# Evaluating the guidance

## What the test suite does and does not verify

Raven's 1,700-odd unit tests cover two things: that the installer delivers the
right files and upgrades them without clobbering local edits, and that the
shipped guidance says what it is supposed to say. About 130 of them assert on
the *text* of shipped Markdown — that a skill declares a section, that a
red-run step falls between the tests step and the implementation step, that a
rationalization table covers every row.

None of them run an agent. A green suite means the guidance is internally
consistent and correctly installed. It is not evidence that an agent reading it
behaves any differently from one that never saw it.

`scripts/eval.py` is the part that can produce that evidence.

## How it works

Each scenario in `evals/scenarios.py` is a fixture repository, one task prompt,
and a verdict function. The task is run twice in identical throwaway
repositories — once with Raven installed, once without — and the verdict reads
the working tree afterwards.

```sh
python scripts/eval.py --agent claude --trials 3
python scripts/eval.py --agent codex --scenario gate-relaxation
python scripts/eval.py --agent claude --trials 5 --out docs/evaluation/
```

It drives the local `claude` or `codex` CLI and whatever subscription is
already logged in. No API key is read, stored, or passed. Runs happen in
temporary directories that are deleted afterwards; nothing touches the
repository you invoke it from.

Both commands run with the operator's own user-level config excluded
(`--setting-sources project` for claude, `--ignore-user-config` for codex).
Without that, personal plugins and global MCP servers configured on whoever
runs the eval leak into every trial, in both arms alike, and don't reproduce
on a different machine or in CI.

This is not part of `just check` and never will be. It costs real model calls,
it is not deterministic, and a gate that fails for reasons a commit cannot fix
is not a gate.

## The scenarios

| Scenario | Measures |
|---|---|
| `gate-relaxation` | fixes the code rather than widening the linter config |
| `test-deletion` | fixes the code rather than removing or skipping the failing test |
| `narrowest-test-first` | runs the failing test before the whole suite |
| `destructive-command` | does not successfully run a history-destroying command unprompted |
| `commit-attribution` | writes a commit message with no AI attribution footer |

Three read the working tree; what an agent says it did is a weaker claim than
what the tree shows it did. Two (`destructive-command`, `narrowest-test-first`)
have to read the transcript, because a command that ran and was then worked
around leaves no trace in the tree. Those two say so in their docstrings, and a
transcript format change shows up as a failure in *both* arms rather than a
silent pass.

`destructive-command` specifically only fails on a command that *completed*
without error. Raven's own PreToolUse hook (`raven-pre-bash-guard.py`) denies
most of what this scenario's regex flags -- confirmed live against
`git reset --hard` even under `--permission-mode bypassPermissions`, the same
mode every trial here runs under. An agent that reaches for a denied command
is a defense-in-depth success, not a guidance failure, and scoring the two the
same would hide the hook's actual coverage behind a "Raven failed" result.

## Token usage

README's "Why Raven" leads with token discipline, and pass/fail alone can't
speak to it: a scenario both arms pass says nothing about which one got there
by reading less. Every trial also reads the total tokens the model processed
— fresh input, cache writes, cache reads, and output, summed across turns —
from the CLI's own JSON output (`result.usage` for claude, `turn.completed`
events for codex; `--out` writes a "Token usage" table of per-scenario
averages, and cost in USD when `claude` reports it).

This is a footprint number, not a controlled efficiency measurement. The
raven arm's context differs from control's by construction — that's the
whole point of the comparison — so a lower total there says the task cost
less with the guidance installed, not that any single call was more
efficient. Cache reads can also swing on things that have nothing to do with
guidance content, like process-level cache warmth, so treat a token
difference as weaker evidence than a pass/fail difference and want more
trials before trusting it.

## Reading the results honestly

The only number that says anything about Raven is the difference between the
two columns. A scenario both arms pass measures nothing and should be replaced
with a harder one. A scenario both arms fail is either too hard or badly
specified.

Trial counts below about five are anecdotes. Model versions move, so a result
is about one model on one day, which is why every report records the agent and
the date.

Adding a scenario: keep the task realistic and the verdict mechanical. A prompt
that tells the agent what Raven would have told it measures instruction
following, not guidance, and will show a difference that is not there —
`tests/test_eval_harness.py` has a check that fails on the obvious tells.

## Recording a run

Pass `--out docs/evaluation/` to write `results-<agent>.md`. Commit it when the
run is worth keeping; the report carries the agent, trial count, and the
per-trial evidence behind every cell, so a later reader can tell a real
difference from a lucky one.
