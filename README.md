# Raven

> Reusable Agentic Verification, Execution, and Navigation

<p align="center">
  <img src="./raven.jpg" alt="Raven mascot" width="58%">
</p>

Raven is a library to encourage AI coding agents towards effective and efficient behavior.

**Note:** This is a rapidly developing space, so "best practices" is a moving target.

## Quick Start

From the repository where you want Raven installed:

```sh
RAVEN_PATH=/path/to/raven
export PATH="$RAVEN_PATH/scripts:$PATH"

cd /path/to/destination-repo
raven install python --dry-run
raven install python
```

Replace `python` with `typescript`, `go`, `rust`, `swift`, `elixir`, `lua`, or `dotfiles`.

If you prefer not to edit `PATH`, use `"$RAVEN_PATH/scripts/raven"` in place of `raven`.

## What Raven Installs

Raven installs reusable agent guidance and the state needed to upgrade it safely:

- `.raven/config.toml`: human-edited configuration with inline documentation.
- `.raven/manifest.json`: machine-written install state used for safe upgrades.
- `AGENTS.md`: canonical agent instructions, or a guided merge artifact if the file already exists.
- `.agents/skills/`: canonical reusable skills.
- Claude Code and Codex adapter files when enabled in `.raven/config.toml`.
- Optional starter tool configuration files when the selected language template includes them and the destination path does not already exist.

## Install Into a Repository

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

### 2. Navigate to the destination repository

```sh
cd /path/to/destination-repo
```

### 3. Initialize Raven (optional)

```sh
raven init <language>
```

Raven currently has support for Python, TypeScript, Go, Rust, Swift, Elixir, Lua, and dotfiles. So for example, if you're using Raven in a Rust project you'd use:

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

### 4. Preview the install

```sh
raven install <language> --dry-run
```

**Tip:** If you already configured a language via `raven init`, you can omit the language here.

### 5. Install Raven

```sh
raven install <language>
```

Use `--dry-run` to see the full list of files before writing them.

## Upgrade an Existing Installation

### 1. Get a new version of Raven

Pull, download, or otherwise get the latest copy of this repo on your local machine and take note of where you put it.

### 2. Preview the upgrade

```sh
raven upgrade --dry-run
```

### 3. Upgrade Raven

```sh
raven upgrade
```

### Upgrade behavior

Dry runs separate files into clear categories:

- New Raven files to be copied
- Unmodified Raven files that will safely be upgraded
- Raven files that are already up to date
- Locally modified Raven files requiring a manual merge
- File name conflicts requiring a manual merge
- Excluded template/configured files

Raven overwrites only explicit override paths and managed files whose current content still matches the last installed manifest hash. Existing project-owned content is preserved by default.

## Merge Behavior for AGENTS.md and CLAUDE.md

When `AGENTS.md` or `CLAUDE.md` already exists, Raven does not replace it. On install, it writes guided merge artifacts under `.raven/merge/`:

- `AGENTS.md.raven` or `CLAUDE.md.raven`: the Raven-suggested content or symlink guidance.
- `*.instructions.md`: a short merge note for the project owner.
- `*.patch`: an append-only patch when Raven can represent the suggestion safely as text.

Raven treats `AGENTS.md` as canonical and normally installs `CLAUDE.md` as a symlink to `AGENTS.md`.

- If a destination repo already has a `CLAUDE.md` file, Raven leaves it alone by default.
- To explicitly adopt the Raven compatibility symlink, answer Y when prompted or run with `--adopt-claude-symlink`.
- When adoption is enabled, Raven moves the existing file to `CLAUDE.md.bak`.
- If that backup already exists, Raven fails instead of overwriting it.

The generated `AGENTS.md` patch wraps Raven guidance in a marked block with a content hash. If that block is applied and left unchanged, later `upgrade` runs can limit updates to the Raven block, preserving project-owned content elsewhere in `AGENTS.md`. If the Raven block is edited, a Raven upgrade will report it as requiring manual merge.

## Finish a Manual Merge with `raven accept`

For any conflicting file — a locally modified Raven-managed file, or an existing file Raven does not yet track — Raven leaves your file untouched and writes review artifacts under `.raven/merge/`:

- `<file>.raven`: the current template version.
- `<file>.diff`: a review-only diff from your file to the template (for non-instruction files).
- `<file>.instructions.md`: how to merge.

After you merge the template's changes by hand, record the result so future upgrades stop re-prompting:

```sh
raven accept            # accept every pending merge under .raven/merge/
raven accept .mcp.json  # or accept specific paths
```

