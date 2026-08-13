# Raven Agent Compatibility

Raven keeps one source of truth and adds thin compatibility layers for individual agent clients.

## Canonical Files

These files are agent-neutral and should remain the source of truth:

- `AGENTS.md`: root instructions loaded by compatible agents.
- `.agents/skills/raven-*/`: reusable skills loaded on demand.
- `.claude/docs/raven-*.md`: shared Raven reference documents. The path is Claude-shaped today, but the content is intended to be reusable across agents.

Do not duplicate canonical guidance into agent-specific files unless the target client requires a different schema.

## Claude Code Adapter

Claude-specific files:

- `CLAUDE.md`: compatibility symlink or pointer to `AGENTS.md`.
- `.claude/skills`: compatibility symlink to `.agents/skills`.
- `.claude/agents/raven-*.md`: Claude Code subagents.
- `.claude/hooks/raven-*.py`: Claude Code hook scripts.
- `.claude/rules/raven-*.md`: Claude Code scoped rules.
- `.claude/settings.json`: Claude Code hook wiring.

## Codex Adapter

Codex-specific files:

- `.codex/config.toml`: Codex project config, including subagent concurrency defaults and MCP servers.
- `.codex/agents/raven-*.toml`: Codex custom agents.
- `.codex/hooks.json`: Codex hook wiring.
- `.codex/hooks/raven-*.py`: Codex hook scripts.
- `.codex/rules/raven.rules`: Codex command approval rules.
- `.codex/scripts/raven-*.py`: Codex helper scripts.

Codex reads `.agents/skills` directly, so Raven does not install a `.codex/skills` copy.
Per the Codex skills documentation, "Codex scans `.agents/skills` in every directory from
your current working directory up to the repository root," loading each subdirectory that
contains a `SKILL.md` with `name` and `description` frontmatter — the exact shape Raven
ships at `.agents/skills/raven-*/SKILL.md`. The canonical skills are therefore live for
Codex, not inert files, and the shared `AGENTS.md` can safely instruct both harnesses to
invoke `raven-*` skills.

- Source: <https://developers.openai.com/codex/skills>
- Last verified: 2026-07-02 (Codex CLI skills GA; feature present in the 2026-06-22
  changelog, v0.142.0). Re-verify against the source if this ages past the doc-freshness
  window in `scripts/self-check.py`.

## Adapter File Classification

Every file that exists under both `.claude/` and `.codex/` falls into one of three
categories. Check this table before "fixing" an apparent inconsistency between the two
trees — all three are deliberate.

