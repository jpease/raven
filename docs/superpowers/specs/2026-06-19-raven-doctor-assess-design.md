# Design: `raven doctor` & `raven assess`

Date: 2026-06-19
Status: Approved design, pending implementation plan

## Summary

Add two new read-only Raven CLI subcommands that report how well a destination
repository and its local environment conform to Raven's expectations:

- `raven doctor` answers **"Is the setup correct?"** — it diagnoses Raven's own
  installation and the local machine/toolchain.
- `raven assess` answers **"How well does this project meet Raven's standards?"**
  — it grades the project's own code and configuration against the practices the
  active language template encodes.

Both commands are advisory by default, severity-scored, support `--json`, and
exit non-zero only when an `error`-severity finding is present.

## Motivation

Raven installs guardrails (quality gates, structural conventions, recommended
tooling) but provides no single command to answer "is this repo actually set up
the way Raven intends, and does its code meet the bar?" Today that knowledge is
scattered across `upgrade --dry-run`, `raven-tool-check.py`, and manual
inspection. These two commands consolidate it into deterministic, agent- and
CI-readable reports.

## Command Split (organizing principle)

| | `raven doctor` | `raven assess` |
|---|---|---|
| Question | "Is the setup correct?" | "How well does this project meet Raven's standards?" |
| Subject | Raven's install + the local machine/toolchain | The project's own code & config |
| Fix lives in | environment / `raven upgrade` / restore a file | your code/config |
| Failing means | "Raven can't do its job here / environment incomplete" | "your codebase has room to improve against the standard" |

Memorable line: **doctor checks Raven and the machine; assess grades your repo
and your code.**

## Shared Infrastructure

New modules under `scripts/raven_lib/`:

- `assess.py` — the assessment engine: defines the finding model and the check
  functions, and assembles the ordered list of findings for each command.
- `report.py` — rendering: human-readable grouped output and `--json` output.

### Finding model

A `Finding` dataclass:

- `id: str` — stable identifier (e.g. `"doctor.config.schema"`), used in JSON
  and tests.
- `severity: Severity` — enum `error` | `warn` | `ok`.
- `category: str` — grouping label for human output (e.g. `"Install integrity"`).
- `title: str` — one-line summary of what was checked.
- `detail: str` — what was actually found.
- `fix: str | None` — concrete next step when `severity != ok`; omitted for `ok`.

A command run produces a `list[Finding]` in a stable, category-grouped order.

### Severity to exit code

- Any `error` finding present → process exit `1`.
- Otherwise → exit `0` (including when only `warn` findings exist).

This makes `--run` a real CI gate while keeping the static/default mode advisory.

### Rendering

`report.py` renders the same `list[Finding]` two ways:

- **Human (default):** findings grouped by `category`, one line each, marked
  `✓` (ok) / `!` (warn) / `✗` (error). For non-ok findings the `detail` and
  `fix` are shown. A trailing summary line reports counts:
  `N errors, M warnings, K ok`.
- **`--json`:** `{ "command": str, "os": str, "findings": [ ... ],
  "summary": { "errors": int, "warnings": int, "ok": int } }` where each finding
  serializes its full dataclass.

### Reuse of existing code

- **Tool probing** (`doctor` toolchain checks) calls the existing tool-check
  engine in `.claude/scripts/raven-tool-check.py` rather than reimplementing CLI
  and MCP probing. The engine functions (`check_all_tools`, the `TOOLS` table)
  are imported/invoked; `assess.py` adapts their results into `Finding`s.
- **Config & manifest reading** reuses `config.py` and `manifest.py`.
- **Drift detection** reuses the same template-vs-installed comparison the
  `upgrade` path already computes (in `plan.py` / `apply.py`), surfaced as
  findings rather than as an upgrade plan.

## `raven doctor` Checks

Category: **Toolchain**

- Recommended Raven tools present (wraps the tool-check engine). A missing
  required tool → `error`; a missing tool that has `optionalWhen` → `warn`.
- The active template's gate tools present (e.g. `ruff`, `pyright` for python),
  drawn from the per-language gate table (see below). Missing → `error` (the
  gates cannot run without them).

Category: **Install integrity**

- `.raven/config.toml` parses and `schema` matches the current supported value
  (`error` if missing/unparseable/wrong schema).
- `.raven/manifest.json` present and parseable (`error` if absent on an
  otherwise-installed repo).
- Each component enabled in `config.toml [components]` actually exists on disk
  (`warn` per missing component, with `fix` = re-run install/upgrade).
- `AGENTS.md` present (`error` if absent).
- `CLAUDE.md` is a symlink to `AGENTS.md` (`warn` if it is a regular file or
  points elsewhere; `ok` if correct or intentionally absent per config).

