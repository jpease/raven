#!/usr/bin/env python3

from __future__ import annotations

import json
import re
import shlex
import sys

# Tokens made up solely of these characters are top-level shell operators that
# separate one simple command from the next.
_OPERATOR_CHARS = frozenset(";|&()<>")

# Long options that map onto the short letters the destructive rules reason about.
# One shared map is enough: the program check gates which rule consumes the flags.
_LONG_OPTION_LETTERS = {
    "--recursive": "r",
    "--force": "f",
}


def _load_payload() -> dict | None:
    try:
        return json.load(sys.stdin)
    except Exception:
        return None


def _extract_command(payload: dict) -> str:
    tool_input = payload.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        tool_input = {}
    return tool_input.get("command") or payload.get("command") or ""


def _is_codex_hook(payload: dict) -> bool:
    # Both Claude Code and Codex include these fields; both use the structured JSON path.
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


def _deny_message(command: str) -> str:
    return (
        "Blocked potentially destructive command."
        f" Ask for explicit approval before running: {command}"
    )


def _command_segments(command: str) -> list[list[str]]:
    """Split a command into simple-command segments of tokens.

    Splits on top-level shell operators (``;`` ``|`` ``&`` ``(`` ``)`` ``<``
    ``>`` and newlines) while respecting quotes. On a lexer error such as
    unbalanced quotes, that line falls back to a whitespace split so the
    remaining checks still run (best effort -- err toward more checking).
    """
    segments: list[list[str]] = []
    for line in command.splitlines():
        try:
            lexer = shlex.shlex(line, posix=True, punctuation_chars=True)
            lexer.whitespace_split = True
            tokens = list(lexer)
        except ValueError:
            segments.append(line.split())
            continue

        current: list[str] = []
        for token in tokens:
            if token and all(ch in _OPERATOR_CHARS for ch in token):
                segments.append(current)
                current = []
            else:
                current.append(token)
        segments.append(current)

    return [segment for segment in segments if segment]


def _program_and_args(segment: list[str]) -> tuple[str, list[str]] | None:
    """Return (program, remaining tokens), skipping leading env-assignments and sudo."""
    index = 0
    while index < len(segment):
        token = segment[index]
        if token == "sudo":
            index += 1
            continue
        if re.match(r"[A-Za-z_][A-Za-z0-9_]*=", token):
            index += 1
            continue
        break
    if index >= len(segment):
        return None
    return segment[index], segment[index + 1 :]


def _normalize_options(args: list[str]) -> tuple[set[str], list[str]]:
    """Split args into a set of short-option letters and positional arguments.

    Combined clusters (``-rf``), split short options (``-r`` ``-f``), and mapped
    long options (``--recursive`` -> ``r``) all reduce to the same letter set.
    Tokens after a ``--`` end-of-options marker are treated as positional only.
    """
    flags: set[str] = set()
    positionals: list[str] = []
    end_of_options = False
    for token in args:
        if end_of_options:
            positionals.append(token)
            continue
        if token == "--":
            end_of_options = True
            continue
        if token.startswith("--"):
            name = token.split("=", 1)[0]
            mapped = _LONG_OPTION_LETTERS.get(name)
            if mapped:
                flags.add(mapped)
            # Unknown long options carry no short letter; ignore them.
        elif token.startswith("-") and len(token) > 1:
            flags.update(token[1:])
        else:
            positionals.append(token)
    return flags, positionals


def _is_destructive_rm(program: str, flags: set[str], positionals: list[str]) -> bool:
    if program.lower() != "rm":
        return False
    recursive = "r" in flags or "R" in flags
    force = "f" in flags
    if not (recursive and force):
        return False
    return any(arg == "/" or arg == "~" or arg.startswith("~/") for arg in positionals)


def _is_destructive_git_clean(program: str, flags: set[str], positionals: list[str]) -> bool:
    if program.lower() != "git":
        return False
    if not positionals or positionals[0] != "clean":
        return False
    return "f" in flags and "d" in flags and "x" in flags


def main() -> int:
    payload = _load_payload()
    if payload is None:
        return 0

    command = _extract_command(payload)
    if not command:
        return 0

    # Regex checks whose intents have no option-combination bypass.
    regex_patterns = [
        r"sudo\s+rm\b",
        r"git\s+reset\s+--hard",
        r"\bdropdb\b",
        r"\bDROP\s+DATABASE\b",
        r"kubectl\s+delete\b",
        r"aws\b.*\bdelete\b",
    ]
    for pattern in regex_patterns:
        if re.search(pattern, command, re.IGNORECASE):
            return _deny(_deny_message(command), payload)

    # Tokenized checks for destructive intents with option-spelling variants:
    # rm force+recursive at / or ~, and git clean force+d+x.
    for segment in _command_segments(command):
        parsed = _program_and_args(segment)
        if parsed is None:
            continue
        program, args = parsed
        flags, positionals = _normalize_options(args)
        if _is_destructive_rm(program, flags, positionals) or _is_destructive_git_clean(
            program, flags, positionals
        ):
            return _deny(_deny_message(command), payload)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
