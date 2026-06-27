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

## Formatting and linting

This template installs a two-tool Swift quality setup with a clear division of labor:

- **`swift-format` (Apple) owns formatting.** `.swift-format` uses Apple's defaults — 4-space indentation (the Xcode/community standard; swift-format's own 2-space default is overridden) and the default 100-column line length — and runs *formatting only*: its lint-style opinion rules (`ReplaceForEachWithForLoop`, `UseTripleSlashForDocumentationComments`, etc.) are disabled so SwiftLint is the single linter. `just format` rewrites in place; `just lint-format` verifies without modifying (CI-friendly). It is invoked via `xcrun swift-format`, so no separate install is needed on macOS with Xcode.
- **SwiftLint owns linting.** `.swiftlint.yml` follows community best-practice defaults, with the three formatting rules swift-format owns (`trailing_comma`, `opening_brace`, `closure_parameter_position`) disabled so the two tools never conflict.

`just check` runs `lint-format`, `lint`, build, and test. Both tools scope to **git-tracked Swift only**, so build output (`DerivedData`, `.build`) and vendored SwiftPM checkouts are never formatted or linted. The post-edit hook (`raven-post-edit-format.py`) auto-formats edited `.swift` files with swift-format when available.

This is a **community-consensus baseline**. Layer stricter, project-specific quality rules (e.g. additional SwiftLint opt-in rules, `force_unwrapping`) in the project's own `.swiftlint.yml` rather than here.
