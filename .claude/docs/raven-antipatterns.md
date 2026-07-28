# Repo Anti-Pattern Registry

A living record of anti-patterns *this repository* keeps producing — not a list
Raven prescribes. Raven ships this file almost empty on purpose: the content is
inherently repo-specific, and a template that pre-fills code-shape opinions would
be prescribing style, not process.

Loaded on demand (`.claude/docs/`, not `.claude/rules/`): a registry that is meant
to grow should not cost every session's context budget. `raven-review-pr`
references it by path when relevant instead of it being always-loaded.

## When To Add An Entry

Add an entry only when two instances of the same pattern are demonstrable in
the same review, cited by file and line at recording time. A single
instance stays an ordinary review comment and is never recorded on its own.

This registry has no memory across sessions: a first sighting that is never
paired with a second instance in the same review is simply lost, not
tracked. Recurrences whose two instances land months apart, in
different sessions, will never be recorded — that is a deliberate cost, not
an oversight; the alternative is an ever-growing list of unconfirmed single
sightings.

## Entry Format

Each entry is a level-3 heading (the pattern's short name) with four fields:

- **Status**: `observed` | `promoted to <check-name>` | `retired`
- **Pattern**: what it looks like — concrete, code-shape description, plus
  the two cited instances (file:line) that justified recording it
- **Why**: why it is wrong *here* — repo-specific, not a general style opinion
- **Instead**: what to do instead

## Status Lifecycle

1. `observed` — recorded once two cited instances exist in the same review.
   Reviewers may cite this entry in future findings instead of
   re-explaining the issue each time.
2. `promoted to <check>` — once the pattern is mechanically detectable,
   recommend a Semgrep rule (or the project's existing static-analysis
   equivalent) wired into the gate, naming the check. Writing the rule and
   wiring the gate is separate, authorized implementation work per Pause
   And Ask, not something the reviewer does directly. Update the status to
   name the check once that work lands — a promoted entry should stop
   consuming reviewer attention, since the gate catches it now.
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
