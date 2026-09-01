"""Shared path, component-map, and marker constants for the installer/upgrader.

Values here are the single source of truth other modules read from -- for example
``COMPONENT_PATHS`` drives both what `apply`/`plan` copy and what `config` gates --
so a path or component name that needs to change belongs here, not re-typed at the
call site.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import NamedTuple

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
# .claude/settings.json adoption (#200): a pre-existing hand-written copy is
# backed up here before Raven takes over the file, mirroring the CLAUDE.md
# symlink-adoption precedent above -- but settings.json is a plain managed
# file, not a symlink, so adoption backs up and overwrites real content
# instead of redirecting a link.
SETTINGS_JSON_PATH = ".claude/settings.json"
SETTINGS_JSON_BACKUP_PATH = ".claude/settings.json.bak"
# .gitattributes (#206) and .ignore (#238) each ship a real template file
# under common/ -- unlike .gitignore, which has no template file at all and is
# purely synthesized by blocks._ensure_gitignored -- but neither may ever be
# whole-file copied onto a destination: most destination repos already carry
# their own .gitattributes (binary handling, diff drivers, language-specific
# normalization) and their own .ignore (build output, vendored trees, fixture
# data) for reasons unrelated to Raven, unlike .claude/settings.json (#200),
# which destination repos rarely hand-write before Raven arrives. Kept out of
# DEFAULT_EXCLUDES on purpose: DEFAULT_EXCLUDES is toggled off by
# --include-readme (see cli.py), a flag with nothing to do with either path,
# so folding them in there would make --include-readme accidentally re-enable
# whole-file copy. `is_excluded` checks this set directly and unconditionally
# instead, so the walk never turns one into a normal will_copy/will_upgrade
# TemplateEntry; `blocks.ensure_gitattributes_lines` and
# `blocks.ensure_ignore_lines` merge their required lines into the
# destination's own file, the same idempotent-append shape
# `_ensure_gitignored` already established for .gitignore.
GITATTRIBUTES_PATH = ".gitattributes"
IGNORE_PATH = ".ignore"
MERGE_ONLY_TEMPLATE_PATHS = {GITATTRIBUTES_PATH, IGNORE_PATH}
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
    "hooks": [
        ".claude/hooks",
        ".codex/hooks",
        ".codex/hooks.json",
        ".gitattributes",
        ".raven/git-hooks",
    ],
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
#: Top-level directories that are part of Raven itself rather than an
#: installable template. `list_language_templates` walks the repo root, so a
#: new directory here is offered as a language until it is listed.
NON_TEMPLATE_DIRS = {"common", "docs", "evals", "project-skills", "scripts", "tests"}
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


class LaneClaim(NamedTuple):
    """One lane a Raven skill and an upstream skill both claim.

    ``prefer`` is one of exactly two values, ``"raven"`` or ``"upstream"``.
    There is no third state on purpose: a lane whose owner is unclear does not
    belong in the table yet.
    """

    lane: str
    raven_skill: str
    source: str
    upstream_skill: str
    prefer: str
    reason: str


# Lanes claimed by both a Raven skill and a skill from a declared source.
#
# Declared, never inferred. Name and description similarity would miss the
# cases that matter -- the strongest real pair, `raven-debug-failure` and
# `systematic-debugging`, shares no tokens -- and invent ones that do not. A
# row here is an opinion Raven is willing to state and a test can check.
#
# This is data: adding a row requires no code change. A row is evaluated only
# when its `source` is declared in the destination's `.raven/config.toml`, so
# the table being machine-global does not make the report machine-global.
LANE_CLAIMS = (
    LaneClaim(
        "planning",
        "raven-plan",
        "superpowers",
        "writing-plans",
        "raven",
        "durable artifact, interrogation, fresh-context check",
    ),
    LaneClaim(
        "testing",
        "raven-write-tests",
        "superpowers",
        "test-driven-development",
        "raven",
        "repo guards and duplicate-check funnel",
    ),
    LaneClaim(
        "debugging",
        "raven-debug-failure",
        "superpowers",
        "systematic-debugging",
        "raven",
        "CI-failure handling upstream lacks",
    ),
    LaneClaim(
        "completion",
        "raven-task-complete",
        "superpowers",
        "verification-before-completion",
        "raven",
        "lifecycle checkpoint integration",
    ),
    LaneClaim(
        "review",
        "raven-review-pr",
        "superpowers",
        "requesting-code-review",
        "raven",
        "antipattern registry and Semgrep promotion",
    ),
    LaneClaim(
        "delegation",
        "raven-delegate-or-inline",
        "superpowers",
        "dispatching-parallel-agents",
        "raven",
        "inline-vs-delegate decision upstream does not make",
    ),
)


def claude_config_dir() -> Path:
    """Where Claude Code keeps its user-level state, honoring ``CLAUDE_CONFIG_DIR``.

    The single place in ``raven_lib`` that reads that variable: `doctor` looks
    up the plugin registry beneath this directory, and keeping the lookup here
    means a test can point `doctor` at a temp registry by passing a path
    instead of patching the environment or ``Path.home``.

    An empty value is treated as unset -- ``CLAUDE_CONFIG_DIR=""`` in a shell
    profile means "I did not set this", not "resolve against the filesystem
    root".
    """
    override = os.environ.get("CLAUDE_CONFIG_DIR")
    if override:
        return Path(override)
    return Path.home() / ".claude"


def _any_exists(p: Path) -> bool:
    return p.exists() or p.is_symlink()
