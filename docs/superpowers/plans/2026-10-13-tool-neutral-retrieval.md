# Plan: tool-neutral, opt-in code-intelligence retrieval

Status: executed and dogfooded in this repository. Verification: `scripts/self-check.py` passes, and
the new upgrade prompt ran against a copy of this repository's pre-change state (keep, remove,
and Enter-for-default) before the final self-upgrade used `--drop-mcp gitnexus`.

## Goal

Stop Raven's shipped guidance from treating one named code-graph tool (GitNexus) as the
default and as mandatory. After this change the retrieval ladder is `rg` and LSP first. A
code-intelligence index is an optional aid with no mandated step, and Raven names CodeGraph as
the recommended optional exploration aid while keeping GitNexus as a documented alternative.

## Why (evidence, summarised)

Head-to-head runs on private downstream repos (Rust, TS+Go, Swift, Python, Elixir). Repos are
named by role only, per the public-repo hygiene rule in `AGENTS.md`.

- **Headless agent tasks.** 72 runs on Sonnet: 4 repos, 2 task types, 3 arms
  (grep-only baseline, CodeGraph over MCP, code-review-graph over MCP), 3 repetitions.
  - Caller-listing (impact) recall was equal across arms (0.92 to 0.93). The baseline was
    cheapest per run ($0.13, against $0.19 for CodeGraph and $0.23 for code-review-graph).
  - Exploration recall was 1.00 in every arm. CodeGraph cost $0.16 against $0.27 for the
    baseline, with fewer than half the turns. code-review-graph matched the baseline cost.
