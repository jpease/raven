# raven.py → scripts/raven_lib/ Package Refactor

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split the monolithic `scripts/raven.py` (1769 lines) into a `scripts/raven_lib/` package with logical submodules, grouping pure functions together and isolating I/O at module edges.

**Architecture:** Create `scripts/raven_lib/` with eleven focused submodules plus `__init__.py` (full re-export for backward compat). Keep `scripts/raven.py` as a thin 6-line shim so all subprocess callers (`self-check.py`, tests, the wrapper script) continue to work unchanged. Keep `scripts/raven` (shell wrapper) untouched. Update `tests/helpers.py` to load via `import raven_lib as raven` instead of `spec_from_file_location`.

> **Why `raven_lib/` not `raven/`**: `scripts/raven` (the shell wrapper) already exists as a file; a `scripts/raven_lib/` directory would conflict on the filesystem. `raven_lib/` is unambiguous.

**Tech Stack:** Python 3.9+, stdlib only — no new dependencies.

**Pure-function modules:** `config.py` (all parsing/computation functions), `hashing.py` (`sha256_bytes`, `_symlink_fingerprint`), `blocks.py` (~12 of 15 functions). These contain no I/O and are testable without filesystem fixtures.

---

## Target File Map

| File | Symbols moved from `raven.py` |
|------|-------------------------------|
| `scripts/raven_lib/constants.py` | All module constants + `_any_exists` |
| `scripts/raven_lib/models.py` | `TemplateEntry`, `RavenConfig`, `RavenBlock`, `Classification`, `ApplyPlan` |
| `scripts/raven_lib/config.py` | `strip_comment`, `parse_value`, `parse_simple_toml`, `load_config`, `default_config_text`, `path_matches`, `_disabled_by_component`, `component_disabled`, `config_excluded`, `_update_config_platform` |
| `scripts/raven_lib/template.py` | `is_excluded`, `should_preserve_symlink`, `iter_template_entries`, `entries_for_destination` |
| `scripts/raven_lib/hashing.py` | `sha256_bytes`, `file_sha256`, `_symlink_fingerprint`, `entry_fingerprint`, `destination_fingerprint`, `same_content` |
| `scripts/raven_lib/blocks.py` | `normalized_block_content`, `_is_markdown_table_separator_cell`, `_normalize_markdown_table_separator`, `comparison_block_content`, `block_content_matches`, `raven_block_sha256`, `raven_block_begin_for`, `raven_managed_block`, `find_raven_block`, `raven_block_is_unchanged`, `block_managed_state`, `update_raven_block`, `template_entry_text`, `append_patch_text`, `write_guided_merge_artifacts` |
| `scripts/raven_lib/manifest.py` | `load_manifest`, `git_ref`, `save_manifest`, `_make_manifest_record`, `update_manifest`, `manifest_allows_upgrade` |
| `scripts/raven_lib/apply.py` | `_classify_entry`, `classify`, `copy_paths`, `claude_symlink_adoption_needed`, `adopt_claude_symlink`, `prompt_for_claude_symlink_adoption` |
| `scripts/raven_lib/plan.py` | `print_section`, `print_apply_summary`, `print_dry_run_summary`, `_without`, `build_apply_plan`, `print_dry_run_plan`, `apply_plan`, `normalize_override` |
| `scripts/raven_lib/git_hooks.py` | `_git_hooks_dir`, `install_git_hooks` |
| `scripts/raven_lib/cli.py` | `list_language_templates`, `select_language_interactively`, `_parse_install_language`, `_run`, `cmd_init`, `cmd_install`, `cmd_upgrade`, `main` + all argparse setup |
| `scripts/raven_lib/__init__.py` | Re-export full public API from all submodules |
| `scripts/raven_lib/__main__.py` | `from .cli import main; sys.exit(main())` |
| `scripts/raven.py` | Thin shim: `sys.path` + `from raven_lib.cli import main; sys.exit(main())` |

