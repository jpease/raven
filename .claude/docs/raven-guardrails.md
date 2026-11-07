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
- `.claude/hooks/raven-pre-edit-guard.py` blocks edits to protected secret-like files and warns on high-churn paths. For paths a project lists under `[edit_guard] protected_paths` in `.raven/config.toml`, it escalates the edit to a permission prompt on Claude Code, or adds a warning to context on Codex and Gemini CLI. This is the mechanical backstop for the Pause-And-Ask categories a project can spell as paths; the judgment-call categories stay prose.
- `.claude/hooks/raven-pre-read-secret-guard.py` denies a `Read` of a secret-bearing path. See "`Read(...)` pattern depth, and the `.env` family" below.
- `.claude/hooks/raven-pre-bash-test-scope.py` adds one advisory sentence when the session's first test command covers the whole suite, and says nothing afterwards.
- `.claude/hooks/raven-post-bash-summarize.py` nudges noisy commands toward RTK when exact raw output is not required.
- `.claude/hooks/raven-post-bash-truncate.py` (Claude Code and Gemini CLI) replaces a Bash result longer than `[bash_output] max_lines` with its head, its tail, and the path of a file holding all of it. A tool result is re-read every later turn, so this enforces the token pillar. Codex cannot replace a result from PostToolUse and relies on its own `tool_output_token_limit`.
- `.claude/hooks/raven-post-edit-format.py` runs cheap formatters when available.
- `.claude/settings.json`'s `permissions.deny` block adds a native, host-enforced layer over the same blocked-tier surface as the bash and edit guards. See "Two-Layer Enforcement" below.
- `.raven/git-hooks/lib/check-gate-relaxation.py` blocks a commit that stages a suppression naming no rule — a bare `# noqa`, `@ts-ignore`, `//nolint`, `#[allow(warnings)]`, `rubocop:disable all` — in the eight languages Raven ships gates for. See "Blanket Suppressions" below.

## Blanket Suppressions At Commit Time

A blanket suppression turns a gate off for a line, a file, or a whole crate without naming a rule. It is the cheapest way to make a red gate green. `.claude/rules/raven-python.md`, `.claude/docs/raven-python-quality.md`, `raven-write-tests`, `raven-dependency-update`, and this file all ask for the narrowest scoped suppression instead; this check is the part an agent cannot edit around.

Each of the nine detectors was checked against the real linter. A harmless syntax gets no detector; a bare `rubocop:disable` names no cop and suppresses nothing.

Only a staged suppression with no committed counterpart is a finding, so one that moved, was reindented, or travelled through a rename stays silent; a second copy does not. A line carrying `raven-hygiene: allow` is skipped on both sides, so deleting the marker from a still-blanket suppression reports it.

What it leaves alone, and where each is caught instead:

- **A rule code with no reason beside it.** Only Python has a settled place for a reason. Review catches this; `.claude/scripts/raven-capability-roster.py` shows the shape that passes.
- **A linter config edited to check less.** `raven assess` reports the standing state: a ruff family selected and then wholly ignored, a `per-file-ignores` keyed on `*`, an `exclude` covering the tree, a `typeCheckingMode` below the `standard` floor. It parses Python configs only.
- **A deleted or unconditionally skipped test.** Not checked: `def test_` is Python, and the other toolchains need their own detection. The observable form is a diff that leaves a file with fewer test functions.

`[git_hooks] block_gate_relaxation = false` in `.raven/config.toml` turns the check off, the same shape `block_ai_attribution_content` uses. Make that change as a reviewed repository-level decision, never as a step in landing a suppression the check refused.

## Two-Layer Enforcement: Native `permissions.deny` + Guard Hooks

`common/.claude/settings.json`'s `permissions.deny` mirrors the **blocked** tier of `raven-pre-bash-guard.py` and `raven-pre-edit-guard.py`, never the warn-only **caution** tier. The two layers are additive, not redundant:

| Layer | Enforced by | Precision | Coverage |
| --- | --- | --- | --- |
| Native (`permissions.deny`) | Claude Code host, before the tool call is even dispatched | Glob/prefix matching only | Claude only — Codex has no `permissions` equivalent |
| Hook (`raven-pre-bash-guard.py`, `raven-pre-edit-guard.py`) | A Python process Claude Code, Codex, and Gemini CLI all spawn per tool call | Tokenizes the command: normalizes option clusters, resolves wrappers, follows nested payloads | Every host |

**Do not remove or weaken the hooks in favor of the native rules.** `raven assess` reports a hook whose body does nothing as not installed, and one that never reaches `check` as ungated. Two reasons:

1. **Codex has no `permissions` equivalent.** Its hook coverage (Bash, `apply_patch`, MCP calls) is the *only* enforcement it gets.
2. **The hooks are more precise than a glob.** `raven-pre-bash-guard.py` normalizes option clusters (`-rf`, `-fr`, `--recursive --force`), skips an option's value operand (`git -c core.pager=cat clean -fdx` reads as `clean`), and matches at the program position.

