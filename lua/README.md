# Lua Raven Template

Copy this template into the root of a Lua repository with `scripts/raven.py` from this repository.

This directory assembles:

- shared agent guidance from `common/`
- Lua-specific Raven rules in `.claude/rules/raven-lua.md`
- Lua quality reference material in `.claude/docs/raven-lua-quality.md`
- a starter `stylua.toml` for StyLua and `.luacheckrc` for luacheck

`README.md` is template documentation and is excluded by default when applying the template.

When copying into a project, run the top-level apply script from the destination repository root:

```sh
cd /path/to/lua-project
RAVEN_TEMPLATE=/path/to/raven

python "$RAVEN_TEMPLATE/scripts/raven.py" install lua --dry-run
python "$RAVEN_TEMPLATE/scripts/raven.py" install lua
```

After copying:

- Run `just install-hooks` to add a pre-commit hook (`just check-fast` — fast format and lint checks) and a pre-push hook (`just check` — the full format, lint, and test gate), or wire those commands into existing hooks manually.
- Use project-owned files for project-specific guidance. Avoid editing `raven-*` files unless you are intentionally updating the Raven template content.
