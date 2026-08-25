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

- This repository is public. Everything committed here — including `docs/superpowers/` specs and plans — is world-readable.
- Dogfooding and downstream validation happen in private repos. Refer to them by role, never by name: "a private iOS app repo", "the #60 reporter", "a downstream Node consumer".
- Do not commit local absolute paths. Write repro steps as `cd <downstream-repo> && raven doctor`, not `cd /Users/<name>/Developer/...`.
- This matters most in specs and plans, which are written during dogfooding — exactly when naming the real test repo is the natural thing to type.
- `just check-fast` (and therefore the pre-commit hook) runs `scripts/check-staged-hygiene.py`, which blocks a commit whose staged diff adds a home-directory absolute path (macOS `/Users/<name>`, Linux `/home/<name>`, Windows `C:\Users\<name>` or `C:/Users/<name>`, WSL `/mnt/c/Users/<name>`, or `~`/`$HOME` — matched case-insensitively, tolerant of doubled separators, and exempting known-shared segments like `/Users/Shared` or `C:\Users\Public`) or, if `.git/info/raven-private-names` (or `RAVEN_HYGIENE_DENYLIST`) lists one, a private repository name (matched as a whole word; entries under 5 characters are dropped at load time as too likely to false-positive). It scans added lines — including a narrow 2-line join, to catch a name or path split across a line break — plus the destination *path* of every new, modified, or renamed staged entry, not just file content, discovered via `git diff --cached --name-status -z` so a path holding a space, an embedded quote, or a non-ASCII character is scanned correctly regardless of `core.quotePath`; `uv.lock` is no longer exclude-listed, since word-boundary matching already keeps routine hash/version-bump noise from tripping the name check. A binary file's content is never scanned (a binary diff has no line content to see, an accepted permanent gap), though its path still is. A staged hunk this checker cannot parse is reported as its own explicit finding rather than silently skipped — in practice, `git diff --cached` never emits such a hunk today, including for a staged merge-conflict resolution, so this is a defensive backstop, not an observed gap. Removing a leak is never itself a violation.
- A line the checker flags but that is legitimate (this rule's own prose, a test fixture asserting the detector works, documentation *about* the pattern) can carry a trailing `raven-hygiene: allow` comment to suppress that line — visible in the diff, reviewable, and not a file- or directory-level exclusion. In a `.py` file a marker on a line holding only closing brackets and commas also covers back to the line its outermost bracket opened on, because `ruff format` splits a long call and carries the trailing marker down to the closing bracket, stranding the text the marker was written for (#237). Reach stops at that construct; bracket pairing runs over `tokenize`, so a bracket inside a string literal never pairs with a real one, and a file that will not tokenize falls back to the marker covering its own line. A path-level finding has no line to carry that marker; rename the path instead. Keep the local name list itself out of tracked files: in local memory or `.git/info/`-excluded config; putting it in a tracked file recreates the leak.

## Gate Relaxation

- Raven's guidance tells an agent not to weaken a gate in eight places and, until #229, enforced it in none. A rule the agent can relax is a prompt, not a control.
- `just check-fast` (and therefore the pre-commit hook) runs `scripts/check-staged-relaxation.py`, which blocks a staged change that adds a suppression comment to a `.py` file with no rule code or no reason (`# noqa`, `# type: ignore`, `# pyright: ignore`, plus the file-level `ruff: noqa` and `mypy: ignore-errors` blankets, which have no narrow form); edits a linter config so it checks less (widening ruff's `ignore`, adding a `per-file-ignores` entry, dropping a rule from `select`, lowering pyright's `typeCheckingMode`, turning on mypy's `ignore_errors`); or switches a test off — an unconditional skip, or a diff that ends with fewer test functions in a file than it started with.
- Tightening is silent. Adding to `select`, removing from `ignore`, raising `typeCheckingMode`, a conditional `skipif`/`skipUnless`, and a rename that adds the test back all pass.
- The suppression and config detectors both parse the committed and staged blobs of the same file rather than reading the diff, so a relaxation buried in a reformat is still seen and a suppression the file already carried is grandfathered (#233). A suppression is matched by its form, its rule codes, and whether a reason follows, so one that moved, was reindented, or travelled through a rename stays silent, while a second copy of it, or one that lost its reason, reports. `pyproject.toml`, `ruff.toml`, `pyrightconfig.json`, `mypy.ini`, `setup.cfg`, `tsconfig.json`, and `Cargo.toml` are compared for config — the last two close to free, since JSON and TOML parsers already exist here for the rest (#245); `raven_lib/gate_config.py` records why ESLint's and the remaining five languages' formats still are not.
- The `raven-hygiene: allow` marker suppresses a relaxation finding on the line it appears on, the same as a hygiene finding, and reaches back over a closing-bracket construct in the same way — `ruff format` splits a long `@pytest.mark.skip(reason=...)` and leaves the marker on the bracket, away from the decorator line the skip detector reports (#237). For a config file the marked line is dropped before parsing, so it never enters the comparison; on both sides of a suppression comparison, so that deleting a marker from a still-reasonless suppression starts reporting it again. A test-count finding has no line of its own — a marker on any added line in that file suppresses it.
- `raven assess` reports the same relaxation as a standing state rather than a delta: a ruff config that selects a rule family and then ignores all of it, a `per-file-ignores` keyed on `*`, an `exclude` covering the whole tree, a `typeCheckingMode` below the `standard` floor the python template ships, a `tsconfig.json` with `strict`/`noImplicitAny`/`strictNullChecks` off, or a `Cargo.toml` `[lints]` entry that allows an entire lint family (`clippy::all`, rustc's `warnings`).
- `common/.raven/git-hooks/lib/check-gate-relaxation.py` is the shipped half of the staged check (#231), invoked from the shipped `pre-commit` beside the attribution and managed-block scripts. It reports a *blanket* suppression — one naming no rule — in any of the eight languages Raven declares gates for, chosen by each staged file's own extension rather than by the configured template, so a polyglot repo gets the right detector per file. Same blob comparison and same `raven-hygiene: allow` marker as the repo-only checker. It deliberately drops three things that checker has, each argued in its docstring: no config comparison at all, even for `tsconfig.json`/`Cargo.toml` now that the repo-only checker reads them (#245) -- that stays an architectural choice, not a format limitation, for every language; no test-deletion detector; and no reason requirement, since only Python has a settled place to put one. Every syntax was run against the real linter before earning a detector, and the observed behavior and upstream URL sit beside each pattern. `raven doctor`'s `doctor.hooks.gate_relaxation` reports the checker and names any of the template's source extensions it cannot read, so a language with no detector says so rather than passing silently. Config comparison and the test-count detector stay repo-only, like `check-staged-hygiene.py`.

## Local Instruction Boundary

- Project-specific instructions for maintaining Raven belong above the managed block in this file.
- The block between `RAVEN:BEGIN` and `RAVEN:END` is managed template content used to test safe block upgrades.
- Do not edit inside the managed block directly; update the source template instead.

<!-- RAVEN:BEGIN sha256=b4eaaa122f9776b24a91cd697d32fee400ec42c24d21ff93dd350265b9c40354 -->
# AGENTS.md

## Primary Objective

Be effective while preserving context. Prefer targeted retrieval, summaries, and deterministic tools over broad file reads.

## Canonical Context

- `AGENTS.md` is the authoritative root instruction file.
- `.agents/skills/` is the canonical location for reusable skills.
- Agent-specific skill paths (e.g. `.claude/skills`) should point to `.agents/skills`, not duplicate content.
- When a `raven-*` skill and a generic skill cover the same intent, prefer the `raven-*` one — it encodes this project's guardrails.
- Deeper guidance lives in `.claude/docs/`: `raven-authority-map` (canonical vs non-canonical context), `raven-guardrails` (guardrail types), `raven-coding-principles` (cross-language quality), `raven-namespace` (Raven-owned files), `raven-agent-compatibility` (canonical vs Claude/Codex adapters), `raven-lsp-mcp` (LSP-over-MCP and language-server defaults), `raven-antipatterns` (repo-specific recurring-issue registry).
- If another tool inserts a managed block in `AGENTS.md`, treat it as authoritative for that tool's commands, syntax, and resource names — not as an override of these workflow guardrails.

## Retrieval Discipline

Use the cheapest adequate source before reading full files.

| Need | First tool |
|---|---|
| Exact string, symbol, config key, or error | `rg` |
| File discovery by name, type, or extension | `fd` |
| Definition, references, type info, diagnostics | LSP |
| "How does X work?" / conceptual flow discovery | `mcp__gitnexus__query` |
| Blast-radius before editing a symbol | `mcp__gitnexus__impact` |
| Syntax-aware pattern or mechanical rewrite | ast-grep or Semgrep |
| Build, test, or log output | RTK-wrapped shell command |

- `rg` is recursive by default; never pass `-r` for recursion. `-r` is ripgrep's `--replace` and takes an argument — unlike grep's `-r`, which means `--recursive`.
- `rg`, `fd`, and `ast-grep` skip dot-directories by default. Raven's `.ignore` re-admits `.agents/`, `.claude/`, `.codex/`, and `.raven/` in a tree Raven installed into. Elsewhere — an uninstalled tree, or `$HOME`, which Raven deliberately skips — an empty result proves nothing until you re-run with `--hidden` (`--no-ignore hidden` for ast-grep) or `git grep`.
- Run ast-grep by full name as `ast-grep --lang <lang> -p '<pattern>'`, never the `sg` alias. An empty result is not absence until `--debug-query=ast` shows the pattern parsed as intended.
- Batch independent reads, searches, and inspections per turn.
- Skeleton-first: for a large or unfamiliar file, get a symbol map (LSP document symbols, or `ast-grep`/`rg`) before reading, then read only the ranges you need — read a full file only when it is small or the whole structure matters.
- Return concise findings before editing.
- When two literal `rg` guesses miss, switch tools rather than iterating term variations. `mcp__gitnexus__query` is the conceptual-discovery step where an index is configured — it returns execution paths grouped by process, not just file locations. It is not proof: verify with `rg`, LSP, targeted reads, or tests before changing code.
- GitNexus tools are spelled `mcp__gitnexus__<tool>`. Vendor-generated GitNexus content uses shorter labels (`impact()`, `gitnexus_query`) for the same tools — read them as the MCP tools, and take parameter names from the tool schema, not from the skill prose. No MCP grant? A subagent with Bash but no MCP access can reach the same operations via the CLI: `gitnexus query|context|impact|trace|detect-changes`.
- Stop when two or more appropriate tools have failed to locate a credible file, symbol, or integration point. Summarize what was tried and delegate per the Delegation section, or ask the user.
- Tool availability comes from the session capability roster. If no roster is present, probe before relying on any non-baseline tool. MCP servers the roster lists as configured may still be unapproved or unconnected; a failed call is information, not a contradiction of the roster.
- When the repo configures a code-intelligence index (such as GitNexus), its impact analysis before a symbol edit and change-detection before a commit are mandatory, not optional table picks. If it is stale, reindex or say so — do not silently skip it.

## Delegation

Delegate or ask when the scope of a task exceeds what targeted retrieval can resolve in the main context. Use the `raven-delegate-or-inline` skill for the decision criteria, delegation mechanics, and anti-habit checks. Raven ships `raven-security-reviewer`, `raven-refactor-reviewer`, `raven-test-debugger`, and `raven-codebase-cartographer` as Claude Code subagents for common audits. Sub-agent returns must include an `## Out Of Scope Findings` section; disposition those findings per `raven-triage-discovery` rather than leaving them in chat or in an issue comment.

## Shell Command Policy

Use RTK for commands likely to produce noisy output:

- tests and builds
- package managers
- large diffs or recursive listings
- cloud CLIs
- Docker and Kubernetes commands

Prefer `jq`/`yq` over `grep`/`sed`/`awk` for structured JSON/YAML.

Do not use RTK when exact raw output matters — small precise diffs, generated code, compression-sensitive compiler output, or security-sensitive review.

## Pause And Ask

Pause and ask before work that is ambiguous or could create durable harm:

- public API, schema, migration, compatibility, or release behavior changes
- auth/authz, secret handling, destructive operations, filesystem deletion, or network exposure
- dependency additions, license-sensitive code, vendored code, or generated artifacts
- broad refactors, cross-module architecture changes, or unclear scope boundaries
- any task where the safe behavior depends on product intent the repo does not make clear

## Editing Rules

- Make minimal patches.
- Before changing public APIs, check references with LSP and repo-configured impact analysis.
- Before large mechanical edits, use ast-grep or Semgrep.
- Run the narrowest relevant test first.
- If tests fail, inspect only failing output first.

## Verification State

- If you lose track of what was verified, re-verify before editing further or claiming completion.
- Do not claim broad success from narrow checks; state exactly what ran and what remains unverified.
- After context compaction or a long interruption, restate the current goal and verified state before continuing risky edits.

## Convergence

- A task ends in success, progression (one blocker removed, the next isolated with evidence), or stop. Progression is an acceptable end state; report it plainly.
- Stop and report when the same test has failed after three consecutive fixes aimed at it, when a fix needs code the task did not scope, or when the diff grows while the failing signal does not change.
- Do not keep patching once the work stops converging. Partial work leaves the codebase more legible than it was.
- `raven-task-complete` states the test for each of the three states; `raven-debug-failure`'s `When To Stop` covers the narrower case where ownership was never found.

## Safety Rules

- Do not run destructive commands without explicit approval.
- Before offering to run a destructive command, check whether approval can lift the block. A hard deny cannot be granted in chat.
- Do not substitute an equivalent-effect command when a guardrail blocks one. A block denies the outcome, not the command string: report it and hand the command to the user.
- Do not modify secrets, credentials, generated files, lockfiles, or migrations unless required.
- Do not add dependencies without explaining why.
- Never hide uncertainty; state confidence and unresolved assumptions.
- Agreement is not helpfulness. Before ratifying a design, plan, or conclusion the user proposed, name the specific thing you would change, or state why you agree with it.

## Platform Awareness

- Prefer portable commands and hooks for guidance shared across macOS, Linux, Windows, and WSL.
- On Windows, account for PowerShell/CMD path behavior and native-vs-WSL execution.
- Treat `.mcp.json` tools as locally configured capabilities, not guaranteed dependencies.

## Tool Availability Memory

- When recommended tools matter, use the `raven-tool-bootstrap` skill.
- Record verified tool availability in local user memory outside the repository.
- If recommended tools are missing, ask whether to install them, provide instructions, remind later, or stop reminding.
- Do not install tools or suppress future reminders without explicit user approval.
- If a SessionStart hook reports missing or unverified tools, ask how to proceed before relying on them.
<!-- RAVEN:END -->

<!-- gitnexus:start -->
# GitNexus — Code Intelligence

This project is indexed by GitNexus as **raven** (4250 symbols, 9118 relationships, 174 execution flows). Use the GitNexus MCP tools to understand code, assess impact, and navigate safely.

> Index stale? Run `node .gitnexus/run.cjs analyze` from the project root — it auto-selects an available runner. No `.gitnexus/run.cjs` yet? `npx gitnexus analyze` (npm 11 crash → `npm i -g gitnexus`; #1939).

## Always Do

- **MUST run impact analysis before editing any symbol.** Before modifying a function, class, or method, run `impact({target: "symbolName", direction: "upstream"})` and report the blast radius (direct callers, affected processes, risk level) to the user.
- **MUST run `detect_changes()` before committing** to verify your changes only affect expected symbols and execution flows. For regression review, compare against the default branch: `detect_changes({scope: "compare", base_ref: "main"})`.
- **MUST warn the user** if impact analysis returns HIGH or CRITICAL risk before proceeding with edits.
- When exploring unfamiliar code, use `query({search_query: "concept"})` to find execution flows instead of grepping. It returns process-grouped results ranked by relevance.
- When you need full context on a specific symbol — callers, callees, which execution flows it participates in — use `context({name: "symbolName"})`.
- For security review, `explain({target: "fileOrSymbol"})` lists taint findings (source→sink flows; needs `analyze --pdg`).

## Never Do

- NEVER edit a function, class, or method without first running `impact` on it.
- NEVER ignore HIGH or CRITICAL risk warnings from impact analysis.
- NEVER rename symbols with find-and-replace — use `rename` which understands the call graph.
- NEVER commit changes without running `detect_changes()` to check affected scope.

## Resources

| Resource | Use for |
|----------|---------|
| `gitnexus://repo/raven/context` | Codebase overview, check index freshness |
| `gitnexus://repo/raven/clusters` | All functional areas |
| `gitnexus://repo/raven/processes` | All execution flows |
| `gitnexus://repo/raven/process/{name}` | Step-by-step execution trace |

## CLI

| Task | Read this skill file |
|------|---------------------|
| Understand architecture / "How does X work?" | `.claude/skills/gitnexus/gitnexus-exploring/SKILL.md` |
| Blast radius / "What breaks if I change X?" | `.claude/skills/gitnexus/gitnexus-impact-analysis/SKILL.md` |
| Trace bugs / "Why is X failing?" | `.claude/skills/gitnexus/gitnexus-debugging/SKILL.md` |
| Rename / extract / split / refactor | `.claude/skills/gitnexus/gitnexus-refactoring/SKILL.md` |
| Tools, resources, schema reference | `.claude/skills/gitnexus/gitnexus-guide/SKILL.md` |
| Index, status, clean, wiki CLI commands | `.claude/skills/gitnexus/gitnexus-cli/SKILL.md` |

<!-- gitnexus:end -->
