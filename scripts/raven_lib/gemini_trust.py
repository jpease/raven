"""Read whether Gemini CLI trusts a project folder, from Gemini's trustedFolders.json.

Gemini CLI skips a project's `.gemini/` settings, hooks, policies, and custom
agents unless the project directory is trusted, recorded in
`~/.gemini/trustedFolders.json` (or `GEMINI_CLI_TRUSTED_FOLDERS_PATH`). Raven
installs that layer; this module lets `raven doctor` report whether it is live
or inert.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

TRUST_FOLDER = "TRUST_FOLDER"
TRUST_PARENT = "TRUST_PARENT"
DO_NOT_TRUST = "DO_NOT_TRUST"

TRUSTED = "trusted"
UNTRUSTED = "untrusted"
INVALID = "invalid"


def gemini_home() -> Path:
    """Where Gemini CLI keeps user-level state, honoring ``GEMINI_CLI_HOME``."""
    override = os.environ.get("GEMINI_CLI_HOME")
    home = Path(override) if override else Path.home()
    return home / ".gemini"


def gemini_trust_store_path() -> Path:
    """Gemini CLI's trust store, honoring its dedicated path override."""
    override = os.environ.get("GEMINI_CLI_TRUSTED_FOLDERS_PATH")
    if override:
        return Path(override)
    return gemini_home() / "trustedFolders.json"


def strip_json_comments(text: str) -> str:
    """Strip JavaScript-style comments while preserving JSON string contents."""
    output: list[str] = []
    index = 0
    in_string = False
    escaped = False
    while index < len(text):
        char = text[index]
        if in_string:
            output.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            index += 1
            continue
        if char == '"':
            in_string = True
            output.append(char)
            index += 1
            continue
        if char == "/" and index + 1 < len(text) and text[index + 1] == "/":
            output.extend((" ", " "))
            index += 2
            while index < len(text) and text[index] not in "\r\n":
                output.append(" ")
                index += 1
            continue
        if char == "/" and index + 1 < len(text) and text[index + 1] == "*":
            output.extend((" ", " "))
            index += 2
            while index + 1 < len(text) and text[index : index + 2] != "*/":
                output.append(text[index] if text[index] in "\r\n" else " ")
                index += 1
            if index + 1 >= len(text):
                raise ValueError("unterminated JSON block comment")
            output.extend((" ", " "))
            index += 2
            continue
        output.append(char)
        index += 1
    return "".join(output)


def trust_entries(text: str) -> dict[str, str]:
    """Parse and validate Gemini CLI's ``{path: TrustLevel}`` trust map."""
    data = json.loads(strip_json_comments(text))
    if not isinstance(data, dict):
        raise ValueError("trusted folders file is not a JSON object")
    entries: dict[str, str] = {}
    valid_levels = {TRUST_FOLDER, TRUST_PARENT, DO_NOT_TRUST}
    for key, value in data.items():
        if not isinstance(value, str) or value not in valid_levels:
            raise ValueError(f"invalid trust level for {key!r}")
        entries[str(key)] = value
    return entries


def _normalize_path(path: Path) -> str:
    normalized = os.path.abspath(str(path)).replace("\\", "/")
    if sys.platform in ("darwin", "win32"):
        return normalized.lower()
    return normalized


def _real_path_if_exists(path: Path) -> Path:
    try:
        if path.exists():
            return Path(os.path.realpath(path))
    except OSError:
        pass
    return path


def _covers(base: str, target: str) -> bool:
    return target == base or target.startswith(base.rstrip("/") + "/")


def project_trust(root: Path, store_path: Path | None = None) -> str | None:
    """Return Gemini's effective trust for ``root``.

    ``TRUST_FOLDER`` and ``DO_NOT_TRUST`` take effect at the recorded path,
    while ``TRUST_PARENT`` takes effect at that path's parent. Among rules
    whose effective path covers ``root``, the longest normalized recorded path
    wins, as it does in Gemini CLI. Returns ``None`` when the store cannot be
    read, ``INVALID`` when Gemini would reject it, and ``""`` when no valid
    entry covers the project.
    """
    path = store_path if store_path is not None else gemini_trust_store_path()
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    try:
        entries = trust_entries(text)
    except ValueError:
        return INVALID

    rules: list[tuple[int, str, str]] = []
    for key, level in entries.items():
        recorded = _normalize_path(Path(key))
        effective = Path(recorded).parent if level == TRUST_PARENT else Path(recorded)
        effective = _real_path_if_exists(effective)
        rules.append((len(recorded), _normalize_path(effective), level))

    target = _normalize_path(_real_path_if_exists(root))
    rules.sort(key=lambda rule: rule[0], reverse=True)
    for _recorded_length, effective, level in rules:
        if not _covers(effective, target):
            continue
        if level in (TRUST_FOLDER, TRUST_PARENT):
            return TRUSTED
        return UNTRUSTED
    return ""
