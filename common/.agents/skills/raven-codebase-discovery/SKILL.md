---
name: raven-codebase-discovery
description: Use when locating where behavior lives, mapping a feature, or answering architecture questions before editing.
---

# Codebase Discovery

Goal: find the smallest sufficient context.

## Skip When

- The relevant file, symbol, or exact edit location was already provided.
- The task is a small local edit that does not require architecture or ownership discovery.

## Required Constraints

- Batch independent reads, searches, and inspections when possible.
- Do not read many full files before targeted retrieval.
- Do not use Semble for exhaustive proof that something does not exist.
- Verify Semble candidates with `rg`, LSP, targeted file reads, or tests before treating them as facts.
- Return only relevant files, symbols, relationships, confidence, and unresolved questions.
- Stop when targeted retrieval fails; delegate or pause rather than continuing to expand context.

## Process

1. Restate the behavior being located.
2. If exact terms are known, use `rg`.
3. If location is unknown, use Semble with a natural-language query for a single targeted lookup.
4. For promising symbols, use LSP definition and references.
5. For conceptual/flow questions ("how does X work?"), use `gitnexus_query` if a code-intelligence index is configured. For change impact, use `gitnexus_impact`.
6. Read only the smallest relevant ranges.

## When To Stop

Targeted retrieval has failed when two or more appropriate tools or queries have not found a credible file, symbol, owner, or integration point; when promising candidates lead to unrelated code; or when the next step would require broad full-file reading without a clear target.

When that happens, stop and report:

- what behavior or question you were trying to locate
- which tools or queries were already tried
- the best candidate paths or symbols, if any
- the unresolved question blocking progress

Then delegate per AGENTS.md Delegation guidance, or pause and ask the user if no delegation mechanism is available. For a broad mapping question, hand off to the `raven-codebase-cartographer` subagent with a scoped brief: the behavior or question to locate, the tools or queries already tried, and the best candidate paths so far.

## Broad Exploration

For architecture or "how does X work" questions that would need multiple queries to answer — not a single symbol lookup:

- If a code-intelligence index is configured (e.g. GitNexus), use `gitnexus_query` first — it returns execution flows and process-grouped results in a single call. Results are richer if the index was built with `--embeddings`.
- Otherwise delegate to the `semble-search` subagent (Claude Code) or fall back to direct Semble queries.

Verify all candidates the same way: `rg`, LSP, targeted reads, or tests before treating them as facts.
