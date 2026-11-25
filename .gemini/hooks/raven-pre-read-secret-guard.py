#!/usr/bin/env python3
"""PreToolUse/BeforeTool hook: deny a ``Read`` or ``read_file`` of a secret-bearing path.

This replaces the 21 ``Read(...)`` entries that used to sit in
``permissions.deny``. Those rules used gitignore semantics, where a bare
filename matches at any depth -- ``Read(*.pem)`` covered every ``.pem``
anywhere, which is what made them worth having. Claude Code 2.1.259 began
evaluating a Bash command's implied read scope against the same rules at
*directory* granularity, so a recursive read of the repository root escalated
because some ``.pem`` *could* exist inside it. No file had to be present. Every
``rg`` and ``grep`` at the root prompted, which put the prompt on routine
discovery and trained approval reflex -- the opposite of what a secrets guard
is for.

A settings-only fix does not exist. Rules evaluate deny -> ask -> allow
(``raven-guardrails.md``), so no ``permissions.allow`` entry can carry an
exception to a deny, and anchoring the globs so they stop matching at depth
would trade the prompt for a real hole (``packages/api/.env`` would stop being
covered). A hook is the one place that sees the *concrete path* a read is
about, so it can refuse ``.env`` while saying nothing about a directory scan
that might contain one.

The hook covers Claude ``Read`` and Gemini ``read_file``. It does not cover
Bash (``cat .env``), which belongs to ``raven-pre-bash-guard.py``, or Gemini
``read_many_files``. Codex has no Read tool, so it is not wired there.

``[hooks] block_secret_reads = false`` in ``.raven/config.toml`` turns this off,
the same shape ``block_gate_relaxation`` uses: a repository-level decision made
in the open and reviewable as a config change.
"""

from __future__ import annotations

import fnmatch
import importlib.util
import json
import os
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path

# Ported one-for-one from the `Read()` deny entries this replaces. Matched
# against the path's basename, and separately against each directory segment
# for the container names, which is what `secret/**` expressed before.
_SECRET_FILE_GLOBS = (
    "*.pem",
    "*.key",
    "*.p12",
    "*.pfx",
    "*.crt",
    "*.cer",
    ".env",
    ".env.*",
    ".envrc",
    "secret",
    "secrets",
    "secret.*",
    "secrets.*",
    "credential",
    "credentials",
    "credential.*",
    "credentials.*",
)

#: Directory names whose contents were covered by `secret/**`-style rules.
_SECRET_DIRS = frozenset({"secret", "secrets", "credential", "credentials"})


def _load_payload() -> dict | None:
    try:
        payload = json.load(sys.stdin)
    except (ValueError, OSError):
        return None
    return payload if isinstance(payload, dict) else None


def matches(file_path: str) -> str | None:
    """The rule a path trips, or None. Directory segments count, as `secret/**` did."""
    path = Path(file_path)
    name = path.name
    for glob in _SECRET_FILE_GLOBS:
        if fnmatch.fnmatch(name, glob):
            return glob
    for segment in path.parts[:-1]:
        if segment in _SECRET_DIRS:
            return f"{segment}/**"
    return None


def _raven_config_module():
    """Import the shared ``raven_config.py`` that ships in the same hooks component."""
    path = Path(__file__).resolve().parents[2] / ".raven" / "git-hooks" / "lib" / "raven_config.py"
    name = "raven_config_for_secret_guard"
    spec = importlib.util.spec_from_file_location(
        name, path, loader=SourceFileLoader(name, str(path))
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"could not load raven_config from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _enabled(start: Path) -> bool:
    """Whether `[hooks] block_secret_reads` is on. Fails closed: only an explicit false disables."""
    for candidate in (start, *start.parents):
        config = candidate / ".raven" / "config.toml"
        if not config.is_file():
            continue
        try:
            raven_config = _raven_config_module()
        except (ImportError, OSError):
            return True
        try:
            values = raven_config.read_config(config) or {}
        except raven_config.RavenConfigError:
            return True
        value = values.get("hooks", {}).get("block_secret_reads")
        return not (isinstance(value, str) and raven_config.parse_bool(value) is False)
    return True


def _is_gemini_hook(payload: dict) -> bool:
    if "GEMINI_PROJECT_DIR" in os.environ:
        return True
    event = payload.get("hook_event_name")
    if event in ("BeforeTool", "AfterTool"):
        return True
    tool = payload.get("tool_name")
    return tool in ("run_shell_command", "read_file", "write_file", "replace")


def _deny(reason: str, payload: dict) -> int:
    if _is_gemini_hook(payload):
        print(json.dumps({"decision": "deny", "reason": reason}))
        return 0
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": reason,
                }
            }
        )
    )
    return 0


def main() -> int:
    """Deny a Read whose target matches one of the ported secret rules."""
    payload = _load_payload()
    if payload is None:
        return 0
    tool_input = payload.get("tool_input") or {}
    file_path = (
        (tool_input.get("file_path") or tool_input.get("path"))
        if isinstance(tool_input, dict)
        else None
    )
    if not isinstance(file_path, str) or not file_path:
        return 0

    rule = matches(file_path)
    if rule is None:
        return 0

    cwd = payload.get("cwd")
    start = Path(cwd) if isinstance(cwd, str) and cwd else Path.cwd()
    if not _enabled(start):
        return 0

    return _deny(
        f"{file_path} matches the secret-file rule `{rule}`. Raven blocks reading credential "
        "material into the transcript. Stop and tell the user which file was blocked; do not "
        "read it through another tool or command. If the file holds no secrets (an example or "
        "fixture), the user can rename it or set `block_secret_reads = false` under `[hooks]` "
        "in `.raven/config.toml`.",
        payload,
    )


if __name__ == "__main__":
    raise SystemExit(main())
