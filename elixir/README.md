# Elixir Raven Template

Copy this template into the root of an Elixir or Phoenix repository with `scripts/raven` from this repository.

This directory assembles:

- shared agent guidance from `common/`
- Elixir-specific Raven rules in `.claude/rules/raven-elixir.md`
- Elixir quality reference material in `.claude/docs/raven-elixir-quality.md`
- an Elixir MCP example using Expert as the default language server

`README.md` is template documentation and is excluded by default when applying the template.

When copying into a project, run the top-level Raven command from the destination repository root:

```sh
cd /path/to/elixir-project
RAVEN_TEMPLATE=/path/to/raven

"$RAVEN_TEMPLATE/scripts/raven" install elixir --dry-run
"$RAVEN_TEMPLATE/scripts/raven" install elixir
```

If this repository's `scripts/` directory is on your `PATH`, use:

```sh
raven install elixir --dry-run
raven install elixir
```

After copying:

- Run `just install-hooks` to add a pre-commit hook (`just check-fast` — fast lint and format checks) and a pre-push hook (`just check` — the full lint, type, and test gate), or wire those commands into existing hooks manually.
- Use project-owned files for project-specific guidance. Avoid editing `raven-*` files unless you are intentionally updating the Raven template content.
