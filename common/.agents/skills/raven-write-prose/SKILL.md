---
name: raven-write-prose
description: Use when drafting or editing prose — comments, READMEs, docs, specs, commit messages, issue bodies. Plain-language rules plus a structural edit pass.
---

# Write Prose

Plain words are part of good prose. The larger part is structure — rhythm, list length, hedging, signposting — and a word swap reaches none of it.

**These tests do not detect machine writing.** What they measure is scaffolding a writer leaves in: an essay signposts, runs sentences to a similar length, and closes paragraphs rhetorically, whichever kind of writer made it. Use them as an edit pass on a draft, never as evidence about who wrote something.

## Correctness first

The fourteen tests measure scaffolding. None of them measures whether the
document is true, and the measured failures of real documentation are the other
kind: across 179 documentation units and two surveys of 323 developers, the
three severest problems were ambiguity, incompleteness, and incorrectness
(Uddin and Robillard, *How API Documentation Fails*, IEEE Software 2015). A
page can score zero tells and still send its reader to a flag that no longer
exists.

So run your genre's question before any of the fourteen:

| genre | the question |
|---|---|
| code comment | does this still describe what the code does? |
| docstring | does the function raise, return, and guarantee what this says? |
| README, tutorial, how-to | did you run the commands, in order, from a clean checkout? |
| reference | is every name, type, default, and version the one in the code? |
| spec, essay | is every number and citation traceable to something you checked? |

A failure here outranks every finding below it.

Trouble writing plainly is often a signal for an unchecked claim. Verify, then write the plain version.

## Spine: Orwell's six rules

1. Never use a metaphor, simile or other figure of speech which you are used to seeing in print.
2. Never use a long word where a short one will do.
3. If it is possible to cut a word out, always cut it out.
4. Never use the passive where you can use the active.
5. Never use a foreign phrase, a scientific word or a jargon word if you can think of an everyday English equivalent.
6. Break any of these rules sooner than say anything outright barbarous.

Rule 4 needs a test of its own, because "passive" is the label most often hung
on sentences that are not passive. Orwell's own essay runs 26% passive against
a 17% baseline for transitive verbs in ordinary prose (Pullum, *Fear and
Loathing of the English Passive*). Judge by what the sentence hides: **does it
drop an actor the reader needs?** "The file is written atomically" hides
nobody. "Mistakes were made" hides the whole point.

## The fourteen tells

Each row names the artifact, gives a test you can run, and gives the fix. Run the tests; do not judge by feel. Apply the delete tests to whole paragraphs as well as sentences — an explanation that restates the rule above it goes the same way a flourish does.

| tell | test | fix |
|---|---|---|
| Signposting | Delete the sentence. Does meaning survive? | Delete it. |
| Throat-clearing | Does sentence one carry new information? | Start where information starts. |
| Tricolon default | Count list lengths. Are most three? | Cut to two or extend to four where honest. |
| `not X, but Y` | Search `not…but`, `isn't…it's`, `not about…about`, the split form `It is not A. It is B.`, and the trailing tag `X, not Y` | State Y alone. In a title, cut the tag. |
| Symmetric hedge | A sentence weighing both sides, concluding neither | Commit, or cut it. |
| Drumroll or dependent heading | Does the heading name its own content? Ordinary nesting is fine; flag one that names nothing alone, like `### Inputs` or `### Decision`. | Name it in full. |
| Restating close | Does the last paragraph hold a new fact? | Cut it. |
| Bulletification | Are the bullets full sentences that flow into each other? And the reverse: has every paragraph become a `**Label**: value` bullet? | Give flowing bullets their paragraph back, or a bulleted argument its prose. |
| No specifics | Count numbers, names, paths, versions. Zero? Applies to conceptual and summary prose; engineering docs are built from specifics and always pass. | Add them, or say you don't know. Do not cite evidence for a claim nobody would dispute. |
| Unearned confidence | Does the piece admit any dead end? | Say what you did not verify. |
| Long-word default | `rg -oN '\b[a-z]{9,}\b' FILE \| sort -u`, then triage each | Use the shorter everyday word. |
| Closing flourish | Take the last sentence of each paragraph. Does it hold a fact the paragraph did not already have? | Delete it. If it held a fact, state the fact plainly. |
| Essence-framing | Search `what (this\|that\|it)('s)? (really\|actually) (means\|is\|matters)`, `at (its\|their) core`, `(boils\|comes) down to`, `the real (question\|issue) is`. A heading or a named specific ("what registry v2 means") is not a hit. | Delete the frame; state the claim directly. |
| Stakes-inflation | Search `changes everything`, `cannot be overstated`, `profound implications`, `watershed moment`, `game-?changer`, `pivotal moment`, `marks a turning point` | Cut it, or replace with the number that earns the claim. |

