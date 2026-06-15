# Lua Raven Stack — Design

**Date:** 2026-06-14
**Status:** Approved design, pending implementation plan
**Topic:** A new `lua` language template stack, at full parity with the existing language stacks.

## Problem

Raven ships per-language stacks (`python/`, `go/`, `rust/`, `swift/`, `typescript/`,
`elixir/`) plus the new `dotfiles/` stack. There is no Lua stack. Lua is widely used
(Neovim config and plugins, LÖVE/love2d game dev, OpenResty/nginx, Redis scripting,
embedded scripting) and has a distinct toolchain and a set of language hazards
(global pollution, version fragmentation, `load`/`loadstring` on untrusted input)
that warrant Raven guidance.

## Goals

- Add a `lua` stack at **full parity** with the language stacks (rule + quality doc
  + justfile + starter tool configs + `.mcp.json`/`.codex` with an LSP).
- Use the standard Lua toolchain as defaults, verified against upstream docs.
- Stay neutral across Lua ecosystems (plain PUC-Lua and LuaJIT), with Neovim/LÖVE/
  OpenResty noted as variants rather than baked in.

## Non-Goals

- Shipping `.luarc.json` (LuaLS workspace config: library paths, recognized
  globals). That is editor/project-specific and would impose Neovim/LÖVE
  assumptions. Deliberately omitted to keep LSP defaults neutral.
- A separate LuaJIT stack. The `lua` stack covers LuaJIT; differences are documented
  in the quality doc.
- Graceful-degradation justfile logic. The justfile is a starter that assumes the
  documented tools, exactly like the other language stacks (e.g. `go` assumes
  `golangci-lint`).

## Decisions (from brainstorming)

1. **Scope:** full language parity, mirroring the `go/` stack structure.
2. **Linter:** luacheck (config `.luacheckrc`). Most widely used; needs the
   Lua/luarocks toolchain. `selene` (single Rust binary) documented as an
   alternative in the quality doc.
3. **Ecosystem:** general / plain Lua (PUC-Lua + LuaJIT). Neutral defaults; Neovim/
   LÖVE/OpenResty noted as variants.
4. **Formatter:** StyLua (`stylua`, `stylua --check`), config `stylua.toml`.
5. **Tests:** busted (`busted`).
6. **LSP:** `lua-language-server` (LuaLS).
7. **stylua.toml minimal:** set only uncontroversial keys (`column_width`,
   `line_endings`); leave indentation at StyLua's default — Lua indent style is
   contested and has no dominant winner.
8. **.luacheckrc general + commented variants:** neutral defaults plus commented
   `vim` (Neovim) and `love` (LÖVE) global blocks for the two most common contexts.

## Architecture

The `lua` stack is a new top-level template dir, a sibling of the language stacks,
auto-discovered by the installer (`list_language_templates` enumerates top-level
dirs not in `NON_TEMPLATE_DIRS` and not dot-prefixed). It mirrors the `go/` stack's
symlink-into-`common/` structure, with only the Lua differentiators as real files.

### Components (real differentiator files in `lua/`)

1. **`lua/.claude/rules/raven-lua.md`** (always loaded) — mirrors `raven-go.md`:
   - Applicability: modules, Neovim config/plugins, LÖVE, OpenResty, Redis scripts,
     embedded scripting.
   - Setup and commands: prefer `just`; fallbacks `stylua` / `stylua --check`,
     `luacheck .`, `busted`; `luarocks` for deps.
   - Lua safety: `local` by default (no accidental globals); `pcall`/`error` for
     recoverable failures; never `load`/`loadstring`/`dofile` on untrusted input;
     avoid `os.execute`/`io.popen` string injection.
   - Pause and ask: version compatibility (5.1 vs 5.2/5.3/5.4 vs LuaJIT — `goto`,
     integer `//`, bitwise ops, `__index` semantics), C API/FFI, embedded host
     contracts.
   - Architecture: modules return a table; avoid global state.
   - Testing: busted. Dependencies: luarocks, license/maintenance checks.
   - Quality gates: run `just check` (or `stylua --check` + `luacheck` + `busted`).

