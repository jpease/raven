# Raven Project Lifecycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add lightweight optional project lifecycle management to Raven: a `raven-project-lifecycle` skill with session state, checkpoint enforcement hooks, and issue-tracker workflow skills for GitHub and GitLab.

**Architecture:** A new `raven-session.py` script manages `.raven/session.md` as the single source of truth for local execution state; a `PreToolUse` hook validates checkpoint calls before allowing them to proceed; three new skills (`raven-project-lifecycle`, `raven-github-issues`, `raven-gitlab-issues`) provide workflow guidance; a `[lifecycle]` and `[issue_tracker]` section in `.raven/config.toml` controls feature flags and platform selection.

**Tech Stack:** Python 3.10+ stdlib only (no new dependencies); `unittest` + `tempfile` for tests; `gh` / `glab` CLI called via subprocess for optional issue-tracker integration.

**Spec:** `docs/superpowers/specs/2026-06-08-raven-project-lifecycle-design.md`

**Path deviation from spec:** `raven-session.py` ships at `common/.claude/scripts/raven-session.py` and `common/.codex/scripts/raven-session.py` (consistent with `raven-tool-check.py` pattern) rather than `scripts/raven-session.py`. The Claude hook references `.claude/scripts/raven-session.py`; the Codex hook references `.codex/scripts/raven-session.py`.

---

## File Map

| Action | Path |
|---|---|
| Modify | `scripts/raven.py` — add `[lifecycle]` + `[issue_tracker]` to `default_config_text()` |
| Create | `common/.claude/scripts/raven-session.py` |
| Create | `common/.codex/scripts/raven-session.py` (copy) |
| Create | `common/.claude/hooks/raven-session-checkpoint.py` |
| Create | `common/.codex/hooks/raven-session-checkpoint.py` (near-copy, different script path) |
| Modify | `common/.claude/settings.json` — add PreToolUse checkpoint hook |
| Modify | `common/.codex/hooks.json` — add PreToolUse checkpoint hook |
| Create | `common/.agents/skills/raven-project-lifecycle/SKILL.md` |
| Create | `common/.agents/skills/raven-github-issues/SKILL.md` |
| Create | `common/.agents/skills/raven-gitlab-issues/SKILL.md` |
| Modify | `common/.claude/docs/raven-namespace.md` — claim `.raven/session*` paths |
| Modify | `common/.agents/skills/raven-tool-bootstrap/SKILL.md` — add gh/glab checks |
| Create | `tests/test_raven_session.py` |

---

## Task 1: Add `[lifecycle]` and `[issue_tracker]` to `default_config_text()`

**Files:**
- Modify: `scripts/raven.py`
- Test: `tests/test_raven.py`

- [ ] **Step 1: Write the failing test**

Add to `class RavenTests` in `tests/test_raven.py`:

```python
def test_default_config_includes_lifecycle_section(self):
    config = raven.default_config_text("python", False)
    self.assertIn("[lifecycle]", config)
    self.assertIn("checkpoint_enforcement = true", config)

def test_default_config_includes_issue_tracker_section(self):
    config = raven.default_config_text("python", False)
    self.assertIn("[issue_tracker]", config)
    self.assertIn('platform = "none"', config)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_raven.py::RavenTests::test_default_config_includes_lifecycle_section tests/test_raven.py::RavenTests::test_default_config_includes_issue_tracker_section -v
```

Expected: FAIL — sections not yet in `default_config_text()`.

- [ ] **Step 3: Add the new sections to `default_config_text()`**

In `scripts/raven.py`, locate `default_config_text()`. After the last existing config block, append before the closing `"""`:

```python
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
        # platform = "github"   # use raven-github-issues + gh CLI
        # platform = "gitlab"   # use raven-gitlab-issues + glab CLI
        platform = "none"        # no external issue tracker
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_raven.py::RavenTests::test_default_config_includes_lifecycle_section tests/test_raven.py::RavenTests::test_default_config_includes_issue_tracker_section -v
```

Expected: PASS.

- [ ] **Step 5: Run existing config tests to check for regressions**

```bash
python -m pytest tests/test_raven.py::RavenTests::test_default_config_is_self_documenting -v
```

Expected: PASS. If it fails, ensure each added line has a comment above it.

- [ ] **Step 6: Commit**

```bash
git add scripts/raven.py tests/test_raven.py
git commit -m "feat(config): add [lifecycle] and [issue_tracker] sections to default config"
```

---

## Task 2: Create `raven-session.py` — init and status

**Files:**
- Create: `common/.claude/scripts/raven-session.py`
- Create: `tests/test_raven_session.py`

- [ ] **Step 1: Write failing tests for `--init` and `--status`**

Create `tests/test_raven_session.py`:

```python
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "common" / ".claude" / "scripts" / "raven-session.py"


def load_session():
    spec = importlib.util.spec_from_file_location("raven_session", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class SessionInitTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.raven_dir = self.root / ".raven"
        self.raven_dir.mkdir()
        self.session_file = self.raven_dir / "session.md"

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, args: list[str]) -> int:
        mod = load_session()
        with patch("pathlib.Path.cwd", return_value=self.root):
            import os
            orig = os.getcwd()
            os.chdir(self.root)
            try:
                return mod.main(args)
            finally:
                os.chdir(orig)

    def test_init_creates_session_file(self):
        rc = self._run(["--init", "greenfield", "unit-a", "unit-b"])
        self.assertEqual(rc, 0)
        self.assertTrue(self.session_file.exists())

    def test_init_records_project_type(self):
        self._run(["--init", "brownfield", "unit-a"])
        content = self.session_file.read_text()
        self.assertIn("**Project Type:** brownfield", content)

    def test_init_records_units_with_first_as_current(self):
        self._run(["--init", "greenfield", "unit-a", "unit-b", "unit-c"])
        content = self.session_file.read_text()
        self.assertIn("- [ ] unit-a (current)", content)
        self.assertIn("- [ ] unit-b", content)
        self.assertIn("- [ ] unit-c", content)

    def test_init_fails_if_session_already_exists(self):
        self._run(["--init", "greenfield", "unit-a"])
        rc = self._run(["--init", "greenfield", "unit-b"])
        self.assertNotEqual(rc, 0)

    def test_status_prints_current_unit(self):
        self._run(["--init", "greenfield", "unit-a", "unit-b"])
        import io
        from contextlib import redirect_stdout
        f = io.StringIO()
        with redirect_stdout(f):
            self._run(["--status"])
        output = f.getvalue()
        self.assertIn("unit-a", output)
        self.assertIn("current", output.lower())
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_raven_session.py -v
```

