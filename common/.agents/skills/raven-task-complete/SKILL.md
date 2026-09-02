---
name: raven-task-complete
description: Use before declaring a unit of work done to verify correctness, diff scope, and cleanliness.
---

# Task Complete

Lightweight verification ritual before declaring a unit of work finished. Closes the gap between "I think I'm done" and "I verified I'm done."

## Skip When

- The change is docs-only, config-only, or a one-line edit with no behavior change.
- The user explicitly says to skip verification and ship.

## Required Constraints

- Do not declare a task done without running at least the narrowest relevant verification.
- State what was verified and what was not — never silently skip a step.
- Do not generalize a narrow check into a broad claim. If you ran one test file, say that — not "all tests pass." Name the exact scope you verified.
- If a verification step fails, address it before proceeding.
- State design intent that is not derivable from the diff: the constraint that forced this design, the alternative rejected, or a non-obvious behavior. If nothing forced a decision, say so explicitly rather than padding.

## Terminal States

A unit of work ends in one of three states. Name which one before handing off.

| State | What it means | Test |
|---|---|---|
| Success | The capability works on the real path, and the case that motivated the work behaves differently now. | Run what was asked for and show the output. |
| Progression | One blocker is removed and the next is isolated. This is a success condition, not a partial failure. An agent with no way to report it plainly is the one that tries a fifth patch. | The report carries the blocker removed, the next blocker, and the evidence isolating it: a failing command, a stack frame, a diff that moves the symptom. |
| Stop | Further work needs scope the task does not have, a patch over the cause instead of a fix, or logic that can no longer be followed. | One trip condition holds: the same test failed after three consecutive fixes aimed at it; a fix needs code the task did not scope; the diff grows while the failing signal does not change. |

Stop producing patches once the work stops converging. Partial work leaves the codebase more legible than it found it: scaffolding deleted, the narrowing test kept, what was ruled out written down.

## Rationalization Check

| Thought | Reality |
|---|---|
| "This is too simple to need verification" | `Skip When` already covers docs-only/one-line edits. Anything else runs the narrowest check. |
| "It looks right, I'll say it's verified" | Looking right isn't verifying. Run the check or state the gap. |
| "It exited zero, so it passed" | An exit code is a claim. Pipes report the last stage, gate wrappers tally and exit zero, and empty output is no answer. Read the line that decides it; `raven-guardrails` lists the shapes. |
| "Nothing I touched affects the tests" | That's an assumption, not evidence. Run the narrowest relevant test to confirm. |
| "I verified this earlier in the session" | State what changed since, or re-run against the current diff. |
| "The code explains itself" | Then say that explicitly. Silence is indistinguishable from having no reason. |
| "I noted the other problems in a comment" | A comment is not a disposition. Each finding gets FOLD IN, FILE, or DROP per `raven-triage-discovery`. |
| "One more patch will fix it" | Count them. Three consecutive fixes aimed at the same failing signal is a Stop trip condition; report the state instead of trying a fourth. |
| "The gates are green, so nothing needs a human" | A gate checks what someone thought to encode. Name what it cannot: a judgment call, a chosen default, a step that is hard to undo. |

## Process

1. **Run the narrowest test** covering the changed behavior — the single test file, test case, or command most directly relevant. If no test exists and one should, note the gap explicitly.
2. **Check diff scope** — run `git diff` and confirm only intended files changed. Flag unintended files, config drift, or stray hunks.
3. **Remove debug scaffolding** — scan touched files for temporary additions left during the session: `print`, `console.log`, `dbg!`, `IO.inspect`, `fmt.Println`, temporary `TODO` comments, commented-out blocks. Then list the comment lines
   the diff adds — `git diff -U0 | rg '^\+[^+]' | rg '#|//|/\*'` — and check each
   against `raven-write-prose`'s genre rule for comments. A comment that only
   makes sense beside this diff belongs in the commit body, not the file.
4. **Run lint and type-check** on touched files using the project's configured tools. If no tool is configured, note it and skip.
5. **Disposition discovered work** — enumerate anything found during this unit that falls outside the current issue's acceptance criteria, including findings returned by sub-agents, and assign each one a disposition per `raven-triage-discovery`. "None" must be stated, not implied.
6. **Name what needs human eyes.** Rank the parts of the diff a reviewer should actually read, and say why each one: it is hard to undo, it touches stored data or a public contract, or it rests on a judgment the gates cannot check — a chosen default, a name, a trade-off. Everything else is covered by the checks that just ran. Reviewer attention is the scarce resource; spending it evenly across the diff wastes it.
7. **State the verification summary** before handing off.

## Integration with raven-project-lifecycle

When using `raven-project-lifecycle`, run this skill immediately before calling `raven-session.py --complete <unit>` (`.claude/scripts/` for Claude Code, `.codex/scripts/` for Codex). The checkpoint hook enforces completion criteria; this skill ensures you meet them before invoking it.

## Output

Always:

> State: [Success | Progression | Stop] — [the test from `Terminal States` that puts it there].

On success:

> Verified: [test command and result], [lint/type-check result]. Diff scoped to [N files]. No debug scaffolding found.

When gaps exist:

> Gap: [what was not verified and why]. Residual risk: [what remains unchecked].

Always:

> Needs review: [the parts a human should read, most consequential first, each with the reason]. If none: `Needs review: none — the gates cover this diff.`

Always:

> Intent: [what forced this design — the constraint, the rejected alternative, or the non-obvious behavior a future reader would trip on]. If none: `Intent: none — mechanical rename, no design decision.`

Always:

> Discovered work: [each item's disposition per `raven-triage-discovery`]. If none: `Discovered work: none.`
