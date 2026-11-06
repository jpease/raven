# Raven Project Instructions

This repository is Raven itself: the reusable template library and installer for agentic coding guidance.

## Self-Test Workflow

- Use this repository as a live testbed for Raven installation and upgrade behavior.
- After changing template files, managed guidance, or `scripts/raven.py`, run `uv run --group dev python scripts/self-check.py` (the documented dev environment — see "Developing Raven" in `README.md`).
- The self-check validates the installed shape, runs `upgrade --dry-run`, applies `upgrade`, then runs the unit tests.
- Treat unexpected self-upgrade output as a product issue unless the changed behavior was intentional.

## Upstream Template Maintenance

- Raven templates sometimes encode setup commands for third-party software, such as `mcp-language-server` and language servers.
- When editing those templates, validate the commands against the current upstream maintainer documentation before changing defaults.
- Treat stale third-party setup guidance as a Raven maintenance bug, even if the template still installs successfully.

## Public Repository Hygiene

- This repository is public. Everything committed here is world-readable.
- Dogfooding and downstream validation happen in private repos. Refer to them by role, never by name: "a private iOS app repo", "the `#60` reporter", "a downstream Node consumer".
- Do not commit local absolute paths. Write repro steps as `cd <downstream-repo> && raven doctor`, not `cd /Users/<name>/Developer/...`.
- Agent plans and specs are working notes and stay out of the tree. Superpowers specs and plans go to `.raven/plans/` (gitignored) instead of `docs/superpowers/`, and are never committed. `scripts/check-prose.py` rejects a tracked file under either directory.
- `just check-fast` (and so the pre-commit hook) runs `scripts/check-staged-hygiene.py`. It blocks a staged diff that adds a home-directory absolute path, or a private repository name listed in `.git/info/raven-private-names` or `RAVEN_HYGIENE_DENYLIST`, in added lines or staged paths. Removing a leak never blocks. The docstring lists the exact patterns and exemptions.
- A legitimate flagged line (this rule's own prose, a fixture proving the detector works, docs about the pattern) carries a trailing `raven-hygiene: allow` comment. In a `.py` file, a marker on a closing-bracket line covers the whole bracketed construct, so a `ruff format` reflow keeps it attached. A path finding has no line to mark; rename the path. Keep the name list itself in `.git/info/` or local memory, never in a tracked file.

## Gate Relaxation

- `just check-fast` runs `scripts/check-staged-relaxation.py`, which enforces Raven's rule against weakening a gate. It blocks a staged change that:
  - adds a `.py` suppression with no rule code or no reason (`# noqa`, `# type: ignore`, `# pyright: ignore`, file-level `ruff: noqa`, `mypy: ignore-errors`);
  - edits `pyproject.toml`, `ruff.toml`, `pyrightconfig.json`, `mypy.ini`, `setup.cfg`, `tsconfig.json`, or `Cargo.toml` so it checks less;
  - switches a test off: an unconditional skip, or fewer test functions in a file than before;
  - loosens one of Raven's own gate limits (`LIMIT_CONSTANTS` in the script), or drops a gate from `check-fast`.
- Tightening passes silently. A suppression the committed file already had is grandfathered, including one that moved or was renamed with its file.
- `raven-hygiene: allow` suppresses a finding on its line. A test-count finding has no line, so a marker on any added line of that file suppresses it.
- `raven assess` reports the same relaxations as standing state. The shipped `common/.raven/git-hooks/lib/check-gate-relaxation.py` blocks blanket suppressions in destination repos for all eight template languages. Each script's docstring holds its detection rules and the reasons for what it leaves out.

## Prose Budget

- `just check-fast` and CI run `scripts/check-prose.py` over the staged versions of shipped guidance (`common/` and each language tree), the root docs, `docs/*.md`, `project-skills/`, and non-test Python.
- Budgets: 120 words per paragraph or list item, 2,500 per document, 300 per `##` section of `AGENTS.md` and `common/AGENTS.md`, one `X, not Y` contrast per heading section, and 10 lines per Python comment block.
- Shipped files and root `AGENTS.md` carry no bare issue references: a destination repo cannot resolve them, and in agent-loaded text they are history. Link an upstream issue by URL; put Raven's own history in the commit message. Shipped `SKILL.md` files stay under 1,200 words.
- The same files carry no capitalized directives (`MUST`, `NEVER`, `ALWAYS`) and no sentence of eight or more words stated twice in one file. Shouting or restating a rule signals it fights the model's training; state it once or enforce it with a check.
- Over budget means cut or split. A raised budget constant is reported by `check-staged-relaxation.py` unless its line carries a marker and a reason.
- `raven-hygiene: allow` exempts a line that has to keep its shape, such as an example teaching the pattern; a marker quoted in backticks does not count. Document and section budgets take no marker. Real markers outside `tests/` are capped by `MARKER_BUDGET`, except one approving a limit change, whose job ends with that commit.

## Local Instruction Boundary

- Project-specific instructions for maintaining Raven belong above the managed block in this file.
- The block between `RAVEN:BEGIN` and `RAVEN:END` is managed template content used to test safe block upgrades.
- Do not edit inside the managed block directly; update the source template instead.

## Code Indexes

- This repository records `[mcp] optional = []` in `.raven/config.toml` and wires no code-index MCP server. Dogfooding the shipped guidance means `rg` and LSP first.
- A maintainer who wants GitNexus or CodeGraph adds the server in `.claude/settings.local.json` or user-level MCP config. Keep `.gitnexusrc` at `{"skipContextFiles": true}` so `gitnexus analyze` does not write a MUST-style block into this file.

<!-- RAVEN:BEGIN sha256=e95da894e2a8639c5324960148b0760d45535946153437ab184f18b6362254c5 -->
# AGENTS.md

## Primary Objective

Be effective while preserving context. Prefer targeted retrieval, summaries, and deterministic tools over broad file reads.

## Canonical Context

- `AGENTS.md` is the authoritative root instruction file.
- `.agents/skills/` is the canonical location for reusable skills.
- Agent-specific skill paths (e.g. `.claude/skills`) mirror `.agents/skills`; edit the canonical copy, never the mirror.
- When a `raven-*` skill and a generic skill cover the same intent, prefer the `raven-*` one — it encodes this project's guardrails.
- Deeper guidance in `.claude/docs/raven-*.md`; open one when its trigger matches:
  - `guardrails`: relaxing a gate or adding a suppression.
  - `authority-map`: deciding which doc to trust.
  - `coding-principles`: structuring or reviewing code.
  - `namespace`: adding or placing a Raven-owned file.
  - `agent-compatibility`: editing client adapter files.
  - `lsp-mcp`, `semgrep`: tool setup.
  - `tool-assessment`: choosing retrieval tools.
  - `antipatterns`: working where a repeat failure is recorded.
- If another tool inserts a managed block in `AGENTS.md`, treat it as authoritative for that tool's commands, syntax, and resource names — not as an override of these workflow guardrails.

## Retrieval Discipline

Use the cheapest adequate source before reading full files.

| Need | First tool |
|---|---|
| Exact string, symbol, config key, or error | `rg` |
| File discovery by name, type, or extension | `fd` |
| Definition, references, type info, diagnostics | LSP |
| "How does X work?" / conceptual flow discovery | Listed code index, else `rg` and LSP |
| Blast-radius before editing a symbol | LSP references, else `rg` |
| Syntax-aware pattern or mechanical rewrite | ast-grep or Semgrep |
| Large diff before commit | `git diff --stat`, then targeted hunks |
| Test, build, or log output | quiet flag first, RTK if still noisy |

- Batch independent reads, searches, and inspections per turn.
- Skeleton-first: for a large or unfamiliar file, get a symbol map (LSP document symbols, or `ast-grep`/`rg`), then read only the needed ranges.
- Return concise findings before editing.
- When two literal `rg` guesses miss, switch tools rather than iterating term variations; an index query is discovery, not proof, so verify with `rg`, LSP, or tests before changing code. Tool spellings, flags, and dot-directory caveats live in `raven-codebase-discovery`.
- Stop when two or more appropriate tools have failed to locate a credible file, symbol, or integration point. Summarize what was tried, then delegate or ask.
- Tool availability comes from the session capability roster. If no roster is present, probe before relying on a non-baseline tool. A listed MCP server may still be unapproved or unconnected; treat a failed call as information about the session.
- A listed code index is an optional aid whose results are discovery only; say so if it is stale. A configured MCP server is not an index.

## Skills

A skill costs a file read on Codex and a step — an `activate_skill`/`Skill` tool call — on Claude Code and Gemini CLI, before any work starts. Invoke one for a task of several steps or when the user asks for it; a one-file change or a short paragraph needs none.

## Delegation

Delegate or ask when the scope of a task exceeds what targeted retrieval can resolve in the main context. Use the `raven-delegate-or-inline` skill for the decision criteria, delegation mechanics, and anti-habit checks. Raven ships `raven-security-reviewer`, `raven-refactor-reviewer`, `raven-test-debugger`, `raven-codebase-cartographer`, and `raven-prose-reviewer` as subagents across Claude Code, Codex, and Gemini CLI for common audits. Sub-agent returns must include an `## Out Of Scope Findings` section; disposition those findings per `raven-triage-discovery` rather than leaving them in chat or in an issue comment.

## Shell Command Policy

Prefer a command's own quiet flag before RTK (`pytest -q`, `ruff check --quiet`, `npm ci --silent`) — same familiar format, and it still surfaces real failures and violations.

Use RTK for commands likely to produce noisy output beyond what a quiet flag removes: tests and builds, package managers, cloud CLIs, Docker and Kubernetes commands.

For large diffs or recursive listings, use `git diff --stat` and `fd` before RTK — RTK's summary of these has been seen truncating output behind a local log file the agent can't read back. Read the full diff or listing directly when the summary isn't enough.

Prefer `jq`/`yq` over `grep`/`sed`/`awk` for structured JSON/YAML.

Do not use RTK when exact raw output matters — small precise diffs, generated code, compression-sensitive compiler output, or security-sensitive review.

## Pause And Ask

Pause and ask before work that is ambiguous or could create durable harm:

- public API, schema, migration, compatibility, or release behavior changes
- auth/authz, secret handling, destructive operations, filesystem deletion, or network exposure
- dependency additions, license-sensitive code, vendored code, or generated artifacts
- broad refactors, cross-module architecture changes, or unclear scope boundaries
- any task where the safe behavior depends on product intent the repo does not make clear

Otherwise keep going; do not stop to report status or offer to continue.

## Editing Rules

- Make minimal patches.
- Before changing public APIs, check references with LSP, then confirm with `rg`.
- Before large mechanical edits, use ast-grep or Semgrep.
- Run the narrowest relevant test first.
- If tests fail, inspect only failing output first.

## Verification State

- If you lose track of what was verified, re-verify before editing further or claiming completion.
- Do not claim broad success from narrow checks; state exactly what ran and what remains unverified.
- The final report separates what ran from what was not checked, and names where you looked for anything you could not find.
- After context compaction or a long interruption, restate the current goal and verified state before continuing risky edits.

## Convergence

- A task ends in success, progression (one blocker removed, the next isolated with evidence), or stop. Progression is an acceptable end state; report it plainly.
- Stop and report when the same test has failed after three consecutive fixes aimed at it, when a fix needs code the task did not scope, or when the diff grows while the failing signal does not change.
- Do not keep patching once the work stops converging; hand off through `raven-plan` to a fresh session. Partial work leaves the codebase more legible.
- `raven-task-complete` states the test for each of the three states; `raven-debug-failure`'s `When To Stop` covers the narrower case where ownership was never found.

## Safety Rules

- Do not run destructive commands without explicit approval.
- Before offering to run a destructive command, check whether approval can lift the block. A hard deny cannot be granted in chat.
- Do not substitute an equivalent-effect command when a guardrail blocks one. A block denies the outcome, not the command string: report it and hand the command to the user.
- Do not modify secrets, credentials, generated files, lockfiles, or migrations unless required.
- Do not add dependencies without explaining why.
- Never hide uncertainty; state confidence and unresolved assumptions.
- Agreement is not helpfulness. Before ratifying a design, plan, or conclusion the user proposed, name the specific thing you would change, or state why you agree with it.
- When offering options, lead with a recommendation and its one real trade-off; ask only when the choice is close.
- When you do ask, prefer a structured-choice prompt with a free-text escape hatch when the harness offers one; if only plain text is available, phrase it so a bare "yes" or "no" resolves unambiguously — never let one word plausibly answer two different clauses.
- When the roster reports a recommended tool missing, do not install it or silence the reminder without the user's say; `raven-tool-bootstrap` records their answer.
- Prefer portable commands and hooks; guidance is shared across macOS, Linux, Windows, and WSL.
<!-- RAVEN:END -->
