---
name: raven-implement-feature
description: Use when adding a new feature or behavior to an existing codebase.
---

# Implement Feature

## Skip When

- The task is a one-line edit, docs-only edit, config-only change, or direct bug fix.
- The user already identified the exact file and no new behavior or integration point is needed.

AGENTS.md Retrieval Discipline and Verification State already govern batching, Semble verification, and reporting what went unverified. This skill adds only what is specific to feature work.

## Required Constraints

- Identify the existing pattern or integration point before editing.
- Prefer existing abstractions and conventions.
- Do not introduce dependencies or new architecture patterns by default.
- Run at least one relevant verification command when the project has an applicable test or check.
- Work that exceeds the stated scope ceiling requires stopping and asking per AGENTS.md Pause And Ask, not silent expansion.

## Process

1. Discover existing patterns with Semble or `rg`. If a similar pattern is already known, use Semble `find_related` on it for a more targeted result than a fresh search.
2. Use LSP to inspect relevant definitions and types.
3. Identify the smallest integration point.
4. Check GitNexus if the feature crosses module boundaries.
5. Before editing, state:
   - the observable behavior change, in one or two sentences
   - the acceptance criteria you will verify against
   - the scope ceiling: what you will not touch, build, or generalize
6. Implement using existing conventions.
7. Add or update tests.
8. Run narrow tests first, then broader relevant tests.
9. Summarize user-visible behavior, touched files, and whether the scope ceiling held or where it moved.

## When To Stop

Apply the AGENTS.md stop rule against the owning module, comparable pattern, or smallest integration point. Also stop if candidates are contradictory, unrelated, or too broad to inspect without reading many full files.

Do not invent a new integration point just because discovery is inconclusive.
