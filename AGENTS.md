# Raven Project Instructions

This repository is Raven itself: the reusable template library and installer for agentic coding guidance.

## Self-Test Workflow

- Use this repository as a live testbed for Raven installation and upgrade behavior.
- After changing template files, managed guidance, or `scripts/raven.py`, run `python scripts/self-check.py`.
- The self-check validates the installed shape, runs `upgrade --dry-run`, applies `upgrade`, then runs the unit tests.
- Treat unexpected self-upgrade output as a product issue unless the changed behavior was intentional.

## Upstream Template Maintenance

- Raven templates sometimes encode setup commands for third-party software, such as `mcp-language-server` and language servers.
- When editing those templates, validate the commands against the current upstream maintainer documentation before changing defaults.
- Treat stale third-party setup guidance as a Raven maintenance bug, even if the template still installs successfully.

## Local Instruction Boundary

- Project-specific instructions for maintaining Raven belong above the managed block in this file.
- The block between `RAVEN:BEGIN` and `RAVEN:END` is managed template content used to test safe block upgrades.
- Do not edit inside the managed block directly; update the source template instead.

<!-- RAVEN:BEGIN sha256=65171e1a745b5698ec892e5f61e5371b07d45c5b539995be5b2d00861165ced2 -->
# AGENTS.md

## Primary Objective

Be effective while preserving context. Prefer targeted retrieval, summaries, and deterministic tools over broad file reads.

## Canonical Context

- `AGENTS.md` is the authoritative root instruction file.
- `.agents/skills/` is the canonical location for reusable skills.
- Agent-specific skill paths, such as `.claude/skills`, should point to `.agents/skills` instead of duplicating content.
- When a `raven-*` skill and a generic skill cover the same intent (commit, review, tests, debugging), prefer the `raven-*` skill — it encodes this project's specific guardrails.
- Use `.claude/docs/raven-authority-map.md` to distinguish canonical source-of-truth context from non-canonical plans, notes, and history.
- Use `.claude/docs/raven-guardrails.md` to understand deterministic, procedural, instructional, and manual guardrails.
- Use `.claude/docs/raven-coding-principles.md` for shared coding-quality principles that apply across languages.
- Use `.claude/docs/raven-namespace.md` to understand which files are Raven-owned.
- Use `.claude/docs/raven-agent-compatibility.md` to understand canonical Raven files versus Claude and Codex adapter files.
- Use `.claude/docs/raven-lsp-mcp.md` for Raven's default LSP-over-MCP bridge recommendation and language-server defaults.
- If another tool inserts its own managed block in `AGENTS.md`, treat that block as authoritative for that tool's invocation commands, tool syntax, and resource names — not as an override of the workflow guardrails in this file.

## Retrieval Discipline

Use the cheapest adequate source before reading full files.

| Need | First tool |
|---|---|
| Exact string, symbol, config key, or error | `rg` |
| File discovery by name, type, or extension | `fd` |
| Unknown implementation location but clear intent | Semble |
| Definition, references, type info, diagnostics | LSP |
| Architecture or blast-radius question | repo-configured code intelligence, such as GitNexus if present |
| Syntax-aware pattern or mechanical rewrite | ast-grep or Semgrep |
| Build, test, or log output | RTK-wrapped shell command |

- Batch independent reads, searches, and inspections in a single turn.
- Skeleton-first: for a large or unfamiliar file, get a symbol map (LSP document symbols, or `ast-grep`/`rg` for definitions) before reading, then read only the ranges you need. Read a full file only when it is small or the whole structure matters, not as a first discovery step.
- Return concise findings before editing. Avoid pasting raw command output unless essential.
- Semble is for conceptual discovery — not exhaustive proof and not sufficient for an edit decision on its own. Verify with `rg`, LSP, targeted reads, or tests before changing code.
- If two literal `rg` guesses miss, switch to Semble rather than iterating term variations.
- Stop when two or more appropriate tools have failed to locate a credible file, symbol, or integration point. Summarize what was tried and delegate per the Delegation section, or ask the user.
- If a tool named above is not installed, fall back to `rg` plus targeted reads and flag the missing capability per Tool Availability Memory.

## Delegation

Delegate or ask when the scope of a task exceeds what targeted retrieval can resolve in the main context.

When to delegate:

- An architecture or "how does X work" question would take many retrieval steps to answer directly.
- The expected output is noisy relative to what the main context needs — large diffs, long logs, or many candidate files where only a summary or a few facts matter.
- The work is a specialized audit with its own checklist, such as a security review, test coverage analysis, or type design review.

How to delegate:

- Frame the task as a self-contained question: state the goal, what has already been ruled out, and the expected output shape (a list of files, a yes/no with evidence, a root-cause summary).
- Do not pass the full conversation history — delegation should reduce context, not duplicate it.
- If no delegation mechanism is available, pause and ask the user instead of expanding retrieval indefinitely.

Platform notes:

- Claude Code: use the Agent tool with an appropriate subagent type, or a project-defined subagent if one matches the audit.
- Other harnesses: fall back to asking the user to scope the task further, or use any equivalent delegation mechanism the harness provides.

## Shell Command Policy

Use RTK for commands likely to produce noisy output:

