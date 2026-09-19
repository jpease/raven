---
name: raven-debloat
description: Use for periodic subtractive maintenance — removing dead code, inert placeholder subsystems, or redundant layers.
---

# Debloat

Periodic subtractive maintenance across an area: find code that no longer earns its place and propose removing it. The failure mode it addresses is accumulation where every individual piece is defensible — plumbed-but-inert subsystems, mirrored state layers, defensive abstractions guarding problems that no longer exist.

## Skip When

- The task is cleaning up the diff you just wrote. That belongs in the change itself or a review pass, not a maintenance sweep across an area.
- Tests, static analysis, or a runtime check are red right now. Fix the baseline first — cutting against a broken baseline is not measurable.
- The area is under active feature work or an in-flight refactor by someone else.

## Required Constraints

- No SLOC target. Size is a forcing function for finding simplification, never a goal to reach. Do not set, accept, or infer a size or percentage goal; if the user names one, treat it as a hint about where to look and say so.
- Every structural removal is proposed and confirmed before it is applied. No automatic deletion.
- Deleting a subsystem is a broad refactor with unclear scope by definition — route to AGENTS.md Pause And Ask every time, no exceptions.
- Replacing bespoke code with a third-party library is a dependency addition — route to AGENTS.md Pause And Ask before writing any code.
- Dead-code claims need semantic evidence: LSP references, GitNexus impact (`mcp__gitnexus__impact`), or a dead-code analyzer. Text search alone does not prove a symbol is unused — dynamic dispatch, reflection, config, and generated call sites never show up in `rg`.
- Green tests prove behavior, not design health. A passing suite is not evidence the code deserves to stay.
- Report "nothing structural to remove" as a conclusion with evidence when that is the finding. Never delete to have something to report.

## Process

1. Run Preflight. Do not jump to a deletion because one candidate looks obvious.
2. Take the highest applicable tier of the Reduction Hierarchy, propose the specific candidate with its evidence, and wait for confirmation.
3. Apply one candidate as one milestone, verify with the baseline commands, keep it independently revertible, and check in — small verified milestones beat one large pass.
4. Run the Anti-Gaming Self-Audit every few milestones and honor its verdict, including when the verdict is to stop.
5. Report per Output, and record any accumulation shape that recurred across candidates in `.claude/docs/raven-antipatterns.md` — removal clears the instances, the registry stops the shape recurring.

## Preflight

1. Before the first deletion, verify tests, static analysis, and a runtime check all pass now. Record the exact commands — they are both the baseline and the per-milestone gate.
2. Record a size baseline broken down per area, so later measurement is per-area rather than one aggregate figure.
3. Compute the irreducible floor: generated code, platform scaffolding, vendored files, lockfiles. These are not candidates — exclude them from the baseline and never propose them.
4. Pin formatting. Run the project's formatter and land it separately, so later diffs stay comparable and reformatting cannot be mistaken for reduction.
5. Name the dead-code tooling this repo actually has. If there is none beyond text search, say so — every claim below is lower-confidence as a result.

## Reduction Hierarchy

Work in this order. Earlier tiers are higher-confidence and lower-risk; do not skip ahead to a riskier tier because it looks larger.

1. Genuinely dead code — unreferenced symbols, files, and branches, confirmed semantically.
2. Placeholder subsystems fully plumbed into models, persistence, or UI but inert. **Gated: Pause And Ask.**
3. Debug and test scaffolding sitting in shipping source — relocate it to the test tree; do not delete coverage.
4. Redundant state or abstraction layers mirroring each other, including partial fixes that left the surrounding weirdness intact.
5. Clean-room rewrite of a component against its tests as the behavioral spec. Viable only where tests assert observable behavior rather than internals, which is what `raven-write-tests` requires.
6. Replacing bespoke code with a mature library. **Gated: Pause And Ask — a dependency addition, however obviously better the library looks.**
7. Comment hygiene — delete comments restating the obvious, add the one explaining the genuinely surprising thing. Hygiene only, never counted as a reduction.
8. Riskier architectural simplification. **Gated: Pause And Ask.**

## Anti-Gaming Self-Audit

Run every few milestones. This audit can end the run, and ending it is a success state. Classify every reduction so far as one of:

- **Structural** — a subsystem, layer, abstraction, or dead path is gone. The thing that produced the code no longer exists.
- **Cheap** — comment deletion, line packing, formatting, import shuffling, whitespace. Nothing structural changed.

If cheap reductions dominate, state which of these is true: you are gaming the metric, or the structural well is dry. If the well is dry, stop and report — do not go hunting more cheap wins. Continuing a run whose recent reductions are all cheap produces a reformatted codebase and a fake result, which is exactly what this audit exists to prevent.

## Rationalization Check

| Thought | Reality |
|---|---|
| "This looks unused, I'll remove it" | Looking unused is not evidence. LSP references or impact analysis, or it stays. |
| "This one is too risky, I'll leave it and report done" | Under-reach is a failure too. Name the candidate and its risk; let the user decide. |
| "A mature library is obviously better here" | Obvious to you is still a dependency addition. Pause And Ask before writing code. |
| "I'll tidy comments to keep momentum" | Comment hygiene is never a reduction. If it is all that is left, say the well is dry. |
| "Reformatting would let me re-measure" | Formatting was pinned in Preflight. Re-measuring after a reformat is gaming. |

## Stop Conditions

Stop and report rather than continuing when:

- The self-audit finds cheap reductions dominating.
- A milestone needed more than one revert-and-retry. Revert to the last green milestone and hand the decision back.
- A candidate's blast radius stays unclear after targeted retrieval — apply `raven-safe-refactor`'s evidence and stopping rules to any candidate that renames, moves, or changes a shared contract.
- The remaining candidates are all gated and no decision has come back.

## Output

Per milestone: `Removed: [what, and the evidence it was safe]. Area: [name, before → after]. Verified: [commands and results]. Revertible as [commit or patch].`

At the end: `Structural: [list]. Cheap: [list]. Audit verdict: [continuing | well dry | gaming — stopped]. Proposed but not applied: [gated candidates awaiting a decision].` When nothing qualified, that report is instead `No structural reduction available in [area] — [what was inspected, with what tooling, and why each candidate was ruled out].`
