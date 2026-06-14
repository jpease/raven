# Dotfiles Stack Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `dotfiles` template stack that gives agents source-of-truth, apply, secrets, and per-format validation guardrails for editing home-directory configuration.

**Architecture:** A new top-level `dotfiles/` dir, auto-discovered by the installer (no code change), built by mirroring an existing stack's symlink structure into `common/` and swapping in dotfiles differentiators. v1 ships exactly two pieces of new prose: a stack-local rule (`dotfiles/.claude/rules/raven-dotfiles.md`) and a global, description-gated skill (`common/.agents/skills/raven-dotfiles/SKILL.md`). No justfile, no quality doc, no tool-config file, and `.mcp.json`/`.codex/config.toml` omit the `lsp` server.

**Tech Stack:** Python 3 (Raven CLI + `unittest`), Markdown templates, JSON/TOML config, relative symlinks.

**Spec:** `docs/superpowers/specs/2026-06-14-dotfiles-stack-design.md`

---

## File Structure

New files (real):
- `dotfiles/README.md` — stack readme
- `dotfiles/.mcp.json` — MCP servers (semgrep/semble/gitnexus), no `lsp`
- `dotfiles/.codex/config.toml` — Codex MCP config, no `lsp`
- `dotfiles/.claude/rules/raven-dotfiles.md` — always-loaded rule (stack-local)
- `common/.agents/skills/raven-dotfiles/SKILL.md` — on-demand workflow skill (global, gated)

New files (symlinks, mirrored from `go/`):
- `dotfiles/AGENTS.md` → `../common/AGENTS.md`; `dotfiles/CLAUDE.md` → `AGENTS.md`
- `dotfiles/.agents/skills` → `../../common/.agents/skills`
- `dotfiles/.claude/agents/*` (4) → `../../../common/.claude/agents/*`
- `dotfiles/.claude/docs/*` (8 shared) → `../../../common/.claude/docs/*` (NO `raven-*-quality.md`)
- `dotfiles/.claude/hooks/*` (5) → `../../../common/.claude/hooks/*`
- `dotfiles/.claude/rules/raven-security.md`, `raven-tests.md` → `../../../common/.claude/rules/*`
- `dotfiles/.claude/scripts/*` (2) → `../../../common/.claude/scripts/*`
- `dotfiles/.claude/settings.json` → `../../common/.claude/settings.json`
- `dotfiles/.claude/skills` → `../.agents/skills`
- `dotfiles/.codex/{agents,hooks,hooks.json,rules,scripts}` → `../../common/.codex/*`
- `dotfiles/.raven/git-hooks` → `../../common/.raven/git-hooks`

Deliberately absent vs the `go/` stack: `justfile`, `.golangci.yml` (any tool config), `.claude/docs/raven-go-quality.md` (no dotfiles quality doc).

Modified files:
- `tests/test_template.py` — add a test for the dotfiles stack (Task 1)

---

### Task 1: Add the failing test for the dotfiles stack

**Files:**
- Modify: `tests/test_template.py` (add one test method to `TemplateTests`)

- [ ] **Step 1: Write the failing test**

Add this method inside the `TemplateTests` class (e.g. after `test_language_templates_define_specific_lsp_mcp_defaults`):

```python
    def test_dotfiles_stack_shape(self):
        languages = raven.list_language_templates()
        self.assertIn("dotfiles", languages)

        stack = REPO_ROOT / "dotfiles"

        # Stack-local rule exists as a real file.
        rule = stack / ".claude" / "rules" / "raven-dotfiles.md"
        self.assertTrue(rule.is_file())

        # .mcp.json ships semgrep/semble/gitnexus but intentionally no lsp server.
        mcp = json.loads((stack / ".mcp.json").read_text(encoding="utf-8"))
        servers = mcp["mcpServers"]
        self.assertIn("semgrep", servers)
        self.assertIn("semble", servers)
        self.assertIn("gitnexus", servers)
        self.assertNotIn("lsp", servers)

        # Global, description-gated skill lives in common/.
        skill = REPO_ROOT / "common" / ".agents" / "skills" / "raven-dotfiles" / "SKILL.md"
        self.assertTrue(skill.is_file())

        # v1 intentionally ships no justfile and no quality doc for this stack.
        self.assertFalse((stack / "justfile").exists())
        self.assertFalse((stack / ".claude" / "docs" / "raven-dotfiles-quality.md").exists())
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_template.py -k dotfiles_stack_shape -v`
Expected: FAIL — `dotfiles` not in `list_language_templates()` (AssertionError on the first assertion).

