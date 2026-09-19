---
name: raven-write-prose
description: Use when writing a whole document from scratch (README, spec, ADR, issue body) or when asked for a prose review. Not for editing a sentence, comment, or paragraph in place.
---

# Write Prose

Plain words are part of good prose. The larger part is structure — rhythm, list length, hedging, signposting — and a word swap reaches none of it.

These tests do not detect machine writing. They measure scaffolding a writer leaves in; use them as an edit pass on a draft, never as evidence about who wrote something. The commands that run them mechanically live in `raven-review-prose`; a review is when to run them, an edit is not.

## Correctness first

No tell below measures whether the document is true, and the severest failures of real documentation are ambiguity, incompleteness, and incorrectness (Uddin and Robillard, *How API Documentation Fails*, IEEE Software 2015; 179 documentation units, 323 developers). Ask your genre's question before any tell:

| genre | the question |
|---|---|
| code comment | does this still describe what the code does? |
| docstring | does the function raise, return, and guarantee what this says? |
| README, tutorial, how-to | did you run the commands, in order, from a clean checkout? |
| reference | is every name, type, default, and version the one in the code? |
| spec, essay | is every number and citation traceable to something you checked? |

A failure here outranks every finding below it. Trouble writing plainly is often a signal for an unchecked claim: verify, then write the plain version.

## Spine: Orwell's six rules

1. Never use a metaphor, simile or other figure of speech which you are used to seeing in print.
2. Never use a long word where a short one will do.
3. If it is possible to cut a word out, always cut it out.
4. Never use the passive where you can use the active.
5. Never use a foreign phrase, a scientific word or a jargon word if you can think of an everyday English equivalent.
6. Break any of these rules sooner than say anything outright barbarous.

Rule 4 needs a test of its own, because "passive" is the label most often hung on sentences that are not passive; Orwell's own essay runs 26% passive against a 17% baseline (Pullum, *Fear and Loathing of the English Passive*). Judge by what the sentence hides: **does it drop an actor the reader needs?** "The file is written atomically" hides nobody. "Mistakes were made" hides the whole point.

## The fourteen tells

Each row names the artifact, the test, and the fix. The delete tests apply to whole paragraphs too.

| tell | test | fix |
|---|---|---|
| Signposting | Delete the sentence. Does meaning survive? | Delete it. |
| Throat-clearing | Does sentence one carry new information? | Start where information starts. |
| Tricolon default | Count list lengths. Are most three? | Cut to two or extend to four where honest. |
| `not X, but Y` | Delete the negated half. Does the sentence still say something? | State Y alone. In a title, cut the tag. |
| Symmetric hedge | A sentence weighing both sides, concluding neither | Commit, or cut it. |
| Drumroll or dependent heading | Does the heading name its own content? `### Inputs` alone names nothing. | Name it in full. |
| Restating close | Does the last paragraph hold a new fact? | Cut it. |
| Bulletification | Do the bullets flow into each other like sentences, or has every paragraph become a `**Label**: value` bullet? | Give flowing bullets their paragraph back, or a bulleted argument its prose. |
| No specifics | Count numbers, names, paths, versions. Zero? Engineering docs are built from specifics and always pass. | Add them, or say you don't know. |
| Unearned confidence | Does the piece admit any dead end? | Say what you did not verify. |
| Long-word default | Any word of nine or more letters with a shorter everyday equivalent | Use the shorter word. |
| Closing flourish | Does the last sentence of each paragraph hold a fact the paragraph did not already have? | Delete it, or state the fact plainly. |
| Essence-framing | "what this really means", "at its core", "boils down to", "the real question is" | Delete the frame; state the claim directly. |
| Stakes-inflation | "changes everything", "cannot be overstated", "game-changer", "turning point" | Cut it, or replace with the number that earns the claim. |

`X, not Y` needs judgment. "Green tests prove behavior, not design health" survives the delete test; "It's not about speed. It's about correctness" does not. Most instances of the broad form rule out a real misreading, so judge by the test and not by the shape.

The tag on a heading, a commit subject, or an issue title gets through the delete test, so a title takes a second one: **does the negated half rule out something the reader would otherwise have expected?** `not cwd` does; "measured rather than assumed" rates the method, and the replacement is the number that earned the claim.

`Unearned confidence` and `No specifics` fire when something is missing, so a low count is not a clean document until you know which tells the zeroes came from.

## Tone

Do not be stuffy. Argue with evidence rather than assertion. Do not be too pleased with yourself. Do not lecture. Get straight in.

## Match the voice

Read the surrounding file before writing and match how it sounds. A terse codebase does not get essay comments. Rewrite any rule borrowed from an outside style guide in plain words first; copying is how inflated wording enters.

## When not to apply

Quotations, code, error strings, log output, proper nouns, settled terms with no plain equivalent, and any file whose existing voice is deliberate.

## Genre

Read `reference/genres.md` before running the tells. Which of them can fire depends on what you are writing, and a zero from a tell that cannot fire is not a clean result.

## Words

Read `reference/words.md` when doing a word pass; it holds the flagged-word table with a keep-test for each. Read `reference/words-history.md` when adding, removing, or reconsidering an entry.
