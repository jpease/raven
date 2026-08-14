#!/usr/bin/env python3
"""PreToolUse hook: deny edits to secret-like paths, and warn (without blocking) on high-churn ones.

Denial output is shaped differently for Claude (stderr + exit 2) vs Codex (a
``hookSpecificOutput`` JSON payload on stdout, exit 0) -- see `_deny` and
`_is_codex_hook` -- since the two hosts expect different denial protocols.
"""

from __future__ import annotations

import json
import os.path
import re
import sys


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


def _extract_path(payload: dict) -> str:
    tool_input = payload.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        tool_input = {}
    return tool_input.get("file_path") or tool_input.get("path") or payload.get("file_path") or ""


def _is_codex_hook(payload: dict) -> bool:
    return "hook_event_name" in payload or "tool_name" in payload


# Hoisted to module level (rather than a local inside `main()`) so tests --
# and the native `permissions.deny` drift check in particular -- can read the
# real deny/warn tiers instead of restating them. Zero behavior change: same
# lists, same order, just reachable from outside `main()`.
BLOCKED = [
    r"\.pem$",
    r"\.key$",
    r"\.p12$",
    r"\.pfx$",
    r"\.crt$",
    r"\.cer$",
    # `.env` is the spelling projects use *least* for real values: the committed
    # template is `.env.example` and the secrets live in `.env.local`,
    # `.env.production`, `.env.development`. `.envrc` (direnv) is a shell script
    # that commonly exports them (issue #213).
    r"(^|/)\.env(\.[^/]*)?$",
    r"(^|/)\.envrc$",
    # Anchored to a path segment: a bare `secrets` substring also blocks
    # `docs/how-we-handle-secrets.md` and any `test_secrets_helper.py`.
    r"(^|/)secrets?(\.|/|$)",
    # Anchored to a path segment, same shape as `secrets` above: a bare
    # `credentials` substring also blocked `docs/credentials-design.md`,
    # `tests/test_credentials_helper.py`, and `src/credentialsProvider.ts`
    # (issue #197).
    r"(^|/)credentials?(\.|/|$)",
]
CAUTION = [
    r"/migrations/",
    r"/generated/",
    r"package-lock\.json$",
    r"Cargo\.lock$",
    r"pnpm-lock\.yaml$",
]


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
    """Read the hook payload from stdin and deny or warn based on the edited path."""
    payload = _load_payload()
    if payload is None:
        return 0

    path = _extract_path(payload)
    if not path:
        return 0

    # Collapse `..` traversal lexically (no filesystem access -- this must stay
    # fast and side-effect-free, unlike Path.resolve()) *after* the backslash
    # swap, so Windows-style input (`src\..\.env`) normalizes the same as
    # POSIX input. os.path.normpath never introduces a leading "./" for a
    # plain relative path on a POSIX host, so it does not break the `(^|/)`
    # anchors below (verified: normpath("docs/credentials-design.md") ==
    # "docs/credentials-design.md", normpath(".env") == ".env").
    normalized = os.path.normpath(path.replace("\\", "/"))

    if any(re.search(pattern, normalized, re.IGNORECASE) for pattern in BLOCKED):
        return _deny(f"Protected file path. Confirm intent before editing: {path}", payload)

    if any(re.search(pattern, normalized, re.IGNORECASE) for pattern in CAUTION):
        print(
            f"High-churn or generated/protected path. Edit only when required: {path}",
            file=sys.stderr,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
