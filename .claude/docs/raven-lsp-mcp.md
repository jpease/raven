# LSP MCP Defaults

Last verified: 2026-08-24

Use client-native LSP or language plugins first when the agent client provides a reliable one for the project language. When no client-native option is available, Raven's recommended general-purpose fallback is `mcp-language-server` from `isaacphi/mcp-language-server`.

`mcp-language-server` is a generic MCP adapter for stdio-based language servers. It exposes semantic tools such as definition, references, hover, diagnostics, and rename through MCP. It still requires the actual language server for the project language.

## Never Run Two Providers For One Language

A language server started by two clients is two full instances. They do not share an index, a process, or memory. If a harness already launches the server for a language, do not add a second path to it.

Claude Code covers this through official marketplace LSP plugins, which launch the language server themselves. So a language with a plugin gets no `lsp` server in `.mcp.json`, and the plugin is the only provider. Codex has no LSP integration of its own (verified against codex-cli 0.149.1), so `.codex/config.toml` keeps the `mcp-language-server` bridge for every language.

Swift shows why this matters. `sourcekitd` does no pooling: three `sourcekit-lsp` clients opened against one workspace produced three separate `SourceKitService` processes, and none of them was shared with the instance Xcode was already running. Measured resident size ranged from 0.3 GB to 6.5 GB each. Running the plugin and the bridge together in one Swift repo doubles that bill for no added capability.

The two providers are not feature-identical, and the plugin is the one to keep:

| | Claude Code LSP plugin | `mcp-language-server` bridge |
| --- | --- | --- |
| Definition, references, hover | yes | yes |
| Document and workspace symbols | yes | no |
| Implementations, call hierarchy | yes | no |
| Diagnostics | no | yes |
| Rename, in-place edit | no | yes |

For diagnostics on a plugin-covered language, use the repository's own gate — `just check`, the compiler, or the linter — rather than reaching for a second language server. That is the authoritative answer anyway, per the client-native caveat at the end of this file.

## Recommended Split

Every row names one language server. The "Provider" column says who starts it: the named Claude Code plugin, or the `mcp-language-server` bridge in `.mcp.json`. Codex always uses the bridge, from `.codex/config.toml`.

| Language   | Preferred LSP command for generic MCP fallback                                                | Provider on Claude Code |
| ---------- | --------------------------------------------------------------------------------------------- | ----------------------- |
| Python     | `pyright-langserver --stdio` or the repo's configured `basedpyright-langserver --stdio`       | `pyright-lsp` plugin |
| TypeScript | `typescript-language-server --stdio`                                                          | `typescript-lsp` plugin |
| Rust       | `rust-analyzer`                                                                               | `rust-analyzer-lsp` plugin |
| Swift      | `sourcekit-lsp`                                                                               | `swift-lsp` plugin |
| Go         | `gopls`                                                                                       | `gopls-lsp` plugin |
| C/C++      | `clangd` with the repo's compile database settings                                            | `clangd-lsp` plugin |
| Lua        | `lua-language-server`                                                                         | `lua-lsp` plugin |
| Elixir     | `expert` when available (still alpha upstream); ElixirLS remains a viable fallback if the repository already uses it | bridge (no plugin) |
| Ruby       | `ruby-lsp`                                                                                    | `ruby-lsp` plugin |

## Install

Install the language server from its official documentation. On Claude Code, add the plugin its row names with `/plugin install <name>@claude-plugins-official`; the plugins are opt-in, so a plugin-covered language has no LSP until you do. The `mcp-language-server` bridge is needed for Codex, and on Claude Code only for a language no plugin covers.

| Component                  | Official install documentation                                           | Language-server command              |
| -------------------------- | ------------------------------------------------------------------------ | ------------------------------------ |
| `mcp-language-server`      | https://github.com/isaacphi/mcp-language-server                          | n/a                                  |
| Python / Pyright           | https://github.com/microsoft/pyright                                     | `pyright-langserver --stdio`         |
| TypeScript language server | https://github.com/typescript-language-server/typescript-language-server | `typescript-language-server --stdio` |
| Go / gopls                 | https://go.dev/gopls/                                                    | `gopls`                              |
| Rust Analyzer              | https://rust-analyzer.github.io/manual.html                              | `rust-analyzer`                      |
| SourceKit-LSP              | https://github.com/swiftlang/sourcekit-lsp                               | `sourcekit-lsp`                      |
| Elixir Expert              | https://expert-lsp.org/docs/installation                                 | `expert` (`-- --stdio` required)     |
| Lua Language Server        | https://github.com/LuaLS/lua-language-server                             | `lua-language-server`                |
| Ruby LSP                   | https://shopify.github.io/ruby-lsp/                                      | `ruby-lsp`                            |

Treat Raven's template defaults as convenience defaults, not a replacement for upstream documentation.

## MCP Configuration Pattern

Every language template ships a `.codex/config.toml` bridge entry. A `.mcp.json` bridge entry ships only for a language no Claude Code plugin covers, so today Elixir is the one template that carries both. The general shape is:

```json
{
  "mcpServers": {
    "lsp": {
      "command": "mcp-language-server",
      "args": ["--workspace", ".", "--lsp", "expert", "--", "--stdio"]
    }
  }
}
```

The Codex equivalent, which every template ships:

```toml
[mcp_servers.lsp]
command = "mcp-language-server"
args = ["--workspace", ".", "--lsp", "expert", "--", "--stdio"]
```

Both examples show the `-- --stdio` form: a language server that needs stdio flags takes them after `--`. A server that does not, such as `sourcekit-lsp` or `gopls`, ends its args at the server name.

## Use Policy

- Prefer LSP for known symbols: definitions, references, diagnostics, hover/type information, and rename-impact checks.
- Do not use LSP as a replacement for exact text search, semantic discovery, or architecture graph analysis.
- If the bridge or language server is not installed, fall back to `rg`, compiler diagnostics, and targeted file reads.
- Do not add a second provider for a language that already has one. Two clients on one language server means two resident instances, and for `sourcekit-lsp` that is gigabytes per copy.
- Do not assume `.mcp.json` works unchanged on every machine; PATH, plugin installation, and language-server installation all still matter.
- Client-native LSP reliability is a property of the client, not the language. A client that launches one workspace-wide server can misresolve imports in monorepos and multi-package layouts (e.g. TypeScript project references / solution-style root `tsconfig` with `"files": []`, or unbuilt workspace packages), emitting spurious "cannot find module" diagnostics. When the project has an authoritative build or typecheck gate (`tsc -b`, `mypy`, `cargo check`) and it disagrees with editor-injected diagnostics, trust the gate. Keep using the language server for on-demand navigation (definition, references, hover, rename); when plugin diagnostics stay noisy, trust the gate rather than starting a second server to get a second opinion.
