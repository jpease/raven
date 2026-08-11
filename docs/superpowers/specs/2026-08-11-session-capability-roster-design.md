# Design: Session Capability Roster

Date: 2026-08-11
Status: Approved design, pending implementation plan

## Summary

Raven already probes recommended tooling at session start, but the result never
reaches the agent. This design splits the existing tool check into a **prober**
and an **emitter**, and has the emitter print a compact capability roster into
session context on every session start.

The roster covers CLI tools, configured MCP servers, the active template's gate
tools, the issue-tracker CLI, and code-intelligence index freshness. It is
served from cache so it never blocks session start, and refreshed by a detached
background process.

`AGENTS.md` then defers to the roster as the source of truth for tool
availability, shedding the hedging language it currently carries.

## Motivation

`common/.claude/scripts/raven-tool-check.py` probes 14 tools and persists the
result to `~/.raven/tool-memory.json`. It is wired as a SessionStart hook in
both the Claude Code and Codex adapters, and `raven doctor` re-runs it on
demand via `toolchain_findings`.

Three defects make that machinery nearly inert in practice.

### 1. Silent degradation

Nothing reads the cache back into session context. The agent knows the
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
self-correcting, so it matters less than (1), but it is the same root cause.

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
  diagnostic. The roster is a passive per-session fact sheet.
- **Probing tool health beyond presence.** The roster answers "is it here and
  is the index current", not "does it work correctly".

## Design

### Components

| Component | Change |
|---|---|
| `raven-tool-check.py` (x2 adapters) | Remains the **prober**. `--session-start` retires in favor of `--refresh`: probe everything, write cache, print nothing. `--write`, `--no-reminder`, `--clear-no-reminder`, `--json`, and human mode are unchanged. |
| `raven-capability-roster.py` (x2 adapters, new) | The **emitter**. Reads cache, formats the roster, writes it to stdout, spawns the refresh. Flags: `--no-refresh`, `--json`. |
| `common/.claude/settings.json`, `common/.codex/hooks.json` | SessionStart repointed from the prober to the emitter. |
| `scripts/raven_lib/` installer, `.raven/manifest.json` | Installer resolves the active template's gate tools at apply/upgrade time and records them in the manifest. |
| `common/AGENTS.md` | Retrieval ladder defers to the roster; hedging removed. |

The prober and emitter are separate scripts because they have different
lifetimes and different test shapes. Probing needs subprocesses, a network of
config lookups, and a writable cache. Formatting is a pure function from a
cache dictionary to a string. Splitting them makes the format — the part most
likely to need iteration — testable without a subprocess.

Both adapters get their own copy of the new script. The existing
`.claude/` and `.codex/` copies of `raven-tool-check.py` are regular files with
differing content, not symlinks; they diverge in the paths embedded in help
text and prompts. The new script follows that established convention.

### Cache schema (version 2)

CLI tool availability is machine-global. Template, gate tools, tracker, and
index health are per-repository. Rather than write a new file into the
destination repo — which would add gitignore and upgrade surface — the existing
machine-global cache gains a `repos` map keyed by absolute repository path:

```jsonc
{
  "version": 2,
  "tools":       { /* machine-global CLI results; v1 shape unchanged */ },
  "preferences": { /* v1 shape unchanged */ },
  "repos": {
    "<absolute-repo-path>": {
      "template": "python",
      "gateTools": { "ruff": true, "pyright": true, "pytest": true },
      "mcpServers": ["gitnexus", "semble", "lsp", "semgrep"],
      "tracker": {
        "platform": "github",
        "cli": "gh",
        "available": true,
        "version": "2.62.0"
      },
      "index": {
        "tool": "gitnexus",
        "indexedAt": "2026-08-08T12:00:00+00:00",
        "lastCommit": "abc1234",
        "symbols": 2643
      },
      "checkedAt": "2026-08-11T20:00:00+00:00"
    }
  }
}
```

