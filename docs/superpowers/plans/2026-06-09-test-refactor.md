# Test Suite Refactor: Split test_raven.py by concern

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split the monolithic `tests/test_raven.py` (1440+ lines, one class) into focused files grouped by concern so individual tests are easy to locate and merge conflicts are rare.

**Architecture:** Extract a `tests/helpers.py` with shared module-loading boilerplate; create one `conftest.py` to put `tests/` on `sys.path`; migrate tests in cohesive batches; delete `test_raven.py` at the end. `test_raven_session.py` stays untouched.

**Tech Stack:** Python 3.9+, unittest, pytest — no new dependencies.

---

## Target File Map

| New file | Tests moved from `test_raven.py` |
|----------|----------------------------------|
| `tests/helpers.py` | shared `REPO_ROOT`, `RAVEN_PATH`, `load_raven()`, `raven` |
| `tests/conftest.py` | `sys.path` fixup so `helpers` is importable |
| `tests/test_classification.py` | classify, config, components, starter-tool-configs, default-config |
| `tests/test_copy_and_manifest.py` | copy_paths, manifest read/write |
| `tests/test_managed_blocks.py` | RAVEN:BEGIN/END block upgrade/repair |
| `tests/test_skills.py` | `.claude/skills` directory handling |
| `tests/test_guided_merge.py` | guided merge artifacts |
| `tests/test_claude_symlink.py` | CLAUDE.md symlink adoption |
| `tests/test_templates.py` | language template integrity, LSP defaults |
| `tests/test_cli.py` | wrapper script, help output, self-check |
| `tests/test_agent_hooks.py` | Claude/Codex hook script behavior |
| `tests/test_tool_check.py` | raven-tool-check.py, MCP config, timeouts |
| `tests/test_git_hooks.py` | `GitHookInstallerTests` (move class verbatim) |
| `tests/test_commit_msg_hook.py` | `CommitMsgHookTests` (move class verbatim) |

Keep unchanged: `tests/test_raven_session.py`
Delete when migration is complete: `tests/test_raven.py`

---

### Task 1: Create `tests/helpers.py` and `tests/conftest.py`

**Files:**
- Create: `tests/helpers.py`
- Create: `tests/conftest.py`

- [ ] **Create `tests/helpers.py`**

```python
import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RAVEN_PATH = REPO_ROOT / "scripts" / "raven.py"


def load_raven():
    spec = importlib.util.spec_from_file_location("raven", RAVEN_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


raven = load_raven()
```

- [ ] **Create `tests/conftest.py`**

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
```

- [ ] **Verify helpers is importable**

```bash
PYENV_VERSION=3.9.24 python -c "import sys; sys.path.insert(0, 'tests'); from helpers import raven; print('ok')"
```
Expected: `ok`.

---

### Task 2: Migrate classification and config tests

**Files:**
- Create: `tests/test_classification.py`

Move these 11 tests from `RavenTests` (line numbers in `test_raven.py`):
- `test_classifies_missing_identical_and_unknown_existing_files` (36)
- `test_config_can_disable_components_and_exclude_paths` (179)
- `test_starter_tool_configs_are_copied_when_missing` (209)
- `test_existing_starter_tool_config_is_skipped_without_merge` (238)
- `test_config_can_disable_starter_tool_configs` (263)
- `test_config_can_disable_agent_specific_components` (744)
- `test_excludes_generated_files_anywhere` (787)
- `test_default_config_is_self_documenting` (723)
- `test_default_config_includes_lifecycle_section` (734)
- `test_default_config_includes_issue_tracker_section` (739)
- `test_conflict_fixture_preserves_existing_files_and_writes_guidance` (935)

- [ ] **Create `tests/test_classification.py`** with this header and the moved test methods:

```python
import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from helpers import REPO_ROOT, raven


class ClassificationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.destination = Path(self.tmp.name)
        self.template = REPO_ROOT / "python"
        self.excludes = {"README.md"}

    # --- paste test methods here verbatim ---
