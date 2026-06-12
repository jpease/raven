---
name: raven-commit
description: Use when writing git commit messages. Enforces Conventional Commits format.
allowed-tools: Bash(git *)
---

# Conventional Commits

## Commit format

```
<type>[optional scope]: <description>

[optional body]

[optional footer(s)]
```

## Types

| Type       | Use when                                 | SemVer impact |
| ---------- | ---------------------------------------- | ------------- |
| `feat`     | Adding a new feature                     | MINOR         |
| `fix`      | Patching a bug                           | PATCH         |
| `docs`     | Documentation only                       | none          |
| `style`    | Formatting, whitespace (no logic change) | none          |
| `refactor` | Neither a fix nor a feature              | none          |
| `perf`     | Performance improvement                  | none          |
| `test`     | Adding or fixing tests                   | none          |
| `build`    | Build system or dependency changes       | none          |
| `ci`       | CI configuration changes                 | none          |
| `chore`    | Misc tasks (e.g. release scripts)        | none          |
| `revert`   | Reverting a prior commit                 | none          |

## Breaking changes

Two ways to mark — use one or both:

1. Append `!` after the type/scope: `feat!:` or `feat(api)!:`
2. Add a footer: `BREAKING CHANGE: <description>`

Breaking changes trigger a MAJOR SemVer bump regardless of type.

## Rules

- **Description**: lowercase, imperative mood, no trailing period, immediately after `type: `; aim for 50 characters, hard limit 72 (including `type(scope): ` prefix); test with "when applied, this change will…"
- **Body**: separated from description by one blank line; wrap lines at 72 columns (`git log` indents 4 spaces, keeping total ≤76 and within RFC 2822's 78-char limit); state the problem in present tense (what the code does _without_ this change), explain why this solution is better, and note alternatives considered and discarded; for `perf` commits include benchmark numbers and describe trade-offs (e.g. CPU vs memory vs readability); if you find yourself explaining a tricky implementation detail, consider whether a code comment would serve future readers better
- **Self-contained**: include all relevant context directly — external links (PRs, issues, benchmarks) may disappear; the message must stand alone
- **Footers**: one blank line after body; format `Token: value` or `Token #value`; multi-word tokens use `-` (e.g. `Reviewed-by`); use `Fixes: abcdef012345 ("subject")` when the commit corrects a bug introduced by a prior commit; exception: `BREAKING CHANGE` (with space) is valid
- **`BREAKING CHANGE`** footer token must be uppercase
- **`BREAKING-CHANGE`** is synonymous with `BREAKING CHANGE` in footers
- Types and scopes are case-insensitive (except `BREAKING CHANGE`)
- **No AI attribution**: never add `Co-Authored-By`, `Generated-by`, or any footer or comment crediting an AI agent (Claude, Codex, Gemini, Copilot, etc.); commits represent the human author's work

## Examples

```
# Minimal
docs: fix typo in README

# With scope
feat(lang): add Polish language support

# Breaking change with !
feat(api)!: remove deprecated /v1/users endpoint

# Breaking change with footer
feat!: drop Node 6 support

BREAKING CHANGE: uses optional chaining, not available in Node 6.

# Bug fix with body and footers
fix: prevent request race condition

Introduce a request ID tied to the latest request.
Dismiss responses that don't match the latest ID.
Remove now-obsolete timeout workarounds.

Reviewed-by: Z
Refs: #123

# Revert
revert: let us never again speak of the noodle incident

Refs: 676104e, a215868
```

## Referencing commits

When a body references another commit, use at least 12 hex characters of the hash plus the subject and date (shorter IDs risk collisions as the repository grows):

```
fix: correct off-by-one in pagination

Regressed in f86a374abc12 (pagination: switch to cursor-based offset, 2024-11-03).
```

Obtain this format with `git show -s --date=short --pretty='format:%.12h (%s, %ad)' <commit>`.

## Workflow guidance

- **One concern per commit.** If a change fits multiple types, split into multiple commits. If the body is growing long, that is a signal the patch does more than one thing.

- **Wrong type before merge**: use `git rebase -i` to fix. After release, leave it — tools will simply ignore the non-conforming commit.

## SemVer mapping

```
fix            → PATCH
feat           → MINOR
BREAKING CHANGE → MAJOR  (overrides all other types)
```
