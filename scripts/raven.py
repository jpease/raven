#!/usr/bin/env python3

from __future__ import annotations

import argparse
import filecmp
import fnmatch
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from textwrap import dedent

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EXCLUDES = {"README.md"}
EXCLUDED_NAMES = {".DS_Store", ".ruff_cache", "__pycache__"}
CONFIG_PATH = Path(".raven") / "config.toml"
MANIFEST_PATH = Path(".raven") / "manifest.json"
MERGE_DIR = Path(".raven") / "merge"
ROOT_INSTRUCTION_FILES = {"AGENTS.md", "CLAUDE.md"}
CLAUDE_PATH = "CLAUDE.md"
CLAUDE_BACKUP_PATH = "CLAUDE.md.bak"
RAVEN_BLOCK_BEGIN = "<!-- RAVEN:BEGIN -->"
RAVEN_BLOCK_BEGIN_RE = re.compile(r"<!-- RAVEN:BEGIN(?: sha256=([a-f0-9]{64}))? -->")
RAVEN_BLOCK_END = "<!-- RAVEN:END -->"
DEFAULT_COMPONENTS = {
    "root_instructions": True,
    "skills": True,
    "agents": True,
    "hooks": True,
    "rules": True,
    "docs": True,
    "scripts": True,
    "mcp": True,
    "settings": True,
    "tool_configs": True,
}
DEFAULT_CLAUDE_COMPONENTS = {
    "settings": True,
    "hooks": True,
    "subagents": True,
    "rules": True,
}
DEFAULT_CODEX_COMPONENTS = {
    "config": True,
    "hooks": True,
    "subagents": True,
    "rules": True,
}
COMPONENT_PATHS = {
    "root_instructions": ["AGENTS.md", "CLAUDE.md"],
    "skills": [".agents/skills", ".claude/skills"],
    "agents": [".claude/agents", ".codex/agents"],
    "hooks": [".claude/hooks", ".codex/hooks", ".codex/hooks.json"],
    "rules": [".claude/rules", ".codex/rules"],
    "docs": [".claude/docs"],
    "scripts": [".claude/scripts", ".codex/scripts"],
    "mcp": [".mcp.json"],
    "settings": [".claude/settings.json", ".codex/config.toml"],
    "tool_configs": [
        ".credo.exs",
        ".formatter.exs",
        ".swift-format",
        ".swiftlint.yml",
        "eslint.config.mjs",
        "prettier.config.mjs",
        "pyproject.toml",
        "rustfmt.toml",
    ],
}
STARTER_TOOL_CONFIG_PATHS = set(COMPONENT_PATHS["tool_configs"])
CLAUDE_COMPONENT_PATHS = {
    "settings": [".claude/settings.json"],
    "hooks": [".claude/hooks", ".claude/scripts"],
    "subagents": [".claude/agents"],
    "rules": [".claude/rules"],
}
CODEX_COMPONENT_PATHS = {
    "config": [".codex/config.toml"],
    "hooks": [".codex/hooks", ".codex/hooks.json", ".codex/scripts"],
    "subagents": [".codex/agents"],
    "rules": [".codex/rules"],
}
NON_TEMPLATE_DIRS = {"common", "scripts", "tests", "docs", "project-skills"}
KIND_FILE = "file"
KIND_SYMLINK = "symlink"


def _any_exists(p: Path) -> bool:
    return p.exists() or p.is_symlink()


@dataclass(frozen=True)
class TemplateEntry:
    relative: str
    source: Path
    copy_as_symlink: bool = False


@dataclass(frozen=True)
class RavenConfig:
    template: str | None
    include_readme: bool
    components: dict[str, bool]
    claude_components: dict[str, bool]
    codex_components: dict[str, bool]
    exclude_paths: list[str]
    exists: bool = False


@dataclass(frozen=True)
class RavenBlock:
    start: int
    end: int
    content: str
    declared_sha256: str | None


@dataclass(frozen=True)
class Classification:
    will_copy: list[str]
    will_upgrade: list[str]
    identical: list[str]
    needs_merge: list[str]
    unknown_existing: list[str]
    excluded: list[str]


@dataclass(frozen=True)
class ApplyPlan:
    requested_overrides: list[str]
    overwritten: list[str]
    newly_copied_overrides: list[str]
    will_copy: list[str]
    will_upgrade: list[str]
    identical: list[str]
    needs_merge: list[str]
    unknown_existing: list[str]
    effective_classification: Classification
    adopt_claude_symlink: bool
    guided_merge_paths: list[str]

    @property
    def copied(self) -> list[str]:
        return self.will_copy + self.newly_copied_overrides


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
    return RavenConfig(
        template=template if isinstance(template, str) else None,
        include_readme=bool(include_readme),
        components=components,
        claude_components=claude_components,
        codex_components=codex_components,
        exclude_paths=exclude_paths,
        exists=True,
    )


def default_config_text(template_name: str, include_readme: bool) -> str:
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


def config_excluded(relative: str, config: RavenConfig) -> bool:
    if component_disabled(relative, config):
        return True
    return any(path_matches(relative, pattern) for pattern in config.exclude_paths)


def is_excluded(
    path: Path, relative: str, explicit_excludes: set[str], config: RavenConfig | None = None
) -> bool:
    if relative in explicit_excludes:
        return True
    if config and config_excluded(relative, config):
        return True
    return any(part in EXCLUDED_NAMES for part in path.parts)


