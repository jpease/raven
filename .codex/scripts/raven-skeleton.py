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
from dataclasses import dataclass

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

# Languages whose declarations cannot be expressed as a node-kind union use an
# ast-grep YAML structural rule instead, run via ``ast-grep scan``. Elixir's
# def/defp/defmodule/defmacro are `call` nodes indistinguishable from ordinary
# calls by --kind; they are isolated by constraining the call's target
# identifier. Verified against ast-grep 0.43.0 and exercised by a golden test.
STRUCTURAL_RULES: dict[str, str] = {
    "elixir": (
        "id: raven-elixir-defs\n"
        "language: elixir\n"
        "rule:\n"
        "  kind: call\n"
        "  has:\n"
        "    field: target\n"
        '    regex: "^(defmodule|defmacrop|defmacro|defp|def)$"\n'
    ),
}

# Languages that get a SUPPLEMENTAL ast-grep structural query in addition to
# their --kind query (see NODE_KINDS above). TS/JS/TSX top-level
# arrow-function and function-expression `const`/`let` declarations
# (`export const f = () => {...}`) are not covered by any node-kind union --
# adding `lexical_declaration` wholesale to NODE_KINDS would also match every
# ordinary `const x = 42`, flooding the symbol map. Instead this rule matches
# only lexical/variable declarations whose initializer is itself a function
# (arrow or function-expression), and its rows are merged with the --kind
# rows in astgrep_skeleton. Verified against ast-grep 0.44.1 and exercised by
# golden tests (issue #110).
LEXICAL_FUNCTION_LANGS: frozenset[str] = frozenset({"typescript", "tsx", "javascript"})


def lexical_function_rule(language: str) -> str | None:
    """Return the supplemental ast-grep YAML rule that matches function-valued
    `const`/`let` declarations for ``language``, or None when the language has
    no such supplement."""
    if language not in LEXICAL_FUNCTION_LANGS:
        return None
    return (
        "id: raven-lexical-fn-decls\n"
        f"language: {language}\n"
        "rule:\n"
        "  any:\n"
        "    - kind: lexical_declaration\n"
        "      has:\n"
        "        kind: variable_declarator\n"
        "        has:\n"
        "          field: value\n"
        "          any:\n"
        "            - kind: arrow_function\n"
        "            - kind: function_expression\n"
        "    - kind: variable_declaration\n"
        "      has:\n"
        "        kind: variable_declarator\n"
        "        has:\n"
        "          field: value\n"
        "          any:\n"
        "            - kind: arrow_function\n"
        "            - kind: function_expression\n"
    )


def detect_language(path: str) -> str | None:
    """Map a file path to an ast-grep language name by extension, or None."""
    _, ext = os.path.splitext(path)
    return LANGUAGE_BY_EXTENSION.get(ext.lower())


def node_kinds(language: str) -> list[str]:
    """Return the declaration node kinds for a language, or [] if the ast-grep
    backend handles it with a structural rule instead (or not at all)."""
    return NODE_KINDS.get(language, [])


def astgrep_rule(language: str) -> str | None:
    """Return the ast-grep YAML structural rule for a language, or None when the
    language is handled by the node-kind table (or unsupported)."""
    return STRUCTURAL_RULES.get(language)


def astgrep_supports(language: str) -> bool:
    """Whether the ast-grep backend can skeletonize a language -- via either the
    node-kind table or a structural rule."""
    return bool(node_kinds(language)) or astgrep_rule(language) is not None


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
    binary = astgrep_binary()
    if binary is None:
        return None

    rule = astgrep_rule(language)
    if rule is not None:
        command = [binary, "scan", "--inline-rules", rule, "--json=stream", "--", path]
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            return None
        rows = parse_astgrep_stream(result.stdout)
    else:
        kinds = node_kinds(language)
        if not kinds:
            return None
        command = [
            binary,
            "run",
            "--lang",
            language,
            "--kind",
            ",".join(kinds),
            "--json=stream",
            "--",
            path,
        ]
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        # ``ast-grep run`` follows the grep/rg convention: exit 1 means "ran
        # fine, zero matches" (verified against ast-grep 0.44.1), not an
        # error -- only other codes (e.g. an invalid --kind) are real
        # failures. Treating 1 as fatal would wrongly discard the primary
        # tier's (empty) result before the lexical-function supplement below
        # ever runs, degrading all-arrow-function files to the ctags/rg tier.
        if result.returncode not in (0, 1):
            return None
        rows = parse_astgrep_stream(result.stdout)

    # Supplement TS/JS/TSX with function-valued lexical/variable
    # declarations (arrow functions, function expressions) that no --kind
    # union can select without also matching ordinary constants. Best
    # effort: if the supplemental scan fails for any reason, keep the
    # primary rows rather than lose them.
    supplement_rule = lexical_function_rule(language)
    if supplement_rule is not None:
        supplement_command = [
            binary,
            "scan",
            "--inline-rules",
            supplement_rule,
            "--json=stream",
            "--",
            path,
        ]
        supplement_result = subprocess.run(
            supplement_command, capture_output=True, text=True, check=False
        )
        if supplement_result.returncode == 0:
            rows = rows + parse_astgrep_stream(supplement_result.stdout)

    return sort_rows(rows)


