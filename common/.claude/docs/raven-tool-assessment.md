# Tool Assessment

Last verified: 2026-06-14

This template intentionally separates tool roles. No single retrieval tool should replace all others.

## Recommended Tool Roles

| Tool | Best suited for | Notes |
|---|---|---|
| `rg` | Exact strings, symbols, error messages, config keys, exhaustive confirmation | Usually the cheapest first step. Claude Code usually includes ripgrep; install separately if search fails. |
| `fd` | File discovery by name, extension, type, or pattern | Faster and friendlier than `find`. Use to locate files before reading them. |
| `just` | Consistent task runner for test, lint, format, typecheck, and hook installation | Use `just --list` to discover available recipes. Prefer `just check` over invoking tools directly. |
| Semble | Intent-based code search when the owning file or symbol is unknown | Best for "where is this behavior?" questions. Treat it as semantic retrieval, not exhaustive proof or an editing decision by itself. |
| LSP | Definitions, references, hover/type info, diagnostics, rename safety | Best once a symbol is known. Prefer client-native LSP integrations when available; otherwise use `mcp-language-server` plus the relevant language server. |
| GitNexus | Architecture, dependency, call-path, and blast-radius reasoning | Best for structural questions. Treat as a graph/static-analysis layer, not as a replacement for LSP. Disk footprint reaches hundreds of MB even for small repos, is gitignored (not committed), and regenerates fully on reindex rather than updating incrementally. Contributors on constrained disk may leave unconfigured and rely on the `rg`+LSP fallback documented in the retrieval ladder. |
| ast-grep | Syntax-aware search and mechanical rewrites | Best when code shape matters more than raw text. Good for reviewable structural edits. |
| Semgrep | Security, policy, and multi-language static-analysis rules | Best for finding risky patterns and enforcing rules across codebases. Heavier than ast-grep for simple rewrites. |
| Gitleaks | Deterministic secret scanning | Best for checking staged changes with `gitleaks git --staged` (gitleaks >= 8.19) or `gitleaks protect --staged` (older releases) and repository history with `gitleaks git` / `gitleaks detect`. |
| OSV-Scanner | Known advisories in dependency lockfiles | Backs `just audit`, which is report-only and never part of `check`. One binary covers npm, PyPI, crates.io, Go, Hex, Maven, RubyGems and more; it reads no Swift or Lua manifest. |
| `jq` | Structured JSON reads and transformations | Use for JSON output when a purpose-built parser is not already available. This is a transform tool, not a retrieval source. |
| `yq` | Structured YAML reads and transformations | Use for YAML output when a purpose-built parser is not already available. This is a transform tool, not a retrieval source. |
| RTK | Compressing noisy command output before it enters model context | Best for tests, builds, logs, and large CLI output. Bypass it when exact output is required. |

## Cross-Platform Availability

| Tool | macOS | Linux | Windows native | Windows WSL |
|---|---:|---:|---:|---:|
| Claude Code | Yes | Yes | Yes | Yes |
| `rg` | Yes | Yes | Yes | Yes |
| `fd` | Yes | Yes | Yes | Yes |
| `just` | Yes | Yes | Yes | Yes |
| Semble | Likely, via Python/`uvx` | Likely, via Python/`uvx` | Likely, but validate locally | Yes |
| `mcp-language-server` LSP bridge | Yes, requires Go and language server | Yes, requires Go and language server | Likely, validate PATH/toolchain behavior | Yes |
| GitNexus | Validate locally | Validate locally | Validate locally | Validate locally |
| ast-grep | Yes | Yes | Yes | Yes |
| Semgrep | Yes | Yes | Supported, but confirm current CLI behavior | Yes |
| Gitleaks | Yes | Yes | Yes | Yes |
| OSV-Scanner | Yes | Yes | Yes | Yes |
| `jq` | Yes | Yes | Yes | Yes |
| `yq` | Yes | Yes | Yes | Yes |
| RTK | Yes | Yes | Yes, via prebuilt binary | Yes |

## Practical Guidance