def should_preserve_symlink(path: Path) -> bool:
    if not path.is_symlink():
        return False
    target = os.readlink(path).replace("\\", "/")
    return not re.match(r"(\.\./)+common/", target)


def iter_template_entries(
    template: Path, excludes: set[str], config: RavenConfig | None = None
) -> list[TemplateEntry]:
    entries: dict[str, TemplateEntry] = {}

    for root, dirnames, filenames in os.walk(template, followlinks=True):
        root_path = Path(root)
        kept_dirnames = []
        for dirname in dirnames:
            path = root_path / dirname
            relative = path.relative_to(template).as_posix()
            if is_excluded(path, relative, excludes, config):
                continue
            if should_preserve_symlink(path):
                entries[relative] = TemplateEntry(
                    relative=relative, source=path, copy_as_symlink=True
                )
                continue
            kept_dirnames.append(dirname)
        dirnames[:] = kept_dirnames

        for filename in filenames:
            path = root_path / filename
            relative = path.relative_to(template).as_posix()
            if is_excluded(path, relative, excludes, config):
                continue
            entries[relative] = TemplateEntry(
                relative=relative,
                source=path,
                copy_as_symlink=should_preserve_symlink(path),
            )

    return [entries[key] for key in sorted(entries)]


def entries_for_destination(
    template: Path,
    excludes: set[str],
    config: RavenConfig | None,
    destination: Path,
) -> dict[str, TemplateEntry]:
    entries = {entry.relative: entry for entry in iter_template_entries(template, excludes, config)}
    for relative in STARTER_TOOL_CONFIG_PATHS:
        if relative in entries and _any_exists(destination / relative):
            entries.pop(relative)

    skills_entry = entries.get(".claude/skills")
    target = destination / ".claude" / "skills"
    if (
        skills_entry
        and skills_entry.copy_as_symlink
        and target.exists()
        and target.is_dir()
        and not target.is_symlink()
    ):
        entries.pop(".claude/skills")
        for relative, entry in list(entries.items()):
            if relative.startswith(".agents/skills/") and not entry.copy_as_symlink:
                suffix = relative.removeprefix(".agents/skills/")
                entries[f".claude/skills/{suffix}"] = TemplateEntry(
                    relative=f".claude/skills/{suffix}",
                    source=entry.source,
                    copy_as_symlink=False,
                )
    return {key: entries[key] for key in sorted(entries)}


def same_content(entry: TemplateEntry, target: Path) -> bool:
    if entry.copy_as_symlink:
        return target.is_symlink() and os.readlink(target) == os.readlink(entry.source)
    if not target.is_file():
        return False
    return filecmp.cmp(entry.source, target, shallow=False)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _symlink_fingerprint(target: str) -> dict[str, str]:
    return {
        "kind": KIND_SYMLINK,
        "target": target,
        "sha256": sha256_bytes(f"symlink:{target}".encode()),
    }


def entry_fingerprint(entry: TemplateEntry) -> dict[str, str]:
    if entry.copy_as_symlink:
        return _symlink_fingerprint(os.readlink(entry.source))
    return {
        "kind": KIND_FILE,
        "sha256": file_sha256(entry.source),
    }


def destination_fingerprint(path: Path) -> dict[str, str] | None:
    if path.is_symlink():
        return _symlink_fingerprint(os.readlink(path))
    if path.is_file():
        return {
            "kind": KIND_FILE,
            "sha256": file_sha256(path),
        }
    return None


def normalized_block_content(text: str) -> str:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    return "\n".join(line.rstrip() for line in lines).strip("\n")


def _is_markdown_table_separator_cell(cell: str) -> bool:
    stripped = cell.strip()
    if len(stripped) < 3:
        return False
    inner = stripped.strip(":")
    return bool(inner) and set(inner) == {"-"}


def _normalize_markdown_table_separator(line: str) -> str | None:
    stripped = line.strip()
    if not stripped.startswith("|") or not stripped.endswith("|"):
        return None
    cells = stripped.strip("|").split("|")
    if not cells or not all(_is_markdown_table_separator_cell(cell) for cell in cells):
        return None
    normalized_cells: list[str] = []
    for cell in cells:
        value = cell.strip()
        left = ":" if value.startswith(":") else ""
        right = ":" if value.endswith(":") else ""
        normalized_cells.append(f"{left}---{right}")
    return "|" + "|".join(normalized_cells) + "|"


def comparison_block_content(text: str) -> str:
    normalized_lines: list[str] = []
    for line in normalized_block_content(text).split("\n"):
        table_separator = _normalize_markdown_table_separator(line)
        normalized_lines.append(table_separator if table_separator is not None else line)
    return "".join("".join(normalized_lines).split())


def block_content_matches(left: str, right: str) -> bool:
    return comparison_block_content(left) == comparison_block_content(right)


def raven_block_sha256(text: str) -> str:
    return sha256_bytes(normalized_block_content(text).encode("utf-8"))


def raven_block_begin_for(text: str) -> str:
    return f"<!-- RAVEN:BEGIN sha256={raven_block_sha256(text)} -->"


def raven_managed_block(text: str) -> str:
    content = normalized_block_content(text)
    return "\n".join(["", raven_block_begin_for(content), *content.splitlines(), RAVEN_BLOCK_END])


