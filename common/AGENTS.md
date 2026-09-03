# AGENTS.md

## Primary Objective

Be effective while preserving context. Prefer targeted retrieval, summaries, and deterministic tools over broad file reads.

## Canonical Context

- `AGENTS.md` is the authoritative root instruction file.
- `.agents/skills/` is the canonical location for reusable skills.
- Agent-specific skill paths (e.g. `.claude/skills`) should point to `.agents/skills`, not duplicate content.
- When a `raven-*` skill and a generic skill cover the same intent, prefer the `raven-*` one — it encodes this project's guardrails.
- Deeper guidance lives in `.claude/docs/raven-*.md`: guardrails, authority map, coding principles, namespace, agent compatibility, LSP defaults, and the antipattern registry. Read one when its subject comes up.
- If another tool inserts a managed block in `AGENTS.md`, treat it as authoritative for that tool's commands, syntax, and resource names — not as an override of these workflow guardrails.

## Retrieval Discipline

Use the cheapest adequate source before reading full files.

| Need | First tool |
|---|---|
| Exact string, symbol, config key, or error | `rg` |
| File discovery by name, type, or extension | `fd` |
| Definition, references, type info, diagnostics | LSP |
| "How does X work?" / conceptual flow discovery | `mcp__gitnexus__query` |
| Blast-radius before editing a symbol | `mcp__gitnexus__impact` |
| Syntax-aware pattern or mechanical rewrite | ast-grep or Semgrep |
| Build, test, or log output | RTK-wrapped shell command |

- Batch independent reads, searches, and inspections per turn.
- Skeleton-first: for a large or unfamiliar file, get a symbol map (LSP document symbols, or `ast-grep`/`rg`) before reading, then read only the ranges you need — read a full file only when it is small or the whole structure matters.
- Return concise findings before editing.
- When two literal `rg` guesses miss, switch tools rather than iterating term variations; an index query is discovery, not proof, so verify with `rg`, LSP, or tests before changing code. Tool spellings, flags, and dot-directory caveats live in `raven-codebase-discovery`.
- Stop when two or more appropriate tools have failed to locate a credible file, symbol, or integration point. Summarize what was tried and delegate per the Delegation section, or ask the user.
- Tool availability comes from the session capability roster. If no roster is present, probe before relying on any non-baseline tool. An MCP server the roster lists may still be unapproved or unconnected; a failed call is information, not a contradiction of the roster.
- When the session roster lists a code-intelligence index, run its impact analysis before a symbol edit and its change-detection before a commit; say so if it is stale. No `Index` line means nothing to run: a configured MCP server is not an index.

## Skills

A skill costs a file read on Codex and a step on Claude Code, before any work starts. Invoke one for a task of several steps or when the user asks for it; a one-file change or a short paragraph needs none.

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

## Convergence

- A task ends in success, progression (one blocker removed, the next isolated with evidence), or stop. Progression is an acceptable end state; report it plainly.
- Stop and report when the same test has failed after three consecutive fixes aimed at it, when a fix needs code the task did not scope, or when the diff grows while the failing signal does not change.
- Do not keep patching once the work stops converging. Partial work leaves the codebase more legible than it was.
- `raven-task-complete` states the test for each of the three states; `raven-debug-failure`'s `When To Stop` covers the narrower case where ownership was never found.

## Safety Rules

- Do not run destructive commands without explicit approval.
- Before offering to run a destructive command, check whether approval can lift the block. A hard deny cannot be granted in chat.
- Do not substitute an equivalent-effect command when a guardrail blocks one. A block denies the outcome, not the command string: report it and hand the command to the user.
- Do not modify secrets, credentials, generated files, lockfiles, or migrations unless required.
- Do not add dependencies without explaining why.
- Never hide uncertainty; state confidence and unresolved assumptions.
- Agreement is not helpfulness. Before ratifying a design, plan, or conclusion the user proposed, name the specific thing you would change, or state why you agree with it.
- When offering options, lead with a recommendation and its one real trade-off; ask only when the choice is close.
- When you do ask, prefer a structured-choice prompt with a free-text escape hatch when the harness offers one; if only plain text is available, phrase it so a bare "yes" or "no" resolves unambiguously — never let one word plausibly answer two different clauses.
- When the roster reports a recommended tool missing, do not install it or silence the reminder without the user's say; `raven-tool-bootstrap` records their answer.
- Prefer portable commands and hooks; guidance is shared across macOS, Linux, Windows, and WSL.
