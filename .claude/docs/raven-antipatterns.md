# Repo Anti-Pattern Registry

A living record of anti-patterns *this repository* keeps producing — not a list
Raven prescribes. Raven ships this file almost empty on purpose: the content is
inherently repo-specific, and a template that pre-fills code-shape opinions would
be prescribing style, not process.

Loaded on demand (`.claude/docs/`, not `.claude/rules/`): a registry that is meant
to grow should not cost every session's context budget. `raven-review-pr`
references it by path when relevant instead of it being always-loaded.

## When To Add An Entry

Add an entry only when a pattern has been observed **more than once** (two
strikes). Do not record on first sighting — a single occurrence is a normal
review comment. Recording every first sighting turns this into an
ever-growing complaint list instead of a signal of genuine recurrence.

## Entry Format

Each entry is a level-3 heading (the pattern's short name) with four fields:

- **Status**: `observed` | `promoted to <check-name>` | `retired`
- **Pattern**: what it looks like — concrete, code-shape description
- **Why**: why it is wrong *here* — repo-specific, not a general style opinion
- **Instead**: what to do instead

## Status Lifecycle

1. `observed` — recorded after the second occurrence. Reviewers may cite this
   entry in future findings instead of re-explaining the issue each time.
2. `promoted to <check>` — once the pattern is mechanically detectable, write a
   Semgrep rule (or the project's existing static-analysis equivalent) and wire
   it into the project's gate. Update the status to name the check. A promoted
   entry should stop consuming reviewer attention — the gate catches it now.
3. `retired` — the motivating conditions are gone (code refactored away, check
   removed, pattern stopped recurring). Delete retired entries the next time
   this file is edited; this is a working registry, not a changelog, and a
   registry that only grows is worse than no registry.

## Semgrep Is Optional

Promotion assumes the pattern is mechanically detectable, and does not require
Semgrep specifically. If Semgrep is not configured for this repo, promote to
whatever deterministic check the project already uses (linter rule, ast-grep
rule, custom CI script), or leave the entry at `observed` indefinitely. Never
block recording an entry on Semgrep availability.

## Template Entry (illustrative only — replace or delete)

### Example: placeholder pattern name

- Status: observed
- Pattern: describe the concrete code shape here — not filled in by Raven.
- Why: describe why it is wrong for *this* codebase — not filled in by Raven.
- Instead: describe the preferred alternative — not filled in by Raven.
