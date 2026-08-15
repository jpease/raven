# Flagged Words

Each word carries a keep-test. A word that passes its test stays. A flat ban would flag correct prose and train people to bypass the check.

| word | keep only when | otherwise write |
|---|---|---|
| adjudicate | never | decide, settle |
| re-litigate | never | reopen, argue again |
| vacuous, vacuously | never | a test: passes without testing anything. a claim: says nothing |
| surface (verb) | never | show, report, raise |
| canonical | naming the authoritative source among competing copies | the real one, use X |
| durable | contrasting with something that does not persist | saved, lasting |
| posture | describing physical stance | approach, stance |
| materially | quantifying a difference you can state | enough to matter, or give the number |

## Words to weigh, but not to lint

`explicitly` and `deliberately` are the two most common long adverbs in this body of prose — 594 and 460 uses across 1.6 million words of markdown in five repositories. Both usually earn their place. `explicitly` contrasts with *implicitly* or *by inference*; `deliberately` marks a choice so a later reader does not undo it as an oversight.

Same test for both: does it rule out an alternative the reader might otherwise assume? If not, cut it.

Neither is a Vale rule. At those counts a linter would raise about a thousand prompts, nearly all of them passing, which teaches people to skip the tool. A word whose true-positive rate is low belongs in a writer's checklist, not a gate.

## Adding a word

Add words because they rose in measurement, not because they sound inflated. A list built from intuition covers words nobody writes.

Measure with:

```bash
git log --format='%s%n%b' -n 400 > /tmp/commits.txt
rg -oiN --no-filename -w 'WORD1|WORD2|WORD3' /tmp/commits.txt \
  | tr 'A-Z' 'a-z' | sort | uniq -c | sort -rn
```

Baseline taken 2026-08-14 across 400 commits, roughly 6,700 lines of body prose:

| word | count |
|---|---|
| canonical, canonicality, canonically | 35 |
| surface, surfaced, surfacing (verb) | 25 |
| explicitly | 14 |
| semantics | 9 |
| durable | 9 |
| posture | 4 |
| materially | 4 |
| vacuous | 1 |

Re-run against commits made after the rules file landed and compare. A word that has not fallen needs a different fix than another table row.

When measuring a repo that installs Raven, exclude the installed paths. Raven's own guidance uses `canonical` heavily and correctly, so a repo-wide count charges Raven's vocabulary to the writer:

```bash
git grep -ohiwE 'WORD' -- 'docs/*' 'README.md' 'src/*'   # the writer's own prose
```

## The sweep finds what the table cannot

The table only holds words someone thought to add. For everything else run the long-word sweep from the skill:

```bash
rg -oN '\b[a-z]{9,}\b' FILE | sort -u
```

Triage each hit with one question: is there a shorter everyday word for this?

## Check where a term of art came from

A tic can pass itself off as domain vocabulary. Before accepting a flagged word as settled, check its provenance:

```bash
git log --reverse -S 'WORD' --pickaxe-regex --format='%h %ad %s' --date=short | head -5
```

A word that first appears recently, spreads across documents in weeks, and has no use before the repo was worked on by agents is a coinage, not a domain term.

Then check the citation. A coinage tends to arrive with one: `WORD` named as a pattern, cited to a section that turns out never to define it.

```bash
git grep -c 'the-coined-phrase' -- 'AGENTS.md'
```

Both checks come from a real case: `adjudicate` was nearly downgraded from `never` because a repo cited an "adjudication-ledger pattern" to a section titled "One-Command Check" that never uses the phrase.
