"""Render adapter configuration files deterministically at install time.

Renders `.gemini/settings.json` (and in #271, `.mcp.json` and `.codex/config.toml`)
from shared wiring in `common/` and per-language MCP server definitions.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .constants import MCP_DEFINITION_PATH, REPO_ROOT


def resolve_common_root(template: Path, common_root: Path | None = None) -> Path:
    """Resolve the `common/` directory path, tolerating test fixtures and sibling trees."""
    if common_root is not None:
        return common_root.resolve()
    sibling = template.parent / "common"
    if sibling.is_dir():
        return sibling.resolve()
    return (REPO_ROOT / "common").resolve()


def _extract_mcp_servers(path: Path) -> dict[str, Any]:
    """Parse an MCP JSON file and return its server mapping, tolerating wrapper keys."""
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    if not isinstance(data, dict):
        return {}
    if "mcpServers" in data and isinstance(data["mcpServers"], dict):
        return dict(data["mcpServers"])
    if all(isinstance(v, dict) for v in data.values()):
        return dict(data)
    return {}


def load_mcp_servers(template: Path, common_root: Path | None = None) -> dict[str, Any]:
    """Load per-language MCP servers, merging baseline common servers with template servers.

    Resolution order:
    1. Common baseline: `common/.raven/mcp.json` or fallback `common/.mcp.json`.
    2. Template overrides/additions: `template/.raven/mcp.json` or fallback `template/.mcp.json`.
    """
    common = resolve_common_root(template, common_root)
    common_servers: dict[str, Any] = {}
    for candidate in [common / MCP_DEFINITION_PATH, common / ".mcp.json"]:
        if candidate.is_file():
            common_servers = _extract_mcp_servers(candidate)
            if common_servers:
                break

    template_servers: dict[str, Any] = {}
    for candidate in [template / MCP_DEFINITION_PATH, template / ".mcp.json"]:
        if candidate.is_file():
            try:
                # If template file points to or resolves to the common file, skip duplicating
                if candidate.resolve() in (
                    (common / MCP_DEFINITION_PATH).resolve(),
                    (common / ".mcp.json").resolve(),
                ):
                    continue
            except OSError:
                pass
            template_servers = _extract_mcp_servers(candidate)
            if template_servers:
                break

    merged = dict(common_servers)
    merged.update(template_servers)
    return merged


def load_gemini_base_settings(template: Path, common_root: Path | None = None) -> dict[str, Any]:
    """Load base Gemini settings (hook wiring, etc.) from `common/` and template overrides."""
    common = resolve_common_root(template, common_root)
    base_settings: dict[str, Any] = {}

    common_settings = common / ".gemini" / "settings.json"
    if common_settings.is_file():
        try:
            data = json.loads(common_settings.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                base_settings = dict(data)
        except (json.JSONDecodeError, OSError):
            pass

    template_settings = template / ".gemini" / "settings.json"
    if template_settings.is_file():
        try:
            # If not pointing to common settings, merge template-level overrides
            if template_settings.resolve() != common_settings.resolve():
                data = json.loads(template_settings.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    for k, v in data.items():
                        if k == "mcpServers":
                            continue
                        if isinstance(v, dict) and isinstance(base_settings.get(k), dict):
                            base_settings[k] = {**base_settings[k], **v}
                        else:
                            base_settings[k] = v
        except OSError:
            pass

    return base_settings


def render_gemini_settings(template: Path, common_root: Path | None = None) -> str:
    """Render `.gemini/settings.json` deterministically with sorted keys and 2-space indents."""
    settings = load_gemini_base_settings(template, common_root)
    mcp_servers = load_mcp_servers(template, common_root)
    if mcp_servers:
        settings["mcpServers"] = mcp_servers
    return json.dumps(settings, indent=2, sort_keys=True) + "\n"


def can_render_gemini_settings(template: Path, common_root: Path | None = None) -> bool:
    """Whether inputs exist to render `.gemini/settings.json` for `template`."""
    common = resolve_common_root(template, common_root)
    if (common / ".gemini" / "settings.json").is_file():
        return True
    if (template / ".gemini" / "settings.json").is_file():
        return True
    return bool(load_mcp_servers(template, common_root))