Expected: ERROR — script does not exist yet.

- [ ] **Step 3: Create `common/.claude/scripts/raven-session.py` with `--init` and `--status`**

```python
#!/usr/bin/env python3
"""Raven session state manager for raven-project-lifecycle."""
from __future__ import annotations

import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

RAVEN_DIR = Path(".raven")
SESSION_FILE = RAVEN_DIR / "session.md"
LOCK_FILE = RAVEN_DIR / "session.lock"
ARCHIVE_FILE = RAVEN_DIR / "session-archive.md"
CONFIG_FILE = RAVEN_DIR / "config.toml"
CONTEXT_SOFT_CAP = 50


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _atomic_write(path: Path, content: str) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.rename(path)


def _parse_session(text: str) -> dict:
    """Parse session.md into a structured dict."""
    data: dict = {
        "project_type": "",
        "started": "",
        "last_updated": "",
        "parent_issue": None,
        "units": [],  # list of {"name": str, "done": bool, "issue": str|None, "completed_at": str|None}
        "context_lines": [],
    }
    lines = text.splitlines()
    in_units = False
    in_context = False

    for line in lines:
        if m := re.match(r"\*\*Project Type:\*\* (.+)", line):
            data["project_type"] = m.group(1).strip()
        elif m := re.match(r"\*\*Started:\*\* (.+)", line):
            data["started"] = m.group(1).strip()
        elif m := re.match(r"\*\*Last Updated:\*\* (.+)", line):
            data["last_updated"] = m.group(1).strip()
        elif m := re.match(r"\*\*Parent Issue:\*\* (.+)", line):
            data["parent_issue"] = m.group(1).strip()
        elif line.strip() == "## Units":
            in_units = True
            in_context = False
        elif line.strip() == "## Context":
            in_units = False
            in_context = True
        elif in_units and (m := re.match(r"- \[([ x])\] (\S+)(.*)", line)):
            done = m.group(1) == "x"
            name = m.group(2)
            rest = m.group(3)
            issue = None
            completed_at = None
            if im := re.search(r"→ (#\d+)", rest):
                issue = im.group(1)
            if cm := re.search(r"\(completed ([^)]+)\)", rest):
                completed_at = cm.group(1)
            data["units"].append({
                "name": name, "done": done,
                "issue": issue, "completed_at": completed_at,
            })
        elif in_context:
            data["context_lines"].append(line)

    return data


def _render_session(data: dict) -> str:
    lines = ["# Raven Session", ""]
    lines.append(f"**Project Type:** {data['project_type']}  ")
    lines.append(f"**Started:** {data['started']}  ")
    lines.append(f"**Last Updated:** {data['last_updated']}  ")
    if data.get("parent_issue"):
        lines.append(f"**Parent Issue:** {data['parent_issue']}  ")
    lines.append("")
    lines.append("## Units")
    lines.append("")
    current_set = False
    for u in data["units"]:
        if u["done"]:
            entry = f"- [x] {u['name']}"
            if u.get("issue"):
                entry += f" → {u['issue']}"
            if u.get("completed_at"):
                entry += f" (completed {u['completed_at']})"
        else:
            if not current_set:
                entry = f"- [ ] {u['name']}"
                if u.get("issue"):
                    entry += f" → {u['issue']}"
                entry += " (current)"
                current_set = True
            else:
                entry = f"- [ ] {u['name']}"
                if u.get("issue"):
                    entry += f" → {u['issue']}"
        lines.append(entry)
    lines.append("")
    lines.append("## Context")
    lines.extend(data["context_lines"] if data["context_lines"] else [""])
    return "\n".join(lines) + "\n"


def cmd_init(args: list[str]) -> int:
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("project_type")
    p.add_argument("units", nargs="+")
    p.add_argument("--parent", default=None)
    ns = p.parse_args(args)

    if SESSION_FILE.exists():
        print(f"error: session already exists at {SESSION_FILE}. Use --status to resume.", file=sys.stderr)
        return 1

    RAVEN_DIR.mkdir(exist_ok=True)
    data = {
        "project_type": ns.project_type,
        "started": _now(),
        "last_updated": _now(),
        "parent_issue": ns.parent,
        "units": [{"name": u, "done": False, "issue": None, "completed_at": None} for u in ns.units],
        "context_lines": [""],
    }
    _atomic_write(SESSION_FILE, _render_session(data))
    print(f"Session initialized: {len(ns.units)} unit(s), project type '{ns.project_type}'.")
    if ns.parent:
        print(f"Parent issue: {ns.parent}. Create child issues manually with gh/glab and record them in session.md.")
    _update_gitignore()
    return 0


def _update_gitignore() -> None:
    """Append session file entries to .gitignore if not already present."""
    gitignore = Path(".gitignore")
    entries = [".raven/session.md", ".raven/session.lock", ".raven/session-archive.md"]
    existing = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
    missing = [e for e in entries if e not in existing]
    if missing:
        block = "\n# Raven session state\n" + "\n".join(missing) + "\n"
        with gitignore.open("a", encoding="utf-8") as f:
            f.write(block)


def cmd_status(args: list[str]) -> int:
    if not SESSION_FILE.exists():
        print("No active session. Run --init to start one.", file=sys.stderr)
        return 1
    data = _parse_session(SESSION_FILE.read_text(encoding="utf-8"))
    completed = [u for u in data["units"] if u["done"]]
    pending = [u for u in data["units"] if not u["done"]]
    current = pending[0]["name"] if pending else None
    print(f"Project type : {data['project_type']}")
    if data.get("parent_issue"):
        print(f"Parent issue : {data['parent_issue']}")
    print(f"Completed    : {len(completed)}/{len(data['units'])} unit(s)")
    if current:
        print(f"Current unit : {current}")
    else:
        print("All units complete.")
    if len(pending) > 1:
        print(f"Remaining    : {', '.join(u['name'] for u in pending[1:])}")
    if len(data["context_lines"]) > CONTEXT_SOFT_CAP:
        print(f"warning: context block is {len(data['context_lines'])} lines (>{CONTEXT_SOFT_CAP}). Consider running --archive.")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print("usage: raven-session.py --init|--status|--validate|--complete|--archive [args]", file=sys.stderr)
        return 1
    cmd = args[0]
    rest = args[1:]
    if cmd == "--init":
        return cmd_init(rest)
    if cmd == "--status":
        return cmd_status(rest)
    print(f"error: unknown command {cmd}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run init and status tests**

```bash
python -m pytest tests/test_raven_session.py::SessionInitTests -v
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add common/.claude/scripts/raven-session.py tests/test_raven_session.py
git commit -m "feat(session): add raven-session.py with --init and --status"
```

---

## Task 3: Add `--validate` and `--complete` to `raven-session.py`

**Files:**
- Modify: `common/.claude/scripts/raven-session.py`
- Modify: `tests/test_raven_session.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_raven_session.py`:

```python
class SessionValidateCompleteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.raven_dir = self.root / ".raven"
        self.raven_dir.mkdir()
        self.session_file = self.raven_dir / "session.md"

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, args: list[str]) -> int:
        mod = load_session()
        import os
        orig = os.getcwd()
        os.chdir(self.root)
        try:
            return mod.main(args)
        finally:
            os.chdir(orig)

    def _init(self, *units):
        self._run(["--init", "greenfield"] + list(units))

    def test_validate_passes_for_current_unit(self):
        self._init("unit-a", "unit-b")
        rc = self._run(["--validate", "unit-a"])
        self.assertEqual(rc, 0)

    def test_validate_fails_for_wrong_unit(self):
        self._init("unit-a", "unit-b")
        rc = self._run(["--validate", "unit-b"])
        self.assertNotEqual(rc, 0)

    def test_validate_fails_for_already_completed_unit(self):
        self._init("unit-a", "unit-b")
        self._run(["--complete", "unit-a"])
        rc = self._run(["--validate", "unit-a"])
        self.assertNotEqual(rc, 0)

    def test_validate_fails_when_no_session(self):
        rc = self._run(["--validate", "unit-a"])
        self.assertNotEqual(rc, 0)

    def test_complete_marks_unit_done(self):
        self._init("unit-a", "unit-b")
        self._run(["--complete", "unit-a"])
        content = self.session_file.read_text()
        self.assertIn("- [x] unit-a", content)

    def test_complete_advances_current_to_next_unit(self):
        self._init("unit-a", "unit-b")
        self._run(["--complete", "unit-a"])
        content = self.session_file.read_text()
        self.assertIn("- [ ] unit-b (current)", content)

    def test_complete_records_timestamp(self):
        self._init("unit-a")
        self._run(["--complete", "unit-a"])
        content = self.session_file.read_text()
        self.assertRegex(content, r"completed \d{4}-\d{2}-\d{2}T")

    def test_complete_fails_for_wrong_unit(self):
        self._init("unit-a", "unit-b")
        rc = self._run(["--complete", "unit-b"])
        self.assertNotEqual(rc, 0)

    def test_complete_fails_when_no_session(self):
        rc = self._run(["--complete", "unit-a"])
        self.assertNotEqual(rc, 0)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_raven_session.py::SessionValidateCompleteTests -v
