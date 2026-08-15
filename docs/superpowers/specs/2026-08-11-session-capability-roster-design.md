# Design: Session Capability Roster

Date: 2026-08-11
Status: Revised after adversarial review; approved design, pending
implementation plan

## Summary

Raven already probes recommended tooling at session start, but the result never
reaches the agent. This design adds an **emitter** script that probes inline and
prints a compact capability roster into session context on every session start.

The roster covers CLI tools, configured MCP servers, the active template's gate
tools, the issue-tracker CLI, and code-intelligence index freshness.

`AGENTS.md` then defers to the roster for tool availability, dropping most of
the hedging it currently carries while keeping one fallback sentence for
contexts where no roster exists.

## Motivation

`common/.claude/scripts/raven-tool-check.py` probes 14 tools and persists the
result to `~/.raven/tool-memory.json`. It is wired as a SessionStart hook in
both the Claude Code and Codex adapters, and `raven doctor` re-runs it on
demand via `toolchain_findings`.

Three defects make that machinery nearly inert in practice.

### 1. Silent degradation

Nothing reads the result back into session context. The agent knows the
retrieval ladder from `AGENTS.md` but not whether any rung of it is installed,
so it discovers availability by attempting a call. When it does not attempt the
call, it silently uses a worse tool:

    AGENTS.md: "Syntax-aware pattern or mechanical rewrite -> ast-grep or Semgrep"
    Agent:     (availability unknown) -> uses rg plus manual edits
    Reality:   both installed

Nothing failed and nothing was logged. The better path was simply never taken.
This is the most expensive of the three defects because it is invisible.

### 2. Wasted failed calls

The inverse case costs a round-trip and muddies the transcript. It is
self-correcting, so it matters less than (1), but it shares the root cause.

### 3. Stale trust

The `--session-start` path is silent-on-success and, after its first run,
silent-on-everything:

```python
if args.session_start:
    if memory["preferences"].get(_DO_NOT_REMIND_KEY):
        return 0
    if _memory_has_complete_records(memory, current_os):
        return 0  # never speaks again
```

`_memory_has_complete_records` checks only record presence and OS match. There
is no TTL and no timestamp comparison. Once every tool has been recorded once,
the hook returns 0 forever — including after a tool is uninstalled. Observed
during design: a local cache written 14 days earlier still reported all 14
tools available, and the hook emitted nothing.

### Adjacent evidence

Issue #143 documents the same disease in a different organ: two shipped
subagents instruct the agent to use Semble, LSP, and GitNexus while their
`tools:` frontmatter allowlist denies MCP entirely. In both cases Raven asserts
a retrieval ladder it never verifies.

## Non-Goals

- **Subagent coverage.** SessionStart hooks do not fire for subagents, so
  `raven-codebase-cartographer` and `raven-refactor-reviewer` will not see a
  roster. That gap is issue #143 and needs a different fix (`disallowedTools`
  in place of a `tools` allowlist). This design does not address it.
- **Installing tools.** The roster reports; `raven-tool-bootstrap` continues to
  own the install conversation, and the existing consent rules are unchanged.
- **Replacing `raven doctor`.** Doctor stays the on-demand, severity-scored
  diagnostic. The roster is a passive per-session fact sheet. See "Doctor
  reconciliation" for how their scopes relate.
- **Proving a tool works.** The roster answers "is it present and is the index
  current", not "does it execute correctly" or "is this MCP server connected".
  The format labels each line accordingly rather than overclaiming.

## Design

### Probe inline; there is no cache, lock, or background refresh

An earlier draft of this design cached the roster and refreshed it in a
detached background process, on the premise that probing is expensive. That
premise is false. Measured on the development machine:

| Operation | Cost |
|---|---|
| Python interpreter startup (unavoidable, paid by any hook script) | ~140 ms |
| `check_all_tools()` for all 14 tools | **2.7 ms** |
| `git rev-parse HEAD` | 5.3 ms |
| `git status --porcelain` | 19.4 ms |

