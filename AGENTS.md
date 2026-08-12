# Raven Project Instructions

This repository is Raven itself: the reusable template library and installer for agentic coding guidance.

## Self-Test Workflow

- Use this repository as a live testbed for Raven installation and upgrade behavior.
- After changing template files, managed guidance, or `scripts/raven.py`, run `uv run --group dev python scripts/self-check.py` (the documented dev environment — see "Developing Raven" in `README.md`).
- The self-check validates the installed shape, runs `upgrade --dry-run`, applies `upgrade`, then runs the unit tests.
- Treat unexpected self-upgrade output as a product issue unless the changed behavior was intentional.

## Upstream Template Maintenance

- Raven templates sometimes encode setup commands for third-party software, such as `mcp-language-server` and language servers.
- When editing those templates, validate the commands against the current upstream maintainer documentation before changing defaults.
- Treat stale third-party setup guidance as a Raven maintenance bug, even if the template still installs successfully.

## Public Repository Hygiene

- This repository is public. Everything committed here — including `docs/superpowers/` specs and plans — is world-readable.
- Dogfooding and downstream validation happen in private repos. Refer to them by role, never by name: "a private iOS app repo", "the #60 reporter", "a downstream Node consumer".
- Do not commit local absolute paths. Write repro steps as `cd <downstream-repo> && raven doctor`, not `cd /Users/<name>/Developer/...`.
- This matters most in specs and plans, which are written during dogfooding — exactly when naming the real test repo is the natural thing to type.
- Before committing docs that reference downstream validation, grep the diff for private repo names and `/Users/`. Keep the name list in local memory or `.git/info/exclude`d config; putting it in a tracked file recreates the leak.

## Local Instruction Boundary

- Project-specific instructions for maintaining Raven belong above the managed block in this file.
- The block between `RAVEN:BEGIN` and `RAVEN:END` is managed template content used to test safe block upgrades.
- Do not edit inside the managed block directly; update the source template instead.

<!-- RAVEN:BEGIN sha256=1b9ed74e3d0b2325f8b4c737468de967574a803124480d864f23756039628c8c -->
# AGENTS.md

## Primary Objective

Be effective while preserving context. Prefer targeted retrieval, summaries, and deterministic tools over broad file reads.

## Canonical Context

- `AGENTS.md` is the authoritative root instruction file.
- `.agents/skills/` is the canonical location for reusable skills.
- Agent-specific skill paths (e.g. `.claude/skills`) should point to `.agents/skills`, not duplicate content.
- When a `raven-*` skill and a generic skill cover the same intent, prefer the `raven-*` one — it encodes this project's guardrails.
- Deeper guidance lives in `.claude/docs/`: `raven-authority-map` (canonical vs non-canonical context), `raven-guardrails` (guardrail types), `raven-coding-principles` (cross-language quality), `raven-namespace` (Raven-owned files), `raven-agent-compatibility` (canonical vs Claude/Codex adapters), `raven-lsp-mcp` (LSP-over-MCP and language-server defaults), `raven-antipatterns` (repo-specific recurring-issue registry).
- If another tool inserts a managed block in `AGENTS.md`, treat it as authoritative for that tool's commands, syntax, and resource names — not as an override of these workflow guardrails.

## Retrieval Discipline

Use the cheapest adequate source before reading full files.

| Need | First tool |
|---|---|
| Exact string, symbol, config key, or error | `rg` |
| File discovery by name, type, or extension | `fd` |
| Unknown implementation location but clear intent | Semble |
| Definition, references, type info, diagnostics | LSP |
| "How does X work?" / conceptual flow discovery | `mcp__gitnexus__query` |
| Blast-radius before editing a symbol | `mcp__gitnexus__impact` |
| Syntax-aware pattern or mechanical rewrite | ast-grep or Semgrep |
| Build, test, or log output | RTK-wrapped shell command |

