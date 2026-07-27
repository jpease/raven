---
name: raven-plan
description: Use when work needs durable planning, approval checkpoints, or multi-step execution that should survive chat/session boundaries.
---

# Raven Plan

Use this skill when a task needs a durable plan before implementation, especially when the work spans multiple files, issues, sessions, agents, or approval checkpoints.

This complements interactive planning modes. The important output is a project-local artifact that can be reviewed, resumed, and updated outside the current chat.

## Process

1. Clarify the goal, constraints, acceptance criteria, and known non-goals.
2. Inspect enough project context to identify the owning modules and verification path.
3. Write a concise durable plan in a project-appropriate location, such as `.raven/plans/<short-name>.md`, unless the repo already has a planning convention.
4. Include scope, assumptions, ordered work items, verification, rollback or follow-up notes, and open questions.
5. Get approval before executing when the plan changes public API, schema, migration, release, auth, destructive, dependency, or broad architecture behavior.
6. Update the plan at meaningful checkpoints instead of relying on chat history.
7. When complete, record what shipped, what was verified, and any follow-up issues.

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

## Work Items (end state / verification command / invariants per item)

## Verification

## Follow-Ups
```

## Avoid

- Do not create a plan artifact for a trivial one-step change.
- Do not let the plan replace issue acceptance criteria when issues are the source of truth.
- Do not keep executing after a material plan change that requires approval.
