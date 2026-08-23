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
| Definition, references, type info, diagnostics | LSP |
| Third-party API shape or signature | LSP against the installed package |
| "How does X work?" / conceptual flow discovery | `mcp__gitnexus__query` |
| Blast-radius before editing a symbol | `mcp__gitnexus__impact` |
| Syntax-aware pattern or mechanical rewrite | ast-grep or Semgrep |
| Build, test, or log output | RTK-wrapped shell command |

- `rg` is recursive by default; never pass `-r` for recursion. `-r` is ripgrep's `--replace` and takes an argument — unlike grep's `-r`, which means `--recursive`.
- `rg` skips hidden files and directories by default. Raven's own content sits under `.agents/` and `.claude/`, so `rg pattern common/` finds nothing and reads as clean. Use `--hidden` or `git grep` when searching shipped guidance.
- Batch independent reads, searches, and inspections per turn.
- Skeleton-first: for a large or unfamiliar file, get a symbol map (LSP document symbols, or `ast-grep`/`rg`) before reading, then read only the ranges you need — read a full file only when it is small or the whole structure matters.
- Take a third-party API's shape from the installed version, not from memory. Confirm the symbol with LSP against the package in the environment before calling it — a name renamed a major ago still writes fluently from training and fails at runtime.
- Return concise findings before editing.
- When two literal `rg` guesses miss, switch tools rather than iterating term variations. `mcp__gitnexus__query` is the conceptual-discovery step where an index is configured — it returns execution paths grouped by process, not just file locations. It is not proof: verify with `rg`, LSP, targeted reads, or tests before changing code.
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
- Before offering to run a destructive command, check whether approval can lift the block. A hard deny cannot be granted in chat.
- Do not substitute an equivalent-effect command when a guardrail blocks one. A block denies the outcome, not the command string: report it and hand the command to the user.
- Do not modify secrets, credentials, generated files, lockfiles, or migrations unless required.
- Do not add dependencies without explaining why.
- Never hide uncertainty; state confidence and unresolved assumptions.
- Agreement is not helpfulness. Before ratifying a design, plan, or conclusion the user proposed, name the specific thing you would change, or state why you agree with it.

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
