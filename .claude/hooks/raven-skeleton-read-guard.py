#!/usr/bin/env python3

"""Raven skeleton-first read gate (rung 2).

A Claude Code ``PreToolUse`` hook for ``Read``. When enabled in
``.raven/config.toml``, it denies *unbounded* reads of large supported-language
files and points the agent at the ``raven-skeleton`` helper so it fetches a
symbol map and reads only the ranges it needs.

Opt-in and default off: absent or unset config means the gate never fires.
Self-contained: standard library only.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

DEFAULT_THRESHOLD = 500

# Extensions the raven-skeleton ast-grep backend can produce a skeleton for.
# Keep in sync with the languages raven-skeleton.py supports via ast-grep --
# its NODE_KINDS table plus STRUCTURAL_RULES (Elixir is handled by a structural
# rule). Gating an extension the helper cannot skeletonize would point the agent
# at a helper that returns nothing.
SUPPORTED_EXTENSIONS = {
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".go",
    ".rs",
    ".swift",
    ".lua",
    ".ex",
    ".exs",
}

_GATE_RE = re.compile(r"^\s*read_gate\s*=\s*true\b", re.IGNORECASE)
_THRESHOLD_RE = re.compile(r"^\s*read_gate_threshold_lines\s*=\s*(\d+)")


def parse_gate_config(text: str) -> tuple[bool, int]:
    """Parse the opt-in gate config from raw ``.raven/config.toml`` text.

    Returns ``(enabled, threshold)``. Default off with a default threshold; a
    line scan (no TOML parser) keeps the hook self-contained, matching the
    existing checkpoint hook. The threshold key shares the ``read_gate`` prefix,
    so the gate key is matched precisely to avoid enabling on the threshold line.
    """
    enabled = False
    threshold = DEFAULT_THRESHOLD
    for line in text.splitlines():
        if _GATE_RE.match(line):
            enabled = True
        match = _THRESHOLD_RE.match(line)
        if match:
            threshold = int(match.group(1))
    return (enabled, threshold)


def is_unbounded_read(tool_input: dict) -> bool:
    """A read with neither ``offset`` nor ``limit`` pulls the whole file."""
    return not tool_input.get("offset") and not tool_input.get("limit")


def should_gate(
    tool_input: dict,
    line_count: int,
    *,
    enabled: bool,
    threshold: int,
    supported: bool,
) -> bool:
    """Deny only when the gate is on, the file is a supported language, the read
    is unbounded, and the file is at least ``threshold`` lines. Everything else
    passes through."""
    if not enabled:
        return False
    if not supported:
        return False
    if not is_unbounded_read(tool_input):
        return False
    return line_count >= threshold


def is_supported(path: str) -> bool:
    _, ext = os.path.splitext(path)
    return ext.lower() in SUPPORTED_EXTENSIONS


def _line_count(path: str) -> int:
    with open(path, "rb") as handle:
        return sum(1 for _ in handle)


def _gate_config() -> tuple[bool, int]:
    config = Path(".raven/config.toml")
    if not config.exists():
        return (False, DEFAULT_THRESHOLD)
    return parse_gate_config(config.read_text(encoding="utf-8"))


def _load_payload() -> dict | None:
    try:
        return json.load(sys.stdin)
    except Exception:
        return None


def _is_codex_hook(payload: dict) -> bool:
    return "hook_event_name" in payload or "tool_name" in payload


def _deny(message: str, payload: dict) -> int:
    if _is_codex_hook(payload):
        print(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "deny",
                        "permissionDecisionReason": message,
                    }
                }
            )
        )
        return 0
    print(message, file=sys.stderr)
    return 2


def main() -> int:
    payload = _load_payload()
    if payload is None:
        return 0
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return 0

    enabled, threshold = _gate_config()
    if not enabled:
        return 0

    path = tool_input.get("file_path") or tool_input.get("path") or ""
    if not path or not is_supported(path) or not is_unbounded_read(tool_input):
        return 0
    if not os.path.isfile(path):
        return 0

    if not should_gate(
        tool_input,
        _line_count(path),
        enabled=enabled,
        threshold=threshold,
        supported=True,
    ):
        return 0

    return _deny(
        f"Skeleton-first read gate: {path} is large. Get a symbol map first with the "
        "raven-skeleton helper (.claude/scripts/raven-skeleton.py <file>), then Read only "
        "the ranges you need, or pass offset/limit for a bounded read. See the "
        "raven-skeleton skill.",
        payload,
    )


if __name__ == "__main__":
    raise SystemExit(main())
