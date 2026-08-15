---
name: raven-write-prose
description: Use when drafting or editing prose — comments, READMEs, docs, specs, commit messages, issue bodies. Plain-language rules plus a structural edit pass.
---

# Write Prose

Plain words are part of good prose. The larger part is structure — rhythm, list length, hedging, signposting — and a word swap reaches none of it.

**These tests do not detect machine writing.** Graded against six of this author's blog posts and nine agent-written technical documents, they fired 6.6 times per human essay and 3.9 times per agent document. What they measure is scaffolding a writer leaves in: an essay signposts, runs sentences to a similar length, and closes paragraphs rhetorically, whichever kind of writer made it. Use them as an edit pass on a draft, never as evidence about who wrote something.

## Spine: Orwell's six rules

1. Never use a metaphor, simile or other figure of speech which you are used to seeing in print.
2. Never use a long word where a short one will do.
3. If it is possible to cut a word out, always cut it out.
4. Never use the passive where you can use the active.
5. Never use a foreign phrase, a scientific word or a jargon word if you can think of an everyday English equivalent.
6. Break any of these rules sooner than say anything outright barbarous.

## The twelve tells

Each row names the artifact, gives a test you can run, and gives the fix. Run the tests; do not judge by feel. Apply the delete tests to whole paragraphs as well as sentences — an explanation that restates the rule above it goes the same way a flourish does.

| tell | test | fix |
|---|---|---|
| Signposting | Delete the sentence. Does meaning survive? | Delete it. |
| Throat-clearing | Does sentence one carry new information? | Start where information starts. |
| Tricolon default | Count list lengths. Are most three? | Cut to two or extend to four where honest. |
| `not X, but Y` | Search `not…but`, `isn't…it's`, `not about…about`, and the split form `It is not A. It is B.` | State Y alone. |
| Symmetric hedge | A sentence weighing both sides, concluding neither | Commit, or cut it. |
| Drumroll or dependent heading | Does the heading name its own content? Ordinary nesting is fine; flag one that names nothing alone, like `### Inputs` or `### Decision`. | Name it in full. |
| Restating close | Does the last paragraph hold a new fact? | Cut it. |
| Bulletification | Are the bullets full sentences that flow into each other? And the reverse: has every paragraph become a `**Label**: value` bullet? | Give flowing bullets their paragraph back, or a bulleted argument its prose. |
| No specifics | Count numbers, names, paths, versions. Zero? Applies to conceptual and summary prose; engineering docs are built from specifics and always pass. | Add them, or say you don't know. Do not cite evidence for a claim nobody would dispute. |
| Unearned confidence | Does the piece admit any dead end? | Say what you did not verify. |
| Long-word default | `rg -oN '\b[a-z]{9,}\b' FILE \| sort -u`, then triage each | Use the shorter everyday word. |
| Closing flourish | Take the last sentence of each paragraph. Does it hold a fact the paragraph did not already have? | Delete it. If it held a fact, state the fact plainly. |

The long-word sweep is Orwell's rules 2 and 5 made mechanical. Run it on anything you write. Most hits are technical terms with no shorter form and get kept; the sweep exists to make you ask the question of each one rather than only of words someone already listed.

`X, not Y` needs judgment, and here is the test: **delete the negated half. Does the sentence still say something?**

"Green tests prove behavior, not design health" → "Green tests prove behavior." Still a claim. Keep it.

"It's not about speed. It's about correctness." → the first sentence alone says nothing. That is the tell.

Use the delete test rather than a regex. The broad form appears 3,244 times across 1.6 million words and the narrow copula form 516, nearly all of them ruling out a real misreading. Three independent reviewers reading an earlier wording of this rule flagged sentences that passed the delete test, so judge by the test and not by the shape.

Two tells read backwards from the rest. `Unearned confidence` and `No specifics` fire when something is *missing*, so a clean document scores no on both. Do not read a low total as a clean document without checking which tells the zeroes came from.

Expect the count to track document type. Across nine technical documents, procedures and reference pages fired 1 to 3 tells each; the one conceptual spec fired 10, and essays fired more still. Prose that argues is where these tests earn their place, and where they are noisiest.

A "uniform rhythm" test was removed after measurement. It asked for three consecutive sentences of similar length, and it had no working range: technical documents contain almost no paragraph reaching three sentences, while every essay tested fired on runs like 4/9/9 words, which are not uniform. Two thresholds were tried and both were guesses.

The closing-flourish test is positional, not lexical. A metaphor-word count across 148,000 words of drafting found 24 hits, so the vocabulary is too rare and too varied for a linter to catch. The position is consistent: last sentence of a paragraph, after the facts, restating them.

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

Read `reference/genres.md` before running the tells. Which of them can fire depends on what you are writing, and a zero from a tell that cannot fire is not a clean result. It also carries the one rule per genre worth knowing: a comment says why, a docstring states a contract, a README orients, a spec records a decision.

For a code comment, run one test before any of the twelve: does this still describe what the code does? Reviewing 486 comments produced 19 edits and 10 were contradicted by the code beside them, against one finding each from the prose tests.

## Words

Read `reference/words.md` when doing a word pass. It holds the flagged-word table with a keep-test for each, and how to measure which words to add.
