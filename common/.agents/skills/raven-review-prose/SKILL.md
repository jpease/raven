---
name: raven-review-prose
description: Use when reviewing prose for inflated wording and leftover scaffolding, or when a draft needs rebuilding rather than editing.
---

# Review Prose

Three passes, cheapest first. Stop at any pass that resolves the piece.

The mechanical steps run through one helper that ships per adapter: `.claude/scripts/raven-review-prose.py` (Claude Code), `.codex/scripts/raven-review-prose.py` (Codex), or `.gemini/scripts/raven-review-prose.py` (Gemini CLI). Commands below write it as `raven-review-prose.py`; run it with `python3 <that path>`. It exits 0 clean, 1 with findings, 2 when it could not run.

## Pass 0: what is under review

Reviewing a whole file? Skip to pass 1. Reviewing a branch or a diff, settle which prose the change actually introduced before flagging any of it.

A comment whose lines fall inside a diff hunk is not a comment the change wrote. Editing one line of a docstring pulls the entire docstring into the hunk, and a file rewritten in full pulls in every comment it already had. Blame each line or range you mean to flag, against the branch point:

```bash
raven-review-prose.py scope --base main FILE:42 FILE:60-71
```

Each line comes back `pre-existing` or `in scope`. Line numbers are the working tree's, so they match the file you are reading, and a line not yet committed is in scope. A line the change only moved or copied traces back to the commit that first wrote it. A base that names no commit exits 2 and labels nothing.

A finding on a pre-existing line can still be a real defect. Report it apart from the change under review rather than folding it in, and let whoever owns the branch decide.

## Pass 1: Vale, if installed

```bash
raven-review-prose.py vale FILE
```

When Vale is not installed, this prints one line saying so and exits 0; continue to pass 2. A missing optional tool never fails a review. It finds Vale's config inside the installed `raven-write-prose` skill; pass `--config` to use another.

A low finding count is good news only once you know the rules are live. `Packages` in that config *declares* proselint, write-good and Readability; nothing downloads until someone runs `vale sync` in that directory, and `write-good.Passive = YES` sits there inert until they do. The helper names each declared package missing from StylesPath before Vale's own output. Unsynced, the sentence "The results were surfaced by the system and were utilized" yields one finding and flags neither passive.

Vale covers the word half only. It cannot see a tricolon, a restating conclusion, or a dependent heading.

Two things it will flag that are correct. A file whose job is to name the banned words — the prose rules file, `reference/words.md`, `reference/words-history.md`, the prose skills themselves — trips every word rule by design; skip those. And a `KeepTest` finding is a prompt. Read the keep-test and decide.

## Pass 2: the structural pass

Walk all fourteen tells from `raven-write-prose`. Run each test rather than judging by feel.

## Mechanical checks

Run these when the user asks for a review or before a document is published. Never per edit: a transcript of a one-section README change that ran them cost ten tool calls against a control's three, for the same result. Two calls cover them:

```bash
raven-review-prose.py sweep FILE
raven-review-prose.py subjects -n 400
```

`sweep` skips fenced code and inline code spans, matches without regard to case, and joins hard-wrapped lines, so "At its core" opening a sentence and a participle wrapped onto the next line both match. Each finding reads `FILE:LINE: check: text`; `--only CHECK` narrows the run. `subjects` checks recent commit subjects for the `X, not Y` tag.

`long-word` is Orwell's rules 2 and 5 made mechanical, the tell most often skipped, and the one that finds the most. Most hits are technical terms with no shorter form and get kept; the sweep exists to make you ask the question of each one.

It also flags one fact restated across clauses: "implemented an enhanced retry mechanism to improve resilience against transient call failures" says "retry failed calls up to three times" twice. Does the word add a fact `retry` did not already carry?

`contrast-heading` and `contrast` catch the `X, not Y` tag on titles and its `rather than` form in bodies. A hit that names a thing — `not cwd`, `not Package.swift`, "filed separately rather than folded in" — rules out the wrong behavior the fix replaced and stays. A hit that rates the method — "measured rather than assumed" — goes. Position decides this, which is why no linter can: `measured|verified` against `assumed|inferred` reads both ways.

`participle` catches the trailing participle clause, the sentence-level closing flourish. Keep a hit that states a checkable consequence ("allowing a second run to resume from the lock file"); cut one that only rates the change ("improving maintainability").

`essence` and `stakes` catch essence-framing ("at its core") and stakes-inflation ("changes everything"). A heading or a named specific ("what registry v2 means") is not a hit.

## Pass 3: verdict

Report findings, or escalate to rebuild.

Report each finding in this shape:

```
Structural (README.md, para 3)
  Original:  "It's not about speed. It's about correctness."
  Suggested: "Correctness matters more than speed here."
  Reason:    not-X-but-Y construction
```

## When to rebuild instead of edit

Editing bad prose in place mostly swaps words and keeps the shape, because the draft in front of you anchors what you produce.

Escalate to rebuild when either holds:

- Four or more structural tells fire inside one section.
- Reading the whole document, the shape is the problem rather than the wording.

Below that, edit in place.

## The rebuild path

1. Reduce the piece to claims and facts. An outline, with no sentence kept intact.
2. Dispatch `raven-prose-reviewer` with the outline only. The subagent never receives the original draft — that is the entire mechanism, and passing the draft defeats it.
3. The subagent writes fresh against the `raven-write-prose` rules.
4. Review its output through passes 1 and 2.

If the dispatch fails, fall back to editing in place and say plainly in your report that shape problems will likely survive.

## When not to apply

Skip quotes, code, error strings, log output, proper nouns, and any file whose existing voice is deliberate. Read the `when not to apply` section of `raven-write-prose` before flagging any of these.
