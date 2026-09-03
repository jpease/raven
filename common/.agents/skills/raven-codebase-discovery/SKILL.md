---
name: raven-codebase-discovery
description: Use when locating where behavior lives, mapping a feature, or answering architecture questions before editing.
---

# Codebase Discovery

Goal: find the smallest sufficient context.

## Skip When

- The relevant file, symbol, or exact edit location was already provided.
- The task is a small local edit that does not require architecture or ownership discovery.

AGENTS.md Retrieval Discipline already governs tool order, batching, skeleton-first reading, and verifying a semantic hit before acting on it. This skill adds only what is specific to discovery.

## Required Constraints

- Do not use a semantic or index query for exhaustive proof that something does not exist. `rg` is what proves absence.
- Return only relevant files, symbols, relationships, confidence, and unresolved questions.

## Process

1. Restate the behavior being located.
2. If exact terms are known, use `rg`.
3. If location is unknown, use `mcp__gitnexus__query` for a single targeted natural-language lookup. With no index configured, see Broad Exploration below.
4. For promising symbols, use LSP definition and references.
5. For conceptual/flow questions ("how does X work?"), use `mcp__gitnexus__query` if a code-intelligence index is configured. For change impact, use `mcp__gitnexus__impact`.
6. Read only the smallest relevant ranges.

## When To Stop

Apply the AGENTS.md stop rule. Discovery also counts as failed when promising candidates lead to unrelated code, or when the next step would require broad full-file reading without a clear target.

Report what you were trying to locate, what was tried, the best candidate paths, and the unresolved question. Then delegate per AGENTS.md Delegation guidance, or pause and ask if no delegation mechanism is available. For a broad mapping question, hand off to the `raven-codebase-cartographer` subagent with that same brief.

## Tool Notes

- `rg` is recursive by default; never pass `-r` for recursion. `-r` is ripgrep's `--replace` and takes an argument, unlike grep's `-r`.
- `rg`, `fd`, and `ast-grep` skip dot-directories by default. Raven's `.ignore` re-admits `.agents/`, `.claude/`, `.codex/`, and `.raven/` in a tree Raven installed into. Elsewhere, an empty result proves nothing until you re-run with `--hidden` (`--no-ignore hidden` for ast-grep) or `git grep`.
- Run ast-grep by full name as `ast-grep --lang <lang> -p '<pattern>'`, never the `sg` alias. An empty result is not absence until `--debug-query=ast` shows the pattern parsed as intended.
- GitNexus tools are spelled `mcp__gitnexus__<tool>`. Vendor-generated GitNexus content uses shorter labels (`impact()`, `gitnexus_query`) for the same tools; take parameter names from the tool schema, not from prose. Without an MCP grant, a subagent with Bash reaches the same operations through the CLI: `gitnexus query|context|impact|trace|detect-changes`.

## Broad Exploration

For architecture or "how does X work" questions that would need multiple queries to answer — not a single symbol lookup:

- If a code-intelligence index is configured (e.g. GitNexus), use `mcp__gitnexus__query` first — it returns execution flows and process-grouped results in a single call. Results are richer if the index was built with `--embeddings`.
- With no index configured, widen `rg` instead: search for the domain nouns and error strings the feature would use, not just the identifier you first guessed. If two such passes miss, hand off to the `raven-codebase-cartographer` subagent rather than continuing to guess terms.
