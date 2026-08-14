# Guardrails

Guardrails are checks and procedures that make agent work more reliable. Prefer deterministic guardrails over instruction-only guardrails when the behavior can be checked mechanically.

## Guardrail Levels

| Level         | Examples                                                     | Use when                                                  |
| ------------- | ------------------------------------------------------------ | --------------------------------------------------------- |
| Deterministic | tests, linters, type checks, hooks, scripts, dry-run tools   | A machine can verify the condition.                       |
| Procedural    | skills with required discovery, edit, and verification steps | The agent must follow a repeatable workflow.              |
| Instructional | `AGENTS.md`, scoped rules, review guidance                   | The behavior is contextual and cannot be fully automated. |
| Manual        | user approval, code review, explicit override paths          | Judgment or risk acceptance is required.                  |

## Current Deterministic Guardrails

- `scripts/raven.py` previews template application, classifies identical files, protects changed files, and only overwrites explicitly requested paths.
- `.claude/scripts/raven-tool-check.py` checks recommended local tools. Agent workflows may record tool availability or reminder preferences outside the repository.
- `.claude/hooks/raven-pre-bash-guard.py` blocks clearly destructive shell commands.
- `.claude/hooks/raven-pre-edit-guard.py` blocks edits to protected secret-like files and warns on high-churn paths.
- `.claude/hooks/raven-post-bash-summarize.py` nudges noisy commands toward RTK when exact raw output is not required.
- `.claude/hooks/raven-post-edit-format.py` runs cheap formatters when available.
- `.claude/settings.json`'s `permissions.deny` block adds a native, host-enforced layer over the same blocked-tier surface as the two guard hooks above (issue #199) — see "Two-Layer Enforcement" below.

## Two-Layer Enforcement: Native `permissions.deny` + Guard Hooks

`common/.claude/settings.json` ships a `permissions.deny` block that mirrors the **blocked** tier of `raven-pre-bash-guard.py` and `raven-pre-edit-guard.py` — never the **caution** tier, which is warn-only in the hooks and would misrepresent a deny as a warning. The two layers are additive, not redundant:

| Layer | Enforced by | Precision | Coverage |
| --- | --- | --- | --- |
| Native (`permissions.deny`) | Claude Code host, before the tool call is even dispatched | Glob/prefix matching only | Claude only — Codex has no `permissions` equivalent |
| Hook (`raven-pre-bash-guard.py`, `raven-pre-edit-guard.py`) | A Python process Claude Code and Codex both spawn per tool call | Tokenizes the command: normalizes option clusters, resolves wrappers, follows nested payloads | Both hosts |

**Do not remove or weaken the hooks in favor of the native rules.** Two reasons:

1. **Codex has no `permissions` equivalent.** Its hook coverage (Bash, `apply_patch`, MCP calls) is the *only* enforcement it gets; `permissions.deny` is Claude-only.
2. **The hooks are more precise than a glob can be.** `raven-pre-bash-guard.py` tokenizes a command, normalizes option clusters (`-rf`, `-fr`, `--recursive --force` all reduce to the same intent), skips the value operand of an option that takes one (`git -c core.pager=cat clean -fdx` still reads as `clean`), and matches at the program position rather than anywhere in the text. A `Bash(...)` glob rule cannot do any of that.

### What the native layer cannot catch

These are real, current gaps in `permissions.deny` relative to the hooks — not oversights, but properties of glob/prefix matching that a tokenizing hook does not share. Each is exercised by `tests/test_permissions_deny.py::ProgramOptionBearingCoverageTests`, so a change that silently "fixes" one of these by over-broadening a rule will be caught by that test's `expect_covered=False` assertion, which then needs a deliberate update.