**Import dependency order (no circular imports):**
```
constants  →  (stdlib only)
models     →  constants
config     →  constants, models
hashing    →  constants, models
template   →  constants, models, config
blocks     →  constants, models, hashing
manifest   →  constants, models, hashing
apply      →  constants, models, config, template, hashing, blocks, manifest
plan       →  constants, models, apply, blocks
git_hooks  →  constants
cli        →  all above
__init__   →  all above (re-exports)
```

---

### Task 1: Create package skeleton

**Files:**
- Create: `scripts/raven_lib/` (directory)
- Create: `scripts/raven_lib/__init__.py` (empty for now — filled in Task 12)
- Create: `scripts/raven_lib/__main__.py`

- [ ] **Create directory and `__main__.py`**

```bash
mkdir scripts/raven
```

`scripts/raven_lib/__main__.py`:
```python
from .cli import main
import sys
sys.exit(main())
```

`scripts/raven_lib/__init__.py` (placeholder — will be filled in Task 12):
```python
# Public API re-export — populated in Task 12
```

- [ ] **Verify directory exists**

```bash
ls scripts/raven_lib/
```
Expected: `__init__.py  __main__.py`

---

### Task 2: Extract `constants.py` and `models.py`

**Files:**
- Create: `scripts/raven_lib/constants.py`
- Create: `scripts/raven_lib/models.py`

These have no intra-project imports so they go first.

- [ ] **Create `scripts/raven_lib/constants.py`**

Copy lines 1–93 from `raven.py` (the `from __future__` import, all stdlib imports, all module-level constants, and `_any_exists`). The file should look like:

```python
from __future__ import annotations

import os
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
```

> **Note on `REPO_ROOT`**: In the package, `__file__` is `scripts/raven_lib/constants.py`, so `parents[2]` is the repo root (two levels up from `scripts/raven_lib/`).

- [ ] **Create `scripts/raven_lib/models.py`**

Copy the five dataclasses (lines 99–152 from `raven.py`):

```python
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .constants import KIND_FILE, KIND_SYMLINK


@dataclass(frozen=True)
class TemplateEntry:
    source: Path
    relative: str
    copy_as_symlink: bool


@dataclass(frozen=True)
class RavenConfig:
    template: str | None
    include_readme: bool
    exclude_paths: list[str]
    components: dict[str, bool]
    claude_components: dict[str, bool]
    codex_components: dict[str, bool]
    exists: bool


@dataclass(frozen=True)
class RavenBlock:
    content: str
    declared_sha256: str | None
    start: int
    end: int


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
```

- [ ] **Verify both files import cleanly**

```bash
PYENV_VERSION=3.9.24 python -c "
import sys; sys.path.insert(0, 'scripts')
from raven_lib.constants import REPO_ROOT, CONFIG_PATH
from raven_lib.models import TemplateEntry, RavenConfig, ApplyPlan
print('ok')
"
```
Expected: `ok`.

---

### Task 3: Extract `config.py`

**Files:**
- Create: `scripts/raven_lib/config.py`

Symbols: `strip_comment`, `parse_value`, `parse_simple_toml`, `load_config`, `default_config_text`, `path_matches`, `_disabled_by_component`, `component_disabled`, `config_excluded`, `_update_config_platform`

Pure functions (no I/O): `strip_comment`, `parse_value`, `parse_simple_toml`, `default_config_text`, `path_matches`, `_disabled_by_component`, `component_disabled`, `config_excluded`

I/O functions: `load_config` (reads file), `_update_config_platform` (reads + writes file)

- [ ] **Create `scripts/raven_lib/config.py`**

Header:
```python
from __future__ import annotations

import re
from pathlib import Path

from .constants import (
    CONFIG_PATH,
    COMPONENT_PATHS,
    DEFAULT_COMPONENTS,
    DEFAULT_CLAUDE_COMPONENTS,
    DEFAULT_CODEX_COMPONENTS,
    CLAUDE_COMPONENT_PATHS,
    CODEX_COMPONENT_PATHS,
)
from .models import RavenConfig

_ISSUE_TRACKER_SECTION_RE = re.compile(r"^\s*\[([^\]]+)\]")
_PLATFORM_LINE_RE = re.compile(r"^\s*platform\s*=")

# --- paste strip_comment through _update_config_platform verbatim ---
```