Probing is cheap because `command_status`
(`common/.claude/scripts/raven-tool-check.py:294-312`) short-circuits to
`shutil.which` unless `RUN_COMMAND_PROBES` is set, and that flag reads
`RAVEN_TOOL_CHECK_EXECUTE` (line 207) — an environment variable set nowhere in
`common/`, `scripts/`, `tests/`, or the justfile. The subprocess-executing path
is dead in every shipped configuration. The same is true of
`RAVEN_TOOL_CHECK_CLAUDE_CLI` (line 208), which gates the `claude mcp list`
subprocess.

A cache plus a lock plus a detached spawn plus an atomic-write refactor, all to
avoid 2.7 ms, would have cost more than it saved: the detached child pays the
same ~140 ms interpreter startup, on every session, forever.

**The emitter therefore probes inline every session.** Consequences, all
favorable:

- The roster is always current. There is no one-session staleness, no TTL to
  tune, and no cold-start special case.
- No `repos` cache map, so no absolute-path cache key and none of the worktree,
  container, or duplicate-clone fragmentation that key would have caused.
- No lock file, no stale-lock reclamation, no atomic-write refactor of
  `save_memory`, no platform-specific process detachment.
- `optionalWhen` and the `timed_out` tri-state are available directly from the
  in-memory probe result, so no new persistence is required.

Total added cost at session start is roughly 30 ms of work on top of an
interpreter start that the current hook already pays.

### Components

| Component | Change |
|---|---|
| `raven-capability-roster.py` (x2 adapters, new) | The **emitter**. Resolves the repo root, imports the prober module for probe primitives, probes, formats, writes to stdout. Flags: `--json`, `--no-color`. |
| `raven-tool-check.py` (x2 adapters) | Unchanged responsibilities. `--session-start` is **retained** as a deprecated alias (see Migration). Gains nothing new; the emitter reuses its functions rather than duplicating them. |
| `common/.claude/settings.json`, `common/.codex/hooks.json` | SessionStart repointed to the emitter. |
| `scripts/raven_lib/` installer, `.raven/manifest.json` | Installer records the active template's resolved gate tools in the manifest. |
| `common/AGENTS.md` | Retrieval ladder defers to the roster; most hedging removed. |

The emitter imports the prober rather than reimplementing it. Both scripts ship
side by side in `.claude/scripts/`, so the emitter loads its sibling by
`Path(__file__).parent / "raven-tool-check.py"` via `importlib`. It must not
use `sys.argv[0]`: under the Codex launcher the script is invoked through
`runpy.run_path` with a relative path.

This keeps probe logic single-sourced while leaving formatting — the part most
likely to need iteration — in a small file testable with fixture data and no
subprocess.

Both adapters get their own copy. The existing `.claude/` and `.codex/` copies
of `raven-tool-check.py` are regular files with differing content, not
symlinks; they diverge in the paths embedded in help text and prompts. The new
script follows that established convention, and the existing adapter-parity
tests extend to cover it.

### Repo root resolution

The emitter must not use `Path.cwd()`. `tests/test_agent_hooks.py:256-258`
records that "Codex Desktop can invoke a hook with a process cwd outside the
project", and `tests/test_template.py:258-282` exercises exactly that case. The
Codex launcher in `common/.codex/hooks.json` already resolves the root from the
hook's stdin payload and then `runpy.run_path`s the target without chdir'ing.

The emitter resolves its root the same way: read `cwd` from the stdin payload
when present, walk upward to the nearest directory containing `.git`, and
`Path.resolve()` the result. Every repo-scoped read — `.raven/config.toml`,
`.raven/manifest.json`, `.gitnexus/meta.json`, `.mcp.json` — is taken relative
to that root, and `git` invocations run with it as `cwd`.

The prober's own `Path.cwd()` usage
(`_claude_mcp_config_paths:333-340`, `_codex_mcp_config_paths:343-349`) is a
pre-existing bug with the same cause. It is tracked separately; this design
does not depend on fixing it, because the emitter passes an explicit root to
the functions it reuses.