def find_raven_block(text: str) -> RavenBlock | None:
    lines = text.splitlines()
    for start, line in enumerate(lines):
        match = RAVEN_BLOCK_BEGIN_RE.fullmatch(line.strip())
        if not match:
            continue
        for end in range(start + 1, len(lines)):
            if lines[end].strip() == RAVEN_BLOCK_END:
                return RavenBlock(
                    start=start,
                    end=end,
                    content="\n".join(lines[start + 1 : end]),
                    declared_sha256=match.group(1),
                )
        return None
    return None


def raven_block_is_unchanged(block: RavenBlock) -> bool:
    return block.declared_sha256 == raven_block_sha256(block.content)


def block_managed_state(entry: TemplateEntry, target: Path) -> str | None:
    if (
        entry.relative not in ROOT_INSTRUCTION_FILES
        or entry.copy_as_symlink
        or not target.is_file()
    ):
        return None
    block = find_raven_block(target.read_text(encoding="utf-8"))
    if block is None:
        return None
    source_text = normalized_block_content(entry.source.read_text(encoding="utf-8"))
    block_text = normalized_block_content(block.content)
    if block_text == source_text:
        return "identical" if raven_block_is_unchanged(block) else "upgradeable"
    if block_content_matches(block_text, source_text):
        return "upgradeable"
    if not raven_block_is_unchanged(block):
        return "modified"
    return "upgradeable"


def update_raven_block(entry: TemplateEntry, target: Path) -> None:
    text = target.read_text(encoding="utf-8")
    block = find_raven_block(text)
    source_text = normalized_block_content(entry.source.read_text(encoding="utf-8"))
    if block is None or (
        not raven_block_is_unchanged(block)
        and not block_content_matches(block.content, source_text)
    ):
        raise ValueError(f"cannot safely update modified or missing Raven block: {entry.relative}")
    lines = text.splitlines()
    replacement = raven_managed_block(entry.source.read_text(encoding="utf-8")).splitlines()[1:]
    updated = lines[: block.start] + replacement + lines[block.end + 1 :]
    trailing_newline = "\n" if text.endswith("\n") else ""
    target.write_text("\n".join(updated) + trailing_newline, encoding="utf-8")


def load_manifest(destination: Path) -> dict:
    path = destination / MANIFEST_PATH
    if not path.exists():
        return {"schema": 1, "files": {}}
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"schema": 1, "files": {}}
    if not isinstance(manifest, dict):
        return {"schema": 1, "files": {}}
    if not isinstance(manifest.get("files"), dict):
        manifest["files"] = {}
    return manifest


def git_ref() -> str:
    result = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "rev-parse", "--short=12", "HEAD"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        return result.stdout.strip()
    return "unknown"


def save_manifest(destination: Path, manifest: dict) -> None:
    path = destination / MANIFEST_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _make_manifest_record(entry: TemplateEntry, target: Path) -> dict[str, str] | None:
    installed = destination_fingerprint(target)
    if installed is None:
        return None
    base: dict[str, str] = {
        "kind": installed["kind"],
        "sourceSha256": entry_fingerprint(entry)["sha256"],
        "installedSha256": installed["sha256"],
    }
    return {**base, "target": installed["target"]} if installed["kind"] == KIND_SYMLINK else base


def update_manifest(
    destination: Path,
    template_name: str,
    template: Path,
    excludes: set[str],
    config: RavenConfig,
    paths: list[str],
    manifest: dict | None = None,
    entries: dict[str, TemplateEntry] | None = None,
) -> None:
    if manifest is None:
        manifest = load_manifest(destination)
    manifest["schema"] = 1
    manifest["template"] = template_name
    manifest["ravenVersion"] = git_ref()
    manifest["updatedAt"] = datetime.now(timezone.utc).isoformat()
    manifest.setdefault("files", {})

    if entries is None:
        entries = entries_for_destination(template, excludes, config, destination)
    new_records = {
        relative: record
        for relative in sorted(set(paths))
        if (entry := entries.get(relative)) is not None
        if (record := _make_manifest_record(entry, destination / relative)) is not None
    }
    manifest["files"].update(new_records)

    save_manifest(destination, manifest)


def manifest_allows_upgrade(manifest: dict, relative: str, target: Path) -> bool:
    record = manifest.get("files", {}).get(relative)
    if not isinstance(record, dict):
        return False
    current_state = destination_fingerprint(target)
    if not current_state:
        return False
    if current_state.get("kind") != record.get("kind"):
        return False
    if current_state["kind"] == KIND_SYMLINK and current_state.get("target") != record.get(
        "target"
    ):
        return False
    return current_state["sha256"] == record.get("installedSha256")


def _classify_entry(entry: TemplateEntry, destination: Path, manifest: dict) -> str:
    target = destination / entry.relative
    if not _any_exists(target):
        return "will_copy"
    if same_content(entry, target):
        return "identical"
    block_state = block_managed_state(entry, target)
    if block_state == "identical":
        return "identical"
    if block_state == "upgradeable":
        return "will_upgrade"
    if block_state == "modified":
        return "needs_merge"
    if manifest_allows_upgrade(manifest, entry.relative, target):
        return "will_upgrade"
    if entry.relative in manifest.get("files", {}):
        return "needs_merge"
    return "unknown_existing"


