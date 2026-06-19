# raven doctor & raven assess Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add two read-only Raven CLI subcommands — `raven doctor` (diagnoses Raven's install + local toolchain) and `raven assess` (grades the project against its template's standards) — that emit severity-scored, `--json`-capable reports and exit non-zero only on `error` findings.

**Architecture:** A shared `assess.py` engine produces an ordered `list[Finding]`; `report.py` renders findings as human text or JSON and maps severity to the exit code. `doctor` and `assess` are thin `cmd_*` functions in `cli.py` that assemble findings from existing Raven modules (`config.py`, `manifest.py`, `apply.classify`, `blocks.pending_merge_paths`), a declarative per-language gate table (`data/gates.toml`), and a subprocess call to the installed `raven-tool-check.py --json`. All subprocess and tool probing goes through one injectable runner so tests never invoke real tools.

**Tech Stack:** Python 3 standard library only (argparse, dataclasses, enum, json, subprocess, pathlib, tomllib). Tests use `unittest` via `tests/helpers.py`. No new third-party dependencies.

## Global Constraints

- No new third-party dependencies; standard library plus existing `raven_lib` modules only.
- Both commands are strictly read-only: no file writes, no auto-fix, no tool/dependency installation.
- Severity → exit code: any `error` finding → exit `1`; otherwise exit `0` (including when only `warn`/`ok` findings exist).
- Type hints required on all new signatures; no `Any` in typed code; prefer `T | None` over `Optional[T]`; no mutable default arguments.
- Catch specific exceptions; never bare `except`. Malformed config/manifest/tool-check output must surface as findings, not uncaught exceptions.
- Follow existing `tests/` patterns: subclass `RavenTestCase` from `tests/helpers.py`, run via `python scripts/self-check.py` / `python -m unittest discover`.
- `Finding.id` values are stable strings (e.g. `"doctor.config.schema"`); JSON output and tests key off them.
- All new code lives under `scripts/raven_lib/`; data file under `scripts/raven_lib/data/`.
- Lint/format/typecheck with the repo gates (`ruff check .`, `ruff format .`, `pyright`) before each commit; fix issues in touched code.

---

### Task 1: Finding model and severity→exit mapping

**Files:**
- Create: `scripts/raven_lib/findings.py`
- Test: `tests/test_findings.py`

**Interfaces:**
- Produces:
  - `class Severity(str, Enum)` with members `OK = "ok"`, `WARN = "warn"`, `ERROR = "error"`.
  - `@dataclass(frozen=True) class Finding` with fields `id: str`, `severity: Severity`, `category: str`, `title: str`, `detail: str`, `fix: str | None = None`.
  - `def exit_code(findings: list[Finding]) -> int` — returns `1` if any finding has `severity == Severity.ERROR`, else `0`.
  - `def summarize(findings: list[Finding]) -> dict[str, int]` — returns `{"errors": int, "warnings": int, "ok": int}`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_findings.py
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from raven_lib.findings import Finding, Severity, exit_code, summarize


class FindingsTests(unittest.TestCase):
    def _f(self, severity: Severity) -> Finding:
        return Finding(id="x", severity=severity, category="C", title="t", detail="d")

    def test_exit_code_zero_when_no_errors(self):
        findings = [self._f(Severity.OK), self._f(Severity.WARN)]
        self.assertEqual(exit_code(findings), 0)

    def test_exit_code_one_when_any_error(self):
        findings = [self._f(Severity.OK), self._f(Severity.ERROR)]
        self.assertEqual(exit_code(findings), 1)

    def test_summarize_counts_by_severity(self):
        findings = [self._f(Severity.OK), self._f(Severity.WARN), self._f(Severity.ERROR), self._f(Severity.OK)]
        self.assertEqual(summarize(findings), {"errors": 1, "warnings": 1, "ok": 2})

    def test_severity_value_is_lowercase_string(self):
        self.assertEqual(Severity.WARN.value, "warn")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_findings -v` (from repo root, after `cd` is not needed — run `python -m unittest discover -s tests` style; use `PYTHONPATH=scripts python -m unittest tests.test_findings -v`)
Expected: FAIL with `ModuleNotFoundError: No module named 'raven_lib.findings'`.

- [ ] **Step 3: Write minimal implementation**

```python
# scripts/raven_lib/findings.py
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Severity(str, Enum):
    OK = "ok"
    WARN = "warn"
    ERROR = "error"


@dataclass(frozen=True)
class Finding:
    id: str
    severity: Severity
    category: str
    title: str
    detail: str
    fix: str | None = None


def exit_code(findings: list[Finding]) -> int:
    return 1 if any(f.severity is Severity.ERROR for f in findings) else 0


