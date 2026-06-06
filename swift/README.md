# Swift Raven Template

Copy this directory into the root of a Swift, SwiftUI, or Apple-platform repository to install token-efficient agentic coding defaults.

This template inherits shared files from `../common` using symlinks and adds Swift-specific Raven rules in `.claude/rules/raven-swift.md`.

`AGENTS.md` is authoritative. `CLAUDE.md` is provided only for Claude Code compatibility and should point to the same instructions.
`.agents/skills/` is canonical. Claude and Codex files are compatibility adapters.

When copying into a project that will not also contain this repository's `common/` directory, use the top-level apply script:

```sh
cd /path/to/swift-project
RAVEN_TEMPLATE=/path/to/raven

python "$RAVEN_TEMPLATE/scripts/raven.py" install swift --dry-run
python "$RAVEN_TEMPLATE/scripts/raven.py" install swift
```

After copying:

- Review `.mcp.json` and remove unavailable MCP servers.
- Review `.claude/settings.json`, `.claude/hooks/`, `.codex/config.toml`, and `.codex/hooks.json`; hooks are included for Claude Code and Codex.
- Run `just install-hooks` to add a pre-commit git hook that runs `just check`, or add `just check` manually to an existing hook.
- Use project-owned files for project-specific guidance. Avoid editing `raven-*` files unless you are intentionally updating the Raven template content.