`RAVEN_TOOL_MEMORY` continues to override the cache location, so tests remain
isolated. A version-1 cache migrates by reading `tools` and `preferences`
unchanged and initializing `repos` to an empty object; no data is discarded and
no user-visible migration step is required.

The cache stores only facts about the index itself — `indexedAt`, `lastCommit`,
and symbol count, all read from `.gitnexus/meta.json` without invoking
GitNexus. It deliberately does **not** store a staleness verdict.

Staleness is computed by the emitter at emit time, comparing the cached
`lastCommit` against the repository's current `HEAD`. Caching the verdict would
be wrong: `HEAD` moves whenever the user commits, so a verdict written by the
previous session's refresh goes stale within minutes of any commit — precisely
the situation the marker exists to catch. The emitter therefore pays one
`git rev-parse HEAD` per session, which is cheap and always correct.

### Refresh lifecycle

Session start never blocks on probing.

- **Warm cache** — emit the roster from cache, then spawn a detached
  `--refresh`. Emission is a file read and a string format.
- **Cold cache** — run the cheap probes inline, emit a partial roster, and
  spawn the detached refresh for the rest. "Cheap" means anything that costs no
  subprocess: `shutil.which` presence checks in a thread pool, plus the file
  reads for MCP server names (`.mcp.json`, Codex `config.toml`), template and
  tracker platform (`.raven/config.toml`), gate tool names
  (`.raven/manifest.json`), and index metadata (`.gitnexus/meta.json`).
  Deferred to the refresh: everything requiring a subprocess, which is version
  strings and any probe run under `RAVEN_TOOL_CHECK_EXECUTE=1`. A first session
  therefore gets a roster that is complete except for version numbers, at
  single-digit-millisecond cost and without a blocking probe.

The single exception to the no-subprocess rule is the emitter's
`git rev-parse HEAD`, which runs on every session — warm or cold — because
index staleness cannot be cached correctly (see above). It is one process
invocation against the local object store and is bounded by a short timeout;
on failure the `Index` line renders without a staleness verdict.
- **`--write`** — the `raven-tool-bootstrap` path taken after a user installs
  tools. This runs a synchronous full probe so a fresh install takes effect
  immediately rather than one session later.

The steady-state consequence is that the roster reflects the world as of the
previous session. That is acceptable for presence facts, which change rarely
and only through deliberate user action, and `--write` covers the one case
where the user just changed them on purpose.

### Roster format

Written to stdout by the emitter; SessionStart hook stdout is injected as
session context by both adapters. Nominal case:

```
=== RAVEN CAPABILITIES ===  probed 2026-08-11 · template: python
  CLI      rg fd just jq yq rtk ast-grep semgrep gitleaks osv-scanner uvx
  MCP      gitnexus semble lsp semgrep
  Gates    ruff pyright pytest
  Tracker  gh 2.62.0
  Index    gitnexus · 2643 symbols · current with HEAD
  Absent   —
```

Degraded case:

```
=== RAVEN CAPABILITIES ===  probed 2026-08-11 · template: python
  CLI      rg fd just jq yq rtk ast-grep gitleaks uvx
  MCP      gitnexus lsp
  Gates    ruff pyright pytest
  Tracker  gh 2.62.0
  Index    gitnexus · 2643 symbols · STALE (indexed abc1234, HEAD def5678)
  Absent   semgrep — structural rules; fall back to ast-grep
           osv-scanner — optional here: advisories covered by Dependabot
```

Format rules:

- A section line is omitted entirely when its category is not applicable — no
  `Tracker` line when `[issue_tracker].platform` is unset, no `Index` line when
  no index metadata is readable, no `Gates` line when the manifest carries no
  resolved gate tools.
- `Absent` distinguishes genuinely-missing tools from tools whose
  `optionalWhen` condition is satisfied. The prober already records
  `optionalWhen`; the roster renders it as the trailing clause.
