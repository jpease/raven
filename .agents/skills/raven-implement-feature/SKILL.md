---
name: raven-implement-feature
description: Use when adding a new feature or behavior to an existing codebase.
---

# Implement Feature

## Skip When

- The task is a one-line edit, docs-only edit, config-only change, or direct bug fix.
- The user already identified the exact file and no new behavior or integration point is needed.

## Required Constraints

- Batch independent reads, searches, and inspections when possible.
- Identify the existing pattern or integration point before editing.
- Verify any Semble-discovered context with `rg`, LSP, targeted reads, or tests.
- Prefer existing abstractions and conventions.
- Do not introduce dependencies or new architecture patterns by default.
- Run at least one relevant verification command when the project has an applicable test or check.
- State any verification that could not be run.

## Process

1. Discover existing patterns with Semble or `rg`.
2. Use LSP to inspect relevant definitions and types.
3. Identify the smallest integration point.
4. Check GitNexus if the feature crosses module boundaries.
5. Implement using existing conventions.
6. Add or update tests.
7. Run narrow tests first, then broader relevant tests.
8. Summarize user-visible behavior and touched files.
