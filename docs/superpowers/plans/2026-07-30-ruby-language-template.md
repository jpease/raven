# Ruby Language Template Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a full `ruby/` language template tree to Raven, at parity with the existing `lua/`/`elixir/` trees, plus every cross-cutting registration point (gate data, skeleton generator, LSP defaults, docs) a new language template requires.

**Architecture:** `ruby/` is a new top-level template directory, auto-discovered by `list_language_templates()` (any top-level, non-dot, non-`NON_TEMPLATE_DIRS` directory). It mirrors `lua/`'s shape: every shared path is a symlink into `common/` (per `scripts/self-check.py`'s `_TREE_SYMLINKS_TO_COMMON` / `_TREE_SYMLINKS_WITHIN_TREE`, which is the authoritative list), and only the Ruby differentiators are real files (`justfile`, `.mcp.json`, `.codex/config.toml`, `.rubocop.yml`, `.claude/rules/raven-ruby.md`, `.claude/docs/raven-ruby-quality.md`, `README.md`).

**Tech Stack:** RuboCop (lint + format, one pass), Minitest via `bundle exec rake test`, ruby-lsp for the MCP LSP bridge, osv-scanner for the (ungraded) `audit` recipe — matching `docs/superpowers/specs/2026-07-30-ruby-template-design.md`.

## Global Constraints

- Ruby version floor: **3.3+** (Ruby 3.2 reached EOL 2026-03-31). State this explicitly in the rules doc.
- No `fmt-check` or `typecheck` recipe: RuboCop covers lint+format in one pass; Sorbet/RBS are opt-in, not universal.
- `audit` uses **osv-scanner**, not bundler-audit — `tests/test_gates.py` hardcodes this for every template with real scanner input, and osv-scanner supports Ruby (Gemfile.lock/RubyGems).
- `audit` is justfile-only: never add `"audit"` to `GATE_DATA["ruby"]["recipes"]` or `fallback_commands`, and never reference it from `check`/`check-fast` (per `tests/test_gates.py::AuditRecipeTests`).
- LSP: `ruby-lsp`, invoked bare (no `-- --stdio` suffix — confirmed via Shopify docs).
- `common/.claude/scripts/raven-skeleton.py` and `common/.codex/scripts/raven-skeleton.py` must stay byte-identical (`tests/test_skeleton.py::test_claude_and_codex_skeleton_scripts_are_byte_identical`) — every skeleton-generator edit goes into both files identically.
- Every new/edited file must be UTF-8, no trailing-whitespace issues, and match the surrounding file's existing style (indentation, quote style) exactly.
- Do not touch `scripts/raven_lib/cli.py`'s hand-written example language list (line ~694) — it is already stale (missing `lua`/`dotfiles`) and out of scope; `lua`'s own design didn't touch it either, since language templates are auto-discovered, not read from that string.

---

### Task 1: Scaffold the `ruby/` tree's shared symlinks

**Files:**
- Create: `ruby/AGENTS.md`, `ruby/CLAUDE.md`, `ruby/.agents/skills`, `ruby/.claude/skills`, `ruby/.claude/hooks`, `ruby/.claude/scripts`, `ruby/.claude/settings.json`, `ruby/.claude/agents/raven-codebase-cartographer.md`, `ruby/.claude/agents/raven-refactor-reviewer.md`, `ruby/.claude/agents/raven-security-reviewer.md`, `ruby/.claude/agents/raven-test-debugger.md`, `ruby/.claude/docs/raven-agent-compatibility.md`, `ruby/.claude/docs/raven-antipatterns.md`, `ruby/.claude/docs/raven-authority-map.md`, `ruby/.claude/docs/raven-coding-principles.md`, `ruby/.claude/docs/raven-guardrails.md`, `ruby/.claude/docs/raven-lsp-mcp.md`, `ruby/.claude/docs/raven-namespace.md`, `ruby/.claude/docs/raven-semgrep.md`, `ruby/.claude/docs/raven-tool-assessment.md`, `ruby/.claude/rules/raven-security.md`, `ruby/.codex/agents`, `ruby/.codex/hooks`, `ruby/.codex/hooks.json`, `ruby/.codex/rules`, `ruby/.codex/scripts`, `ruby/.raven/git-hooks` (all symlinks)

**Interfaces:**
- Consumes: `scripts/self-check.py`'s `_TREE_SYMLINKS_TO_COMMON` (list of `common/`-relative paths every tree must symlink) and `_TREE_SYMLINKS_WITHIN_TREE` (dict of within-tree relative symlinks: `CLAUDE.md`→`AGENTS.md`, `.claude/skills`→`../.agents/skills`) — these are the authoritative source, already used to validate every other language tree.
- Produces: the full shared-component symlink skeleton other tasks' real files sit inside.

- [ ] **Step 1: Create the symlinks with a one-off script that reads the authoritative list**