- `Absent —` on a fully-provisioned machine is deliberate. Its presence
  confirms the roster ran and found nothing missing, which is a different fact
  from the roster having been suppressed.
- The `STALE` marker on `Index` exists because `CLAUDE.md` makes GitNexus
  impact analysis mandatory before symbol edits. A stale index makes that check
  quietly wrong, and nothing currently surfaces it.
- When `preferences.doNotRemind` is set, the `Absent` line is suppressed but
  the rest of the roster still emits. The preference means "stop nagging me
  about installing things", not "stop telling me what I have".

  This is a **display-only** rule, and it is the one place the implementation
  is most likely to go wrong. The retiring `--session-start` mode returns early
  when `doNotRemind` is set, skipping the probe entirely. `--refresh` must not
  inherit that behavior: it always probes and always writes the cache, because
  the roster's available-tool lines depend on fresh data regardless of the
  user's reminder preference. Only the emitter consults `doNotRemind`, and only
  to decide whether to render the `Absent` line.

### Gate-tool data across the shipping boundary

`scripts/raven_lib/` is installer-side and does not ship. Destination repos
receive three standalone scripts under `.claude/scripts/`, each self-contained.
The template-to-gate-tools map lives in `scripts/raven_lib/data/gate_data.py`
and is therefore unreachable from the shipped emitter.

`.raven/config.toml` does ship and already carries `template` and
`[issue_tracker].platform`, so those two facts need no new plumbing. Gate tools
do. Three options were considered:

1. Duplicate the map into the shipped script. Rejected: two sources of truth,
   drifting silently.
2. Infer gate tools from the shipped justfile recipes. Rejected: indirect and
   brittle against recipe renames.
3. Have the installer resolve `GATE_DATA[template].tools` at apply/upgrade time
   and record the result in `.raven/manifest.json`. **Selected.**

Option 3 keeps `GATE_DATA` as the single source of truth and gives the shipped
emitter a derived artifact to read. It matches the manifest's documented role
as machine-written install and upgrade state, and it means a template's gate
tools change only through a Raven upgrade — which is already the moment the
rest of that template's content changes.

The prober probes each recorded gate tool for presence; the emitter renders
them. A manifest without the new field (written by an older Raven) yields no
`Gates` line rather than an error.

### AGENTS.md changes

The retrieval ladder becomes authoritative, with a single fallback sentence
covering the cases where no roster exists — subagents, Codex installs without
the adapter, cold cache, and hook failure.

Removed:

- `, if index configured` from the `gitnexus_query` and `gitnexus_impact` rows.
- The bullet: "If a tool named above is not installed, fall back to `rg` plus
  targeted reads and flag the missing capability per Tool Availability Memory."

Added, in the Retrieval Discipline bullets:

- "Tool availability comes from the session capability roster. If no roster is
  present, probe before relying on any non-baseline tool."

Retained unchanged: the Tool Availability Memory section, including "If a
SessionStart hook reports missing or unverified tools, ask how to proceed
before relying on them" — now triggered by the roster's `Absent` line rather
than by a one-time prompt.

Net token change in `AGENTS.md` is approximately break-even. The gain is
accuracy, not size.

## Error Handling

The governing rule: a failure in the roster path must never block session start
and must never emit a traceback into session context. Every failure mode below
results in exit code 0.

| Condition | Behavior |
|---|---|
| Corrupt cache JSON | `_normalize_memory` extends to cover v2 and `repos`; falls through to the cold-cache path |
| Version-1 cache | `tools` and `preferences` read unchanged; `repos` initialized empty |
| Detached spawn fails | Swallowed; the roster still emits from cache |
| `.raven/config.toml` absent or unparseable | Repo-scoped sections omitted; CLI section still emits |
| Manifest absent or lacking gate tools | `Gates` line omitted |
| `.gitnexus/meta.json` absent or unreadable | `Index` line omitted; not treated as an error |
| `git rev-parse HEAD` fails | `Index` renders without a staleness verdict |
| Refresh lock held | Spawn skipped for this session |
| Any unhandled exception in the emitter | Caught at top level; nothing printed; exit 0 |

