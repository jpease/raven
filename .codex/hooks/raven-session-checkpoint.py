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
    except (ValueError, OSError):
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


def _strip_heredoc_bodies(text: str) -> str:
    """Remove heredoc bodies from text before tokenization.

    Tracks heredoc delimiters (dash variant, quoted or bare) and removes every
    line between the opener and its matching terminator, including the terminator.
    Known limitation: does not handle bash 4's tilde-indented variant. This is a
    strict improvement over zero heredoc awareness.
    """
    lines = text.split("\n")
    result = []
    i = 0
    while i < len(lines):
        line = lines[i]
        # Check for heredoc openers: <<EOF, <<'EOF', <<"EOF", <<-EOF, etc.
        heredoc_match = re.search(r"<<-?(['\"]?)(\w+)\1(?:\s|$)", line)
        if heredoc_match:
            # Found a heredoc opener; extract the delimiter
            delimiter = heredoc_match.group(2)
            # Add the line up to and including the heredoc opener
            result.append(line[: heredoc_match.start()] + "<<" + delimiter)
            i += 1
            # Skip all lines until we find the terminator
            while i < len(lines):
                if lines[i].strip() == delimiter:
                    # Found the terminator; skip it and continue
                    i += 1
                    break
                i += 1
        else:
            result.append(line)
            i += 1
    return "\n".join(result)


_ENV_ASSIGNMENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")


def _completion_unit(command: str) -> str | None:
    """Return the unit argument only for a genuine ``raven-session.py --complete``.

    A completion command must actually invoke the session CLI in command position:
    the token in command position (after stripping env-var assignments and
    interpreter prefixes) must have basename ``raven-session.py``, and a
    ``--complete`` flag must follow in the same statement. Any other command —
    including one that merely mentions those tokens in prose, heredocs, or
    non-command positions — yields ``None`` so unrelated shell commands are
    allowed through untouched.

    Algorithm:
    1. Strip heredoc bodies before tokenization (shlex has no heredoc awareness).
    2. Normalize newlines to statement separators.
    3. Tokenize with shlex.shlex(punctuation_chars=True, posix=True, whitespace_split=True)
       to isolate statement operators (;, |, &) as individual tokens.
    4. Split the token stream into statements on those operators.
    5. Per statement, skip leading NAME=value assignments and optional interpreter
       prefixes (python/python3), then check that the next token's basename is
       the session script filename and the statement contains --complete.

    Falls back to regexes only when the command is not validly quoted (ValueError),
    so a malformed command still defers to the CLI's own validation.
    """
    # Strip heredoc bodies first
    text = _strip_heredoc_bodies(command)

    # Normalize newlines to a statement separator (semicolon)
    # so multi-line commands are treated as separate statements.
    text = text.replace("\n", ";")

    try:
        # Tokenize with punctuation_chars so statement operators are isolated.
        lexer = shlex.shlex(text, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        tokens = list(lexer)
    except ValueError:
        # Malformed quote: fall back to the regex-based fallback path.
        if not re.search(r"(?:^|[\s/])raven-session\.py(?:\s|$)", command):
            return None
        m = re.search(r"--complete\s+(\S+)", command)
        return m.group(1) if m else None

    # Split tokens into statements on shell operators.
    statement_operators = {";", "|", "&", "&&", "||"}
    statements = []
    current_statement = []
    for token in tokens:
        if token in statement_operators:
            if current_statement:
                statements.append(current_statement)
                current_statement = []
        else:
            current_statement.append(token)
    if current_statement:
        statements.append(current_statement)

    # Check each statement for a valid raven-session.py invocation.
    for stmt in statements:
        if not stmt:
            continue

        # Skip leading NAME=value assignments.
        idx = 0
        while idx < len(stmt) and _ENV_ASSIGNMENT_RE.match(stmt[idx]):
            idx += 1

        # Skip optional interpreter prefix (python or python3).
        if idx < len(stmt) and stmt[idx] in ("python", "python3"):
            idx += 1

        # The next token must be the session script (or a path to it).
        if idx >= len(stmt) or Path(stmt[idx]).name != "raven-session.py":
            continue

        # This statement invokes raven-session.py; now check for --complete.
        for i in range(idx + 1, len(stmt)):
            if stmt[i] == "--complete":
                return stmt[i + 1] if i + 1 < len(stmt) else None

    return None


def main() -> int:
    """Read the hook payload from stdin and deny a ``--complete`` bash call raven-session.py would reject."""
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
        [sys.executable, ".codex/scripts/raven-session.py", "--validate", unit],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        msg = result.stderr.strip() or result.stdout.strip() or f"Cannot complete unit '{unit}'"
        return _deny(msg, payload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
