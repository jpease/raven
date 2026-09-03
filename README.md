# Raven

> Reusable Agentic Verification, Execution, and Navigation

<p align="center">
  <img src="./raven.jpg" alt="Raven mascot" width="58%">
</p>

Raven installs one set of agent instructions — `AGENTS.md`, skills, subagents,
hooks, and rules — into your repositories, then upgrades them in place without
overwriting what you changed. It is for anyone maintaining more than one repo
who would rather not hand-copy the same guidance into each.

**Status:** no tagged release. Installs pin to a commit sha recorded in
`.raven/manifest.json`, and the template file set changes between commits. This
is a fast-moving space, so treat any "best practice" here as a moving target.

## Quick Start

Clone this repository somewhere and note where you put it. Then, from the
repository you want Raven installed into:

```sh
RAVEN_PATH=/path/to/raven
export PATH="$RAVEN_PATH/scripts:$PATH"

cd /path/to/destination-repo
raven install python --dry-run
raven install python
```

Replace `python` with `typescript`, `go`, `rust`, `swift`, `elixir`, `lua`,
`ruby`, or `dotfiles`. For a repo with no language stack — a static site, a docs
tree, an infrastructure repo — use `generic`, which installs the shared guidance
and no gates. Rather not touch `PATH`? Use `"$RAVEN_PATH/scripts/raven"` in
place of `raven`.

To change anything before installing — say, the Claude Code adapter but not
the Codex one — run `raven init <language>` first to write
`.raven/config.toml`, then edit it. Omit the language and Raven prompts for it.

> **NOTE: Your checkout has to preserve symlinks.**
> 
> Raven's templates share files through symlinks, and a checkout that cannot
> create them stores each one as a regular file holding the target path — including
> two Codex security hooks, which would then do nothing.
> 
> `install`, `upgrade`, and `accept` refuse that shape outright, and `raven doctor`
> reports it as an error.
>
> Fix it with `git config --global core.symlinks true` and a fresh clone; a
> flattened checkout cannot be repaired in place.
>
> On Windows, first enable Developer Mode or run git from an elevated shell
> so it is allowed to create symlinks.

## Why Raven

- **Token discipline**: a retrieval order that reaches for `rg`, LSP, and a code index before whole-file reads; noisy commands routed through RTK; and, on Claude Code, a hook that trims oversized command output to its head, its tail, and a file path. The guidance itself costs about 7,800 tokens per step on Claude Code and 3,500 on Codex (`docs/evaluation.md`, `fixed-cost`); whether it saves more than it costs over a task is what `scripts/eval.py` exists to measure, and the answer so far is "not yet shown".
- **Reusable agent setup**: Share guidance, skills, hooks, rules, and docs across repos.
- **Agent adapters**: Keep `AGENTS.md` and `.agents/skills` canonical while installing thin Claude Code and Codex compatibility layers.
- **Language-aware templates**: Start with common behavior, then layer language-specific rules.
- **Safe updates**: Track installed files with `.raven/manifest.json` and only auto-upgrade unchanged Raven-managed files.
- **Local control**: Configure each destination repo with a self-documented `.raven/config.toml`.
- **Low collision surface**: Raven-owned files use the `raven-*` namespace so project-owned guidance can use natural names.

## What Raven Installs

Reusable agent guidance, plus the state needed to upgrade it safely:

- `.raven/config.toml`: human-edited configuration with inline documentation.
- `.raven/manifest.json`: machine-written install state used for safe upgrades.
- `AGENTS.md`: canonical agent instructions, or a guided merge artifact if the file already exists.
- `.agents/skills/`: canonical reusable skills.
- `.claude/settings.json`: managed like any other template file, upgraded in place. `.claude/settings.local.json` is your own local-overrides layer — Raven never manages it.
- `.gitattributes`: append-only. Raven adds the `eol=lf` lines its shipped hooks and scripts need and leaves everything else alone.
- `.ignore`: append-only. Raven adds a `!` negation for each directory it installs guidance into, so `rg`, `fd` and `ast-grep` — which skip dot-directories by default — search the guidance without `--hidden`. Removing the lines only makes that guidance harder to find; it hides nothing else. Skipped when the destination is your home directory itself, where `.claude/` is Claude Code's runtime state rather than shipped guidance.
- Git hooks: three symlinks into git's effective hooks directory (`.git/hooks/` normally) — `commit-msg`, `pre-commit`, and `pre-push`. From then on, every commit runs `just check-fast` (lint + format) and every push runs `just check` (adds typecheck and test) if a justfile is present, blocking on failure; `commit-msg` strips AI-agent attribution trailers rather than blocking. A hook manager or an external `core.hooksPath` already owning that directory (e.g. husky) makes Raven defer to it instead — see `raven doctor` for how to wire Raven's hooks through it. To remove Raven's own hooks, delete the three symlinks.
- `.gitignore`: append-only, the same way as `.gitattributes` and `.ignore` above — entries for `.raven/merge/` and `.claude/settings.local.json`.
- Claude Code and Codex adapter files when enabled in `.raven/config.toml`. Codex loads a project's `.codex/` layer — config, hooks, rules, and agents — only after you trust the project, and runs each hook only after you review it once in `/hooks`. Until both are done the Codex files are installed but inert, and nothing in Codex or Raven says so.
- Starter tool configuration files when the language template ships them and the destination path does not already exist.

## Commands

