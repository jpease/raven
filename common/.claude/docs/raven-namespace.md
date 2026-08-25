# Raven Namespace

Raven-owned files use the `raven-*` namespace wherever the host tool allows it. This leaves destination repositories free to use ordinary names for project-specific guidance without causing update conflicts.

## Raven-Owned Paths

These paths are owned by the Raven template:

- `.agents/skills/raven-*/`
- `.claude/rules/raven-*.md`
- `.claude/docs/raven-*.md`
- `.claude/agents/raven-*.md`
- `.claude/hooks/raven-*.py`
- `.claude/scripts/raven-*.py`
- `.codex/agents/raven-*.toml`
- `.codex/hooks/raven-*.py`
- `.codex/rules/raven.rules`
- `.codex/scripts/raven-*.py`
- `.raven/config.toml` (feature flags and platform config; tracked in git)
- `.raven/session.md` (gitignored; per-project lifecycle state)
- `.raven/session.lock` (transient; never committed)
- `.raven/session-archive.md` (gitignored; completed unit history)

These integration files are also template-managed, but they cannot be fully namespaced because agents and tools expect these names:

- `AGENTS.md`
- `CLAUDE.md`
- `.mcp.json`
- `.claude/settings.json`
- `.codex/config.toml`
- `.codex/hooks.json`

`.claude/settings.json` is fully Raven-owned like any other managed file: it upgrades in place with no guided merge, even when a pre-existing hand-written copy needs one-time adoption consent first (`raven install --adopt-settings-json`). `.claude/settings.local.json` is the user's own local-overrides layer and is never touched or shipped by Raven. `.mcp.json`, by contrast, is explicitly **not** owned this way -- a pre-existing copy stays on the guided-merge path (`.raven/merge/`) like any other file Raven does not track.

`.gitattributes` is a third shape, neither of the above: append-only, never whole-file owned or guided-merged (#206). Most destination repos already have their own `.gitattributes` for reasons unrelated to Raven (binary handling, diff drivers, language-specific normalization), so overwriting it wholesale the way `.claude/settings.json` is overwritten would destroy pre-existing content -- but routing a pre-existing copy through the guided-merge path the way `.mcp.json` is would force a manual merge for a file that is safe to reconcile automatically. Instead, `blocks.ensure_gitattributes_lines` reads the required `eol=lf` lines straight from the shipped `common/.gitattributes` template and appends only the ones missing from the destination's own `.gitattributes`, under a Raven-labeled comment header, on every install and upgrade -- never touching, reordering, or removing a line it did not add. `common/.gitattributes` itself is excluded from the normal template walk (`MERGE_ONLY_TEMPLATE_PATHS` in `constants.py`) so it can never become an ordinary `will_copy`/`will_upgrade` entry by accident.

`.ignore` is merged the same append-only way, by `blocks.ensure_ignore_lines`, and is in the same `MERGE_ONLY_TEMPLATE_PATHS` set (#238). It carries one negation per directory Raven installs guidance into — `.agents/`, `.claude/`, `.codex/`, `.raven/` — because ripgrep, fd and ast-grep share the `ignore` crate and skip a dot-directory unless something un-hides it, so without the file an installed project cannot search its own instructions with the tools this repository's retrieval ladder names first. Every shipped line begins with `!`, and a negation can only un-ignore, so the merge cannot hide a path the destination was searching before Raven arrived. Unlike `.gitattributes`, the merge is not gated on a component: the four directories span every component, and `.raven/` exists in any installation. The one destination skipped entirely is the home directory itself, where `.claude/` holds Claude Code's runtime state -- transcripts, job output, plugins, caches -- and un-hiding it would make every search from `$HOME` drag through gigabytes; a subdirectory of home is the ordinary case and still gets the file.

## Rules

- Do not put project-specific guidance in `raven-*` files.
- Project repositories may use ordinary names for their own skills, rules, docs, agents, hooks, and scripts.
- Use nested `AGENTS.md` when the guidance applies only to a directory.
- If project guidance conflicts with template guidance, prefer the more specific project guidance for its scope.
- When reapplying the template, manually merge only files that the apply script reports as changed existing files.
- Use `.claude/docs/raven-agent-compatibility.md` to distinguish canonical Raven content from Claude and Codex adapter files.

## AGENTS.md Authoring Rules

Use these rules when writing project-specific agent instructions:

- Write operational instructions for agents, not broad human-facing documentation.
- Place guidance at the most specific directory that fully owns it; move it upward only when genuinely shared.
- Keep instructions concise. Every always-loaded line must earn its place by citing the failure it was observed to prevent — a correction someone had to make, a guardrail an agent worked around — never a failure it might prevent.
- Use descriptive, search-friendly prose and stable names instead of brittle path-heavy references.
- Keep content text-only and easy to search. Avoid diagrams, binary content, and formatting that interferes with parsing.
- Prefer default-no: if most tasks in the scope do not need the information, move it to a skill, scoped rule, or reference document.