```

Expected: FAIL — `--validate` and `--complete` not yet implemented.

- [ ] **Step 3: Add `cmd_validate`, `cmd_complete`, and lockfile helpers to `raven-session.py`**

Add after `cmd_status`:

```python
def _acquire_lock() -> None:
    """Create lockfile with PID. Retry 3x on live PID; remove stale."""
    import time
    for attempt in range(4):
        if not LOCK_FILE.exists():
            LOCK_FILE.write_text(f"{os.getpid()}\n{_now()}", encoding="utf-8")
            return
        text = LOCK_FILE.read_text(encoding="utf-8").strip()
        pid_str = text.splitlines()[0] if text else ""
        try:
            pid = int(pid_str)
        except ValueError:
            LOCK_FILE.unlink(missing_ok=True)
            continue
        # Check if PID is alive
        try:
            os.kill(pid, 0)
        except (ProcessLookupError, PermissionError):
            # Dead or not ours — stale lock
            LOCK_FILE.unlink(missing_ok=True)
            continue
        if attempt < 3:
            time.sleep(0.2)
        else:
            print(
                f"error: session locked by PID {pid}. Another agent may be running. "
                "If not, delete .raven/session.lock manually.",
                file=sys.stderr,
            )
            sys.exit(1)


def _release_lock() -> None:
    LOCK_FILE.unlink(missing_ok=True)