| Command | Does |
| --- | --- |
| [`raven init <language>`](docs/commands.md#raven-init-language) | Write `.raven/config.toml` so you can configure before installing. |
| [`raven install <language>`](docs/commands.md#raven-install-language) | Copy the template in and record what it wrote. |
| [`raven upgrade`](docs/commands.md#raven-upgrade) | Re-apply the template over an existing install. |
| [`raven accept`](docs/commands.md#raven-accept) | Record a merge you finished by hand. |
| [`raven doctor`](docs/commands.md#raven-doctor) | Read-only health check of the Raven install. |
| [`raven assess`](docs/commands.md#raven-assess) | Grade the project against its template's quality gates. |

`install`, `upgrade`, and `accept` take `--dry-run`. `doctor` and `assess` are
read-only, and `init` writes only `.raven/config.toml`. Full reference:
[docs/commands.md](docs/commands.md).

## When a File Already Exists

Raven does not overwrite files you own. On upgrade it only replaces a managed
file whose content still matches the hash recorded at install time; anything
you edited is reported and left in place, with review artifacts written under
`.raven/merge/` for you to merge by hand. `raven accept` records the
result so later upgrades don't pester you about it.

A few files — `CLAUDE.md`, `.claude/settings.json` — Raven can take over
outright instead, and asks for consent rather than writing a merge artifact.

See [docs/upgrading.md](docs/upgrading.md) for the full rules, including
removal of dropped files, template switching, and line-ending handling.

## More Than One Repository

Every command above runs inside one repository. `raven fleet` is the exception:
it runs from anywhere and reports every repository Raven has been installed
into, which template each uses, and which are behind this checkout.

```sh
raven fleet
```

`install` and `upgrade` record the repository they ran in, so the list builds
itself. It stores paths only -- everything else is read live from each
repository's manifest. See [docs/commands.md](docs/commands.md#raven-fleet).

## Optional Tooling

Raven's templates recommend `rg`, `fd`, `just`, GitNexus, ast-grep, Semgrep,
Gitleaks, OSV-Scanner, Vale, `jq`, `yq`, RTK, and a language server over MCP,
but require none of them. Run `raven doctor` after installing; its Toolchain
section reports which ones you have.

Two of those are named directly in the guidance Raven installs, so it is worth
knowing what they are before you read `AGENTS.md` and wonder: **RTK** is a CLI
proxy that compresses noisy command output before it reaches the model, and
**GitNexus** indexes the repository so an agent can ask what a change would
break. Both are optional. Without RTK the hint that suggests it stays silent;
without a GitNexus index the guidance that leans on it does not apply. Install
commands and the per-language LSP defaults are in
[docs/tooling.md](docs/tooling.md).

## External Skill Libraries

A repository can also depend on a skill library installed outside it, such as a
Claude Code plugin. Declare it and `raven doctor` checks that it is installed,
then lists every lane where one of its skills and a Raven skill claim the same
kind of work:

```toml
[sources.superpowers]
kind = "claude-plugin"
```

Raven neither installs nor vendors the library, and retires none of its own
skills in response. The report exists so that call can be made on evidence.
Details are in [docs/commands.md](docs/commands.md#raven-doctor).

## Repository Layout

Raven-managed paths use `raven-*` wherever possible.

- `common/`: shared policy, skills, subagents, hooks, docs, rules, scripts, and MCP examples.
- `python/`, `swift/`, `rust/`, `typescript/`, `go/`, `elixir/`, `lua/`, `ruby/`, `dotfiles/`: templates that assemble common guidance with stack-specific Raven rules.
- `generic/`: the common-only template for repos with no language stack — shared guidance, no rules file, no gate, no language server.
- `scripts/raven`: executable CLI wrapper for the commands above.
- `scripts/raven.py` and `scripts/raven_lib/`: Python implementation for the CLI.
- `tests/`: applicator tests.
- `evals/` and `scripts/eval.py`: on-demand behavioral evaluation of the shipped guidance.
- `project-skills/`: maintenance-only skills for this repository; not copied into destination repos.

## Developing Raven

Raven's runtime (`scripts/raven.py` + `scripts/raven_lib/`) is stdlib-only, so
*using* Raven needs no dependencies. Developing Raven needs `pytest`, plus
[`uv`](https://docs.astral.sh/uv/) to run it reproducibly:

```sh
just test                             # uv run --group dev python -m pytest, via the justfile
uv run --group dev python scripts/self-check.py
```

`just test` and `just check` resolve their own `uv`-managed dev environment
by default (see `[dependency-groups]` in `pyproject.toml` and the committed
`uv.lock`) -- no manual venv setup needed. Not using `uv`? Install the dev
group into your own interpreter (`python -m pip install --group dev`, pip 25.1
or newer) and
override the launcher: `RAVEN_PYTHON=python just test` or
`just PYTHON='python' test`.

`scripts/eval.py` is the other half, and the one the unit tests cannot cover:
it runs task scenarios through the local `claude` or `codex` CLI, once with
Raven installed and once without, and grades what each run left behind. It
costs real model calls, so it is on-demand and never part of a gate. See
[docs/evaluation.md](docs/evaluation.md) for the method and its limits.

Use `scripts/self-check.py` for the dogfood workflow: it validates this repo's
installed Raven shape, runs self-upgrade dry-run/apply, and then runs the unit
tests. It requires Raven to already be installed here (`.raven/config.toml`
must exist); on a fresh clone run `python scripts/raven.py install <language>`
first.

## License

MIT. See [LICENSE](LICENSE).
