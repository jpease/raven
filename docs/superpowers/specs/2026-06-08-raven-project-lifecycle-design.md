# Design: raven-project-lifecycle

**Date:** 2026-06-08  
**Status:** Approved  

## Summary

Add a lightweight, optional project lifecycle skill to Raven. Users who want heavy-duty lifecycle orchestration (phased requirements, NFR design, approval workflows, audit logs) should use AI-DLC or equivalent. Users who want something built in get this.

The skill scopes, tracks, and delegates. It never touches code directly.

---

## Context and Motivation

AI-DLC (awslabs/aidlc-workflows) is a comprehensive lifecycle orchestration framework that complements Raven well. Raven handles execution quality (hooks, tool selection, code intelligence, language-specific rules). AI-DLC handles project lifecycle (Inception → Construction → Operations phases, session state, audit trails).

For users who don't want AI-DLC, Raven currently has no answer for multi-session, multi-unit tasks. Without lifecycle scaffolding, agents context-bleed across large tasks and lose state between sessions.

This feature fills that gap with a deliberately narrow scope.

---

## Design Decisions

- **Not a replication of AI-DLC.** No requirements analysis, NFR design stages, architecture documents, or approval workflows. Those are AI-DLC's lane.
- **Optional.** Users who don't invoke the skill get exactly what they have today.
- **Additive only.** No changes to existing Raven skills, hooks, or docs.
- **Single-orchestrator model.** Designed for one agent running units sequentially. Parallel-agent workflows (`superpowers:dispatching-parallel-agents`) should not share a session.

---

## New Artifacts

```
.agents/skills/raven-project-lifecycle/
    SKILL.md

.agents/skills/raven-github-issues/
    SKILL.md                           (generalized from personal skill; requires gh CLI)

.agents/skills/raven-gitlab-issues/
    SKILL.md                           (mirrors GitHub version; requires glab CLI)

scripts/
    raven-session.py

.claude/hooks/
    raven-session-checkpoint.py
.codex/hooks/
    raven-session-checkpoint.py        (copied, not symlinked)

.raven/
    config.toml                        (Raven-wide feature config, tracked)
    session.md                         (per-project state, gitignored)
    session.lock                       (transient, never committed)
    session-archive.md                 (completed unit history, gitignored)
```

`raven-namespace.md` is updated to claim `.raven/` as Raven-owned.

---

## Skill: `raven-project-lifecycle`

**Location:** `.agents/skills/raven-project-lifecycle/SKILL.md`

### Skip When
- The task is a single unit of work completable in one session with no context-loss risk
- The user has already scoped and decomposed the work explicitly
- The task is a one-off fix, doc change, or isolated refactor

### Phase 1 — Workspace Detection
1. Check for existing `.raven/session.md` — if found, display resume summary and jump to Phase 3
2. If new session: scan for brownfield signals (source files, existing deps, configs, git history)
3. Classify greenfield vs brownfield
4. If brownfield: invoke `raven-codebase-discovery` to build architecture context before scoping

### Phase 2 — Scoping
1. Decompose work into ordered, named units — each should be completable in a single session
2. Call `python scripts/raven-session.py --init <project-type> <unit-1> <unit-2> ...`
3. Present the unit plan to the user and wait for confirmation before proceeding

### Phase 3 — Execution Loop *(repeats per unit)*
1. Read current unit from session state (`python scripts/raven-session.py --status`)
2. Select the appropriate Raven execution skill:
   - New behavior → `raven-implement-feature`
   - Structure change → `raven-safe-refactor`
   - Test coverage → `raven-write-tests`
   - Broken behavior → `raven-debug-failure`
3. Execute that skill for the unit
4. Call `python scripts/raven-session.py --complete <unit-name>` — hook validates before allowing
5. Advance to next unit

### Phase 4 — Wrap-up
1. Call `python scripts/raven-session.py --status` to confirm all units complete
2. Summarize changes across all units
3. Suggest natural next steps (PR, review, deploy)

---

## Script: `raven-session.py`

**Location:** `scripts/raven-session.py`

### Commands