- [ ] **Step 3: Commit the failing test**

```bash
git add tests/test_template.py
git commit -m "test(dotfiles): add failing shape test for dotfiles stack"
```

---

### Task 2: Scaffold the dotfiles stack structure from go/

This mirrors the `go/` stack's symlink structure. `go/`'s symlinks are relative (`../../common/...`) and `dotfiles/` sits at the same depth, so copying preserves valid links.

**Files:**
- Create: `dotfiles/` (entire tree, via copy then prune)

- [ ] **Step 1: Copy go/ to dotfiles/ preserving symlinks**

Run (macOS `cp -R` recreates symlinks rather than following them):

```bash
cp -R go dotfiles
```

- [ ] **Step 2: Remove the files that do not apply to v1**

```bash
rm dotfiles/justfile
rm dotfiles/.golangci.yml
rm dotfiles/.claude/docs/raven-go-quality.md
rm dotfiles/.claude/rules/raven-go.md
```

- [ ] **Step 3: Verify the symlink structure resolves**

Run: `find dotfiles -type l ! -exec test -e {} \; -print`
Expected: no output (every symlink resolves). If any path prints, it is broken — stop and inspect.

- [ ] **Step 4: Verify no leftover Go-specific real files**

Run: `find dotfiles -type f`
Expected exactly: `dotfiles/README.md`, `dotfiles/.mcp.json`, `dotfiles/.codex/config.toml`. (README/.mcp.json/config.toml are still Go's content — rewritten in later tasks.)

- [ ] **Step 5: Commit the scaffold**

```bash
git add dotfiles
git commit -m "feat(dotfiles): scaffold stack structure from common base"
```

---

### Task 3: Write the dotfiles .mcp.json (no lsp)

**Files:**
- Modify: `dotfiles/.mcp.json` (overwrite Go's content)

- [ ] **Step 1: Replace the file contents**

Write `dotfiles/.mcp.json` exactly as:

```json
{
  "mcpServers": {
    "semgrep": {
      "command": "semgrep",
      "args": [
        "mcp"
      ]
    },
    "semble": {
      "command": "uvx",
      "args": [
        "--from",
        "semble[mcp]",
        "semble"
      ]
    },
    "gitnexus": {
      "command": "gitnexus",
      "args": [
        "mcp"
      ]
    }
  }
}
```

- [ ] **Step 2: Verify it is valid JSON with no lsp**

Run: `jq '.mcpServers | has("lsp")' dotfiles/.mcp.json`
Expected: `false`

- [ ] **Step 3: Commit**

```bash
git add dotfiles/.mcp.json
git commit -m "feat(dotfiles): mcp config without language server"
```

---

### Task 4: Write the dotfiles .codex/config.toml (no lsp)

**Files:**
- Modify: `dotfiles/.codex/config.toml` (overwrite Go's content)

- [ ] **Step 1: Replace the file contents**

Write `dotfiles/.codex/config.toml` exactly as:

```toml
# Raven Codex project configuration for dotfiles / home-directory config.
# Project-local Codex config loads only after the project .codex layer is trusted.

[agents]
max_threads = 4
max_depth = 1

[mcp_servers.semgrep]
command = "semgrep"
args = ["mcp"]

[mcp_servers.semble]
command = "uvx"
args = ["--from", "semble[mcp]", "semble"]

[mcp_servers.gitnexus]
command = "gitnexus"
args = ["mcp"]
```

- [ ] **Step 2: Verify there is no lsp server defined**

Run: `grep -c 'mcp_servers.lsp' dotfiles/.codex/config.toml`
Expected: `0`

- [ ] **Step 3: Commit**

```bash
git add dotfiles/.codex/config.toml
git commit -m "feat(dotfiles): codex config without language server"
```

---

### Task 5: Write the raven-dotfiles rule

**Files:**
- Create: `dotfiles/.claude/rules/raven-dotfiles.md`

- [ ] **Step 1: Write the rule file**

Write `dotfiles/.claude/rules/raven-dotfiles.md` exactly as:

```markdown
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
```

- [ ] **Step 2: Verify the test's rule assertion now passes**

Run: `python -m pytest tests/test_template.py -k dotfiles_stack_shape -v`
Expected: still FAIL, but now on the skill assertion (`common/.agents/skills/raven-dotfiles/SKILL.md`), not the rule — confirms the rule file is found.

- [ ] **Step 3: Commit**

```bash
git add dotfiles/.claude/rules/raven-dotfiles.md
git commit -m "feat(dotfiles): add raven-dotfiles rule"
```

---

### Task 6: Verify validator commands, then write the raven-dotfiles skill

Per `CLAUDE.md`'s upstream-template-maintenance rule, validator invocations must be
checked against current upstream docs before being committed as defaults.

**Files:**
- Create: `common/.agents/skills/raven-dotfiles/SKILL.md`

- [ ] **Step 1: Verify each validator invocation against upstream**

Confirm the flag/subcommand for each tool below is current (man page or official
docs). Correct the skill table in Step 2 if upstream differs. Tools to verify:
`shellcheck`, `zsh -n`, `fish -n` / `--no-execute`, PSScriptAnalyzer
`Invoke-ScriptAnalyzer`, `taplo lint`, `yq`, `jq`, `ssh -G`,
`git config --list --file`.

Record any correction inline in the table before writing the file.

- [ ] **Step 2: Write the skill file**

Write `common/.agents/skills/raven-dotfiles/SKILL.md` (apply any corrections from
Step 1 to the table):

```markdown
---
name: raven-dotfiles
description: Use when editing home-directory configuration (dotfiles) — shell rc files, editor/WM/app config under ~/.config or $HOME — especially when files may be symlinked, generated, or managed by a tool like chezmoi, stow, yadm, bare-git, or Nix home-manager.
---

# Editing Dotfiles Safely

Follow this workflow whenever you edit home-directory configuration. The hazard is
that the live file is frequently not the source of truth, there is no test/build
gate, and bad configs often fail only at next login or reload.

## Workflow

1. **Locate the source of truth.** Before editing, determine whether the live file
   is real or a symlink/generated artifact of a managed source.
   - `ls -l <file>` to detect symlinks; follow the link.
   - Check for a managed source tree: a `dotfiles/` repo, a chezmoi source dir, a
     bare git work-tree, or a Nix/home-manager generation (read-only store path).
   - The tool ecosystem grows; treat the examples as a starting point and
     investigate. If you cannot determine the source, STOP and ask.

2. **Capture a revert path.** Before any risky edit, ensure you can undo:
   `git stash` / `git diff` in a tracked tree, the manager's diff or dry-run, or a
   plain copy of the file. Prefer dry-run/diff over in-place edits on managed trees.

3. **Edit the source, not the artifact.** Make the change in the source-of-truth
   file located in step 1.

4. **Validate syntax.** Run the validator for the format. Skip validators that are
   not installed; never claim a check you did not run.

   | Format | Check |
   |---|---|
   | bash/sh | `shellcheck <file>` |
   | zsh | `zsh -n <file>` (shellcheck zsh support is partial) |
   | fish | `fish -n <file>` (a.k.a. `--no-execute`) |
   | PowerShell | `Invoke-ScriptAnalyzer <file>` for lint; `pwsh` parse for syntax |
   | toml | `taplo lint <file>` |
   | yaml | `yq . <file>` (or yamllint) |
   | json | `jq . <file>` |
   | ssh config | `ssh -G -F <file> <host>` |
   | git config | `git config --list --file <file>` |

5. **State the apply step — never auto-apply.** Tell the user exactly how the change
   takes effect (source the file, reload the daemon, run the manager's apply) and
   warn if it can only fail at next login/restart.

6. **Secrets-scan before any commit.** Dotfiles are secret-dense. Run gitleaks (if
   available) or scan for tokens/keys before committing. Never commit secrets
   inline.
```

- [ ] **Step 3: Run the shape test to verify it passes**

Run: `python -m pytest tests/test_template.py -k dotfiles_stack_shape -v`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add common/.agents/skills/raven-dotfiles/SKILL.md
git commit -m "feat(dotfiles): add raven-dotfiles workflow skill"
```

---

### Task 7: Write the dotfiles README

**Files:**
- Modify: `dotfiles/README.md` (overwrite Go's content)

- [ ] **Step 1: Inspect a sibling README for tone/length**

Run: `cat go/README.md`
Expected: a short readme; match its structure and length.

- [ ] **Step 2: Write dotfiles/README.md**

Write a concise readme matching the sibling style. Required content: what the stack
is (agent guidance for editing home-directory config), that it ships a
`raven-dotfiles` rule and skill, that v1 has no justfile/quality doc by design, and
the source-of-truth + apply + secrets posture. Keep it to roughly the length of
`go/README.md`; do not invent commands the stack does not ship.

- [ ] **Step 3: Commit**

```bash
git add dotfiles/README.md
git commit -m "docs(dotfiles): add stack readme"
```

---

### Task 8: Full verification (install, upgrade, symlinks, self-check)

**Files:** none (verification only)

- [ ] **Step 1: No broken symlinks across all templates**

Run: `python -m pytest tests/test_template.py -k "no_broken_symlinks or dotfiles_stack_shape or templates_install_and_upgrade" -v`
Expected: PASS (covers `test_templates_have_no_broken_symlinks`,
`test_dotfiles_stack_shape`, and `test_all_language_templates_install_and_upgrade_cleanly`, which now includes dotfiles).

- [ ] **Step 2: Full test suite**

Run: `python -m pytest -q`
Expected: all tests pass.

- [ ] **Step 3: Self-check (install shape + upgrade dry-run + upgrade + unit tests)**

Run: `python scripts/self-check.py`
Expected: passes with no unexpected self-upgrade output. (Per `CLAUDE.md`, treat
unexpected self-upgrade output as a product issue.)

- [ ] **Step 4: Smoke-test a real dotfiles install into a temp dir**

```bash
tmp=$(mktemp -d) && python scripts/raven.py install "$tmp" dotfiles && \
  test -f "$tmp/.claude/rules/raven-dotfiles.md" && \
  test -f "$tmp/.claude/skills/raven-dotfiles/SKILL.md" && \
  jq '.mcpServers | has("lsp")' "$tmp/.mcp.json" && \
  echo OK && rm -rf "$tmp"
```

Expected: prints `false` then `OK` (rule installed, skill resolved through the
shared skills symlink, no lsp server). If the `install` subcommand signature
differs, confirm it against `python scripts/raven.py --help` first.

- [ ] **Step 5: Final commit if any verification fix was needed**

```bash
git add -A
git commit -m "test(dotfiles): verify stack installs and upgrades cleanly"
```

---

## Self-Review

**Spec coverage:**
- Source-of-truth backbone → Task 5 (rule) + Task 6 (skill step 1).
- Tool-agnostic + extensible examples → Task 5 and Task 6 prose ("examples only / ecosystem grows").
- Four verification pillars (validators, apply discipline, dry-run/backup, secrets) → rule (Task 5) + skill (Task 6) + mapping in spec.
- Skill in `common/` (global, gated) → Task 6.
- `.mcp.json`/codex omit lsp → Tasks 3, 4 + test in Task 1.
- v1 drops justfile / quality doc / tool config → Task 2 pruning + Task 1 assertions.
- bash/zsh/fish/powershell coverage → Task 6 table.
- Auto-discovery, no installer code change → Task 1 (`list_language_templates` includes dotfiles after dir exists) + Task 8 smoke test.
- Upstream command verification → Task 6 step 1.

**Placeholder scan:** README body (Task 7) is described, not templated verbatim, because it must match sibling tone and length — every other file has exact content. No "TBD"/"handle edge cases" steps.

**Type/name consistency:** rule path `dotfiles/.claude/rules/raven-dotfiles.md` and skill path `common/.agents/skills/raven-dotfiles/SKILL.md` are used identically in the test (Task 1), creation tasks (5, 6), and smoke test (Task 8, where the skill resolves via the `.claude/skills → .agents/skills → common` symlink chain). Test method name `test_dotfiles_stack_shape` is consistent across Tasks 1, 6, 8.
