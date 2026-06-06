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

## Process

1. Restate the behavior being located.
2. If exact terms are known, use `rg`.
3. If location is unknown, use Semble with a natural-language query.
4. For promising symbols, use LSP definition and references.
5. If change impact matters, use GitNexus.
6. Read only the smallest relevant ranges.