def _current_unit(data: dict) -> dict | None:
    for u in data["units"]:
        if not u["done"]:
            return u
    return None


def cmd_validate(args: list[str]) -> int:
    if not args:
        print("error: --validate requires a unit name", file=sys.stderr)
        return 1
    unit_name = args[0]
    if not SESSION_FILE.exists():
        print("error: no active session", file=sys.stderr)
        return 1
    data = _parse_session(SESSION_FILE.read_text(encoding="utf-8"))
    current = _current_unit(data)
    if current is None:
        print("error: all units already complete", file=sys.stderr)
        return 1
    if current["name"] != unit_name:
        print(
            f"error: '{unit_name}' is not the current unit (current: '{current['name']}')",
            file=sys.stderr,
        )
        return 1
    if current["done"]:
        print(f"error: unit '{unit_name}' is already marked complete", file=sys.stderr)
        return 1
    return 0


def cmd_complete(args: list[str]) -> int:
    if not args:
        print("error: --complete requires a unit name", file=sys.stderr)
        return 1
    unit_name = args[0]
    if not SESSION_FILE.exists():
        print("error: no active session", file=sys.stderr)
        return 1
    # Validate first
    rc = cmd_validate([unit_name])
    if rc != 0:
        return rc
    _acquire_lock()
    try:
        data = _parse_session(SESSION_FILE.read_text(encoding="utf-8"))
        for u in data["units"]:
            if u["name"] == unit_name:
                u["done"] = True
                u["completed_at"] = _now()
                break
        data["last_updated"] = _now()
        _atomic_write(SESSION_FILE, _render_session(data))
    finally:
        _release_lock()
    print(f"Unit '{unit_name}' marked complete.")
    remaining = [u for u in data["units"] if not u["done"]]
    if remaining:
        print(f"Next unit: {remaining[0]['name']}")
    else:
        print("All units complete. Run --status for a summary.")
    return 0
```

Update `main()` to route `--validate` and `--complete`:

```python
    if cmd == "--validate":
        return cmd_validate(rest)
    if cmd == "--complete":
        return cmd_complete(rest)
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_raven_session.py::SessionValidateCompleteTests -v
```

Expected: all PASS.

- [ ] **Step 5: Run all session tests**

```bash
python -m pytest tests/test_raven_session.py -v
```

Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add common/.claude/scripts/raven-session.py tests/test_raven_session.py
git commit -m "feat(session): add --validate and --complete with lockfile protocol"
```

---

## Task 4: Add `--archive` to `raven-session.py`

**Files:**
- Modify: `common/.claude/scripts/raven-session.py`
- Modify: `tests/test_raven_session.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_raven_session.py`:

```python
class SessionArchiveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.raven_dir = self.root / ".raven"
        self.raven_dir.mkdir()
        self.session_file = self.raven_dir / "session.md"
        self.archive_file = self.raven_dir / "session-archive.md"

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, args):
        mod = load_session()
        import os; orig = os.getcwd(); os.chdir(self.root)
        try:
            return mod.main(args)
        finally:
            os.chdir(orig)

    def test_archive_moves_completed_units_to_archive_file(self):
        self._run(["--init", "greenfield", "unit-a", "unit-b", "unit-c"])
        self._run(["--complete", "unit-a"])
        self._run(["--complete", "unit-b"])
        self._run(["--archive"])
        archive = self.archive_file.read_text()
        self.assertIn("unit-a", archive)
        self.assertIn("unit-b", archive)

    def test_archive_removes_completed_units_from_session(self):
        self._run(["--init", "greenfield", "unit-a", "unit-b", "unit-c"])
        self._run(["--complete", "unit-a"])
        self._run(["--archive"])
        session = self.session_file.read_text()
        self.assertNotIn("unit-a", session)
        self.assertIn("unit-b", session)

    def test_archive_preserves_pending_units_in_session(self):
        self._run(["--init", "greenfield", "unit-a", "unit-b"])
        self._run(["--complete", "unit-a"])
        self._run(["--archive"])
        session = self.session_file.read_text()
        self.assertIn("unit-b", session)

    def test_archive_appends_to_existing_archive(self):
        self._run(["--init", "greenfield", "unit-a", "unit-b"])
        self._run(["--complete", "unit-a"])
        self._run(["--archive"])
        self._run(["--complete", "unit-b"])
        self._run(["--archive"])
        archive = self.archive_file.read_text()
        self.assertIn("unit-a", archive)
        self.assertIn("unit-b", archive)
```

- [ ] **Step 2: Run to verify failure**

```bash
python -m pytest tests/test_raven_session.py::SessionArchiveTests -v
```

Expected: FAIL.

- [ ] **Step 3: Implement `cmd_archive`**

Add to `common/.claude/scripts/raven-session.py`:

```python
def cmd_archive(args: list[str]) -> int:
    if not SESSION_FILE.exists():
        print("error: no active session", file=sys.stderr)
        return 1
    _acquire_lock()
    try:
        data = _parse_session(SESSION_FILE.read_text(encoding="utf-8"))
        completed = [u for u in data["units"] if u["done"]]
        if not completed:
            print("No completed units to archive.")
            return 0
        # Append completed units to archive
        archive_lines = [f"\n## Archived {_now()}\n"]
        for u in completed:
            entry = f"- [x] {u['name']}"
            if u.get("issue"):
                entry += f" → {u['issue']}"
            if u.get("completed_at"):
                entry += f" (completed {u['completed_at']})"
            archive_lines.append(entry)
        with ARCHIVE_FILE.open("a", encoding="utf-8") as f:
            f.write("\n".join(archive_lines) + "\n")
        # Remove completed units from session
        data["units"] = [u for u in data["units"] if not u["done"]]
        data["last_updated"] = _now()
        _atomic_write(SESSION_FILE, _render_session(data))
    finally:
        _release_lock()
    print(f"Archived {len(completed)} unit(s) to {ARCHIVE_FILE}.")
    return 0
```