def classify(
    template: Path,
    destination: Path,
    excludes: set[str],
    config: RavenConfig | None = None,
    manifest: dict | None = None,
    entries: dict[str, TemplateEntry] | None = None,
) -> Classification:
    if manifest is None:
        manifest = load_manifest(destination)

    entry_iter = (
        entries.values()
        if entries is not None
        else iter_template_entries(template, excludes, config)
    )
    groups: dict[str, list[str]] = {
        "will_copy": [],
        "will_upgrade": [],
        "identical": [],
        "needs_merge": [],
        "unknown_existing": [],
    }
    for entry in entry_iter:
        groups[_classify_entry(entry, destination, manifest)].append(entry.relative)

    return Classification(
        **groups,
        excluded=sorted(set(excludes) | set(config.exclude_paths if config else [])),
    )


def copy_paths(
    template: Path,
    destination: Path,
    paths: list[str],
    config: RavenConfig | None = None,
    entries: dict[str, TemplateEntry] | None = None,
    update_managed_blocks: bool = False,
) -> None:
    if entries is None:
        entries = entries_for_destination(template, set(), config, destination)
    for relative in paths:
        entry = entries[relative]
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if update_managed_blocks and block_managed_state(entry, target) == "upgradeable":
            update_raven_block(entry, target)
        elif entry.copy_as_symlink:
            if _any_exists(target):
                target.unlink()
            target.symlink_to(os.readlink(entry.source))
        else:
            shutil.copy2(entry.source, target, follow_symlinks=True)


def claude_symlink_adoption_needed(destination: Path, entries: dict[str, TemplateEntry]) -> bool:
    entry = entries.get(CLAUDE_PATH)
    target = destination / CLAUDE_PATH
    if entry is None or not entry.copy_as_symlink or not _any_exists(target):
        return False
    return not (target.is_symlink() and os.readlink(target) == os.readlink(entry.source))


def adopt_claude_symlink(destination: Path, entries: dict[str, TemplateEntry]) -> list[str]:
    entry = entries.get(CLAUDE_PATH)
    if entry is None or not entry.copy_as_symlink:
        raise ValueError("CLAUDE.md is not configured as a Raven symlink in this template")
    target = destination / CLAUDE_PATH
    backup = destination / CLAUDE_BACKUP_PATH
    if not _any_exists(target):
        target.symlink_to(os.readlink(entry.source))
        return [CLAUDE_PATH]
    if target.is_symlink() and os.readlink(target) == os.readlink(entry.source):
        return []
    if _any_exists(backup):
        raise FileExistsError(
            f"refusing to adopt CLAUDE.md because {CLAUDE_BACKUP_PATH} already exists"
        )
    target.rename(backup)
    target.symlink_to(os.readlink(entry.source))
    return [CLAUDE_BACKUP_PATH, CLAUDE_PATH]


def prompt_for_claude_symlink_adoption(destination: Path) -> bool:
    if not sys.stdin.isatty():
        return False
    print(
        "Raven uses AGENTS.md as the canonical agent instructions file and normally installs "
        "CLAUDE.md as a symlink to AGENTS.md."
    )
    print(f"This repository already has {destination / CLAUDE_PATH}.")
    print(
        f"Choose whether to leave it untouched or move it to {CLAUDE_BACKUP_PATH} and create the symlink."
    )
    while True:
        try:
            answer = input("Adopt CLAUDE.md symlink? [y/N]: ").strip().lower()
        except EOFError:
            return False
        if answer in {"", "n", "no"}:
            return False
        if answer in {"y", "yes"}:
            return True
        print("  Enter y or n.")


def template_entry_text(entry: TemplateEntry) -> str:
    if entry.copy_as_symlink:
        target = os.readlink(entry.source)
        return (
            f"# Raven suggested handling for `{entry.relative}`\n\n"
            f"Raven normally installs `{entry.relative}` as a symlink to `{target}`.\n\n"
            "Because this file already exists in the destination repository, Raven did not replace it. "
            "Review the existing file and decide whether to keep it, merge guidance from AGENTS.md, "
            "or manually convert it to the symlink/pointer your agent tooling expects.\n"
        )
    return entry.source.read_text(encoding="utf-8")


def append_patch_text(relative: str, existing_text: str, raven_text: str) -> str:
    existing_lines = existing_text.splitlines()
    block_lines = raven_managed_block(raven_text).splitlines()
    start = len(existing_lines) + 1
    count = len(block_lines)
    patch_lines = [
        f"--- a/{relative}",
        f"+++ b/{relative}",
        f"@@ -{len(existing_lines)},0 +{start},{count} @@",
        *[f"+{line}" for line in block_lines],
        "",
    ]
    return "\n".join(patch_lines)


