# Dotfiles Raven Stack — Design

**Date:** 2026-06-14
**Status:** Approved design, pending implementation plan
**Topic:** A new `dotfiles` template stack for editing home-directory configuration with agentic tools.

## Problem

Raven ships per-language stacks (`python/`, `go/`, `rust/`, …) that give an agent
targeted guardrails and tooling for a codebase. There is no equivalent for the
home-directory configuration domain (`~/.config`, shell rc files, editor config,
window-manager config, app configs). Editing dotfiles with Claude/Codex has
domain-specific hazards the language stacks do not address:

- The live file is often **not** the source of truth — it may be a symlink target
  or a rendered artifact of a managed source tree. Editing it in place is wrong
  and can be silently overwritten.
- The target **may or may not be a git repo**, and may be managed by any of a
  growing set of tools (chezmoi, stow, yadm, bare-git, Nix home-manager, …) or by
  nothing at all.
- There is **no compiler, test suite, or build** to act as a verification gate.
- Configs are **secret-dense** (ssh, aws, netrc, env files, tokens).
- Bad configs frequently **fail late** — only at next login, shell start, daemon
  reload, or display-manager restart — so an edit can look fine and still lock the
  user out.

## Goals

- Give an agent full-parity guidance for the dotfiles domain: guardrails plus a
  deterministic edit/validate/apply workflow.
- Be **tool-agnostic and extensible** — durable against new dotfile managers
  appearing over time. No hardcoded manager list as the load-bearing mechanism.
- Substitute a meaningful **verification model** for the missing test/build gate.
- Stay self-contained: depend only on what ships with Raven, Claude Code, or
  Codex. No dependency on user-local or third-party skills.

## Non-Goals (v1)

- A `justfile` of recipes. Cut: graceful no-op-when-not-a-repo logic is fiddly and
  the target often lacks a repo or `just`; the skill tells the agent which
  validator to run directly.
- A `.shellcheckrc` (or other) tool-config file. Cut: marginal value and a clobber
  risk when dropped into a home dir.
- A separate `raven-dotfiles-quality.md` deep doc. Cut: its per-format validator
  table and apply matrix are folded, in compact form, into the skill instead.
- Renaming the installer's "languages" terminology to "stacks". Out of scope; the
  picker will list `dotfiles` as-is.

## Design Decisions (from brainstorming)

1. **Primary job:** full template — both guardrails and a verification/workflow
   model, adapted to the dotfiles domain.
2. **Management model:** tool-agnostic principles as the durable backbone (find the
   source of truth before editing; never edit a symlink target or generated file in
   place), with a lightweight, *explicitly-extensible* heuristic that names common
   tools only as examples. No brittle detector script to maintain.
3. **Verification model (all four pillars):** syntax/lint validators; reload/apply
   discipline (never auto-apply; flag late failures); dry-run/backup before risky
   edits; secrets scan before any commit.
4. **Scaffolding:** degrade gracefully in a non-repo home dir.
5. **v1 surface:** **rule + skill only.**
6. **Shells covered:** bash, zsh, fish, powershell.
7. **No external-skill dependency:** the source-of-truth/apply workflow is fully
   self-contained in the Raven-owned skill.
8. **Skill location (resolved during planning):** skills are shared across stacks
   via `common/.agents/skills/` (each stack symlinks `.agents/skills` to it). There
   is no stack-local skill mechanism, so `raven-dotfiles` lives in
   `common/.agents/skills/raven-dotfiles/` and ships to every install, dormant
   until its description triggers on dotfiles editing.
9. **LSP omitted (resolved during planning):** dotfiles span many formats with no
   single language server, so the stack's `.mcp.json` and `.codex/config.toml` omit
   the `lsp` MCP server entirely (keeping semgrep/semble/gitnexus). The per-stack
   LSP-defaults tests only check the six named languages, so dotfiles is unaffected.

## Architecture

The `dotfiles` stack is a new top-level template dir, a sibling of the language
stacks. Stacks are **auto-discovered** by the installer (`list_language_templates`
in `scripts/raven_lib/cli.py` enumerates top-level dirs not in
`NON_TEMPLATE_DIRS` and not dot-prefixed), so creating the directory *is* the
registration — no code change is required to make it selectable.