`accept` records your merged file as the new baseline — its current content plus the current template version — and removes the merge artifacts. A later `raven upgrade` then reports the file as up to date until Raven's template changes again, at which point it is surfaced for merge once more rather than silently overwriting your customizations. Preview with `raven accept --dry-run`.

## Restore a Raven-Managed File

By default, Raven will not overwrite a file you have edited locally — even if it is Raven-managed. To force a specific file back to the template version, pass its template-relative path as an argument:

```sh
raven upgrade .claude/scripts/raven-tool-check.py
```

This force-copies only the named file and leaves everything else untouched. Use `install` instead of `upgrade` when `.raven/config.toml` does not yet exist:

```sh
raven install python .claude/scripts/raven-tool-check.py
```

You can name multiple paths in a single command. The path must match the template layout exactly — run `raven upgrade --dry-run` first to see the canonical names if you are unsure.

## Optional Tool Bootstrap

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

Raven treats checked tools as recommended capabilities, not mandatory dependencies. If a tool is not installed or configured, agents should use the retrieval ladder and fall back to cheaper deterministic tools.

Recommended tools include `rg`, `fd`, `just`, `uvx`, Semble, GitNexus, `mcp-language-server`, ast-grep, Semgrep, Gitleaks, `jq`, `yq`, and RTK.

On Windows, prefer WSL when the target repository is POSIX-heavy or already uses Linux/macOS shell tooling. Native Windows is reasonable for Windows-native projects, but PATH handling and language-server installation should be verified per machine.

Language templates include `.mcp.json` defaults for Semble, GitNexus, and LSP. For LSP, Raven uses `mcp-language-server` as the general fallback when the agent client does not already provide a reliable native/plugin LSP integration. The default language servers are:

| Template   | LSP command in `.mcp.json`           |
| ---------- | ------------------------------------ |
| Python     | `pyright-langserver --stdio`         |
| TypeScript | `typescript-language-server --stdio` |
| Go         | `gopls`                              |
| Rust       | `rust-analyzer`                      |
| Swift      | `sourcekit-lsp`                      |
| Elixir     | `expert`                             |
| Lua        | `lua-language-server`                |

Install `mcp-language-server` and the language server for the template you chose from their official documentation. Raven includes the `.mcp.json` command shape; see `.claude/docs/raven-lsp-mcp.md` after installation for official documentation links and template-specific command shapes.

See [raven-lsp-mcp.md](.claude/docs/raven-lsp-mcp.md) and [raven-tool-assessment.md](.claude/docs/raven-tool-assessment.md) after installation for the agent-facing details.

## Why Raven Works

- **Token discipline**: Prefer targeted retrieval, summaries, and deterministic tools over broad file reads.
- **Reusable agent setup**: Share AGENTS guidance, skills, subagents, hooks, rules, docs, and MCP examples across repos.
- **Agent adapters**: Keep `AGENTS.md` and `.agents/skills` canonical while installing thin Claude Code and Codex compatibility layers.
- **Language-aware templates**: Start with common behavior, then layer language-specific rules.
- **Safe updates**: Track installed files with `.raven/manifest.json` and only auto-upgrade unchanged Raven-managed files.
- **Local control**: Configure each destination repo with a self-documented `.raven/config.toml`.
- **Low collision surface**: Raven-owned files use the `raven-*` namespace so project-owned guidance can use natural names.

## Repository Layout

Raven-managed paths use `raven-*` wherever possible.

- `common/`: shared policy, skills, subagents, hooks, docs, rules, scripts, and MCP examples.
- `python/`, `swift/`, `rust/`, `typescript/`, `go/`, `elixir/`, `lua/`, `dotfiles/`: templates that assemble common guidance with stack-specific Raven rules.
- `scripts/raven`: executable CLI wrapper for `raven init`, `raven install`, and `raven upgrade`.
- `scripts/raven.py` and `scripts/raven_lib/`: Python implementation for the CLI.
- `tests/`: applicator tests.
- `project-skills/`: maintenance-only skills for this repository; not copied into destination repos.

## Developing Raven

```sh
python -m unittest discover -s tests
python scripts/self-check.py
```

Use `python scripts/self-check.py` for the dogfood workflow: it validates this repo's installed Raven shape, runs self-upgrade dry-run/apply, and then runs the unit tests. `self-check.py` requires Raven to already be installed in this repo (`.raven/config.toml` must exist); run `python scripts/raven.py install <language>` first if you have a fresh clone.

Project-local maintenance skills live under `project-skills/`; destination-facing files live in `common/` or language template directories.

## License

MIT. See [LICENSE](LICENSE).
