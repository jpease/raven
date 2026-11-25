#!/usr/bin/env python3
"""PostToolUse hook: best-effort auto-format a just-edited file with its language's formatter.

Silent and always exits 0 -- a missing formatter, an unsupported extension, or a
malformed hook payload all mean "nothing to do", never a hook failure that would
block the edit or spam the transcript.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path


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


_PATCH_HEADER = re.compile(r"^\*\*\* (?:Add File|Update File|Delete File|Move to): (.+)$")


def _patch_paths(text: str) -> list[str]:
    """Every file a Codex ``apply_patch`` payload adds, updates, deletes, or moves to.

    Headers are matched on the stripped line, as Codex's own parser does. An
    add-hunk content line starts with ``+``, so it never matches. ``*** Environment
    ID:`` names a remote executor, not a file, and is not captured.
    """
    paths: list[str] = []
    for line in text.splitlines():
        match = _PATCH_HEADER.match(line.strip())
        if match is None:
            continue
        path = match.group(1).strip()
        if path and path not in paths:
            paths.append(path)
    return paths


def _extract_paths(payload: dict) -> list[str]:
    tool_input = payload.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        return []
    command = tool_input.get("command")
    if payload.get("tool_name") == "apply_patch" and isinstance(command, str):
        return _patch_paths(command)
    path = tool_input.get("file_path") or tool_input.get("path") or payload.get("file_path")
    return [path] if path and isinstance(path, str) else []


def _anchored(path: str, payload: dict) -> str:
    """``path`` joined onto the payload ``cwd`` when it is relative and ``cwd`` is absolute."""
    cwd = payload.get("cwd")
    if isinstance(cwd, str) and os.path.isabs(cwd) and not os.path.isabs(path):
        return os.path.join(cwd, path)
    return path


def run(command: list[str]) -> None:
    """Run a formatter command, discarding its output; failure is not reported (best-effort)."""
    subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)


def _swift_format_cmd() -> list[str] | None:
    """Resolve Apple's swift-format: prefer a PATH binary, else the Xcode toolchain via xcrun."""
    if shutil.which("swift-format"):
        return ["swift-format"]
    if shutil.which("xcrun"):
        return ["xcrun", "swift-format"]
    return None


def _format(path: Path) -> None:
    """Format one existing file with its language's formatter, if one is available."""
    suffix = path.suffix.lower()
    if suffix == ".py" and shutil.which("ruff"):
        run(["ruff", "format", str(path)])
    elif suffix in {".js", ".jsx", ".ts", ".tsx", ".json", ".md"} and shutil.which("prettier"):
        run(["prettier", "--write", str(path)])
    elif suffix == ".swift":
        swift_format = _swift_format_cmd()
        if swift_format:
            run([*swift_format, "format", "--in-place", str(path)])


def _is_remote_patch(payload: dict) -> bool:
    """True for an ``apply_patch`` whose files live on a remote executor, not this host."""
    tool_input = payload.get("tool_input")
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if payload.get("tool_name") != "apply_patch" or not isinstance(command, str):
        return False
    return any(line.strip().startswith("*** Environment ID:") for line in command.splitlines())


def main() -> int:
    """Read the hook payload from stdin and format each edited file whose type is supported."""
    payload = _load_payload()
    if payload is None or _is_remote_patch(payload):
        return 0

    for raw_path in _extract_paths(payload):
        path = Path(_anchored(raw_path, payload))
        # Deleted files and the source of a `Move to` no longer exist.
        if path.is_file():
            _format(path)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