| Category | Meaning | Files |
|---|---|---|
| **Byte-identical (unified)** | One real file under `common/.claude/`; the `.codex/` path is a template-internal symlink to it. Nothing to keep in sync. | `scripts/raven-capability-roster.py`, `scripts/raven-session.py`, `scripts/raven-skeleton.py`, `scripts/raven-tool-check.py`, `hooks/raven-post-bash-summarize.py`, `hooks/raven-post-edit-format.py`, `hooks/raven-pre-bash-guard.py`, `hooks/raven-pre-edit-guard.py`, `hooks/raven-session-checkpoint.py` (computes its own adapter directory at runtime, same pattern as `raven-tool-check.py`, instead of hardcoding one — issue #195) |
| **Schema-translated** | Same role, different file format required by the harness. Not comparable line-by-line. | `.claude/agents/raven-*.md` ↔ `.codex/agents/raven-*.toml`; `.claude/settings.json` ↔ `.codex/hooks.json`; `.claude/rules/raven-security.md` ↔ `.codex/rules/raven.rules`; `.claude/skills` symlink ↔ Codex reading `.agents/skills` directly |
| **Intentionally asymmetric** | Exists for one harness only, because the underlying capability does not exist in the other. See Known Asymmetries below. | `.claude/hooks/raven-skeleton-read-guard.py` (Claude-only); `.codex/config.toml` (Codex-only) |

### How the unified files stay unified

The `.codex/` entries are symlinks spelled to climb back in through `common/`, e.g.
`common/.codex/scripts/raven-session.py -> ../../../common/.claude/scripts/raven-session.py`.

That spelling is load-bearing. `should_preserve_symlink` in `scripts/raven_lib/template.py`
dereferences a symlink — copying real content into the destination — only when its target
matches `(\.\./)+common/`. Any other spelling is preserved *as a symlink* at the
destination. Because `.claude/scripts` and `.codex/scripts` are independently toggleable
components (`[components.claude] scripts = false`), a destination-level link from one
adapter into the other would dangle in exactly the configuration that most needs those
files — a Codex-only install. The shorter `../../.claude/scripts/<name>` resolves to the
same file in the repo and is therefore an easy "simplification" to make by mistake; it is
wrong. Tests in `tests/test_claude_script_symlinks.py` pin both the spelling and the
dereference behavior, and `tests/test_apply.py` installs a Claude-disabled destination to
prove real files arrive.

Consequently these links never reach a destination, so `.raven/manifest.json` records the
installed files as `KIND_FILE`, not `KIND_SYMLINK`. `KIND_SYMLINK` remains correct for
links that are *meant* to reach a destination, such as `CLAUDE.md` and `.claude/skills`.
This also means the unification needs no symlink support on the destination platform:
a destination never receives one of these links.

Runtime-derived adapter identity: because one file serves both harnesses, a unified script
cannot embed its own adapter directory as a literal. `raven-tool-check.py` derives it from
its install layout (`_adapter_directory_from_install_layout`) for both the project root and
the directory named in `--help` and remediation text. Deliberately *not* symlink-resolving:
adapter identity follows the path the script was invoked through, not where its bytes live.

### Why `.codex/hooks.json` repeats its launcher six times

It cannot be hoisted into a shared file, and this has already been tried. Codex can invoke
a hook with a process cwd outside the project, so the launcher must parse the JSON payload
on stdin to find the project root *before* any relative path resolves — which means no
relative path to a shim script resolves either, and Codex offers no project-directory
variable (`$CLAUDE_PROJECT_DIR` is Claude-only, which is why Codex needs the expression at
all). Commit `aa4ec79` replaced a `git rev-parse` wrapper with the inline expression for
exactly this reason. The six copies are therefore irreducible without generating
`hooks.json` at install time; the drift guard in `tests/test_agent_hooks.py` makes a missed
copy fail loudly instead. Do not re-file this as duplication to clean up.

## Known Asymmetries

Some Claude adapter files intentionally have no Codex counterpart because the underlying
agent capability does not exist in Codex, not because of an oversight. Recorded here so
audits don't re-flag them:

- **`.claude/hooks/raven-skeleton-read-guard.py`** (the rung-2 skeleton-first read gate,
  wired to the `Read` matcher in `.claude/settings.json`) has no `.codex/hooks/`
  counterpart and no entry in `.codex/hooks.json`. Codex has no discrete, universally
  matchable `Read` tool — its `PreToolUse` hook coverage is `Bash`, `apply_patch`, and MCP
  calls only, so there is nothing to gate the same way. See
  `docs/research/hook-read-interception.md` for the capability comparison and
  `docs/superpowers/plans/2026-06-18-skeleton-first-reads.md` for the decision to keep
  Codex at advisory guidance (rung 0/1) instead of a deny gate.

  Unifying the byte-identical hook scripts must not sweep this one along: giving it a
  `.codex/hooks/` counterpart would wire a gate Codex cannot fire. Its continued absence is
  asserted by `test_deliberately_unlinked_codex_hooks_stay_real_files`, so the asymmetry
  fails loudly if it is ever erased by a well-meaning cleanup rather than a decision.

## Maintenance Rules

- Keep `AGENTS.md` and `.agents/skills` canonical.
- Keep adapter files as schema translations, not independent policy documents.
- When a Claude and Codex adapter describe the same role, update both in the same Raven change.
- Check the classification table first. A **unified** file is edited once, under
  `common/.claude/`; a **path-transformed** file must be edited in both trees. Adding a
  new adapter file means classifying it — and if it is byte-identical, unifying it.
- Prefer project config switches over deleting Raven files by hand.
- If a destination project has stronger local guidance, preserve it and merge Raven guidance into the managed block or local agent adapter as appropriate.
