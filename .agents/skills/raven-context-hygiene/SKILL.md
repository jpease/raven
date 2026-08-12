---
name: raven-context-hygiene
description: Use at unit completion and when the user signals a new unrelated task is beginning.
model: haiku
---

# Context Hygiene

## Skip When

- The session just started and there is no prior work in context.
- The new request is a direct follow-up to what was just discussed.

## Process

1. Identify the trigger:
   - Unit completion: invoked after `raven-session.py --complete`
   - New-session language: user says something like "now let's work on X" or "next up is Y"
2. Check whether the current harness's own instructions state that context is managed automatically (e.g. Claude Code states conversations are summarized/compacted automatically and work should continue without manually clearing).
   - If so: skip the manual-clear prompt. Briefly restate the new goal and continue — the harness already handles context growth.
   - If not (an unfamiliar harness, or genuine uncertainty): ask "Looks like we're starting something new — would you like to `/clear` context, `/compact`, or continue as-is?" and wait for a response before proceeding.
