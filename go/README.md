# Go Raven Template

Copy this template into the root of a Go repository with `scripts/raven.py` from this repository.

This directory assembles:

- shared agent guidance from `common/`
- Go-specific Raven rules in `.claude/rules/raven-go.md`
- Go quality reference material in `.claude/docs/raven-go-quality.md`
- a starter `.golangci.yml` for `golangci-lint`

`README.md` is template documentation and is excluded by default when applying the template.

When copying into a project, run the top-level apply script from the destination repository root:

```sh
cd /path/to/go-project
RAVEN_TEMPLATE=/path/to/raven

python "$RAVEN_TEMPLATE/scripts/raven.py" install go --dry-run
python "$RAVEN_TEMPLATE/scripts/raven.py" install go
```

After copying:

- Run `just install-hooks` to add a pre-commit hook (`just check-fast` — fast format and lint checks) and a pre-push hook (`just check` — the full format, vet, lint, and test gate), or wire those commands into existing hooks manually.
- Use project-owned files for project-specific guidance. Avoid editing `raven-*` files unless you are intentionally updating the Raven template content.
