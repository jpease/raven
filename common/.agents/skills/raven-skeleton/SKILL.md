---
name: raven-skeleton
description: Use before reading a large or unfamiliar source file. Get a symbol map (declarations with exact line ranges) first, then read only the ranges you need instead of the whole file.
---

# Skeleton-First Reads

Goal: spend context on the parts of a file that matter. For a large or unfamiliar
source file, get a structural skeleton first, then read only the ranges you need.
This implements the skeleton-first guidance in `AGENTS.md` Retrieval Discipline.

## Skip When

- The file is small, or the whole structure genuinely matters.
- The exact symbol and line range were already provided.
- You already need a specific known range — just read it directly.

## Process

1. Run the skeleton helper from your agent's scripts directory:
   - Claude Code: `python .claude/scripts/raven-skeleton.py <file>`
   - Codex: `python .codex/scripts/raven-skeleton.py <file>`

   It prints one declaration per line as `START-END<TAB>header`, for example:

   ```
   1-2	def top_function(x):
   5-7	class Greeter:
   6-7	def greet(self):
   ```

2. Pick the declarations you care about and read only their line ranges, e.g.
   `Read(file, offset=5, limit=3)` for `5-7`.

3. Read the full file only if the skeleton shows you genuinely need most of it.

## When No Skeleton Is Available

If the helper prints `No skeleton available ...` (no symbols found, unsupported
language, or no backend installed), fall back to reading the file directly. The
helper never blocks a read; it only offers a cheaper path.

## Approximate Ranges

If the output begins with `Approximate declaration ranges; AST generator
unavailable.`, the skeleton came from a degraded `rg` declaration scan: the start
lines are real but each end line is inferred (the line before the next
declaration). Treat the ranges as hints and read a little generously around them.

## Supported Languages

The helper tries a backend ladder and notes which tier produced the skeleton:

1. **ast-grep** (exact): Python, TypeScript/TSX, JavaScript, Go, Rust, Swift, Lua,
   and Elixir (via a structural rule). Needs an installed `ast-grep` binary.
2. **Universal Ctags** (exact): used when ast-grep is unavailable or finds nothing;
   requires genuine Universal Ctags with JSON support.
3. **`rg`** (approximate): a final degraded declaration scan; see Approximate
   Ranges above.

Languages outside these tiers fall through to the no-skeleton message.
