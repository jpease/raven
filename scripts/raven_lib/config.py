from __future__ import annotations

import fnmatch
import functools
import re
import string
import sys
from pathlib import Path
from typing import TypeAlias

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

# A scalar or list value parsed from the simplified TOML config.
ConfigValue: TypeAlias = bool | int | str | list["ConfigValue"]


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


def parse_value(value: str) -> ConfigValue:
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


def parse_simple_toml(text: str) -> dict[str, object]:
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


def _merge_component_overrides(
    raw: dict, section_key: str, defaults: dict[str, bool]
) -> dict[str, bool]:
    section = raw.get(section_key)
    overrides = (
        {k: v for k, v in section.items() if k in defaults and isinstance(v, bool)}
        if isinstance(section, dict)
        else {}
    )
    return {**defaults, **overrides}


def build_config(raw: dict, *, exists: bool) -> RavenConfig:
    """Build a RavenConfig from a parsed-TOML mapping. Pure; no filesystem access."""
    exclude_paths: list[str] = []
    raw_exclude = raw.get("exclude")
    if isinstance(raw_exclude, dict):
        paths = raw_exclude.get("paths")
        if isinstance(paths, list):
            exclude_paths = [str(p).replace("\\", "/") for p in paths if isinstance(p, str)]

    template = raw.get("template")
    raw_issue_tracker = raw.get("issue_tracker")
    raw_platform = (
        raw_issue_tracker.get("platform") if isinstance(raw_issue_tracker, dict) else None
    )
    platform = raw_platform if isinstance(raw_platform, str) else "none"
    return RavenConfig(
        template=template if isinstance(template, str) else None,
        include_readme=bool(raw.get("include_readme", False)),
        components=_merge_component_overrides(raw, "components", DEFAULT_COMPONENTS),
        claude_components=_merge_component_overrides(
            raw, "components.claude", DEFAULT_CLAUDE_COMPONENTS
        ),
        codex_components=_merge_component_overrides(
            raw, "components.codex", DEFAULT_CODEX_COMPONENTS
        ),
        exclude_paths=exclude_paths,
        platform=platform,
        exists=exists,
    )


def load_config(destination: Path) -> RavenConfig:
    path = destination / CONFIG_PATH
    if not path.exists():
        return build_config({}, exists=False)
    try:
        raw = parse_simple_toml(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(
            f"warning: could not read {path} ({exc}); using default Raven configuration.",
            file=sys.stderr,
        )
        return build_config({}, exists=True)
    return build_config(raw, exists=True)


@functools.lru_cache(maxsize=1)
def _config_template() -> string.Template:
    return string.Template(
        (Path(__file__).parent / "data" / "config.toml.tmpl").read_text(encoding="utf-8")
    )


def default_config_text(template_name: str, include_readme: bool, platform: str = "none") -> str:
    return _config_template().substitute(
        template=template_name,
        include_readme=str(include_readme).lower(),
        platform=platform,
    )


def path_within(path: str, prefix: str) -> bool:
    """Whether ``path`` is ``prefix`` itself or a descendant directory entry of it."""
    return path == prefix or path.startswith(f"{prefix}/")


def path_matches(path: str, pattern: str) -> bool:
    normalized = pattern.strip().replace("\\", "/")
    if not normalized:
        return False
    if normalized.endswith("/**"):
        return path_within(path, normalized[:-3])
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
            if path_within(relative, component_path):
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
        is_this_skill = path_within(relative, f".agents/skills/{skill_name}") or path_within(
            relative, f".claude/skills/{skill_name}"
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


def replace_platform_line(text: str, platform: str) -> str:
    """Return config text with the active [issue_tracker] platform value replaced.

    Pure: rewrites only the first uncommented ``platform =`` line inside the
    ``[issue_tracker]`` section, leaving commented examples and other sections
    untouched.
    """
    new_lines = []
    in_section = False
    updated = False
    for line in text.splitlines(keepends=True):
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
    return "".join(new_lines)


def _update_config_platform(config_path: Path, platform: str) -> None:
    """Replace the active platform value in [issue_tracker] section of config."""
    text = config_path.read_text(encoding="utf-8")
    config_path.write_text(replace_platform_line(text, platform), encoding="utf-8")