- Prefer WSL for Windows projects that need Linux parity, sandboxing, or POSIX-heavy scripts.
- Prefer native Windows when the project itself is Windows-native and uses Windows toolchains.
- For Python templates, use Python-based hooks because the target repository is expected to have Python available. For non-Python templates, choose the runtime already required by that language ecosystem.
- Use `mcp-language-server` as Raven's default general-purpose LSP-over-MCP fallback when a client-native LSP integration is unavailable.
- Keep `.mcp.json` editable. The language templates provide reasonable defaults, but PATH and language-server installation remain local machine concerns.
- Use `.claude/docs/raven-lsp-mcp.md` for LSP bridge setup and per-language defaults.
- Use `.claude/docs/raven-semgrep.md` for Semgrep community and Pro edition setup. Raven defaults to the community edition via the `.mcp.json` MCP server entry; do not enable the `semgrep@claude-plugins-official` plugin unless you have a Semgrep AppSec Platform account.
- Use `just --list` to discover available project recipes before invoking tools directly. Prefer `just test`, `just lint`, `just check`, and `just install-hooks` over raw tool commands when a justfile is present.
- Check tool presence before relying on optional tools. If an optional tool is unavailable, fall back to the retrieval ladder.
- Use `jq` and `yq` for structured JSON/YAML transformations instead of brittle line-oriented parsing.
- Use Gitleaks as the deterministic secret scan when the project has no stronger local policy; Raven's optional pre-commit hook runs `gitleaks git --staged` only when Gitleaks is installed, and falls back to `gitleaks protect --staged` when the installed Gitleaks predates 8.19 and lacks the `git` subcommand (its "unknown command" failure would otherwise look identical to a detected leak).
- Use `just audit` (OSV-Scanner) to surface known advisories in dependency lockfiles. It is deliberately not part of `check`: an audit's result changes when a database is published to, not when the tree changes, so as a gate it would fail commits that cannot fix it. Treat findings as evidence to classify — see the Advisory Triage section of the `raven-dependency-update` skill — not as a build break.
- Use `.claude/scripts/raven-tool-check.py` to print recommended-tool status. Agent workflows may use `--write` to cache checked results in `~/.raven/tool-memory.json`.
- `raven-tool-check.py`'s `command_status` defaults to a presence-only check (`shutil.which`; actual execution only under `RAVEN_TOOL_CHECK_EXECUTE=1`), while `raven-run-hook.sh` always executes its candidate launcher with `-c ""` to confirm it actually runs (see that script's own inline comment on the Windows WindowsApps alias trap). This is intentional, not an inconsistency to fix: the interpreter-choice check gates the one thing every hook depends on, and is checked once per hook dispatch, so the cost of an execution probe is cheap and the risk of getting it wrong is high. The tool roster instead reports on many optional tools per session start, where executing every candidate would be too slow, and it is already documented and understood elsewhere as a best-effort inventory rather than a load-bearing dispatch decision.

## Retrieval Discipline

- Do not make Semble the default search path for every task.
- Use `rg` first for exact identifiers, filenames, paths, config keys, logs, errors, and literals.
- Use LSP for definitions, references, call hierarchy, type information, diagnostics, and rename-impact checks.
- Use ast-grep for syntax-aware structural searches and codemod candidates.
- Use Semble for conceptual discovery when relevant code may not share obvious names with the query.
- After Semble returns candidate snippets, verify with `rg`, LSP, targeted file reads, or tests before editing.
- Do not use Semble for exhaustive proof that something does not exist.
- Treat token-reduction claims as retrieval-efficiency claims unless validated end-to-end in the local coding workflow.

## Verification Sources

- Claude Code supports macOS, Windows, Ubuntu, Debian, Alpine, and WSL configurations; native Windows lacks sandboxing while WSL supports it.
- Claude Code hooks support command hooks, and Node-based hook commands are the most portable cross-platform option.
- Claude Code MCP tool search is designed to defer tool definitions until needed, which aligns with token-efficiency goals.
- Semble describes itself as code search for agents and documents Claude Code MCP usage through `uvx --from "semble[mcp]" semble`.
- RTK documents prebuilt binaries for Windows, Linux, and macOS and is designed to compress command output.
- ast-grep is installable through cross-platform package managers including npm, pip, cargo, Homebrew, and Scoop.
- Semgrep documents macOS, Linux, and Windows support, though Windows support should still be validated for team workflows.
- Gitleaks documents Homebrew, Docker, binary, pre-commit, and git scanning modes. Releases >= 8.19 keep `detect`/`protect` hidden/deprecated in favor of `gitleaks git` and `gitleaks git --staged`; releases before 8.19 do not have the `git` subcommand at all, so Raven's pre-commit hook falls back to `gitleaks protect --staged` when it detects an "unknown command" failure.
- OSV-Scanner documents Homebrew, Scoop, WinGet, Arch/Alpine packages, SLSA3 release binaries for Linux/macOS/Windows, and a Go source install. Its documented exit codes are 0 (scanned, clean), 1–126 (result-related, i.e. findings), 127 (general error), 128 (nothing scannable), and 129–255 (other errors); Raven's `audit` recipe classifies these and always exits 0. Supported manifests cover npm, PyPI, crates.io, Go, Hex (`mix.lock`), Maven, RubyGems, NuGet, Composer, Dart, Haskell, R and Conan — there is no Swift (`Package.resolved`) or LuaRocks input, so those two templates ship an `audit` recipe that reports the gap instead of a clean scan.
- jq and yq provide cross-platform install paths and are appropriate for structured transformations, not semantic code discovery.

- `mcp-language-server` documents installation, stdio language-server configuration, and semantic tools including definition, references, diagnostics, hover, and rename in its official repository.