def write_guided_merge_artifacts(
    destination: Path, entries: dict[str, TemplateEntry], paths: list[str]
) -> list[str]:
    written: list[str] = []
    merge_dir = destination / MERGE_DIR
    for relative in sorted(set(paths) & ROOT_INSTRUCTION_FILES):
        entry = entries.get(relative)
        target = destination / relative
        if entry is None or not _any_exists(target):
            continue
        merge_dir.mkdir(parents=True, exist_ok=True)
        raven_path = merge_dir / f"{relative}.raven"
        raven_text = template_entry_text(entry)
        raven_path.write_text(raven_text, encoding="utf-8")
        written.append(raven_path.relative_to(destination).as_posix())

        patch_path = merge_dir / f"{relative}.patch"
        patch_written = False
        if not entry.copy_as_symlink and target.is_file():
            patch_path.write_text(
                append_patch_text(relative, target.read_text(encoding="utf-8"), raven_text),
                encoding="utf-8",
            )
            patch_written = True

        instructions_path = merge_dir / f"{relative}.instructions.md"
        suggestion = raven_path.relative_to(destination).as_posix()
        patch = patch_path.relative_to(destination).as_posix()
        if patch_written:
            body = (
                f"# Guided Raven merge for `{relative}`\n\n"
                f"Raven found an existing `{relative}` and did not modify it.\n\n"
                f"- Existing file: `{relative}`\n"
                f"- Raven suggestion for review: `{suggestion}`\n"
                f"- Append-only patch: `{patch}`\n\n"
                "## Recommended automatic merge\n\n"
                "From the destination repository root, inspect the patch first:\n\n"
                f"```sh\npatch --dry-run -p1 < {patch}\n```\n\n"
                "If the dry run succeeds and the appended Raven guidance is appropriate, apply it:\n\n"
                f"```sh\npatch -p1 < {patch}\n```\n\n"
                "This appends a `RAVEN:BEGIN` / `RAVEN:END` managed block to the existing file. "
                "Future Raven upgrades can update that block automatically as long as it is not edited directly.\n\n"
                "## Manual merge option\n\n"
                f"Review `{suggestion}` and copy only the guidance that applies. If you do this without "
                "the managed block markers, "
                "Raven will not be able to upgrade that content automatically later.\n\n"
                "Do not apply the suggestion blindly if the repository already has stronger local instructions.\n"
            )
        else:
            body = (
                f"# Guided Raven merge for `{relative}`\n\n"
                f"Raven found an existing `{relative}` and did not modify it.\n\n"
                f"- Existing file: `{relative}`\n"
                f"- Raven suggestion for review: `{suggestion}`\n\n"
                "Raven could not generate an automatic text patch for this file. Review the suggestion "
                "and manually merge the guidance that applies.\n\n"
                "Do not apply the suggestion blindly if the repository already has stronger local instructions.\n"
            )
        instructions_path.write_text(body, encoding="utf-8")
        written.append(instructions_path.relative_to(destination).as_posix())
        if patch_written:
            written.append(patch_path.relative_to(destination).as_posix())
    return written


def print_section(title: str, paths: list[str]) -> None:
    print(title)
    if not paths:
        print("  (none)")
        return
    for path in paths:
        print(f"  {path}")


def print_apply_summary(
    copied: list[str],
    upgraded: list[str],
    overwritten: list[str],
    adopted_claude: list[str],
    identical: list[str],
    needs_merge: list[str],
    unknown_existing: list[str],
) -> None:
    print_section(f"Copied {len(copied)} file(s):", copied)

    if upgraded:
        print()
        print_section(f"Upgraded {len(upgraded)} unchanged Raven-managed file(s):", upgraded)

    if overwritten:
        print()
        print_section(f"Overwrote {len(overwritten)} explicitly requested file(s):", overwritten)

    if adopted_claude:
        print()
        print_section(
            "Adopted CLAUDE.md compatibility symlink; original file was backed up:", adopted_claude
        )

    if identical:
        print()
        print_section("Already up to date; not copied:", identical)

    if needs_merge:
        print()
        print_section(
            "!!! Manual merge still required for locally modified Raven-managed files. These were not copied. !!!",
            needs_merge,
        )

    if unknown_existing:
        print()
        print_section(
            "!!! Manual merge still required for existing files not known to be Raven-managed. "
            "These were not copied. !!!",
            unknown_existing,
        )


def print_dry_run_summary(classification: Classification) -> None:
    print_section("Will copy new Raven files:", classification.will_copy)
    print()
    print_section("Will upgrade unchanged Raven-managed files:", classification.will_upgrade)
    print()
    print_section("Already up to date; will not copy:", classification.identical)
    print()
    print_section(
        "Manual merge required; locally modified Raven-managed files:", classification.needs_merge
    )
    print()
    print_section(
        "Manual merge required; existing files not known to be Raven-managed:",
        classification.unknown_existing,
    )
    print()
    print("Preview only. Re-run without --dry-run to copy and upgrade files listed above.")


def _without(paths: list[str], excluded: set[str]) -> list[str]:
    return sorted(set(paths) - excluded)


