# Python Raven Template

Copy this directory into the root of a Python repository to install token-efficient agentic coding defaults.

This template inherits shared files from `../common` using symlinks and adds Python-specific Raven rules in `.claude/rules/raven-python.md`.

`AGENTS.md` is authoritative. `CLAUDE.md` is provided only for Claude Code compatibility and should point to the same instructions.
`.agents/skills/` is canonical. Claude and Codex files are compatibility adapters.

When copying into a project that will not also contain this repository's `common/` directory, use the top-level apply script from the destination repository root:

```sh
cd /path/to/python-project
RAVEN_TEMPLATE=/path/to/raven

python "$RAVEN_TEMPLATE/scripts/raven.py" install python --dry-run
python "$RAVEN_TEMPLATE/scripts/raven.py" install python
```

After copying:

- Review `.mcp.json` and remove unavailable MCP servers.
- Review `.claude/settings.json`, `.claude/hooks/`, `.codex/config.toml`, and `.codex/hooks.json`; hooks are included for Claude Code and Codex.
- Run `just install-hooks` to add a pre-commit git hook that runs `just check`, or add `just check` manually to an existing hook.
- Use project-owned files for project-specific guidance. Avoid editing `raven-*` files unless you are intentionally updating the Raven template content.

For Windows teams, WSL generally gives the closest parity with Linux CI and POSIX-heavy Python tooling. Native Windows is also supported, but hooks and commands should stay Python-based rather than Bash-only.
