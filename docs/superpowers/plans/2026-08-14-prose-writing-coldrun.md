# Cold-Context Run: raven-write-prose

Date: 2026-08-14
Verdict: the skill works. 0 hard-ban words, 1 marginal structural tell.

## Why this run exists

Every other task in the prose plan was written by someone carrying the context
the skill exists to replace — four rounds of correction that live in a
conversation, not in the file. None of them show whether the shipped text works
for a reader who was not there. That is the skill's whole audience.

## Method

A `general-purpose` subagent, not a fork — a fork inherits the parent's context,
which is the thing being controlled for. The brief held the full text of
`raven-write-prose/SKILL.md` and nothing else about this project, plus an
instruction not to read any repository files.

The one edit to the skill text: the long-word tell's `rg` command was reworded
as "run a sweep for words of nine letters or more", since the agent was told not
to touch the filesystem.

Task: write a 300-word README section for a command-line tool that checks
documentation for broken links. Invent the specifics.

Grading was done here, not by the subagent. An agent asked to grade its own
output grades against its intent rather than the artifact.

## Results

| tell | fired | evidence |
|---|---|---|
| Signposting | no | no sentence announces what the next one does |
| Throat-clearing | no | sentence one names the tool and what it does |
| Tricolon default | **marginal** | list lengths 4, 3, 5, 3, 3 — three of five are three-item |
| `not X, but Y` | no | regex sweep returned nothing |
| Uniform rhythm | no | "Two known gaps." (3 words) sits beside 30-word sentences |
| Symmetric hedge | no | commits everywhere; no both-sides sentence |
| Drumroll or dependent heading | no | "## Checking links" names the content and stands alone |
| Restating close | no | last paragraph holds two facts stated nowhere else |
| Bulletification | no | the flag list is genuinely tabular, correct as bullets |
| No specifics | no | `5s`, `8`, `16`, `2.4s`, 291 ok, 12 skipped, exit codes 0/1/2, 403, 429 |
| Unearned confidence | no | a "Two known gaps" paragraph, including "there is no way to tell them apart" |
| Long-word default | no | 13 hits, all technical terms or common words; none had a shorter form |

Long-word hits, all kept on triage: aggressive, annotations, attributes,
concurrency, everything, generates, linkrotignore, protection, redirects,
repeatable, something, understands, unreadable.

One Orwell rule 4 violation, outside the twelve tells: "Relative paths and
anchors **are checked** against the working tree."

## What this says

The two rules most likely to be ignored both transferred. "Say what you did not
verify" produced a two-sentence known-gaps paragraph that admits an unsolvable
case. "Cite specifics" produced timeouts, counts, exit codes, and HTTP statuses
in a piece about a tool that does not exist.

The tricolon result is the honest weak spot. Three of five lists came out at
three items, which meets the test's "are most three?" threshold. The list
lengths did vary, so this reads as the tell being marginally sensitive rather
than the writing being formulaic. Worth watching across more runs before
changing the test.

## Not changed

No skill edit. Task 8 Step 4 sets the bar at zero hard-ban words and two or
fewer structural tells; this run clears it. Adding rules on the strength of one
marginal result is the failure mode the plan warns about — a longer skill, not a
better one.

## Not verified

One run, one task, one model. This does not measure the review skill, the
rebuild path, or whether the rules hold over a long document. The tricolon
threshold needs more runs before it means anything.