Add routing in `main()`:

```python
    if cmd == "--archive":
        return cmd_archive(rest)
```

- [ ] **Step 4: Run archive tests**

```bash
python -m pytest tests/test_raven_session.py::SessionArchiveTests -v
```

Expected: all PASS.

- [ ] **Step 5: Run full test suite**

```bash
python -m pytest tests/test_raven_session.py -v
```

Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add common/.claude/scripts/raven-session.py tests/test_raven_session.py
git commit -m "feat(session): add --archive command"
```

---

## Task 5: Copy `raven-session.py` to Codex scripts

**Files:**
- Create: `common/.codex/scripts/raven-session.py`

- [ ] **Step 1: Copy the script**

```bash
cp common/.claude/scripts/raven-session.py common/.codex/scripts/raven-session.py
```

- [ ] **Step 2: Verify the copy is identical**

```bash
diff common/.claude/scripts/raven-session.py common/.codex/scripts/raven-session.py
```

Expected: no output (files identical).

- [ ] **Step 3: Commit**

```bash
git add common/.codex/scripts/raven-session.py
git commit -m "feat(session): copy raven-session.py to codex scripts"
```

---

## Task 6: Create `raven-session-checkpoint.py` hook (Claude)

**Files:**
- Create: `common/.claude/hooks/raven-session-checkpoint.py`
- Modify: `tests/test_raven_session.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_raven_session.py`:

```python
import importlib.util as _ilu
import io
import json

HOOK_PATH = REPO_ROOT / "common" / ".claude" / "hooks" / "raven-session-checkpoint.py"

def load_hook():
    spec = _ilu.spec_from_file_location("raven_session_checkpoint", HOOK_PATH)
    mod = _ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _claude_payload(command: str) -> str:
    return json.dumps({"tool_input": {"command": command}})


class CheckpointHookTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.raven_dir = self.root / ".raven"
        self.raven_dir.mkdir()
        self.config_file = self.raven_dir / "config.toml"
        self.session_file = self.raven_dir / "session.md"

    def tearDown(self):
        self.tmp.cleanup()

    def _run_hook(self, payload_str: str) -> int:
        mod = load_hook()
        import os; orig = os.getcwd(); os.chdir(self.root)
        try:
            with patch("sys.stdin", io.StringIO(payload_str)):
                return mod.main()
        finally:
            os.chdir(orig)

    def test_hook_allows_when_enforcement_disabled(self):
        self.config_file.write_text(
            "[lifecycle]\ncheckpoint_enforcement = false\n", encoding="utf-8"
        )
        rc = self._run_hook(_claude_payload("python .claude/scripts/raven-session.py --complete unit-a"))
        self.assertEqual(rc, 0)

    def test_hook_denies_when_no_session(self):
        self.config_file.write_text(
            "[lifecycle]\ncheckpoint_enforcement = true\n", encoding="utf-8"
        )
        rc = self._run_hook(_claude_payload("python .claude/scripts/raven-session.py --complete unit-a"))
        self.assertNotEqual(rc, 0)

    def test_hook_allows_valid_checkpoint(self):
        self.config_file.write_text(
            "[lifecycle]\ncheckpoint_enforcement = true\n", encoding="utf-8"
        )
        # Write a valid session with unit-a as current
        from unittest.mock import patch as _patch
        import os; orig = os.getcwd(); os.chdir(self.root)
        try:
            mod = load_session()
            mod.main(["--init", "greenfield", "unit-a", "unit-b"])
        finally:
            os.chdir(orig)
        rc = self._run_hook(_claude_payload("python .claude/scripts/raven-session.py --complete unit-a"))
        self.assertEqual(rc, 0)

    def test_hook_denies_wrong_unit(self):
        self.config_file.write_text(
            "[lifecycle]\ncheckpoint_enforcement = true\n", encoding="utf-8"
        )
        import os; orig = os.getcwd(); os.chdir(self.root)
        try:
            mod = load_session()
            mod.main(["--init", "greenfield", "unit-a", "unit-b"])
        finally:
            os.chdir(orig)
        rc = self._run_hook(_claude_payload("python .claude/scripts/raven-session.py --complete unit-b"))
        self.assertNotEqual(rc, 0)
```

- [ ] **Step 2: Run to verify failure**

```bash
python -m pytest tests/test_raven_session.py::CheckpointHookTests -v
```

Expected: ERROR — hook file does not exist.

- [ ] **Step 3: Create `common/.claude/hooks/raven-session-checkpoint.py`**

```python
#!/usr/bin/env python3
"""PreToolUse hook: validate raven-session.py --complete before allowing."""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path


def _load_payload() -> dict | None:
    try:
        return json.load(sys.stdin)
    except Exception:
        return None


def _extract_command(payload: dict) -> str:
    tool_input = payload.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        tool_input = {}
    return tool_input.get("command") or payload.get("command") or ""


def _is_codex_hook(payload: dict) -> bool:
    return "hook_event_name" in payload or "tool_name" in payload


def _deny(message: str, payload: dict) -> int:
    if _is_codex_hook(payload):
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": message,
            }
        }))
        return 0
    print(message, file=sys.stderr)
    return 2


def _enforcement_enabled() -> bool:
    config = Path(".raven/config.toml")
    if not config.exists():
        return True
    for line in config.read_text(encoding="utf-8").splitlines():
        if "checkpoint_enforcement" in line and "false" in line:
            return False
    return True


def _extract_unit(command: str) -> str | None:
    m = re.search(r"--complete\s+(\S+)", command)
    return m.group(1) if m else None


