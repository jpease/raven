"""Read whether Codex trusts a project, from Codex's own user config.

Codex loads a project's ``.codex/`` layer -- config, hooks, rules, custom
agents -- only for a project it trusts, and the only record of that trust is a
``[projects.'<path>'] trust_level = 'trusted'`` table in ``$CODEX_HOME/config.toml``
(verified live against codex-cli 0.152.1, 2026-09-02: a ``-c`` override on the
command line grants nothing, and an untrusted project's hooks are parsed and
then skipped without a word). Raven installs that layer; nothing on either side
says when it is inert. This module is what lets `raven doctor` say so.

Codex's config is Codex's file, not Raven's: it holds arrays, inline tables,
and sections this repository's TOML subset rejects outright. So this is a
scanner for one table shape, not a parser -- it reads ``[projects.*]`` headers
and the ``trust_level`` key beneath them and ignores everything else.
"""

from __future__ import annotations

import os
from pathlib import Path

from .config import strip_comment

TRUSTED = "trusted"
UNTRUSTED = "untrusted"

_PROJECTS_PREFIX = "projects."


def codex_home() -> Path:
    """Where Codex keeps its user-level state, honoring ``CODEX_HOME``.

    An empty value is treated as unset, for the same reason
    `constants.claude_config_dir` treats ``CLAUDE_CONFIG_DIR=""`` that way.
    """
    override = os.environ.get("CODEX_HOME")
    if override:
        return Path(override)
    return Path.home() / ".codex"


def _section_name(line: str) -> str | None:
    """The header name of a ``[section]`` line, or None for any other line.

    ``[[array.of.tables]]`` headers are not sections this cares about and
    return None rather than a name with a stray bracket.
    """
    if not (line.startswith("[") and line.endswith("]")):
        return None
    if line.startswith("[["):
        return None
    return line[1:-1].strip()


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


def trust_entries(text: str) -> dict[str, str]:
    """``{project path: trust_level}`` for every ``[projects.<path>]`` table in ``text``.

    The path is returned exactly as written, unquoted; the caller decides how
    to compare it. A ``[projects.<path>]`` table with no ``trust_level`` key is
    recorded with an empty value, so "present but unset" and "absent" stay
    distinguishable. A commented-out header is not a header.
    """
    entries: dict[str, str] = {}
    current: str | None = None
    for raw_line in text.splitlines():
        line = strip_comment(raw_line)
        if not line:
            continue
        section = _section_name(line)
        if section is not None:
            if section.startswith(_PROJECTS_PREFIX):
                current = _unquote(section[len(_PROJECTS_PREFIX) :])
                entries.setdefault(current, "")
            else:
                current = None
            continue
        if current is None or "=" not in line:
            continue
        key, value = (part.strip() for part in line.split("=", 1))
        if key == "trust_level":
            entries[current] = _unquote(value)
    return entries


def _same_path(a: Path, b: Path) -> bool:
    return os.path.normcase(str(a)) == os.path.normcase(str(b))


def project_trust(root: Path, config_path: Path | None = None) -> str | None:
    """Codex's recorded trust for ``root``, or None when Codex has no config at all.

    Returns ``"trusted"``, ``"untrusted"``, or ``""`` for a project no entry
    covers. An entry for an ancestor directory covers the project -- observed
    live: a repository under a trusted home directory runs its hooks -- and
    the nearest entry wins, so an explicit ``untrusted`` on the project itself
    is not overridden by a trusted parent. That last rule is this module's
    reading, not documented Codex behavior; it is the conservative one, since
    the cost of a wrong ``untrusted`` here is a warning, and the cost of a
    wrong ``trusted`` is silence about an inert install.
    """
    path = config_path if config_path is not None else codex_home() / "config.toml"
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    entries = trust_entries(text)
    if not entries:
        return ""
    resolved = {Path(key).expanduser().resolve(): value for key, value in entries.items()}
    target = root.resolve()
    for candidate in (target, *target.parents):
        for entry, value in resolved.items():
            if _same_path(entry, candidate):
                return value
    return ""