- tests and builds
- package managers
- large diffs or recursive listings
- cloud CLIs
- Docker and Kubernetes commands

Prefer `jq`/`yq` for reading or transforming structured JSON/YAML instead of `grep`/`sed`/`awk`.

Do not use RTK when exact raw output matters, such as reviewing a small precise diff, inspecting generated code, diagnosing compression-sensitive compiler output, or doing a security-sensitive review.

## Pause And Ask

Pause and ask before work that is ambiguous or could create durable harm:

- public API, schema, migration, compatibility, or release behavior changes
- auth/authz, secret handling, destructive operations, filesystem deletion, or network exposure
- dependency additions, license-sensitive code, vendored code, or generated artifacts
- broad refactors, cross-module architecture changes, or unclear scope boundaries
- any task where the safe behavior depends on product intent the repo does not make clear

## Editing Rules

- Make minimal patches.
- Before changing public APIs, use LSP references and any authoritative repo-configured impact-analysis guidance.
- Before large mechanical edits, use ast-grep or Semgrep.
- Run the narrowest relevant test first.
- If tests fail, inspect only failing output first.

## Verification State

- If you lose track of what was verified, re-verify before editing further or claiming completion.
- Do not claim broad success from narrow checks; state exactly what ran and what remains unverified.
- After context compaction or a long interruption, restate the current goal and verified state before continuing risky edits.

## Safety Rules

- Do not run destructive commands without explicit approval.
- Do not modify secrets, credentials, generated files, lockfiles, or migrations unless required.
- Do not add dependencies without explaining why.
- Never hide uncertainty; state confidence and unresolved assumptions.

## Platform Awareness

- Prefer portable commands and hooks when guidance is shared across macOS, Linux, native Windows, and WSL.
- On Windows, account for PowerShell/CMD path behavior and whether the project is running natively or inside WSL.
- Treat optional tools in `.mcp.json` as locally configured capabilities, not guaranteed dependencies.

## Tool Availability Memory

- When recommended tools matter, use the `raven-tool-bootstrap` skill.
- Record verified tool availability in local user memory outside the repository.
- If recommended tools are missing, ask whether to install them, provide instructions, remind later, or stop reminding.
- Do not install tools or suppress future reminders without explicit user approval.
- If a SessionStart hook reports missing or unverified tools, pause and ask the user how to proceed before relying on those optional tools.
<!-- RAVEN:END -->

<!-- gitnexus:start -->
# GitNexus — Code Intelligence

This project is indexed by GitNexus as **raven** (1883 symbols, 3382 relationships, 92 execution flows). Use the GitNexus MCP tools to understand code, assess impact, and navigate safely.

> Index stale? Run `node .gitnexus/run.cjs analyze` from the project root — it auto-selects an available runner. No `.gitnexus/run.cjs` yet? `npx gitnexus analyze` (npm 11 crash → `npm i -g gitnexus`; #1939).

## Always Do

- **MUST run impact analysis before editing any symbol.** Before modifying a function, class, or method, run `impact({target: "symbolName", direction: "upstream"})` and report the blast radius (direct callers, affected processes, risk level) to the user.
- **MUST run `detect_changes()` before committing** to verify your changes only affect expected symbols and execution flows. For regression review, compare against the default branch: `detect_changes({scope: "compare", base_ref: "main"})`.
- **MUST warn the user** if impact analysis returns HIGH or CRITICAL risk before proceeding with edits.
- When exploring unfamiliar code, use `query({query: "concept"})` to find execution flows instead of grepping. It returns process-grouped results ranked by relevance.
- When you need full context on a specific symbol — callers, callees, which execution flows it participates in — use `context({name: "symbolName"})`.

## Never Do

- NEVER edit a function, class, or method without first running `impact` on it.
- NEVER ignore HIGH or CRITICAL risk warnings from impact analysis.
- NEVER rename symbols with find-and-replace — use `rename` which understands the call graph.
- NEVER commit changes without running `detect_changes()` to check affected scope.

## Resources

| Resource | Use for |
|----------|---------|
| `gitnexus://repo/raven/context` | Codebase overview, check index freshness |
| `gitnexus://repo/raven/clusters` | All functional areas |
| `gitnexus://repo/raven/processes` | All execution flows |
| `gitnexus://repo/raven/process/{name}` | Step-by-step execution trace |

## CLI

| Task | Read this skill file |
|------|---------------------|
| Understand architecture / "How does X work?" | `.claude/skills/gitnexus/gitnexus-exploring/SKILL.md` |
| Blast radius / "What breaks if I change X?" | `.claude/skills/gitnexus/gitnexus-impact-analysis/SKILL.md` |
| Trace bugs / "Why is X failing?" | `.claude/skills/gitnexus/gitnexus-debugging/SKILL.md` |
| Rename / extract / split / refactor | `.claude/skills/gitnexus/gitnexus-refactoring/SKILL.md` |
| Tools, resources, schema reference | `.claude/skills/gitnexus/gitnexus-guide/SKILL.md` |
| Index, status, clean, wiki CLI commands | `.claude/skills/gitnexus/gitnexus-cli/SKILL.md` |

<!-- gitnexus:end -->
