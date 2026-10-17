"""Raven's own gate limits: which constants they are and how to read them.

Shared by `check-staged-relaxation.py`, which reports a limit moved the loose
way, and `check-prose.py`, which leaves a marker approving such a move out of
its marker budget: that marker's job ends with the commit that raises the
limit, after which the new value is the baseline.
"""

from __future__ import annotations

import ast

#: Constant name -> the direction that loosens it, by repo-relative file.
LIMIT_CONSTANTS: dict[str, dict[str, str]] = {
    "scripts/check-prose.py": dict.fromkeys(
        (
            "PARAGRAPH_WORDS",
            "DOC_WORDS",
            "SKILL_WORDS",
            "AGENTS_SECTION_WORDS",
            "COMMENT_BLOCK_LINES",
            "MARKER_BUDGET",
        ),
        "up",
    ),
    "scripts/self-check.py": {
        "THRESHOLDS": "up",
        "PROFILES": "up",
        "SKILL_DESCRIPTION_AGGREGATE_LIMIT": "up",
    },
    "evals/scenarios.py": {"FIXED_COST_OVERHEAD_CEILINGS": "up"},
    "scripts/eval.py": {"MIN_PUBLISHED_TRIALS": "down"},
}


def limit_values(text: str, names: dict[str, str]) -> dict[tuple[str, str], tuple[float, int]]:
    """(constant, key) -> (number, line) for every number a named constant holds.

    A plain number has key ""; a dict maps each key to its number, or to the
    first number of a tuple value (`PROFILES` holds `(budget, path)`).
    """
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return {}
    values: dict[tuple[str, str], tuple[float, int]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target, value = node.targets[0], node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            target, value = node.target, node.value
        else:
            continue
        if not isinstance(target, ast.Name) or target.id not in names:
            continue
        if isinstance(value, ast.Dict):
            items = [(k, v) for k, v in zip(value.keys, value.values) if k is not None]
            for key_node, item in items:
                if isinstance(item, ast.Tuple) and item.elts:
                    item = item.elts[0]
                if (
                    isinstance(key_node, ast.Constant)
                    and isinstance(item, ast.Constant)
                    and isinstance(item.value, (int, float))
                ):
                    values[(target.id, str(key_node.value))] = (item.value, item.lineno)
        elif isinstance(value, ast.Constant) and isinstance(value.value, (int, float)):
            values[(target.id, "")] = (value.value, value.lineno)
    return values


def limit_lines(path: str, text: str) -> set[int]:
    """1-based lines of `text` that hold a limit value, if `path` is a limit file."""
    names = LIMIT_CONSTANTS.get(path)
    if names is None:
        return set()
    return {line for _value, line in limit_values(text, names).values()}
