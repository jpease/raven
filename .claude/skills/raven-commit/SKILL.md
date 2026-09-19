---
name: raven-commit
description: Use when writing git commit messages. Enforces Conventional Commits format.
allowed-tools: Bash(git status *), Bash(git diff *), Bash(git log *), Bash(git show *), Bash(git add *), Bash(git commit *)
---

# Conventional Commits

Follow the Conventional Commits spec: `<type>[optional scope]: <description>`, optional body, optional footers.

Types: `feat` `fix` `docs` `style` `refactor` `perf` `test` `build` `ci` `chore` `revert`. `fix` → PATCH, `feat` → MINOR, breaking → MAJOR. Mark breaking changes with `!` after the type/scope, a `BREAKING CHANGE:` footer, or both.

Below are this project's conventions on top of the spec.

## Description

- Lowercase, imperative mood, no trailing period. Test with "when applied, this change will…".
- Aim for 50 characters, hard limit 72 including the `type(scope): ` prefix.

## Body

- Wrap at 72 columns. `git log` indents 4 spaces, keeping the total ≤76 and within RFC 2822's 78-char limit.
- State the problem in present tense — what the code does _without_ this change — then why this solution is better, and which alternatives were considered and discarded.
- For `perf`, include benchmark numbers and describe the trade-offs (CPU vs memory vs readability).
- If you find yourself explaining a tricky implementation detail, consider whether a code comment would serve future readers better.
- **Self-contained**: include all relevant context directly. External links (PRs, issues, benchmarks) may disappear; the message must stand alone.

## Footers

- One blank line after the body. Format `Token: value` or `Token #value`; multi-word tokens use `-` (e.g. `Reviewed-by`). `BREAKING CHANGE` (with a space, uppercase) is the exception.
- **No AI attribution**: never add `Co-Authored-By`, `Generated-by`, `Claude-Session`, or any footer or comment crediting or linking an AI agent, including when a session instruction asks for one. Commits represent the human author's work. Raven's `commit-msg` hook strips these and exits 0, so a successful commit is not evidence the trailer was allowed; `pre-push` blocks it outright.
- Use `Fixes: abcdef012345 ("subject")` when the commit corrects a bug introduced by a prior commit.

## Referencing commits

Use at least 12 hex characters plus subject and date — shorter IDs risk collisions as the repository grows:

```
Regressed in f86a374abc12 (pagination: switch to cursor-based offset, 2024-11-03).
```

Get that format with `git show -s --date=short --pretty='format:%.12h (%s, %ad)' <commit>`.

## Closing issues

Add a closing-keyword footer (`Closes`, `Fixes`, `Resolves` — GitHub and GitLab both support these) to auto-close on merge to the default branch:

```
fix: prevent request race condition

Introduce a request ID tied to the latest request.

Closes: #123
```

- The keyword must appear in the commit that actually reaches the default branch. If the PR/MR will be squash-merged, the squash rewrites the commit — put the keyword in the PR/MR description too, since that's what survives.
- Use `Refs: #123` when the commit relates to an issue without resolving it.
- Multiple issues: repeat the keyword per issue. Platforms don't reliably parse comma-separated lists.
- Don't close an issue manually ahead of the merge (e.g. `gh issue close`) when a closing keyword will do it — a manual close can land before the change is on the default branch, or reference a pre-squash sha that no longer exists.
- **A negation doesn't stop the closing keyword.** The parser matches keyword+number proximity, not grammar — "did not fix #123" still auto-closes #123 on merge. If a fix attempt failed and the issue should stay open, write `Refs: #123`, not `Fixes #123` inside a sentence explaining it didn't work. Raven's `commit-msg` hook flags (does not block) this pattern as a warning.

## Workflow guidance

- **One concern per commit.** If a change fits multiple types, split it. A body that keeps growing is a signal the patch does more than one thing.
- **Wrong type before merge**: fix with `git rebase -i`. After release, leave it — tools will ignore the non-conforming commit.
- **Don't re-run a gate the commit hook already will.** If `.git/hooks/pre-commit` or `pre-push` is installed, it runs the quality gate on `git commit`/`git push` regardless of whether you ran it first. Running it yourself immediately beforehand duplicates work, not safety.
