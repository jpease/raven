from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
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
    "hooks": [".claude/hooks", ".codex/hooks", ".codex/hooks.json", ".raven/git-hooks"],
    "rules": [".claude/rules", ".codex/rules"],
    "docs": [".claude/docs"],
    "scripts": [".claude/scripts", ".codex/scripts"],
    "mcp": [".mcp.json"],
    "settings": [".claude/settings.json", ".codex/config.toml"],
    "tool_configs": [
        ".credo.exs",
        ".formatter.exs",
        ".golangci.yml",
        ".luacheckrc",
        ".swift-format",
        ".swiftlint.yml",
        "eslint.config.mjs",
        "prettier.config.mjs",
        "pyproject.toml",
        "rustfmt.toml",
        "stylua.toml",
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
