#!/usr/bin/env python3
"""PostToolUse hook: replace an oversized Bash result with its head, its tail, and a path to the whole.

Every line of a tool result is paid for on every later turn of the session,
so a 2,000-line test log costs its full price dozens of times over. This hook
keeps the first ``HEAD_LINES`` lines (where a traceback starts) and the last
lines up to the configured limit (where a summary lands), writes the complete
output to a file, and names that file in the replacement so nothing is lost:
the agent can search it with ``rg`` or read a range with ``sed -n`` instead
of carrying all of it in context.

Claude Code and Gemini CLI. Claude's PostToolUse hook can replace a result
through ``hookSpecificOutput.updatedToolOutput``; the Bash ``tool_response`` is
``{stdout, stderr, ...}`` and each stream gets its own ``max_lines`` budget and
its own spill file (``-stderr.log`` suffix for stderr), so a failing build with
empty stdout and a huge stderr is still cut. The replacement keeps the
original dict shape, because Claude ignores a value that does not match the
tool's output shape. Gemini's AfterTool ``tool_response`` is
``{llmContent, returnDisplay, error}`` with the streams merged into one
string; the hook replaces it with ``decision: "deny"`` plus the shrunk text
as ``reason`` (https://github.com/google-gemini/gemini-cli/blob/main/docs/hooks/reference.md).
Codex documents a replacement through ``{"continue": false, "reason": ...}``
(https://developers.openai.com/codex/hooks), but a live run on codex-cli 0.172.0
showed the model still receiving the original output, so this file has no
``.codex/hooks/`` counterpart (recorded in
``.claude/docs/raven-agent-compatibility.md``). A command already routed
through RTK is left alone -- it is compressed once, on purpose.

Configured by ``[bash_output] max_lines`` in ``.raven/config.toml``; ``0``
turns it off. Fail-open: anything this cannot parse leaves the result as it
was.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
import tempfile
from importlib.machinery import SourceFileLoader
from pathlib import Path

DEFAULT_MAX_LINES = 150
HEAD_LINES = 40
SPILL_DIRECTORY_NAME = "raven-bash-output"


def _load_payload() -> dict | None:
    try:
        payload = json.load(sys.stdin)
    except (ValueError, OSError):
        return None
    return payload if isinstance(payload, dict) else None


def _is_gemini_hook(payload: dict) -> bool:
    if "GEMINI_PROJECT_DIR" in os.environ:
        return True
    event = payload.get("hook_event_name")
    if event in ("BeforeTool", "AfterTool"):
        return True
    tool = payload.get("tool_name")
    return tool in ("run_shell_command", "read_file", "write_file", "replace")


def _raven_config_module():
    """Import ``.raven/git-hooks/lib/raven_config.py`` from the install layout.

    Installed at ``<root>/.claude/hooks/``, so two parents up is the project
    root. Same pattern as ``raven-skeleton-read-guard.py``.
    """
    path = Path(__file__).resolve().parents[2] / ".raven" / "git-hooks" / "lib" / "raven_config.py"
    spec = importlib.util.spec_from_file_location(
        "raven_config_for_bash_truncate",
        path,
        loader=SourceFileLoader("raven_config_for_bash_truncate", str(path)),
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"could not load raven_config from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def parse_max_lines(text: str) -> int:
    """``[bash_output] max_lines`` from raw config text; the default when absent.

    A non-integer or negative value keeps the default rather than turning the
    hook off: a typo should not silently remove a guardrail.
    """
    try:
        raven_config = _raven_config_module()
    except (ImportError, OSError):
        return DEFAULT_MAX_LINES
    section = raven_config.parse_config_text(text).get("bash_output", {})
    value = section.get("max_lines", "").strip()
    if value.isdigit():
        return int(value)
    return DEFAULT_MAX_LINES


def read_max_lines() -> int:
    """The configured limit from the install's ``.raven/config.toml``, or the default."""
    config = Path(__file__).resolve().parents[2] / ".raven" / "config.toml"
    try:
        text = config.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return DEFAULT_MAX_LINES
    return parse_max_lines(text)


def truncate(
    stdout: str, max_lines: int, spill_path: str, head_lines: int = HEAD_LINES
) -> str | None:
    """The replacement text, or None when ``stdout`` is within ``max_lines``.

    Head and tail are split so the tail gets whatever the limit leaves after
    the head: a test runner prints its verdict last, and that is the part a
    reader must not lose.
    """
    if max_lines <= 0:
        return None
    lines = stdout.splitlines()
    total = len(lines)
    if total <= max_lines:
        return None
    head = min(head_lines, max_lines // 2)
    tail = max_lines - head
    omitted = total - head - tail
    marker = (
        f"[raven: {omitted} of {total} lines omitted from the middle. Full output: "
        f"{spill_path} -- search it with rg, or read a range with sed -n, rather "
        f"than the whole file.]"
    )
    kept = [*lines[:head], marker, *lines[total - tail :]]
    return "\n".join(kept) + ("\n" if stdout.endswith("\n") else "")


def _spill(text: str, session_id: str, stream: str = "") -> str | None:
    """Write the complete output under the temp directory; the path, or None.

    stdout keeps ``<session>-<digest>.log``; another stream adds ``-<stream>``.
    """
    directory = Path(tempfile.gettempdir()) / SPILL_DIRECTORY_NAME
    digest = hashlib.sha1(text.encode("utf-8", "replace")).hexdigest()[:12]
    safe_session = "".join(ch for ch in session_id if ch.isalnum() or ch in "-_")[:32] or "session"
    suffix = f"-{stream}" if stream else ""
    path = directory / f"{safe_session}-{digest}{suffix}.log"
    try:
        directory.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", errors="replace")
    except OSError:
        return None
    return str(path)


def _shrink(text: str, max_lines: int, session_id: str, stream: str) -> str | None:
    """The replacement for one stream, or None when it fits or cannot be spilled.

    Nowhere to keep the whole output means nothing may be dropped.
    """
    if max_lines <= 0 or len(text.splitlines()) <= max_lines:
        return None
    spill_path = _spill(text, session_id, stream)
    if spill_path is None:
        return None
    return truncate(text, max_lines, spill_path)


def main() -> int:
    """Read the PostToolUse payload and replace an oversized Bash result."""
    payload = _load_payload()
    if payload is None:
        return 0
    response = payload.get("tool_response")
    if not isinstance(response, dict):
        return 0
    tool_input = payload.get("tool_input") or {}
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if isinstance(command, str) and command.lstrip().startswith("rtk "):
        return 0

    max_lines = read_max_lines()
    if max_lines <= 0:
        return 0
    raw_session = payload.get("session_id")
    session_id = raw_session if isinstance(raw_session, str) else ""

    if _is_gemini_hook(payload):
        content = response.get("llmContent")
        if not isinstance(content, str):
            return 0
        replacement = _shrink(content, max_lines, session_id, "")
        if replacement is not None:
            print(json.dumps({"decision": "deny", "reason": replacement}))
        return 0

    updated = dict(response)
    changed = False
    stdout_key = "stdout" if "stdout" in response else "output"
    for key, stream in ((stdout_key, ""), ("stderr", "stderr")):
        text = response.get(key)
        if not isinstance(text, str):
            continue
        replacement = _shrink(text, max_lines, session_id, stream)
        if replacement is not None:
            updated[key] = replacement
            changed = True
    if changed:
        print(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "PostToolUse",
                        "updatedToolOutput": updated,
                    }
                }
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