- [ ] **Run import check**

```bash
PYENV_VERSION=3.9.24 python -c "
import sys; sys.path.insert(0, 'scripts')
from raven_lib.config import load_config, default_config_text, parse_simple_toml
print('ok')
"
```
Expected: `ok`.

---

### Task 4: Extract `hashing.py`

**Files:**
- Create: `scripts/raven_lib/hashing.py`

Symbols: `sha256_bytes` (pure), `file_sha256`, `_symlink_fingerprint` (pure), `entry_fingerprint`, `destination_fingerprint`, `same_content`

- [ ] **Create `scripts/raven_lib/hashing.py`**

```python
from __future__ import annotations

import filecmp
import hashlib
import os
from pathlib import Path

from .constants import KIND_FILE, KIND_SYMLINK
from .models import TemplateEntry

# --- paste sha256_bytes through same_content verbatim ---
```

- [ ] **Run import check**

```bash
PYENV_VERSION=3.9.24 python -c "
import sys; sys.path.insert(0, 'scripts')
from raven_lib.hashing import sha256_bytes, file_sha256, same_content
print(sha256_bytes(b'hello'))
"
```
Expected: sha256 hex string, no errors.

---

### Task 5: Extract `template.py`

**Files:**
- Create: `scripts/raven_lib/template.py`

Symbols: `is_excluded`, `should_preserve_symlink`, `iter_template_entries`, `entries_for_destination`

- [ ] **Create `scripts/raven_lib/template.py`**

```python
from __future__ import annotations

import fnmatch
import os
from pathlib import Path

from .constants import EXCLUDED_NAMES, NON_TEMPLATE_DIRS, KIND_FILE, KIND_SYMLINK
from .config import component_disabled, config_excluded
from .models import TemplateEntry, RavenConfig

# --- paste is_excluded through entries_for_destination verbatim ---
```

- [ ] **Run import check**

```bash
PYENV_VERSION=3.9.24 python -c "
import sys; sys.path.insert(0, 'scripts')
from raven_lib.template import iter_template_entries, entries_for_destination
print('ok')
"
```
Expected: `ok`.

---

### Task 6: Extract `blocks.py`

**Files:**
- Create: `scripts/raven_lib/blocks.py`

Symbols (pure): `normalized_block_content`, `_is_markdown_table_separator_cell`, `_normalize_markdown_table_separator`, `comparison_block_content`, `block_content_matches`, `raven_block_sha256`, `raven_block_begin_for`, `raven_managed_block`, `find_raven_block`, `raven_block_is_unchanged`, `template_entry_text`, `append_patch_text`

Symbols (I/O): `block_managed_state`, `update_raven_block`, `write_guided_merge_artifacts`

- [ ] **Create `scripts/raven_lib/blocks.py`**

```python
from __future__ import annotations

import re
from pathlib import Path

from .constants import (
    RAVEN_BLOCK_BEGIN,
    RAVEN_BLOCK_BEGIN_RE,
    RAVEN_BLOCK_END,
    ROOT_INSTRUCTION_FILES,
    MERGE_DIR,
)
from .models import TemplateEntry, RavenBlock
from .hashing import sha256_bytes

# --- paste normalized_block_content through write_guided_merge_artifacts verbatim ---
```

- [ ] **Run import check**

```bash
PYENV_VERSION=3.9.24 python -c "
import sys; sys.path.insert(0, 'scripts')
from raven_lib.blocks import find_raven_block, raven_block_sha256, block_managed_state
print('ok')
"
```
Expected: `ok`.

---

### Task 7: Extract `manifest.py`

**Files:**
- Create: `scripts/raven_lib/manifest.py`

Symbols: `load_manifest`, `git_ref`, `save_manifest`, `_make_manifest_record`, `update_manifest`, `manifest_allows_upgrade`

- [ ] **Create `scripts/raven_lib/manifest.py`**

