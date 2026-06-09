# Raven Context Hygiene Skill — Design Spec

**Date:** 2026-06-09
**Status:** Approved

## Problem

Long context degrades AI response quality. Natural task boundaries — finishing a unit of work, starting something unrelated — are the right moments to clear or compact, but agents don't currently prompt users to consider this. Left unaddressed, users work in bloated context longer than they need to.

## Goal

A lightweight skill that surfaces a context hygiene recommendation at the right moment, prompts the user to make a deliberate choice, and stays out of the way otherwise.

## Non-Goals

- Model or effort-level selection guidance (too vendor-specific, changes too frequently)
- Automatic context clearing or compaction (agent cannot trigger these; only the user can)
- Measuring context size or token count

## Triggers

Two signals cause the agent to invoke this skill:

1. **Unit completion** — after `raven-session.py --complete` in `raven-project-lifecycle`
2. **Explicit new-session language** — user says something like "now let's work on X" or "next up is Y"

These were chosen because they are structural or linguistic events the agent can detect reliably with low false-positive rate. "Long investigation" and generic task-topic shift were considered and rejected: they require subjective judgment that leads to noisy false positives.

## Skill Design

### File

`common/.agents/skills/raven-context-hygiene/SKILL.md`

### Skip When

- The session just started and there is no prior work in context.
- The new request is a direct follow-up to what was just discussed.

### Process

1. Identify the trigger (unit completion or new-session language).
2. Ask: *"Looks like we're starting something new — would you like to `/clear` context, `/compact`, or continue as-is?"*
3. Wait for response, then proceed accordingly.

### Design Decisions

**Why block for a response?** A non-blocking recommendation scrolls by and gets ignored. A direct question ensures the user makes a deliberate choice. The cost (one response) is low at a natural pause point.

**Why no handoff note?** If the user clears context, they are intentionally leaving prior work behind — there is nothing to carry forward. Their current prompt remains in shell history if needed.

**Why `/clear` and `/compact` by name?** Both Claude Code and Codex use these exact commands. Named commands are more actionable than generic descriptions.

**Why not an AGENTS.md rule?** Would fire too broadly across short single-task sessions. A standalone skill with a clear description is sufficient for agent invocation.

## Integration

`raven-project-lifecycle` Phase 3 gains one step after the `--complete` call:

```
5. Invoke `raven-context-hygiene`.
```

No other skills require changes.

## Out of Scope

A companion "model selection" skill was considered and deferred. Model IDs and capability tiers change too frequently for stable guidance; principles-only guidance would not be actionable enough to justify a skill.
