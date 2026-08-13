"""Shared path, component-map, and marker constants for the installer/upgrader.

Values here are the single source of truth other modules read from -- for example
``COMPONENT_PATHS`` drives both what `apply`/`plan` copy and what `config` gates --
so a path or component name that needs to change belongs here, not re-typed at the
call site.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EXCLUDES = {"README.md"}
# The complete set of valid `[issue_tracker].platform` config values, and the
# only values `--platform` accepts. Both `cli.py`'s two `--platform`
# `choices=` argparse definitions and `config.py`'s config-value validation
# import this rather than duplicating the set (#173).
VALID_PLATFORMS = ("github", "gitlab", "none")
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
    "scripts": True,
    "subagents": True,
    "rules": True,
}
DEFAULT_CODEX_COMPONENTS = {
    "config": True,
    "hooks": True,
    "scripts": True,
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
        ".rubocop.yml",
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
# Adapter helper scripts get their own switch rather than riding along with
# `hooks`: skills call them directly (see raven-skeleton, raven-project-
# lifecycle, raven-tool-bootstrap), so a repo that declines hook enforcement
# still needs the scripts those skills invoke.
CLAUDE_COMPONENT_PATHS = {
    "settings": [".claude/settings.json"],
    "hooks": [".claude/hooks"],
    "scripts": [".claude/scripts"],
    "subagents": [".claude/agents"],
    "rules": [".claude/rules"],
}
CODEX_COMPONENT_PATHS = {
    "config": [".codex/config.toml"],
    "hooks": [".codex/hooks", ".codex/hooks.json"],
    "scripts": [".codex/scripts"],
    "subagents": [".codex/agents"],
    "rules": [".codex/rules"],
}
NON_TEMPLATE_DIRS = {"common", "scripts", "tests", "docs", "project-skills"}
KIND_FILE = "file"
KIND_SYMLINK = "symlink"
# Every symlink the template tree under `common/` ships, as `common/`-relative
# POSIX paths. A checkout made without symlink support -- git for Windows
# without Developer Mode or the "create symbolic links" privilege, or
# `core.symlinks=false` -- materializes each of these as a *regular file whose
# entire content is the target path string*. Raven's walk then classifies them
# as ordinary files and copies that placeholder text into the destination as if
# it were real content; two of them are Codex security hooks, which afterwards
# fail open rather than blocking anything (#177).
#
# Raven does not support no-symlink checkouts: `broken_template_symlinks` turns
# this registry into a preflight that refuses install/upgrade/accept, and a
# `doctor` check that reports the same condition. Reconstructing the intended
# symlinks from the placeholder text would mean the installer guessing at the
# contents of security-enforcement hooks; re-cloning with symlinks enabled is
# both cheap and unambiguous.
#
# Every language template reaches these same files through its own directory
# symlink into `common/` (e.g. `python/.codex/hooks -> ../../common/.codex/
# hooks`), which the walk follows, so checking `common/` alone covers all of
# them. Deliberately pinned by hand rather than globbed: a new `common/` symlink
# must be an explicit edit here, and `test_template.py`'s registry canary fails
# until it is.
EXPECTED_TEMPLATE_SYMLINKS = frozenset(
    {
        "CLAUDE.md",
        ".claude/skills",
        ".codex/hooks/raven-post-bash-summarize.py",
        ".codex/hooks/raven-post-edit-format.py",
        ".codex/hooks/raven-pre-bash-guard.py",
        ".codex/hooks/raven-pre-edit-guard.py",
        ".codex/hooks/raven-session-checkpoint.py",
        ".codex/scripts/raven-capability-roster.py",
        ".codex/scripts/raven-session.py",
        ".codex/scripts/raven-skeleton.py",
        ".codex/scripts/raven-tool-check.py",
    }
)
# The two-line remedy for a flattened checkout, shared verbatim by the CLI
# preflight and the `doctor` finding so a user cannot be told two different
# things about the same condition.
SYMLINK_CHECKOUT_FIX = (
    "re-clone Raven with symlinks enabled: `git config --global core.symlinks true`, "
    "then clone again (an existing flattened checkout cannot be repaired in place). "
    "On Windows, first enable Developer Mode or run git from an elevated shell so it "
    "is permitted to create symbolic links."
)


def _any_exists(p: Path) -> bool:
    return p.exists() or p.is_symlink()