def summarize(findings: list[Finding]) -> dict[str, int]:
    return {
        "errors": sum(1 for f in findings if f.severity is Severity.ERROR),
        "warnings": sum(1 for f in findings if f.severity is Severity.WARN),
        "ok": sum(1 for f in findings if f.severity is Severity.OK),
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=scripts python -m unittest tests.test_findings -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add scripts/raven_lib/findings.py tests/test_findings.py
git commit -m "feat(assess): add Finding model and severity exit mapping"
```

---

### Task 2: Report rendering (human + JSON)

**Files:**
- Create: `scripts/raven_lib/report.py`
- Test: `tests/test_report.py`

**Interfaces:**
- Consumes: `Finding`, `Severity`, `summarize` from `raven_lib.findings`.
- Produces:
  - `def render_human(command: str, os_name: str, findings: list[Finding]) -> str` — grouped by `category` in first-seen order; one line per finding prefixed `✓ ` (OK) / `! ` (WARN) / `✗ ` (ERROR), showing `title`; for non-OK findings, an indented `detail` line and, when `fix` is set, an indented `fix: <text>` line. Ends with a summary line `Summary: {errors} errors, {warnings} warnings, {ok} ok`.
  - `def render_json(command: str, os_name: str, findings: list[Finding]) -> str` — JSON string of `{"command", "os", "findings": [{"id","severity","category","title","detail","fix"}...], "summary": {...}}`, `indent=2`. `severity` serializes to its `.value`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_report.py
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from raven_lib.findings import Finding, Severity
from raven_lib.report import render_human, render_json


def _findings() -> list[Finding]:
    return [
        Finding(id="a.ok", severity=Severity.OK, category="Toolchain", title="ripgrep present", detail="found"),
        Finding(id="a.warn", severity=Severity.WARN, category="Toolchain", title="fd missing", detail="not found", fix="install fd"),
        Finding(id="b.err", severity=Severity.ERROR, category="Install integrity", title="config missing", detail="no config.toml", fix="run raven install"),
    ]


class ReportTests(unittest.TestCase):
    def test_human_groups_by_category_and_marks_severity(self):
        out = render_human("doctor", "darwin", _findings())
        self.assertIn("Toolchain", out)
        self.assertIn("Install integrity", out)
        self.assertIn("✓ ripgrep present", out)
        self.assertIn("! fd missing", out)
        self.assertIn("✗ config missing", out)
        self.assertIn("fix: install fd", out)
        self.assertIn("Summary: 1 errors, 1 warnings, 1 ok", out)

    def test_human_omits_fix_for_ok(self):
        out = render_human("doctor", "darwin", _findings())
        # The OK line has no "fix:" immediately associated; fix only appears for warn/error.
        self.assertEqual(out.count("fix:"), 2)

    def test_json_is_machine_readable(self):
        out = render_json("assess", "linux", _findings())
        data = json.loads(out)
        self.assertEqual(data["command"], "assess")
        self.assertEqual(data["os"], "linux")
        self.assertEqual(data["summary"], {"errors": 1, "warnings": 1, "ok": 1})
        self.assertEqual(data["findings"][1]["severity"], "warn")
        self.assertEqual(data["findings"][2]["fix"], "run raven install")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=scripts python -m unittest tests.test_report -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'raven_lib.report'`.

- [ ] **Step 3: Write minimal implementation**

```python
# scripts/raven_lib/report.py
from __future__ import annotations

import json

from .findings import Finding, Severity, summarize

_MARK = {Severity.OK: "✓", Severity.WARN: "!", Severity.ERROR: "✗"}


def render_human(command: str, os_name: str, findings: list[Finding]) -> str:
    lines: list[str] = [f"raven {command} ({os_name})", ""]
    seen: list[str] = []
    for category in [f.category for f in findings]:
        if category not in seen:
            seen.append(category)
    for category in seen:
        lines.append(category)
        for finding in [f for f in findings if f.category == category]:
            lines.append(f"  {_MARK[finding.severity]} {finding.title}")
            if finding.severity is not Severity.OK:
                lines.append(f"      {finding.detail}")
                if finding.fix:
                    lines.append(f"      fix: {finding.fix}")
        lines.append("")
    counts = summarize(findings)
    lines.append(
        f"Summary: {counts['errors']} errors, {counts['warnings']} warnings, {counts['ok']} ok"
    )
    return "\n".join(lines)


def render_json(command: str, os_name: str, findings: list[Finding]) -> str:
    payload = {
        "command": command,
        "os": os_name,
        "findings": [
            {
                "id": f.id,
                "severity": f.severity.value,
                "category": f.category,
                "title": f.title,
                "detail": f.detail,
                "fix": f.fix,
            }
            for f in findings
        ],
        "summary": summarize(findings),
    }
    return json.dumps(payload, indent=2)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=scripts python -m unittest tests.test_report -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add scripts/raven_lib/report.py tests/test_report.py
git commit -m "feat(assess): add human and JSON report rendering"
```

---

### Task 3: Per-language gate table (data + loader)

**Files:**
- Create: `scripts/raven_lib/data/gates.toml`
- Create: `scripts/raven_lib/gates.py`
- Test: `tests/test_gates.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) class GateSpec` with fields `recipes: tuple[str, ...]`, `tools: tuple[str, ...]`, `config_signals: tuple[tuple[str, str | None], ...]` (each is `(file, substring_or_None)`), `detect_signals: tuple[str, ...]`, `fallback_commands: dict[str, tuple[str, ...]]`.
  - `def load_gate_specs() -> dict[str, GateSpec]` — parses `data/gates.toml` (via `tomllib`) into a `template_name -> GateSpec` map.
  - `def gate_spec_for(template: str) -> GateSpec | None` — convenience lookup.

**Notes:** Cover the templates that ship justfiles. `python` is authoritative for tests; include `go`, `rust`, `typescript`, `swift`, `elixir`, `lua` with their gate recipes. Inspect each `<lang>/justfile` to copy the real recipe names and `<lang>` config signal files; do not invent recipe names. The python values below are verified from `python/justfile` and `python/pyproject.toml`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_gates.py
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from raven_lib.gates import GateSpec, gate_spec_for, load_gate_specs


class GatesTests(unittest.TestCase):
    def test_python_gate_spec_present(self):
        specs = load_gate_specs()
        self.assertIn("python", specs)
        spec = specs["python"]
        self.assertIsInstance(spec, GateSpec)

    def test_python_recipes_match_justfile(self):
        spec = gate_spec_for("python")
        assert spec is not None
        for recipe in ("lint", "format", "typecheck", "test"):
            self.assertIn(recipe, spec.recipes)

    def test_python_detect_signals_include_pyproject(self):
        spec = gate_spec_for("python")
        assert spec is not None
        self.assertIn("pyproject.toml", spec.detect_signals)

    def test_python_fallback_for_lint_is_ruff(self):
        spec = gate_spec_for("python")
        assert spec is not None
        self.assertEqual(spec.fallback_commands["lint"], ("ruff", "check", "."))

    def test_unknown_template_returns_none(self):
        self.assertIsNone(gate_spec_for("cobol"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=scripts python -m unittest tests.test_gates -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'raven_lib.gates'`.

- [ ] **Step 3a: Create the data file**

Inspect `python/justfile`, `go/justfile`, `rust/justfile`, `typescript/justfile`, `swift/justfile`, `elixir/justfile`, `lua/justfile` first and copy real recipe names. The `python` block below is verified.

```toml
# scripts/raven_lib/data/gates.toml
# Per-language gate expectations consumed by `raven assess`.
# Each [<template>] entry declares the justfile recipes, gate tool ids,
# tool-config signals, language-detection signals, and non-just fallback
# commands for that template. Keep recipe names in sync with <template>/justfile.

[python]
recipes = ["lint", "format", "typecheck", "test"]
tools = ["ruff", "pyright"]
detect_signals = ["pyproject.toml", "setup.py", "setup.cfg"]
# config_signals: each entry is [file, required_substring]; substring "" means
# "file must merely exist".
config_signals = [["pyproject.toml", "[tool.ruff]"]]

[python.fallback_commands]
lint = ["ruff", "check", "."]
format = ["ruff", "format", "--check", "."]
typecheck = ["pyright"]
test = ["python", "-m", "pytest"]

# Repeat a [<template>] + [<template>.fallback_commands] block per language,
# copying recipe names and config files from each <template>/justfile.
```

- [ ] **Step 3b: Write the loader**

```python
# scripts/raven_lib/gates.py
from __future__ import annotations

import tomllib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

_GATES_PATH = Path(__file__).resolve().parent / "data" / "gates.toml"


@dataclass(frozen=True)
class GateSpec:
    recipes: tuple[str, ...]
    tools: tuple[str, ...]
    config_signals: tuple[tuple[str, str | None], ...]
    detect_signals: tuple[str, ...]
    fallback_commands: dict[str, tuple[str, ...]]


def _build_spec(raw: dict[str, object]) -> GateSpec:
    recipes = tuple(str(r) for r in raw.get("recipes", []))  # type: ignore[union-attr]
    tools = tuple(str(t) for t in raw.get("tools", []))  # type: ignore[union-attr]
    detect = tuple(str(s) for s in raw.get("detect_signals", []))  # type: ignore[union-attr]
    config_signals_raw = raw.get("config_signals", [])
    config_signals: list[tuple[str, str | None]] = []
    if isinstance(config_signals_raw, list):
        for pair in config_signals_raw:
            if isinstance(pair, list) and pair:
                file = str(pair[0])
                substring = str(pair[1]) if len(pair) > 1 and pair[1] != "" else None
                config_signals.append((file, substring))
    fallback_raw = raw.get("fallback_commands", {})
    fallback: dict[str, tuple[str, ...]] = {}
    if isinstance(fallback_raw, dict):
        for recipe, command in fallback_raw.items():
            if isinstance(command, list):
                fallback[str(recipe)] = tuple(str(part) for part in command)
    return GateSpec(
        recipes=recipes,
        tools=tools,
        config_signals=tuple(config_signals),
        detect_signals=detect,
        fallback_commands=fallback,
    )


@lru_cache(maxsize=1)
def load_gate_specs() -> dict[str, GateSpec]:
    data = tomllib.loads(_GATES_PATH.read_text(encoding="utf-8"))
    return {name: _build_spec(raw) for name, raw in data.items() if isinstance(raw, dict)}


def gate_spec_for(template: str) -> GateSpec | None:
    return load_gate_specs().get(template)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=scripts python -m unittest tests.test_gates -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add scripts/raven_lib/data/gates.toml scripts/raven_lib/gates.py tests/test_gates.py
git commit -m "feat(assess): add declarative per-language gate table"
```

---

### Task 4: Injectable command runner

**Files:**
- Create: `scripts/raven_lib/runner.py`
- Test: `tests/test_runner.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) class RunResult` with fields `ok: bool` (process returned 0), `code: int`, `stdout: str`, `stderr: str`, `found: bool` (executable existed), `timed_out: bool`.
  - `def run_command(command: list[str], cwd: Path, timeout: int = 120) -> RunResult` — resolves `command[0]` with `shutil.which`; if absent returns `RunResult(ok=False, code=127, stdout="", stderr="", found=False, timed_out=False)`; otherwise runs via `subprocess.run` capturing text output; on `subprocess.TimeoutExpired` returns `timed_out=True, ok=False, code=124`.
  - `Runner` type alias: `Runner = Callable[[list[str], Path], RunResult]` (timeout bound by callers). `assess.py`/`doctor` accept a `Runner` parameter defaulting to a thin wrapper around `run_command` so tests inject a fake.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_runner.py
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from raven_lib.runner import RunResult, run_command


class RunnerTests(unittest.TestCase):
    def test_missing_executable_reports_not_found(self):
        result = run_command(["definitely-not-a-real-binary-xyz"], Path.cwd())
        self.assertFalse(result.found)
        self.assertFalse(result.ok)
        self.assertEqual(result.code, 127)

    def test_true_command_succeeds(self):
        # `python -c "pass"` is portable and always present in this repo's env.
        result = run_command([sys.executable, "-c", "pass"], Path.cwd())
        self.assertTrue(result.found)
        self.assertTrue(result.ok)
        self.assertEqual(result.code, 0)

    def test_nonzero_command_reports_failure(self):
        result = run_command([sys.executable, "-c", "import sys; sys.exit(3)"], Path.cwd())
        self.assertTrue(result.found)
        self.assertFalse(result.ok)
        self.assertEqual(result.code, 3)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=scripts python -m unittest tests.test_runner -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'raven_lib.runner'`.

- [ ] **Step 3: Write minimal implementation**

```python
# scripts/raven_lib/runner.py
from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


@dataclass(frozen=True)
class RunResult:
    ok: bool
    code: int
    stdout: str
    stderr: str
    found: bool
    timed_out: bool


def run_command(command: list[str], cwd: Path, timeout: int = 120) -> RunResult:
    executable = shutil.which(command[0])
    if executable is None:
        return RunResult(ok=False, code=127, stdout="", stderr="", found=False, timed_out=False)
    try:
        completed = subprocess.run(
            [executable, *command[1:]],
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return RunResult(ok=False, code=124, stdout="", stderr="", found=True, timed_out=True)
    return RunResult(
        ok=completed.returncode == 0,
        code=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
        found=True,
        timed_out=False,
    )


Runner = Callable[[list[str], Path], RunResult]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=scripts python -m unittest tests.test_runner -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add scripts/raven_lib/runner.py tests/test_runner.py
git commit -m "feat(assess): add injectable command runner"
```

---

### Task 5: doctor — install integrity & drift checks

**Files:**
- Create: `scripts/raven_lib/doctor.py`
- Test: `tests/test_doctor.py`

**Interfaces:**
- Consumes: `Finding`, `Severity` (findings); `load_config` (`config.py`) → `RavenConfig`; `load_manifest` (`manifest.py`); `classify` (`apply.py`) → `Classification`; `pending_merge_paths` (`blocks.py`); `entries_for_destination` (`template.py`); `git_ref` (`manifest.py`); `COMPONENT_PATHS`, `CLAUDE_PATH`, `DEFAULT_EXCLUDES`, `REPO_ROOT`, `_any_exists` (`constants.py`).
- Produces:
  - `def integrity_findings(destination: Path) -> list[Finding]` — Install-integrity category: config parses & `RavenConfig.exists` (else `error` `doctor.install.config`); manifest present (`warn` `doctor.install.manifest` if absent); each enabled component in `config.components` has at least one existing path from `COMPONENT_PATHS` (`warn` `doctor.install.component.<name>` per missing); `AGENTS.md` present (`error` `doctor.install.agents`); `CLAUDE.md` is a symlink to `AGENTS.md` (`warn` `doctor.install.symlink` if a regular file or wrong target; `ok` if correct).
  - `def drift_findings(destination: Path) -> list[Finding]` — Drift & freshness category: from `classify(...)`, `needs_merge` + `unknown_existing` → `warn` `doctor.drift.modified` (one finding listing the paths, or `ok` if none); `pending_merge_paths(...)` non-empty → `warn` `doctor.drift.pending`; manifest `ravenVersion` differs from `git_ref()` → `warn` `doctor.drift.version` (skip when manifest absent or `ravenVersion == "unknown"`).

**Notes:** When `config.exists` is `False`, `integrity_findings` returns a single `error` finding and the caller skips drift. Build `entries`/`classify` with `excludes = DEFAULT_EXCLUDES` and `template = REPO_ROOT / config.template`. Guard `config.template is None` by treating template-fit/classify as skipped with a `warn`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_doctor.py
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from helpers import RavenTestCase
from raven_lib.doctor import drift_findings, integrity_findings
from raven_lib.findings import Severity


class DoctorIntegrityTests(RavenTestCase):
    def _ids(self, findings):
        return {f.id: f for f in findings}

    def test_missing_config_is_single_error(self):
        findings = integrity_findings(self.destination)
        ids = self._ids(findings)
        self.assertIn("doctor.install.config", ids)
        self.assertEqual(ids["doctor.install.config"].severity, Severity.ERROR)

    def test_missing_agents_md_is_error_when_config_exists(self):
        (self.destination / ".raven").mkdir()
        (self.destination / ".raven" / "config.toml").write_text(
            'schema = 1\ntemplate = "python"\n', encoding="utf-8"
        )
        findings = integrity_findings(self.destination)
        ids = self._ids(findings)
        self.assertEqual(ids["doctor.install.config"].severity, Severity.OK)
        self.assertIn("doctor.install.agents", ids)
        self.assertEqual(ids["doctor.install.agents"].severity, Severity.ERROR)

    def test_correct_claude_symlink_is_ok(self):
        (self.destination / ".raven").mkdir()
        (self.destination / ".raven" / "config.toml").write_text(
            'schema = 1\ntemplate = "python"\n', encoding="utf-8"
        )
        (self.destination / "AGENTS.md").write_text("# A\n", encoding="utf-8")
        (self.destination / "CLAUDE.md").symlink_to("AGENTS.md")
        findings = integrity_findings(self.destination)
        ids = self._ids(findings)
        self.assertEqual(ids["doctor.install.symlink"].severity, Severity.OK)

    def test_claude_regular_file_is_warn(self):
        (self.destination / ".raven").mkdir()
        (self.destination / ".raven" / "config.toml").write_text(
            'schema = 1\ntemplate = "python"\n', encoding="utf-8"
        )
        (self.destination / "AGENTS.md").write_text("# A\n", encoding="utf-8")
        (self.destination / "CLAUDE.md").write_text("not a symlink\n", encoding="utf-8")
        findings = integrity_findings(self.destination)
        ids = self._ids(findings)
        self.assertEqual(ids["doctor.install.symlink"].severity, Severity.WARN)


class DoctorDriftTests(RavenTestCase):
    def test_clean_destination_reports_ok_modified(self):
        (self.destination / ".raven").mkdir()
        (self.destination / ".raven" / "config.toml").write_text(
            'schema = 1\ntemplate = "python"\n', encoding="utf-8"
        )
        findings = drift_findings(self.destination)
        ids = {f.id for f in findings}
        self.assertIn("doctor.drift.modified", ids)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=scripts python -m unittest tests.test_doctor -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'raven_lib.doctor'`.

- [ ] **Step 3: Write minimal implementation**

```python
# scripts/raven_lib/doctor.py
from __future__ import annotations

from pathlib import Path

from .apply import classify
from .blocks import pending_merge_paths
from .constants import (
    CLAUDE_PATH,
    COMPONENT_PATHS,
    DEFAULT_EXCLUDES,
    REPO_ROOT,
    _any_exists,
)
from .config import load_config
from .findings import Finding, Severity
from .manifest import git_ref, load_manifest

_INTEGRITY = "Install integrity"
_DRIFT = "Drift & freshness"


def integrity_findings(destination: Path) -> list[Finding]:
    config = load_config(destination)
    if not config.exists:
        return [
            Finding(
                id="doctor.install.config",
                severity=Severity.ERROR,
                category=_INTEGRITY,
                title="Raven config missing or unreadable",
                detail=f"No usable .raven/config.toml under {destination}.",
                fix="run `raven install <language>` to set up Raven",
            )
        ]

    findings: list[Finding] = [
        Finding(
            id="doctor.install.config",
            severity=Severity.OK,
            category=_INTEGRITY,
            title="Raven config present",
            detail=f"template = {config.template!r}",
        )
    ]

    manifest_path = destination / ".raven" / "manifest.json"
    if manifest_path.exists():
        findings.append(
            Finding(
                id="doctor.install.manifest",
                severity=Severity.OK,
                category=_INTEGRITY,
                title="Manifest present",
                detail=".raven/manifest.json found",
            )
        )
    else:
        findings.append(
            Finding(
                id="doctor.install.manifest",
                severity=Severity.WARN,
                category=_INTEGRITY,
                title="Manifest missing",
                detail=".raven/manifest.json not found; upgrade/accept state is unknown",
                fix="run `raven install` or `raven upgrade` to regenerate it",
            )
        )

    for name, enabled in config.components.items():
        if not enabled:
            continue
        paths = COMPONENT_PATHS.get(name, [])
        if paths and not any(_any_exists(destination / rel) for rel in paths):
            findings.append(
                Finding(
                    id=f"doctor.install.component.{name}",
                    severity=Severity.WARN,
                    category=_INTEGRITY,
                    title=f"Component '{name}' enabled but absent",
                    detail=f"None of {paths} exist though [components].{name} = true",
                    fix="run `raven upgrade` to restore missing component files",
                )
            )

    agents = destination / "AGENTS.md"
    if _any_exists(agents):
        findings.append(
            Finding(
                id="doctor.install.agents",
                severity=Severity.OK,
                category=_INTEGRITY,
                title="AGENTS.md present",
                detail="root instruction file found",
            )
        )
    else:
        findings.append(
            Finding(
                id="doctor.install.agents",
                severity=Severity.ERROR,
                category=_INTEGRITY,
                title="AGENTS.md missing",
                detail="the canonical root instruction file is absent",
                fix="run `raven install` to create AGENTS.md",
            )
        )

    findings.append(_symlink_finding(destination))
    return findings


def _symlink_finding(destination: Path) -> Finding:
    claude = destination / CLAUDE_PATH
    if not claude.exists() and not claude.is_symlink():
        return Finding(
            id="doctor.install.symlink",
            severity=Severity.OK,
            category=_INTEGRITY,
            title="CLAUDE.md absent",
            detail="no CLAUDE.md; AGENTS.md is used directly",
        )
    if claude.is_symlink():
        target = claude.readlink().as_posix()
        if target == "AGENTS.md":
            return Finding(
                id="doctor.install.symlink",
                severity=Severity.OK,
                category=_INTEGRITY,
                title="CLAUDE.md -> AGENTS.md",
                detail="symlink target is correct",
            )
        return Finding(
            id="doctor.install.symlink",
            severity=Severity.WARN,
            category=_INTEGRITY,
            title="CLAUDE.md points elsewhere",
            detail=f"symlink target is {target!r}, expected 'AGENTS.md'",
            fix="re-point CLAUDE.md at AGENTS.md (see `raven upgrade --adopt-claude-symlink`)",
        )
    return Finding(
        id="doctor.install.symlink",
        severity=Severity.WARN,
        category=_INTEGRITY,
        title="CLAUDE.md is a regular file",
        detail="CLAUDE.md should be a symlink to AGENTS.md",
        fix="run `raven upgrade --adopt-claude-symlink`",
    )


def drift_findings(destination: Path) -> list[Finding]:
    config = load_config(destination)
    findings: list[Finding] = []
    if config.template is None:
        return [
            Finding(
                id="doctor.drift.template",
                severity=Severity.WARN,
                category=_DRIFT,
                title="No template configured",
                detail="config has no template; drift cannot be evaluated",
                fix="set `template` in .raven/config.toml",
            )
        ]

    template = REPO_ROOT / config.template
    classification = classify(template, destination, set(DEFAULT_EXCLUDES), config)
    modified = sorted(set(classification.needs_merge) | set(classification.unknown_existing))
    if modified:
        findings.append(
            Finding(
                id="doctor.drift.modified",
                severity=Severity.WARN,
                category=_DRIFT,
                title=f"{len(modified)} Raven-owned file(s) locally modified",
                detail=", ".join(modified),
                fix="review and `raven upgrade` or `raven accept`",
            )
        )
    else:
        findings.append(
            Finding(
                id="doctor.drift.modified",
                severity=Severity.OK,
                category=_DRIFT,
                title="No Raven-owned drift detected",
                detail="installed Raven files match their templates",
            )
        )

    pending = pending_merge_paths(destination)
    if pending:
        findings.append(
            Finding(
                id="doctor.drift.pending",
                severity=Severity.WARN,
                category=_DRIFT,
                title=f"{len(pending)} pending guided merge(s)",
                detail=", ".join(pending),
                fix="resolve and run `raven accept`",
            )
        )

    manifest = load_manifest(destination)
    installed_version = manifest.get("ravenVersion")
    current = git_ref()
    if (
        isinstance(installed_version, str)
        and installed_version not in ("", "unknown")
        and current != "unknown"
        and installed_version != current
    ):
        findings.append(
            Finding(
                id="doctor.drift.version",
                severity=Severity.WARN,
                category=_DRIFT,
                title="Raven templates may be out of date",
                detail=f"installed {installed_version}, current {current}",
                fix="run `raven upgrade --dry-run` to preview updates",
            )
        )
    return findings
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=scripts python -m unittest tests.test_doctor -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add scripts/raven_lib/doctor.py tests/test_doctor.py
git commit -m "feat(doctor): add install-integrity and drift checks"
```

---

### Task 6: doctor — toolchain checks (tool-check subprocess reuse)

**Files:**
- Modify: `scripts/raven_lib/doctor.py` (add `toolchain_findings` and `build_doctor_findings`)
- Test: `tests/test_doctor.py` (add a class)

**Interfaces:**
- Consumes: `RunResult`, `Runner`, `run_command` (`runner.py`); `gate_spec_for` (`gates.py`).
- Produces:
  - `def toolchain_findings(destination: Path, runner: Runner = ...) -> list[Finding]` — Toolchain category. Runs `python <destination>/.claude/scripts/raven-tool-check.py --json` via `runner`; parses the JSON `results` array. Each result → `ok` if `available`, else `warn` (id `doctor.tool.<id>`); if `optionalWhen` is set, append it to `detail`. If the tool-check script is absent (`RunResult.found is False` or non-zero with no parseable JSON), emit one `warn` `doctor.tool.script` instead of crashing. Then, for the active template's `GateSpec.tools`, emit `doctor.gate-tool.<name>` (`ok`/`warn`) by checking `shutil.which`-style availability via `runner` `["<tool>", "--version"]` — but reuse the tool-check `results` where the id matches to avoid double-probing.
  - `def build_doctor_findings(destination: Path, runner: Runner = ...) -> list[Finding]` — concatenates `toolchain_findings` + `integrity_findings` + (drift only when config exists) in that category order.

**Notes:** Default `runner` argument is the module-level `_default_runner` wrapping `run_command` with a short timeout; tests pass a fake `runner` returning canned `RunResult`. Parse tool-check JSON defensively with `json.loads` inside `try/except json.JSONDecodeError`.

- [ ] **Step 1: Write the failing test**

```python
# add to tests/test_doctor.py
import json
from pathlib import Path

from raven_lib.runner import RunResult


def _fake_toolcheck_runner(results):
    payload = json.dumps({"os": "darwin", "results": results})

    def runner(command, cwd):
        if any("raven-tool-check.py" in part for part in command):
            return RunResult(ok=True, code=0, stdout=payload, stderr="", found=True, timed_out=False)
        # gate-tool --version probes: pretend present
        return RunResult(ok=True, code=0, stdout="1.0\n", stderr="", found=True, timed_out=False)

    return runner


class DoctorToolchainTests(RavenTestCase):
    def _config(self):
        (self.destination / ".raven").mkdir()
        (self.destination / ".raven" / "config.toml").write_text(
            'schema = 1\ntemplate = "python"\n', encoding="utf-8"
        )

    def test_available_tool_is_ok(self):
        from raven_lib.doctor import toolchain_findings
        from raven_lib.findings import Severity

        self._config()
        results = [{"id": "rg", "name": "ripgrep", "available": True, "purpose": "search", "optionalWhen": None}]
        findings = toolchain_findings(self.destination, _fake_toolcheck_runner(results))
        match = next(f for f in findings if f.id == "doctor.tool.rg")
        self.assertEqual(match.severity, Severity.OK)

    def test_missing_tool_is_warn_never_error(self):
        from raven_lib.doctor import toolchain_findings
        from raven_lib.findings import Severity

        self._config()
        results = [{"id": "fd", "name": "fd", "available": False, "purpose": "find", "optionalWhen": None}]
        findings = toolchain_findings(self.destination, _fake_toolcheck_runner(results))
        match = next(f for f in findings if f.id == "doctor.tool.fd")
        self.assertEqual(match.severity, Severity.WARN)
        self.assertFalse(any(f.severity == Severity.ERROR for f in findings))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=scripts python -m unittest tests.test_doctor.DoctorToolchainTests -v`
Expected: FAIL with `ImportError: cannot import name 'toolchain_findings'`.

- [ ] **Step 3: Write minimal implementation**

Add to `scripts/raven_lib/doctor.py`:

```python
import json

from .gates import gate_spec_for
from .runner import RunResult, Runner, run_command

_TOOLCHAIN = "Toolchain"


def _default_runner(command: list[str], cwd: Path) -> RunResult:
    return run_command(command, cwd, timeout=15)


def _tool_check_results(destination: Path, runner: Runner) -> list[dict] | None:
    script = destination / ".claude" / "scripts" / "raven-tool-check.py"
    if not script.exists():
        return None
    import sys as _sys

    result = runner([_sys.executable, str(script), "--json"], destination)
    if not result.found or result.timed_out:
        return None
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
    results = data.get("results")
    return results if isinstance(results, list) else None


def toolchain_findings(destination: Path, runner: Runner = _default_runner) -> list[Finding]:
    findings: list[Finding] = []
    results = _tool_check_results(destination, runner)
    if results is None:
        findings.append(
            Finding(
                id="doctor.tool.script",
                severity=Severity.WARN,
                category=_TOOLCHAIN,
                title="Tool-check script unavailable",
                detail="could not run .claude/scripts/raven-tool-check.py --json",
                fix="run `raven install` to restore Raven scripts, then re-run",
            )
        )
        return findings

    seen_ids: set[str] = set()
    for result in results:
        if not isinstance(result, dict):
            continue
        tool_id = str(result.get("id", "unknown"))
        seen_ids.add(tool_id)
        name = str(result.get("name", tool_id))
        available = bool(result.get("available"))
        optional_when = result.get("optionalWhen")
        if available:
            findings.append(
                Finding(
                    id=f"doctor.tool.{tool_id}",
                    severity=Severity.OK,
                    category=_TOOLCHAIN,
                    title=f"{name} present",
                    detail=str(result.get("purpose", "")),
                )
            )
        else:
            detail = f"{name} not installed or configured"
            if isinstance(optional_when, str) and optional_when:
                detail += f" (optional when {optional_when})"
            findings.append(
                Finding(
                    id=f"doctor.tool.{tool_id}",
                    severity=Severity.WARN,
                    category=_TOOLCHAIN,
                    title=f"{name} missing",
                    detail=detail,
                    fix="see `raven-tool-bootstrap` skill for install guidance",
                )
            )

    config = load_config(destination)
    spec = gate_spec_for(config.template) if config.template else None
    if spec is not None:
        for tool in spec.tools:
            if tool in seen_ids:
                continue
            probe = runner([tool, "--version"], destination)
            severity = Severity.OK if probe.found and probe.ok else Severity.WARN
            findings.append(
                Finding(
                    id=f"doctor.gate-tool.{tool}",
                    severity=severity,
                    category=_TOOLCHAIN,
                    title=f"{tool} {'present' if severity is Severity.OK else 'missing'}",
                    detail=f"gate tool for the {config.template} template",
                    fix=None if severity is Severity.OK else f"install {tool} to run the template's gates",
                )
            )
    return findings


def build_doctor_findings(destination: Path, runner: Runner = _default_runner) -> list[Finding]:
    findings = toolchain_findings(destination, runner)
    integrity = integrity_findings(destination)
    findings.extend(integrity)
    config = load_config(destination)
    if config.exists:
        findings.extend(drift_findings(destination))
    return findings
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=scripts python -m unittest tests.test_doctor -v`
Expected: PASS (all doctor tests).

- [ ] **Step 5: Commit**

```bash
git add scripts/raven_lib/doctor.py tests/test_doctor.py
git commit -m "feat(doctor): add toolchain checks via tool-check reuse"
```

---

### Task 7: assess — wiring & template-fit checks (static)

**Files:**
- Create: `scripts/raven_lib/assess.py`
- Test: `tests/test_assess.py`

**Interfaces:**
- Consumes: `Finding`, `Severity`; `load_config`; `gate_spec_for` (`gates.py`); `Runner`, `_default_runner` (import from `doctor.py` or `runner.py`).
- Produces:
  - `def wiring_findings(destination: Path) -> list[Finding]` — Quality-gate wiring category. Read `<destination>/justfile` text (`warn` `assess.wiring.justfile` if absent). For each recipe in `GateSpec.recipes`, check a line `^<recipe>:` exists (`ok`/`warn` `assess.wiring.recipe.<recipe>`). For each `config_signal` `(file, substring)`: file exists and (substring is None or substring in file text) → `ok`/`warn` `assess.wiring.config.<file>`. Pre-commit hook at `.git/hooks/pre-commit` containing `just check` → `ok`/`warn` `assess.wiring.hook`.
  - `def template_fit_findings(destination: Path) -> list[Finding]` — Template fit category. If any `GateSpec.detect_signals` file exists → `ok` `assess.fit.signal`; else `warn`. (Mismatch detection: if a *different* template's detect signal is the only one present, `warn` `assess.fit.mismatch`.)
  - `def build_assess_findings(destination: Path, run: bool, runner: Runner = _default_runner) -> list[Finding]` — concatenates wiring + (gate compliance from Task 8 when `run` else a single informational finding) + template-fit. For this task, when `run is False` emit one `ok` `assess.gates.skipped` finding titled "Gates not executed (use --run)".

**Notes:** Parse the justfile with simple line scanning (recipe headers are `name:` at column 0), consistent with how the repo's justfiles are written; do not add a just parser dependency.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_assess.py
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from helpers import RavenTestCase
from raven_lib.assess import build_assess_findings, template_fit_findings, wiring_findings
from raven_lib.findings import Severity


class AssessWiringTests(RavenTestCase):
    def _python_config(self):
        (self.destination / ".raven").mkdir()
        (self.destination / ".raven" / "config.toml").write_text(
            'schema = 1\ntemplate = "python"\n', encoding="utf-8"
        )

    def test_missing_justfile_warns(self):
        self._python_config()
        findings = wiring_findings(self.destination)
        match = next(f for f in findings if f.id == "assess.wiring.justfile")
        self.assertEqual(match.severity, Severity.WARN)

    def test_present_recipes_are_ok(self):
        self._python_config()
        (self.destination / "justfile").write_text(
            "lint:\n    ruff check .\nformat:\n    ruff format .\n"
            "typecheck:\n    pyright\ntest:\n    python -m pytest\n",
            encoding="utf-8",
        )
        findings = wiring_findings(self.destination)
        ids = {f.id: f for f in findings}
        self.assertEqual(ids["assess.wiring.recipe.lint"].severity, Severity.OK)
        self.assertEqual(ids["assess.wiring.recipe.test"].severity, Severity.OK)

    def test_ruff_config_signal_detected(self):
        self._python_config()
        (self.destination / "pyproject.toml").write_text("[tool.ruff]\nline-length = 100\n", encoding="utf-8")
        findings = wiring_findings(self.destination)
        match = next(f for f in findings if f.id == "assess.wiring.config.pyproject.toml")
        self.assertEqual(match.severity, Severity.OK)


class AssessFitTests(RavenTestCase):
    def test_matching_signal_is_ok(self):
        (self.destination / ".raven").mkdir()
        (self.destination / ".raven" / "config.toml").write_text(
            'schema = 1\ntemplate = "python"\n', encoding="utf-8"
        )
        (self.destination / "pyproject.toml").write_text("[tool.ruff]\n", encoding="utf-8")
        findings = template_fit_findings(self.destination)
        match = next(f for f in findings if f.id == "assess.fit.signal")
        self.assertEqual(match.severity, Severity.OK)


class AssessBuildTests(RavenTestCase):
    def test_without_run_gates_are_skipped(self):
        (self.destination / ".raven").mkdir()
        (self.destination / ".raven" / "config.toml").write_text(
            'schema = 1\ntemplate = "python"\n', encoding="utf-8"
        )
        findings = build_assess_findings(self.destination, run=False)
        self.assertIn("assess.gates.skipped", {f.id for f in findings})


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=scripts python -m unittest tests.test_assess -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'raven_lib.assess'`.

- [ ] **Step 3: Write minimal implementation**

```python
# scripts/raven_lib/assess.py
from __future__ import annotations

from pathlib import Path

from .config import load_config
from .doctor import _default_runner
from .findings import Finding, Severity
from .gates import gate_spec_for, load_gate_specs
from .runner import Runner

_WIRING = "Quality-gate wiring"
_FIT = "Template fit"
_GATES = "Gate compliance"


def _recipe_present(justfile_text: str, recipe: str) -> bool:
    return any(line.rstrip().startswith(f"{recipe}:") for line in justfile_text.splitlines())


def wiring_findings(destination: Path) -> list[Finding]:
    config = load_config(destination)
    spec = gate_spec_for(config.template) if config.template else None
    findings: list[Finding] = []
    if spec is None:
        return [
            Finding(
                id="assess.wiring.template",
                severity=Severity.WARN,
                category=_WIRING,
                title="No gate spec for template",
                detail=f"template {config.template!r} has no gate expectations",
                fix="set a supported `template` in .raven/config.toml",
            )
        ]

    justfile = destination / "justfile"
    if not justfile.is_file():
        findings.append(
            Finding(
                id="assess.wiring.justfile",
                severity=Severity.WARN,
                category=_WIRING,
                title="No justfile",
                detail="Raven's quality gates are defined in a justfile",
                fix="run `raven install` / `raven upgrade` to add the template justfile",
            )
        )
        text = ""
    else:
        text = justfile.read_text(encoding="utf-8")
        findings.append(
            Finding(
                id="assess.wiring.justfile",
                severity=Severity.OK,
                category=_WIRING,
                title="justfile present",
                detail="quality-gate recipes can be defined here",
            )
        )

    for recipe in spec.recipes:
        present = _recipe_present(text, recipe)
        findings.append(
            Finding(
                id=f"assess.wiring.recipe.{recipe}",
                severity=Severity.OK if present else Severity.WARN,
                category=_WIRING,
                title=f"gate recipe '{recipe}' {'defined' if present else 'missing'}",
                detail=f"justfile recipe `{recipe}`",
                fix=None if present else f"add a `{recipe}:` recipe to the justfile",
            )
        )

    for file, substring in spec.config_signals:
        target = destination / file
        ok = target.is_file() and (substring is None or substring in target.read_text(encoding="utf-8"))
        findings.append(
            Finding(
                id=f"assess.wiring.config.{file}",
                severity=Severity.OK if ok else Severity.WARN,
                category=_WIRING,
                title=f"tool config {file} {'present' if ok else 'missing'}",
                detail=f"expected {substring!r} in {file}" if substring else f"expected {file}",
                fix=None if ok else f"configure the gate tools in {file}",
            )
        )

    hook = destination / ".git" / "hooks" / "pre-commit"
    hook_ok = hook.is_file() and "just check" in hook.read_text(encoding="utf-8")
    findings.append(
        Finding(
            id="assess.wiring.hook",
            severity=Severity.OK if hook_ok else Severity.WARN,
            category=_WIRING,
            title=f"pre-commit gate hook {'installed' if hook_ok else 'not installed'}",
            detail=".git/hooks/pre-commit running `just check`",
            fix=None if hook_ok else "run `just install-hooks`",
        )
    )
    return findings


def template_fit_findings(destination: Path) -> list[Finding]:
    config = load_config(destination)
    spec = gate_spec_for(config.template) if config.template else None
    if spec is None:
        return []
    present = [s for s in spec.detect_signals if (destination / s).exists()]
    if present:
        return [
            Finding(
                id="assess.fit.signal",
                severity=Severity.OK,
                category=_FIT,
                title="Template matches project signals",
                detail=f"found {', '.join(present)} for template {config.template}",
            )
        ]

    findings = [
        Finding(
            id="assess.fit.signal",
            severity=Severity.WARN,
            category=_FIT,
            title="No language signal for configured template",
            detail=f"none of {list(spec.detect_signals)} found; cannot confirm template fit",
            fix="confirm `template` in .raven/config.toml matches this project",
        )
    ]
    for other_name, other_spec in load_gate_specs().items():
        if other_name == config.template:
            continue
        hit = [s for s in other_spec.detect_signals if (destination / s).exists()]
        if hit:
            findings.append(
                Finding(
                    id="assess.fit.mismatch",
                    severity=Severity.WARN,
                    category=_FIT,
                    title="Different language detected",
                    detail=f"found {', '.join(hit)} suggesting template {other_name}",
                    fix=f"consider `raven install {other_name}` if that is correct",
                )
            )
            break
    return findings


def build_assess_findings(destination: Path, run: bool, runner: Runner = _default_runner) -> list[Finding]:
    findings = wiring_findings(destination)
    if run:
        from .gate_run import gate_compliance_findings

        findings.extend(gate_compliance_findings(destination, runner))
    else:
        findings.append(
            Finding(
                id="assess.gates.skipped",
                severity=Severity.OK,
                category=_GATES,
                title="Gates not executed (use --run)",
                detail="static checks only; pass --run for a true pass/fail verdict",
            )
        )
    findings.extend(template_fit_findings(destination))
    return findings
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=scripts python -m unittest tests.test_assess -v`
Expected: PASS. (Note: `build_assess_findings` imports `gate_run` only when `run=True`, so Task 7 tests pass before Task 8 exists.)

- [ ] **Step 5: Commit**

```bash
git add scripts/raven_lib/assess.py tests/test_assess.py
git commit -m "feat(assess): add gate-wiring and template-fit checks"
```

---

### Task 8: assess --run — gate execution

**Files:**
- Create: `scripts/raven_lib/gate_run.py`
- Test: `tests/test_gate_run.py`

**Interfaces:**
- Consumes: `Finding`, `Severity`; `load_config`; `gate_spec_for`; `Runner`, `RunResult`, `run_command` (`runner.py`).
- Produces:
  - `def gate_compliance_findings(destination: Path, runner: Runner) -> list[Finding]` — Gate compliance category. Determine command per recipe: if `just` is available (probe `["just", "--version"]` via `runner`) and `<destination>/justfile` defines the recipe, command is `["just", recipe]`; else use `GateSpec.fallback_commands[recipe]`. When falling back because `just` is absent, prepend one `warn` `assess.gates.just` finding. For each recipe run `runner(command, destination)`: `ok` → `assess.gates.<recipe>` ok; non-zero → `error`; tool not found (`found is False`) → `warn` with install fix; timeout → `warn`.

**Notes:** Reuse `_recipe_present` logic by importing the small helper from `assess.py` or re-deriving; to avoid a circular import (`assess` imports `gate_run` lazily; `gate_run` must NOT import `assess` at module top level), inline a local `_recipe_present` copy in `gate_run.py`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_gate_run.py
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from helpers import RavenTestCase
from raven_lib.findings import Severity
from raven_lib.gate_run import gate_compliance_findings
from raven_lib.runner import RunResult


def _runner(outcomes):
    """outcomes: dict mapping the joined command string -> RunResult."""

    def runner(command, cwd):
        key = " ".join(command)
        for needle, result in outcomes.items():
            if needle in key:
                return result
        return RunResult(ok=True, code=0, stdout="", stderr="", found=True, timed_out=False)

    return runner


class GateRunTests(RavenTestCase):
    def _python_config_with_justfile(self):
        (self.destination / ".raven").mkdir()
        (self.destination / ".raven" / "config.toml").write_text(
            'schema = 1\ntemplate = "python"\n', encoding="utf-8"
        )
        (self.destination / "justfile").write_text(
            "lint:\n    ruff check .\nformat:\n    ruff format .\n"
            "typecheck:\n    pyright\ntest:\n    python -m pytest\n",
            encoding="utf-8",
        )

    def test_passing_gate_is_ok(self):
        self._python_config_with_justfile()
        runner = _runner({"just --version": RunResult(True, 0, "", "", True, False)})
        findings = gate_compliance_findings(self.destination, runner)
        lint = next(f for f in findings if f.id == "assess.gates.lint")
        self.assertEqual(lint.severity, Severity.OK)

    def test_failing_gate_is_error(self):
        self._python_config_with_justfile()
        runner = _runner({
            "just --version": RunResult(True, 0, "", "", True, False),
            "just lint": RunResult(False, 1, "", "E501", True, False),
        })
        findings = gate_compliance_findings(self.destination, runner)
        lint = next(f for f in findings if f.id == "assess.gates.lint")
        self.assertEqual(lint.severity, Severity.ERROR)

    def test_missing_just_falls_back_and_warns(self):
        self._python_config_with_justfile()
        runner = _runner({"just --version": RunResult(False, 127, "", "", False, False)})
        findings = gate_compliance_findings(self.destination, runner)
        self.assertIn("assess.gates.just", {f.id for f in findings})


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=scripts python -m unittest tests.test_gate_run -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'raven_lib.gate_run'`.

- [ ] **Step 3: Write minimal implementation**

```python
# scripts/raven_lib/gate_run.py
from __future__ import annotations

from pathlib import Path

from .config import load_config
from .findings import Finding, Severity
from .gates import gate_spec_for
from .runner import Runner

_GATES = "Gate compliance"


def _recipe_present(justfile_text: str, recipe: str) -> bool:
    return any(line.rstrip().startswith(f"{recipe}:") for line in justfile_text.splitlines())


def gate_compliance_findings(destination: Path, runner: Runner) -> list[Finding]:
    config = load_config(destination)
    spec = gate_spec_for(config.template) if config.template else None
    if spec is None:
        return []

    just_available = runner(["just", "--version"], destination).found
    justfile = destination / "justfile"
    justfile_text = justfile.read_text(encoding="utf-8") if justfile.is_file() else ""

    findings: list[Finding] = []
    used_fallback = False
    for recipe in spec.recipes:
        use_just = just_available and _recipe_present(justfile_text, recipe)
        if use_just:
            command = ["just", recipe]
        else:
            fallback = spec.fallback_commands.get(recipe)
            if fallback is None:
                continue
            command = list(fallback)
            if not just_available:
                used_fallback = True
        result = runner(command, destination)
        findings.append(_recipe_finding(recipe, command, result))

    if used_fallback:
        findings.insert(
            0,
            Finding(
                id="assess.gates.just",
                severity=Severity.WARN,
                category=_GATES,
                title="just not available; used fallback commands",
                detail="install just to run Raven's canonical gate recipes",
                fix="install just (https://just.systems)",
            ),
        )
    return findings


def _recipe_finding(recipe: str, command: list[str], result) -> Finding:
    label = " ".join(command)
    if not result.found:
        return Finding(
            id=f"assess.gates.{recipe}",
            severity=Severity.WARN,
            category=_GATES,
            title=f"gate '{recipe}' could not run",
            detail=f"command not found: {label}",
            fix=f"install the tool for `{label}`",
        )
    if result.timed_out:
        return Finding(
            id=f"assess.gates.{recipe}",
            severity=Severity.WARN,
            category=_GATES,
            title=f"gate '{recipe}' timed out",
            detail=f"`{label}` did not finish in time",
            fix="run the gate manually to investigate",
        )
    if result.ok:
        return Finding(
            id=f"assess.gates.{recipe}",
            severity=Severity.OK,
            category=_GATES,
            title=f"gate '{recipe}' passed",
            detail=f"`{label}` exited 0",
        )
    return Finding(
        id=f"assess.gates.{recipe}",
        severity=Severity.ERROR,
        category=_GATES,
        title=f"gate '{recipe}' failed",
        detail=f"`{label}` exited {result.code}",
        fix=f"fix the reported issues, then re-run `{label}`",
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=scripts python -m unittest tests.test_gate_run tests.test_assess -v`
Expected: PASS (gate_run tests + assess tests still green).

- [ ] **Step 5: Commit**

```bash
git add scripts/raven_lib/gate_run.py tests/test_gate_run.py
git commit -m "feat(assess): execute gates under --run with just/fallback"
```

---

### Task 9: Wire `doctor` and `assess` into the CLI

**Files:**
- Modify: `scripts/raven_lib/cli.py` (add `cmd_doctor`, `cmd_assess`, two subparsers, dispatch)
- Modify: `scripts/raven_lib/__init__.py` (export new public functions in `__all__`)
- Test: `tests/test_cli.py` (extend)

**Interfaces:**
- Consumes: `build_doctor_findings` (`doctor.py`); `build_assess_findings` (`assess.py`); `render_human`, `render_json` (`report.py`); `exit_code` (`findings.py`); `os_key`-equivalent — use `platform.system().lower()` mapped like the tool-check `os_key`, or import a small `os_key` helper. For simplicity define a local `_os_name()` in `cli.py` returning `platform.system().lower()`.
- Produces:
  - `def cmd_doctor(args: argparse.Namespace) -> int` — resolve destination (`_resolve_destination`); build findings; print `render_json` if `args.json` else `render_human`; return `exit_code(findings)`.
  - `def cmd_assess(args: argparse.Namespace) -> int` — same shape, passes `run=args.run`.

**Notes:** `cmd_doctor`/`cmd_assess` must not require an installed `.raven/` to avoid crashing — `build_doctor_findings` already returns an `error` finding for missing config and `build_assess_findings` should be guarded: if `load_config(destination).exists is False`, return a single `error` finding `assess.config.missing` rather than running wiring checks. Add that guard to `build_assess_findings` in Task 7's function (update inline here if not already present).

- [ ] **Step 1: Write the failing test**

```python
# add to tests/test_cli.py
import json as _json


class DoctorAssessCliTests(RavenTestCase):
    def _run(self, *cli_args):
        return subprocess.run(
            [sys.executable, str(RAVEN_PATH), "-d", str(self.destination), *cli_args],
            capture_output=True,
            text=True,
            check=False,
        )

    def test_doctor_help_lists_command(self):
        result = subprocess.run(
            [sys.executable, str(RAVEN_PATH), "--help"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertIn("doctor", result.stdout)
        self.assertIn("assess", result.stdout)

    def test_doctor_on_empty_dir_errors(self):
        result = self._run("doctor", "--json")
        self.assertEqual(result.returncode, 1)
        data = _json.loads(result.stdout)
        self.assertEqual(data["command"], "doctor")
        self.assertTrue(any(f["severity"] == "error" for f in data["findings"]))

    def test_assess_json_on_installed_repo_exits_zero(self):
        (self.destination / ".raven").mkdir()
        (self.destination / ".raven" / "config.toml").write_text(
            'schema = 1\ntemplate = "python"\n', encoding="utf-8"
        )
        (self.destination / "AGENTS.md").write_text("# A\n", encoding="utf-8")
        (self.destination / "justfile").write_text(
            "lint:\n    ruff check .\nformat:\n    ruff format .\n"
            "typecheck:\n    pyright\ntest:\n    python -m pytest\n",
            encoding="utf-8",
        )
        result = self._run("assess", "--json")
        # Static-only assess emits no error findings -> exit 0.
        self.assertEqual(result.returncode, 0)
        data = _json.loads(result.stdout)
        self.assertEqual(data["command"], "assess")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=scripts python -m unittest tests.test_cli.DoctorAssessCliTests -v`
Expected: FAIL — `raven --help` lacks `doctor`/`assess`; invalid choice error for the subcommand.

- [ ] **Step 3: Write minimal implementation**

In `scripts/raven_lib/cli.py`, add imports near the top (with the other `from .` imports):

```python
import platform

from .assess import build_assess_findings
from .doctor import build_doctor_findings
from .findings import exit_code
from .report import render_human, render_json
```

Add command functions (near `cmd_accept`):

```python
def _os_name() -> str:
    name = platform.system().lower()
    if name == "darwin":
        return "darwin"
    if name == "windows":
        return "windows"
    return "linux"


def cmd_doctor(args: argparse.Namespace) -> int:
    destination = _resolve_destination(args)
    if destination is None:
        return 2
    findings = build_doctor_findings(destination)
    output = (
        render_json("doctor", _os_name(), findings)
        if args.json
        else render_human("doctor", _os_name(), findings)
    )
    print(output)
    return exit_code(findings)


def cmd_assess(args: argparse.Namespace) -> int:
    destination = _resolve_destination(args)
    if destination is None:
        return 2
    findings = build_assess_findings(destination, run=args.run)
    output = (
        render_json("assess", _os_name(), findings)
        if args.json
        else render_human("assess", _os_name(), findings)
    )
    print(output)
    return exit_code(findings)
```

Register subparsers (after the `accept_parser` block, before `args = parser.parse_args()`):

```python
    doctor_parser = subparsers.add_parser(
        "doctor",
        usage="raven doctor [OPTIONS]",
        help="diagnose Raven's install and the local toolchain",
        description=(
            "Read-only diagnostics for Raven's own installation and the local tooling.\n"
            "Exits non-zero only when the Raven install itself is broken."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    doctor_parser.add_argument("--json", action="store_true", help="print machine-readable JSON")

    assess_parser = subparsers.add_parser(
        "assess",
        usage="raven assess [OPTIONS]",
        help="grade the project against the active template's standards",
        description=(
            "Read-only scorecard of how well this project conforms to Raven's gate and\n"
            "convention expectations. Static by default; --run executes the gates."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    assess_parser.add_argument(
        "--run", action="store_true", help="execute the quality gates for a true pass/fail verdict"
    )
    assess_parser.add_argument("--json", action="store_true", help="print machine-readable JSON")
```

Extend dispatch (after the `accept` branch):

```python
    if args.command == "doctor":
        return cmd_doctor(args)
    if args.command == "assess":
        return cmd_assess(args)
```

Guard `build_assess_findings` for a missing install (in `assess.py`, at the top of the function):

```python
    config = load_config(destination)
    if not config.exists:
        return [
            Finding(
                id="assess.config.missing",
                severity=Severity.ERROR,
                category="Quality-gate wiring",
                title="Raven not installed here",
                detail="no .raven/config.toml; cannot assess against a template",
                fix="run `raven install <language>` first",
            )
        ]
```

Add the new public names to `scripts/raven_lib/__init__.py` imports and `__all__` (`build_doctor_findings`, `build_assess_findings`, `Finding`, `Severity`, `exit_code`, `render_human`, `render_json`). Inspect the existing `__all__` block and `test_package_api.py` so the drift guard stays green.

- [ ] **Step 4: Run tests**

Run: `PYTHONPATH=scripts python -m unittest tests.test_cli tests.test_package_api -v`
Expected: PASS, including the new CLI tests.

- [ ] **Step 5: Commit**

```bash
git add scripts/raven_lib/cli.py scripts/raven_lib/__init__.py tests/test_cli.py
git commit -m "feat(cli): wire raven doctor and raven assess subcommands"
```

---

### Task 10: Full suite, self-check, and docs

**Files:**
- Modify: `README.md` (document `doctor` and `assess` under the command list)
- Modify: `scripts/raven_lib/cli.py` (add the two commands to the `epilog` "Common commands" block)
- Test: full suite via self-check

**Interfaces:** none new.

- [ ] **Step 1: Run the entire unit suite**

Run: `PYTHONPATH=scripts python -m unittest discover -s tests -v`
Expected: PASS — all prior tests plus the new `test_findings`, `test_report`, `test_gates`, `test_runner`, `test_doctor`, `test_assess`, `test_gate_run`, and extended `test_cli`.

- [ ] **Step 2: Update README and CLI epilog**

In `README.md`, add `doctor` and `assess` to the command reference with one-line descriptions and the `assess --run` / `--json` flags. In `cli.py` `main()` epilog, add:

```
  raven doctor
  raven assess
  raven assess --run
```

- [ ] **Step 3: Run the quality gates on touched code**

Run: `ruff format scripts/raven_lib tests && ruff check scripts/raven_lib tests && pyright scripts/raven_lib`
Expected: clean (fix any issues in touched files; no `# type: ignore`/`# noqa` without a scoped reason).

- [ ] **Step 4: Run the self-check workflow**

Run: `python scripts/self-check.py`
Expected: PASS — installed shape valid, `upgrade --dry-run` clean, unit tests green. Investigate any unexpected self-upgrade output per `CLAUDE.md`.

- [ ] **Step 5: Commit**

```bash
git add README.md scripts/raven_lib/cli.py
git commit -m "docs(cli): document raven doctor and raven assess"
```

---

## Self-Review Notes

- **Spec coverage:** Finding model + severity→exit (Task 1) ✓; rendering human/JSON (Task 2) ✓; gate table (Task 3) ✓; injectable runner / no real tools in tests (Task 4) ✓; doctor install-integrity + drift + freshness (Task 5) ✓; doctor toolchain via tool-check subprocess reuse (Task 6) ✓; assess wiring + template-fit (Task 7) ✓; assess `--run` gate execution with just/fallback (Task 8) ✓; CLI wiring + severity exit + `--json` (Task 9) ✓; docs + self-check (Task 10) ✓. Out-of-scope items (no auto-fix, no installs, no new deps) are enforced by the Global Constraints and the read-only check implementations.
- **Type consistency:** `Finding`/`Severity`/`exit_code`/`summarize` (Task 1) are consumed unchanged in Tasks 2, 5–9. `RunResult`/`Runner`/`run_command` (Task 4) are consumed unchanged in Tasks 6, 8. `GateSpec`/`gate_spec_for`/`load_gate_specs` (Task 3) are consumed unchanged in Tasks 6–8. `build_doctor_findings`/`build_assess_findings` signatures defined in Tasks 6/7 match the calls in Task 9.
- **Circular imports:** `assess.py` imports `gate_run` lazily inside `build_assess_findings`; `gate_run.py` never imports `assess` (it inlines `_recipe_present`). `assess.py` importing `_default_runner` from `doctor.py` is one-directional (doctor does not import assess).
- **Known follow-up to resolve during Task 3:** fill `gates.toml` entries for `go`, `rust`, `typescript`, `swift`, `elixir`, `lua` by reading each `<lang>/justfile`; only `python` is verified in this plan.