| Command | Behavior |
|---|---|
| `--init <type> [--parent <n>] <unit...>` | Create `.raven/session.md`. If `--parent` is given and a platform is configured, create child issues via `gh`/`glab` and record their numbers in `session.md`. Fails if session already exists. |
| `--complete <unit-name>` | Mark unit done, advance current pointer, update timestamp. If a child issue number is recorded for this unit, close it via `gh`/`glab`. |
| `--status` | Print current unit, completed units, remaining units, and parent issue if set. |
| `--validate <unit-name>` | Exit 0 if valid to complete; exit 1 + message if not. Called by hook only. |
| `--archive` | Move completed units to `session-archive.md`, reset units list for next phase. User-triggered: agent surfaces the suggestion when the context cap warning fires, but waits for confirmation before running. |

### Invariants
- Script is the **only** process that reads or writes `session.md`. The skill and hook never access the file directly.
- All writes are atomic: write to `.raven/session.tmp`, then rename to `session.md`.
- Script warns (but does not fail) if the `## Context` block exceeds ~50 lines.

### Lockfile Protocol
- Script creates `.raven/session.lock` containing `<PID>\n<ISO-timestamp>` before any write.
- On encountering an existing lock:
  1. Check if the PID in the lockfile is alive
  2. **Dead PID** → stale lock, remove silently, proceed
  3. **Live PID** → retry 3 times with 200ms delay
  4. Still locked → exit 1: `"Session locked by PID <X>. Another agent may be running. If not, delete .raven/session.lock manually."`
- Lock is removed after every write (success or failure).

---

## State File: `.raven/session.md`

**Gitignored.** Users who want to commit session state remove the ignore entry manually.

**Without a parent issue** (local units only):

```markdown
# Raven Session

**Project Type:** brownfield  
**Started:** 2026-06-08T21:00:00Z  
**Last Updated:** 2026-06-08T22:30:00Z  

## Units

- [x] add-auth-middleware (completed 2026-06-08T21:45:00Z)
- [ ] write-auth-tests (current)
- [ ] update-api-docs

## Context

Key facts to preserve across sessions — architecture decisions, 
constraints discovered during brownfield analysis, anything that 
would otherwise be re-derived cold.
```

**With a parent issue** (`--parent 123`, `platform = "github"`):

```markdown
# Raven Session

**Project Type:** brownfield  
**Started:** 2026-06-08T21:00:00Z  
**Last Updated:** 2026-06-08T22:30:00Z  
**Parent Issue:** #123 (github)

## Units

- [x] add-auth-middleware → #124 (completed 2026-06-08T21:45:00Z)
- [ ] write-auth-tests → #125 (current)
- [ ] update-api-docs → #126

## Context

Key facts to preserve across sessions — architecture decisions, 
constraints discovered during brownfield analysis, anything that 
would otherwise be re-derived cold.
```

Parsed with simple string matching. The `## Units` block is fully script-managed. The `## Context` section is human-maintained; the script never modifies it. Child issue numbers (e.g. `→ #124`) are written by `--init` and read by `--complete` to close the corresponding issue.

---

## Hook: `raven-session-checkpoint.py`

**Location:** `.claude/hooks/raven-session-checkpoint.py` and `.codex/hooks/raven-session-checkpoint.py` (copied, not symlinked — symlinks are unreliable on Windows)

**Trigger:** `PreToolUse` on Bash commands matching `raven-session\.py --complete`

### Execution Flow

```
1. Read .raven/config.toml
   └─ lifecycle.checkpoint_enforcement = false → exit 0 (no-op)

2. Check .raven/session.md exists
   └─ missing → exit 1: "No session active. Run --init first."

3. Parse unit name from intercepted command

4. Call: python scripts/raven-session.py --validate <unit-name>
   └─ exit 0 → allow (hook exits 0)
   └─ exit 1 → block, surface error message from script
```

The hook never reads `session.md` directly. All state knowledge lives in the script.

### `--validate` checks (inside the script)
- `session.md` is well-formed (has `## Units` block with at least one current unit)
- Unit name matches the declared current unit
- Unit is not already marked `[x]`
- No stale lock (handled by lockfile protocol above)

### `hooks.json` additions (same pattern for `.claude/` and `.codex/`)

```json
{
  "matcher": "raven-session\\.py --complete",
  "hooks": [{
    "type": "command",
    "command": "python .claude/hooks/raven-session-checkpoint.py",
    "timeout": 10,
    "statusMessage": "Validating session checkpoint"
  }]
}
```

---

## Config: `.raven/config.toml`

**Tracked in git.** Shipped as part of Raven's template library.

