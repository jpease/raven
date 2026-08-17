# Research: assessments of technical documentation, and what they change in the prose skill

**Research date:** August 17, 2026.

Raven's prose guidance was built from a corpus of its own writing. Every tell in
`raven-write-prose` was validated against text; the frame around them — that
prose scaffolding is the thing worth catching — never was. This note collects
the outside assessments that do measure documentation, and records which of them
landed in the skill.

## The assessments

| Source | Method | Finding |
|---|---|---|
| Uddin and Robillard, *How API Documentation Fails*, IEEE Software 32(4), 2015 | two surveys, 323 professional developers; 179 documentation units analysed; 10 problem types | the three severest are ambiguity, incompleteness, incorrectness |
| Aghajani et al., *Software Documentation Issues Unveiled*, ICSE 2019 | 878 artifacts mined from mailing lists, Stack Overflow, issues, pull requests | taxonomy under What / How / Process / Tools |
| Morkes and Nielsen, *Concise, SCANNABLE, and Objective*, 1997 | five writing styles, measured usability against a control | concise +58%, scannable +47%, objective +27%, all three +124% |
| Pullum, *Fear and Loathing of the English Passive* | corpus counts of passive transitive verbs | ~17% baseline; Orwell's own essay runs 26% |
| Prana et al., *Categorizing the Content of GitHub README Files*, EMSE 24, 2019 | 4,226 sections from 393 READMEs, hand-labelled | what and how are well covered; purpose and status are thin |
| Carroll, *The Nurnberg Funnel* | minimalist instruction: cut explanation, start on a real task | effect sizes not verified here — the review PDF would not parse and secondary sources do not quote them |
| GDS, *GOV.UK content principles* | style guide reviewed by the Centre for Information Design Research, University of Reading | higher-literacy readers prefer plain English because it is faster; the cited "80% prefer plain sentences" figure was not traced to a primary study |

Exemplar doc sets these are usually argued against: Stripe (every example runnable
in eight languages, populated with the reader's own test key), Django (split by
mode before the split had a name), Rust (doc examples compile and run as tests),
Diátaxis (the framework naming the four modes), GOV.UK.

## What landed

- **A correctness gate ahead of the fourteen tells.** `SKILL.md` now opens on the
  Uddin and Robillard result and a per-genre question to run first. The skill
  already did this for code comments; the research says it belongs in front of
  every genre.
- **A test for Orwell's rule 4.** The six rules stay quoted verbatim. Beneath
  them, Pullum's count, and the replacement test: does the sentence drop an
  actor the reader needs?
- **Tutorial, how-to, and reference rows in `genres.md`,** with mode-mixing named
  as their shared failure, and a note that bulletification cannot fire in any of
  them — the Morkes and Nielsen numbers point the opposite way in a procedure.
- **`why` and status in the README row** (Prana et al.).
- **C-EXAMPLE and C-FAILURE in the docstring section,** from Rust's API
  guidelines. Rust can require an example on every public item because rustdoc
  runs them; that is the same point `genres.md` already makes about examples
  nothing collects.
- **The 27% objective-style result** now backs the stakes-inflation tell, which
  had no citation.

## Not applied

- Kaplan-Moss's five-to-six-sentence paragraph cap, from the series on Django's
  docs. A mechanical check, and the skill has no paragraph-length tell yet.
- The GDS reading-age target. Wrong instrument for engineering prose, and the
  supporting figure is untraced.
- Carroll's minimalism as a cited source. The README rule already states it
  ("every detail you add pushes the first command further down"); citing it
  without verified effect sizes would add a reference and no fact.