The stack reuses the entire shared base tree unchanged (root `AGENTS.md`/`CLAUDE.md`,
`.claude/` and `.codex/` agents/hooks/scripts/settings, shared `raven-*` skills).
Only the differentiators below are new.

### Components

**1. `dotfiles/.claude/rules/raven-dotfiles.md` (always loaded)**
Mirrors the structure of `raven-python.md`, domain-shifted:

- **Applicability** — shell/editor/WM/app configs in any format; target may or may
  not be a repo; may be managed by an external tool.
- **Source of truth (core rule, tool-agnostic)** — before editing any config,
  determine whether the live file is the real file or a rendered/symlinked artifact
  of a managed source. Never edit a symlink target or generated file in place; find
  and edit the source. A short, explicitly-extensible heuristic names common
  patterns (symlink chains; a managed source tree under `~/.local/share/*` or a
  `dotfiles/` repo; a VCS-tracked home) as *examples*, with a standing instruction
  to investigate rather than assume.
- **Pause-and-ask** — for edits that only fail at next login/restart (login shell,
  display manager, WM, PAM/ssh) or that could lock the user out (sshd,
  sudoers-adjacent).
- **Secrets** — configs are secret-dense; never commit without a secrets scan;
  never paste secret-bearing config into external tools.

The rule ships as a real file at `dotfiles/.claude/rules/raven-dotfiles.md`,
matching the existing per-stack pattern (e.g. `go/.claude/rules/raven-go.md`).
`dotfiles/.codex/rules` stays a symlink to `common/.codex/rules`, exactly like the
language stacks — the per-stack rule is Claude-side only, a known limitation shared
with every existing stack and out of scope to change here.

**2. `common/.agents/skills/raven-dotfiles/SKILL.md` (on demand, global)**
The Raven-owned edit/validate/apply workflow, invoked when editing managed
dotfiles. Steps:

1. Locate the source of truth (apply the rule's heuristic; investigate symlinks /
   managed trees).
2. Capture a revert path (git stash/diff, or a copy) before any risky edit; prefer
   dry-run/diff over in-place edits on managed trees.
3. Edit the source, not the live artifact.
4. Validate syntax with the per-format validator (compact table, below). Skip
   validators that are not installed; never claim verification that did not run.
5. State the apply step (source the file, reload the daemon, run the manager's
   apply). **Never auto-apply.** Flag that a bad config may only surface at next
   login/restart.
6. Secrets-scan (gitleaks if present) before any commit.

Compact validator/apply reference folded into the skill:

| Format | Syntax/lint check |
|---|---|
| bash/sh | `shellcheck` |
| zsh | `zsh -n` (shellcheck zsh support is partial) |
| fish | `fish -n` / `fish --no-execute` |
| powershell | `Invoke-ScriptAnalyzer` (PSScriptAnalyzer) + a `pwsh`-based parse |
| toml | `taplo` |
| yaml / json | `yq` / `jq` |
| ssh config | `ssh -G` |
| git config | `git config --list -f <file>` |

PowerShell pulls in cross-platform concerns (profile paths differ on Windows vs
`pwsh` on macOS/Linux; manager conventions differ). The skill defers to the base
`AGENTS.md` Platform Awareness section rather than duplicating it.

### Validator-command verification

Per `CLAUDE.md`'s upstream-template-maintenance rule, every third-party validator
invocation above (4 shells + toml/yaml/json/ssh/git) is a **candidate** and must be
verified against current upstream documentation when the template files are
written, not taken as final from this spec.

## Verification-Pillar Mapping

- Syntax/lint validators → skill step 4 + rule (validators table).
- Reload/apply discipline → skill step 5 + rule (pause-and-ask, late failure).
- Dry-run / backup first → skill steps 2–3.
- Secrets scan → rule (secrets section) + skill step 6.

## Open Questions

None blocking. Future (out of scope): renaming installer "languages" → "stacks";
optional justfile once a non-repo-safe recipe pattern is proven.
