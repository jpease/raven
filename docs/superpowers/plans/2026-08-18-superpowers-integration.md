# Plan: External sources and skill-lane collision reporting

## Goal

Give Raven a way to record that a repository depends on an externally-installed
agent-skill library, verify that dependency in `raven doctor`, and report every
case where a Raven skill and an installed upstream skill claim the same lane.

The collision report is the deliverable. The source declaration exists to make
it possible. Nothing is retired or merged as a result — the report exists so a
later decision can be made on evidence.

## Definitions

- **Superpowers**: a Claude Code plugin (`obra/superpowers`, MIT) shipping a
  library of process skills — `test-driven-development`, `systematic-debugging`,
  `writing-plans`, and eleven others. It is installed through Claude Code's
  plugin marketplace, machine-global, not per repository. It is the only source
  this plan implements.
- **Lane**: a short slug naming a kind of work a skill claims, e.g. `debugging`.
  Lanes are declared by Raven in `LANE_CLAIMS` (Work Item 4), never inferred.
  The slug is printed in the collision finding.
- **Collision**: one Raven skill and one upstream skill claiming the same lane,
  both *installed* where this repository would reach them — the Raven skill in
  the destination tree, the upstream skill under a recorded `installPath`.
  Deliberately **not** "both present in the same session": Raven cannot
  establish session presence (Assumption 7), so neither this definition nor any
  finding's message may claim it. Copying the word "session" into a finding is
  the specific mistake to avoid.
- **Claude adapter present**: the destination has a `.claude/` directory.
  There is no single "adapter enabled" boolean — `[components.claude]` is a
  table of per-component toggles (`components.claude.scripts` and
  `components.codex.scripts` move independently), so presence of the directory
  is the test, following `doctor._tool_check_script`'s precedent of resolving
  under whichever adapter the install actually has. A destination with no
  `.claude/` is Codex-only: no Claude plugin is reachable, and the Sources
  section is skipped entirely.
- **GSD**: `open-gsd/gsd-core`, a separate spec-driven workflow system. Named
  only to state it is out of scope.
- **`scripts/check-guidance.py`**: a repo gate that validates commands and flags
  quoted in tracked markdown against the real CLI parsers. It is why every
  command in this plan must be one that actually exists.
- **Config-first short-circuit**: `build_doctor_findings` loads the config
  first and, if it is malformed, returns that single ERROR and nothing else —
  every later check assumes a loadable config. New checks go after it.

## Scope