The last row matters most. A hook that crashes noisily on every session start
is worse than the status quo, because it costs context on every single session
and trains the user to ignore hook output.

## Concurrency

Multiple sessions opening simultaneously would otherwise each spawn a refresh
and race on the cache write. Two mitigations:

- **Atomic writes.** `save_memory` currently calls `write_text` directly. It
  moves to a write-temp-then-`os.replace` pattern so a concurrent reader never
  observes a partial file.
- **Refresh lock.** A refresh acquires a lock file under `~/.raven/` before
  probing. If the lock is held and not stale, the spawning session skips the
  refresh rather than queuing one. Stale locks — older than a fixed timeout —
  are reclaimed, so a killed refresh cannot wedge the mechanism permanently.

Detached spawning is platform-specific: `start_new_session=True` on POSIX,
`DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP` on Windows. Both redirect stdout
and stderr to devnull so a refresh cannot write into a later session's context.

## Testing

Splitting the emitter from the prober makes roster formatting a pure function,
testable with a fixture cache and no subprocess. That is the primary test win
and it is currently impossible.

**Emitter (new tests):**

- Warm cache renders the nominal roster
- Cold cache renders a partial roster and requests a refresh
- Corrupt cache falls through to the cold path without raising
- Version-1 cache migrates without data loss
- Absent-required versus absent-optional render differently
- Stale versus current index render differently
- Staleness tracks current `HEAD`, not a cached verdict: an unchanged cache
  plus a moved `HEAD` renders `STALE`
- `git rev-parse` failure renders `Index` without a staleness verdict
- Each section line is omitted when its category is inapplicable
- `doNotRemind` suppresses `Absent` but not the rest of the roster
- `--no-refresh` emits without spawning
- An unhandled internal error yields empty stdout and exit 0

**Prober (extend `tests/test_tool_check.py`):**

- `--refresh` writes the cache and prints nothing
- `--refresh` probes and writes even when `doNotRemind` is set, unlike the
  `--session-start` mode it replaces
- Gate tools, MCP servers, tracker CLI, and index metadata populate the `repos`
  entry
- Existing `--write`, `--no-reminder`, and `--json` behavior is unregressed

**Cross-cutting:**

- Adapter parity: both copies of each script stay in sync modulo their embedded
  path strings, following the existing parity assertions
- Hook wiring: `tests/test_agent_hooks.py` asserts SessionStart targets the
  emitter in both `settings.json` and `hooks.json`
- Installer: the manifest gains resolved gate tools on apply and on upgrade
- Concurrency: two simultaneous refresh attempts leave a valid cache; a stale
  lock is reclaimed

**Dogfooding:** `scripts/self-check.py` exercises apply and upgrade against this
repository, so after implementation this repo's own next session emits a roster.
That is the acceptance signal.

## Migration and Compatibility

- Existing version-1 caches are read without user action.
- Repos installed from an older Raven receive the emitter and the repointed
  hook on their next `raven upgrade`. Until the installer records gate tools in
  their manifest, the roster omits the `Gates` line and is otherwise complete.
- `--session-start` is removed rather than deprecated. It is invoked only from
  Raven's own hook wiring, which is updated in the same change; no downstream
  repo is expected to call it directly. `raven doctor` continues to use
  `--json`, which is unchanged.
- Orphaned-file removal (issue #97) handles retiring nothing here — no file is
  deleted; the prober is modified in place and the emitter is added.

## Open Interactions

Issue #143 must be fixed for the roster to reach subagents, but the two changes
are independent and can land in either order. If #143 lands first, subagents
gain MCP access but still lack availability information. If this design lands
first, main-session agents gain the roster while subagents keep the current
behavior. Neither ordering creates a regression.