Every bash-guard rule runs through **one** entry point, `_find_destructive_rule`, which follows nested payloads (`sh -c …`, herestrings, `ssh`, `xargs`) to `_MAX_NESTING_DEPTH` and applies every rule at every level. A rule added elsewhere, such as a second pass over top-level segments, misses nested commands: `sh -c 'rm -rf ~'` gets through while `sh -c 'dropdb prod'` is denied.

A nested payload must be **sliced out of the original tokens** with `_first_operand_index`. Rebuilding it from normalized positionals drops its flags (`xargs rm -rf /` becomes `rm /`), and every flag-keyed rule misses it.

**Reassemble the slice the way the program treats its argv.** `ssh` space-joins its arguments for the remote shell, so its payload is space-joined: `ssh host sh -c 'rm -rf /'` really runs `sh -c rm -rf /`. `xargs` execs the argv it was given, so its payload is re-quoted with `shlex.join`. The wrong join is a false negative or a false positive, so a new branch must first answer "does this program flatten or exec?"

The destructive-git set (`reset --hard`, `clean -fdx`, forced `checkout`/`restore`, `stash clear`/`drop`, `branch -D`, forced `push`, `filter-branch`, `update-ref -d`, `reflog expire`) is matched on the subcommand **plus the flag that makes it destructive**: `git checkout main`, `git stash`, `git branch -d merged` and `git push origin main` are ordinary work. `--force-with-lease` stays allowed on purpose. It refuses to overwrite work it has not seen, and denying it would push people toward plain `--force`.

### What the native layer cannot catch

These gaps come from glob/prefix matching. `tests/test_permissions_deny.py::ProgramOptionBearingCoverageTests` pins each with an `expect_covered=False` assertion, so over-broadening a rule to "fix" one fails that test.

- **Arbitrary flag reordering/clustering.** `git clean -fdx` has 6 clustered orderings plus split (`-f -d -x`) and long-option (`--force -d -x`) spellings. `permissions.deny` ships only the 4 spellings in the hook's `DENIED_BASH_COMMANDS` fixture (`tests/test_agent_hooks.py`), each also as `git * clean ...` so a global option cannot defeat it; `git clean -fxd` is hook-only. The `rm` rules mirror the same fixture exactly, so `rm -v -rf /` is hook-only too.
- **Substring-anywhere-in-argument matching.** The SQL "drop database" check (`psql`, `mysql`, `mariadb`, `sqlite3`) has no program-position or subcommand shape: the hook lowercases every argument and looks for a `"drop database"` substring anywhere. `permissions.deny` ships the literal upper- and lower-case spellings only (`Bash(psql *DROP DATABASE*)`, `Bash(psql *drop database*)`); mixed case (`Drop Database`) is not covered natively.
- **Compound commands ARE covered.** Claude Code splits on `&&`, `||`, `;`, `|`, `|&`, `&`, and newlines and matches each part, so `safe-cmd && rm -rf /` does not bypass `Bash(rm -rf /)`. It strips a fixed set of wrappers (`timeout`, `time`, `nice`, `nohup`, `stdbuf`, `command`/`builtin`, `noglob`, flagless `xargs`) but not `direnv exec`, `devbox run`, `mise exec`, `npx`, `docker exec`, `watch`, `setsid`, `ionice`, `flock`, or `find -exec`/`-delete`. `Bash(rm *)` misses `docker exec ctr rm -rf /`; the hook catches it.
- **A destructive command reached over `ssh`.** The hook follows the remote command, so `ssh -p 2222 host "kubectl delete pod web"` and the bare `ssh host rm -rf /` are both denied; `_VALUE_TAKING_OPTIONS` keeps `-p 2222` or `-o Key=value` from hiding the payload. Natively the remote command has no anchorable shape, and a rule that sees inside it (`Bash(ssh * delete *)`) would deny ordinary remote work, so none ships.
- **Secret reads.** `permissions.deny` ships no `Read(...)` rules; `raven-pre-read-secret-guard.py` covers secret-bearing paths (see the next section), and `tests/test_permissions_deny.py` fails if a `Read(...)` rule comes back. Writes to those paths are the edit guard's `BLOCKED` list, and `NoCautionOrEditRuleAdditionsSlippedIntoDenyTests` keeps `Edit(...)`/`Write(...)` rules out of `permissions.deny`.
- **Piping a fetched URL into an interpreter.** `curl -sSL URL | sh` spans two subcommands, and a rule broad enough to reach it (`Bash(curl *)`, `Bash(sh)`) would deny ordinary work. No `curl`/`wget` entry ships; `PipeToShellIsHookOnlyTests` asserts that. The hook denies the piped form and the `sh -c "$(curl ...)"` form, for shells and for `python3 -`/`node`/`ruby`/`perl` reading stdin. It is a speed bump: fetching to a file and running it in two steps still works, by design.
- **`git checkout -f` with no pathspec.** The shipped rules need an operand (`Bash(git checkout -f *)`), because a trailing `" *"` needs a real argument. The hook denies the bare form too: `-f` on `checkout`/`restore` always discards the worktree.
- **Claude Code's own circuit breaker** for `rm -rf /` and `rm -rf ~` (including through `$(...)`, backtick, and `<(...)` substitution) is active even in `bypassPermissions` mode and cannot be configured. It does not replace the shipped rules: `git reset --hard`, `git clean -fdx`, `dropdb`, and `kubectl delete` have no built-in breaker.

