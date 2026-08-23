---
name: raven-implement-feature
description: Use when adding a new feature or behavior to an existing codebase.
---

# Implement Feature

## Skip When

- The task is a one-line edit, docs-only edit, config-only change, or direct bug fix.
- The user already identified the exact file and no new behavior or integration point is needed.

AGENTS.md Retrieval Discipline and Verification State already govern batching, verifying a semantic hit before acting on it, and reporting what went unverified. This skill adds only what is specific to feature work.

## Required Constraints

- Identify the existing pattern or integration point before editing.
- Prefer existing abstractions and conventions.
- Do not introduce dependencies or new architecture patterns by default.
- Take a third-party API's shape from the installed version, not from memory. Confirm the symbol with LSP against the installed package before calling it — a name renamed a major ago still writes fluently from training and fails at runtime.
- Run at least one relevant verification command when the project has an applicable test or check.
- Work that exceeds the stated scope ceiling requires stopping and asking per AGENTS.md Pause And Ask, not silent expansion.

## Process

1. Discover existing patterns with `rg`, or with `mcp__gitnexus__query` where an index is configured. If a similar pattern is already known, `ast-grep` its shape for a more targeted result than a fresh text search.
2. Use LSP to inspect relevant definitions and types.
3. Before picking an integration point, check whether the feature needs symbols from two components that do not already depend on each other. If so, resolve the dependency-direction question first — which side may legally import the other, or whether a new shared location is needed — using GitNexus or the project's dependency graph/build manifest (package config, module map, import-boundary rules). Do this before choosing where the code lives, not while writing it.
4. Identify the smallest integration point consistent with that direction.
5. Before editing, state:
   - the observable behavior change, in one or two sentences
   - the acceptance criteria you will verify against
   - the scope ceiling: what you will not touch, build, or generalize
   - when the change hand-rolls something in a category with a standard solution (crypto, auth, date/time arithmetic, parsing, retry and backoff), one sentence on why not the library. This is a stated reason, not an approval gate — adding a dependency stays gated by AGENTS.md Pause And Ask, and the point is that hand-rolling stops being the silent default.
6. Add or update tests for the behavior change before implementing, per `raven-write-tests`.
7. Run them and confirm they fail for the behavior they assert, per `raven-write-tests`.
8. Implement using existing conventions.
9. Run narrow tests first, then broaden to relevant tests.
10. Summarize user-visible behavior, touched files, and whether the scope ceiling held or where it moved.

## When To Stop

Apply the AGENTS.md stop rule against the owning module, comparable pattern, or smallest integration point. Also stop if candidates are contradictory, unrelated, or too broad to inspect without reading many full files.

Do not invent a new integration point just because discovery is inconclusive.