def build_apply_plan(
    destination: Path,
    classification: Classification,
    requested_overrides: list[str],
    adopt_claude_symlink_requested: bool,
    entries: dict[str, TemplateEntry],
    *,
    dry_run: bool,
    prompt_claude_symlink: bool,
) -> ApplyPlan:
    override_set = set(requested_overrides)
    overwritten = sorted(path for path in requested_overrides if _any_exists(destination / path))
    newly_copied_overrides = sorted(path for path in requested_overrides if path not in overwritten)
    will_copy = _without(classification.will_copy, override_set)
    will_upgrade = _without(classification.will_upgrade, override_set)
    identical = _without(classification.identical, override_set)
    needs_merge = _without(classification.needs_merge, override_set)
    unknown_existing = _without(classification.unknown_existing, override_set)

    adopt_claude_symlink = False
    claude_conflicts = set(needs_merge) | set(unknown_existing)
    if CLAUDE_PATH in claude_conflicts and claude_symlink_adoption_needed(destination, entries):
        if adopt_claude_symlink_requested:
            adopt_claude_symlink = True
        elif not dry_run and prompt_claude_symlink:
            adopt_claude_symlink = prompt_for_claude_symlink_adoption(destination)

    if adopt_claude_symlink:
        needs_merge = [path for path in needs_merge if path != CLAUDE_PATH]
        unknown_existing = [path for path in unknown_existing if path != CLAUDE_PATH]

    effective_classification = Classification(
        will_copy=will_copy,
        will_upgrade=will_upgrade,
        identical=identical,
        needs_merge=needs_merge,
        unknown_existing=unknown_existing,
        excluded=classification.excluded,
    )
    guided_merge_paths = sorted((set(needs_merge) | set(unknown_existing)) & ROOT_INSTRUCTION_FILES)

    return ApplyPlan(
        requested_overrides=requested_overrides,
        overwritten=overwritten,
        newly_copied_overrides=newly_copied_overrides,
        will_copy=will_copy,
        will_upgrade=will_upgrade,
        identical=identical,
        needs_merge=needs_merge,
        unknown_existing=unknown_existing,
        effective_classification=effective_classification,
        adopt_claude_symlink=adopt_claude_symlink,
        guided_merge_paths=guided_merge_paths,
    )


def print_dry_run_plan(
    destination: Path,
    classification: Classification,
    entries: dict[str, TemplateEntry],
    plan: ApplyPlan,
) -> int:
    if plan.requested_overrides:
        print_section("Would overwrite explicitly requested file(s):", plan.overwritten)
        print()
        print_section(
            "Would copy explicitly requested missing file(s):",
            plan.newly_copied_overrides,
        )
        print()
    if plan.adopt_claude_symlink:
        if (destination / CLAUDE_BACKUP_PATH).exists():
            print(
                f"error: {CLAUDE_BACKUP_PATH} already exists; "
                "remove it before adopting the CLAUDE.md symlink.",
                file=sys.stderr,
            )
            return 2
        print_section(
            "Would adopt CLAUDE.md compatibility symlink:", [CLAUDE_BACKUP_PATH, CLAUDE_PATH]
        )
        print()
    print_dry_run_summary(plan.effective_classification)
    if (
        not plan.adopt_claude_symlink
        and CLAUDE_PATH in set(classification.needs_merge) | set(classification.unknown_existing)
        and claude_symlink_adoption_needed(destination, entries)
    ):
        print()
        print(
            "CLAUDE.md exists as a regular destination file. Raven can leave it untouched, "
            "or you can rerun with --adopt-claude-symlink to move it to CLAUDE.md.bak and "
            "create the AGENTS.md symlink."
        )
    if plan.guided_merge_paths:
        print()
        print_section(
            "Would write guided merge artifacts for existing instruction files:",
            plan.guided_merge_paths,
        )
    return 0


def apply_plan(
    destination: Path,
    template_name: str,
    template: Path,
    excludes: set[str],
    config: RavenConfig,
    manifest: dict,
    entries: dict[str, TemplateEntry],
    plan: ApplyPlan,
) -> tuple[int, list[str], list[str]]:
    adopted_claude: list[str] = []
    if plan.adopt_claude_symlink:
        try:
            adopted_claude = adopt_claude_symlink(destination, entries)
        except FileExistsError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2, [], []

    try:
        if plan.requested_overrides:
            copy_paths(template, destination, plan.requested_overrides, config, entries=entries)
        if plan.will_copy:
            copy_paths(template, destination, plan.will_copy, config, entries=entries)
        if plan.will_upgrade:
            copy_paths(
                template,
                destination,
                plan.will_upgrade,
                config,
                entries=entries,
                update_managed_blocks=True,
            )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2, adopted_claude, []

    managed_paths = (
        plan.copied
        + plan.will_upgrade
        + plan.overwritten
        + plan.identical
        + ([CLAUDE_PATH] if adopted_claude else [])
    )
    if managed_paths:
        update_manifest(
            destination,
            template_name,
            template,
            excludes,
            config,
            managed_paths,
            manifest=manifest,
            entries=entries,
        )

    merge_artifacts = write_guided_merge_artifacts(destination, entries, plan.guided_merge_paths)
    return 0, adopted_claude, merge_artifacts


def normalize_override(path: str) -> str:
    normalized = path.strip().replace("\\", "/")
    if normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def list_language_templates() -> list[str]:
    return sorted(
        d.name
        for d in REPO_ROOT.iterdir()
        if d.is_dir() and not d.name.startswith(".") and d.name not in NON_TEMPLATE_DIRS
    )


def select_language_interactively() -> str:
    if not sys.stdin.isatty():
        print(
            "error: language required; pass it as an argument (e.g. raven install python)",
            file=sys.stderr,
        )
        sys.exit(2)
    languages = list_language_templates()
    if not languages:
        print("error: no language templates found in Raven repo", file=sys.stderr)
        sys.exit(2)
    print("Available language templates:")
    for i, lang in enumerate(languages, 1):
        print(f"  {i}. {lang}")
    while True:
        try:
            raw = input("Select language: ").strip()
            idx = int(raw) - 1
            if 0 <= idx < len(languages):
                return languages[idx]
        except (ValueError, EOFError):
            pass
        print(f"  Enter a number between 1 and {len(languages)}.")


