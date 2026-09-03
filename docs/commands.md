# Raven Commands

Every command runs from the root of the repository you are installing Raven
into. See the [README](../README.md) for setup and `PATH` notes.

## Running against another repository

`-d`/`--destination` is a global option, placed before the subcommand, that
points any command at a repository other than the current directory:

```sh
raven --destination /path/to/other-repo doctor
raven -d /path/to/other-repo install python
```

Defaults to `.`. `raven fleet` is the one command this does not apply to --
it never runs against a single repository; see below.

## `raven init <language>`

Writes `.raven/config.toml` and nothing else.

```sh
raven init rust
```

Optional — `install` writes the same file if it is missing. Run `init` first
when you want to change something before installation, such as installing the
Claude Code adapter but not the Codex one.

Omit the language and Raven prompts for it.

`--platform {github,gitlab,none}` sets `[issue_tracker].platform` in the
config this writes, which gates which skills get installed (default: `none`).
The same flag on `install` updates it in an existing config too. Without it,
edit `.raven/config.toml` by hand.

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

The language argument is optional once `.raven/config.toml` exists. `--platform`
works the same way it does on `init`, above.

Files that already exist are not overwritten. Depending on the file, Raven
either leaves it alone and writes a merge artifact, or asks to adopt it — see
[Upgrading and Merges](upgrading.md).

Also installs three git hooks — `commit-msg`, `pre-commit`, `pre-push` — as
symlinks into git's effective hooks directory. From then on, every commit and
push is gated: `pre-commit` runs `just check-fast`, `pre-push` runs `just
check`, either blocks on failure, and `commit-msg` strips AI-agent attribution
trailers. See [What Raven Installs](../README.md#what-raven-installs) for the
full breakdown, including how to remove them.

`--include-readme` installs the language template's own `README.md`, which is
excluded by default. It also works on `upgrade` and `accept`, below; on
`accept` it only changes which template entries are recognized as
Raven-managed, since `accept` never copies files.

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

### Codex trust

Codex loads a project's `.codex/` layer — config, hooks, rules, custom agents —
only for a project you have trusted, and skips it silently otherwise. Doctor
reads Codex's own `$CODEX_HOME/config.toml` and reports
`doctor.codex.untrusted` as a warning when no `[projects]` entry covers this
repository or one of its parents, `doctor.codex.unconfigured` as info when
Codex has no config on the machine at all, and an OK finding when the project
is trusted. Each hook additionally needs a one-time review in Codex's `/hooks`;
that state lives outside the config file, so doctor names it but cannot check
it. Skipped when the repository has no `.codex/` directory.

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

## `raven fleet`

Reports every repository Raven has been installed into, and which of them are
behind this checkout.

```sh
raven fleet          # human-readable report
raven fleet --json   # machine-readable
raven fleet --prune  # forget paths that no longer hold a Raven install
```

Unlike every other command here, `fleet` does not run from inside a Raven
repository -- it runs from anywhere. `install` and `upgrade` record the
repository they ran in, in `~/.raven/repos.json`, and `fleet` reads that list.
Set `RAVEN_HOME` to move the file.

The registry stores paths and nothing else. Template, pinned sha, and
staleness are read live from each repository's own `.raven/manifest.json`, so
the only thing it can be wrong about is which directories to look in --
`--prune` fixes that, and a registered path that has gone away is reported as
a warning rather than silently dropped.

`fleet` never upgrades anything. A repository that is behind reports the
command to run and where to run it; which of them is safe to touch right now
is not a question this command can answer. Being behind is a report, not a
broken install, so like `doctor` it exits non-zero only on an `error` finding.

A repository installed before this command existed is not in the registry
until its next `install` or `upgrade`.

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

A recipe can also be unreachable in a third way: it runs the tool and throws
the exit status away. `assess` reports a gate recipe whose body swallows failure
— `|| true`, just's `-` line prefix, or a trailing `exit 0` — because no run can
reveal that one, the tool prints its findings and the recipe exits 0 regardless.
Only the template's declared gate recipes are graded, which is what keeps the
report-only `audit` recipe, whose `exit 0` is deliberate, out of the check.

A gate that `--run` executes is graded on its output as well as its exit code.
A tool that runs, finds nothing to look at, and exits 0 reports the same green
as one that checked every file — so `ruff` warning that it found no Python
files, or `go test` reporting `[no test files]` for every package, is graded
`warn` ("passed without checking anything") rather than `ok`. The warning names
the evidence and does not change the exit code: an inert gate is wiring to fix,
not a failing build. Only tools whose no-work output has been verified have a
detector; `pyright` prints `0 errors, 0 warnings, 0 informations` either way, so
a silent gate is still graded `ok`.

```sh
raven assess          # static wiring checks, runs nothing
raven assess --run    # execute the lint, format, typecheck, and test gates
raven assess --json   # machine-readable, combines with --run
```

Exit `1` when a gate fails or a required config is missing, `0` otherwise.
