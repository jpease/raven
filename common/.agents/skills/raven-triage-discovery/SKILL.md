---
name: raven-triage-discovery
description: Use when work outside the current issue's scope is discovered mid-task and needs an explicit disposition.
---

# Triage Discovery

Work found mid-task that falls outside the current issue's acceptance criteria needs a disposition, not a mention. This skill assigns one.

## Skip When

- The finding is already covered by the current issue's stated acceptance criteria.
- The finding is already tracked by an existing open issue. Link to that issue and move on.

## Required Constraints

- Every finding outside current scope gets exactly one disposition: FOLD IN, FILE, or DROP.
- A comment on the current issue or its epic is not a disposition. It is legitimate only as a pointer to a filed issue, never as the terminal record of new work.
- When the choice between FILE and DROP is unclear, file. A closable issue costs less than an invisible one.
- State every disposition to the user. An unstated DROP is indistinguishable from having forgotten.

## Dispositions

| Disposition | Applies when | Required action |
|---|---|---|
| FOLD IN | The finding is inside the current issue's stated scope | Fix it in this diff; name it in the completion summary |
| FILE | The finding is real work outside current scope | Create a new issue linked to the parent or epic |
| DROP | The finding was considered and rejected | State the reason to the user in the completion summary |

## Filing

- File as a sub-issue so the parent's task list shows it: `gh issue create --parent <n>`, or `glab issue create --parent-id <n>`. An issue nobody sees is the failure this skill exists to prevent.
- Where sub-issue linkage is unavailable (gh older than 2.49, or a tracker without it), add a task-list checkbox to the parent body instead.
- With no tracker configured, record the item in the repository's durable planning location, such as `.raven/plans/`, and state it in the completion summary. Never chat-only.
- Title the issue with the problem. Body carries the evidence: file, symbol, and what you observed.
- After filing, a comment on the parent pointing at the new issue is useful. The reverse — a comment instead of an issue — is the failure mode.

## Rationalization Check

| Thought | Reality |
|---|---|
| "I'll note it in a comment so it isn't lost" | A comment is where findings go to be lost. Comment only to point at a filed issue. |
| "This is too small to file" | Small and real is FILE. Small and rejected is DROP with a reason. Neither is silence. |
| "The epic already mentions this area" | An area is not an issue. Nothing schedules an area. |
| "I'll just fix it while I'm here" | That is FOLD IN only if it is in scope. Otherwise it is silent scope expansion. |
| "I'm not sure it's a real problem" | Then file it. Deciding is the tracker's job, not something to settle by dropping. |
| "The user saw it in my summary" | A summary is chat. Chat is as invisible as the epic comment this skill replaces. |

## Output

State the disposition of every finding before declaring the unit of work done:

> Discovered work: [N] item(s). FOLD IN: [what, now in this diff]. FILED: [#num — title]. DROPPED: [what — why].

When there is none:

> Discovered work: none.