```toml
[lifecycle]
checkpoint_enforcement = true

[issue_tracker]
# Controls which external issue tracker this project uses.
# This is independent of local session tracking (governed by [lifecycle] above).
#
# platform = "github"   # use raven-github-issues + gh CLI
# platform = "gitlab"   # use raven-gitlab-issues + glab CLI
platform = "none"        # no external issue tracker
```

### `[lifecycle]`

Read by both hook scripts at runtime. Setting `checkpoint_enforcement = false` makes the hook a no-op; the skill still works but checkpoint enforcement becomes instructional only (same level as AI-DLC).

### `[issue_tracker]`

Describes which **external** issue tracker the project uses. This is orthogonal to local session tracking — a project can have `platform = "github"` and still use `raven-project-lifecycle` locally, or have `platform = "none"` and use neither.

| Value | Meaning | Required CLI |
|---|---|---|
| `"github"` | Project uses GitHub Issues; activate `raven-github-issues` | `gh` |
| `"gitlab"` | Project uses GitLab issues; activate `raven-gitlab-issues` | `glab` |
| `"none"` | No external issue tracker | — |

`raven-tool-bootstrap` checks for the required CLI based on this value. The `raven-github-issues` and `raven-gitlab-issues` skills check this value at invocation and ask for confirmation before proceeding if a different platform is configured. The `raven-project-lifecycle` skill reads this value only to include the right pointer in its positioning text.

---

## Issue-Tracker Workflow Skills

### `raven-github-issues`

Generalized from an existing personal skill. Minimal changes from the source:

- The "competing local task system" line is updated to: "If your project uses `raven-project-lifecycle` for local session tracking, treat them as complementary — `raven-project-lifecycle` manages local execution state while this skill manages external issue visibility."
- Adds a check at invocation: if `[issue_tracker].platform` is not `"github"`, warn the user and ask for confirmation before proceeding (not a hard block — user may be switching platforms or overriding).
- `raven-tool-bootstrap` checks for `gh` CLI when platform is `"github"`.

**Integration with `raven-project-lifecycle`:**

When `--parent <n>` is passed to `raven-session.py --init`, the script creates child issues under the parent. Child issue numbers are stored in `session.md` and closed automatically by `--complete`.

GitHub sub-issues require `gh` CLI v2.49+. The script checks the installed version at `--init` time:
- v2.49+: creates true sub-issues via `gh issue create --parent <n>`
- older: falls back to adding a task-list checkbox in the parent issue body and creates standalone linked issues

### `raven-gitlab-issues`

Mirrors `raven-github-issues` with GitLab-specific adaptations:

- Uses `glab` CLI instead of `gh`
- "merge requests" instead of "pull requests"
- GitLab issue commands: `glab issue list`, `glab issue view <n>`, `glab issue note <n> -m "..."`, `glab issue create`, `glab issue update`, `glab issue close <n>`
- Same workflow, execution rules, and heuristics as the GitHub version
- Adds a check at invocation: if `[issue_tracker].platform` is not `"gitlab"`, warn and ask for confirmation before proceeding (not a hard block)
- `raven-tool-bootstrap` checks for `glab` CLI when platform is `"gitlab"`

**Integration with `raven-project-lifecycle`:**

When `--parent <n>` is passed to `raven-session.py --init`, the script creates child issues using `glab issue create --parent-id <n>`. GitLab's parent-child issue relationship is stable — no version fallback required.

---

## Positioning

`raven-project-lifecycle` ships with positioning text that adapts to the configured platform:

- `platform = "github"`: appends "This project uses GitHub Issues — for issue-driven execution, use `raven-github-issues` alongside or instead of this skill."
- `platform = "gitlab"`: appends "This project uses GitLab issues — for issue-driven execution, use `raven-gitlab-issues` alongside or instead of this skill."
- `platform = "none"`: no issue-tracker mention appended.

For heavy-duty lifecycle orchestration (phased requirements, NFR design, structured approval workflows), AI-DLC or an equivalent tool is the right choice. Raven's lifecycle skill is the lightweight local-first alternative.

---

## What This Does Not Change

- All existing Raven skills, hooks, docs, and templates are unchanged
- No new dependencies beyond optional `gh` / `glab` CLIs (checked by `raven-tool-bootstrap`)
- `raven.py` installer: install new skills, hook scripts, and `.raven/config.toml` template as standard managed files
- `raven-namespace.md`: add `.raven/` as Raven-owned namespace
