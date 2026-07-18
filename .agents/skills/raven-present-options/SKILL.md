---
name: raven-present-options
description: Use when presenting the user with multiple viable options or approaches to choose between.
---

# Present Options

Lead with a recommendation for this task, not a neutral survey.

## Skip When

- Only one viable approach exists.
- The user explicitly asked for an exhaustive comparison or survey of all options.

## Format

**Recommendation:** [Option X] — one sentence stating which you'd pick.
**Why:** [One sentence tied to this task's specifics — what makes it best here, not in general.]
**Trade-off:** [One sentence on the key advantage of the runner-up vs your choice.]

Keep the whole thing to ~3 sentences of prose. If more context is needed, the choice is probably not clear enough yet — the user can ask "why not Y?" if they disagree.

## When To Ask Instead

Use `AskUserQuestion` (or the platform equivalent) when the choice is genuinely close, depends on unstated preferences, or has more than two options with complex dependencies between them.
