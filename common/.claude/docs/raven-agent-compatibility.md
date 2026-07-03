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

## Maintenance Rules

- Keep `AGENTS.md` and `.agents/skills` canonical.
- Keep adapter files as schema translations, not independent policy documents.
- When a Claude and Codex adapter describe the same role, update both in the same Raven change.
- Prefer project config switches over deleting Raven files by hand.
- If a destination project has stronger local guidance, preserve it and merge Raven guidance into the managed block or local agent adapter as appropriate.