def _parse_install_language(items: list[str]) -> tuple[str | None, list[str]]:
    if not items:
        return None, []
    first = items[0]
    candidate = REPO_ROOT / first
    if candidate.is_dir() and first not in NON_TEMPLATE_DIRS and not first.startswith("."):
        return first, items[1:]
    return None, items


def _run(
    destination: Path,
    template_name: str,
    include_readme: bool,
    dry_run: bool,
    requested_overrides: list[str],
    adopt_claude_symlink_requested: bool = False,
    prompt_claude_symlink: bool = True,
) -> int:
    config = load_config(destination)
    template = REPO_ROOT / template_name
    excludes = set() if include_readme else DEFAULT_EXCLUDES

    if not template.is_dir():
        print(f"Unknown language template: {template_name}", file=sys.stderr)
        return 2

    requested_overrides_norm = sorted(
        {n for path in requested_overrides if (n := normalize_override(path))}
    )
    entries = entries_for_destination(template, excludes, config, destination)
    invalid_overrides = [path for path in requested_overrides_norm if path not in entries]
    if invalid_overrides:
        print(
            "Invalid override path(s); each override must be an included file in the selected template:",
            file=sys.stderr,
        )
        for path in invalid_overrides:
            print(f"  {path}", file=sys.stderr)
        return 2

    manifest = load_manifest(destination)
    classification = classify(
        template, destination, excludes, config, manifest=manifest, entries=entries
    )
    plan = build_apply_plan(
        destination,
        classification,
        requested_overrides_norm,
        adopt_claude_symlink_requested,
        entries,
        dry_run=dry_run,
        prompt_claude_symlink=prompt_claude_symlink,
    )

    print(f"Template: {template}")
    print(f"Destination: {destination}")
    print(f"Config: {destination / CONFIG_PATH}")
    print()

    if dry_run:
        return print_dry_run_plan(destination, classification, entries, plan)

    rc, adopted_claude, merge_artifacts = apply_plan(
        destination,
        template_name,
        template,
        excludes,
        config,
        manifest,
        entries,
        plan,
    )
    if rc != 0:
        return rc

    print_apply_summary(
        plan.copied,
        plan.will_upgrade,
        plan.overwritten,
        adopted_claude,
        plan.identical,
        plan.needs_merge,
        plan.unknown_existing,
    )
    if merge_artifacts:
        print()
        print_section(
            "Wrote guided merge artifacts for existing instruction files:", merge_artifacts
        )

    return 0


def cmd_init(args: argparse.Namespace) -> int:
    destination = Path(args.destination).expanduser().resolve()
    if not destination.is_dir():
        print(f"error: destination directory does not exist: {destination}", file=sys.stderr)
        return 2
    config = load_config(destination)
    if config.exists:
        print(
            f"error: config already exists at {destination / CONFIG_PATH}; "
            "run `raven upgrade` to update managed files.",
            file=sys.stderr,
        )
        return 2
    language = args.language or select_language_interactively()
    template = REPO_ROOT / language
    if not template.is_dir():
        print(f"error: unknown language template: {language}", file=sys.stderr)
        return 2
    path = destination / CONFIG_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(default_config_text(language, False), encoding="utf-8")
    print(f"Created {destination / CONFIG_PATH}")
    return 0


def cmd_install(args: argparse.Namespace) -> int:
    destination = Path(args.destination).expanduser().resolve()
    if not destination.is_dir():
        print(f"error: destination directory does not exist: {destination}", file=sys.stderr)
        return 2

    install_items = getattr(args, "args", None)
    if install_items is None:
        install_items = ([args.language] if args.language is not None else []) + args.overrides
    language_arg, overrides = _parse_install_language(install_items)
    config = load_config(destination)

    if config.exists:
        template_name = config.template or list_language_templates()[0]
        include_readme = args.include_readme or config.include_readme
    else:
        language = language_arg or select_language_interactively()
        template_name = language
        include_readme = args.include_readme
        if not args.dry_run:
            init_args = argparse.Namespace(destination=str(destination), language=language)
            rc = cmd_init(init_args)
            if rc != 0:
                return rc
            config = load_config(destination)

    return _run(
        destination,
        template_name,
        include_readme,
        args.dry_run,
        overrides,
        adopt_claude_symlink_requested=args.adopt_claude_symlink,
    )


def cmd_upgrade(args: argparse.Namespace) -> int:
    destination = Path(args.destination).expanduser().resolve()
    if not destination.is_dir():
        print(f"error: destination directory does not exist: {destination}", file=sys.stderr)
        return 2
    config = load_config(destination)
    if not config.exists:
        print(
            "error: no .raven/config.toml found; run `raven install <language>` "
            "to set up Raven first.",
            file=sys.stderr,
        )
        return 2
    template_name = config.template or list_language_templates()[0]
    include_readme = args.include_readme or config.include_readme
    return _run(
        destination,
        template_name,
        include_readme,
        args.dry_run,
        args.overrides,
        adopt_claude_symlink_requested=args.adopt_claude_symlink,
    )


