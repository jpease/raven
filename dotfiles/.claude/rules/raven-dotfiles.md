# Dotfiles Rules

## Applicability

Use these rules when editing home-directory configuration: shell startup files
(bash, zsh, fish, PowerShell), editor config (Neovim/Vim, VS Code, Emacs),
window-manager, compositor, and terminal config, and application config under
`~/.config` or `$HOME`, in any format (toml, yaml, json, ini, lua, shell).

Project-specific `AGENTS.md`, local docs, and an existing dotfiles management
tool's conventions override this file when they are more specific.

## Source Of Truth (read before any edit)

The live file at its runtime path is frequently NOT the file you should edit.

- Determine whether the file is the real source or a symlinked/rendered artifact of
  a managed source tree BEFORE editing.
- Never edit a symlink target in place; follow the link and edit the source.
- Never edit a generated/rendered file; edit the source that produces it, then
  re-render.
- Treat the management tool as unknown and investigate. Common patterns, as
  examples only (the ecosystem grows — do not assume this list is complete):
  - Symlink farms (e.g. GNU Stow): the live file is a symlink into a `dotfiles/`
    repo.
  - Rendered source trees (e.g. chezmoi): the live file is generated from a source
    dir; edit the source and apply.
  - VCS-tracked home (e.g. bare-git, yadm): the live file is real but tracked;
    commit deliberately.
  - Declarative generation (e.g. Nix home-manager): the live file is read-only and
    regenerated from configuration.
- If you cannot determine the source of truth, STOP and ask rather than editing the
  live file. See the `raven-dotfiles` skill for the step-by-step workflow.

## Apply Discipline

- Editing a config does not make it take effect. State the apply/reload step
  explicitly (source the file, reload the daemon, run the manager's apply).
- Never auto-apply. The user runs apply/reload.
- Warn that a bad config can fail late — only at next login, shell start, daemon
  reload, or display-manager restart — not at edit time.

## Pause And Ask

In addition to AGENTS.md guardrails, pause before editing config that can lock the
user out or only fails late:

- login shells and shell startup files that abort the session on error
- ssh client/server config, `authorized_keys`, PAM, or sudoers-adjacent files
- display manager, window manager, or compositor startup
- anything that requires a reboot or re-login to validate

## Secrets

- Dotfiles are secret-dense: ssh keys/config, `~/.aws`, `~/.netrc`, `.env` files,
  tokens, and API keys.
- Never commit config without a secrets scan (gitleaks if available).
- Never paste secret-bearing config into external tools or logs.
- Prefer references to a secret store over inline secrets when adding new config.

## Verification

Dotfiles have no build or test suite. Use, in order:

1. Syntax/lint validators for the format (the `raven-dotfiles` skill has the
   per-format table).
2. A dry-run or diff before applying on managed trees.
3. A captured revert path (copy or VCS stash) before risky edits.
4. A secrets scan before any commit.
