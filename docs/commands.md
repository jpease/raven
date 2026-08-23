# Raven Commands

Every command runs from the root of the repository you are installing Raven
into. See the [README](../README.md) for setup and `PATH` notes.

## `raven init <language>`

Writes `.raven/config.toml` and nothing else.

```sh
raven init rust
```

Optional — `install` writes the same file if it is missing. Run `init` first
when you want to change something before installation, such as installing the
Claude Code adapter but not the Codex one.

Omit the language and Raven prompts for it.

`.raven/config.toml` documents its own options inline. One worth knowing up
front: Raven installs starter formatter and linter config files when the
language template ships them and the destination path does not already exist.
To skip them:

```toml
[components]
tool_configs = false
```

## `raven install <language>`

Copies the template into the current repository and records what it wrote in
`.raven/manifest.json`.

```sh
raven install python --dry-run   # list every file first
raven install python
```

The language argument is optional once `.raven/config.toml` exists.

Files that already exist are not overwritten. Depending on the file, Raven
either leaves it alone and writes a merge artifact, or asks to adopt it — see
[Upgrading and Merges](upgrading.md).

## `raven upgrade`

Re-applies the current template over an existing installation.

```sh
raven upgrade --dry-run
raven upgrade
```

Raven only overwrites a managed file whose content still matches the hash
recorded at install time. Anything you edited is reported and left in place.
[Upgrading and Merges](upgrading.md) covers the rules in full, including
removal of files the template no longer ships and switching templates.

### Restoring one file

By default Raven will not overwrite a file you edited, even a Raven-managed
one. Pass a template-relative path to force that single file back to the
template version:

```sh
raven upgrade .claude/scripts/raven-tool-check.py
```

Everything else is untouched. You can name several paths in one command. The
path has to match the template layout exactly — run `raven upgrade --dry-run`
first if you are unsure of the spelling.

Use `install` instead when `.raven/config.toml` does not exist yet:

```sh
raven install python .claude/scripts/raven-tool-check.py
```

## `raven accept`

Records a merge you finished by hand so later upgrades stop re-prompting.

```sh
raven accept --dry-run  # preview
raven accept            # accept everything under .raven/merge/
raven accept .mcp.json  # or named paths only
```

See [Upgrading and Merges](upgrading.md#finishing-a-merge-with-raven-accept)
for what "accept" records and when the file shows up again.

## `raven doctor`

Read-only health check of Raven's own installation in this repository: config,
manifest, enabled components, the `AGENTS.md` root instruction file, declared
external sources, and the local toolchain.

```sh
raven doctor          # human-readable report
raven doctor --json   # machine-readable
```

Exit `1` means at least one `error` finding. Exit `0` means only warnings or
OK findings — a missing optional tool is a warning, not a failure.

### Sources

A repository can declare a skill library that is installed outside it, such as
a Claude Code plugin:

```toml
[sources.superpowers]
kind = "claude-plugin"
required = false
```

Doctor reports whether that plugin is installed, reading Claude Code's own
plugin registry, and then lists every lane where one of its skills and a Raven
skill claim the same kind of work — naming both skills and which one Raven
prefers. Raven neither installs nor vendors the library; declaring it only asks
for the check.

Collisions are informational and never change the exit code. `required = true`
turns a missing source into an `error`, for a repository whose workflow depends
on it. A registry Raven cannot read stays a warning either way, because "cannot
tell" is a weaker claim than "not installed". A repository with no `.claude/`
directory can reach no Claude plugin, and the whole section is skipped.

## `raven assess`

Grades the project against its template's quality-gate expectations: justfile
recipe wiring, tool-config signals, the pre-commit hook, and template fit.
Static checks only unless you pass `--run`.

A declared recipe is graded separately from a gated one. Both hooks run `just
check`, so a recipe `check` never reaches is one no commit and no push can fail
on, and `assess.wiring.check` reports how many declared gate recipes the push
gate actually runs. A template that keeps `test` out of `check` deliberately —
swift does, because an Xcode UI suite is too heavy for every push — reports
that exclusion as `info` instead of grading it as a defect.

```sh
raven assess          # static wiring checks, runs nothing
raven assess --run    # execute the lint, format, typecheck, and test gates
raven assess --json   # machine-readable, combines with --run
```

Exit `1` when a gate fails or a required config is missing, `0` otherwise.
