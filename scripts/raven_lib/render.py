"""Render adapter configuration files deterministically at install time.

Renders `.gemini/settings.json`, `.mcp.json`, and `.codex/config.toml` from
shared wiring in `common/` and per-language MCP server definitions (#265,
#271).
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


def _drop_plugin_covered_lsp(servers: dict[str, Any], template_name: str) -> dict[str, Any]:
    """Remove the `lsp` bridge server for a language with a Claude Code LSP plugin.

    Running the `mcp-language-server` bridge alongside a native Claude Code LSP
    plugin means two LSP clients against one workspace -- measured as several
    gigabytes of duplicate `sourcekit-lsp` processes for Swift
    (`raven-lsp-mcp.md`). Only `render_mcp_json` (Claude Code) calls this.
    `render_codex_config_toml` and `render_gemini_settings` always want the
    bridge: neither harness has a plugin alternative to avoid duplicating
    (#271).
    """
    if template_name not in CLAUDE_LSP_PLUGIN_TEMPLATES or "lsp" not in servers:
        return servers
    return {name: value for name, value in servers.items() if name != "lsp"}


def render_gemini_settings(template: Path, common_root: Path | None = None) -> str:
    """Render `.gemini/settings.json` deterministically with sorted keys and 2-space indents.

    Every MCP server, always -- Gemini CLI has no marketplace LSP plugin
    ecosystem to avoid duplicating, so it gets the same unfiltered set
    `render_codex_config_toml` does, unlike `render_mcp_json`.
    """
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


def render_mcp_json(template: Path, common_root: Path | None = None) -> str:
    """Render `.mcp.json` deterministically, preserving common-then-template key order.

    `json.dumps` without `sort_keys` walks a dict in insertion order, which is
    also what `load_mcp_servers` produces: every common baseline server (in
    the order `common/.raven/mcp.json` declares them), then every per-language
    addition not already present. That is what makes this byte-identical to
    the checked-in per-language `.mcp.json` files it replaces (#271) -- sorting
    keys would reorder `semgrep`/`gitnexus` alphabetically and break that.
    """
    servers = _drop_plugin_covered_lsp(load_mcp_servers(template, common_root), template.name)
    return json.dumps({"mcpServers": servers}, indent=2) + "\n"


def can_render_mcp_json(template: Path, common_root: Path | None = None) -> bool:
    """Whether inputs exist to render `.mcp.json` for `template`."""
    return bool(_drop_plugin_covered_lsp(load_mcp_servers(template, common_root), template.name))


#: Templates with a Claude Code marketplace LSP plugin (`raven-lsp-mcp.md`'s
#: "Provider on Claude Code" column). `.mcp.json` and `.gemini/settings.json`
#: exclude the `mcp-language-server` bridge for these; `.codex/config.toml`
#: always includes it, since Codex has no plugin alternative at all.
CLAUDE_LSP_PLUGIN_TEMPLATES = frozenset(
    {"python", "typescript", "rust", "swift", "go", "lua", "ruby"}
)

#: The `# Raven Codex project configuration for {description}` phrase per
#: template, the one hand-authored part of `.codex/config.toml` with no other
#: machine-readable source (it is prose, read by a human trusting the
#: project, not by Codex).
CODEX_CONFIG_DESCRIPTIONS = {
    "python": "Python repositories.",
    "typescript": "TypeScript repositories.",
    "rust": "Rust repositories.",
    "swift": "Swift repositories.",
    "go": "Go repositories.",
    "lua": "Lua repositories.",
    "ruby": "Ruby repositories.",
    "elixir": "Elixir repositories.",
    "generic": "repositories with no language stack.",
    "dotfiles": "dotfiles / home-directory config.",
}


def _toml_string(value: str) -> str:
    """A TOML basic string literal. JSON and TOML basic-string escaping agree
    on quote/backslash/control-character handling, so `json.dumps` is exact
    for the plain command/argument tokens this renders.
    """
    return json.dumps(value)


def _toml_mcp_server_table(name: str, server: dict[str, Any]) -> str:
    lines = [f"[mcp_servers.{name}]"]
    command = server.get("command")
    if isinstance(command, str):
        lines.append(f"command = {_toml_string(command)}")
    args = server.get("args")
    if isinstance(args, list):
        rendered_args = ", ".join(_toml_string(a) for a in args if isinstance(a, str))
        lines.append(f"args = [{rendered_args}]")
    return "\n".join(lines)


def render_codex_config_toml(template: Path, common_root: Path | None = None) -> str:
    """Render `.codex/config.toml` deterministically: every MCP server, always.

    Unlike `.mcp.json`/`.gemini/settings.json`, this never drops the `lsp`
    bridge for a plugin-covered language -- Codex has no plugin mechanism, so
    `.codex/config.toml` is the one place every template's `mcp-language-
    server` entry always lands (#271).
    """
    description = CODEX_CONFIG_DESCRIPTIONS.get(template.name, f"{template.name} repositories.")
    servers = load_mcp_servers(template, common_root)
    sections = [_toml_mcp_server_table(name, server) for name, server in servers.items()]
    body = "\n\n".join(sections)
    header = (
        f"# Raven Codex project configuration for {description}\n"
        "# Project-local Codex config loads only after the project .codex layer is trusted.\n"
        "\n"
        "[agents]\n"
        "max_concurrent_threads_per_session = 4"
    )
    return f"{header}\n\n{body}\n" if body else f"{header}\n"


def can_render_codex_config_toml(template: Path, common_root: Path | None = None) -> bool:
    """Whether inputs exist to render `.codex/config.toml` for `template`."""
    return bool(load_mcp_servers(template, common_root)) or template.name in (
        CODEX_CONFIG_DESCRIPTIONS
    )