def ctags_binary() -> str | None:
    """Resolve an executable that is genuinely **Universal** Ctags with JSON
    support. BSD ctags (the default ``/usr/bin/ctags`` on macOS) and Exuberant
    Ctags lack the ``end`` field this backend depends on, so they are rejected.
    """
    binary = shutil.which("ctags")
    if binary is None:
        return None
    try:
        version = subprocess.run([binary, "--version"], capture_output=True, text=True, check=False)
        if "Universal Ctags" not in version.stdout:
            return None
        features = subprocess.run(
            [binary, "--list-features"], capture_output=True, text=True, check=False
        )
    except OSError:
        return None
    if "json" not in features.stdout:
        return None
    return binary


def parse_ctags_json(text: str, source_lines: list[str]) -> list[dict]:
    """Parse Universal Ctags JSON-Lines output into sorted rows. This is the
    *exact* fallback tier: a tag is kept only when it carries both an integer
    ``line`` and an integer ``end`` (the scope boundary). Tags without ``end``
    cannot yield an exact range and are dropped. The header is read from the
    source so it matches the ast-grep tier's "first line of the declaration"."""
    rows: list[dict] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            tag = json.loads(line)
        except json.JSONDecodeError:
            continue
        if tag.get("_type") != "tag":
            continue
        start = tag.get("line")
        end = tag.get("end")
        if not isinstance(start, int) or isinstance(start, bool):
            continue
        if not isinstance(end, int) or isinstance(end, bool):
            continue
        header = source_lines[start - 1].strip() if 1 <= start <= len(source_lines) else ""
        rows.append({"start_line": start, "end_line": end, "header": header})
    return sort_rows(rows)


