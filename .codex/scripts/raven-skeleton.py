#!/usr/bin/env python3

"""Raven skeleton generator.

Produces a structural skeleton of a source file -- its declarations with exact
start/end line numbers -- so an agent can read only the ranges it needs instead
of the whole file. Self-contained on purpose: it depends only on the standard
library and an installed ``ast-grep`` binary, with degraded fallbacks.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys

# Extension -> ast-grep language name. Detection is intentionally broader than
# ast-grep support: a file may be detected (so the fallback ladder can handle it)
# even when the ast-grep backend has no node kinds for it (e.g. Elixir).
LANGUAGE_BY_EXTENSION: dict[str, str] = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".js": "javascript",
    ".jsx": "javascript",
    ".go": "go",
    ".rs": "rust",
    ".swift": "swift",
    ".lua": "lua",
    ".ex": "elixir",
    ".exs": "elixir",
}

# Language -> tree-sitter node kinds that represent top-level declarations.
# Verified against ast-grep 0.43.0; an invalid kind aborts the whole query, so
# this table is exercised end-to-end by the golden tests. Languages whose
# declarations cannot be expressed as a simple node-kind union (e.g. Elixir,
# where def/defp are `call` nodes) are deliberately omitted and fall through to
# the degraded backends.
NODE_KINDS: dict[str, list[str]] = {
    "python": ["function_definition", "class_definition"],
    "typescript": [
        "function_declaration",
        "class_declaration",
        "interface_declaration",
        "type_alias_declaration",
        "enum_declaration",
        "method_definition",
    ],
    "javascript": ["function_declaration", "class_declaration", "method_definition"],
    "go": ["function_declaration", "method_declaration", "type_declaration"],
    "rust": [
        "function_item",
        "struct_item",
        "enum_item",
        "trait_item",
        "impl_item",
        "mod_item",
    ],
    # tree-sitter-swift models struct/enum/extension under class_declaration.
    "swift": ["function_declaration", "class_declaration", "protocol_declaration"],
    "lua": ["function_declaration"],
}
# TSX shares TypeScript's declaration kinds.
NODE_KINDS["tsx"] = NODE_KINDS["typescript"]


def detect_language(path: str) -> str | None:
    """Map a file path to an ast-grep language name by extension, or None."""
    _, ext = os.path.splitext(path)
    return LANGUAGE_BY_EXTENSION.get(ext.lower())


def node_kinds(language: str) -> list[str]:
    """Return the declaration node kinds for a language, or [] if the ast-grep
    backend does not support it."""
    return NODE_KINDS.get(language, [])


def exclusive_range_to_lines(start: dict, end: dict) -> tuple[int, int]:
    """Convert an ast-grep zero-based, exclusive-end range to one-based
    inclusive ``(start_line, end_line)``.

    ast-grep follows tree-sitter's convention: positions are zero-based and the
    end position is exclusive. A block that visually ends on line N often
    reports its end as the start of line N+1 (column 0); that trailing line must
    not be counted.
    """
    start_line = start["line"] + 1
    if end["column"] == 0 and end["line"] > start["line"]:
        end_line = end["line"]
    else:
        end_line = end["line"] + 1
    return (start_line, end_line)


def _header(text: str) -> str:
    """First non-empty line of a matched declaration, stripped. With a --kind
    query ast-grep does not isolate the symbol name, so the declaration header
    is the most reliable, fragile-free label."""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def parse_astgrep_stream(text: str) -> list[dict]:
    """Parse ast-grep ``--json=stream`` output (one JSON match per line) into
    sorted ``{start_line, end_line, header}`` rows with one-based inclusive
    lines. Blank lines are ignored."""
    rows: list[dict] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        match = json.loads(line)
        rng = match["range"]
        start_line, end_line = exclusive_range_to_lines(rng["start"], rng["end"])
        rows.append(
            {
                "start_line": start_line,
                "end_line": end_line,
                "header": _header(match.get("text", "")),
            }
        )
    return rows


def sort_rows(rows: list[dict]) -> list[dict]:
    """Order rows by start line ascending, then by end line descending so a
    container (wider range) precedes the members it encloses. Exact duplicates
    are removed."""
    seen: set[tuple] = set()
    unique: list[dict] = []
    for row in rows:
        key = (row["start_line"], row["end_line"], row["header"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)
    unique.sort(key=lambda r: (r["start_line"], -r["end_line"]))
    return unique


def format_skeleton(rows: list[dict], max_symbols: int = 300) -> str:
    """Render rows as ``start-end<TAB>header`` lines, capped at ``max_symbols``
    with a trailing note when truncated."""
    lines = [f"{r['start_line']}-{r['end_line']}\t{r['header']}" for r in rows[:max_symbols]]
    remaining = len(rows) - max_symbols
    if remaining > 0:
        lines.append(f"... {remaining} more symbol(s) truncated")
    return "\n".join(lines)


def astgrep_binary() -> str | None:
    """Resolve the ast-grep executable. Always invoke it as ``ast-grep``; never
    ``sg``, which on some Linux systems is the unrelated ``setgroups`` utility."""
    return shutil.which("ast-grep")


def astgrep_skeleton(path: str, language: str | None = None) -> list[dict] | None:
    """Generate a skeleton for ``path`` using ast-grep.

    Returns sorted ``{start_line, end_line, header}`` rows, or ``None`` when the
    language is unsupported by the ast-grep backend or the binary is missing --
    the signal for the caller to fall through to a degraded backend.
    """
    language = language or detect_language(path)
    if language is None:
        return None
    kinds = node_kinds(language)
    if not kinds:
        return None
    binary = astgrep_binary()
    if binary is None:
        return None

    result = subprocess.run(
        [binary, "run", "--lang", language, "--kind", ",".join(kinds), "--json=stream", "--", path],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    return sort_rows(parse_astgrep_stream(result.stdout))


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: raven-skeleton.py <file>", file=sys.stderr)
        return 2
    path = argv[0]
    if not os.path.isfile(path):
        print(f"error: no such file: {path}", file=sys.stderr)
        return 1

    rows = astgrep_skeleton(path)
    if rows is None:
        print(
            f"No skeleton available for {path} "
            "(unsupported language or ast-grep unavailable); read the file directly."
        )
        return 0
    if not rows:
        print(f"No top-level symbols found in {path}.")
        return 0

    print(f"Skeleton of {path} ({len(rows)} symbols). Read ranges with Read offset/limit:")
    print(format_skeleton(rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
