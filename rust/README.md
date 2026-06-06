# Rust Raven Template

Copy this template into the root of a Rust repository with `scripts/raven.py` from this repository.

This directory assembles:

- shared agent guidance from `common/`
- Rust-specific Raven rules in `.claude/rules/raven-rust.md`
- Rust quality reference material in `.claude/docs/raven-rust-quality.md`

`README.md` is template documentation and is excluded by default when applying the template.

When copying into a project, run the top-level apply script from the destination repository root:

```sh
cd /path/to/rust-project
RAVEN_TEMPLATE=/path/to/raven

python "$RAVEN_TEMPLATE/scripts/raven.py" install rust --dry-run
python "$RAVEN_TEMPLATE/scripts/raven.py" install rust
```

After copying:

- Run `just install-hooks` to add a pre-commit git hook that runs `just check`, or add `just check` manually to an existing hook.
- Use project-owned files for project-specific guidance. Avoid editing `raven-*` files unless you are intentionally updating the Raven template content.