```python
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from .constants import REPO_ROOT, MANIFEST_PATH, KIND_SYMLINK
from .models import TemplateEntry
from .hashing import entry_fingerprint, destination_fingerprint

# --- paste load_manifest through manifest_allows_upgrade verbatim ---
```

- [ ] **Run import check**

```bash
PYENV_VERSION=3.9.24 python -c "
import sys; sys.path.insert(0, 'scripts')
from raven_lib.manifest import load_manifest, manifest_allows_upgrade
print('ok')
"
```
Expected: `ok`.

---

### Task 8: Extract `apply.py`

**Files:**
- Create: `scripts/raven_lib/apply.py`

Symbols: `_classify_entry`, `classify`, `copy_paths`, `claude_symlink_adoption_needed`, `adopt_claude_symlink`, `prompt_for_claude_symlink_adoption`

- [ ] **Create `scripts/raven_lib/apply.py`**

```python
from __future__ import annotations

import os
import shutil
from pathlib import Path

from .constants import CLAUDE_PATH, CLAUDE_BACKUP_PATH, ROOT_INSTRUCTION_FILES, _any_exists
from .models import TemplateEntry, RavenConfig, Classification
from .config import component_disabled, config_excluded
from .template import iter_template_entries, entries_for_destination
from .hashing import same_content
from .blocks import block_managed_state, update_raven_block
from .manifest import load_manifest, manifest_allows_upgrade

# --- paste _classify_entry through prompt_for_claude_symlink_adoption verbatim ---
```

- [ ] **Run import check**

```bash
PYENV_VERSION=3.9.24 python -c "
import sys; sys.path.insert(0, 'scripts')
from raven_lib.apply import classify, copy_paths
print('ok')
"
```
Expected: `ok`.

---

### Task 9: Extract `plan.py`

**Files:**
- Create: `scripts/raven_lib/plan.py`

Symbols: `print_section`, `print_apply_summary`, `print_dry_run_summary`, `_without`, `build_apply_plan`, `print_dry_run_plan`, `apply_plan`, `normalize_override`

Pure functions: `_without`, `normalize_override`, `build_apply_plan` (calls `_any_exists` and `claude_symlink_adoption_needed` which do I/O — but the logic branching is pure; keep as-is)

- [ ] **Create `scripts/raven_lib/plan.py`**

```python
from __future__ import annotations

from pathlib import Path

from .constants import (
    CLAUDE_PATH,
    ROOT_INSTRUCTION_FILES,
    MERGE_DIR,
    _any_exists,
)
from .models import TemplateEntry, RavenConfig, Classification, ApplyPlan
from .config import load_config
from .template import entries_for_destination
from .blocks import write_guided_merge_artifacts
from .manifest import update_manifest
from .apply import (
    classify,
    copy_paths,
    adopt_claude_symlink,
    claude_symlink_adoption_needed,
    prompt_for_claude_symlink_adoption,
)

# --- paste print_section through normalize_override verbatim ---
```

- [ ] **Run import check**

```bash
PYENV_VERSION=3.9.24 python -c "
import sys; sys.path.insert(0, 'scripts')
from raven_lib.plan import build_apply_plan, apply_plan, normalize_override
print('ok')
"
```
Expected: `ok`.

---

### Task 10: Extract `git_hooks.py`

**Files:**
- Create: `scripts/raven_lib/git_hooks.py`

Symbols: `_git_hooks_dir`, `install_git_hooks`

- [ ] **Create `scripts/raven_lib/git_hooks.py`**

```python
from __future__ import annotations

import os
import subprocess
import stat
from pathlib import Path

from .constants import REPO_ROOT, COMPONENT_PATHS

# --- paste _git_hooks_dir and install_git_hooks verbatim ---
```

- [ ] **Run import check**

```bash
PYENV_VERSION=3.9.24 python -c "
import sys; sys.path.insert(0, 'scripts')
from raven_lib.git_hooks import install_git_hooks
print('ok')
"
```
Expected: `ok`.

---

### Task 11: Extract `cli.py`

**Files:**
- Create: `scripts/raven_lib/cli.py`

