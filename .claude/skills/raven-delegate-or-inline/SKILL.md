---
name: raven-delegate-or-inline
description: Use when deciding whether to delegate a task to a sub-agent or handle it inline.
---

# Delegate Or Inline

Default to inline. Delegate only when the task matches at least one criterion below — "this feels like it needs a deep look" is not sufficient justification on its own.

## Skip When

- The task is a surgical, single-file, single-symbol edit.
- The user already told you which approach to use for this task.
- The task is large but forms one continuous causal chain — each step's design depends on the previous step's resolved outcome. Splitting a chain like this forces independent subagents to either re-derive the same reasoning or receive it secondhand and lossily. Delegate breadth (independent files, parallel checks); keep depth (one unresolved chain of decisions) inline even at large size.

## When To Delegate

- An architecture or "how does X work" question would take many retrieval steps to answer directly.
- The expected output is noisy relative to what the main context needs — large diffs, long logs, or many candidates where only a summary matters.
- The work is a specialized audit with its own checklist, such as a security review, test coverage analysis, or type design review.
- Independent or adversarial reasoning is needed (competing approaches, code review) rather than one continuous train of thought.

## How To Delegate

- Frame the task as a self-contained question: state the goal, what is already ruled out, and the expected output shape (file list, yes/no with evidence, root-cause summary).
- Do not pass the full conversation history — delegation should reduce context, not duplicate it.
- Before delegating a symbol-editing task, run impact analysis yourself and put the blast radius (callers, affected flows, risk) in the brief; the subagent lacks your context and cannot infer scope. Have the subagent run change-detection before committing.
- Give the brief an explicit editable-file list, not just a forbidden-file list. "You may modify A, B, C; nothing else" is checkable; "don't touch the vendor directory" is not.
- Before dispatching a task that carries a value or change through a pipeline, trace the data path end to end — producer, serializer, reader, consumer — and confirm every hop is either in the editable list or deliberately excluded for a stated reason. A subagent that stays correctly in scope through a gap in the brief will still return green: it edits what it was told to, notices an unwired hop, correctly declines to touch it, and reports it as out of scope while every test and gate passes.
- Require an `## Out Of Scope Findings` section in the return, present-but-empty when there are none. A return without it is incomplete: what the sub-agent noticed but you did not ask about is exactly what gets lost. Disposition whatever comes back per `raven-triage-discovery` — but treat an entry naming a file on the task's own data path as a briefing defect, not a routine follow-up: fold it into this task rather than filing it for later.
- After the subagent returns, verify the feature end to end on real input, not only by running its tests — its tests were written against the brief and inherit any gap the brief had.
- If no delegation mechanism is available, pause and ask the user instead of expanding retrieval indefinitely.

## Rationalization Check

| Thought | Reality |
|---|---|
| "This feels like it needs a deep look" | A feeling isn't a criterion. Match it to a bullet above, or stay inline. |
| "Delegating is safer / more thorough" | Splitting off a surgical edit adds a context hop, not rigor. |
| "I always delegate audits like this" | Habit isn't the test. Re-check the task's actual shape against the bullets. |
| "This is large, I should split it up" | Size alone isn't the test either. If it's one coupled chain of decisions rather than independent pieces, splitting adds re-derivation cost, not speed. |
| "The subagent's tests are green, it's done" | Its tests were written against the brief you gave it. A gap in the brief is invisible to them. Verify end to end before trusting green. |

## Platform Notes

- Claude Code: use the Agent tool with an appropriate subagent type, or a project-defined subagent if one matches the audit.
- Other harnesses: fall back to asking the user to scope the task further, or use any equivalent delegation mechanism the harness provides.