- `rg` is recursive by default; never pass `-r` for recursion. `-r` is ripgrep's `--replace` and takes an argument — unlike grep's `-r`, which means `--recursive`.
- Batch independent reads, searches, and inspections per turn.
- Skeleton-first: for a large or unfamiliar file, get a symbol map (LSP document symbols, or `ast-grep`/`rg`) before reading, then read only the ranges you need — read a full file only when it is small or the whole structure matters.
- Return concise findings before editing.
- Semble is for conceptual discovery — switch to it when two literal `rg` guesses miss, rather than iterating term variations. It is not proof: verify with `rg`, LSP, targeted reads, or tests before changing code.
- When a code-intelligence index is configured, prefer `mcp__gitnexus__query` over Semble for "how does X work" and flow-based questions — it returns execution paths grouped by process, not just file locations.
- GitNexus tools are spelled `mcp__gitnexus__<tool>`. Vendor-generated GitNexus content uses shorter labels (`impact()`, `gitnexus_query`) for the same tools — read them as the MCP tools, and take parameter names from the tool schema, not from the skill prose. No MCP grant? A subagent with Bash but no MCP access can reach the same operations via the CLI: `gitnexus query|context|impact|trace|detect-changes`.
- Stop when two or more appropriate tools have failed to locate a credible file, symbol, or integration point. Summarize what was tried and delegate per the Delegation section, or ask the user.
- Tool availability comes from the session capability roster. If no roster is present, probe before relying on any non-baseline tool. MCP servers the roster lists as configured may still be unapproved or unconnected; a failed call is information, not a contradiction of the roster.
- When the repo configures a code-intelligence index (such as GitNexus), its impact analysis before a symbol edit and change-detection before a commit are mandatory, not optional table picks. If it is stale, reindex or say so — do not silently skip it.

## Delegation

Delegate or ask when the scope of a task exceeds what targeted retrieval can resolve in the main context. Use the `raven-delegate-or-inline` skill for the decision criteria, delegation mechanics, and anti-habit checks. Raven ships `raven-security-reviewer`, `raven-refactor-reviewer`, `raven-test-debugger`, and `raven-codebase-cartographer` as Claude Code subagents for common audits. Sub-agent returns must include an `## Out Of Scope Findings` section; disposition those findings per `raven-triage-discovery` rather than leaving them in chat or in an issue comment.

## Shell Command Policy

Use RTK for commands likely to produce noisy output:

- tests and builds
- package managers
- large diffs or recursive listings
- cloud CLIs
- Docker and Kubernetes commands

Prefer `jq`/`yq` over `grep`/`sed`/`awk` for structured JSON/YAML.

Do not use RTK when exact raw output matters — small precise diffs, generated code, compression-sensitive compiler output, or security-sensitive review.

## Pause And Ask

Pause and ask before work that is ambiguous or could create durable harm:

- public API, schema, migration, compatibility, or release behavior changes
- auth/authz, secret handling, destructive operations, filesystem deletion, or network exposure
- dependency additions, license-sensitive code, vendored code, or generated artifacts
- broad refactors, cross-module architecture changes, or unclear scope boundaries
- any task where the safe behavior depends on product intent the repo does not make clear

## Editing Rules

- Make minimal patches.
- Before changing public APIs, check references with LSP and repo-configured impact analysis.
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

- Prefer portable commands and hooks for guidance shared across macOS, Linux, Windows, and WSL.
- On Windows, account for PowerShell/CMD path behavior and native-vs-WSL execution.
- Treat `.mcp.json` tools as locally configured capabilities, not guaranteed dependencies.

## Tool Availability Memory

- When recommended tools matter, use the `raven-tool-bootstrap` skill.
- Record verified tool availability in local user memory outside the repository.
- If recommended tools are missing, ask whether to install them, provide instructions, remind later, or stop reminding.
- Do not install tools or suppress future reminders without explicit user approval.
- If a SessionStart hook reports missing or unverified tools, ask how to proceed before relying on them.
<!-- RAVEN:END -->

<!-- gitnexus:start -->
# GitNexus — Code Intelligence

This project is indexed by GitNexus as **raven** (2945 symbols, 6086 relationships, 141 execution flows). Use the GitNexus MCP tools to understand code, assess impact, and navigate safely.

> Index stale? Run `node .gitnexus/run.cjs analyze` from the project root — it auto-selects an available runner. No `.gitnexus/run.cjs` yet? `npx gitnexus analyze` (npm 11 crash → `npm i -g gitnexus`; #1939).

## Always Do

- **MUST run impact analysis before editing any symbol.** Before modifying a function, class, or method, run `impact({target: "symbolName", direction: "upstream"})` and report the blast radius (direct callers, affected processes, risk level) to the user.
- **MUST run `detect_changes()` before committing** to verify your changes only affect expected symbols and execution flows. For regression review, compare against the default branch: `detect_changes({scope: "compare", base_ref: "main"})`.
- **MUST warn the user** if impact analysis returns HIGH or CRITICAL risk before proceeding with edits.
- When exploring unfamiliar code, use `query({search_query: "concept"})` to find execution flows instead of grepping. It returns process-grouped results ranked by relevance.
- When you need full context on a specific symbol — callers, callees, which execution flows it participates in — use `context({name: "symbolName"})`.
- For security review, `explain({target: "fileOrSymbol"})` lists taint findings (source→sink flows; needs `analyze --pdg`).

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
