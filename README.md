# Raven

> Reusable Agentic Verification, Execution, and Navigation

<p align="center">
  <img src="./raven.jpg" alt="Raven mascot" width="58%">
</p>

Raven is a library to encourage AI coding agents towards effective and efficient behavior.

**Note:** This is a rapidly developing space, so "best practices" is a moving target.

## Project Principles

- **Token discipline**: Prefer targeted retrieval, summaries, and deterministic tools over broad file reads.
- **Reusable agent setup**: Share AGENTS guidance, skills, subagents, hooks, rules, docs, and MCP examples across repos.
- **Agent adapters**: Keep `AGENTS.md` and `.agents/skills` canonical while installing thin Claude Code and Codex compatibility layers.
- **Language-aware templates**: Start with common behavior, then layer language-specific rules.
- **Safe updates**: Track installed files with `.raven/manifest.json` and only auto-upgrade unchanged Raven-managed files.
- **Local control**: Configure each destination repo with a self-documented `.raven/config.toml`.
- **Low collision surface**: Raven-owned files use the `raven-*` namespace so project-owned guidance can use natural names.

## Installation

### 1. Get Raven

Clone, download, or otherwise get a copy of this repo on your local machine and take note of where you put it.

```sh
RAVEN_PATH=/path/to/raven
```

For the cleanest command, add Raven's scripts directory to your PATH:

```sh
export PATH="$RAVEN_PATH/scripts:$PATH"
```

After that, you can run `raven` commands from any destination repository root. If you do not add it to PATH, use `"$RAVEN_PATH/scripts/raven"` in place of `raven` in the commands below.

### 2. Navigate to your project's root

```sh
cd /path/to/destination-repo
```

### 3. Install Raven

#### 3.A Initialize Raven (optional)

```sh
raven init <language>
```

Raven currently has support for Python, TypeScript, Rust, Swift, and Elixir. So for example, if you're using Raven in a Rust project you'd use:

```sh
raven init rust
```

This will generate `.raven/config.toml`. This is optional because running
`install` will also generate the file if it doesn't exist. But if you wish to
configure anything before installation, for example if you wish to
install support for Claude or Codex, instead of both (the default), this is the
way to do it.

See `.raven/config.toml` for inline documentation of the available options.
For example, Raven installs starter formatter/linter config files by default
when the selected language template includes them, but only when the destination
path does not already exist. To opt out before installation, set:

```toml
[components]
tool_configs = false
```

**Tip:** If you omit the language, Raven will prompt you interactively.

#### 3.B Dry Run (optional, but recommended)

```sh
raven install <language> --dry-run
```

**Tip:** If you already configured a language via `raven init`, you can omit the language here.

#### 3.C Run the install command

```sh
raven install <language>
```

The `install` command creates:

- `.raven/config.toml`: human-edited configuration with inline documentation
- `.raven/manifest.json`: machine-written install state used for safe upgrades
- All Raven files (use --dry-run to see the full list)

## Upgrade Raven

### 1. Get a new version of Raven

Pull, download, or otherwise get the latest copy of this repo on your local machine and take note of where you put it.

### 2 Dry Run (optional, but recommended)

```sh
raven upgrade --dry-run
```

### 3. Run the upgrade command

```sh
raven upgrade
```

### Upgrade Behavior

Dry runs separate files into clear categories:

- New Raven files to be copied
- Unmodified Raven files that will safely be upgraded
- Raven files that are already up to date
- Locally modified Raven files requiring a manual merge
- File name conflicts requiring a manual merge
- Excluded template/configured files

Raven overwrites only explicit override paths and managed files whose current content still matches the last installed manifest hash. Existing project-owned content is preserved by default.

## AGENTS.md and CLAUDE.md

When `AGENTS.md` or `CLAUDE.md` already exists, Raven does not replace it. On install, it writes guided merge artifacts under `.raven/merge/`:

- `AGENTS.md.raven` or `CLAUDE.md.raven`: the Raven-suggested content or symlink guidance.
- `*.instructions.md`: a short merge note for the project owner.
- `*.patch`: an append-only patch when Raven can represent the suggestion safely as text.

Raven treats `AGENTS.md` as canonical and normally installs `CLAUDE.md` as a symlink to `AGENTS.md`. If a destination repo already has a `CLAUDE.md` file, Raven leaves it alone by default. To explicitly adopt the Raven compatibility symlink, answer Y when prompted or run with `--adopt-claude-symlink`. In that case, Raven moves the existing file to `CLAUDE.md.bak`. If that backup already exists, Raven will fail instead of overwriting it.

The generated `AGENTS.md` patch wraps Raven guidance in a marked block with a content hash. If that block is applied and left unchanged, later `upgrade` runs can limit updates to the Raven block, preserving project-owned content elsewhere in `AGENTS.md`. If the Raven block is edited, a Raven upgrade will report it as requiring manual merge.

## Forcing Overwrites

By default, Raven will not overwrite a file you have edited locally — even if it is Raven-managed. To force a specific file back to the template version, pass its template-relative path as an argument:

```sh
raven upgrade .claude/scripts/raven-tool-check.py
```

This force-copies only the named file and leaves everything else untouched. Use `install` instead of `upgrade` when `.raven/config.toml` does not yet exist:

