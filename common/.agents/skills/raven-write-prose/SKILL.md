---
name: raven-write-prose
description: Use when drafting or editing prose — comments, READMEs, docs, specs, commit messages, issue bodies. Applies plain-language rules and removes machine-writing tells.
---

# Write Prose

Write prose a human would write. Plain words are part of that. The larger part is structure: what marks text as machine-written is rhythm, list length, hedging, and signposting, and a word swap reaches none of it.

## Spine: Orwell's six rules

1. Never use a metaphor, simile or other figure of speech which you are used to seeing in print.
2. Never use a long word where a short one will do.
3. If it is possible to cut a word out, always cut it out.
4. Never use the passive where you can use the active.
5. Never use a foreign phrase, a scientific word or a jargon word if you can think of an everyday English equivalent.
6. Break any of these rules sooner than say anything outright barbarous.

## The thirteen tells

Each row names the artifact, gives a test you can run, and gives the fix. Run the tests; do not judge by feel. Apply the delete tests to whole paragraphs as well as sentences — an explanation that restates the rule above it goes the same way a flourish does.

| tell | test | fix |
|---|---|---|
| Signposting | Delete the sentence. Does meaning survive? | Delete it. |
| Throat-clearing | Does sentence one carry new information? | Start where information starts. |
| Tricolon default | Count list lengths. Are most three? | Cut to two or extend to four where honest. |
| `not X, but Y` | Search `not…but`, `isn't…it's`, `not about…about` | State Y alone. |
| Uniform rhythm | Three consecutive sentences within ~5 words | Merge two, or cut one to a fragment. |
| Symmetric hedge | A sentence weighing both sides, concluding neither | Commit, or cut it. |
| Drumroll or dependent heading | Does it name the content, and does it still parse with the heading above it removed? | Name it in full. |
| Restating close | Does the last paragraph hold a new fact? | Cut it. |
| Bulletification | Are the bullets full sentences that flow? | Make them a paragraph. |
| No specifics | Count numbers, names, paths, versions. Zero? | Add them, or say you don't know. |
| Unearned confidence | Does the piece admit any dead end? | Say what you did not verify. |
| Long-word default | `rg -oN '\b[a-z]{9,}\b' FILE \| sort -u`, then triage each | Use the shorter everyday word. |
| Closing flourish | Take the last sentence of each paragraph. Does it hold a fact the paragraph did not already have? | Delete it. If it held a fact, state the fact plainly. |

The long-word sweep is Orwell's rules 2 and 5 made mechanical. Run it on anything you write. Most hits are technical terms with no shorter form and get kept; the sweep exists to make you ask the question of each one rather than only of words someone already listed.

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

## Words

Read `reference/words.md` when doing a word pass. It holds the flagged-word table with a keep-test for each, and how to measure which words to add.
