---
name: raven-plan
description: Use when work needs durable planning, approval checkpoints, or multi-step execution that should survive chat/session boundaries.
---

# Raven Plan

Use this skill when a task needs a durable plan before implementation, especially when the work spans multiple files, issues, sessions, agents, or approval checkpoints.

This complements interactive planning modes. The important output is a project-local artifact that can be reviewed, resumed, and updated outside the current chat.

## Process

1. Interrogate the request per Interrogate First, then record the goal, constraints, acceptance criteria, and known non-goals.
2. Inspect enough project context to identify the owning modules and verification path.
3. Write a concise durable plan in a project-appropriate location, such as `.raven/plans/<short-name>.md`, unless the repo already has a planning convention.
4. Include scope, assumptions, ordered work items, verification, rollback or follow-up notes, and open questions.
5. Run the Fresh-Context Check before requesting approval.
6. Get approval before executing when the plan changes public API, schema, migration, release, auth, destructive, dependency, or broad architecture behavior.
7. Update the plan at meaningful checkpoints instead of relying on chat history.
8. When complete, record what shipped, what was verified, and any follow-up issues.

## Interrogate First

Question the request before writing anything down. Ask what the goal leaves undefined, which constraints are assumed rather than stated, and what result the user would call wrong. Keep asking until the user says the description is complete. When the work falls in an AGENTS.md Pause And Ask category, add a pre-mortem to that list: assume this shipped and caused an incident, and say what the incident was. No specific answer means the category was recognized as a label rather than as a failure, which is the signal to ask rather than proceed.

Propose the first approach yourself. Reacting to an approach the user proposed inherits its blind spots, and AGENTS.md Safety Rules already governs ratifying it without challenge.

Write no code during this step. The Completion Criteria below make a plan terminable; they do not make an underspecified request correct, and a terminable plan built on one finishes green on the wrong work.

## Completion Criteria

Each work item's completion criteria must give three things, not prose:

- **End state**: what is observably true when the item is done.
- **Verification command**: the literal command and its expected result — not "tests pass" (e.g. `pytest tests/test_upgrade.py` exits 0).
- **Invariants**: what must remain unchanged (e.g. no file outside `scripts/raven_lib/` is modified; no new dependency is added).

Example: end state — `raven upgrade` skips unmanaged files; verification — `python scripts/self-check.py` exits 0; invariants — no new dependency is added.

Prose-only criteria such as "the migration is complete" or "tests are passing" are insufficient: they cannot terminate a check or survive a session boundary. Reject them and ask for the triple instead.

## Durable Plan Shape

```markdown
# Plan: <short title>

## Goal

## Scope

## Non-Goals

## Assumptions

## Alternatives (approach rejected / why / what would reopen it)

## Work Items (end state / verification command / invariants per item)

## Verification

## Follow-Ups
```

Fill Alternatives during the design discussion, while the argument is live. Written afterwards it degrades to a list of approaches nobody seriously held, and the reasoning that ruled each one out is already gone. Generate at least one of them by inverting a constraint rather than by varying the chosen approach — what ships if only one work item can, what the tenth-of-the-work version looks like, what the design would be if the code being changed did not exist. Three designs that differ in a parameter are one design, and a set like that records no decision.

An alternative a reader would actively restore at the code — an obvious-looking simplification the plan rejected for a reason invisible at that line — also earns a comment at the site, per `raven-write-prose` on code comments. The rest stay in the plan: a rejected-alternatives note at every decision site decays into changelog commentary about a design no current reader can observe.

## Fresh-Context Check

A plan is durable when someone holding only the plan can act on it. Test that instead of assuming it.

Hand the plan alone — no conversation history — to a zero-context reader: a fresh session, or a sub-agent briefed with nothing but the file path. Ask it to state the goal, the files it would change, and the verification command it would run.

It passes when the reader answers all three and asks no blocking question. Every question it does ask marks a hole; write the answer into the plan and repeat. Answering in chat leaves the hole in place and hides it, because the next reader starts where the fresh one did.

When no fresh session or sub-agent is available, say the plan is unverified for resumption rather than calling it durable.

## Avoid

- Do not create a plan artifact for a trivial one-step change.
- Do not let the plan replace issue acceptance criteria when issues are the source of truth.
- Do not keep executing after a material plan change that requires approval.
