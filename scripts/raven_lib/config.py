from __future__ import annotations

import fnmatch
import re
from pathlib import Path
from textwrap import dedent

from .constants import (
    CLAUDE_COMPONENT_PATHS,
    CODEX_COMPONENT_PATHS,
    COMPONENT_PATHS,
    CONFIG_PATH,
    DEFAULT_CLAUDE_COMPONENTS,
    DEFAULT_CODEX_COMPONENTS,
    DEFAULT_COMPONENTS,
)
from .models import RavenConfig

_ISSUE_TRACKER_SECTION_RE = re.compile(r"^\s*\[([^\]]+)\]")
_PLATFORM_LINE_RE = re.compile(r"^\s*platform\s*=")


def strip_comment(line: str) -> str:
    in_quote = False
    escaped = False
    result = []
    for char in line:
        if escaped:
            result.append(char)
            escaped = False
            continue
        if char == "\\" and in_quote:
            result.append(char)
            escaped = True
            continue
        if char == '"':
            in_quote = not in_quote
            result.append(char)
            continue
        if char == "#" and not in_quote:
            break
        result.append(char)
    return "".join(result).strip()


def parse_value(value: str):
    value = value.strip()
    if value in {"true", "false"}:
        return value == "true"
    if value.startswith('"') and value.endswith('"'):
        return value[1:-1]
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [
            parse_value(part.strip().rstrip(","))
            for part in inner.split(",")
            if part.strip().rstrip(",")
        ]
    try:
        return int(value)
    except ValueError:
        return value


def parse_simple_toml(text: str) -> dict:
    data: dict[str, object] = {}
    section: str | None = None
    lines: list[str] = []
    pending = ""
    for raw_line in text.splitlines():
        line = strip_comment(raw_line)
        if not line:
            continue
        if pending:
            pending = f"{pending} {line}"
            if "]" in line:
                lines.append(pending)
                pending = ""
            continue
        if "=" in line and "[" in line and "]" not in line:
            pending = line
            continue
        lines.append(line)
    if pending:
        lines.append(pending)

    for line in lines:
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip()
            data.setdefault(section, {})
            continue
        if "=" not in line:
            continue
        key, value = [part.strip() for part in line.split("=", 1)]
        target = data if section is None else data.setdefault(section, {})
        if isinstance(target, dict):
            target[key] = parse_value(value)
    return data


def load_config(destination: Path) -> RavenConfig:
    path = destination / CONFIG_PATH
    if not path.exists():
        return RavenConfig(
            template=None,
            include_readme=False,
            components=DEFAULT_COMPONENTS.copy(),
            claude_components=DEFAULT_CLAUDE_COMPONENTS.copy(),
            codex_components=DEFAULT_CODEX_COMPONENTS.copy(),
            exclude_paths=[],
            exists=False,
        )
    try:
        raw = parse_simple_toml(path.read_text(encoding="utf-8"))
    except Exception:
        return RavenConfig(
            template=None,
            include_readme=False,
            components=DEFAULT_COMPONENTS.copy(),
            claude_components=DEFAULT_CLAUDE_COMPONENTS.copy(),
            codex_components=DEFAULT_CODEX_COMPONENTS.copy(),
            exclude_paths=[],
            exists=True,
        )

    raw_components = raw.get("components")
    overrides = (
        {k: v for k, v in raw_components.items() if k in DEFAULT_COMPONENTS and isinstance(v, bool)}
        if isinstance(raw_components, dict)
        else {}
    )
    components = {**DEFAULT_COMPONENTS, **overrides}
    raw_claude_components = raw.get("components.claude")
    claude_overrides = (
        {
            k: v
            for k, v in raw_claude_components.items()
            if k in DEFAULT_CLAUDE_COMPONENTS and isinstance(v, bool)
        }
        if isinstance(raw_claude_components, dict)
        else {}
    )
    claude_components = {**DEFAULT_CLAUDE_COMPONENTS, **claude_overrides}
    raw_codex_components = raw.get("components.codex")
    codex_overrides = (
        {
            k: v
            for k, v in raw_codex_components.items()
            if k in DEFAULT_CODEX_COMPONENTS and isinstance(v, bool)
        }
        if isinstance(raw_codex_components, dict)
        else {}
    )
    codex_components = {**DEFAULT_CODEX_COMPONENTS, **codex_overrides}

    exclude_paths: list[str] = []
    raw_exclude = raw.get("exclude")
    if isinstance(raw_exclude, dict):
        paths = raw_exclude.get("paths")
        if isinstance(paths, list):
            exclude_paths = [str(p).replace("\\", "/") for p in paths if isinstance(p, str)]

    template = raw.get("template")
    include_readme = raw.get("include_readme", False)
    raw_issue_tracker = raw.get("issue_tracker")
    raw_platform = (
        raw_issue_tracker.get("platform")
        if isinstance(raw_issue_tracker, dict)
        else None
    )
    platform = raw_platform if isinstance(raw_platform, str) else "none"
    return RavenConfig(
        template=template if isinstance(template, str) else None,
        include_readme=bool(include_readme),
        components=components,
        claude_components=claude_components,
        codex_components=codex_components,
        exclude_paths=exclude_paths,
        platform=platform,
        exists=True,
    )


