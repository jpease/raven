# Dotfiles Raven Template

Copy this template into the root of a dotfiles / home-directory config tree with
`scripts/raven.py` from this repository. The target may be `~/.config`, a
`dotfiles/` repository, or any home-directory config layout — managed by chezmoi,
stow, yadm, bare-git, Nix home-manager, or nothing at all.

This directory assembles:

- shared agent guidance from `common/`
- dotfiles-specific Raven rules in `.claude/rules/raven-dotfiles.md`
- the `raven-dotfiles` skill (shared from `common/.agents/skills/`), which carries
  the edit → locate-source → validate → apply → secrets-scan workflow

By design this stack ships no `justfile`, no quality doc, and no tool-config file:
dotfiles have no single build or test gate, and the target is often not a git repo.

`README.md` is template documentation and is excluded by default when applying the
template.

When copying into a target tree, run the top-level apply script from the
destination root:

```sh
cd /path/to/dotfiles
RAVEN_TEMPLATE=/path/to/raven

python "$RAVEN_TEMPLATE/scripts/raven.py" install dotfiles --dry-run
python "$RAVEN_TEMPLATE/scripts/raven.py" install dotfiles
```

After copying:

- Editing a config is never the same as applying it. Find the source of truth
  before editing (the live file may be a symlink or a generated artifact), state
  the apply/reload step, and scan for secrets before any commit. The
  `raven-dotfiles` rule and skill enforce this.
- Use project-owned files for setup-specific guidance. Avoid editing `raven-*`
  files unless you are intentionally updating the Raven template content.
