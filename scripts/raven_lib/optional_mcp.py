"""Decide which opt-in MCP servers a repository keeps when `raven upgrade` runs.

Raven used to ship a `gitnexus` MCP server to every repository. It is now an
opt-in catalog entry (`common/.raven/mcp-optional.json`) selected by
`[mcp] optional` in `.raven/config.toml`. Raven owns `.mcp.json`,
`.codex/config.toml` and `.gemini/settings.json` wholesale, so an unmodified copy
is rewritten in place on upgrade: without a decision, a repository that relied on
the old default would silently lose a working server. This module turns that
case into an explicit keep-or-remove question.

The config key is the record of the decision. Absent means "not decided yet"
(`RavenConfig.optional_mcp is None`); `[]` means "decided none". Only the absent
case ever prompts, so the question is asked at most once per repository.
"""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

from .models import RavenConfig

#: The files Raven renders MCP servers into, relative to the repository root.
MCP_CONFIG_PATHS = (".mcp.json", ".codex/config.toml", ".gemini/settings.json")

_TOML_SERVER_RE = re.compile(r"^\[mcp_servers\.([A-Za-z0-9_-]+)\]", re.MULTILINE)

#: One sentence of per-server advice appended to the prompt, where Raven has any.
SERVER_HINTS = {
    "gitnexus": (
        'If you keep it, add {"skipContextFiles": true} to .gitnexusrc so `gitnexus analyze` '
        "does not write a MUST-style block into AGENTS.md."
    ),
}


@dataclass(frozen=True)
class OptionalMcpDecision:
    """The outcome of `decide_optional_mcp` for one `raven upgrade` run."""

    #: The effective `[mcp] optional` list this run renders with.
    names: list[str]
    #: Whether a live run must record `names` in `.raven/config.toml`.
    write: bool = False
    #: Servers that were configured with no recorded decision (what a dry run reports).
    pending: list[str] = field(default_factory=list)
    #: Servers kept only because the run was not interactive (CI, a pipe, dry run).
    kept_unasked: list[str] = field(default_factory=list)


def servers_configured_in(destination: Path) -> set[str]:
    """MCP server names declared by any Raven-rendered MCP file under ``destination``."""
    found: set[str] = set()
    for relative in MCP_CONFIG_PATHS:
        path = destination / relative
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if relative.endswith(".toml"):
            found.update(_TOML_SERVER_RE.findall(text))
            continue
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            continue
        servers = data.get("mcpServers") if isinstance(data, dict) else None
        if isinstance(servers, dict):
            found.update(servers)
    return found


def unknown_names(names: Iterable[str], catalog: Iterable[str]) -> list[str]:
    """Names in ``names`` that are not in the optional catalog, sorted."""
    return sorted(set(names) - set(catalog))


def prompt_to_keep_optional_server(name: str) -> bool:
    """Ask whether to keep ``name``; True (keep) on Enter, EOF, or any non-interactive stdin.

    Keep is the default because it changes nothing: the question exists to stop
    a silent removal, so the unanswered case must never be the removal.
    """
    if not sys.stdin.isatty():
        return True
    print()
    print(f"'{name}' is now an optional MCP server in Raven.")
    print(
        "Raven no longer installs it by default. In Raven's agent-task tests, grep and a "
        "language server found as many callers as a code-graph tool and cost less; the one "
        "measured gain was cheaper exploration questions, from CodeGraph."
    )
    print(
        f"This repository has a '{name}' server configured. Keeping it records "
        f'`[mcp] optional = ["{name}"]` in .raven/config.toml; removing it records '
        "`optional = []` and Raven stops writing the server into .mcp.json, .codex/config.toml "
        "and .gemini/settings.json (a file you have edited is not rewritten; it gets a "
        "guided-merge artifact instead)."
    )
    hint = SERVER_HINTS.get(name)
    if hint:
        print(hint)
    while True:
        try:
            answer = input(f"Keep {name}? [Y/n]: ").strip().lower()
        except EOFError:
            return True
        if answer in {"", "y", "yes"}:
            return True
        if answer in {"n", "no"}:
            return False
        print("  Enter y or n.")


def decide_optional_mcp(
    destination: Path,
    config: RavenConfig,
    catalog: Iterable[str],
    *,
    keep: Iterable[str] = (),
    drop: Iterable[str] = (),
    dry_run: bool,
    ask: Callable[[str], bool] = prompt_to_keep_optional_server,
    interactive: bool | None = None,
) -> OptionalMcpDecision:
    """Resolve the effective `[mcp] optional` list for an upgrade.

    Flags (``keep``/``drop``) always apply and always count as a decision. With no
    flag and no recorded decision, every catalog server that is already configured
    in the repository is *pending*: a live interactive run asks, and every other run
    keeps it. A dry run never asks and never asks to write.
    """
    if interactive is None:
        interactive = sys.stdin.isatty()
    catalog = list(catalog)
    keep = set(keep)
    drop = set(drop)
    names = set(config.optional_mcp or ())
    names |= keep
    names -= drop
    flagged = bool(keep or drop)

    pending: list[str] = []
    kept_unasked: list[str] = []
    if config.optional_mcp is None:
        configured = servers_configured_in(destination)
        pending = [n for n in catalog if n in configured and n not in keep and n not in drop]
        for name in pending:
            if dry_run:
                names.add(name)
                kept_unasked.append(name)
            elif interactive:
                if ask(name):
                    names.add(name)
            else:
                names.add(name)
                kept_unasked.append(name)

    ordered = [n for n in catalog if n in names]
    write = not dry_run and (flagged or bool(pending))
    return OptionalMcpDecision(
        names=ordered, write=write, pending=pending, kept_unasked=kept_unasked
    )
