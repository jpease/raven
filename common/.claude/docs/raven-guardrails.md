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
- `.claude/hooks/raven-pre-edit-guard.py` blocks edits to protected secret-like files, warns on high-churn paths, and — for paths a project lists under `[edit_guard] protected_paths` in `.raven/config.toml` (#247) — escalates the edit to a permission prompt on Claude Code, or adds a warning to context on Codex. This is the mechanical backstop for the Pause-And-Ask categories a project can spell as paths; the judgment-call categories stay prose.
- `.claude/hooks/raven-pre-bash-test-scope.py` adds one advisory sentence when the session's first test command covers the whole suite, and says nothing afterwards. The narrowest-test-first line in `AGENTS.md` was prose only until it.
- `.claude/hooks/raven-post-bash-summarize.py` nudges noisy commands toward RTK when exact raw output is not required.
- `.claude/hooks/raven-post-bash-truncate.py` (Claude Code only) replaces a Bash result longer than `[bash_output] max_lines` with its head, its tail, and the path of a file holding all of it. A tool result is re-read on every later turn, so this is where the token pillar is enforced rather than advised; Codex's PostToolUse hook cannot replace a result, so that host relies on its own `tool_output_token_limit`.
- `.claude/hooks/raven-post-edit-format.py` runs cheap formatters when available.
- `.claude/settings.json`'s `permissions.deny` block adds a native, host-enforced layer over the same blocked-tier surface as the two guard hooks above (issue #199) — see "Two-Layer Enforcement" below.
- `.raven/git-hooks/lib/check-gate-relaxation.py` blocks a commit that stages a suppression naming no rule — a bare `# noqa`, `@ts-ignore`, `//nolint`, `#[allow(warnings)]`, `rubocop:disable all` — in the eight languages Raven ships gates for. See "Blanket Suppressions" below.

## Blanket Suppressions At Commit Time

A blanket suppression turns a gate off for a line, a file, or a whole crate without naming a rule. It is the cheapest way to make a red gate green, and until issue #231 every Raven site asking for the narrowest scoped suppression instead — `.claude/rules/raven-python.md`, `.claude/docs/raven-python-quality.md`, `raven-write-tests`, `raven-dependency-update`, this file — was prose an agent could read, agree with, and then edit around.

Each of the nine detectors was run against the real linter before it shipped, on a fixture violating two rules: the narrow form leaves one reporting, the blanket form silences both. A syntax the linter proved harmless got no detector. A bare `rubocop:disable` names no cop, suppresses nothing, and still reports the offence, so flagging it would be a false accusation.

For each staged file the committed and staged blobs are each reduced to a multiset of the suppressions that would report, and only a staged one with no committed counterpart is a finding. A suppression that moved, was reindented, or travelled through a rename matches itself and stays silent; a second copy of one does not. Reading added diff lines instead would make a whitespace-only reformat report every suppression the file already had. A line carrying `raven-hygiene: allow` is passed over on the committed side as well as the staged one, so deleting the marker from a still-blanket suppression starts reporting it.

What it leaves alone, and where each is caught instead:

- **A rule code with no reason beside it.** Only Python has a settled place to put one, and requiring a reason in eight languages would mean eight guesses about what a reason looks like. Review catches this; `.claude/scripts/raven-capability-roster.py` shows the shape that passes.
- **A linter config edited to check less.** `raven assess` reports the standing state — a ruff family selected and then wholly ignored, a `per-file-ignores` keyed on `*`, an `exclude` covering the tree, a `typeCheckingMode` below the `standard` floor. All five configs it parses are Python's; the other seven templates keep their gate config in YAML, in executable source, or in a format with no rule keys yet, and a stdlib-only runtime on a 3.9 floor cannot read the first two without a dependency or a parser whose failure mode is a false accusation.
- **A deleted or unconditionally skipped test.** `def test_` is Python; the equivalent for eight toolchains is separate work. The observable form is a diff ending with fewer test functions in a file than it started with.

`[git_hooks] block_gate_relaxation = false` in `.raven/config.toml` turns the check off, the same shape `block_ai_attribution_content` uses. That is a repository-level decision made in the open and reviewed as a config change — not a step in landing a suppression the check just refused.

## Two-Layer Enforcement: Native `permissions.deny` + Guard Hooks

`common/.claude/settings.json` ships a `permissions.deny` block that mirrors the **blocked** tier of `raven-pre-bash-guard.py` and `raven-pre-edit-guard.py` — never the **caution** tier, which is warn-only in the hooks and would misrepresent a deny as a warning. The two layers are additive, not redundant:

| Layer | Enforced by | Precision | Coverage |
| --- | --- | --- | --- |
| Native (`permissions.deny`) | Claude Code host, before the tool call is even dispatched | Glob/prefix matching only | Claude only — Codex has no `permissions` equivalent |
| Hook (`raven-pre-bash-guard.py`, `raven-pre-edit-guard.py`) | A Python process Claude Code and Codex both spawn per tool call | Tokenizes the command: normalizes option clusters, resolves wrappers, follows nested payloads | Both hosts |

**Do not remove or weaken the hooks in favor of the native rules.** `raven assess` grades both of them: a hook whose body does nothing reports as not installed, and one that never reaches `check` reports as ungated. Two reasons:

1. **Codex has no `permissions` equivalent.** Its hook coverage (Bash, `apply_patch`, MCP calls) is the *only* enforcement it gets; `permissions.deny` is Claude-only.
2. **The hooks are more precise than a glob can be.** `raven-pre-bash-guard.py` tokenizes a command, normalizes option clusters (`-rf`, `-fr`, `--recursive --force` all reduce to the same intent), skips the value operand of an option that takes one (`git -c core.pager=cat clean -fdx` still reads as `clean`), and matches at the program position rather than anywhere in the text. A `Bash(...)` glob rule cannot do any of that.

Every rule in the bash guard runs through **one** entry point, `_find_destructive_rule`, which follows nested interpreter payloads (`sh -c …`, herestrings, `ssh`, `xargs`) to `_MAX_NESTING_DEPTH` and applies every rule at every level. Adding a rule anywhere else — a second pass over top-level segments, however convenient for a check that needs normalized flags — reintroduces issue #209, where `sh -c 'rm -rf ~'` was allowed while `sh -c 'dropdb prod'` was denied. The severity ordering was inverted by that split, and nothing in the test suite noticed, because every nesting fixture happened to belong to the family that did recurse.

A nested payload must be **sliced out of the original tokens** with `_first_operand_index`, never rebuilt from normalized positionals. Rebuilding drops the payload's own flags, so `xargs rm -rf /` reduced to `rm /` and `ssh host rm -rf /` to `/`: every flag-keyed rule missed them one layer down while the positional-keyed ones (`xargs -I{} kubectl delete pod {}`) still matched — the same asymmetry as #209, reappearing inside the function that fixed it (issues #214, #215).

**How the slice is reassembled differs per program, and follows what that program actually does with its argv.** `ssh` concatenates the remaining arguments with spaces and hands the result to the remote shell as a string, so the payload is space-joined; `ssh host sh -c 'rm -rf /'` really does run `sh -c rm -rf /` remotely, and re-quoting it would invent a threat that is not there. `xargs` execs the argv it was given, so a token that arrived quoted is still one argument and the payload is re-quoted with `shlex.join`; space-joining it collapsed `sh -c 'rm -rf /'` into `sh -c rm -rf /` and lost the payload a level down. Getting this backwards is a false negative in one direction and a false positive in the other, so a new branch needs an answer to "does this program flatten or exec?" before it picks a join.

The destructive-git set (`reset --hard`, `clean -fdx`, forced `checkout`/`restore`, `stash clear`/`drop`, `branch -D`, forced `push`, `filter-branch`, `update-ref -d`, `reflog expire`) is matched on the subcommand **plus the flag that makes it destructive**, never the subcommand alone: `git checkout main`, `git stash`, `git branch -d merged` and `git push origin main` are ordinary work. `--force-with-lease` stays allowed on purpose — refusing to overwrite work it has not seen is the whole point of that spelling, and denying it would push people toward plain `--force` (issue #210).

### What the native layer cannot catch

These are real, current gaps in `permissions.deny` relative to the hooks — not oversights, but properties of glob/prefix matching that a tokenizing hook does not share. Each is exercised by `tests/test_permissions_deny.py::ProgramOptionBearingCoverageTests`, so a change that silently "fixes" one of these by over-broadening a rule will be caught by that test's `expect_covered=False` assertion, which then needs a deliberate update.

- **Arbitrary flag reordering/clustering.** `git clean -fdx` has 6 possible letter orderings for the clustered form alone, plus split (`-f -d -x`) and long-option (`--force -d -x`) spellings. `permissions.deny` ships literal rules only for the 4 spellings this repo's own hook test fixture (`DENIED_BASH_COMMANDS` in `tests/test_agent_hooks.py`) already asserts, each also in a `git * clean ...` form so a global option before the subcommand does not defeat it; anything else — e.g. `git clean -fxd` — is hook-only. The same applies to `rm`'s recursive+force flags: the shipped `rm` rules are exact literal spellings mirroring that same fixture, so an extra/reordered flag the hook still normalizes past (e.g. `rm -v -rf /`) is not natively covered.
- **Substring-anywhere-in-argument matching.** The SQL "drop database" check (`psql`, `mysql`, `mariadb`, `sqlite3`) has no program-position or subcommand shape at all — the hook lowercases every argument and checks for a `"drop database"` substring anywhere. `permissions.deny` ships the literal upper- and lower-case spellings only (`Bash(psql *DROP DATABASE*)`, `Bash(psql *drop database*)`); mixed case (`Drop Database`) is not covered natively.
- **Compound commands ARE covered, contrary to older assumptions.** Claude Code's Bash matching engine natively splits on `&&`, `||`, `;`, `|`, `|&`, `&`, and newlines, and requires each resulting subcommand to match independently. A rule like `Bash(rm -rf /)` is not bypassed by `safe-cmd && rm -rf /`. Wrapper-stripping is also built in for a fixed set (`timeout`, `time`, `nice`, `nohup`, `stdbuf`, `command`/`builtin`, `noglob`, flagless `xargs`) — but NOT for `direnv exec`, `devbox run`, `mise exec`, `npx`, `docker exec`, `watch`, `setsid`, `ionice`, `flock`, or `find -exec`/`-delete`. A rule like `Bash(rm *)` does not cover `docker exec ctr rm -rf /`; the hook, which follows nested interpreter payloads explicitly, still does.
- **A destructive command reached over `ssh`.** The hook follows the remote command as a nested payload, so `ssh -p 2222 host "kubectl delete pod web"` is denied. Natively it is one quoted argument with no anchorable shape: a rule broad enough to see inside it (`Bash(ssh * delete *)`) would deny ordinary remote work, so none is shipped. Hook-only, deliberately. A *value-taking* global option before the payload (`-p 2222`, `-o Key=value`) is the shape that used to defeat the hook here too — see issue #207 and `_VALUE_TAKING_OPTIONS` in the guard. The bare spelling, `ssh host rm -rf /`, is equally legal and equally denied (issue #215); it is what any tool assembling an argv rather than a command line emits, and it is *less* natively anchorable than the quoted form, not more.
- **Read-only secret protection is new, not a restatement.** The `Read(...)` deny rules (e.g. `Read(*.pem)`, `Read(secrets/**)`) cover a gap the edit guard never had: `raven-pre-edit-guard.py` only fires on `Write`/`Edit`, so nothing previously stopped a plain `Read` of a secret-bearing path. Per Claude Code's documented behavior, a `Read(...)` deny rule also blocks `Edit`/`Write` on the same path, so a parallel `Edit(...)` rule is intentionally not shipped alongside each `Read(...)` rule — see `tests/test_permissions_deny.py::NoCautionOrEditRuleAdditionsSlippedIntoDenyTests`.
- **Piping a fetched URL into an interpreter.** `curl -sSL URL | sh` is a relationship between two command segments — something fetches, something else interprets stdin — and a `Bash(...)` pattern matches one subcommand at a time. This is the one gap here that a glob cannot close *at any cost in precision*: a rule broad enough to reach it (`Bash(curl *)`, `Bash(sh)`) would deny ordinary work. No `curl`/`wget` entry is shipped, and `tests/test_permissions_deny.py::PipeToShellIsHookOnlyTests` asserts that absence so a future audit does not read it as an oversight (issue #212). The hook denies both the piped form and the `sh -c "$(curl ...)"` substitution form, for shells and for `python3 -`/`node`/`ruby`/`perl` reading stdin. It is a speed bump, not a boundary — fetching to a file and running it in two steps still works, and is meant to: the value is that the one-liner from a just-read README stops being frictionless.
- **`git checkout -f` with no pathspec.** The shipped git-verb rules are the flag-carrying spellings *with* an operand (`Bash(git checkout -f *)`), because a trailing `" *"` needs a real space and argument in the command. The hook denies the bare form too — `-f` on `checkout`/`restore` always means "discard whatever is in the worktree", operand or not (issue #210).
- **Claude Code also has an independent, non-configurable circuit breaker** for `rm -rf /` and `rm -rf ~` (including through `$(...)`/backtick/`<(...)` substitution), active even in `bypassPermissions` mode. This is separate from, and does not substitute for, the explicit `permissions.deny` rules shipped here — the other destructive intents (`git reset --hard`, `git clean -fdx`, `dropdb`, `kubectl delete`) have no such built-in breaker, and an explicit project-level rule is portable documentation of intent regardless of how the breaker's exact scope evolves.

### `Read(...)` pattern depth, and the `.env` family

Read and Edit rules use gitignore pattern syntax, and a **bare filename with no slash matches at any depth** — `Read(.env)` and `Read(**/.env)` are equivalent, so `packages/api/.env` is already covered without a `**/` entry (measured against code.claude.com/docs/en/permissions.md, 2026-08-13; the same measurement is what the `secret`/`credential` entries and `tests/test_permissions_deny.py::_read_rule_matches` rest on). A single directory segment like `secrets/**` also matches at any depth *in a deny rule* specifically, though not in an allow rule. This is recorded here rather than beside the block because `settings.json` is strict JSON and cannot carry a comment.

Two decisions behind the `.env` entries (issue #213):

- **`Read(.env.*)` deliberately catches `.env.example` too.** Rules are evaluated deny → ask → allow, so a deny rule cannot carry an allowlist exception; keeping the template readable would mean enumerating the secret-bearing variants instead and leaving an unlisted one (`.env.prod`) exposed. That is the wrong direction for a secrets rule, and the cost is small — a `Read` deny does not stop `cat .env.example`, which is the same known ceiling every `Read(...)` entry here has.
- **`.envrc` is in scope.** direnv's file is a shell script that commonly exports the same secrets, and it matched nothing before.

`raven-pre-edit-guard.py`'s `BLOCKED` list carries the same two patterns, so Codex — which has no `permissions` layer at all — gets the same coverage.

`tests/test_permissions_deny.py` is the enforcement point for keeping `permissions.deny` from drifting out of sync with the hooks: it reads the edit guard's real `BLOCKED`/`CAUTION` module-level lists and the bash guard's own `DENIED_BASH_COMMANDS` test fixture, cross-checks them against the real, parsed `permissions.deny` array, and asserts no caution-tier pattern ever appears there.

## Required Verification Pattern

For implementation work:

1. Discover the smallest sufficient context.
2. Verify candidate context with deterministic tools before editing.
3. Make the smallest coherent change.
4. Run the narrowest relevant verification.
5. Broaden verification only after narrow checks pass.
6. Report what was verified and what remains unverified.

A reported status is not the same signal as the thing it reports on:

- **A background or piped command's exit status can lie about the real command's outcome.** A backgrounded script ending in a trailing construct (`echo "done"`, a wrapper's own final line) reports the wrapper's exit code, not the real command's — the real command can have failed non-zero moments earlier. A pipeline's exit status is the last stage's, not the first's: `some-command | tail -f` reports `tail`'s code, so an upstream failure reads as success. Capture and check the actual command's own exit status (`PIPESTATUS[0]` in bash, `$pipestatus[1]` in fish) rather than trusting a wrapper or pipeline's trailing status. Two more shapes report zero by design: a gate script that runs each check as `check || true` and tallies at the end, and a wrapper that returns empty output for a command it does not understand. Empty output with a zero exit is an unanswered question. Read the line that decides the result (`N tests run`, `Checks failed:`, `PASS`), and re-run through `rtk proxy` when RTK's summary is empty.
- **For backgrounded work, verify the durable artifact** — a file changed on disk, a commit that exists, a ref that was pushed — rather than trusting a completion notification that only reflects the launcher's own exit code.
- **A hard-killed write-heavy command can destroy files, not just fail.** A commit, build, or migration killed by SIGTERM/timeout mid-write can leave partially-written, reverted, or deleted files on disk; "timed out" reads as merely slow, not as potentially destructive. Check the affected files' on-disk state before treating a timeout as harmless, and prefer a generous timeout over a tight one for exactly this reason.

## Pause-And-Ask Enforcement Is Prose-Only

`AGENTS.md`'s Pause And Ask categories (auth/secret handling, destructive operations, schema/migration changes, dependency additions, etc.) are enforced by the agent self-identifying a match, every time — nothing in the hook chain greps a diff against them, and there is no fallback if the agent misses one. A project extending this list with its own literal protected paths in `CLAUDE.md`/`AGENTS.md` inherits the same gap: it is a list a human wrote for an agent to remember, not something a hook checks. An opt-in mechanical backstop — a hook that greps a staged/pushed diff against a project-declared list of protected path globs and warns or blocks — would let a downstream project's own extensions to this list get an actual check, but does not exist today.

## Local Hooks Validate Ambient State, Not A Clean Checkout

Local pre-commit/pre-push hooks run in the contributor's normal, already-warmed-up shell — not the from-scratch environment CI always is. A bug that only manifests when some piece of ambient state (an exported environment variable, a cached file, an already-installed tool) is *absent* can stay invisible to every local hook run indefinitely: if every contributor's day-to-day shell already has that state present from ordinary use, no local hook ever exercises the failing branch, while a from-scratch checkout hits it every time. This is a different shape than a missing or misconfigured interpreter (where pointing the hook at the right one fixes it) — here the destination project's own code has a latent bug that only a genuinely clean environment triggers, and no amount of retargeting the hook closes the gap. Local hooks validate "did I break something my environment can see," not "does this work from zero." Treat a periodic clean-environment smoke check (an `env -i`-style invocation, or a CI-only step) as a deliberate companion to ambient pre-commit/pre-push hooks, not a redundant one — it exists specifically to catch the class of bug ambient hooks structurally cannot.

## Override Rules

- Destructive commands require explicit user approval.
- Template overwrites require explicit path arguments to `scripts/raven.py`.
- Missing-tool reminder suppression requires explicit user approval and must be recorded through `.claude/scripts/raven-tool-check.py --no-reminder`.
- Optional tools must not become hard requirements unless the repository documents them as required.

## Maintenance

- Add deterministic checks when a repeated agent failure can be detected mechanically.
- Add or update skills when the failure is procedural.
- Keep root instructions short; move detailed guardrail explanations into this file or a skill.
