# Repo Precedent Log

A record of owner decisions in *this repository* whose answer applies beyond
the task that prompted them. Raven ships this file almost empty on purpose:
precedents are repo-specific, and a template cannot know what an owner has
already decided.

Loaded on demand (from `.claude/docs/` rather than `.claude/rules/`), so a log
that grows does not cost every session's context budget. Agents open it before
asking a Pause And Ask question.

## When To Add An Entry

Only the human owner creates, edits, or retires an entry. An agent may draft
one when the owner answers a question and the answer plainly covers future
cases too, such as "pin third-party CI actions by commit SHA" given while
reviewing one workflow. Show the draft in the response and write it only once
the owner approves the wording.

A one-off answer stays in the conversation. Record a precedent only when the
owner would give the next agent that asks the same answer.

## Entry Format

Each entry is a level-3 heading (the decision's short name) with four fields:

- **Decision**: what to do, stated so an agent can act on it without the
  original conversation
- **Scope**: where it applies and where it does not, by path, task type, or
  condition
- **Decided**: the date and who decided
- **Reconsider when**: the trigger that reopens the question, such as a
  dependency upgrade, a new deployment target, or a calendar date

## Using The Log

Before asking a Pause And Ask question, read this log:

- An active entry's scope covers the case: follow its Decision and cite the
  entry by name in the response instead of asking.
- The scope is unclear, or only nearly covers the case: ask, and name the
  near-miss entry so the owner can widen it, narrow it, or answer once.
- An entry's Reconsider-when trigger has fired: ask, citing the entry and
  the trigger.

An entry answers only the question it records. Extending it to a neighbouring
case by analogy is a new question for the owner.

## Retirement

The owner retires an entry by adding a **Retired** field with the date and
reason. Retired entries stay in the file and are never deleted silently: the
log is a decision history, not a working registry. Agents do not follow a
retired entry, but cite it when the same question returns so the owner sees
the earlier reasoning.

## Template Entry (illustrative only — replace or delete)

### Example: placeholder decision name

- Decision: describe what to do — not filled in by Raven.
- Scope: describe where it applies and where it does not — not filled in by Raven.
- Decided: date and decider — not filled in by Raven.
- Reconsider when: describe the reopening trigger — not filled in by Raven.