Category: **Drift & freshness**

- Raven-owned files locally modified vs their template source (`warn` per file,
  `fix` = review and `raven upgrade` or `raven accept`).
- Pending guided merges under `.raven/merge/` (`warn`, `fix` = resolve and
  `raven accept`).
- Installed `ravenVersion` in the manifest is behind the template version →
  upgrade available (`warn`, `fix` = `raven upgrade --dry-run`).

## `raven assess` Checks

Category: **Quality-gate wiring**

- The template's expected gate recipes (lint/format/typecheck/test) are defined
  in the repo `justfile` (`warn` per missing recipe).
- The expected gate tool configs exist (e.g. `[tool.ruff]` in `pyproject.toml`,
  a pyright config) (`warn` if absent).
- The pre-commit hook running the gate set is installed (`warn` if not, `fix` =
  `just install-hooks`).

Category: **Gate compliance** *(only populated with `--run`)*

- Execute each expected gate and report pass/fail with any available counts.
  A failing gate → `error`. Without `--run`, this category is replaced by a
  single `ok`/`warn` informational finding stating gates were not executed.

Category: **Template fit**

- Detected language signal files (e.g. `pyproject.toml`, `go.mod`, `mix.exs`,
  `Cargo.toml`) match the configured `template`. Mismatch → `warn` (suggests the
  wrong template is applied); no signal found → `warn` (cannot confirm fit).

## Per-language Gate Knowledge (declarative)

Add a declarative table mapping each template to its gate expectations. Preferred
location: `scripts/raven_lib/data/gates.toml` (sibling to the existing
`data/config.toml.tmpl`), loaded by `assess.py`. Each template entry provides:

- `recipes` — expected `justfile` recipe names (e.g. `lint`, `format`,
  `typecheck`, `test`).
- `tools` — gate tool ids required to run those recipes (cross-referenced with
  the tool-check engine where overlapping, e.g. `ruff`, `pyright`).
- `config_signals` — files/sections expected to configure those tools (e.g.
  `pyproject.toml` containing `[tool.ruff]`).
- `detect_signals` — language-detection files used for template-fit checks.
- `fallback_commands` — per-recipe command to run when `just` is unavailable.

This keeps `assess` testable and makes adding a language a data-only change,
consistent with how Raven templates already work. The table is the single source
of truth for both the wiring checks and the `--run` execution model.

## `--run` Execution Model

- `assess --run` prefers `just <recipe>` when `just` is installed and the
  `justfile` defines that recipe (the justfile is Raven's canonical gate
  encoding).
- If `just` is absent, emit a `warn` finding and fall back to the table's
  `fallback_commands` for each gate.
- Never auto-installs tools or dependencies. If a gate tool is missing, the gate
  is reported as `error` with a `fix` pointing at install guidance rather than
  attempting to install it.
- Subprocess execution is isolated behind an injectable runner so unit tests
  never invoke real ruff/pytest.

## CLI Integration

Two new subparsers in `cli.py`, alongside `init`/`install`/`upgrade`/`accept`:

- `raven doctor [--json]`
- `raven assess [--run] [--json]`

Both honor the existing `-d/--destination` global option. Dispatch via new
`cmd_doctor` / `cmd_assess` functions that build findings through `assess.py`,
render through `report.py`, and return the severity-derived exit code.

## Error Handling

- Missing `.raven/` install: `doctor` reports it as an `error` with a `fix` to
  run `raven install`; `assess` reports it as a single `error` and exits.
- Unreadable/malformed config or manifest: surfaced as an `error` finding, not an
  uncaught exception.
- `--run` gate subprocess failures (non-zero exit) are expected signal, captured
  as findings; runner/OS errors (command not found, timeout) are captured and
  reported as `warn`/`error` rather than crashing.

## Testing

- Unit tests per check against fixture repos: a healthy install, a drifted
  install, a wrong-template repo, and a missing-tool environment.
- The engine is pure and dependency-injected: tool probing and the `--run`
  subprocess runner are stubbed, so no real ruff/pytest/just is invoked in unit
  tests.
- `report.py` rendering and severity→exit-code mapping are tested directly off
  synthetic `Finding` lists.
- Tests follow existing `tests/` naming and fixture patterns and run under the
  `python scripts/self-check.py` workflow.

## Out of Scope (YAGNI)

- No auto-fix / remediation; both commands are strictly read-only.
- No installation of tools or dependencies.
- No new third-party dependencies; standard library plus existing Raven modules
  only.
- No per-finding suppression/config beyond what `config.toml [exclude]` and the
  tool-check `--no-reminder` preference already provide.
