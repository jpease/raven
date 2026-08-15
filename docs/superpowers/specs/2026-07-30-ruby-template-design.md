# Ruby Language Template

## Problem

Raven ships language template trees (`python/`, `go/`, `rust/`, `typescript/`,
`swift/`, `elixir/`, `lua/`, `dotfiles/`) but has no Ruby tree. There is no
`ruby` entry in `raven` template selection, `gate_data.py`, `constants.py`'s
starter tool-config list, or the skeleton generator's language tables, so a
Ruby project cannot install Raven guidance, get graded gate recipes, or get
skeleton-first file summaries.

## Goal

Add a full `ruby/` template tree matching the shape and quality bar of the
`lua/` and `elixir/` trees, plus every cross-cutting registration point those
trees required (`gate_data.py`, `constants.py`, skeleton generator, CLI help
text), so Ruby is a first-class supported language template.

## Toolchain decisions

Confirmed against current upstream docs, not assumed from general knowledge
(per this repo's rule to validate third-party setup guidance):

- **Lint + format: RuboCop only.** Ruby has no separately-adopted formatter
  the way Python/Go/JS do (Black/gofmt/Prettier) — RuboCop's `Layout`/`Style`
  cops cover formatting in the same pass as lint. The template therefore ships
  one `lint` recipe, not a `lint` + `fmt-check` pair. This mirrors how the Lua
  template already omits a `typecheck` recipe rather than faking one.
- **Test: Minitest**, stdlib-only (no extra gem), run via `bundle exec rake
  test`. Chosen over RSpec to keep the template dependency-free by default,
  matching the stdlib-first bias of the other lean templates.
- **No `typecheck` recipe.** Sorbet/RBS are opt-in, not a near-universal
  convention like `mypy`/`pyright`/`tsc`, so it is omitted rather than
  reported as passing when unconfigured.
- **LSP: ruby-lsp** (`gem install ruby-lsp`). Confirmed via Shopify's docs:
  invoked bare (`ruby-lsp`, no flags, not via `bundle exec`) for stdio
  clients — this is the actively-maintained community-default LSP,
  superseding Solargraph.
- **Audit: osv-scanner**, not bundler-audit. Originally scoped as
  bundler-audit (confirmed via the `rubysec/bundler-audit` README: binary
  `bundle-audit`, command `bundle-audit check --update`), but reading
  `tests/test_gates.py` revealed a hard repo convention:
  `test_scanning_templates_invoke_osv_scanner_without_failing_the_shell`
  asserts, for every template not in `_NO_SCANNER_INPUT = {"swift", "lua"}`,
  that its `audit` recipe invokes osv-scanner specifically (checks for the
  literal `osv-scanner scan source -r .`). osv-scanner supports Ruby
  (Gemfile.lock / RubyGems is a covered ecosystem), so Ruby has real scanner
  input and must use osv-scanner like every other scanning template, not a
  Ruby-specific exception. `ruby/justfile`'s `audit` recipe is therefore a
  verbatim copy of `python/justfile`'s (lines 38-60): probe for
  `osv-scanner`, print an install pointer and exit 0 if absent, else run
  `osv-scanner scan source -r .` and classify the exit code (0 clean,
  1-126 findings, 128 nothing scannable, other = scan error), always
  exiting 0 so `audit` never blocks a gate. Per `gate_data.py`'s existing
  documented policy, every language's `audit` recipe is justfile-only and
  excluded from the graded `recipes` list because results depend on the
  advisory database rather than the working tree — Ruby follows the same
  pattern.
- **Version floor: 3.3+.** Verified Ruby's support lifecycle: Ruby 3.2 reached
  end-of-life on 2026-03-31 (no further security patches), and 3.3 is now in
  security-only maintenance. The rules doc states 3.2 is EOL outright and asks
  before assuming a project can still target it.

## Design

### New `ruby/` template tree

Cloned from `lua/`'s structure: symlinks to `common/` for skills, hooks,
scripts, and settings; real, language-specific files for the rest.

- `justfile`:
  - `lint`: `bundle exec rubocop`
  - `format`: `bundle exec rubocop -A`
  - `test`: `bundle exec rake test`
  - `check-fast`: `lint` (no separate fmt-check to fold in, unlike Lua/Python)
  - `check`: `check-fast` + `test`, with the standard verified-cache stamp
    (`with-verified-cache.sh`)
  - `audit`: osv-scanner probe/scan/exit-code-classify, verbatim copy of
    `python/justfile`'s `audit` recipe
  - `install-hooks`: same pre-commit/pre-push wiring as every other template
- `.mcp.json`: `semgrep`, `semble`, `gitnexus`, and `lsp` →
  `mcp-language-server --workspace . --lsp ruby-lsp`
- `.codex/config.toml`: same MCP servers mirrored into TOML, matching the
  `lua`/`elixir` shape
- `.claude/rules/raven-ruby.md`: applicability (Ruby scripts, libraries, gems,
  general applications — not Rails-specific); setup/commands; pause-and-ask
  (version compatibility incl. the 3.2 EOL note, metaprogramming/monkey-
  patching core classes, C extensions); Ruby safety (no `eval`/`send`/
  `const_get` on untrusted input, `frozen_string_literal`, avoid reopening
  core classes); error handling (specific `rescue`, no bare rescue, `raise
  ..., cause:`); architecture (POROs/service objects, keep I/O out of pure
  logic); testing (Minitest conventions); dependencies (Bundler/Gemfile.lock,
  license checks); quality gates
- `.claude/docs/raven-ruby-quality.md`: deeper guidance, same section shape as
  `raven-elixir-quality.md`
- `.rubocop.yml`: starter config, `TargetRubyVersion: 3.3`, `NewCops: enable`
- `README.md`: mirrors `lua/README.md`'s shape

### Installer / gate wiring

- `scripts/raven_lib/data/gate_data.py` — new `"ruby"` entry:
  ```python
  "ruby": {
      "recipes": ["lint", "test"],
      "tools": ["rubocop", "ruby"],
      "detect_signals": ["Gemfile", ".rubocop.yml"],
      "config_signals": [[".rubocop.yml", ""]],
      "fallback_commands": {
          "lint": ["rubocop"],
          "test": ["rake", "test"],
      },
  },
  ```
- `scripts/raven_lib/constants.py` — add `.rubocop.yml` to
  `COMPONENT_PATHS["tool_configs"]` (drives `STARTER_TOOL_CONFIG_PATHS`).
- `scripts/raven_lib/cli.py` (~line 694) — add `ruby` to the language-template
  help text example list.

### Skeleton generator (`common/.claude/scripts/raven-skeleton.py`)

Node kinds verified directly against `ast-grep 0.45.0` on sample Ruby files
(not guessed): `method`, `singleton_method`, `class`, `module`, and
`singleton_class` each matched the correct span for `def`, `def self.x`,
`class`, `module`, and `class << self` respectively.

- Extension table: `.rb` → `"ruby"`
- `NODE_KINDS["ruby"] = ["method", "singleton_method", "class", "module", "singleton_class"]`
- `RG_DECLARATION_PATTERNS["ruby"] = r"^\s*(class|module|def)\s"` (degraded
  rg-only tier)
- New golden tests in `tests/test_skeleton.py` mirroring the existing Lua/
  Elixir cases (node-kind path + rg-fallback path)

### Testing

- `tests/test_gates.py`: Ruby recipes and fallback-command assertions,
  mirroring `test_elixir_recipes_include_fmt_check` /
  `test_elixir_fmt_check_fallback_is_mix_format` (adapted: Ruby has no
  fmt-check, so this covers `lint`'s fallback instead).
- `tests/test_skeleton.py`: Ruby node-kind and rg-fallback goldens.
- `tests/test_template.py`: starter `.rubocop.yml` copy-when-missing /
  config-disable behavior (same pattern as the existing starter-tool-config
  tests).
- `tests/test_skills.py`: whatever cross-tree skill-parity assertions already
  run for every language template should extend to `ruby/` automatically once
  it exists with the standard symlink shape.

## Out of scope

- Rails-specific guidance (this targets general Ruby apps/libraries/gems, the
  same framing Lua uses for non-Neovim-specific guidance).
- Sorbet/RBS static typechecking.
- JRuby/TruffleRuby-specific compatibility notes.
- RSpec support (Minitest is the default; a user can still add RSpec to their
  own project, but the template doesn't ship RSpec config).

## Acceptance criteria

- `raven install ruby` (positional `language` arg, or the interactive prompt
  listing it) produces a tree matching the other language templates' shape:
  symlinked shared components, real language-specific rules/docs/justfile/
  mcp/codex-config/starter-tool-config.
- `just check` in a fresh Ruby template install runs `rubocop` then `rake
  test` and passes on an empty/starter project.
- `raven assess` grades Ruby's `lint` and `test` recipes; `audit` is present
  in the justfile but not graded, consistent with every other template.
- Skeleton generation on a `.rb` file returns correct top-level `def`/`class`/
  `module`/`class << self` entries via the ast-grep tier, with rg-tier
  fallback tested independently.
- `python -m pytest` and `python scripts/self-check.py` pass with the new
  template installed as part of this repo's self-test workflow.