- `scripts/raven_lib/models.py`: a `SourceSpec` record; a trailing `sources` field on `RavenConfig`.
- `scripts/raven_lib/config.py`: parse `[sources.<name>]` sections.
- `scripts/raven_lib/__init__.py`: re-export `SourceSpec` (required by `test_package_api.py`).
- `scripts/raven_lib/constants.py`: `claude_config_dir()`, the one function that reads `CLAUDE_CONFIG_DIR`.
- `scripts/raven_lib/constants.py`: the `LANE_CLAIMS` table (same file as `claude_config_dir()` above).
- `scripts/raven_lib/doctor.py`: registry detection plus a `Sources` finding category.
- `scripts/raven_lib/data/config.toml.tmpl`: document the new section.
- `.raven/config.toml` (this repository's own, hand-edited): declare the source.
- Tests to write: `tests/test_config.py`, `tests/test_doctor.py`.
- Tests to **run, not edit**: `tests/test_package_api.py`, `tests/test_orphans.py`,
  `tests/test_raven_config_lib.py`. They are listed because this change can break
  them (export round-trip, positional `RavenConfig` construction, the separate
  git-hooks config parser); if any needs an edit to pass, that is a signal the
  change went wider than intended, not a task.

## Non-Goals

- **No skill is retired.** `raven-debug-failure` and `raven-review-pr` keep shipping.
- **No overlay mechanism.**
- **No `min_version` comparison.** See Assumption 5.
- No vendoring, no per-file provenance in the manifest, no source-aware
  `template.py`. `apply.py`, `manifest.py`, `orphans.py`, `deactivated.py`, and
  `template.py` are untouched.
- No change to `common/AGENTS.md`, `common/.agents/skills/`, or
  `common/.claude/docs/`. This keeps the plan clear of three budgets it would
  otherwise have to raise: the 1110-word `common/AGENTS.md` ceiling (currently
  at 1107), the 435-word skill-description aggregate, and the hand-maintained
  `_TREE_SYMLINKS_TO_COMMON` list in `scripts/self-check.py`.
- No GSD integration.
- No new dependency; stdlib-only on the Python 3.9 floor.

## Assumptions

1. **`[sources.<name>]`, not `[[source]]`.** `parse_simple_toml`
   (`config.py:171`) handles `[section]` headers and `key = value` lines only;
   array-of-tables would need parser work. A dotted header parses today as the
   literal key `"sources.superpowers"`. Precedent exists in both directions:
   `_merge_component_overrides(raw, "components.claude", ...)` (`config.py:267`)
   already depends on this behavior, and
   `common/.claude/scripts/raven-tool-check.py:604-607` iterates parsed section
   names filtering on a `"mcp_servers."` prefix — the identical pattern.
   `build_config` never enumerates or validates the section set, so an unknown
   section is inert. Zero parser changes.
2. **The section suffix is the plugin name.** `[sources.superpowers]` declares
   the plugin `superpowers`. `SourceSpec` carries no name field; the suffix is it.
3. **The registry is `<claude-config-dir>/plugins/installed_plugins.json`.**
   `<claude-config-dir>` is `CLAUDE_CONFIG_DIR` when set and non-empty,
   otherwise the `.claude` directory in the user's home directory. The file's
   shape, as observed:

   ```json
   {
     "version": 1,
     "plugins": {
       "superpowers@claude-plugins-official": [
         {
           "scope": "user",
           "installPath": "<claude-config-dir>/plugins/cache/claude-plugins-official/superpowers/6.3.0",
           "version": "6.3.0",
           "installedAt": "2026-02-24T03:33:22.556Z",
           "lastUpdated": "2026-08-12T18:51:40.233Z",
           "gitCommitSha": "e4a2375c..."
         }
       ]
     }
   }
   ```

   The mapping is nested under the top-level `"plugins"` key, not at the root.
   Keys are `<plugin>@<marketplace>`; match on the segment before `@`, because
   the marketplace name varies. Values are always lists, even with one entry.
   The `scope` field is recorded but unused by this plan. `installPath` values
   are absolute in the real file; the angle brackets above are this document's
   redaction of a home directory, not a literal. Split plugin keys on the
   **first** `@`.
4. **Upstream skills live at `<installPath>/skills/<skill-name>/`.** Verified
   against the installed tree.
5. **`min_version` is not implemented.** The recorded version is weak evidence:
   on the development machine the cache holds four coexisting trees for one
   plugin — two version-named (`6.2.0`, `6.3.0`) and two sha-named — and sibling
   plugins in the same registry record `"version": "unknown"`. A comparison
   against that data would produce confident, wrong answers. `SourceSpec`
   therefore has no `min_version` field in this cut; doctor reports the versions
   it read and where it read them, and compares nothing.
6. **Multiple install records need no tie-break.** A plugin may appear at
   several scopes. Rather than pick a winner, doctor treats every record's
   `installPath` as a place to look: a lane collides if the upstream skill
   directory exists under **any** recorded path. Versions are reported as the
   list that was read. The `.in_use` marker that actually identifies the live
   tree is deliberately **not** read — it is undocumented and its semantics are
   unclear.
7. **Installed is not enabled.** A separate blocklist file and per-project
   enablement settings can disable an installed plugin. Doctor's wording says
   "installed", never "active" or "available to this session".
8. **`exit_code` is ERROR-only.** `findings.py:37` returns 1 if any finding is
   ERROR, else 0. WARN and INFO cannot change doctor's exit code — the Work
   Item 6 invariant is therefore satisfied by construction, provided no new
   finding is ERROR. `required = true` produces ERROR, which is why this
   repository sets `required = false` (Work Item 6).
9. **Doctor's env access is one named function.** `doctor.py` performs no
   out-of-destination reads today (no `Path.home`, `expanduser`, or `os.environ`
   anywhere in the module). `constants.claude_config_dir()` becomes the single
   place that reads the environment; `doctor.py` calls it **only when its
   `registry` parameter is `None`**, in the function body — never as an
   evaluated default in the signature (Work Item 2 gives the reason). Tests
   always pass an explicit path.
10. **`.raven/config.toml` is never rewritten by upgrade.** It is user-owned,
   written once at `init`/`install`, and is not a manifest-tracked template
   entry — only `.codex/config.toml` is. The hand-added `[sources.superpowers]`
   block of Work Item 6 therefore survives Verification step 3's self-upgrade.
11. **These modules already carry `from __future__ import annotations`.**
   `doctor.py`, `config.py`, `models.py`, and `constants.py` all do, so
   `Path | None` and `tuple[str, ...]` annotations are safe on the 3.9 floor.
   A new module would need the import added.

## Alternatives (approach rejected / why / what would reopen it)

**Retire `raven-debug-failure` and `raven-review-pr`, replacing them with
overlay docs.** Rejected on evidence from an adversarial review. Three
independent reasons: (a) `scripts/self-check.py:405-412` records that a skill's
`description:` frontmatter is injected into every session's skill index whether
or not the skill is invoked — that injected description *is* the harness-fired
trigger a retirement would delete, and an `AGENTS.md` pointer to a
`.claude/docs/` file replaces one harness hop with two voluntary ones; (b) the
same mechanism has already decayed unnoticed — `common/AGENTS.md:13` names seven
docs while `common/.claude/docs/` ships nine, with `raven-semgrep.md` and
`raven-tool-assessment.md` shipped, symlinked into all nine language trees,
referenced by `raven-security-review/SKILL.md`, and invisible from the
always-loaded list; (c) Codex reads `.agents/skills` as its only channel and has
no plugin equivalent, so a Codex-only repo would lose the skill outright and, by
the design's own adapter gate, get no warning. Reopened by: an overlay delivery
mechanism that fires on invoking an upstream skill, or Raven's deltas landing
upstream so there is nothing left to deliver.

**Compose: vendor upstream skills at install time, patch them with Raven
deltas, record per-file provenance, and leave the plugin uninstalled in
Raven-managed repos.** This is the durable end state for "a package manager for
agent guidance": one skill index, per-repo pinning, Codex parity, upstream
improvements flowing on upgrade. Deferred, not rejected. The measured problem it
would solve is small — the six Raven skills that overlap Superpowers cost 76
words of the 435-word always-loaded description budget, with bodies loaded only
on invoke — while the machinery is large: eighteen hand-made symlinks per new
shared file across nine language trees plus a `_TREE_SYMLINKS_TO_COMMON` entry
or the file silently never installs, manifest provenance, and MIT attribution.
Nothing here has to be unwound to get there; `[sources.<name>]` is the config
surface it would extend. Reopened by: the collision report showing a lane where
ceding is clearly right, or a Codex-first consumer needing the same skills.

**Overlays as `.claude/rules/` files.** Rejected: rules are always loaded, so
guidance that matters only while one skill runs would tax every session,
contradicting Raven's own token-discipline stance and the argument
`raven-antipatterns.md:8-10` already makes for itself.

**Infer collisions by comparing skill names or descriptions.** Rejected: the
strongest real pair, `raven-debug-failure` and `systematic-debugging`, shares no
tokens. A declared table is testable and states an opinion; a heuristic would
miss the cases that matter and invent ones that don't.

**Read the destination's `AGENTS.md` to decide which skill it prefers.**
Rejected: it makes a reporting function depend on parsing prose. Preference is a
static field per `LANE_CLAIMS` row instead.

**Implement `min_version` now.** Rejected: see Assumption 5. Reopened by the
registry gaining a version field that can be trusted.

**Make a missing source an ERROR by default.** Rejected: the README promises
Raven's templates "recommend tools ... but require none of them". The per-source
`required` knob raises it for a repo that means it.

## Work Items

### 1. `SourceSpec` and `RavenConfig.sources`

- **End state**: `SourceSpec` is a frozen dataclass with two fields: `kind: str`
  and `required: bool = False`. The only recognized `kind` is `"claude-plugin"`;
  `kind` is mandatory. `[sources.superpowers]` parses into
  `RavenConfig.sources["superpowers"]`. A missing `kind`, an unrecognized
  `kind`, or a non-bool `required` raises `ConfigError` naming the section,
  e.g. `[sources.superpowers]: kind must be "claude-plugin", got "npm"`. A
  config with no `sources.` section yields an empty dict. Unknown keys inside
  the section are ignored, not errors, so a future field is forward-compatible.
  `[sources.]` (empty suffix) raises `ConfigError`. A bare `[sources]` section
  with no dot fails the prefix filter and is inert — it declares nothing, and
  that is deliberate rather than an oversight. A dotted suffix such as
  `[sources.a.b]` names the plugin `a.b` — the suffix is taken whole.
  A `sources.<name>` key whose value is not a table also raises `ConfigError`:
  `parse_simple_toml` cannot produce one (a section is always a dict), but
  `build_config` is public and takes a raw mapping, so it fails closed there
  the way the rest of the module does.
- **Verification**: `uv run --group dev python -m pytest tests/test_config.py tests/test_raven_config_lib.py tests/test_package_api.py tests/test_orphans.py` exits 0.
- **Invariants**: `parse_simple_toml` and `parse_value` unmodified. The new
  `RavenConfig` field is appended **after** `exists` with a default —
  `tests/test_orphans.py:168` and `:519` construct `RavenConfig` positionally,
  so any other position breaks them silently. `SourceSpec` is re-exported from
  `scripts/raven_lib/__init__.py` and added to `__all__`, or
  `test_package_api.py`'s `test_all_matches_reexports` fails.

### 2. `claude_config_dir()` and registry detection

- **End state**: `constants.claude_config_dir() -> Path` returns
  `CLAUDE_CONFIG_DIR` when set and non-empty, else the `.claude` directory in
  the user's home. It is the only function in `raven_lib` that reads that
  variable.

  `PluginStatus` is a frozen dataclass with four fields: `state: str` — one of
  the module constants `FOUND`, `NOT_FOUND`, `UNDETERMINABLE` — plus
  `versions: tuple[str, ...]`, `install_paths: tuple[Path, ...]`, and
  `registry: Path` (the file it tried, echoed back so findings can name it).

  `doctor.detect_plugin(registry: Path, plugin: str) -> PluginStatus` is pure:
  it opens `registry`, walks `data["plugins"]`, and matches each key on the
  segment before `@` — a key with no `@` matches on the whole key. It returns
  `NOT_FOUND` only when the file parsed cleanly and the plugin was absent from
  it. Everything else Raven cannot see through — file absent, unopenable,
  invalid JSON, or `plugins` not a dict — is `UNDETERMINABLE`. **A missing
  registry file is `UNDETERMINABLE`, never `NOT_FOUND`**: on a machine where
  Claude Code has never written one, Raven does not know whether the plugin is
  installed, and saying "not installed" there is the same class of confident
  wrong answer that Assumption 5 cuts `min_version` to avoid. A
  `"version": "unknown"` record is `FOUND` with that string carried verbatim.
- **Verification**: `uv run --group dev python -m pytest tests/test_doctor.py -k registry` exits 0, with a
  case for each of: absent file, a **directory** where the file should be
  (portable stand-in for unopenable — `chmod` is a no-op as root and meaningless
  on Windows), invalid JSON, `plugins` not a dict, plugin absent, one record,
  three records at different scopes, `"version": "unknown"`, and a registry key
  with no `@`. The first four assert `UNDETERMINABLE`; only "plugin absent"
  asserts `NOT_FOUND`.
- **Invariants**: `detect_plugin` performs no subprocess, no network call, and
  no environment read. No test monkeypatches `Path.home` or any `pathlib`
  internal — every case builds a temp registry file and passes its path.
  `doctor.py` gains no `os.environ` reference.

  `PluginStatus`, the three state constants, and `detect_plugin` all live in
  `doctor.py`. Only `SourceSpec` is re-exported from `__init__.py`; these are
  internal to the module. The findings entry point is:

  ```python
  def sources_findings(
      destination: Path, config: RavenConfig, *, registry: Path | None = None
  ) -> list[Finding]:
      if registry is None:
          registry = claude_config_dir() / "plugins" / "installed_plugins.json"
  ```

  `config` is a required parameter: declared sources and their `required` flags
  live on `RavenConfig.sources`, and `build_doctor_findings` has already loaded
  the config before calling this, so re-loading here would duplicate the load
  and diverge from the config-first short-circuit's error handling. The
  `registry` default is a `None` sentinel resolved **in the body**, never an
  evaluated default in the signature — the latter freezes the environment at
  import time, and because the CLI reads the environment in a fresh process per
  run, manual Verification step 7 would still pass while every in-process test
  saw the importing process's value.

### 3. `Sources` findings

- **End state**: `raven doctor` grows a `Sources` category holding one *status*
  finding per declared source, id `doctor.sources.<name>`. Work Item 4's
  collision findings join the same category; "one per source" counts status
  findings only. Severity by state:

  | state | severity | wording |
  | --- | --- | --- |
  | `FOUND` | OK | installed, naming the versions read and the registry path |
  | `NOT_FOUND` | WARN, or ERROR when `required = true` | not installed |
  | `UNDETERMINABLE` | WARN **always**, even when `required = true` | cannot determine, naming the path it tried |

  `UNDETERMINABLE` never escalates to ERROR: "Raven cannot tell" is not
  "the dependency is missing", and a required source must not fail a build on
  a machine whose registry Raven simply could not read. Wording says
  "installed", never "active" — an installed plugin can still be blocklisted or
  disabled per project (Assumption 7). The whole section is skipped when the
  destination has no `.claude/` directory (see Definitions).
- **Verification**: `uv run --group dev python -m pytest tests/test_doctor.py -k sources` exits 0, including a
  Codex-only skip case and a `required = true` ERROR case.
- **Invariants**: `build_doctor_findings` keeps its config-first short-circuit;
  no existing finding id, severity, or category name changes. `Sources` is appended last, after
  `Drift & freshness`, so no existing section moves in the rendered report.

### 4. `LANE_CLAIMS` and collision findings — the deliverable

- **End state**: `constants.LANE_CLAIMS` is a tuple of `LaneClaim` rows —
  a `NamedTuple` with `lane`, `raven_skill`, `source`, `upstream_skill`,
  `prefer`, and `reason`, all `str`.
  The initial six rows:

  `prefer` is one of exactly two values: `"raven"` or `"upstream"`. There is no
  third state — a lane whose owner is unclear does not belong in the table yet.
  All six initial rows carry `source = "superpowers"`.

  | lane | raven_skill | source | upstream_skill | prefer | reason |
  | --- | --- | --- | --- | --- | --- |
  | `planning` | `raven-plan` | `superpowers` | `writing-plans` | `raven` | durable artifact, interrogation, fresh-context check |
  | `testing` | `raven-write-tests` | `superpowers` | `test-driven-development` | `raven` | repo guards and duplicate-check funnel |
  | `debugging` | `raven-debug-failure` | `superpowers` | `systematic-debugging` | `raven` | CI-failure handling upstream lacks |
  | `completion` | `raven-task-complete` | `superpowers` | `verification-before-completion` | `raven` | lifecycle checkpoint integration |
  | `review` | `raven-review-pr` | `superpowers` | `requesting-code-review` | `raven` | antipattern registry and Semgrep promotion |
  | `delegation` | `raven-delegate-or-inline` | `superpowers` | `dispatching-parallel-agents` | `raven` | inline-vs-delegate decision upstream does not make |

  A row is evaluated **only when its `source` is declared in the destination's
  `.raven/config.toml`.** A repo that never opted in gets no collision findings,
  however many plugins the machine happens to have installed — the table is
  machine-global, the report is not.

  For each evaluated row, doctor emits one INFO finding, id
  `doctor.sources.collision.<lane>`, when the directory
  `<destination>/.agents/skills/<raven_skill>/` exists **and**
  `<installPath>/skills/<upstream_skill>/` exists under at least one path in
  `PluginStatus.install_paths`. Both tests are directory existence; no file
  inside is opened, `SKILL.md` included. The finding states both skill names,
  the lane slug, and the `prefer` value. The `.claude/`-directory gate of Work
  Item 3 suppresses collisions as well as status findings — a Codex-only
  destination gets nothing from this category at all. Findings follow
  `LANE_CLAIMS` order and
  are not deduplicated — two rows sharing a lane slug produce two findings, and
  the duplicate ids are the signal that the table needs fixing. No collision is
  reported when the source is undeclared, `NOT_FOUND`, or `UNDETERMINABLE`.
- **Verification**: `uv run --group dev python -m pytest tests/test_doctor.py -k collision` exits 0. The
  end-to-end case builds a temp destination whose config declares
  `[sources.superpowers]` and which contains the directory
  `.agents/skills/raven-debug-failure/`, plus a temp registry pointing at a temp
  `installPath` containing `skills/systematic-debugging/`. It asserts the
  `debugging` collision is reported, and that removing any one of the three —
  the Raven directory, the upstream directory, or the config declaration —
  removes the finding.
- **Invariants**: The table is data — adding a row requires no code change.
  Every collision is INFO and must never fail a gate. Nothing reads upstream
  skill *content* or the destination's `AGENTS.md`; directory existence and the
  static `prefer` field are the whole test.

### 5. Document the section in the config template

- **End state**: `data/config.toml.tmpl` carries a commented
  `[sources.superpowers]` block showing `kind = "claude-plugin"` and
  `required = false`, in the file's existing self-documenting voice, commented
  out so a fresh install declares nothing.
- **Verification**: `uv run --group dev python -m pytest tests/test_config.py` exits 0 and
  `uv run --group dev python scripts/raven.py install --dry-run` renders the template without a parse error.
- **Invariants**: A freshly rendered config parses to the same `RavenConfig` as
  before, modulo an empty `sources`. `.raven/manifest.json` gains **no** entry
  for this edit, contrary to what an earlier draft of this item predicted:
  `config.toml.tmpl` is not itself installed anywhere, and the file it renders,
  `.raven/config.toml`, is not manifest-tracked (Assumption 10). The only
  manifest diff a self-check produces here is the version/timestamp churn Work
  Item 6 discards.

### 6. Converge the self-install

- **End state**: This repository's `.raven/config.toml` gains
  `[sources.superpowers]` with `kind = "claude-plugin"` and `required = false`.
  On a machine with the plugin installed, `raven doctor` here reports it
  installed plus six collisions.
- **Verification**: `uv run --group dev python scripts/self-check.py` exits 0; a second consecutive
  run reports no pending upgrade work; `uv run --group dev python scripts/raven.py doctor` exits with
  the code captured in Verification step 0 below.
- **Invariants**: `required` stays `false` here — `true` would produce ERROR on
  every contributor machine without the plugin and turn a green doctor red
  (Assumption 8). A version- or timestamp-only manifest diff is discarded rather
  than committed. On a machine **without** the plugin, the expected end state is
  the "not installed" WARN and zero collisions; that is a pass, not a failure,
  and the collision path is covered by Work Item 4's fixture instead.

## Verification

Run in order. Every command uses `uv run --group dev python` so the interpreter
is the same one the gates use.

0. **Before editing anything**, capture the baseline:
   `uv run --group dev python scripts/raven.py doctor; echo $?` — record the code. Step 5 compares against it.
1. `uv run --group dev python -m pytest tests/test_config.py tests/test_raven_config_lib.py tests/test_doctor.py tests/test_package_api.py tests/test_orphans.py` exits 0.
2. `just test` exits 0 — full suite, no pre-existing failure bypassed.
3. `uv run --group dev python scripts/self-check.py` exits 0.
4. `uv run --group dev python scripts/check-guidance.py` exits 0 — it checks this plan's own commands.
5. `uv run --group dev python scripts/raven.py doctor` exits with the step-0 code, and — when the
   plugin is installed on this machine — its `Sources` section reports the
   source installed and lists **all six** lanes: `planning`, `testing`,
   `debugging`, `completion`, `review`, `delegation`. Fewer than six means an
   upstream skill directory named in `LANE_CLAIMS` does not exist under
   `installPath`. Before editing the table, rule out the two other causes: a
   `LANE_CLAIMS` row naming a `raven_skill` directory this repo does not have,
   and the `.claude/` gate suppressing the whole category. Fix whichever side is
   actually wrong — never the assertion.
6. `just check-fast` passes, including staged-hygiene.
7. With `CLAUDE_CONFIG_DIR` set to an empty directory,
   `uv run --group dev python scripts/raven.py doctor` reports the source
   **undeterminable** (there is no registry file to read — see Work Item 2),
   reports zero collisions, and still exits with the step-0 code. The
   `NOT_FOUND` path has no manual equivalent and is covered by Work Item 2's
   fixtures instead.

## Follow-Ups

- **Open question**: should shipped templates declare `[sources.superpowers]`
  commented-out (as Work Item 5 does) or omit it entirely? Work Item 5 assumes
  commented-out is more discoverable.
- `min_version` was cut (Assumption 5). Revisit only if the registry gains a
  version field that can be trusted, or if reading the `.in_use` marker becomes
  documented behavior.
- Send Raven's genuinely general deltas upstream rather than maintaining them in
  parallel: `raven-debug-failure`'s CI-failure section (treating CI logs as
  untrusted prompt-injection surface, flake-vs-real discrimination) has no
  counterpart in `systematic-debugging` and is not Raven-specific.
- `common/AGENTS.md:13` lists seven `.claude/docs/` files while nine ship. Fix
  separately; it is evidence for Alternatives but not in scope.
- `scripts/self-check.py:414` describes `SKILL_DESCRIPTION_AGGREGATE_LIMIT` as
  "388 words in-tree + 4 words of slack" while line 426 sets 435. Reconcile.
- `.superpowers/sdd/` holds untracked July artifacts and is not in `.gitignore`.
- Revisit lane ownership once the collision report has run against several
  repositories — that data, not argument, should decide any future retirement.
