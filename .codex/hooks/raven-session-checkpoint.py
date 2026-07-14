#!/usr/bin/env python3
"""PreToolUse hook: validate raven-session.py --complete before allowing."""

from __future__ import annotations

import json
import re
import shlex
import subprocess
import sys
from pathlib import Path


def _load_payload() -> dict | None:  # type: ignore[type-arg]
    try:
        return json.load(sys.stdin)
    except Exception:
        return None


def _extract_command(payload: dict) -> str:  # type: ignore[type-arg]
    tool_input = payload.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        tool_input = {}
    return tool_input.get("command") or payload.get("command") or ""


def _is_codex_hook(payload: dict) -> bool:  # type: ignore[type-arg]
    return "hook_event_name" in payload or "tool_name" in payload


def _deny(message: str, payload: dict) -> int:  # type: ignore[type-arg]
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


def _enforcement_enabled() -> bool:
    """Whether the [lifecycle].checkpoint_enforcement assignment is active.

    Reads only the active boolean assignment of ``checkpoint_enforcement`` inside
    the ``[lifecycle]`` section. Comments, similarly named keys, and the key in
    other sections are ignored, so a commented or unrelated ``false`` never
    silently disables enforcement.

    Fail-safe: a missing config, an unreadable file, or a non-boolean value keeps
    enforcement enabled (returns True) and emits a diagnostic to stderr.
    """
    config = Path(".raven/config.toml")
    if not config.exists():
        return True
    try:
        text = config.read_text(encoding="utf-8")
    except OSError as exc:
        print(
            f"raven-session-checkpoint: cannot read {config} ({exc}); keeping enforcement enabled",
            file=sys.stderr,
        )
        return True
    section: str | None = None
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip()
            continue
        if section != "lifecycle" or "=" not in line:
            continue
        key, value = (part.strip() for part in line.split("=", 1))
        if key != "checkpoint_enforcement":
            continue
        if value == "true":
            return True
        if value == "false":
            return False
        print(
            "raven-session-checkpoint: [lifecycle].checkpoint_enforcement must be true or false, "
            f"got {value!r}; keeping enforcement enabled",
            file=sys.stderr,
        )
        return True
    return True


def _completion_unit(command: str) -> str | None:
    """Return the unit argument only for a genuine ``raven-session.py --complete``.

    A completion command must actually invoke the session CLI: some token's
    basename must be ``raven-session.py`` and a ``--complete`` token must be
    present. The unit is the token immediately following ``--complete``. Any
    other command — including one that merely mentions ``--complete`` — yields
    ``None`` so unrelated shell commands are allowed through untouched.

    Tokenizes with shell rules so a quoted unit name containing spaces survives
    intact, matching the positional argument the session CLI receives. Falls
    back to regexes only when the command is not validly quoted, so a malformed
    command still defers to the CLI's own validation.
    """
    try:
        tokens = shlex.split(command)
    except ValueError:
        if not re.search(r"(?:^|[\s/])raven-session\.py(?:\s|$)", command):
            return None
        m = re.search(r"--complete\s+(\S+)", command)
        return m.group(1) if m else None
    if not any(Path(token).name == "raven-session.py" for token in tokens):
        return None
    for i, token in enumerate(tokens):
        if token == "--complete":
            return tokens[i + 1] if i + 1 < len(tokens) else None
    return None


def main() -> int:
    payload = _load_payload()
    if payload is None:
        return 0

    command = _extract_command(payload)
    unit = _completion_unit(command)
    if not unit:
        return 0

    if not _enforcement_enabled():
        return 0

    if not Path(".raven/session.md").exists():
        return _deny("No active session. Run raven-session.py --init first.", payload)

    result = subprocess.run(
        [sys.executable, ".claude/scripts/raven-session.py", "--validate", unit],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        msg = result.stderr.strip() or result.stdout.strip() or f"Cannot complete unit '{unit}'"
        return _deny(msg, payload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