```sh
raven install python .claude/scripts/raven-tool-check.py
```

You can name multiple paths in a single command. The path must match the template layout exactly — run `raven upgrade --dry-run` first to see the canonical names if you are unsure.

## Namespace & Layout

Raven-managed paths use `raven-*` wherever possible.

- `common/`: shared policy, skills, subagents, hooks, docs, rules, scripts, and MCP examples.
- `python/`, `swift/`, `rust/`, `typescript/`, `elixir/`: language templates that assemble common guidance with language-specific Raven rules.
- `scripts/raven`: executable CLI wrapper for `raven install` and `raven upgrade`.
- `scripts/raven.py`: Python implementation for the `init`, `install`, and `upgrade` subcommands.
- `tests/`: applicator tests.
- `project-skills/`: maintenance-only skills for this repository; not copied into destination repos.

## Tool Bootstrap

After installing Raven in a repository, you can print a report for recommended but optional tools:

```sh
python .claude/scripts/raven-tool-check.py
```

For Codex installations, the equivalent script is:

```sh
python .codex/scripts/raven-tool-check.py
```

If `python` is not the right launcher, use that repo's configured launcher, such as `python3`, `py -3`, or an active virtual environment.

The SessionStart hook can also run this check automatically for Claude Code or Codex when the corresponding adapter is enabled. Agent-facing workflows can cache results in `~/.raven/tool-memory.json` so users are not repeatedly prompted about the same tools.

### Checked Tools

Raven treats these as recommended capabilities, not mandatory dependencies. If a tool is not installed or configured, agents should use the retrieval ladder and fall back to cheaper deterministic tools.

On Windows, prefer WSL when the target repository is POSIX-heavy or already uses Linux/macOS shell tooling. Native Windows is reasonable for Windows-native projects, but PATH handling and language-server installation should be verified per machine.

| Tool                  | Why Raven checks for it                                                                   | Windows | Install/docs                                                    |
| --------------------- | ----------------------------------------------------------------------------------------- | ------- | --------------------------------------------------------------- |
| `rg` / ripgrep        | Exact strings, symbols, errors, filenames, config keys, and exhaustive confirmation.      | Yes     | [Link](https://github.com/BurntSushi/ripgrep#installation)      |
| `fd`                  | Fast file discovery by name, extension, type, or pattern.                                 | Yes     | [Link](https://github.com/sharkdp/fd#installation)              |
| `just`                | Task runner for test, lint, format, typecheck, and hook installation.                     | Yes     | [Link](https://just.systems/man/en/)                            |
| `uvx` / uv            | Runs Python-packaged tools such as Semble MCP without adding a project dependency.        | Yes     | [Link](https://docs.astral.sh/uv/getting-started/installation/) |
| Semble                | Intent-based code search when the owning file or symbol is unknown.                       | Likely  | [Link](https://minish.ai/packages/semble/installation/)         |
| GitNexus              | Code graph, dependency, call-path, and blast-radius reasoning.                            | Likely  | [Link](https://github.com/nxpatterns/gitnexus)                  |
| `mcp-language-server` | General LSP-over-MCP fallback for definition, references, diagnostics, and rename safety. | Likely  | [Link](https://github.com/isaacphi/mcp-language-server)         |
| ast-grep              | Syntax-aware search and mechanical rewrites.                                              | Yes     | [Link](https://ast-grep.github.io/guide/quick-start.html)       |
| Semgrep               | Security, policy, and multi-language static-analysis rules.                               | Yes     | [Link](https://semgrep.dev/docs/getting-started/cli)            |
| RTK                   | Compresses noisy command output before it enters model context.                           | Yes     | [Link](https://github.com/rtk-ai/rtk/tree/master)               |

Language templates include `.mcp.json` defaults for Semble, GitNexus, and LSP. For LSP, Raven uses `mcp-language-server` as the general fallback when the agent client does not already provide a reliable native/plugin LSP integration. The default language servers are:

| Template   | LSP command in `.mcp.json`           |
| ---------- | ------------------------------------ |
| Python     | `pyright-langserver --stdio`         |
| TypeScript | `typescript-language-server --stdio` |
| Rust       | `rust-analyzer`                      |
| Swift      | `sourcekit-lsp`                      |
| Elixir     | `expert`                             |

Install `mcp-language-server` and the language server for the template you chose from their official documentation. Raven includes the `.mcp.json` command shape; see `.claude/docs/raven-lsp-mcp.md` after installation for official documentation links and template-specific command shapes.

See `.claude/docs/raven-lsp-mcp.md` and `.claude/docs/raven-tool-assessment.md` after installation for the agent-facing details.

## Development

```sh
python -m unittest discover -s tests
python scripts/self-check.py
```

Use `python scripts/self-check.py` for the dogfood workflow: it validates this repo's installed Raven shape, runs self-upgrade dry-run/apply, and then runs the unit tests. `self-check.py` requires Raven to already be installed in this repo (`.raven/config.toml` must exist); run `python scripts/raven.py install <language>` first if you have a fresh clone.

Project-local maintenance skills live under `project-skills/`; destination-facing files live in `common/` or language template directories.

## License

MIT. See [LICENSE](LICENSE).
