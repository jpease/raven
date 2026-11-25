#!/usr/bin/env python3
"""PostToolUse hook: nudge toward RTK when a just-run bash command looks like a noisy test/build/CLI."""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import sys
from functools import lru_cache

# Commands noisy enough to be worth compressing. Every entry is matched as a
# whole word (see _NOISY_COMMAND): plain substring matching flagged any command
# merely containing an entry's letters, so `aws` fired on
# `git commit -m "fix draws bug"`. The hint is advisory, which is exactly why a
# false positive is corrosive -- it teaches people to ignore hook output.
_NOISY_COMMANDS = (
    r"cargo\s+test",
    r"pytest",
    r"npm\s+test",
    r"pnpm\s+test",
    r"go\s+test",
    r"swift\s+test",
    r"xcodebuild",
    r"docker",
    r"kubectl",
    r"aws",
    r"mix\s+test",
    r"rspec",
    r"busted",
    r"vitest",
    r"jest",
    r"just\s+(?:test|check)",
)

# Same value as HEAD_LINES in raven-post-bash-truncate.py: a result that hook
# would not touch is never nudged either.
NUDGE_MIN_LINES = 40

# Runner -> tokens that count as its own quiet flag. `-s` is absent for pytest
# because there it means --capture=no, which is noisier. Runners with an empty
# set have no quiet flag (`go test` is handled separately in _is_quiet).
QUIET_FLAGS: dict[str, frozenset[str]] = {
    "pytest": frozenset({"-q", "-qq", "--quiet"}),
    "cargo test": frozenset({"-q", "--quiet"}),
    "npm test": frozenset({"-s", "--silent", "--loglevel=silent"}),
    "pnpm test": frozenset({"-s", "--silent", "--loglevel=silent"}),
    "go test": frozenset(),
    "swift test": frozenset({"-q", "--quiet"}),
    "xcodebuild": frozenset({"-quiet"}),
    "docker": frozenset({"-q", "--quiet"}),
    "vitest": frozenset({"--silent"}),
    "jest": frozenset({"--silent"}),
    "kubectl": frozenset(),
    "aws": frozenset(),
    "mix test": frozenset(),
    "rspec": frozenset(),
    "busted": frozenset(),
    "just test": frozenset(),
    "just check": frozenset(),
}

_SEPARATORS = frozenset({"&&", "||", ";", "|", "|&", "&", "(", ")"})
_REDIRECT_CHARS = frozenset("<>&|")

_NOISY_COMMAND = re.compile(r"\b(?:" + "|".join(_NOISY_COMMANDS) + r")\b")


@lru_cache(maxsize=1)
def _rtk_installed() -> bool:
    """True when `rtk` is on PATH.

    RTK is optional, and a hint pointing at a tool the reader cannot run is
    pure context cost on every noisy command -- in a hook whose whole purpose
    is spending less of it. Advisory output that cannot be acted on is the
    fastest way to teach people to ignore hook output, so a project without
    RTK gets silence instead. `brew install rtk` (or https://www.rtk-ai.app/)
    turns the hint back on with no Raven change.
    """
    return shutil.which("rtk") is not None


def _load_payload() -> dict | None:
    try:
        payload = json.load(sys.stdin)
    except (ValueError, OSError):
        return None
    # Valid JSON of the wrong shape (a list, a bare string, a number) is still
    # unusable: returning it would break the `dict` contract below and raise on
    # `.get`. That is the one parseable input that would traceback instead of
    # failing open, on every tool call.
    return payload if isinstance(payload, dict) else None


def _extract_command(payload: dict) -> str:
    tool_input = payload.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        tool_input = {}
    return tool_input.get("command") or payload.get("command") or ""


def _is_redirect(token: str) -> bool:
    return bool(token) and set(token) <= _REDIRECT_CHARS and ("<" in token or ">" in token)