The long-word sweep is Orwell's rules 2 and 5 made mechanical. Run it on anything you write. Most hits are technical terms with no shorter form and get kept; the sweep exists to make you ask the question of each one rather than only of words someone already listed.

The sweep also flags one fact restated across clauses to sound thorough. "Retry failed calls up to three times" says the whole change; "implemented an enhanced retry mechanism to improve resilience against transient call failures" says it twice, in different words. Test: does the word add a fact `retry` didn't already carry? `enhanced`, `mechanism`, and `resilience` don't — cut them.

`X, not Y` needs judgment, and here is the test: **delete the negated half. Does the sentence still say something?**

"Green tests prove behavior, not design health" → "Green tests prove behavior." Still a claim. Keep it.

"It's not about speed. It's about correctness." → the first sentence alone says nothing. That is the tell.

Use the delete test rather than a regex: most instances of the broad form are ruling out a real misreading. Reviewers reading an earlier wording of this rule flagged sentences that passed the delete test, so judge by the test and not by the shape.

One shape gets through the delete test: the tag appended to a heading, a commit subject, or an issue title. "add genre rules, measured rather than assumed" survives it, since "add genre rules" is a working subject line on its own. A title takes a second test instead: **does the negated half rule out something the reader would otherwise have expected?**

```bash
git log --format='%s' -n 400 | rg -N ',\s+(not|never|rather than|instead of)\b'
rg -N '^#{1,6}.*,\s+(not|never|rather than|instead of)\b' FILE
```

Commit subjects here carry a tag that names a thing — `not cwd`, `not the checked-out branch`, `not Package.swift`, `instead of four` — and each rules out the wrong behavior the fix replaced. One rates the method instead: "measured rather than assumed", written into this repo's log while this skill was being built.

Position decides this, not vocabulary, which is why no linter can. `measured|verified|declared` paired against `assumed|estimated|inferred` turns up both ways: naming a checkable state — "The launch-sweep cost of the repair is measured rather than assumed", "'Done' is currently self-declared rather than verified" — and rating already-gathered work, "Measured, not estimated:". Same words either way, so a token list would flag both or neither.

In a title the replacement is the number that earned the claim: "measured across nine documents" over "measured, not assumed".

Two tells read backwards from the rest. `Unearned confidence` and `No specifics` fire when something is *missing*, so a clean document scores no on both. Do not read a low total as a clean document without checking which tells the zeroes came from.

Expect the count to track document type: procedures and reference pages fire 1 to 3 tells each, a conceptual spec can fire 10, and essays fire more still. Prose that argues is where these tests earn their place, and where they are noisiest.

## Tone

- Do not be stuffy.
- Argue with evidence rather than assertion.
- Do not be too pleased with yourself.
- Do not lecture.
- Get straight in.

## Match the voice

Read the surrounding file before writing and match how it sounds. A terse codebase does not get essay comments. A file with a deliberate voice keeps it.

## Borrowed guidance gets rewritten

When you take a rule from an outside style guide, rewrite it in plain words before using it. Copying a source word for word is the most common way inflated wording enters. The five tone rules above came from a magazine guide that words two of them as "do not be hectoring" and "do not be too didactic". Both fail Orwell's rules 2 and 5.

## When not to apply

- Quotations. Keep the original wording.
- Code, error strings, and log output.
- Proper nouns and product names.
- Settled terms with no plain equivalent.
- Any file whose existing voice is deliberate.

## Genre

Read `reference/genres.md` before running the tells. Which of them can fire depends on what you are writing, and a zero from a tell that cannot fire is not a clean result. It also carries the one rule per genre worth knowing: a comment says why, a docstring states a contract, a README orients, a spec records a decision, a tutorial gets the reader to a first run that works, a how-to serves someone who already knows, a reference states what is.

## Words

Read `reference/words.md` when doing a word pass. It holds the flagged-word table with a keep-test for each, and how to measure which words to add.
