---
name: raven-review-pr
description: Use when reviewing a diff, branch, or proposed patch for correctness and maintainability.
---

# Review PR

## Skip When

- The user did not ask for a review of a diff, branch, PR, or proposed patch.
- The task is to implement changes rather than assess existing changes.

## Required Constraints

- Findings must lead the response, ordered by severity.
- Each finding must include file/line evidence when available, severity, confidence, why it matters, and a suggested fix.
- Do not report style-only issues unless they violate documented conventions.
- Do not invent risk. If evidence is weak, state it as an open question instead of a finding.
- Do not over-compress semantic diffs when reviewing correctness.

## Process

1. Inspect changed files and diff summary.
2. Use full diff when necessary.
3. Use LSP diagnostics on changed files.
4. Use LSP references or `rg` for changed public APIs or shared modules.
5. Use tests and build output through RTK.
6. For each test the diff adds or changes to cover a behavior change, run a negative control in a throwaway worktree so the reviewed tree is never touched: `git worktree add --detach <tmp> <base>`, copy the diff's test files into it, run those tests there, and confirm they fail on the asserted behavior with no import or fixture errors. Then `git worktree remove --force <tmp>`. Base lacks the change's new implementation files too, so this covers committed, uncommitted, and new-file diffs alike. A new test that passes without the change is a finding. Skip this for refactor-only diffs.
7. Report issues by severity: correctness, safety/security, maintainability, test coverage, and performance.
8. Check findings against `.claude/docs/raven-antipatterns.md`. Cite a matching entry instead of re-explaining it; on a genuine second occurrence, propose a new entry per that doc's format and write it only once the user authorizes.
9. Recommend promoting a mechanically detectable recorded pattern to a Semgrep rule wired into the gate, naming the check — do not write the rule or gate change yourself; that is separate, authorized implementation work per Pause And Ask. If no such tool is configured, skip promotion and leave the entry at `observed`.

When the session reviewing the diff also wrote it, delegate an independent pass to the `raven-code-reviewer` subagent with the base ref, the plan or acceptance criteria, and the test command.

## Output

Use this shape:

- `Severity`: file:line, confidence, issue, impact, suggested fix.
- `Registry`: matched entries cited, proposed entries and promotion recommendations awaiting authorization.
- `Open questions`: only when needed.
- `Residual risk`: checks not run or areas not reviewed.
