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

`rg`, `fd`, `just`, GitNexus, `mcp-language-server`, ast-grep, Semgrep,
Gitleaks, OSV-Scanner, Vale, `jq`, `yq`, and RTK.

None is required. Two are worth a word because the installed `AGENTS.md` names
them by name, which makes them look mandatory when they are not:

| Tool | What it is | Install |
|---|---|---|
| RTK | A CLI proxy that compresses noisy command output before it reaches the model. `AGENTS.md` routes test, build, and log commands through it. | `brew install rtk` — [rtk-ai.app](https://www.rtk-ai.app/) |
| GitNexus | Indexes the repository into a call graph so an agent can ask what a change breaks. `AGENTS.md` treats its impact analysis as mandatory *where an index is configured*, and silent everywhere else. | `npx gitnexus analyze` |

Skip either one and nothing breaks. The RTK hint is emitted by a hook that
checks `PATH` first and says nothing when RTK is absent, and the GitNexus
guidance is scoped to repositories that have an index.

## Vale takes a second step

Installing the binary is not enough. The `raven-write-prose` skill ships a
config that declares three style packages, and none of them download until you
ask:

```bash
cd .agents/skills/raven-write-prose/reference/vale
vale sync
```

That fetches proselint, write-good, and Readability over the network. Until you
run it the declaration does nothing, and Vale checks only the small vendored
`Raven` style, which needs no download. Skipping this step costs you the
cliché, corporate-speak, and hedging checks, not correctness.

After syncing, open `.vale.ini` and follow the commented block to add
`proselint` to `BasedOnStyles`. Do not add it before syncing — Vale refuses to
run at all against a style it cannot find.

Without Vale the prose skills still work. They print one line saying it is
missing and carry on to the structural pass, which is a reading pass no linter
performs.

## Language servers over MCP

Language templates ship `.mcp.json` defaults for Semgrep and GitNexus. Which
of them also ships an `lsp` server depends on the harness, because the two
harnesses do not start language servers the same way.

Claude Code has official marketplace LSP plugins that launch the language
server themselves. Where one exists, Raven's `.mcp.json` ships no `lsp` server:
running the plugin and the `mcp-language-server` bridge together starts the
same server twice, and a language server is not a cheap process to duplicate.
Swift is the clearest case. Every `sourcekit-lsp` client gets a private
`SourceKitService` — measured between 0.3 GB and 6.5 GB, with no sharing
between clients and none with the instance Xcode already runs.

Codex has no LSP integration of its own, so `.codex/config.toml` keeps the
`mcp-language-server` bridge for every language.

| Template   | Language server                      | Claude Code                | Codex  |
| ---------- | ------------------------------------ | -------------------------- | ------ |
| Python     | `pyright-langserver --stdio`         | `pyright-lsp` plugin       | bridge |
| TypeScript | `typescript-language-server --stdio` | `typescript-lsp` plugin    | bridge |
| Go         | `gopls`                              | `gopls-lsp` plugin         | bridge |
| Rust       | `rust-analyzer`                      | `rust-analyzer-lsp` plugin | bridge |
| Swift      | `sourcekit-lsp`                      | `swift-lsp` plugin         | bridge |
| Elixir     | `expert --stdio`                     | bridge (no plugin)         | bridge |
| Lua        | `lua-language-server`                | `lua-lsp` plugin           | bridge |
| Ruby       | `ruby-lsp`                           | `ruby-lsp` plugin          | bridge |

Install the plugin with `/plugin install <name>@claude-plugins-official`. The
plugins are opt-in, so on Claude Code a template whose row says "plugin" has
no language server until you install it. Nothing in Raven detects that gap
yet; check `/plugin` if LSP tools come back empty.

Raven ships the command shape but does not install anything. Get
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
