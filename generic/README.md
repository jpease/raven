# Generic Raven Template

Copy this template into the root of a repository that has no language stack: a
static site, a documentation tree, an infrastructure or configuration repo, a
notes tree. Use it wherever none of `python`, `typescript`, `go`, `rust`,
`swift`, `elixir`, `lua`, `ruby`, or `dotfiles` describes what the repo holds.

This directory ships the shared agent guidance from `common/` through symlinks
and adds nothing of its own beyond `.mcp.json` and `.codex/config.toml`.

By design it ships no `justfile`, no quality doc, no rules file, and no starter
tool config. A repo with no build system has no gate for `just check` to run,
and a `raven-generic.md` rules file would have no language whose idioms it could
describe — `AGENTS.md`, `raven-prose.md`, and `raven-security.md` already carry
everything that applies. `.mcp.json` and `.codex/config.toml` declare `semgrep`
and `gitnexus` but no `lsp` server, since there is no language to point
`mcp-language-server` at.

If your repo *is* one of the nine stacks, install that template instead: it adds
the language's rules file, its `just check` gate, and its language server on top
of the same shared files this one installs.

`README.md` is template documentation and is excluded by default when applying
the template.

When copying into a target repo, run the top-level apply script from the
destination root:

```sh
cd /path/to/repo
RAVEN_TEMPLATE=/path/to/raven

python "$RAVEN_TEMPLATE/scripts/raven.py" install generic --dry-run
python "$RAVEN_TEMPLATE/scripts/raven.py" install generic
```

After copying:

- Review `.mcp.json` and remove unavailable MCP servers.
- Review `.claude/settings.json`, `.claude/hooks/`, `.codex/config.toml`, and
  `.codex/hooks.json`; hooks are included for Claude Code and Codex.
- Git hooks are installed for you: `raven install` symlinks `.raven/git-hooks/`
  into the repo's hooks directory. There is no `just install-hooks` recipe here
  and none is needed. With no `justfile` to run, the hooks skip the `just`
  gates and still run the AI-attribution scan, the managed-block integrity
  check, and the gitleaks secret scan.
- Use project-owned files for repo-specific guidance. Avoid editing `raven-*`
  files unless you are intentionally updating the Raven template content.