def main() -> int:
    supported_languages = ", ".join(list_language_templates())
    parser = argparse.ArgumentParser(
        prog="raven",
        usage="raven [OPTIONS] COMMAND [ARGS]...",
        description="Apply and safely upgrade Raven agent-instruction templates in a destination repository.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
Common commands:
  raven install <language> --dry-run
  raven install <language>
  raven upgrade --dry-run
  raven upgrade
  raven upgrade .claude/scripts/raven-tool-check.py

Supported languages:
  {supported_languages}

Run "raven COMMAND --help" for command-specific arguments and examples.

If this repository's scripts directory is not on PATH yet, use:
  /path/to/raven/scripts/raven install python --dry-run

File safety:
  - Dry runs never write files.
  - Existing project files are not overwritten by default.
  - Explicit override paths force-copy Raven-owned files.
  - Unchanged Raven-managed files can be upgraded automatically.
  - Locally changed Raven-managed files are reported for manual merge.
""",
    )
    parser.add_argument(
        "-d",
        "--destination",
        default=".",
        help="destination repository root; defaults to the current directory",
    )

    subparsers = parser.add_subparsers(
        dest="command", title="commands", metavar="COMMAND", required=True
    )

    init_parser = subparsers.add_parser(
        "init",
        usage="raven init [OPTIONS] [language]",
        help="create .raven/config.toml only",
        description="Create the destination repo's self-documented .raven/config.toml without copying template files.",
    )
    init_parser.add_argument(
        "language",
        nargs="?",
        default=None,
        help="language template (e.g. python, swift, rust, typescript, elixir); prompts interactively if omitted",
    )

    install_parser = subparsers.add_parser(
        "install",
        usage="raven install [OPTIONS] [language] [override ...]",
        help="first-time apply; creates config if needed and copies safe Raven files",
        description=(
            "Install a language template into the destination repo. Run with --dry-run first.\n"
            "Existing files are preserved unless they are explicitly named as override paths or\n"
            "--adopt-claude-symlink is approved for CLAUDE.md."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
Examples:
  raven install python --dry-run
  raven install python
  raven install python --adopt-claude-symlink
  raven install python .claude/scripts/raven-tool-check.py

Language:
  Supported languages: {supported_languages}
  If no config exists, language is required in non-interactive shells.

Overrides:
  Override paths are template-relative files to force-copy. Use them only for
  files you know are Raven-owned.

AGENTS.md and CLAUDE.md:
  AGENTS.md is canonical; CLAUDE.md is normally installed as a symlink to it.
  If CLAUDE.md already exists, Raven leaves it untouched unless you pass
  --adopt-claude-symlink, which moves it to CLAUDE.md.bak first.
""",
    )
    install_parser.add_argument(
        "language",
        nargs="?",
        default=None,
        help="language template to install; prompts interactively if omitted and no config exists",
    )
    install_parser.add_argument(
        "overrides",
        nargs="*",
        metavar="override",
        help="template-relative file paths to force-copy",
    )
    install_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="preview categories, conflicts, and merge artifacts without writing files",
    )
    install_parser.add_argument(
        "--include-readme",
        action="store_true",
        help="include the language template README.md; overrides config include_readme=false",
    )
    install_parser.add_argument(
        "--adopt-claude-symlink",
        action="store_true",
        help=(
            "if CLAUDE.md exists, move it to CLAUDE.md.bak and create the CLAUDE.md -> "
            "AGENTS.md symlink; fails if backup exists"
        ),
    )

    upgrade_parser = subparsers.add_parser(
        "upgrade",
        usage="raven upgrade [OPTIONS] [override ...]",
        help="apply newer Raven template files using manifest-safe upgrade rules",
        description=(
            "Upgrade an existing Raven installation using .raven/config.toml and .raven/manifest.json.\n"
            "Only unchanged Raven-managed files are upgraded automatically; local edits require manual merge."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  raven upgrade --dry-run
  raven upgrade
  raven upgrade --adopt-claude-symlink
  raven upgrade .claude/scripts/raven-tool-check.py

Override paths force-copy specific template-relative files. Use them only for
files you know are Raven-owned.

AGENTS.md and CLAUDE.md:
  AGENTS.md is canonical; CLAUDE.md is normally installed as a symlink to it.
  If CLAUDE.md already exists, Raven leaves it untouched unless you pass
  --adopt-claude-symlink, which moves it to CLAUDE.md.bak first.
""",
    )
    upgrade_parser.add_argument(
        "overrides",
        nargs="*",
        help="template-relative Raven-owned paths to force-copy even if locally modified",
    )
    upgrade_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="preview upgrade categories, conflicts, and merge artifacts without writing files",
    )
    upgrade_parser.add_argument(
        "--include-readme",
        action="store_true",
        help="include the language template README.md; overrides config include_readme=false",
    )
    upgrade_parser.add_argument(
        "--adopt-claude-symlink",
        action="store_true",
        help=(
            "if CLAUDE.md exists, move it to CLAUDE.md.bak and create the CLAUDE.md -> "
            "AGENTS.md symlink; fails if backup exists"
        ),
    )

    args = parser.parse_args()

    if args.command == "init":
        return cmd_init(args)
    if args.command == "install":
        return cmd_install(args)
    if args.command == "upgrade":
        return cmd_upgrade(args)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