- **Static caller recall.** Depth-1 recall depends on language and repo layout. A Go module
  nested below the repo root made CodeGraph find almost nothing. A pnpm workspace whose
  packages declare `main`/`exports` as build output loses subpath imports (CodeGraph
  issue #2502). GitNexus missed callers in Rust, TS, and Swift and led only on part of Go.
- **Third-party evidence.** An outside benchmark and GitNexus issue #3500 both report no
  accuracy gain from code-graph MCP servers over plain grep, and usually higher cost.
- **Unreliable change-detection.** Every graph tool's diff-to-impact output was coarse or
  inconsistent in these runs (GitNexus risk contradicted its own `impact`, CodeGraph `affected`
  over-approximated, others reported 10 changed symbols for a one-line edit).

Not measured: answer quality beyond file recall, conceptual-search ranking under embeddings
at scale, any model other than Sonnet, or CRG/CodeGraph roster integration.

## Scope

1. `common/AGENTS.md` (managed block source): tool-neutral retrieval table rows, and the
   "run impact / change-detection" mandate becomes optional wording.
2. Seven skills under `common/.agents/skills/` (mirrored to `.claude/skills/`): replace
   `mcp__gitnexus__*` mandates with tool-neutral wording.
   Affected: `raven-codebase-discovery`, `raven-implement-feature`, `raven-debug-failure`,
   `raven-safe-refactor`, `raven-debloat`, `raven-review-pr`, `raven-write-tests`.
3. Agents `raven-codebase-cartographer` and `raven-refactor-reviewer` in all three client
   trees (`common/.claude/agents/*.md`, `common/.codex/agents/*.toml`,
   `common/.gemini/agents/*.md`).
4. Optional MCP servers: `gitnexus` moves from `common/.raven/mcp.json` to a new opt-in
   catalog selected by `[mcp] optional` in `.raven/config.toml`; `raven upgrade` asks existing
   users to keep or remove it; `raven doctor` flags an index with no server. The two
   `mcp__gitnexus__*` pre-allows leave `common/.claude/settings.json`.
5. `common/.claude/scripts/raven-tool-check.py` (and its `.codex`/`.gemini` copies): add a
   CodeGraph entry; keep the GitNexus entry.
6. Docs: `common/.claude/docs/raven-tool-assessment.md`, `docs/tooling.md`, `README.md`,
   `generic/README.md`, `docs/upgrading.md`.
7. Tests that assert the old shipped defaults.

## Non-Goals

- Raven's own repo is not a holdout: see work item 8. Its vendor-generated GitNexus block is
  removed, not kept.
- No roster change: `raven-capability-roster.py` keeps reading `.gitnexus/meta.json` and
  emits no CodeGraph line (see Follow-Ups).
- No removal of GitNexus support: roster staleness line, tool-check entry, and the
  `mcp__gitnexus__rename` disallow in read-only agents all stay.
- No new dependency: CodeGraph is documented and probed, never installed by Raven.

## Assumptions

- Language template `.raven/mcp.json` files do not name `gitnexus` (verified: 0 matches), so
  only `common/.raven/mcp.json` changes, plus the new catalog file. `load_mcp_servers` merges
  common and language servers.
- Raven owns `.mcp.json`, `.codex/config.toml`, and `.claude/settings.json` wholesale. Verified
  on scratch installs: an upgrade rewrites them in place when unmodified, so a pristine repo
  LOSES its `gitnexus` MCP entry; a repo whose `.mcp.json` was edited gets a guided merge
  (`.raven/merge/`) and keeps its entry. See Upgrade Impact.
- `codegraph --version` exits 0 when installed (a CLI-version test exists upstream).
  Work item 5 verifies the command before it ships.

## Alternatives

| Approach | Rejected because | Reopen if |
|---|---|---|
| Replace GitNexus with CodeGraph as the default MCP server | Impact tasks cost 48% more with no recall gain; CodeGraph's `upgrade` can wipe `AGENTS.md` outside its markers (issue #2506), which collides with Raven's managed block; telemetry is on by default. | #2506 is fixed and a downstream A/B shows an accuracy gain, not only a cost gain. |
| Ship both servers | Doubles MCP tool-list overhead for no demonstrated gain. | An A/B shows complementary wins on one task type. |
| Smallest change: edit only `common/AGENTS.md` | Leaves 7 skills and 6 agents telling the agent to call `mcp__gitnexus__*`, which contradicts the new top-level rule. | Never; the contradiction is the bug. |
| Remove GitNexus support entirely | Breaks downstream repos that rely on the roster STALE line. | No downstream repo uses it after a deprecation window. |
| Drop the shipped server silently, document it in `upgrading.md` | A pristine repo loses a working server with no signal; verified on scratch installs. | Never. |
| Keep shipping the server for one more release with a deprecation note | Delays the demotion and still ends in the same silent removal one release later. | Downstream reports a breakage the prompt does not cover. |
| Conditional render: keep the entry whenever `.gitnexus/` exists | Makes a managed file's content depend on repo state; Raven's render is deterministic today. | A consent prompt proves too intrusive. |

## Work Items

### 1. Managed block source: `common/AGENTS.md`

- **End state:** the retrieval table has no `mcp__gitnexus__*` rows; the "conceptual flow
  discovery" row reads "optional code-intelligence index, else `rg` and LSP", and the impact
  row reads "LSP references, else `rg`". The line starting "When the session roster lists a
  code-intelligence index, run its impact analysis..." becomes: an index, when listed, is an
  optional aid; its result is discovery, not proof; say so if the index is stale. No MUST.
- **Verification:** `uv run --group dev python -m pytest tests/test_managed_blocks.py -q` exits 0,
  then `rg -n 'mcp__gitnexus__' common/AGENTS.md` returns nothing. `tests/test_template.py` is
  run at work item 4a, where its default-server assertions change.
- **Invariants:** the `RAVEN:BEGIN/END` markers and every other table row are unchanged; no
  language `AGENTS.md` fragment is edited.

### 2. Skills (seven files, edited in `common/.agents/skills/`)

- **End state:** none of the seven files instructs the agent to *use* a GitNexus tool. Each
  retrieval step reads "a configured code-intelligence index, if any" or names `rg` and LSP.
  `raven-codebase-discovery` keeps one bullet that spells the GitNexus and CodeGraph tool
  names and CLI fallbacks, so spelling guidance exists in exactly one place. The
  `raven-safe-refactor` duplicate-marker guard stays, reworded to apply to any call graph.
  `raven-debug-failure` step 6 drops `trace` and keeps `rg` ownership search first.
- **Verification:** `uv run --group dev python -m pytest tests/test_skills.py -q` exits 0 after
  the `test_dead_code_claims_require_semantic_evidence_rather_than_grep` assertion is moved
  from the literal `gitnexus` to a tool-neutral term (`index`); then
  `rg -c 'mcp__gitnexus__' common/.agents/skills/` shows `raven-codebase-discovery` only.
- **Invariants:** no skill changes its trigger line, frontmatter, or required sections; no
  other test in `tests/test_skills.py` changes its assertion.

### 3. Agents (six files across three clients)

- **End state:** `raven-codebase-cartographer` and `raven-refactor-reviewer` say "a code
  index if available" and name `rg` and LSP first, in the `.claude`, `.codex`, and `.gemini`
  trees. The `disallowedTools` line that blocks `mcp__gitnexus__rename` is unchanged.
- **Verification:** `uv run --group dev python -m pytest tests/test_agent_frontmatter.py -q`
  exits 0.
- **Invariants:** the three trees stay prose-equivalent; no `tools:` allowlist is added.

### 4a. Optional-server catalog and `[mcp] optional` config key

- **End state:** `common/.raven/mcp.json` ships `semgrep` only. A new
  `common/.raven/mcp-optional.json` holds the `gitnexus` definition (command `gitnexus`, args
  `["mcp"]`). `.raven/config.toml` accepts `[mcp] optional = ["gitnexus"]`; the key absent
  means "undecided", an empty list means "decided none". `RavenConfig` gains
  `optional_mcp: list[str] | None = None`, appended last and defaulted because
  `tests/test_orphans.py` builds it positionally. `load_mcp_servers` merges the named catalog
  entries after the baseline; the three render call sites in `template.py` pass the list.
  Unknown names fail closed with a `ConfigError`, as `[issue_tracker].platform` does.
  `common/.claude/settings.json` no longer pre-allows `mcp__gitnexus__*`.
- **Verification:** `uv run --group dev python -m pytest tests/test_config.py tests/test_template.py tests/test_apply.py tests/test_optional_mcp.py -q`
  exits 0 with new cases: default render has no `gitnexus`; `optional = ["gitnexus"]` renders
  it into `.mcp.json`, `.codex/config.toml`, and `.gemini/settings.json`; an unknown name
  raises; `optional = []` equals the default render. The existing `assertIn("gitnexus", ...)`
  assertions in `tests/test_template.py` and `tests/test_apply.py` flip to `assertNotIn`.
- **Invariants:** `semgrep` and `lsp` rendering is byte-identical to today; render stays
  deterministic; key ordering rules in `render.py` are unchanged.

### 4b. Interactive keep-or-remove decision during `raven upgrade`

- **End state:** `raven upgrade` implements the behaviour table in Upgrade Impact: a prompt
  helper beside `prompt_for_adoption` that checks `sys.stdin.isatty()` first, the
  `--keep-mcp NAME` and `--drop-mcp NAME` flags (repeatable, unknown names rejected before any
  write), a config write helper modelled on `replace_platform_line`, and a dry-run section.
  "Configured" means the current `.mcp.json`, `.codex/config.toml`, or `.gemini/settings.json`
  contains a `gitnexus` server.
- **Verification:** `uv run --group dev python -m pytest tests/test_optional_mcp.py tests/test_apply.py -q`
  exits 0 with new cases: interactive keep, interactive remove, EOF on stdin treated as keep,
  non-interactive keep with a notice, both flags, dry-run writes nothing, and no prompt when
  `optional` is already set or no server is configured.
- **Invariants:** a rejected request changes nothing on disk (the existing preflight rule); no
  prompt ever fires on `install`; `raven upgrade --dry-run` exit code and file buckets are
  otherwise unchanged.

### 4c. `raven doctor` check for an index without a server

- **End state:** `optional_mcp_findings` in `scripts/raven_lib/doctor.py` reports three states,
  none an ERROR. INFO `doctor.mcp.optional_undecided`: a catalog server is configured and
  `[mcp] optional` is absent. WARN `doctor.mcp.optional_not_rendered`: the config opts a server
  in but no MCP file declares it (a pending guided merge, a disabled component, an unrun
  upgrade). INFO `doctor.mcp.index_without_server`: an index directory exists, the key is
  absent, and no server is configured. An explicit `optional = []` stays silent, because an
  index with a user-scope server is a legitimate setup; warning there would be noise. This
  narrows the first draft, which warned on any index without a server.
- **Verification:** `uv run --group dev python -m pytest tests/test_optional_mcp.py tests/test_doctor.py -q`
  exits 0, with `OptionalMcpDoctorTests` covering each of the three states plus the silent ones.
- **Invariants:** existing doctor finding ids and severities are unchanged; no network or
  subprocess call is added.

### 5. `raven-tool-check.py`: add CodeGraph

- **End state:** a `codegraph` entry in the tool list of all three copies, with `commands`
  `[["codegraph", "--version"]]`, purpose "pre-indexed exploration and caller lookup", and
  an install note pointing at the official docs and recommending `CODEGRAPH_TELEMETRY=0`.
  It is reported as optional, like GitNexus.
- **Verification:** `npx -y @colbymchenry/codegraph --version` exits 0 (run once by hand with
  telemetry off and recorded; CodeGraph need not be installed globally), then
  `uv run --group dev python -m pytest tests/test_tool_check.py tests/test_claude_script_symlinks.py -q`
  exits 0 with a new test asserting the entry exists and is non-blocking when absent.
- **Invariants:** the GitNexus entry is unchanged; missing optional tools still produce no
  failure exit code; the three script copies diverge only in embedded path strings.

### 6. Docs

- **End state:**
  - `raven-tool-assessment.md` gains a CodeGraph row and a short evidence note: no measured
    accuracy gain, a cost win on exploration only, and the two layout caveats (a Go module
    below the repo root, and a pnpm workspace whose packages export build output).
  - The GitNexus row notes its license (the README badge says PolyForm Noncommercial; confirm
    against the LICENSE file before stating it as fact) and recommends
    `{"skipContextFiles": true}` in `.gitnexusrc`, so `gitnexus analyze` does not inject a
    MUST-style block into `AGENTS.md`.
  - `docs/tooling.md`, `README.md`, and `generic/README.md` stop saying the templates ship a
    GitNexus MCP default or that impact analysis is mandatory where an index exists.
  - `docs/upgrading.md` gains an "Optional MCP servers" section: the config key, the upgrade
    prompt and its non-interactive default, `--keep-mcp`/`--drop-mcp`, dry-run behaviour, and
    the doctor findings.
- **Verification:** `uv run --group dev python -m pytest tests/test_docs_drift.py -q` exits 0 and
  `uv run --group dev python scripts/check-guidance.py` exits 0.
- **Invariants:** no local absolute path and no downstream repo name appears in any edited file
  (`just check-fast` passes the staged-hygiene hook).

### 7. End-to-end self-check

- **End state:** the repo installs, upgrades itself, and passes its full unit suite with the
  template changes in place.
- **Verification:** `uv run --group dev python scripts/self-check.py` exits 0, and
  `rg -n 'mcp__gitnexus__' common/ --glob '!common/.agents/skills/raven-codebase-discovery/**' --glob '!common/.claude/agents/**' --glob '!common/.codex/agents/**' --glob '!common/.gemini/agents/**'`
  returns nothing.
- **Invariants:** unexpected self-upgrade output is treated as a product bug per `AGENTS.md`;
  the self-upgrade rewrites `.mcp.json` and `.claude/settings.json` without the `gitnexus` entry.

### 8. Dogfood: Raven's own repo follows the new guidance

- **End state:** the vendor-generated `<!-- gitnexus:start -->` to `<!-- gitnexus:end -->` block
  is deleted from the root `AGENTS.md` (`.gitnexusrc` already sets `skipContextFiles`, so
  `gitnexus analyze` will not re-inject it). Raven's own `.raven/config.toml` gains
  `[mcp] optional = []` so the self-upgrade drops the `gitnexus` server and pre-allows rather
  than keeping them by the non-interactive default. A maintainer who still wants GitNexus adds
  it to `.claude/settings.local.json` or user scope; Raven's local instructions above the
  managed block say how.
- **Verification:** `rg -n 'gitnexus:start|MUST run impact analysis' AGENTS.md` returns
  nothing, and `uv run --group dev python scripts/self-check.py` exits 0.
- **Invariants:** the `RAVEN:BEGIN/END` managed block is byte-identical to the shipped
  template; no other local instruction above the block changes.

## Upgrade Impact (what `raven upgrade` does to existing users)

Measured on scratch installs of the current template, then an upgrade against a template that
simply dropped the `gitnexus` server (the behaviour before work items 4a to 4c):

| Repo state before upgrade | Result without the prompt |
|---|---|
| Pristine install | `.mcp.json` and `.codex/config.toml` silently lose the `gitnexus` server; `.claude/settings.json` loses the two pre-allows. |
| `.mcp.json` edited | Left untouched, guided-merge artifact written, entry stays until merged. |
| `.claude/settings.json` hand-edited | Left untouched, guided-merge artifact written. |

With work items 4a to 4c the pristine case no longer happens silently:

| Situation at `raven upgrade` | Behaviour |
|---|---|
| Interactive terminal, config has no `[mcp] optional` key, a GitNexus server is configured | Prints what changed (GitNexus demoted to optional, CodeGraph recommended for exploration, the evidence in two lines) and asks keep or remove. Keep writes `optional = ["gitnexus"]`; remove writes `optional = []`. The answer is recorded, so the question is never asked again. |
| Same, non-interactive (CI, pipe) and no flag | No removal. Treated as keep, recorded in config, and a notice says how to remove it. |
| `--keep-mcp gitnexus` or `--drop-mcp gitnexus` | Decides without a prompt, interactive or not. |
| `--dry-run` | Never prompts or writes config; prints a "decision needed" section naming both outcomes. |
| No GitNexus server configured anywhere | No prompt, no config change. |
| `[mcp] optional` already present | Honoured as-is; no prompt. |
| User keeps and had edited `.mcp.json` | Rendered output now matches their server set, so no guided-merge artifact is produced for that entry. |
| User removes and had edited `.mcp.json` | Guided-merge artifact shows the removal; their other servers are untouched. |

Remaining hazards and their handling:

- **Stale vendor block.** GitNexus's own `AGENTS.md` block keeps saying MUST. The prompt text
  and the tool-assessment doc both recommend `.gitnexusrc` `{"skipContextFiles": true}`.
- **Index without a server.** Covered by the doctor check in work item 4c.
- **Discoverability.** `docs/upgrading.md` documents the prompt, the flags, and the config key.

## Verification

Run order: item-specific commands above, then
`uv run --group dev python scripts/self-check.py`, then `just check-fast`.

## Follow-Ups

- CodeGraph roster support: show an `Index` line for `.codegraph/` once a stable, documented
  way to read its freshness exists. CodeGraph auto-syncs, so the stale check may not apply.
- Re-run the agent-task comparison with a larger task set (answer-quality grading, more than
  one symbol per repo, a second model) before promoting any tool to a default.
- Decide whether `docs/upgrading.md` should schedule removal of the GitNexus roster branch.

## Open Questions

- None blocking. The user chose "no graph server by default", "keep GitNexus as a documented
  alternative", and, for upgrades, an interactive keep-or-remove prompt plus a doctor check.
