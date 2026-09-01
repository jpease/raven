# Flagged-Word List: Measurement Record

Date: 2026-08-14 through 2026-08-27
Verdict: `load-bearing` added, `genuinely` reversed from keep-test to `never`, `honest`/`honestly` added.

## Why this record exists

`words.md` and `words-history.md` (the shipped measurement methodology) live in `common/` and ship to every repo that installs Raven. This file doesn't -- its numbers describe this repo's own commits, not a downstream repo's, and shipping them would charge Raven's dogfooding history to someone else's word count. Keeping it here instead is what the methodology itself asks for: measured, not borrowed.

## Baseline and re-measurement

Baseline taken 2026-08-14 across 400 commits, roughly 6,700 lines of body prose. Re-measured 2026-08-24 the same way, after excluding the 46 commits that argue *about* the word list -- a `feat(prose):` or `fix(prose):` commit debating a word otherwise inflates its own target's count (`vacuous` read 13 before the exclusion, 1 after):

| word | 2026-08-14 | 2026-08-24 |
|---|---|---|
| canonical, canonicality, canonically | 35 | 31 |
| surface, surfaced, surfacing (verb) | 25 | 28 |
| explicitly | 14 | 9 |
| semantics | 9 | 8 |
| durable | 9 | 7 |
| posture | 4 | 3 |
| materially | 4 | 3 |
| vacuous | 1 | 1 |
| adjudicate | not measured | 0 |
| re-litigate | not measured | 0 |

The three hard bans (`adjudicate`, `re-litigate`, `vacuous`) have stopped appearing in ordinary work. `surface` is the one keep-test word that did not fall. The two windows overlap without covering the same 400 commits, so read a move of one or two as noise.

## The borrowed list (2026-08-24)

A list borrowed from elsewhere is a hypothesis, not an addition. Twenty-five banned words and phrases from a widely shared list were measured here; seventeen scored zero, among them `delve`, `tapestry`, `realm`, `seamless`, `holistic`, `paradigm`, `streamline`, `landscape`, `robust`, and `worth noting`. Of the eight that appeared, `harness` is domain vocabulary here and `structurally` passes its keep-test in nearly every instance; `genuinely` looked like it did on this same pass but did not hold up under closer scrutiny three days later. One entry, `load-bearing`, earned a row.

## `genuinely` reversed, `honest`/`honestly` added (2026-08-27)

`genuinely` moved from the keep-test list to `never`. Count alone argued the other way: 22 in this repo's last 400 commits, and 13 to 54 across four other actively developed repos checked the same way -- an iOS app, a watchOS app, a TypeScript monorepo, and a Rust CLI. High, consistent counts across unrelated codebases looked like domain need. They weren't: striking the word from every sampled sentence never lost a fact. "a genuinely local-only case (a private-repo symlink target)" loses nothing when `genuinely` is struck, because the parenthetical was already proving the case local-only; "a genuine top-level template (per `list_language_templates()`)" loses nothing either, because the citation was already proving it.

`honest`/`honestly` failed the same test, with a wrinkle. As a modifier ("an honest 404 rather than HTML with a 200") it deletes clean, same as `genuinely`. As the sentence's verb ("deployment.md is honest that shared_buffers=256MB is...", "a scalar cannot be honest here") deletion breaks the sentence, but swapping in a plainer word -- documents, discloses, accurate -- carries the same meaning with nothing lost, the same substitution `PlainWords.yml` already makes for `adjudicate` and `utilize`.

Both now have a Vale rule (`Genuine.yml`, `Honest.yml`), gated on this same spot-check evidence rather than the fuller false-positive measurement `vacuous` got (120 uses, 22 of them `vacuously`) across a full sample. Re-run that measurement for `genuine`/`honest` if either starts throwing more false positives than `vacuous` did.

## Provenance-check case study

The citation check in `words-history.md`'s "Check where a term of art came from" section comes from a real case: `adjudicate` was nearly downgraded from `never` because a repo cited an "adjudication-ledger pattern" to a section titled "One-Command Check" that never uses the phrase.