### `Read(...)` pattern depth, and the `.env` family

`.claude/hooks/raven-pre-read-secret-guard.py` enforces 21 secret-path patterns against the concrete path a `Read` names; `[hooks] block_secret_reads = false` in `.raven/config.toml` turns it off. As `Read(...)` deny rules they prompted on every recursive search of the repository root, because Claude Code checks a Bash command's read scope against them by *directory*. Settings cannot fix that: rules evaluate deny → ask → allow, so no allow entry can carry an exception, and anchoring the globs would drop `packages/api/.env`.

The hook matches basenames and directory segments, as the deny rules did. Read and Edit rules use gitignore syntax, where a **bare filename with no slash matches at any depth**: `Read(.env)` and `Read(**/.env)` are equivalent, so `packages/api/.env` was covered without a `**/` entry ([Claude Code permissions](https://code.claude.com/docs/en/permissions.md); `tests/test_permissions_deny.py::_read_rule_matches` models the same rule). A single directory segment like `secrets/**` also matches at any depth *in a deny rule*, though not in an allow rule.

Two decisions behind the `.env` entries:

- **`.env.*` deliberately catches `.env.example` too.** Exempting the template would mean listing secret-bearing variants and missing an unlisted one (`.env.prod`). The cost is small: the guard covers `Read` only, so `cat .env.example` through Bash still works.
- **`.envrc` is in scope.** direnv's file is a shell script that commonly exports the same secrets.

`raven-pre-edit-guard.py`'s `BLOCKED` list carries the same two patterns for edits on every host.

`tests/test_permissions_deny.py` keeps the layers in sync: every edit-guard `BLOCKED` sample must trip the secret-read guard, `DENIED_BASH_COMMANDS` must be covered by `permissions.deny`, and no caution-tier pattern may appear there.

## Required Verification Pattern

For implementation work:

1. Discover the smallest sufficient context.
2. Verify candidate context with deterministic tools before editing.
3. Make the smallest coherent change.
4. Run the narrowest relevant verification.
5. Broaden verification only after narrow checks pass.
6. Report what was verified and what remains unverified.

A reported status is not the same signal as the thing it reports on:

- **A background or piped command's exit status can lie about the real command's outcome.** A backgrounded script ending in `echo "done"` or a wrapper's own final line reports that line's exit code. A pipeline reports its last stage, so in `some-command | tail -f` an upstream failure reads as success. Check the real command's own status (`PIPESTATUS[0]` in bash, `$pipestatus[1]` in fish).
- **Some shapes report zero by design:** a gate script running each check as `check || true`, and a wrapper returning empty output for a command it does not understand. Empty output with a zero exit is an unanswered question. Read the line that decides the result (`N tests run`, `Checks failed:`, `PASS`), and re-run through `rtk proxy` when RTK's summary is empty.
- **For backgrounded work, verify the durable artifact** (a changed file, a commit, a pushed ref) rather than a completion notification that reflects the launcher's exit code.
- **A hard-killed write-heavy command can destroy files.** A commit, build, or migration killed mid-write can leave partial, reverted, or deleted files. Check the affected files before treating a timeout as harmless, and prefer a generous timeout.

## Pause-And-Ask Enforcement Is Prose-Only

`AGENTS.md`'s Pause And Ask categories (auth/secret handling, destructive operations, schema/migration changes, dependency additions, etc.) depend on the agent recognizing a match; no hook checks a diff against them. Literal protected paths a project adds in `CLAUDE.md`/`AGENTS.md` share that gap. For categories a project can spell as paths, list the globs under `[edit_guard] protected_paths` in `.raven/config.toml`, and `raven-pre-edit-guard.py` escalates or warns on a matching edit.

## Local Hooks Validate Ambient State, Not A Clean Checkout

Local pre-commit and pre-push hooks run in the contributor's warmed-up shell; CI starts from scratch. A bug that appears only when some ambient state (an exported variable, a cached file, an installed tool) is *absent* stays invisible to local hooks while a clean checkout hits it every time, and retargeting the hook's interpreter does not reach it. Pair ambient hooks with a periodic clean-environment check, such as an `env -i`-style invocation or a CI-only step.

## Override Rules

- Destructive commands require explicit user approval.
- Template overwrites require explicit path arguments to `scripts/raven.py`.
- Missing-tool reminder suppression requires explicit user approval and must be recorded through `.claude/scripts/raven-tool-check.py --no-reminder`.
- Optional tools must not become hard requirements unless the repository documents them as required.

## Maintenance

- Add deterministic checks when a repeated agent failure can be detected mechanically.
- Add or update skills when the failure is procedural.
- Keep root instructions short; move detailed guardrail explanations into this file or a skill.
