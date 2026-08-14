# Optional Tooling

Raven treats the tools below as recommended capabilities, not dependencies.
When one is missing, agents fall back to the retrieval ladder and cheaper
deterministic tools. Nothing here is required to use Raven.

## Checking what is installed

After installing Raven in a repository:

```sh
python .claude/scripts/raven-tool-check.py
```

For Codex installations:

```sh
python .codex/scripts/raven-tool-check.py
```

If `python` is not the right launcher, use whatever that repository uses —
`python3`, `py -3`, or an active virtual environment.

The SessionStart hook can run this check automatically for Claude Code or
Codex when the matching adapter is enabled. Agent-facing workflows can cache
the results in `~/.raven/tool-memory.json` so you are not asked about the same
tools over and over.

## Recommended tools

`rg`, `fd`, `just`, `uvx`, Semble, GitNexus, `mcp-language-server`, ast-grep,
Semgrep, Gitleaks, OSV-Scanner, `jq`, `yq`, and RTK.

## Language servers over MCP

Language templates ship `.mcp.json` defaults for Semble, GitNexus, and LSP.
For LSP, Raven uses `mcp-language-server` as the general fallback when the
agent client does not already have a reliable native or plugin integration.

| Template   | LSP command in `.mcp.json`           |
| ---------- | ------------------------------------ |
| Python     | `pyright-langserver --stdio`         |
| TypeScript | `typescript-language-server --stdio` |
| Go         | `gopls`                              |
| Rust       | `rust-analyzer`                      |
| Swift      | `sourcekit-lsp`                      |
| Elixir     | `expert --stdio`                     |
| Lua        | `lua-language-server`                |
| Ruby       | `ruby-lsp`                           |

Raven ships the `.mcp.json` command shape but does not install anything. Get
`mcp-language-server` and the language server for your template from their
own documentation. After installation, `.claude/docs/raven-lsp-mcp.md` in the
destination repository has the official links and the per-template command
shapes, and `.claude/docs/raven-tool-assessment.md` has the agent-facing
details.

## Windows

Prefer WSL when the target repository is POSIX-heavy or already uses
Linux/macOS shell tooling. Native Windows is reasonable for Windows-native
projects, but check `PATH` handling and language-server installation on each
machine.
