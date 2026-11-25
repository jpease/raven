# AGENTS.md per-section cost

Offline estimate of what each `##` section of the `AGENTS.md` that
`raven install python` writes costs in context. The repo's own root
`AGENTS.md` is maintainer-only and is not measured here.

## Method

- Anchor: the measured `AGENTS.md` cost is 3,227 tokens, from
  `docs/evaluation/fixed-cost-attribution.md` (`/context all`, Claude Code
  2.1.319).
- No local tokenizer was installed, so tokens are allocated by character share:
  `est. tokens = 3,227 x section characters / total characters`. The input is the
  `AGENTS.md` from a fresh `raven install python` into a scratch directory
  (8,660 characters, 1,345 words). Each section runs from its `##` heading to the next. The text before the first heading is
  the preamble.
- This is an estimate. Prose, code spans and lists tokenize differently, so
  per-section error is plausibly several percent. The column sums to 3,227.
- No model call and no new `/context` run were made.
- The evidence column stays `pending #296` until the scenarios in #296
  measure whether each section changes behavior. Nothing was cut.

## Table

| Section | Words | Chars | Est. tokens | Share | Evidence |
|---|---:|---:|---:|---:|---|
| (preamble and markers) | 2 | 13 | 5 | 0.2% | pending #296 |
| Primary Objective | 19 | 147 | 55 | 1.7% | pending #296 |
| Canonical Context | 173 | 1250 | 466 | 14.4% | pending #296 |
| Retrieval Discipline | 292 | 1719 | 641 | 19.8% | pending #296 |
| Skills | 53 | 275 | 102 | 3.2% | pending #296 |
| Delegation | 68 | 562 | 209 | 6.5% | pending #296 |
| Shell Command Policy | 132 | 851 | 317 | 9.8% | pending #296 |
| Pause And Ask | 88 | 598 | 223 | 6.9% | pending #296 |
| Editing Rules | 59 | 377 | 140 | 4.4% | pending #296 |
| Verification State | 78 | 475 | 177 | 5.5% | pending #296 |
| Convergence | 116 | 700 | 261 | 8.1% | pending #296 |
| Safety Rules | 265 | 1693 | 631 | 19.5% | pending #296 |
| **Total** | 1345 | 8660 | 3227 | 100% | |