Run this from the repo root (it imports the two constants directly from `scripts/self-check.py` rather than hand-typing ~25 relative paths, so it can't drift from what `validate_symlink_canonicality()` actually checks):

```sh
python3 - <<'PYEOF'
import importlib.util
import os
from pathlib import Path

repo_root = Path(__file__).resolve().parent if False else Path.cwd()
spec = importlib.util.spec_from_file_location("self_check", repo_root / "scripts" / "self-check.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

lang_dir = repo_root / "ruby"
lang_dir.mkdir(exist_ok=True)

for rel in m._TREE_SYMLINKS_TO_COMMON:
    target_path = lang_dir / rel
    target_path.parent.mkdir(parents=True, exist_ok=True)
    source = repo_root / "common" / rel
    relative_target = os.path.relpath(source, start=target_path.parent)
    if target_path.exists() or target_path.is_symlink():
        continue
    target_path.symlink_to(relative_target)
    print(f"linked {target_path.relative_to(repo_root)} -> {relative_target}")

for rel, relative_target in m._TREE_SYMLINKS_WITHIN_TREE.items():
    target_path = lang_dir / rel
    target_path.parent.mkdir(parents=True, exist_ok=True)
    if target_path.exists() or target_path.is_symlink():
        continue
    target_path.symlink_to(relative_target)
    print(f"linked {target_path.relative_to(repo_root)} -> {relative_target}")
PYEOF
```

- [ ] **Step 2: Verify against the same check `self-check.py` runs**

```sh
python3 - <<'PYEOF'
import importlib.util
from pathlib import Path

repo_root = Path.cwd()
spec = importlib.util.spec_from_file_location("self_check", repo_root / "scripts" / "self-check.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
m.validate_symlink_canonicality()
PYEOF
```

Expected: prints `==> validate language-tree symlink canonicality` then `symlink canonicality ok` (or equivalent success line) with no `problems` raised — this now also re-validates every pre-existing tree, so it must stay clean.

- [ ] **Step 3: Commit**

```bash
git add ruby/
git commit -m "feat(ruby): scaffold shared symlinks for the ruby template tree"
```

---

### Task 2: Ruby-specific config files, LSP registration, and tool-config wiring

**Files:**
- Create: `ruby/justfile`, `ruby/.mcp.json`, `ruby/.codex/config.toml`, `ruby/.rubocop.yml`
- Modify: `scripts/raven_lib/constants.py`, `tests/helpers.py`, `tests/test_template.py`, `README.md`, `common/.claude/docs/raven-lsp-mcp.md`

**Interfaces:**
- Consumes: nothing from Task 1 beyond the directory existing.
- Produces: `ruby/.mcp.json`'s `mcpServers.lsp` and `ruby/.codex/config.toml`'s `[mcp_servers.lsp]`, both matching `lsp_mcp_args("ruby")` — the shape Task 6's remaining registries and any future task can rely on.

- [ ] **Step 1: Write `ruby/.rubocop.yml`**

```yaml
AllCops:
  TargetRubyVersion: 3.3
  NewCops: enable
  SuggestExtensions: false
```

- [ ] **Step 2: Write `ruby/.mcp.json`**

```json
{
  "mcpServers": {
    "semgrep": {
      "command": "semgrep",
      "args": [
        "mcp"
      ]
    },
    "semble": {
      "command": "uvx",
      "args": [
        "--from",
        "semble[mcp]",
        "semble"
      ]
    },
    "gitnexus": {
      "command": "gitnexus",
      "args": [
        "mcp"
      ]
    },
    "lsp": {
      "command": "mcp-language-server",
      "args": [
        "--workspace",
        ".",
        "--lsp",
        "ruby-lsp"
      ]
    }
  }
}
```

- [ ] **Step 3: Write `ruby/.codex/config.toml`**

```toml
# Raven Codex project configuration for Ruby repositories.
# Project-local Codex config loads only after the project .codex layer is trusted.

[agents]
max_threads = 4
max_depth = 1

[mcp_servers.semgrep]
command = "semgrep"
args = ["mcp"]

[mcp_servers.semble]
command = "uvx"
args = ["--from", "semble[mcp]", "semble"]

[mcp_servers.gitnexus]
command = "gitnexus"
args = ["mcp"]

[mcp_servers.lsp]
command = "mcp-language-server"
args = ["--workspace", ".", "--lsp", "ruby-lsp"]
```

- [ ] **Step 4: Write `ruby/justfile`**

```just
# Run the test suite
test:
    bundle exec rake test

# Run lint checks
lint:
    bundle exec rubocop

# Format the codebase in place
format:
    bundle exec rubocop -A

# Fast static checks for the pre-commit hook (no tests)
check-fast: lint

# Run the standard local verification set (also runs in the pre-push hook).
# A successful run credits the pre-push stamp too, so a manual `just check`
# right before pushing skips a redundant rerun in the hook.
check: check-fast test
    [ -f .raven/git-hooks/lib/with-verified-cache.sh ] && sh .raven/git-hooks/lib/with-verified-cache.sh check true || true

# Report known advisories in dependency manifests via osv-scanner.
audit:
    #!/usr/bin/env sh
    if ! command -v osv-scanner >/dev/null 2>&1; then
        echo "osv-scanner is not installed; skipping the dependency audit."
        echo "Install: https://google.github.io/osv-scanner/installation/"
        exit 0
    fi
    osv-scanner scan source -r .
    status=$?
    # Documented exit codes: 0 clean, 1-126 result-related (findings),
    # 127 general error, 128 nothing scannable, 129-255 other errors.
    if [ "$status" -eq 0 ]; then
        echo "No known advisories in the scanned manifests."
    elif [ "$status" -ge 1 ] && [ "$status" -le 126 ]; then
        echo "Advisories reported above. Classify each one before remediating"
        echo "(see the raven-dependency-update skill); this is not a gate."
    elif [ "$status" -eq 128 ]; then
        echo "No supported dependency manifest found; nothing to audit."
    else
        echo "osv-scanner exited $status without completing the scan." >&2
    fi
    exit 0

# Install pre-commit (fast checks) and pre-push (full check) git hooks
install-hooks:
    #!/usr/bin/env sh
    # Resolve Git's effective hooks dir (honors core.hooksPath and linked
    # worktrees) so hooks land where Git will run them, not a hard-coded
    # .git/hooks that a custom hooksPath would ignore.
    hooks_dir=$(git rev-parse --git-path hooks) || exit 1
    install_hook() {
        name="$1"
        cmd="$2"
        path="$hooks_dir/$name"
        if [ -f "$path" ]; then
            echo "A $name hook already exists at $path."
            echo "To use RAVEN's gate, add this line to it:"
            printf "  %s\n" "$cmd"
        else
            mkdir -p "$hooks_dir"
            printf '#!/bin/sh\n%s\n' "$cmd" > "$path"
            chmod +x "$path"
            echo "Installed $path to run '$cmd'."
        fi
    }
    install_hook pre-commit "just check-fast"
    install_hook pre-push "just check"
```

- [ ] **Step 5: Register `.rubocop.yml` as a starter tool config**

In `scripts/raven_lib/constants.py`, the `COMPONENT_PATHS["tool_configs"]` list is alphabetically sorted. Edit:

```python
    "tool_configs": [
        ".credo.exs",
        ".formatter.exs",
        ".golangci.yml",
        ".luacheckrc",
        ".swift-format",
        ".swiftlint.yml",
        "eslint.config.mjs",
        "prettier.config.mjs",
        "pyproject.toml",
        "rustfmt.toml",
        "stylua.toml",
    ],
```

becomes:

```python
    "tool_configs": [
        ".credo.exs",
        ".formatter.exs",
        ".golangci.yml",
        ".luacheckrc",
        ".rubocop.yml",
        ".swift-format",
        ".swiftlint.yml",
        "eslint.config.mjs",
        "prettier.config.mjs",
        "pyproject.toml",
        "rustfmt.toml",
        "stylua.toml",
    ],
```

- [ ] **Step 6: Register the LSP default in `tests/helpers.py`**

In `tests/helpers.py`, `LSP_DEFAULTS` currently ends with:

```python
    "elixir": ("expert", True),
    "lua": ("lua-language-server", False),
}
```

Change to:

```python
    "elixir": ("expert", True),
    "lua": ("lua-language-server", False),
    "ruby": ("ruby-lsp", False),
}
```

- [ ] **Step 7: Write a failing test for the starter-config copy behavior**

In `tests/test_template.py`, `test_starter_tool_configs_are_copied_when_missing`'s `expected` dict currently ends with:

```python
            "elixir": [".credo.exs", ".formatter.exs"],
            "lua": ["stylua.toml", ".luacheckrc"],
        }
```

Change to:

```python
            "elixir": [".credo.exs", ".formatter.exs"],
            "lua": ["stylua.toml", ".luacheckrc"],
            "ruby": [".rubocop.yml"],
        }
```

- [ ] **Step 8: Run the affected tests to verify they fail before the LSP tables below exist, then pass**

```sh
python -m pytest tests/test_template.py -k "lsp_mcp_defaults or starter_tool_configs or readme_lsp_table" -v
```

Expected: `test_readme_lsp_table_matches_the_shipped_defaults` FAILs (`ruby` has no README table row yet). The other two should already pass since `.mcp.json`/`.codex/config.toml`/`.rubocop.yml` exist.

- [ ] **Step 9: Add the README LSP table row**

In `README.md`, the table around line 241-249 currently ends:

```
| Elixir     | `expert --stdio`                     |
| Lua        | `lua-language-server`                |
```

Change to:

```
| Elixir     | `expert --stdio`                     |
| Lua        | `lua-language-server`                |
| Ruby       | `ruby-lsp`                            |
```

- [ ] **Step 10: Update the two other README mentions of the language list**

In `README.md` line 26:

```
Replace `python` with `typescript`, `go`, `rust`, `swift`, `elixir`, `lua`, or `dotfiles`.
```

becomes:

```
Replace `python` with `typescript`, `go`, `rust`, `swift`, `elixir`, `lua`, `ruby`, or `dotfiles`.
```

In `README.md` line 270 (Repository Layout):

```
- `python/`, `swift/`, `rust/`, `typescript/`, `go/`, `elixir/`, `lua/`, `dotfiles/`: templates that assemble common guidance with stack-specific Raven rules.
```

becomes:

```
- `python/`, `swift/`, `rust/`, `typescript/`, `go/`, `elixir/`, `lua/`, `ruby/`, `dotfiles/`: templates that assemble common guidance with stack-specific Raven rules.
```

- [ ] **Step 11: Add Ruby rows to `common/.claude/docs/raven-lsp-mcp.md` and bump its verification date**

Line 3 currently reads:

```
Last verified: 2026-07-02
```

Change to:

```
Last verified: 2026-07-30
```

The "Recommended Split" table (around line 11-20) currently ends:

```
| Lua        | `lua-language-server`                                                                         |
| Elixir     | `expert` when available (still alpha upstream); ElixirLS remains a viable fallback if the repository already uses it |
```

Change to:

```
| Lua        | `lua-language-server`                                                                         |
| Elixir     | `expert` when available (still alpha upstream); ElixirLS remains a viable fallback if the repository already uses it |
| Ruby       | `ruby-lsp`                                                                                    |
```

The "Install" table (around line 26-35) currently ends:

```
| Elixir Expert              | https://expert-lsp.org/docs/installation                                 | `expert` (`-- --stdio` required)     |
| Lua Language Server        | https://github.com/LuaLS/lua-language-server                             | `lua-language-server`                |
```

Change to:

```
| Elixir Expert              | https://expert-lsp.org/docs/installation                                 | `expert` (`-- --stdio` required)     |
| Lua Language Server        | https://github.com/LuaLS/lua-language-server                             | `lua-language-server`                |
| Ruby LSP                   | https://shopify.github.io/ruby-lsp/                                      | `ruby-lsp`                            |
```

- [ ] **Step 12: Re-run the affected tests to verify they now pass**

```sh
python -m pytest tests/test_template.py -k "lsp_mcp_defaults or starter_tool_configs or readme_lsp_table" -v
```

Expected: all PASS, including the new `ruby` subtests.

- [ ] **Step 13: Commit**

```bash
git add ruby/justfile ruby/.mcp.json ruby/.codex/config.toml ruby/.rubocop.yml \
  scripts/raven_lib/constants.py tests/helpers.py tests/test_template.py \
  README.md common/.claude/docs/raven-lsp-mcp.md
git commit -m "feat(ruby): add justfile, mcp/codex config, and LSP registration"
```

---

### Task 3: Ruby rules doc, quality doc, README, and context-budget registration

**Files:**
- Create: `ruby/.claude/rules/raven-ruby.md`, `ruby/.claude/docs/raven-ruby-quality.md`, `ruby/README.md`
- Modify: `scripts/self-check.py`

**Interfaces:**
- Consumes: nothing new from prior tasks.
- Produces: `ruby/.claude/rules/raven-ruby.md`'s word count, which Step 5 below feeds into `self-check.py`'s `THRESHOLDS`/`PROFILES`.

- [ ] **Step 1: Write `ruby/.claude/rules/raven-ruby.md`**

```markdown
# Ruby Rules

## Applicability

Use these rules for Ruby scripts, libraries, gems, and general applications (CLI tools, Sinatra-style services, background workers). Rails-specific guidance (ActiveRecord, ActionController, asset pipeline) is out of scope for this template; layer Rails-specific project conventions on top when present.

Project-specific `AGENTS.md`, nested `AGENTS.md`, local docs, and existing task-runner commands override this file when they are more specific.

Use `.claude/docs/raven-ruby-quality.md` for detailed Ruby quality guidance when the task touches error design, gem architecture, metaprogramming, performance, security, or dependency policy.

## Setup And Commands

- Prefer the repository's task runner, such as `just`, `rake`, or project scripts, before inventing raw commands.
- Discover available `rake` tasks (`bundle exec rake -T`) and documented commands before guessing.
- Use the narrowest relevant command first, then broaden after it passes.
- Common fallback commands:
  - `bundle exec rubocop` and `bundle exec rubocop -A` (autocorrect)
  - `bundle exec rake test`
  - `just audit` (osv-scanner against `Gemfile.lock`, when installed)
- Use `bundle exec` to run gem executables against the project's locked versions; do not assume a bare binary on PATH matches `Gemfile.lock`.
- Do not assume every project uses RuboCop, Minitest, or Bundler. Use them when configured or clearly appropriate; RSpec is a common alternative to Minitest.

## Pause And Ask

In addition to the guardrails in AGENTS.md, ask before changing:

- Ruby version targets or compatibility. Ruby 3.2 reached end-of-life on 2026-03-31 (no further security patches) and 3.3 is now security-only maintenance -- flag it if a task assumes 3.2 as a supported floor.
- Monkey-patching or reopening core classes (`String`, `Array`, `Object`, etc.) and other metaprogramming that changes behavior repo-wide.
- Native C extensions or FFI bindings, where behavior depends on the compiled extension rather than the Ruby source alone.

## Ruby Safety

- Never call `eval`, `instance_eval`, `class_eval`, `send`, `public_send`, or `const_get` with untrusted or user-controlled input.
- Avoid string-built shell commands with backticks, `system`, `exec`, or `Kernel#open` with unsanitized input; prefer `Process.spawn`/`Open3` with an argv array over shell interpolation.
- Add `# frozen_string_literal: true` to new files in codebases that already use it; do not mutate frozen strings.
- Avoid reopening or monkey-patching core classes; prefer refinements or explicit wrapper objects when extension is genuinely needed.
- Treat `nil` deliberately: use `&.`, `Array#compact`, or explicit checks rather than relying on `NoMethodError` as control flow.

## Error Handling

- Rescue specific `StandardError` subclasses; avoid bare `rescue` and never rescue `Exception` except at a process-level top boundary.
- Do not swallow exceptions silently. Log or re-raise at minimum.
- Preserve exception context when re-raising: `raise NewError, message, cause: original_error` (or a plain `raise NewError` inside a `rescue` block, which sets `cause` automatically).
- Use `ensure` for cleanup that must run regardless of success or failure; prefer block-based resource APIs (`File.open(...) { |f| ... }`) over manual `ensure`-based closing.

## Architecture

- Keep pure business logic separate from I/O, network calls, time, randomness, and framework integration (service objects/POROs over fat models).
- Preserve existing module and gem boundaries unless the task is explicitly architectural.
- Prefer dependency injection (constructor arguments) over reaching for singletons or global state in business logic.
- Do not create circular `require`/`require_relative` dependencies between sibling files.

## Testing

- Inspect nearby tests and fixtures before adding new patterns.
- Prefer `Minitest::Test` (or the project's existing framework, e.g. RSpec) -- do not introduce a second test framework into a project that already picked one.
- Add regression tests for bug fixes when the failure can be reproduced deterministically.
- Do not delete or weaken tests to make a change pass unless explicitly requested.
- Avoid brittle sleeps, timing assumptions, and oversized fixtures unless the codebase already relies on them.

## Dependencies

- Check license compatibility and maintenance status for new gems before adding them to the `Gemfile`.
- Do not change `Gemfile.lock` unless dependency resolution is required by the task.
- Run `just audit` (osv-scanner) before shipping dependency changes to check for known-vulnerable gem versions.

## Quality Gates

- Run the repository's documented final quality gate before handoff when code changed; `just check` runs `rubocop` and `rake test` when present.
- If no final gate exists, use the narrowest relevant checks first, then broaden to lint and tests.
- Fix RuboCop offenses in touched code.
- Do not add broad `# rubocop:disable` comments spanning a whole file. Prefer fixing the code or the narrowest scoped inline disable with a reason.
```

- [ ] **Step 2: Write `ruby/.claude/docs/raven-ruby-quality.md`**

```markdown
# Ruby Quality Reference

Deeper guidance for Ruby architecture, security, and quality decisions. Load this
when the task touches error design, metaprogramming, object design, performance,
security, or dependency policy -- not for routine edits already covered by
`raven-ruby.md`.

## Version Compatibility

- Ruby 3.2 reached end-of-life on 2026-03-31 (no future security patches).
  Ruby 3.3 is in security-only maintenance; Ruby 3.4+ receives full support.
  Treat 3.3 as the practical floor for new code unless the repo has a
  documented reason to support an EOL interpreter.
- Ractor, Fiber Scheduler, and YJIT behavior can differ across 3.x minor
  versions; check `RUBY_VERSION`/`.ruby-version` before relying on a specific
  minor version's semantics.
- Pattern matching (`case/in`), endless methods (`def square(x) = x * x`), and
  Hash shorthand (`{x:, y:}`) require Ruby 3.1+; do not use them in a codebase
  that documents an earlier floor.

## Error Design

- Define a small hierarchy of custom exceptions per domain (e.g. `class
  PaymentError < StandardError`) rather than raising bare `StandardError` or
  `RuntimeError`, so callers can rescue precisely.
- Prefer returning a `Result`-like object (`[:ok, value]` / `[:error, reason]`,
  or a small value object) at internal API boundaries where "the caller
  should branch on outcome" is expected behavior, not an exceptional path.
  Reserve exceptions for genuinely exceptional conditions.
- Use `raise NewError, "context", cause: original` (or a plain `raise` inside
  `rescue`) to preserve the original backtrace and message when translating
  a lower-level error into a domain error.

## Metaprogramming And Core Classes

- Prefer `define_method`, `method_missing` + `respond_to_missing?`, and
  modules/`Comparable`/`Enumerable` mixins over ad hoc monkey-patching.
- Never reopen core classes (`String`, `Array`, `Hash`, `Object`) in library
  code -- it is a global, load-order-dependent side effect that breaks other
  code sharing the process. Use refinements (`refine`/`using`) when the
  behavior genuinely needs to be scoped, or a wrapper/decorator object
  otherwise.
- If `method_missing` is used, always implement `respond_to_missing?`
  alongside it -- omitting it breaks `respond_to?`, `method()`, and
  duck-typing checks that other code relies on.
- Never call `eval`, `instance_eval`, `class_eval`, `send`, `public_send`, or
  `const_get` with untrusted input -- each is a code-execution or
  arbitrary-object-construction primitive.

## Object Design

- Favor plain Ruby objects (POROs) and service objects over god classes;
  a class with more than one reason to change should usually split.
- Use `Struct`/`Data.define` (Ruby 3.2+) for small immutable value objects
  instead of hand-rolled attr_accessor classes with no behavior.
- Keep constructors cheap and side-effect-free; do I/O in explicit methods,
  not in `initialize`.
- Prefer keyword arguments for methods with more than one or two parameters,
  especially booleans -- `discount(order, apply_tax: true)` reads better and
  is harder to misuse than positional booleans.

## Performance

- Profile before optimizing (`ruby-prof`, `stackprof`, or `Benchmark`); do
  not make performance claims from a single local run.
- Avoid `String#+=` / repeated concatenation in loops; use `String#<<` or
  build an array and `Array#join`.
- Freeze literals and constants (`# frozen_string_literal: true`, or
  `.freeze` on constants) to avoid needless allocation and let YJIT optimize
  more aggressively.
- Reuse `Regexp` literals (they are already memoized by Ruby when written as
  literals, unlike `Regexp.new` inside a hot loop).
- CPU-bound work does not parallelize across threads due to the GVL (Global
  VM Lock); reach for `Process.fork`, external workers, or a C
  extension/Ractor when true parallelism is required.

## Security

- Never call `eval`/`send`/`system`/backtick shell execution with
  user-controlled input; prefer `Process.spawn`/`Open3.capture2` with an
  argv array over shell string interpolation.
- Use `Marshal.load` only on trusted, process-internal data -- it can
  instantiate arbitrary objects and execute code via crafted payloads on
  untrusted input. Prefer JSON for untrusted serialization.
- Avoid `YAML.load` on untrusted input; use `YAML.safe_load` (or
  `Psych.safe_load`) with an explicit `permitted_classes` list.
- Validate and allowlist file paths built from user input before passing
  them to `File`/`Dir` APIs to avoid path traversal.

## Testing

- Prefer Minitest's `assert_*` family for behavior assertions; use
  `Minitest::Mock` or a lightweight test double over heavy mocking of
  internals.
- Use `setup`/`teardown` (or RSpec's `before`/`after` if the project uses
  RSpec) for shared fixtures rather than duplicating setup per test.
- Add a regression test for every bug fix when the failure can be reproduced
  deterministically.
- Avoid `sleep`-based waits in tests; prefer polling with a timeout or
  synchronous test doubles for async code.

## Linting And Formatting

- RuboCop covers both lint and formatting in one pass (there is no separate
  mainstream Ruby formatter the way Python/Go/JS split these concerns) -- a
  single `bundle exec rubocop` run checks both.
- Use `bundle exec rubocop -A` to auto-correct safe offenses; review the diff
  before committing, since some auto-corrections change behavior (e.g.
  frozen-string-literal insertion).
- Scope `# rubocop:disable` comments to the narrowest range (a single line or
  block) with a reason; never disable a cop file-wide without justification
  in `.rubocop.yml`'s `Exclude`/`inherit_mode` sections instead.

## Dependencies

- Check license compatibility (`bundle exec license_finder` if configured)
  and maintenance status (last release date, open security advisories)
  before adding a gem to the `Gemfile`.
- Pin dependency versions in `Gemfile.lock`; do not hand-edit the lockfile.
- Run `just audit` (osv-scanner against `Gemfile.lock`) before shipping
  dependency changes; classify any findings per the `raven-dependency-update`
  skill rather than treating the audit as a blocking gate.
```

- [ ] **Step 3: Write `ruby/README.md`**

```markdown
# Ruby Raven Template

Copy this template into the root of a Ruby repository with `scripts/raven.py` from this repository.

This directory assembles:

- shared agent guidance from `common/`
- Ruby-specific Raven rules in `.claude/rules/raven-ruby.md`
- Ruby quality reference material in `.claude/docs/raven-ruby-quality.md`
- a starter `.rubocop.yml` for RuboCop

`README.md` is template documentation and is excluded by default when applying the template.

When copying into a project, run the top-level apply script from the destination repository root:

```sh
cd /path/to/ruby-project
RAVEN_TEMPLATE=/path/to/raven

python "$RAVEN_TEMPLATE/scripts/raven.py" install ruby --dry-run
python "$RAVEN_TEMPLATE/scripts/raven.py" install ruby
```

After copying:

- Run `just install-hooks` to add a pre-commit hook (`just check-fast` — lint) and a pre-push hook (`just check` — the full lint and test gate), or wire those commands into existing hooks manually.
- Use project-owned files for project-specific guidance. Avoid editing `raven-*` files unless you are intentionally updating the Raven template content.
```

- [ ] **Step 4: Measure the rules file's actual word count**

```sh
wc -w ruby/.claude/rules/raven-ruby.md
```

Expected: `731` (the content above was pre-measured at this length). If it differs (e.g. from a copy/paste whitespace change), use the real number in Step 5 instead of 731, following the same ~15% headroom used by sibling entries (e.g. Elixir: actual 781 words → threshold 890; Lua: actual 598 → threshold 680).

- [ ] **Step 5: Register the context-budget entries in `scripts/self-check.py`**

In `validate_context_budget()`, the `THRESHOLDS` dict currently has:

```python
        "lua/.claude/rules/raven-lua.md": 680,
        "dotfiles/.claude/rules/raven-dotfiles.md": 530,
```

Change to:

```python
        "lua/.claude/rules/raven-lua.md": 680,
        "ruby/.claude/rules/raven-ruby.md": 850,
        "dotfiles/.claude/rules/raven-dotfiles.md": 530,
```

In `validate_aggregate_budget()`, the `PROFILES` dict currently has:

```python
        "lua": (1838, "lua/.claude/rules/raven-lua.md"),
        "dotfiles": (1672, "dotfiles/.claude/rules/raven-dotfiles.md"),
```

Change to:

```python
        "lua": (1838, "lua/.claude/rules/raven-lua.md"),
        "ruby": (2008, "ruby/.claude/rules/raven-ruby.md"),
        "dotfiles": (1672, "dotfiles/.claude/rules/raven-dotfiles.md"),
```

(2008 = 1110 shared `common/AGENTS.md` threshold + 45 shared `raven-security.md` threshold + 850 Ruby rules threshold + 3, matching the same-formula sibling entries: python/elixir/rust/go/lua all compute as `1110 + 45 + <language threshold> + 3`.)

- [ ] **Step 6: Verify the budget checks pass**

```sh
python3 - <<'PYEOF'
import importlib.util
from pathlib import Path

repo_root = Path.cwd()
spec = importlib.util.spec_from_file_location("self_check", repo_root / "scripts" / "self-check.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
m.validate_context_budget()
m.validate_aggregate_budget()
PYEOF
```

Expected: both print their `ok` line with no `SystemExit`.

- [ ] **Step 7: Commit**

```bash
git add ruby/.claude/rules/raven-ruby.md ruby/.claude/docs/raven-ruby-quality.md \
  ruby/README.md scripts/self-check.py
git commit -m "feat(ruby): add rules doc, quality doc, README, and context budgets"
```

---

### Task 4: Gate wiring (`gate_data.py`) and gate tests

**Files:**
- Modify: `scripts/raven_lib/data/gate_data.py`
- Modify: `tests/test_gates.py`

**Interfaces:**
- Consumes: `ruby/justfile` from Task 2 (recipe names/audit shape must match).
- Produces: `GATE_DATA["ruby"]`, consumed by `raven assess` and by every generic parametrized test in `tests/test_gates.py` (`test_gate_data_recipes_present_in_justfile`, `test_gate_data_keys_match_shipped_justfiles`, the whole `AuditRecipeTests` class) automatically, since those iterate `load_gate_specs()`/`list_language_templates()`.

- [ ] **Step 1: Write failing Ruby-specific gate tests**

In `tests/test_gates.py`, after `test_elixir_fmt_check_fallback_is_mix_format` (around line 106) and before `test_swift_lint_format_fallback_runs_swift_format`, add (shown as a fragment, so the fence is `text` rather than `python` — the block is class-body indented and is not a valid standalone module):

```text
    def test_ruby_recipes_are_lint_and_test_only(self):
        # Ruby has no separate fmt-check (RuboCop covers lint+format in one
        # pass) and no typecheck (Sorbet/RBS are opt-in, not universal).
        spec = gate_spec_for("ruby")
        assert spec is not None
        self.assertEqual(set(spec.recipes), {"lint", "test"})

    def test_ruby_lint_fallback_is_rubocop(self):
        spec = gate_spec_for("ruby")
        assert spec is not None
        self.assertEqual(spec.fallback_commands["lint"], ("rubocop",))

    def test_ruby_test_fallback_is_rake_test(self):
        spec = gate_spec_for("ruby")
        assert spec is not None
        self.assertEqual(spec.fallback_commands["test"], ("rake", "test"))
```

- [ ] **Step 2: Run the new tests to confirm they fail**

```sh
python -m pytest tests/test_gates.py -k ruby -v
```

Expected: FAIL — `gate_spec_for("ruby")` returns `None` (no `GATE_DATA["ruby"]` entry yet).

- [ ] **Step 3: Add the `GATE_DATA["ruby"]` entry**

In `scripts/raven_lib/data/gate_data.py`, insert a `"ruby"` entry (alongside the other language entries, e.g. after `"lua"` and before the closing `}` of `GATE_DATA`):

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

- [ ] **Step 4: Run the full gate test file to confirm everything passes**

```sh
python -m pytest tests/test_gates.py -v
```

Expected: all PASS, including the pre-existing `AuditRecipeTests` class now also covering `ruby` (its `audit` recipe present, excluded from `recipes`/`fallback_commands`, unreachable from `check`/`check-fast`, and invoking `osv-scanner scan source -r .` since `"ruby"` is not in `_NO_SCANNER_INPUT`).

- [ ] **Step 5: Commit**

```bash
git add scripts/raven_lib/data/gate_data.py tests/test_gates.py
git commit -m "feat(ruby): wire GATE_DATA for raven assess"
```

---

### Task 5: Skeleton generator support (`.rb` detection, node kinds, rg fallback)

**Files:**
- Modify: `common/.claude/scripts/raven-skeleton.py`, `common/.codex/scripts/raven-skeleton.py` (must stay byte-identical — apply the same edit to both)
- Modify: `tests/test_skeleton.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `detect_language("*.rb") == "ruby"`, `node_kinds("ruby")`, `rg_declaration_pattern("ruby")` — consumed by `astgrep_skeleton`/`ctags_skeleton`/`rg_skeleton`/`generate_skeleton` (unchanged call sites; no other code needs edits since these are pure dict lookups).

- [ ] **Step 1: Write failing tests**

In `tests/test_skeleton.py`:

In `LanguageDetectionTests.test_detects_languages_for_shipped_stacks`, the `cases` dict currently ends:

```python
            "a.ex": "elixir",
            "a.exs": "elixir",
            "a.lua": "lua",
        }
```

Change to:

```python
            "a.ex": "elixir",
            "a.exs": "elixir",
            "a.lua": "lua",
            "a.rb": "ruby",
        }
```

In `NodeKindTests`, after `test_typescript_kinds_include_declarations` (before `test_node_kind_languages_are_a_subset_of_detectable_languages`), add:

```python
    def test_ruby_kinds_include_methods_and_classes(self):
        module = _module()
        kinds = module.node_kinds("ruby")
        self.assertIn("method", kinds)
        self.assertIn("singleton_method", kinds)
        self.assertIn("class", kinds)
        self.assertIn("module", kinds)
        self.assertIn("singleton_class", kinds)
```

In `AstgrepSkeletonTests`, after `test_python_golden` (before `test_typescript_golden`), add:

```python
    @unittest.skipUnless(HAVE_ASTGREP, "ast-grep not installed")
    def test_ruby_golden(self):
        module = _module()
        path = self._write(
            "golden.rb",
            "module Greeter\n  def self.hello\n    \"hi\"\n  end\nend\n\n"
            'class Greeter::Formal\n  def greet(name)\n    "Hello, #{name}"\n  end\nend\n',
        )

        self.assertEqual(
            module.astgrep_skeleton(str(path)),
            [
                {"start_line": 1, "end_line": 5, "header": "module Greeter"},
                {"start_line": 2, "end_line": 4, "header": "def self.hello"},
                {"start_line": 7, "end_line": 11, "header": "class Greeter::Formal"},
                {"start_line": 8, "end_line": 10, "header": "def greet(name)"},
            ],
        )
```

In `RgDeclarationPatternTests.test_has_pattern_for_shipped_languages`, the language list currently is:

```python
        for language in ["python", "typescript", "javascript", "go", "rust", "swift", "lua"]:
```

Change to:

```python
        for language in ["python", "typescript", "javascript", "go", "rust", "swift", "lua", "ruby"]:
```

- [ ] **Step 2: Run the new/changed tests to confirm they fail**

```sh
python -m pytest tests/test_skeleton.py -k "ruby or detects_languages_for_shipped_stacks or has_pattern_for_shipped_languages" -v
```

Expected: FAIL — `detect_language("/repo/a.rb")` returns `None`, `node_kinds("ruby")` returns `[]`, `astgrep_skeleton` returns `None` (unsupported language), `rg_declaration_pattern("ruby")` returns `None`.

- [ ] **Step 3: Edit `common/.claude/scripts/raven-skeleton.py`**

In `LANGUAGE_BY_EXTENSION`, change:

```python
    ".ex": "elixir",
    ".exs": "elixir",
}
```

to:

```python
    ".ex": "elixir",
    ".exs": "elixir",
    ".rb": "ruby",
}
```

In `NODE_KINDS`, change:

```python
    "lua": ["function_declaration"],
}
```

to:

```python
    "lua": ["function_declaration"],
    # Verified against ast-grep 0.45.0 on sample files: each kind matches the
    # correct span for `def`, `def self.x`, `class`, `module`, and
    # `class << self` respectively.
    "ruby": ["method", "singleton_method", "class", "module", "singleton_class"],
}
```

In `RG_DECLARATION_PATTERNS`, change:

```python
    "lua": r"^\s*(local\s+)?function\b",
    "elixir": r"^\s*(defmodule|defmacrop|defmacro|defp|def)\s+\w+",
}
```

to:

```python
    "lua": r"^\s*(local\s+)?function\b",
    "elixir": r"^\s*(defmodule|defmacrop|defmacro|defp|def)\s+\w+",
    "ruby": r"^\s*(class|module|def)\s",
}
```

- [ ] **Step 4: Apply the identical edit to `common/.codex/scripts/raven-skeleton.py`**

```sh
diff common/.claude/scripts/raven-skeleton.py common/.codex/scripts/raven-skeleton.py
```

Expected before this step: shows the three hunks above as the only difference. Apply the same three edits to `common/.codex/scripts/raven-skeleton.py`, then re-run the diff and confirm it is empty.

- [ ] **Step 5: Run the full skeleton test file**

```sh
python -m pytest tests/test_skeleton.py -v
```

Expected: all PASS, including `test_claude_and_codex_skeleton_scripts_are_byte_identical` and `test_node_kind_languages_are_a_subset_of_detectable_languages` (which auto-validates the new `ruby` entry against `LANGUAGE_BY_EXTENSION`).

- [ ] **Step 6: Commit**

```bash
git add common/.claude/scripts/raven-skeleton.py common/.codex/scripts/raven-skeleton.py \
  tests/test_skeleton.py
git commit -m "feat(ruby): add skeleton generator support for .rb files"
```

---

### Task 6: Remaining cross-repo registry consistency

**Files:**
- Modify: `tests/test_skills.py`, `CONTRIBUTING.md`

**Interfaces:**
- Consumes: `ruby/.claude/docs/raven-antipatterns.md` symlink from Task 1 (must already resolve correctly).
- Produces: nothing consumed by later tasks — this is the last registry sweep before full verification.

- [ ] **Step 1: Write a failing test**

In `tests/test_skills.py`, `AntipatternRegistrySymlinkTests.test_all_language_trees_symlink_to_the_canonical_registry`'s `language_dirs` list currently is:

```python
        language_dirs = [
            "dotfiles",
            "elixir",
            "go",
            "lua",
            "python",
            "rust",
            "swift",
            "typescript",
        ]
```

Change to (keeping alphabetical order):

```python
        language_dirs = [
            "dotfiles",
            "elixir",
            "go",
            "lua",
            "python",
            "ruby",
            "rust",
            "swift",
            "typescript",
        ]
```

- [ ] **Step 2: Run it to confirm it now passes (Task 1 already created the symlink)**

```sh
python -m pytest tests/test_skills.py -k AntipatternRegistrySymlink -v
```

Expected: PASS — Task 1's scaffolding already created `ruby/.claude/docs/raven-antipatterns.md` as a correct symlink, so this test should go straight to green without further code changes. If it fails, the actual bug is in Task 1's scaffolding (a missing or broken symlink), not a gap in this test.

- [ ] **Step 3: Update `CONTRIBUTING.md`'s project structure table**

Line ~35 currently reads:

```
| `python/`, `go/`, `rust/`, `typescript/`, `swift/`, `elixir/`, `lua/`, `dotfiles/` | Per-language template trees |
```

Change to:

```
| `python/`, `go/`, `rust/`, `typescript/`, `swift/`, `elixir/`, `lua/`, `ruby/`, `dotfiles/` | Per-language template trees |
```

- [ ] **Step 4: Commit**

```bash
git add tests/test_skills.py CONTRIBUTING.md
git commit -m "docs(ruby): register ruby in the antipattern-symlink test and CONTRIBUTING"
```

---

### Task 7: Full verification

**Files:** none (verification only)

**Interfaces:**
- Consumes: everything from Tasks 1-6.
- Produces: nothing — this is the acceptance gate for the whole feature.

- [ ] **Step 1: Run the full unit test suite**

```sh
python -m pytest
```

Expected: all tests PASS (previous test count plus the new Ruby-specific tests added in Tasks 2/4/5/6).

- [ ] **Step 2: Run the self-check harness**

```sh
python scripts/self-check.py
```

Expected: validates the installed shape, runs `upgrade --dry-run`, applies `upgrade`, then runs the unit tests — all green. Per this repo's `CLAUDE.md`, treat any unexpected self-upgrade output here as a product issue to investigate, not noise to ignore.

- [ ] **Step 3: Smoke-test a fresh `raven install ruby` in a temp directory**

```sh
python3 - <<'PYEOF'
import subprocess
import sys
import tempfile
from pathlib import Path

repo_root = Path.cwd()
with tempfile.TemporaryDirectory() as tmp:
    dest = Path(tmp)
    result = subprocess.run(
        [sys.executable, str(repo_root / "scripts" / "raven.py"), "install", "ruby"],
        cwd=dest,
        capture_output=True,
        text=True,
    )
    print(result.stdout)
    print(result.stderr, file=sys.stderr)
    assert result.returncode == 0, "raven install ruby failed"
    assert (dest / "justfile").is_file()
    assert (dest / ".rubocop.yml").is_file()
    assert (dest / ".claude" / "rules" / "raven-ruby.md").is_file()
    assert (dest / "AGENTS.md").is_file()
    print("smoke test ok")
PYEOF
```

Expected: `smoke test ok` with no assertion errors. (This mirrors `tests/test_template.py::test_all_language_templates_install_and_upgrade_cleanly`, which already exercises `ruby` automatically once it's a discovered template — this manual run is a final human-visible confirmation, not a substitute for that test.)

- [ ] **Step 4: Confirm `just --list` and `just --dry-run check` are syntactically valid, if `just` is installed**

```sh
cd ruby && just --list && cd -
```

Expected: lists `test`, `lint`, `format`, `check-fast`, `check`, `audit`, `install-hooks` with no parse errors. (Running `just check` for real requires a Ruby toolchain with `rubocop`/Minitest installed and a `Gemfile`/`Rakefile`, which this template starter does not ship — that is out of scope, matching every other language template's starter, which similarly assumes the toolchain is present in a real project.)

- [ ] **Step 5: Final review — confirm no stray files**

```sh
git status --short
```

Expected: clean (everything from this plan already committed per-task) or only the files this plan intentionally touched, staged and ready for a final review before merge.