def _strip_redirections(tokens: list[str]) -> list[str]:
    """Drop redirection operators, their targets, and a leading fd (`2` in `2>&1`)."""
    kept: list[str] = []
    skip = False
    for index, token in enumerate(tokens):
        if skip:
            skip = False
            continue
        if _is_redirect(token):
            skip = True
            continue
        if token.isdigit() and index + 1 < len(tokens) and _is_redirect(tokens[index + 1]):
            continue
        kept.append(token)
    return kept


def _segments(command: str) -> list[list[str]]:
    """Simple commands of a shell line, split on control operators, redirections removed.

    Quoted operators stay inside one token, so ``echo 'a && pytest'`` is a
    single argument. Unbalanced quotes fall back to a regex split.
    """
    lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    try:
        tokens = list(lexer)
    except ValueError:
        parts = re.split(r"\s*(?:&&|\|\||;|\|)\s*", command.strip())
        return [part.split() for part in parts if part.split()]
    segments: list[list[str]] = []
    current: list[str] = []
    for token in tokens:
        if token in _SEPARATORS:
            segments.append(current)
            current = []
        else:
            current.append(token)
    segments.append(current)
    return [cleaned for cleaned in (_strip_redirections(seg) for seg in segments) if cleaned]


def _output_line_count(payload: dict) -> int | None:
    """Lines of the command's output, or None when the payload carries none."""
    response = payload.get("tool_response")
    if isinstance(response, str):
        return len(response.splitlines())
    if not isinstance(response, dict):
        return None
    content = response.get("llmContent")
    if isinstance(content, str):
        return len(content.splitlines())
    streams = [response[key] for key in ("stdout", "stderr") if isinstance(response.get(key), str)]
    if not streams:
        return None
    return sum(len(text.splitlines()) for text in streams)


def _runner_is_quiet(command: str) -> bool:
    """True when the matched runner's own segment carries a quiet flag."""
    for segment in _segments(command):
        match = _NOISY_COMMAND.search(" ".join(segment))
        if match is None:
            continue
        runner = re.sub(r"\s+", " ", match.group(0))
        flags = {token for token in segment if token.startswith("-")}
        if runner == "go test":
            return not flags & {"-v", "-json"}
        return bool(flags & QUIET_FLAGS.get(runner, frozenset()))
    return False


def _is_gemini_hook(payload: dict) -> bool:
    if "GEMINI_PROJECT_DIR" in os.environ:
        return True
    event = payload.get("hook_event_name")
    if event in ("BeforeTool", "AfterTool"):
        return True
    tool = payload.get("tool_name")
    return tool in ("run_shell_command", "read_file", "write_file", "replace")


def _needs_nudge(payload: dict, command: str) -> bool:
    """Quiet flag first, RTK only if the output is still noisy."""
    lines = _output_line_count(payload)
    if lines is not None:
        return lines > NUDGE_MIN_LINES
    return not _runner_is_quiet(command)


def main() -> int:
    """Read the hook payload from stdin and print an RTK hint if the command matches a noisy tool."""
    payload = _load_payload()
    if payload is None:
        return 0

    command = _extract_command(payload)
    if not command:
        return 0

    if (
        _rtk_installed()
        and not command.lstrip().startswith("rtk ")
        and _NOISY_COMMAND.search(command)
        and _needs_nudge(payload, command)
    ):
        hint = (
            f"Consider running noisy commands through RTK when exact raw output"
            f" is not required: {command}"
        )
        if _is_gemini_hook(payload):
            print(
                json.dumps(
                    {
                        "systemMessage": hint,
                        "hookSpecificOutput": {
                            "hookEventName": "AfterTool",
                            "additionalContext": hint,
                        },
                    }
                )
            )
        elif "hook_event_name" in payload or "tool_name" in payload:
            print(
                json.dumps(
                    {
                        "hookSpecificOutput": {
                            "hookEventName": "PostToolUse",
                            "additionalContext": hint,
                        }
                    }
                )
            )
        else:
            print(hint)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