def ctags_skeleton(path: str, language: str | None = None) -> list[dict] | None:
    """Generate a skeleton with Universal Ctags. Returns ``None`` when the
    language is undetectable or no Universal Ctags binary is available -- the
    signal to fall through to the degraded backend."""
    language = language or detect_language(path)
    if language is None:
        return None
    binary = ctags_binary()
    if binary is None:
        return None
    result = subprocess.run(
        [
            binary,
            "--options=NONE",
            "--output-format=json",
            "--fields=+{line}{end}{kind}{scope}{signature}",
            "--extras=-p",
            "-o",
            "-",
            "--",
            path,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            source_lines = handle.read().splitlines()
    except OSError:
        return None
    return parse_ctags_json(result.stdout, source_lines)


# Language -> declaration-start regex for the degraded ``rg`` tier. These locate
# where declarations begin; they cannot recover block boundaries, so ranges are
# inferred (next start - 1) and labelled approximate. Methods are intentionally
# omitted -- one portable regex cannot track indentation or brace nesting.
RG_DECLARATION_PATTERNS: dict[str, str] = {
    "python": r"^\s*(async\s+def|def|class)\s+\w+",
    "typescript": (
        r"^\s*(export\s+)?(default\s+)?(declare\s+)?(abstract\s+)?(async\s+)?"
        r"(function|class|interface|type|enum|namespace)\s+[A-Za-z_$][\w$]*"
        r"|^\s*(export\s+)?(const|let|var)\s+[A-Za-z_$][\w$]*\s*="
    ),
    "go": r"^\s*func\s+(\([^)]*\)\s*)?[A-Za-z_]\w*|^\s*type\s+[A-Za-z_]\w*",
    "rust": (
        r"^\s*(pub(\([^)]*\))?\s+)?(async\s+)?(unsafe\s+)?fn\s+\w+"
        r"|^\s*(pub(\([^)]*\))?\s+)?(struct|enum|trait|impl|mod)\b"
    ),
    "swift": (
        r"^\s*(public|private|internal|fileprivate|open)?\s*(final\s+)?"
        r"(func|class|struct|enum|protocol|extension|actor)\s+\w+"
    ),
    "lua": r"^\s*(local\s+)?function\b",
    "elixir": r"^\s*(defmodule|defmacrop|defmacro|defp|def)\s+\w+",
}
RG_DECLARATION_PATTERNS["tsx"] = RG_DECLARATION_PATTERNS["typescript"]
RG_DECLARATION_PATTERNS["javascript"] = RG_DECLARATION_PATTERNS["typescript"]


def rg_declaration_pattern(language: str) -> str | None:
    """Return the degraded-tier declaration regex for a language, or None."""
    return RG_DECLARATION_PATTERNS.get(language)


def parse_rg_matches(text: str, total_lines: int) -> list[dict]:
    """Turn ``rg --line-number --no-heading`` output (``<lineno>:<text>`` lines
    for a single file) into rows. Each declaration's end is inferred as the line
    before the next declaration start, with EOF for the last."""
    starts: list[tuple[int, str]] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        lineno_str, sep, content = line.partition(":")
        if not sep or not lineno_str.strip().isdigit():
            continue
        starts.append((int(lineno_str), content.strip()))
    starts.sort(key=lambda item: item[0])

    rows: list[dict] = []
    for index, (start_line, header) in enumerate(starts):
        end_line = starts[index + 1][0] - 1 if index + 1 < len(starts) else total_lines
        rows.append(
            {"start_line": start_line, "end_line": max(end_line, start_line), "header": header}
        )
    return rows


def _count_lines(path: str) -> int | None:
    try:
        with open(path, "rb") as handle:
            return sum(1 for _ in handle)
    except OSError:
        return None


def rg_skeleton(path: str, language: str | None = None) -> list[dict] | None:
    """Generate an approximate skeleton with ``rg`` declaration matching. The
    final degraded tier: returns ``None`` when the language has no pattern or
    ``rg`` is unavailable."""
    language = language or detect_language(path)
    if language is None:
        return None
    pattern = rg_declaration_pattern(language)
    if pattern is None:
        return None
    binary = shutil.which("rg")
    if binary is None:
        return None
    result = subprocess.run(
        [binary, "--line-number", "--no-heading", "-e", pattern, "--", path],
        capture_output=True,
        text=True,
        check=False,
    )
    # rg exits 1 when there are simply no matches; only >1 is a real error.
    if result.returncode not in (0, 1):
        return None
    total_lines = _count_lines(path)
    if total_lines is None:
        return None
    return parse_rg_matches(result.stdout, total_lines)


@dataclass
class Skeleton:
    """A generated skeleton plus provenance: which backend produced it and
    whether its ranges are approximate (true only for the degraded rg tier)."""

    rows: list[dict]
    backend: str
    approximate: bool = False


def generate_skeleton(path: str) -> Skeleton | None:
    """Run the backend ladder (ast-grep -> Universal Ctags -> rg) and return the
    first non-empty result. The empty-result sanity check is deliberate: a
    backend that runs but returns nothing is treated like an unavailable one, so
    an empty/bad skeleton degrades to the next tier instead of being emitted.
    Returns ``None`` when the language is unsupported or every tier comes up
    empty."""
    language = detect_language(path)
    if language is None:
        return None
    ladder = (
        ("ast-grep", astgrep_skeleton, False),
        ("ctags", ctags_skeleton, False),
        ("rg", rg_skeleton, True),
    )
    for backend, generate, approximate in ladder:
        rows = generate(path, language)
        if rows:
            return Skeleton(rows=rows, backend=backend, approximate=approximate)
    return None


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: raven-skeleton.py <file>", file=sys.stderr)
        return 2
    path = argv[0]
    if not os.path.isfile(path):
        print(f"error: no such file: {path}", file=sys.stderr)
        return 1

    skeleton = generate_skeleton(path)
    if skeleton is None:
        print(
            f"No skeleton available for {path} "
            "(no symbols found, unsupported language, or no backend available); "
            "read the file directly."
        )
        return 0

    print(
        f"Skeleton of {path} ({len(skeleton.rows)} symbols, via {skeleton.backend}). "
        "Read ranges with Read offset/limit:"
    )
    if skeleton.approximate:
        print("Approximate declaration ranges; AST generator unavailable.")
    print(format_skeleton(skeleton.rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