def default_config_text(template_name: str, include_readme: bool, platform: str = "none") -> str:
    include = str(include_readme).lower()
    return dedent(
        f"""\
        # Raven configuration for this repository.
        #
        # This file is intended to be edited by the destination project.
        # Raven reads it when the raven CLI is run without a language argument.
        # Machine-written install/upgrade state lives separately in .raven/manifest.json.

        # Config schema version. Keep this as 1 unless a future Raven release says otherwise.
        schema = 1

        # Language template to apply by default when no language is passed on the command line.
        # Supported values are the language directories in the Raven repo, such as python, swift, rust,
        # typescript, and elixir.
        template = "{template_name}"

        # Include the language template README.md when applying Raven.
        # Usually false because README.md explains the template itself rather than agent behavior
        # that belongs in the destination repository.
        include_readme = {include}

        [components]
        # Root instruction files: AGENTS.md and CLAUDE.md.
        # Turn this off if your repository owns those files and you only want lower-level Raven pieces.
        root_instructions = true

        # Reusable on-demand procedures under .agents/skills/raven-* plus the .claude/skills
        # compatibility symlink.
        skills = true

        # Subagent definitions for enabled agent compatibility layers.
        agents = true

        # Hook scripts and hook wiring for enabled agent compatibility layers.
        # Turn this off if your team does not want Raven to install hook enforcement.
        hooks = true

        # Scoped rule files for enabled agent compatibility layers.
        rules = true

        # Agent-facing reference docs under .claude/docs/raven-*.
        docs = true

        # Helper scripts for enabled agent compatibility layers.
        scripts = true

        # MCP example configuration at .mcp.json.
        # Turn this off if your repository already manages MCP separately.
        mcp = true

        # Agent client settings/config files for enabled compatibility layers.
        settings = true

        # Starter formatter/linter config files for the selected language template.
        # Raven copies these only when the destination path does not already exist.
        # Turn this off if your repository wants to manage all tool configuration manually.
        tool_configs = true

        [components.claude]
        # Claude Code settings at .claude/settings.json, including Raven hook wiring.
        # Turn this off if your repository owns Claude settings and will merge hooks manually.
        settings = true

        # Claude Code hook scripts under .claude/hooks/raven-*.
        hooks = true

        # Claude Code subagent definitions under .claude/agents/raven-*.
        subagents = true

        # Claude Code scoped rule files under .claude/rules/raven-*.
        rules = true

        [components.codex]
        # Codex project config at .codex/config.toml, including MCP and subagent concurrency defaults.
        # Project-local Codex config loads only after the .codex layer is trusted by the user.
        config = true

        # Codex hook wiring and hook scripts under .codex/hooks.json and .codex/hooks/raven-*.
        hooks = true

        # Codex custom agent definitions under .codex/agents/raven-*.toml.
        subagents = true

        # Codex command approval rules under .codex/rules/raven.rules.
        # Codex rules are experimental and complement, not replace, hook guardrails.
        rules = true

        [exclude]
        # Additional template-relative paths to exclude from apply operations.
        # Use exact paths or glob patterns. A trailing /** excludes a directory tree.
        # Examples:
        #   paths = [
        #     ".agents/skills/raven-review-pr/**",
        #     ".claude/agents/raven-security-reviewer.md",
        #   ]
        paths = []

        [lifecycle]
        # Enable checkpoint enforcement hook for raven-project-lifecycle.
        # When true, the PreToolUse hook validates each unit checkpoint before
        # allowing raven-session.py --complete to proceed.
        # Set to false to fall back to instructional-only enforcement.
        checkpoint_enforcement = true

        [issue_tracker]
        # External issue tracker for this project. Controls which issue-tracker
        # workflow skill is active and which CLI raven-tool-bootstrap checks for.
        # This is independent of local session tracking (governed by [lifecycle]).
        #
        # This setting also gates skill installation: raven-github-issues is
        # installed only when platform = "github", and raven-gitlab-issues only
        # when platform = "gitlab".  Neither skill is installed when platform =
        # "none".  Note: upgrade does not remove previously-installed skills.
        #
        # platform = "github"   # use raven-github-issues + gh CLI
        # platform = "gitlab"   # use raven-gitlab-issues + glab CLI
        # platform = "none"     # no external issue tracker
        platform = "{platform}"

        [git_hooks]
        # Strip AI agent attribution trailers (Co-Authored-By, Generated-by) from commit
        # messages before they land in git history.  The commit-msg hook removes lines
        # that name known AI tools or AI provider domains so they never reach the repo.
        # Set to false only if your team intentionally records AI attribution in commits.
        strip_ai_attribution = true
        """
    )