```

- [ ] **Run new file alone**

```
PYENV_VERSION=3.9.24 python -m pytest tests/test_classification.py -q
```
Expected: 11 passed.

---

### Task 3: Migrate copy and manifest tests

**Files:**
- Create: `tests/test_copy_and_manifest.py`

Move these 6 tests:
- `test_apply_preserves_compatibility_symlinks` (54)
- `test_override_path_can_overwrite_one_changed_file` (77)
- `test_manifest_allows_upgrade_for_unchanged_managed_file` (91)
- `test_manifest_requires_merge_for_locally_modified_managed_file` (114)
- `test_update_manifest_records_file_hashes` (134)
- `test_update_manifest_can_adopt_identical_existing_file` (157)

- [ ] **Create `tests/test_copy_and_manifest.py`**

```python
import os
import tempfile
import unittest
from pathlib import Path

from helpers import REPO_ROOT, raven


class CopyAndManifestTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.destination = Path(self.tmp.name)
        self.template = REPO_ROOT / "python"
        self.excludes = {"README.md"}

    # --- paste test methods verbatim ---
```

- [ ] **Run**

```
PYENV_VERSION=3.9.24 python -m pytest tests/test_copy_and_manifest.py -q
```
Expected: 6 passed.

---

### Task 4: Migrate managed-block tests

**Files:**
- Create: `tests/test_managed_blocks.py`

Move these 7 tests:
- `test_generated_agents_patch_marks_block_with_hash` (530)
- `test_applied_agents_block_can_be_safely_upgraded_without_touching_local_content` (538)
- `test_modified_agents_block_requires_merge_instead_of_upgrade` (576)
- `test_whitespace_only_agents_block_formatting_is_repairable` (598)
- `test_markdown_table_formatting_in_agents_block_is_repairable` (635)
- `test_matching_agents_block_with_bad_hash_is_repairable` (670)
- `test_matching_agents_block_without_hash_is_repairable` (703)

- [ ] **Create `tests/test_managed_blocks.py`**

```python
import tempfile
import unittest
from pathlib import Path

from helpers import REPO_ROOT, raven


class ManagedBlockTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.destination = Path(self.tmp.name)
        self.template = REPO_ROOT / "python"
        self.excludes = {"README.md"}

    # --- paste test methods verbatim ---
```

- [ ] **Run**

```
PYENV_VERSION=3.9.24 python -m pytest tests/test_managed_blocks.py -q
```
Expected: 7 passed.

---

### Task 5: Migrate skills, guided-merge, and claude-symlink tests

**Files:**
- Create: `tests/test_skills.py`
- Create: `tests/test_guided_merge.py`
- Create: `tests/test_claude_symlink.py`

Move to `test_skills.py` (2 tests):
- `test_existing_claude_skills_directory_gets_raven_skill_files` (287)
- `test_copy_into_existing_claude_skills_directory_preserves_existing_content` (309)

Move to `test_guided_merge.py` (3 tests):
- `test_guided_merge_artifacts_do_not_modify_existing_agents` (332)
- `test_guided_merge_artifacts_for_existing_claude_symlink_template_do_not_modify_file` (360)
- `test_dry_run_does_not_write_guided_merge_artifacts` (516)

Move to `test_claude_symlink.py` (6 tests):
- `test_adopt_claude_symlink_backs_up_existing_file_and_creates_symlink` (381)
- `test_adopt_claude_symlink_refuses_to_overwrite_existing_backup` (400)
- `test_run_with_adopt_claude_symlink_does_not_report_claude_manual_merge` (420)
- `test_run_with_adopt_claude_symlink_fails_if_backup_exists` (447)
- `test_dry_run_with_adopt_claude_symlink_reports_backup_without_writing` (471)
- `test_dry_run_with_adopt_claude_symlink_fails_if_backup_exists` (492)

- [ ] **Each file uses this header pattern** (adjust class name per file):

```python
import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path

from helpers import REPO_ROOT, raven


class SkillsTests(unittest.TestCase):  # or GuidedMergeTests / ClaudeSymlinkTests
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.destination = Path(self.tmp.name)
        self.template = REPO_ROOT / "python"
        self.excludes = {"README.md"}

    # --- paste test methods verbatim ---
```

- [ ] **Run all three**

```
PYENV_VERSION=3.9.24 python -m pytest tests/test_skills.py tests/test_guided_merge.py tests/test_claude_symlink.py -q
```
Expected: 11 passed.

---

### Task 6: Migrate template-integrity, CLI, agent-hooks, and tool-check tests

**Files:**
- Create: `tests/test_templates.py`
- Create: `tests/test_cli.py`
- Create: `tests/test_agent_hooks.py`
- Create: `tests/test_tool_check.py`

**`test_templates.py`** — 4 tests (803, 871, 883, 909). Uses `self.template` but NOT `self.destination`. No `setUp` needed beyond standard tmp:

```python
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from helpers import REPO_ROOT, raven


class TemplateIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.destination = Path(self.tmp.name)
        self.template = REPO_ROOT / "python"
        self.excludes = {"README.md"}

    # test_all_language_templates_install_and_upgrade_cleanly
    # test_templates_have_no_broken_symlinks
    # test_language_templates_define_specific_lsp_mcp_defaults
    # test_language_templates_define_specific_codex_lsp_mcp_defaults
```

**`test_cli.py`** — 3 tests (973, 979, 1002). Does NOT need `self.template`/`self.excludes`:

```python
import subprocess
import sys
import unittest
from pathlib import Path

from helpers import REPO_ROOT, RAVEN_PATH, raven


class CLITests(unittest.TestCase):
    # test_self_check_script_exists_and_is_executable
    # test_raven_wrapper_exists_and_delegates_to_cli
    # test_install_help_names_language_and_overrides
```

**`test_agent_hooks.py`** — 3 tests (1017, 1037, 1057). No `setUp`:

```python
import importlib.util
import sys
import unittest
from pathlib import Path

from helpers import REPO_ROOT, raven


class AgentHookTests(unittest.TestCase):
    # test_hooks_tolerate_null_tool_input
    # test_hooks_tolerate_non_dict_tool_input
    # test_codex_pre_hooks_emit_deny_payload_for_blocked_actions
```

**`test_tool_check.py`** — 7 tests (1092–1236). No `setUp`:

```python
import importlib.util
import sys
import unittest
from pathlib import Path

from helpers import REPO_ROOT, raven


class ToolCheckTests(unittest.TestCase):
    # test_tool_check_script_imports_without_name_error
    # test_tool_check_parses_claude_mcp_server_names
    # test_claude_mcp_config_files_are_parsed_without_cli
    # test_semble_can_be_available_from_claude_mcp_config_without_cli
    # test_semble_can_be_available_from_codex_mcp_config_without_cli
    # test_slow_claude_mcp_check_does_not_crash_tool_check
    # test_command_timeout_counts_as_unavailable
```

- [ ] **Run all four**

```
PYENV_VERSION=3.9.24 python -m pytest tests/test_templates.py tests/test_cli.py tests/test_agent_hooks.py tests/test_tool_check.py -q
```
Expected: 17 passed.

---

### Task 7: Migrate `GitHookInstallerTests` and `CommitMsgHookTests`

**Files:**
- Create: `tests/test_git_hooks.py`
- Create: `tests/test_commit_msg_hook.py`

- [ ] **Create `tests/test_git_hooks.py`** — copy `GitHookInstallerTests` class verbatim, add header:

```python
import contextlib
import io
import subprocess
import tempfile
import unittest
from pathlib import Path

from helpers import raven


# paste GitHookInstallerTests class verbatim
```

- [ ] **Create `tests/test_commit_msg_hook.py`** — copy `CommitMsgHookTests` class verbatim, add header:

```python
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from helpers import REPO_ROOT, raven


# paste CommitMsgHookTests class verbatim
```

- [ ] **Run both**

```
PYENV_VERSION=3.9.24 python -m pytest tests/test_git_hooks.py tests/test_commit_msg_hook.py -q
```
Expected: 21 passed.

---

### Task 8: Run full new suite, delete `test_raven.py`, final check

- [ ] **Run all new files together**

```
PYENV_VERSION=3.9.24 python -m pytest tests/ --ignore=tests/test_raven.py -q
```
Expected: same count as `test_raven.py` alone (73 from `test_raven.py` + session tests).

- [ ] **Delete `test_raven.py`**

```bash
git rm tests/test_raven.py
```

- [ ] **Run full suite without the old file**

```
PYENV_VERSION=3.9.24 python -m pytest tests/ -q
```
Expected: all tests pass, same total count.

- [ ] **Run self-check**

```bash
python scripts/self-check.py
```
Expected: `RAVEN self-check passed`.

- [ ] **Close issue and commit**

```bash
gh issue close 3 --comment "Completed in $(git rev-parse --short HEAD)"
git add tests/
git commit -m "refactor(tests): split test_raven.py into focused files by concern"
```
