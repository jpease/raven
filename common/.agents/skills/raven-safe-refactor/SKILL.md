---
name: raven-safe-refactor
description: Use for renames, shared abstraction changes, API changes, moved code, or broad mechanical edits.
---

# Safe Refactor

## Skip When

- The edit is isolated, internal, and does not rename, move, or change a contract.
- The task is a behavior change rather than a structure-preserving refactor.

## Required Constraints

- Do not combine refactor and behavior change unless asked.
- Capture reference or dependency evidence before editing public or shared symbols.
- Before editing a shared constant or list, also check for an import-free guarded duplicate: GitNexus impact analysis only walks CALLS/IMPORTS/EXTENDS edges, so a copy kept in sync by convention and a test — not an import, because the two files can't import each other — has no edge for it to find. Grep near the symbol for duplicate-language markers (`mirrors`, `duplicates`, `pinned against`, `guarded against drift`), and `rg` its literal *value* rather than its name, since the copy rarely reuses the name.
- Use syntax-aware tools for broad mechanical changes when available.
- Add a required new member to every implementer before adding it to the shared interface, protocol, or abstract base — stash the declaration if you drafted it first. Declaration-first leaves the tree uncompilable for the whole sweep, so every test run in between returns the same build or import error whatever else the edit broke. `raven-write-tests` covers finding the implementers; this is the order to edit them in.
- Verify textual leftovers with `rg` after renames, moves, or API changes. Do not scope the sweep with extension filters (`--include`/`-t`/`-g '*.ext'`) — extensionless build and config files (`Dockerfile`, `Makefile`, `Rakefile`, `Fastfile`, `Vagrantfile`, `Jenkinsfile`) are invisible to them and are common places for a stale reference to survive.
- Stop and ask or delegate when ownership, references, or blast radius remain unclear after targeted retrieval.
- Do not reformat unrelated files.
- Run targeted tests or explain why no targeted verification exists.

## Rationalization Check

| Thought | Reality |
|---|---|
| "This symbol is only used in one obvious place" | Confirm with LSP references or GitNexus impact — don't assume from memory. |
| "It's a small rename, nothing will break" | Small renames break silently in strings, configs, and docs. Verify with `rg` after. |
| "I already have blast-radius context from earlier" | Re-check if the target, scope, or codebase changed since. |
| "No tests cover this path, so it's probably safe" | Missing coverage raises risk — note the gap, don't treat silence as a pass. |
| "I'll add the interface member first, then fix the implementers" | That leaves the tree uncompilable for the whole sweep. Every test run in between reports the same error whatever else you broke. |
| "GitNexus impact analysis found no callers, so nothing depends on this" | A call graph only sees CALLS/IMPORTS/EXTENDS edges. A constant duplicated across a boundary that can't import back has no edge to find — grep for duplicate-language markers and `rg` the literal value too. |

## Process

1. Identify public surface area.
2. Use LSP references before editing. If similar implementations may exist elsewhere, use `ast-grep` for the pattern's shape or `rg` for its distinctive literals to find them too.
3. Use GitNexus (`mcp__gitnexus__impact`) for dependency and blast-radius analysis. For a shared constant or list, that only walks CALLS/IMPORTS/EXTENDS edges — also grep near it for duplicate-language markers (`mirrors`, `duplicates`, `pinned against`, `guarded against drift`) and `rg` its literal value, since an import-free textual duplicate has no edge to walk.
4. Take a rollback point before the first broad edit — commit the green state, or stash it when the change is not ready to be a commit. Backing out of a direction that fails then costs one command rather than a hand reconstruction.
5. Use ast-grep or Semgrep for mechanical syntax-aware rewrites. Run `ast-grep run -p '<pattern>' -r '<fix>'` without `-U` first — it prints the diff and writes nothing — read that diff, then re-run with `-U` to apply. Reaching for `-U` on the first attempt rewrites every matching file in the tree unreviewed, the kind of destructive command AGENTS.md Safety Rules require approval for. Leave `-i` to a human at a terminal: it opens a full-screen TUI that stalls a non-interactive agent session.
6. Use `rg` to verify no textual leftovers.
7. Run targeted tests.
8. Summarize contract changes.

## When To Stop

Stop before editing when LSP, GitNexus, text search, or syntax-aware search cannot establish the references, ownership, or blast radius of the refactor. Summarize the missing evidence and delegate per AGENTS.md Delegation guidance, or pause and ask the user if the safe change depends on intent or compatibility decisions. For a review pass before a broad refactor, delegate to the `raven-refactor-reviewer` subagent with a scoped brief: the planned change, the references and dependencies found, and the blast-radius question that remains open.
