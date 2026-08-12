---
name: raven-codebase-discovery
description: Use when locating where behavior lives, mapping a feature, or answering architecture questions before editing.
---

# Codebase Discovery

Goal: find the smallest sufficient context.

## Skip When

- The relevant file, symbol, or exact edit location was already provided.
- The task is a small local edit that does not require architecture or ownership discovery.

AGENTS.md Retrieval Discipline already governs tool order, batching, skeleton-first reading, and Semble verification. This skill adds only what is specific to discovery.

## Required Constraints

- Do not use Semble for exhaustive proof that something does not exist.
- Return only relevant files, symbols, relationships, confidence, and unresolved questions.

## Process

1. Restate the behavior being located.
2. If exact terms are known, use `rg`.
3. If location is unknown, use Semble with a natural-language query for a single targeted lookup.
4. For promising symbols, use LSP definition and references.
5. For conceptual/flow questions ("how does X work?"), use `mcp__gitnexus__query` if a code-intelligence index is configured. For change impact, use `mcp__gitnexus__impact`.
6. Read only the smallest relevant ranges.

## When To Stop

Apply the AGENTS.md stop rule. Discovery also counts as failed when promising candidates lead to unrelated code, or when the next step would require broad full-file reading without a clear target.

Report what you were trying to locate, what was tried, the best candidate paths, and the unresolved question. Then delegate per AGENTS.md Delegation guidance, or pause and ask if no delegation mechanism is available. For a broad mapping question, hand off to the `raven-codebase-cartographer` subagent with that same brief.

## Broad Exploration

For architecture or "how does X work" questions that would need multiple queries to answer — not a single symbol lookup:

- If a code-intelligence index is configured (e.g. GitNexus), use `mcp__gitnexus__query` first — it returns execution flows and process-grouped results in a single call. Results are richer if the index was built with `--embeddings`.
- Otherwise delegate to the `semble-search` subagent (Claude Code) or fall back to direct Semble queries.