Symbols: `list_language_templates`, `select_language_interactively`, `_parse_install_language`, `_run`, `cmd_init`, `cmd_install`, `cmd_upgrade`, `main` + all argparse setup

- [ ] **Create `scripts/raven_lib/cli.py`**

```python
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .constants import (
    REPO_ROOT,
    CONFIG_PATH,
    NON_TEMPLATE_DIRS,
    DEFAULT_EXCLUDES,
)
from .models import RavenConfig
from .config import load_config, default_config_text, _update_config_platform
from .template import entries_for_destination
from .manifest import update_manifest
from .apply import classify
from .plan import build_apply_plan, apply_plan, print_dry_run_plan, normalize_override
from .git_hooks import install_git_hooks

# --- paste list_language_templates through main verbatim, including all argparse setup ---
```

- [ ] **Run import check**

```bash
PYENV_VERSION=3.9.24 python -c "
import sys; sys.path.insert(0, 'scripts')
from raven_lib.cli import main
print('ok')
"
```
Expected: `ok`.

---

### Task 12: Wire `__init__.py`, thin `raven.py`, update helpers

**Files:**
- Modify: `scripts/raven_lib/__init__.py`
- Modify: `scripts/raven.py`
- Modify: `tests/helpers.py`

- [ ] **Write `scripts/raven_lib/__init__.py`** — full re-export so `import raven; raven.classify(...)` still works

```python
from __future__ import annotations

from .constants import (
    REPO_ROOT, DEFAULT_EXCLUDES, EXCLUDED_NAMES, CONFIG_PATH, MANIFEST_PATH,
    MERGE_DIR, ROOT_INSTRUCTION_FILES, CLAUDE_PATH, CLAUDE_BACKUP_PATH,
    RAVEN_BLOCK_BEGIN, RAVEN_BLOCK_BEGIN_RE, RAVEN_BLOCK_END,
    DEFAULT_COMPONENTS, DEFAULT_CLAUDE_COMPONENTS, DEFAULT_CODEX_COMPONENTS,
    COMPONENT_PATHS, STARTER_TOOL_CONFIG_PATHS, CLAUDE_COMPONENT_PATHS,
    CODEX_COMPONENT_PATHS, NON_TEMPLATE_DIRS, KIND_FILE, KIND_SYMLINK,
    _any_exists,
)
from .models import (
    TemplateEntry, RavenConfig, RavenBlock, Classification, ApplyPlan,
)
from .config import (
    strip_comment, parse_value, parse_simple_toml, load_config,
    default_config_text, path_matches, component_disabled, config_excluded,
    _update_config_platform,
)
from .template import (
    is_excluded, should_preserve_symlink, iter_template_entries,
    entries_for_destination,
)
from .hashing import (
    sha256_bytes, file_sha256, entry_fingerprint, destination_fingerprint,
    same_content,
)
from .blocks import (
    normalized_block_content, comparison_block_content, block_content_matches,
    raven_block_sha256, raven_block_begin_for, raven_managed_block,
    find_raven_block, raven_block_is_unchanged, block_managed_state,
    update_raven_block, template_entry_text, append_patch_text,
    write_guided_merge_artifacts,
)
from .manifest import (
    load_manifest, git_ref, save_manifest, update_manifest,
    manifest_allows_upgrade,
)
from .apply import (
    classify, copy_paths, claude_symlink_adoption_needed, adopt_claude_symlink,
    prompt_for_claude_symlink_adoption,
)
from .plan import (
    print_section, print_apply_summary, print_dry_run_summary,
    build_apply_plan, print_dry_run_plan, apply_plan, normalize_override,
)
from .git_hooks import install_git_hooks
from .cli import (
    list_language_templates, select_language_interactively,
    cmd_init, cmd_install, cmd_upgrade, main,
)

__all__ = [
    "REPO_ROOT", "DEFAULT_EXCLUDES", "EXCLUDED_NAMES", "CONFIG_PATH",
    "MANIFEST_PATH", "MERGE_DIR", "ROOT_INSTRUCTION_FILES", "CLAUDE_PATH",
    "CLAUDE_BACKUP_PATH", "RAVEN_BLOCK_BEGIN", "RAVEN_BLOCK_BEGIN_RE",
    "RAVEN_BLOCK_END", "DEFAULT_COMPONENTS", "DEFAULT_CLAUDE_COMPONENTS",
    "DEFAULT_CODEX_COMPONENTS", "COMPONENT_PATHS", "STARTER_TOOL_CONFIG_PATHS",
    "CLAUDE_COMPONENT_PATHS", "CODEX_COMPONENT_PATHS", "NON_TEMPLATE_DIRS",
    "KIND_FILE", "KIND_SYMLINK", "_any_exists",
    "TemplateEntry", "RavenConfig", "RavenBlock", "Classification", "ApplyPlan",
    "strip_comment", "parse_value", "parse_simple_toml", "load_config",
    "default_config_text", "path_matches", "component_disabled", "config_excluded",
    "_update_config_platform",
    "is_excluded", "should_preserve_symlink", "iter_template_entries",
    "entries_for_destination",
    "sha256_bytes", "file_sha256", "entry_fingerprint", "destination_fingerprint",
    "same_content",
    "normalized_block_content", "comparison_block_content", "block_content_matches",
    "raven_block_sha256", "raven_block_begin_for", "raven_managed_block",
    "find_raven_block", "raven_block_is_unchanged", "block_managed_state",
    "update_raven_block", "template_entry_text", "append_patch_text",
    "write_guided_merge_artifacts",
    "load_manifest", "git_ref", "save_manifest", "update_manifest",
    "manifest_allows_upgrade",
    "classify", "copy_paths", "claude_symlink_adoption_needed", "adopt_claude_symlink",
    "prompt_for_claude_symlink_adoption",
    "print_section", "print_apply_summary", "print_dry_run_summary",
    "build_apply_plan", "print_dry_run_plan", "apply_plan", "normalize_override",
    "install_git_hooks",
    "list_language_templates", "select_language_interactively",
    "cmd_init", "cmd_install", "cmd_upgrade", "main",
]
```

