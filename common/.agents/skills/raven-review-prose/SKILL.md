---
name: raven-review-prose
description: Use when reviewing prose for machine-writing tells and inflated wording, or when a draft needs rebuilding rather than editing.
---

# Review Prose

Three passes, cheapest first. Stop at any pass that resolves the piece.

## Pass 1: Vale, if installed

```bash
if command -v vale >/dev/null 2>&1; then
  vale --config=<path-to>/raven-write-prose/reference/vale/.vale.ini --output=line FILE
else
  echo "vale not installed; skipping the word pass"
fi
```

When Vale is not installed, print that one line and continue to pass 2. A missing optional tool never fails a review.

Vale covers the word half only. It cannot see a tricolon, a restating conclusion, or a dependent heading.

Two things it will flag that are correct. A file whose job is to name the banned words — the prose rules file, `reference/words.md`, the prose skills themselves — trips every word rule by design; skip those. And a `KeepTest` finding is a prompt. Read the keep-test and decide.

## Pass 2: the structural pass

Walk all twelve tells from `raven-write-prose`. Run each test rather than judging by feel. The long-word sweep is the one most often skipped and the one that finds the most:

```bash
rg -oN '\b[a-z]{9,}\b' FILE | sort -u
```

Triage every hit with one question: is there a shorter everyday word for this? Words borrowed from an outside source are where this finds the most.

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