def path_matches(path: str, pattern: str) -> bool:
    normalized = pattern.strip().replace("\\", "/")
    if not normalized:
        return False
    if normalized.endswith("/**"):
        prefix = normalized[:-3]
        return path == prefix or path.startswith(f"{prefix}/")
    return fnmatch.fnmatch(path, normalized)


def _disabled_by_component(
    relative: str,
    components: dict[str, bool],
    component_paths: dict[str, list[str]],
) -> bool:
    for component, enabled in components.items():
        if enabled:
            continue
        for component_path in component_paths.get(component, []):
            if relative == component_path or relative.startswith(f"{component_path}/"):
                return True
    return False


def component_disabled(relative: str, config: RavenConfig) -> bool:
    return any(
        _disabled_by_component(relative, components, component_paths)
        for components, component_paths in [
            (config.components, COMPONENT_PATHS),
            (config.claude_components, CLAUDE_COMPONENT_PATHS),
            (config.codex_components, CODEX_COMPONENT_PATHS),
        ]
    )


_PLATFORM_GATED_SKILLS: dict[str, str] = {
    "raven-github-issues": "github",
    "raven-gitlab-issues": "gitlab",
}


def platform_excluded(relative: str, config: RavenConfig) -> bool:
    """Exclude issue-tracker skills that don't match the configured platform.

    Skills under .agents/skills/<name> (and their derived .claude/skills/<name>
    twins) are gated: raven-github-issues requires platform=github, and
    raven-gitlab-issues requires platform=gitlab.  Both are excluded when
    platform is "none" or unset.  Previously-installed skills are not removed
    by upgrade; this exclusion only prevents new installations.
    """
    for skill_name, required_platform in _PLATFORM_GATED_SKILLS.items():
        skill_prefix_agents = f".agents/skills/{skill_name}"
        skill_prefix_claude = f".claude/skills/{skill_name}"
        is_this_skill = (
            relative == skill_prefix_agents
            or relative.startswith(f"{skill_prefix_agents}/")
            or relative == skill_prefix_claude
            or relative.startswith(f"{skill_prefix_claude}/")
        )
        if is_this_skill and config.platform != required_platform:
            return True
    return False


def config_excluded(relative: str, config: RavenConfig) -> bool:
    if component_disabled(relative, config):
        return True
    if platform_excluded(relative, config):
        return True
    return any(path_matches(relative, pattern) for pattern in config.exclude_paths)


def _update_config_platform(config_path: Path, platform: str) -> None:
    """Replace the active platform value in [issue_tracker] section of config."""
    lines = config_path.read_text(encoding="utf-8").splitlines(keepends=True)
    in_section = False
    new_lines = []
    updated = False
    for line in lines:
        m = _ISSUE_TRACKER_SECTION_RE.match(line)
        if m:
            in_section = m.group(1).strip() == "issue_tracker"
        if (
            in_section
            and not updated
            and _PLATFORM_LINE_RE.match(line)
            and not line.lstrip().startswith("#")
        ):
            new_lines.append(f'platform = "{platform}"\n')
            updated = True
            continue
        new_lines.append(line)
    config_path.write_text("".join(new_lines), encoding="utf-8")
