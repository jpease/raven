# Flagged Words

Each word carries a keep-test. A word that passes its test stays. A flat ban would flag correct prose and train people to bypass the check.

| word | keep only when | otherwise write |
|---|---|---|
| adjudicate | never | decide, settle |
| vacuous | never | empty, says nothing |
| surface (verb) | never | show, report, raise |
| canonical | naming the authoritative source among competing copies | the real one, use X |
| durable | contrasting with something that does not persist | saved, lasting |
| posture | describing physical stance | approach, stance |
| materially | quantifying a difference you can state | enough to matter, or give the number |

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

This is not hypothetical. `adjudicate` and `vacuous` were nearly downgraded from `never` to keep-tests because a repository appeared to use both as settled terms — one documenting an "adjudication-ledger pattern" cited to `AGENTS.md §2.1`. That section is titled "One-Command Check" and never uses the phrase. Both words entered that repo in 2026 through agent-written commits. They were the tic, wearing the costume of a domain term, and the fake citation is what made the costume convincing.

Weigh a word's history, not how established it looks.
