# TypeScript Raven Template

Copy this directory into the root of a TypeScript repository to install token-efficient agentic coding defaults.

This template inherits shared files from `../common` using symlinks and adds TypeScript-specific Raven rules in `.claude/rules/raven-typescript.md` and a quality reference in `.claude/docs/raven-typescript-quality.md`.

`AGENTS.md` is authoritative. `CLAUDE.md` is provided only for Claude Code compatibility and points to the same instructions.
`.agents/skills/` is canonical. Claude and Codex files are compatibility adapters.

When copying into a project that will not also contain this repository's `common/` directory, use the install script from the destination repository root:

```sh
cd /path/to/typescript-project
RAVEN_TEMPLATE=/path/to/raven

python "$RAVEN_TEMPLATE/scripts/raven.py" install typescript --dry-run
python "$RAVEN_TEMPLATE/scripts/raven.py" install typescript
```

After installing:

- Review `.mcp.json` and remove unavailable MCP servers.
- Review `.claude/settings.json`, `.claude/hooks/`, `.codex/config.toml`, and `.codex/hooks.json`; hooks are included for Claude Code and Codex.
- Run `just install-hooks` to add a pre-commit hook (`just check-fast` — fast lint and format checks) and a pre-push hook (`just check` — the full lint, type, and test gate), or wire those commands into existing hooks manually.
- Use project-owned files for project-specific guidance. Avoid editing `raven-*` files unless you are intentionally updating the Raven template content.

This template applies to TypeScript projects of any shape: monorepos, Node.js services, React applications, CLI tools, and libraries. Language-specific rules in `.claude/rules/raven-typescript.md` are intentionally general; add project-specific guidance in your own `AGENTS.md` or a local rule file.
