# Flagged Words: Measurement Methodology

How to decide whether a word belongs in `words.md` -- read this when adding, removing, or reconsidering a table row. Not needed for a routine word pass.

## Adding a word

Add words because they rose in measurement, not because they sound inflated. A list built from intuition covers words nobody writes.

Measure with:

```bash
git log --format='%s%n%b' -n 400 > /tmp/commits.txt
rg -oiN --no-filename -w 'WORD1|WORD2|WORD3' /tmp/commits.txt \
  | tr 'A-Z' 'a-z' | sort | uniq -c | sort -rn
```

Re-run against commits made after the rules file landed and compare. A word that has not fallen needs a different fix than another table row.

Exclude the commits that argue *about* the word list, or the count charges the debate to the writer:

```bash
git log --format='%s%n%b' -n 400 --invert-grep -i \
  --grep='prose' --grep='vale' --grep='wording' > /tmp/commits.txt
```

A high, consistent count is not proof a word is necessary -- only that it appears. The test that settles a borderline word is deletion: strike it from every sampled sentence and check whether a fact was lost. If a nearby parenthetical, citation, or contrasting clause was already proving the same thing, the word was decoration. A list borrowed from an outside style guide is a hypothesis the same way -- measure it here before adding any of it.

When measuring a repo that installs Raven, exclude the installed paths. Raven's own guidance uses words like `canonical` heavily and correctly, so a repo-wide count charges Raven's vocabulary to the writer:

```bash
git grep -ohiwE 'WORD' -- 'docs/*' 'README.md' 'src/*'   # the writer's own prose
```

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