- [ ] **Replace `scripts/raven.py` body with thin shim**

New content of `scripts/raven.py`:
```python
#!/usr/bin/env python3
"""Entry point — delegates to the raven package."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from raven_lib.cli import main  # noqa: E402

sys.exit(main())
```

- [ ] **Update `tests/helpers.py`**

```python
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RAVEN_PATH = REPO_ROOT / "scripts" / "raven.py"

sys.path.insert(0, str(REPO_ROOT / "scripts"))

import raven_lib as raven  # noqa: E402  (loads scripts/raven_lib/__init__.py)
```

> Tests access `raven.default_config_text(...)` etc. — all symbols re-exported from `__init__.py`.

---

### Task 13: Full test run, self-check, and commit

- [ ] **Run full test suite**

```bash
PYENV_VERSION=3.9.24 python -m pytest tests/ -q
```
Expected: all tests pass (same count as before refactor).

- [ ] **Run self-check**

```bash
python scripts/self-check.py
```
Expected: `RAVEN self-check passed`.

- [ ] **Smoke test CLI via the shim**

```bash
python scripts/raven.py --help
tmp=$(mktemp -d)
python scripts/raven.py -d "$tmp" init python --platform github
cat "$tmp/.raven/config.toml" | grep platform
rm -rf "$tmp"
```
Expected: help output; `platform = "github"` in config.

- [ ] **Verify module import paths work**

```bash
PYENV_VERSION=3.9.24 python -c "
import sys; sys.path.insert(0, 'scripts')
from raven_lib.hashing import sha256_bytes
from raven_lib.blocks import find_raven_block
from raven_lib.config import default_config_text
from raven_lib.apply import classify
print('all submodule imports ok')
"
```
Expected: `all submodule imports ok`.

- [ ] **Close issue and commit**

```bash
gh issue close 4 --comment "Completed in $(git rev-parse --short HEAD)"
git add scripts/raven_lib/ scripts/raven.py tests/helpers.py
git commit -m "refactor(raven): split raven.py into scripts/raven_lib/ package with logical submodules"
```