2. **`lua/.claude/docs/raven-lua-quality.md`** (on demand) — mirrors
   `raven-go-quality.md` depth: error design (pcall boundaries, error objects vs
   strings), version-compatibility matrix, global-pollution avoidance, metatable/OOP
   patterns, performance (locals, table reuse, avoiding rehash), security
   (`load`/`os.execute`/`io.popen` injection, sandboxing), busted patterns,
   luarocks/license hygiene, and a note that `selene` is a single-binary alternative
   to luacheck.

3. **`lua/justfile`** — mirrors `go/justfile`:
   - `test: busted`
   - `lint: luacheck .`
   - `format: stylua .`
   - `fmt-check: stylua --check .`
   - `check: fmt-check lint test` (no `vet` analog in Lua)
   - `install-hooks:` identical to the `go` recipe (pre-commit running `just check`).

4. **`lua/.mcp.json`** — semgrep/semble/gitnexus + lsp:
   `{"command": "mcp-language-server", "args": ["--workspace", ".", "--lsp", "lua-language-server"]}`.

5. **`lua/.codex/config.toml`** — same servers including
   `[mcp_servers.lsp] args = ["--workspace", ".", "--lsp", "lua-language-server"]`.

6. **`lua/stylua.toml`** — minimal: `column_width = 100`, `line_endings = "Unix"`
   (indentation left at StyLua default).

7. **`lua/.luacheckrc`** — neutral starter with commented `vim`/`love` global blocks.

8. **`lua/README.md`** — mirrors `go/README.md` (lists the Lua differentiators and
   the `just install-hooks` step).

### Shared (symlinks from `common/`, identical to `go/`)

`AGENTS.md`/`CLAUDE.md`, `.claude/agents/*`, shared `.claude/docs/*`, `.claude/hooks/*`,
`.claude/rules/raven-security.md` + `raven-tests.md`, `.claude/scripts/*`,
`.claude/settings.json`, `.claude/skills`, `.agents/skills`,
`.codex/{agents,hooks,hooks.json,rules,scripts}`, `.raven/git-hooks`.

### Code and test changes (the only edits outside `lua/`)

- `scripts/raven_lib/constants.py`: add `stylua.toml` and `.luacheckrc` to
  `COMPONENT_PATHS["tool_configs"]` (this set also feeds `STARTER_TOOL_CONFIG_PATHS`).
- `tests/test_template.py`: add `lua` entries to the three parametrized expected
  dicts:
  - `test_starter_tool_configs_are_copied_when_missing`: `"lua": ["stylua.toml", ".luacheckrc"]`.
  - `test_language_templates_define_specific_lsp_mcp_defaults`:
    `"lua": ["--workspace", ".", "--lsp", "lua-language-server"]`.
  - `test_language_templates_define_specific_codex_lsp_mcp_defaults`: same `lua` entry.
- `common/.claude/docs/raven-lsp-mcp.md`: if it enumerates per-language LSP defaults,
  add Lua → `lua-language-server`. The self-check validates shared-doc sync, so this
  is updated in the `common/` source.

## Upstream Verification

Per `CLAUDE.md`'s upstream-template-maintenance rule, verify before committing
defaults: `lua-language-server` invocation via `mcp-language-server`; `stylua` /
`stylua --check` flags and `stylua.toml` keys; `luacheck` config format and `std`
options for `.luacheckrc`; `busted` invocation.

## Verification

- New parametrized coverage: `lua` flows through
  `test_all_language_templates_install_and_upgrade_cleanly`,
  `test_templates_have_no_broken_symlinks`, and the three expected-dict tests.
- Full suite + `self-check.py` + a temp-dir `raven install lua` smoke test.

## Open Questions

None blocking.