- **Arbitrary flag reordering/clustering.** `git clean -fdx` has 6 possible letter orderings for the clustered form alone, plus split (`-f -d -x`) and long-option (`--force -d -x`) spellings. `permissions.deny` ships literal rules only for the 4 spellings this repo's own hook test fixture (`DENIED_BASH_COMMANDS` in `tests/test_agent_hooks.py`) already asserts, each also in a `git * clean ...` form so a global option before the subcommand does not defeat it; anything else — e.g. `git clean -fxd` — is hook-only. The same applies to `rm`'s recursive+force flags: the shipped `rm` rules are exact literal spellings mirroring that same fixture, so an extra/reordered flag the hook still normalizes past (e.g. `rm -v -rf /`) is not natively covered.
- **Substring-anywhere-in-argument matching.** The SQL "drop database" check (`psql`, `mysql`, `mariadb`, `sqlite3`) has no program-position or subcommand shape at all — the hook lowercases every argument and checks for a `"drop database"` substring anywhere. `permissions.deny` ships the literal upper- and lower-case spellings only (`Bash(psql *DROP DATABASE*)`, `Bash(psql *drop database*)`); mixed case (`Drop Database`) is not covered natively.
- **Compound commands ARE covered, contrary to older assumptions.** Claude Code's Bash matching engine natively splits on `&&`, `||`, `;`, `|`, `|&`, `&`, and newlines, and requires each resulting subcommand to match independently. A rule like `Bash(rm -rf /)` is not bypassed by `safe-cmd && rm -rf /`. Wrapper-stripping is also built in for a fixed set (`timeout`, `time`, `nice`, `nohup`, `stdbuf`, `command`/`builtin`, `noglob`, flagless `xargs`) — but NOT for `direnv exec`, `devbox run`, `mise exec`, `npx`, `docker exec`, `watch`, `setsid`, `ionice`, `flock`, or `find -exec`/`-delete`. A rule like `Bash(rm *)` does not cover `docker exec ctr rm -rf /`; the hook, which follows nested interpreter payloads explicitly, still does.
- **A destructive command reached over `ssh`.** The hook follows the remote command as a nested payload, so `ssh -p 2222 host "kubectl delete pod web"` is denied. Natively it is one quoted argument with no anchorable shape: a rule broad enough to see inside it (`Bash(ssh * delete *)`) would deny ordinary remote work, so none is shipped. Hook-only, deliberately. A *value-taking* global option before the payload (`-p 2222`, `-o Key=value`) is the shape that used to defeat the hook here too — see issue #207 and `_VALUE_TAKING_OPTIONS` in the guard.
- **Read-only secret protection is new, not a restatement.** The `Read(...)` deny rules (e.g. `Read(*.pem)`, `Read(secrets/**)`) cover a gap the edit guard never had: `raven-pre-edit-guard.py` only fires on `Write`/`Edit`/`MultiEdit`, so nothing previously stopped a plain `Read` of a secret-bearing path. Per Claude Code's documented behavior, a `Read(...)` deny rule also blocks `Edit`/`Write` on the same path, so a parallel `Edit(...)` rule is intentionally not shipped alongside each `Read(...)` rule — see `tests/test_permissions_deny.py::NoCautionOrEditRuleAdditionsSlippedIntoDenyTests`.
- **Claude Code also has an independent, non-configurable circuit breaker** for `rm -rf /` and `rm -rf ~` (including through `$(...)`/backtick/`<(...)` substitution), active even in `bypassPermissions` mode. This is separate from, and does not substitute for, the explicit `permissions.deny` rules shipped here — the other destructive intents (`git reset --hard`, `git clean -fdx`, `dropdb`, `kubectl delete`) have no such built-in breaker, and an explicit project-level rule is portable documentation of intent regardless of how the breaker's exact scope evolves.

`tests/test_permissions_deny.py` is the enforcement point for keeping `permissions.deny` from drifting out of sync with the hooks: it reads the edit guard's real `BLOCKED`/`CAUTION` module-level lists and the bash guard's own `DENIED_BASH_COMMANDS` test fixture, cross-checks them against the real, parsed `permissions.deny` array, and asserts no caution-tier pattern ever appears there.

## Required Verification Pattern

For implementation work:

1. Discover the smallest sufficient context.
2. Verify candidate context with deterministic tools before editing.
3. Make the smallest coherent change.
4. Run the narrowest relevant verification.
5. Broaden verification only after narrow checks pass.
6. Report what was verified and what remains unverified.

## Override Rules

- Destructive commands require explicit user approval.
- Template overwrites require explicit path arguments to `scripts/raven.py`.
- Missing-tool reminder suppression requires explicit user approval and must be recorded through `.claude/scripts/raven-tool-check.py --no-reminder`.
- Optional tools must not become hard requirements unless the repository documents them as required.

## Maintenance

- Add deterministic checks when a repeated agent failure can be detected mechanically.
- Add or update skills when the failure is procedural.
- Keep root instructions short; move detailed guardrail explanations into this file or a skill.