def main() -> int:
    payload = _load_payload()
    if payload is None:
        return 0

    if not _enforcement_enabled():
        return 0

    if not Path(".raven/session.md").exists():
        return _deny("No active session. Run raven-session.py --init first.", payload)

    command = _extract_command(payload)
    unit = _extract_unit(command)
    if not unit:
        return 0  # not a --complete call we can parse; allow through

    result = subprocess.run(
        [sys.executable, ".claude/scripts/raven-session.py", "--validate", unit],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        msg = result.stderr.strip() or result.stdout.strip() or f"Cannot complete unit '{unit}'"
        return _deny(msg, payload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run hook tests**

```bash
python -m pytest tests/test_raven_session.py::CheckpointHookTests -v
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add common/.claude/hooks/raven-session-checkpoint.py tests/test_raven_session.py
git commit -m "feat(hooks): add raven-session-checkpoint PreToolUse hook (Claude)"
```

---

## Task 7: Create Codex session checkpoint hook and register both hooks

**Files:**
- Create: `common/.codex/hooks/raven-session-checkpoint.py`
- Modify: `common/.claude/settings.json`
- Modify: `common/.codex/hooks.json`

- [ ] **Step 1: Create Codex hook (differs only in script path)**

```bash
cp common/.claude/hooks/raven-session-checkpoint.py common/.codex/hooks/raven-session-checkpoint.py
```

Edit `common/.codex/hooks/raven-session-checkpoint.py` — change the subprocess call path:

Find:
```python
        [sys.executable, ".claude/scripts/raven-session.py", "--validate", unit],
```

Replace with:
```python
        [sys.executable, ".codex/scripts/raven-session.py", "--validate", unit],
```

- [ ] **Step 2: Register hook in `common/.claude/settings.json`**

Add a new entry to the `"PreToolUse"` array:

```json
{
  "matcher": "raven-session.*--complete",
  "hooks": [
    {
      "type": "command",
      "command": "python .claude/hooks/raven-session-checkpoint.py"
    }
  ]
}
```

Full updated `"PreToolUse"` array:

```json
"PreToolUse": [
  {
    "matcher": "Bash",
    "hooks": [
      {
        "type": "command",
        "command": "python .claude/hooks/raven-pre-bash-guard.py"
      }
    ]
  },
  {
    "matcher": "Write|Edit|MultiEdit",
    "hooks": [
      {
        "type": "command",
        "command": "python .claude/hooks/raven-pre-edit-guard.py"
      }
    ]
  },
  {
    "matcher": "raven-session.*--complete",
    "hooks": [
      {
        "type": "command",
        "command": "python .claude/hooks/raven-session-checkpoint.py"
      }
    ]
  }
]
```

- [ ] **Step 3: Register hook in `common/.codex/hooks.json`**

Add a new object to the `"PreToolUse"` array:

```json
{
  "matcher": "raven-session.*--complete",
  "hooks": [
    {
      "type": "command",
      "command": "python .codex/hooks/raven-session-checkpoint.py",
      "timeout": 10,
      "statusMessage": "Validating session checkpoint"
    }
  ]
}
```

- [ ] **Step 4: Validate JSON is well-formed**

```bash
python -m json.tool common/.claude/settings.json > /dev/null && echo "OK"
python -m json.tool common/.codex/hooks.json > /dev/null && echo "OK"
```

Expected: both print `OK`.

- [ ] **Step 5: Commit**

```bash
git add common/.codex/hooks/raven-session-checkpoint.py common/.claude/settings.json common/.codex/hooks.json
git commit -m "feat(hooks): register session checkpoint hook for Claude and Codex"
```

---

## Task 8: Create `raven-project-lifecycle` skill

**Files:**
- Create: `common/.agents/skills/raven-project-lifecycle/SKILL.md`

- [ ] **Step 1: Create the skill file**

```bash
mkdir -p common/.agents/skills/raven-project-lifecycle
```

Write `common/.agents/skills/raven-project-lifecycle/SKILL.md`:

```markdown
---
name: raven-project-lifecycle
description: Use for multi-session or multi-unit tasks where you need brownfield detection, work scoping, and session state. Skip for single-unit tasks, one-off fixes, or doc-only changes.
---

# Project Lifecycle

Lightweight session orchestration for tasks that span multiple units or sessions. Scopes work, tracks progress, and delegates execution to appropriate Raven skills. Does not replace AI-DLC or full lifecycle frameworks — use those when you need phased requirements, NFR design, or structured approval workflows.

For projects with an external issue tracker, check `[issue_tracker].platform` in `.raven/config.toml`:
- `platform = "github"`: use `raven-github-issues` for issue-driven execution alongside this skill
- `platform = "gitlab"`: use `raven-gitlab-issues` alongside this skill
- `platform = "none"`: this skill is the sole task tracker

## Skip When

- The task is a single unit completable in one session with no context-loss risk
- The user has already scoped and decomposed the work explicitly
- The task is a one-off fix, doc change, or isolated refactor

## Required Constraints

- Never implement code directly; always delegate to the appropriate Raven execution skill
- Always call `python .claude/scripts/raven-session.py --status` before beginning Phase 3 to confirm the current unit
- Always call `python .claude/scripts/raven-session.py --complete <unit>` at the end of each unit — the checkpoint hook will validate before allowing it
- Never skip the checkpoint call to move faster

## Phase 1 — Workspace Detection

1. Check for existing `.raven/session.md`:
   - If found: run `python .claude/scripts/raven-session.py --status` and jump to Phase 3
2. Scan for brownfield signals: source files, dependency manifests, git history, existing configs
3. Classify: **greenfield** (no existing code) or **brownfield** (existing codebase)
4. If brownfield: invoke `raven-codebase-discovery` to build architecture context before scoping

## Phase 2 — Scoping

1. Decompose the work into ordered, named units — each completable in a single session
2. Name units with kebab-case (e.g., `add-auth-middleware`, `write-auth-tests`)
3. Run: `python .claude/scripts/raven-session.py --init <greenfield|brownfield> <unit-1> <unit-2> ...`
   - If the parent task is a tracked issue and `[issue_tracker].platform` is set, add `--parent <issue-number>`
   - After `--init`, create child issues manually using `gh issue create` or `glab issue create` and record their numbers in `session.md`
4. Present the unit plan to the user and wait for confirmation before proceeding

## Phase 3 — Execution Loop *(repeats per unit)*

1. Run `python .claude/scripts/raven-session.py --status` — confirm the current unit
2. Select the appropriate Raven execution skill:
   - New feature or behavior → `raven-implement-feature`
   - Rename, move, or API change → `raven-safe-refactor`
   - Test coverage gap → `raven-write-tests`
   - Failing behavior → `raven-debug-failure`
3. Execute that skill for the current unit
4. Run `python .claude/scripts/raven-session.py --complete <unit-name>`
   - The checkpoint hook validates this before allowing it to succeed
5. If the context block in `session.md` grows large, the script will warn — run `--archive` after user confirmation
6. Advance to the next unit

## Phase 4 — Wrap-up

1. Run `python .claude/scripts/raven-session.py --status` to confirm all units complete
2. Summarize changes across all units and files touched
3. Suggest next steps: PR, review, deploy
```

- [ ] **Step 2: Commit**

```bash
git add common/.agents/skills/raven-project-lifecycle/SKILL.md
git commit -m "feat(skills): add raven-project-lifecycle skill"
```

---

## Task 9: Create `raven-github-issues` skill

**Files:**
- Create: `common/.agents/skills/raven-github-issues/SKILL.md`

- [ ] **Step 1: Create the skill file**

```bash
mkdir -p common/.agents/skills/raven-github-issues
```

Write `common/.agents/skills/raven-github-issues/SKILL.md`:

```markdown
---
name: raven-github-issues
description: Use when GitHub Issues are the source of truth for task execution. Requires gh CLI and platform = "github" in .raven/config.toml.
---

# GitHub Issues Workflow

Use this skill when GitHub Issues are the source of truth for task execution.

If your project uses `raven-project-lifecycle` for local session tracking, treat them as complementary: `raven-project-lifecycle` manages local execution state; this skill manages external issue visibility and drives work from issue scope.

Before using this skill, verify `[issue_tracker].platform = "github"` in `.raven/config.toml`. If a different platform is configured, confirm with the user before proceeding.

## Goal

Keep execution state, follow-up work, and completion status in GitHub Issues rather than chat or local task trackers.

## Workflow

1. Read the full issue context before implementation:
   - description, comments, any linked issues or PRs if relevant
2. Extract the goal, scope, and acceptance criteria
3. Verify the issue is still active and not already completed or superseded
4. If beginning work, signal intent by commenting on the issue
5. If the issue is unclear or incomplete, update it before proceeding
6. For non-trivial work, track current step in the issue or a linked planning document
7. Execute work strictly within issue scope
8. If new durable work is discovered: create follow-up issues, do not expand scope silently
9. If work is partially complete or blocked: update the issue with current status and blockers
10. Close or update the issue when the work is complete

## Execution Rules

- Work from issue scope and acceptance criteria
- If using `raven-project-lifecycle` alongside this skill, units of work map to child issues — create them with `gh issue create --parent <n>` (requires gh v2.49+; older versions: add task-list checkboxes in parent body instead)
- Update the issue when the plan changes materially
- Always treat the GitHub Issue as the source of truth for current state
- Resume work based on issue state, not prior chat context

## Common Commands

```bash
gh issue list
gh issue view <number>
gh issue comment <number> --body "Starting work on this"
gh issue create --title "..." --body "..." --parent <number>
gh issue edit <number> --add-label "in-progress"
gh issue close <number> --comment "Completed in <sha>"
```

## Heuristics

Use this skill when:
- The repo policy says GitHub Issues are the primary task system
- The user asks to open, update, or close issues
- Work should be tracked durably across sessions
- Multiple sessions or agents may interact with the same work
```

- [ ] **Step 2: Commit**

```bash
git add common/.agents/skills/raven-github-issues/SKILL.md
git commit -m "feat(skills): add raven-github-issues skill"
```

---

## Task 10: Create `raven-gitlab-issues` skill

**Files:**
- Create: `common/.agents/skills/raven-gitlab-issues/SKILL.md`

- [ ] **Step 1: Create the skill file**

```bash
mkdir -p common/.agents/skills/raven-gitlab-issues
```

Write `common/.agents/skills/raven-gitlab-issues/SKILL.md`:

```markdown
---
name: raven-gitlab-issues
description: Use when GitLab issues are the source of truth for task execution. Requires glab CLI and platform = "gitlab" in .raven/config.toml.
---

# GitLab Issues Workflow

Use this skill when GitLab issues are the source of truth for task execution.

If your project uses `raven-project-lifecycle` for local session tracking, treat them as complementary: `raven-project-lifecycle` manages local execution state; this skill manages external issue visibility and drives work from issue scope.

Before using this skill, verify `[issue_tracker].platform = "gitlab"` in `.raven/config.toml`. If a different platform is configured, confirm with the user before proceeding.

## Goal

Keep execution state, follow-up work, and completion status in GitLab issues rather than chat or local task trackers.

## Workflow

1. Read the full issue context before implementation:
   - description, comments, any linked issues or merge requests if relevant
2. Extract the goal, scope, and acceptance criteria
3. Verify the issue is still active and not already completed or superseded
4. If beginning work, signal intent by adding a note to the issue
5. If the issue is unclear or incomplete, update it before proceeding
6. For non-trivial work, track current step in the issue or a linked planning document
7. Execute work strictly within issue scope
8. If new durable work is discovered: create follow-up issues, do not expand scope silently
9. If work is partially complete or blocked: update the issue with current status and blockers
10. Close or update the issue when the work is complete

## Execution Rules

- Work from issue scope and acceptance criteria
- If using `raven-project-lifecycle` alongside this skill, units of work map to child issues — create them with `glab issue create --parent-id <n>`
- Update the issue when the plan changes materially
- Always treat the GitLab issue as the source of truth for current state
- Resume work based on issue state, not prior chat context

## Common Commands

```bash
glab issue list
glab issue view <number>
glab issue note <number> -m "Starting work on this"
glab issue create --title "..." --description "..." --parent-id <number>
glab issue update <number> --label "in-progress"
glab issue close <number> -m "Completed in <sha>"
```

## Heuristics

Use this skill when:
- The repo policy says GitLab issues are the primary task system
- The user asks to open, update, or close issues or merge requests
- Work should be tracked durably across sessions
- Multiple sessions or agents may interact with the same work
```

- [ ] **Step 2: Commit**

```bash
git add common/.agents/skills/raven-gitlab-issues/SKILL.md
git commit -m "feat(skills): add raven-gitlab-issues skill"
```

---

## Task 11: Update `raven-namespace.md` and `raven-tool-bootstrap`

**Files:**
- Modify: `common/.claude/docs/raven-namespace.md`
- Modify: `common/.agents/skills/raven-tool-bootstrap/SKILL.md`

- [ ] **Step 1: Add session paths to `raven-namespace.md`**

In `common/.claude/docs/raven-namespace.md`, find the `## Raven-Owned Paths` section and add:

```markdown
- `.raven/session.md` (gitignored; per-project lifecycle state)
- `.raven/session.lock` (transient; never committed)
- `.raven/session-archive.md` (gitignored; completed unit history)
```

- [ ] **Step 2: Add gh/glab to `raven-tool-bootstrap`**

In `common/.agents/skills/raven-tool-bootstrap/SKILL.md`, add a new section after `## Commands`:

```markdown
## Issue-Tracker CLI Tools

These are checked only when `[issue_tracker].platform` is set in `.raven/config.toml`:

| Platform | CLI | Install |
|---|---|---|
| `github` | `gh` | `brew install gh` / https://cli.github.com |
| `gitlab` | `glab` | `brew install glab` / https://gitlab.com/gitlab-org/cli |

If `platform = "github"` and `gh` is missing, or `platform = "gitlab"` and `glab` is missing, ask the user whether to install, get instructions, remind later, or stop reminding — same flow as other missing tools.

For GitHub sub-issues (used with `--parent` in `raven-session.py`), verify `gh` version is v2.49 or later:

```bash
gh --version
```

If older, note that `--parent` will fall back to task-list checkboxes in the parent issue body.
```

- [ ] **Step 3: Commit**

```bash
git add common/.claude/docs/raven-namespace.md common/.agents/skills/raven-tool-bootstrap/SKILL.md
git commit -m "docs: update namespace and tool-bootstrap for lifecycle and issue-tracker tools"
```

---

## Task 12: Run full test suite and self-check

**Files:** none (verification only)

- [ ] **Step 1: Run linter**

```bash
just lint
```

Expected: no errors. Fix any `ruff` findings before proceeding.

- [ ] **Step 2: Run type checker**

```bash
just typecheck
```

Expected: no errors on new files. If pyright flags missing stubs or type issues in `raven-session.py`, fix them (add type annotations where missing, use `Path.unlink(missing_ok=True)` correctly, etc.).

- [ ] **Step 3: Run full test suite**

```bash
just test
```

Expected: all tests PASS including new `tests/test_raven_session.py`.

- [ ] **Step 4: Run self-check**

```bash
python scripts/self-check.py
```

Expected: self-check passes, upgrade dry-run shows new skill files as additions, no unexpected changes to existing managed files.

- [ ] **Step 5: Fix any self-check failures, then commit**

If self-check reports unexpected changes, inspect the diff output and resolve before committing.

```bash
git add -p  # stage only verified changes
git commit -m "fix: resolve self-check findings for lifecycle feature"
```

---

## Spec Coverage Check

| Spec requirement | Covered by |
|---|---|
| `[lifecycle].checkpoint_enforcement` config | Task 1 |
| `[issue_tracker].platform` config | Task 1 |
| `raven-session.py --init` with `--parent` | Task 2 |
| `raven-session.py --status` | Task 2 |
| `raven-session.py --validate` | Task 3 |
| `raven-session.py --complete` | Task 3 |
| Lockfile protocol (stale PID, retry, error) | Task 3 |
| Atomic writes | Task 2–3 |
| `raven-session.py --archive` | Task 4 |
| `.gitignore` entries written by `--init` | Task 2 |
| Codex copy of `raven-session.py` | Task 5 |
| `raven-session-checkpoint.py` (Claude) | Task 6 |
| `raven-session-checkpoint.py` (Codex) | Task 7 |
| Hook registered in `settings.json` | Task 7 |
| Hook registered in `hooks.json` | Task 7 |
| `raven-project-lifecycle` SKILL.md | Task 8 |
| `raven-github-issues` SKILL.md | Task 9 |
| `raven-gitlab-issues` SKILL.md | Task 10 |
| `raven-namespace.md` updated | Task 11 |
| `raven-tool-bootstrap` updated (gh/glab) | Task 11 |
| Self-check passes | Task 12 |