### Roster format

Written to stdout by the emitter. SessionStart hook stdout is injected as
session context by both adapters. Values below are real, taken from this
repository rather than composed by hand.

Nominal:

```text
=== RAVEN CAPABILITIES ===  probed 2026-08-11 · template: python
  CLI        rg fd just jq yq rtk ast-grep semgrep gitleaks osv-scanner uvx
  MCP (cfg)  gitnexus lsp semble semgrep
  Gates      ruff ✓  pyright ✓
  Tracker    gh ✓
  Index      gitnexus · 2703 nodes / 128 files · current
  Absent     —
```

Degraded:

```text
=== RAVEN CAPABILITIES ===  probed 2026-08-11 · template: python
  CLI        rg fd just jq yq rtk ast-grep gitleaks uvx
  MCP (cfg)  gitnexus lsp semble
  Gates      ruff ✓  pyright ✗
  Tracker    gh ✓
  Index      gitnexus · 2703 nodes / 128 files · STALE (working tree modified)
  Absent     semgrep — security, policy, and multi-language static-analysis rules
  Optional   osv-scanner
  Unverified —
```

Format rules:

- **`Absent` no longer carries `optionalWhen`.** Only tools with no
  `optionalWhen` fallback render a full `name — purpose` entry — the reader
  has no other coverage for those and needs the purpose string to judge the
  gap. Tools with an `optionalWhen` (something else already covers the work)
  collapse onto a single name-only `Optional` line; the reasoning for why
  each is optional lives only in `TOOLS`, not in the roster.
  Reversed 2026-08-12 (#156): this section originally rendered `purpose` and
  `optionalWhen` verbatim for every absent tool, priced at roughly 450
  characters for the five `optionalWhen` tools. That was cheap once, but the
  roster has no suppression path short of `doNotRemind` — which also
  silences genuine gaps — so the same 450 characters re-emit into context
  every session until every tool is installed. See #156's measurement:
  1825 bytes / 18 lines before this change, 1078 / 15 after on this repo.
- **`MCP (cfg)` is deliberately labelled.** The list is derived from
  configuration files, and configured is not connected: Claude Code requires
  per-project approval, and a misconfigured remote server can fail to connect
  silently. The label prevents the roster from asserting more than it knows.
- **`Gates` renders availability, not just names.** `ruff ✓  pyright ✗` answers
  the decision-relevant question. Names alone would be nearly useless for
  several templates, where the gate tool list is a single generic binary —
  `typescript` is `["npx"]`, `rust` is `["cargo"]`, `elixir` is `["mix"]`
  (`scripts/raven_lib/data/gate_data.py:45-130`).
- **`Unverified` is a third bucket.** `result_status`
  (`raven-tool-check.py:211-222`) is a tri-state — available, `timed_out`,
  missing — and `print_human_report` gives timeouts their own section with the
  wording "installation/configuration was not confirmed". Collapsing timeouts
  into `Absent` would contradict the human report; collapsing them into present
  would assert something unverified. The line is omitted when empty.
- **A section line is omitted when its category is inapplicable** — no
  `Tracker` when `[issue_tracker].platform` is unset, no `Index` when no index
  metadata is readable, no `Gates` when the manifest carries no resolved gate
  tools.
- **`Absent —` on a fully-provisioned machine is deliberate.** Its presence
  confirms the roster ran and found nothing missing, which is a different fact
  from the roster having been suppressed.
- **`preferences.doNotRemind` suppresses `Absent`, `Optional`, and
  `Unverified` only.** The rest of the roster still emits. The preference
  means "stop nagging me about installing things", not "stop telling me what
  I have". This is a display-only rule; the emitter always probes.

### Index staleness

The naive check — cached `lastCommit` versus current `HEAD` — is wrong in both
directions, and the wrong answers are worse than no answer because `CLAUDE.md`
makes GitNexus impact analysis mandatory before symbol edits.

- **False "current".** The agent edits 40 files without committing and runs
  `impact()`. `HEAD` has not moved, so a commit-only check reports the index as
  current. It is not. This is the common case and precisely what the marker
  exists to catch.
- **False "stale".** One docs-only commit moves `HEAD` and flips the marker,
  instructing a reindex of a perfectly good index. On this repository a reindex
  regenerates a 137 MB artifact.

The emitter therefore evaluates two conditions against `.gitnexus/meta.json`:

1. **Committed drift** — `meta.json`'s `lastCommit` differs from
   `git rev-parse HEAD`. Both are full 40-character SHAs; compare them raw and
   never mix in `--short` output, which `scripts/raven_lib/manifest.py:98` uses
   elsewhere at a different width.
2. **Uncommitted drift** — `git status --porcelain` reports any modification to
   a tracked file.

`STALE` renders with which condition tripped, so the message is actionable:
`STALE (working tree modified)` or `STALE (indexed cd29867, HEAD d89f2cd)`.
Either condition alone is sufficient.

Field names come from the real file. `meta.json` has **no `symbols` field**; it
carries `stats` with `files`, `nodes`, `edges`, `communities`, `processes`, and
`embeddings`, plus `schemaVersion`, `lastCommit`, `indexedAt`, and a
`fileHashes` map. The roster renders `stats.nodes` and `stats.files`.
`schemaVersion` is currently `5` and is an unversioned external contract: if
the expected fields are absent, the `Index` line is omitted rather than
rendered with placeholders.

A `fileHashes` comparison would be more precise than `git status`, but it means
hashing every indexed file each session. The two git calls cost about 25 ms
combined and catch the same drift for tracked files, which is what the index
covers.

### Sanitization

The roster is hook stdout, and hook stdout becomes model context. Several of
its inputs are repository-controlled:

- MCP server names, harvested recursively from `.mcp.json` **and
  `~/.claude.json`** by `_mcp_server_names_from_value:319-330`, and from Codex
  TOML by `_codex_mcp_server_names_from_toml:352-362`, which does `strip('"')`
  and nothing else.
- `template` from `.raven/config.toml`.
- `lastCommit` and `stats` from `.gitnexus/meta.json`.

JSON object keys may contain newlines and arbitrary text. A repository shipping
an `.mcp.json` whose server name embeds a fake section header would place that
text in the model's context at session start, before the user's first message,
inside a block that `AGENTS.md` designates as authoritative for tool
availability. `common/.claude/rules/raven-security.md:3` requires treating tool
and log content as untrusted prompt-injection input; the roster must not be the
exception.

Every interpolated value is therefore sanitized before rendering:

- Identifiers (tool, server, template, gate tool, and tracker names) must match
  `[A-Za-z0-9._-]+`. Non-matching values are dropped, not escaped, and a count
  of dropped entries is rendered in their place.
- SHAs must match `[0-9a-f]{7,40}`. Numeric stats must be integers.
- Each rendered field is length-capped; the whole roster is byte-capped, and
  the emitter truncates with an explicit marker rather than emitting an
  unbounded block.
- Strings from the prober's own `TOOLS` table (`purpose`, `optionalWhen`) are
  Raven-authored constants, not repo input, and are exempt from the identifier
  rule — but still count toward the byte cap.

### Gate tools across the shipping boundary

`scripts/raven_lib/` is installer-side and does not ship. Destination repos
receive standalone scripts under `.claude/scripts/`. The template-to-gate-tools
map lives in `scripts/raven_lib/data/gate_data.py` and is unreachable from the
shipped emitter.

The installer resolves it at apply/upgrade time via
`gates.gate_spec_for(template).tools` — the typed accessor, not raw dict
attribute access — and records the result in `.raven/manifest.json`.
`GATE_DATA` stays the single source of truth; the shipped emitter reads a
derived artifact.

Adding a key to the manifest is safe for older Ravens:
`SUPPORTED_MANIFEST_SCHEMAS` (`scripts/raven_lib/manifest.py:16`) validates only
the `schema` value and the `files` shape, and `update_manifest` preserves
unknown keys. A manifest without the field yields no `Gates` line.

### Reading `.raven/config.toml`

The emitter needs `template` and `[issue_tracker].platform`. The real parser
(`scripts/raven_lib/config.py`) does not ship, and the shipped prober's
`_codex_mcp_server_names_from_toml` is a section-header scanner that cannot
read key-value pairs.

The emitter therefore carries a minimal reader for exactly these two keys. It
must handle the trailing-comment form that appears in the shipped config:

```text
platform = "github"      # dogfooding: raven repo uses GitHub Issues
```

A naive `split("=")` yields `"github"      # dogfooding...`. The reader strips
inline comments outside quotes, strips quotes, and accepts nothing else. This
is a deliberate, bounded duplication across the shipping boundary — unlike the
gate-tool map, the alternative would be shipping the full installer parser. A
test pins it against the actual shipped `config.toml` text so the two cannot
silently diverge.

The tracker platform-to-CLI mapping (`github` -> `gh`, `gitlab` -> `glab`)
currently exists only as prose in
`common/.agents/skills/raven-tool-bootstrap/SKILL.md:50`; there is no such
mapping anywhere in `scripts/raven_lib/`. The emitter introduces the first
executable copy. It is two entries and belongs with the roster, but the
implementation plan should note it so a future third copy is not created.

### AGENTS.md changes

Removed:

- `, if index configured` from the `mcp__gitnexus__query` and `mcp__gitnexus__impact` rows.
- The bullet: "If a tool named above is not installed, fall back to `rg` plus
  targeted reads and flag the missing capability per Tool Availability Memory."

Added, in the Retrieval Discipline bullets:

- "Tool availability comes from the session capability roster. If no roster is
  present, probe before relying on any non-baseline tool. MCP servers listed as
  configured may still be unapproved or unconnected; a failed call is
  information, not a contradiction of the roster."

The second sentence is load-bearing. The roster reports configuration, not
connectivity, so removing the fallback entirely would convert a
correct-but-cautious agent into a confidently-wrong one — reintroducing
motivation #2 with the recovery instruction deleted.

Retained unchanged: the Tool Availability Memory section, including "If a
SessionStart hook reports missing or unverified tools, ask how to proceed
before relying on them" — now triggered by the roster's `Absent` and
`Unverified` lines, which is why `Unverified` must exist as a distinct bucket.

`common/CLAUDE.md` and each language tree's `AGENTS.md` are symlinks to
`common/AGENTS.md`; one edit covers every template.

### Context cost

The `AGENTS.md` edit is roughly break-even: two hedges and a fallback bullet
out, one longer bullet in. The roster itself is new cost, and it is not free.

At six to ten lines it is small in absolute terms, but the Claude adapter's
SessionStart entry carries no matcher, so it fires on startup, resume, clear,
**and compact** — meaning the roster is re-injected exactly when context
pressure is highest. The Codex adapter matches `startup|resume|clear|compact`
explicitly, with the same effect.

That is the intended trade: the roster is most valuable after a compaction,
when the agent has lost whatever it had inferred about available tooling. But
it argues for keeping the format tight, which is why the byte cap exists, why
`Absent` renders only for tools that are actually absent, and why `Unverified`
is omitted when empty. The format should not grow without a matching argument
for why the added line changes a decision.

### Doctor reconciliation

`raven doctor` grades the 14 CLI tools plus template gate tools
(`scripts/raven_lib/doctor.py:383-455`). The roster additionally reports MCP
servers, tracker CLI, and index freshness. To keep the two from disagreeing,
the roster's categories are defined as a superset of doctor's, and doctor's
findings remain the authority on severity. The implementation plan should add a
test asserting that every tool doctor grades appears in the roster.

## Error Handling

A failure in the roster path must never block session start and must never emit
a traceback into session context. Every failure mode below exits 0.

| Condition | Behavior |
|---|---|
| Repo root not resolvable (no `.git` above cwd or payload) | CLI section still emits; all repo-scoped lines omitted |
| Corrupt cache JSON | `load_memory:279-286` already catches the decode error and returns defaults; only `preferences.doNotRemind` is read from it |
| Valid JSON, wrong shape | `_normalize_memory:260-276` coerces; unchanged |
| `.raven/config.toml` absent or unparseable | `template` and `Tracker` lines omitted |
| Manifest absent or lacking gate tools | `Gates` line omitted |
| `.gitnexus/meta.json` absent, unreadable, or missing expected fields | `Index` line omitted |
| `git rev-parse` or `git status` fails, times out, or repo has no commits | `Index` renders without a staleness verdict |
| Prober module fails to import | Roster emits repo-scoped sections only, with a one-line note |
| A value fails sanitization | Value dropped; a dropped-entry count rendered in its place |
| Any unhandled exception | Caught at top level; nothing printed; exit 0 |

The last row matters most. A hook that crashes noisily on every session start
is worse than the status quo: it costs context every session and trains the
user to ignore hook output.

Note that the earlier draft routed "corrupt cache JSON" through
`_normalize_memory`. That was wrong — corrupt JSON never reaches it, because
`load_memory` catches the decode failure first. The two functions handle
different failures, and with no roster cache the question is nearly moot.

## Testing

Formatting is a pure function from probe results plus repo facts to a string,
testable with fixture data and no subprocess.

**Emitter:**

- Nominal roster renders all sections
- Each section line is omitted when its category is inapplicable
- Required-absent tools render a full `name — purpose` entry; optional-absent
  tools (an `optionalWhen` fallback exists) collapse onto a single name-only
  `Optional` line instead
- `Absent —` still renders when every gap is optional, so "no mandatory
  gaps" stays legible independent of a populated `Optional` line
- `timed_out` results render under `Unverified`, not `Absent`, regardless of
  whether they also carry an `optionalWhen`
- `doNotRemind` suppresses `Absent` and `Unverified` but nothing else
- Gate tools render present/absent state
- Staleness: committed drift, uncommitted drift, both, neither, and
  `git` failure each render correctly
- `meta.json` missing `stats` or with an unexpected `schemaVersion` omits the
  `Index` line rather than rendering placeholders
- Sanitization: an MCP server name containing a newline and a fake section
  header is dropped and counted, not emitted
- Byte cap truncates with an explicit marker
- Repo root resolves from a stdin payload whose `cwd` is outside the worktree
- An unhandled internal error yields empty stdout and exit 0

**Prober:**

- `--session-start` remains accepted and behaves as documented in Migration
- Existing `--write`, `--no-reminder`, `--json`, and human-mode behavior is
  unregressed
- Its functions remain importable by the emitter with an explicit root argument

**Cross-cutting:**

- Adapter parity for the new script, following the existing assertions
- `tests/test_agent_hooks.py`: `EXPECTED_CODEX_LAUNCHER_COUNT` stays 6, but
  `_good_suffixes()` hardcodes
  `".codex/scripts/raven-tool-check.py --session-start"` and
  `find_codex_launcher_drift` asserts the referenced script exists under
  `common/`. Both need updating for the emitter.
- `.raven/config.toml` reader pinned against the real shipped text, including
  the trailing-comment line
- Installer records resolved gate tools on apply and on upgrade
- Every tool `raven doctor` grades appears in the roster

**Dogfooding:** `scripts/self-check.py` exercises apply and upgrade against this
repository, so after implementation this repo's own next session emits a
roster. That is the acceptance signal.

## Migration and Compatibility

**`--session-start` is retained, not removed.** An earlier draft proposed
removing it on the reasoning that only Raven's own hook wiring invokes it. Two
supported configurations break that assumption:

1. **Locally-modified `settings.json`.** `scripts/raven_lib/plan.py:141`
   documents that locally modified Raven-managed files are left untouched on
   upgrade. Adding one team hook to `settings.json` is a likely customization.
   The unmodified `raven-tool-check.py` upgrades; the customized
   `settings.json` does not.
2. **`components.settings = false`**, documented in `.raven/config.toml` as
   "Turn this off if your repository owns Claude settings and will merge hooks
   manually." `scripts` and `settings` are independent booleans.

In both cases a removed flag would produce argparse `SystemExit(2)` and a usage
dump on stderr at every session start, forever, in a repo that did nothing
wrong — while `AGENTS.md` had been edited to say the roster is authoritative
and no roster would ever appear. The same trap applies to a hand-modified
`common/.codex/hooks.json`.

`--session-start` therefore remains, retaining its current behavior, and is
marked deprecated in `--help`. It may be removed no earlier than one minor
release after the emitter ships, and only once the shipped hook wiring no
longer references it anywhere.

Other compatibility notes:

- The cache schema is **unchanged**. With no roster cache there is no `repos`
  map, no version bump, and none of the mixed-install hazard a bump would have
  created: `main()` at line 692 stamps `memory["version"] = 1` on every
  invocation, so an older Raven sharing the machine-global cache would have
  reset a version-2 marker and, under the earlier draft's migration rule,
  silently discarded every repo's cached state.
- Repos installed from an older Raven receive the emitter and the repointed
  hook on their next `raven upgrade`. Until the installer records gate tools in
  their manifest, the roster omits the `Gates` line and is otherwise complete.
- Orphaned-file removal (issue #97) is not engaged: no shipped file is deleted.

## Revision Notes

This spec was rewritten after an adversarial review. The substantive changes:

- **Deleted the cache, lock, detached refresh, and atomic-write refactor.**
  Probing costs 2.7 ms; the machinery defended it at a cost of ~140 ms of extra
  interpreter startup per session. Probing inline is simpler and always current.
- **Retained `--session-start`** rather than removing it, closing a permanent
  session-start break for repos that customize or disable `settings.json`.
- **Corrected fabricated example data.** `pytest` is not a python gate tool
  (`gate_data.py:33` is `["ruff", "pyright"]`); `lsp` is not in the shipped
  `common/.mcp.json` (gitnexus, semble, semgrep only); `.gitnexus/meta.json`
  has no `symbols` field. The earlier examples were written from a local
  environment rather than from shipped data.
- **Fixed the `Absent` line.** The earlier draft claimed the prober persists
  `optionalWhen`. It does not: `_build_tool_records:535-547` stores seven
  fields and that is not among them. Inline probing makes the question moot.
- **Reworked staleness**, which was wrong in both directions when computed from
  `lastCommit` versus `HEAD` alone.
- **Added sanitization**, absent entirely from the earlier draft despite the
  roster interpolating repository-controlled strings into model context.
- **Added the `Unverified` bucket** for the `timed_out` tri-state the earlier
  format dropped.
- **Added explicit repo-root resolution**, replacing an unstated `Path.cwd()`
  assumption that fails under Codex Desktop.
- **Kept an MCP fallback sentence in AGENTS.md**, because configured is not
  connected and the earlier draft's full hedge removal would have made agent
  behavior worse, not better.

## Open Interactions

Issue #143 must be fixed for the roster to reach subagents, but the two changes
are independent and can land in either order. Neither ordering creates a
regression.

One pre-existing bug found during review is tracked separately and is not a
prerequisite: the prober's `Path.cwd()` assumption (#147). The emitter resolves
its own root, so it is unaffected, but the two touch adjacent code.

A second finding from that review — that `common/.mcp.json` omits the `lsp`
server the retrieval ladder names — was filed as #148 and **closed as invalid**.
`common/.mcp.json` never installs; each language tree ships its own `.mcp.json`
with a language-appropriate `lsp` entry, enforced against `LSP_DEFAULTS` in
`tests/helpers.py` by `tests/test_template.py:343-390`. The roster examples
above therefore show `lsp` as present, and any test fixture for this work should
model a language tree's MCP config rather than `common/`.
