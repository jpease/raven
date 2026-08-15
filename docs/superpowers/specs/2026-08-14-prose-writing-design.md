# Design: Prose Writing Guidance

Date: 2026-08-14
Status: Approved design, pending implementation plan

## Summary

Raven ships guidance for how agents retrieve, edit, and verify code. It ships
nothing for how they write English. This design adds four tiers of prose
guidance: a small always-loaded rules file, a writing skill, a review skill with
a rebuild path, and a reference tier holding the growable word table and an
optional Vale style.

The target is prose a human would write. That is a stricter goal than plain
language, because what marks text as machine-written is mostly structural —
rhythm, list length, hedging, signposting — and a vocabulary list does not
reach any of it.

## Motivation

### The shipped templates are clean

Scanning every tracked `.md` file for inflated vocabulary returns three hits:
one `robust`, one `nuanced`, one `comprehensive`. The problem is not in the
template library.

### The commit history carries the tics

Across 400 commits, roughly 6,700 lines of body prose:

| word | count |
|---|---|
| `canonical` / `canonicality` / `canonically` | 35 |
| `surface` / `surfaced` / `surfacing` (verb) | 25 |
| `explicitly` | 14 |
| `semantics` | 9 |
| `durable` | 9 |
| `posture` | 4 |
| `materially` | 4 |
| `vacuous` | 1 |

`adjudicate` appears zero times in commits. It came up in chat. Any design that
only governs committed files misses half of what gets written, which is why
tier 1 has to be always-loaded rather than skill-gated.

### The tics overlap with real domain terms

`raven-authority-map.md` is about canonical context. `raven-namespace.md` is
about canonical file ownership. A flat denylist would flag correct prose and
train everyone to bypass the checker. Each flagged word carries a keep-test
instead of a ban.

### Vocabulary is the easy half

Reports from people using controlled-language prompts agree: word
rules shorten sentences and remove the worst headings, and leave the underlying
shape intact. The structural tells survive a vocabulary pass untouched.

### Instructions drift

Rules placed in agent instruction files work at first and decay as context
grows. Tier 1 must therefore stay small enough to keep
its position, and anything long must live behind an explicit invocation rather
than in always-loaded context.

## Non-Goals

- **ASD-STE100.** Built for non-native readers of maintenance manuals. It bans
  semicolons, mandates a closed vocabulary, and its own specification contains
  examples where the closed vocabulary creates ambiguity rather than removing
  it. Wrong register for engineering prose.
- **A full external house style.** The Economist guide runs about 2,400 words
  plus a dozen reference files, much of it British spelling, titles like Ms,
  currency formats, and number conventions that have no bearing on a code
  comment. Three parts of it are worth taking; the rest is not.
- **Blocking commits on prose.** Prose quality is a judgment call. A gate that
  flags `canonical` in `raven-authority-map.md` teaches people to bypass gates.
- **Governing marketing or brand copy.** Out of scope.
- **Requiring Vale.** Shipped templates depend on Raven, Claude, and Codex.
  Vale is optional and its absence is never an error.

## Design

### Four tiers

| tier | file | loaded | job |
|---|---|---|---|
| 1 | `common/.claude/rules/raven-prose.md` | always | govern ordinary output |
| 2 | `raven-write-prose/SKILL.md` | on invoke | deliberate writing |
| 3 | `raven-review-prose/SKILL.md` | on invoke | review and rebuild |
| 4 | `raven-write-prose/reference/` | on read | word table, Vale style |

Each tier holds only what its loading cost justifies. Tier 1 pays context on
every session in nine language profiles, so it holds the highest-value rules and
a pointer. Tier 4 costs nothing until read, so it holds everything that grows.

### Tier 1: the rules file

`common/.claude/rules/raven-prose.md`, symlinked into all nine language trees
the way `raven-security.md` already is. Budget 75 words.

The draft below measures 65 words. `validate_context_budget` counts with
`len(text.split())`, which treats each `-` bullet marker as a token, so the
seven bullets cost seven words on their own. The threshold leaves ten words of
headroom for wording changes and no more.

```markdown
# Prose Rules

- Plain words: decide not adjudicate, empty not vacuous, show not surface.
- No signposting or throat-clearing. Start with the content.
- Vary sentence length. Not every list is three items.
- Avoid "not X, but Y" as a default construction.
- Cite specifics: numbers, names, cases.
- Match the voice already in the file.
- Drafting or editing prose? Use raven-write-prose.
```

This file is frozen. New words go to tier 4. Growing tier 1 costs context in
every language profile and pushes the rule further from the model's attention,
which defeats its purpose.

### Tier 2: raven-write-prose

Target 550 words. Frontmatter description capped at 30 words by
`validate_skill_description_budget`.

**Spine.** Orwell's six rules from "Politics and the English Language", quoted
as written. They are short, they generalize to tics nobody has listed yet, and
rule 6 carries its own escape hatch.

**Substance.** Twelve tells. Each names the artifact, gives a test
that can be run, and gives the fix. Naming the specific artifact matters:
instructions phrased as tone requests ("be concise", "be blunt") produce new
artifacts rather than removing old ones.

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

The long-word sweep is Orwell's rules 2 and 5 made mechanical, and it does the
work no word list can. A list only finds words someone already thought to add.
The sweep lists every candidate and asks one question of each: is there a
shorter everyday word for this? Most hits are technical terms with no shorter
form and get kept. This is why the Vale style stays small — it covers the seven
measured repo words, and the sweep covers the rest.

Applying the sweep to this document during review found five failures that the
Vale style would have missed: `hectoring`, `didactic`, `honorifics`,
`provenance`, and `practitioners`. Three came from quoting a source guide word
for word, which is where borrowed vocabulary tends to enter.

**Tone.** Five rules adapted from the Economist guide: do not be stuffy,
argue with evidence rather than assertion, do not be too pleased with yourself,
do not lecture, get straight in.

The source guide words the middle two as "do not be hectoring" and "do not be
too didactic". Both are long words with everyday equivalents, which Orwell's
rules 2 and 5 forbid, so importing them verbatim would put the skill in
violation of its own spine. Borrowed guidance gets translated into plain words
before it ships, never kept just because the source worded it that way.

**Voice matching.** Read the surrounding file before writing and match its
register. A terse codebase does not get essay comments. This generalizes the
Economist guide's dialect-detection step, which exists so an editor does not
impose American spelling on British copy.

**When not to apply.** Quotations, code, error strings, log output, proper
nouns, established terms with no plain equivalent, and any file whose existing
voice is deliberate.

**Pointer** to `reference/words.md`, read only during a vocabulary pass.

### Tier 3: raven-review-prose

Three passes, cheapest first.

1. **Vale, if installed.** `vale --output=line` over the target files. Catches
   the word half. When Vale is absent, print one line saying so and continue.
2. **Structural pass.** Walk the twelve tells. No linter sees a tricolon or a
   restating conclusion.
3. **Verdict.** Report findings, or escalate to rebuild.

**Finding format**, adapted from the Economist guide:

```
Structural (README.md, para 3)
  Original:  "It's not about speed. It's about correctness."
  Suggested: "Correctness matters more than speed here."
  Reason:    not-X-but-Y construction
```

### The rebuild path

Editing bad prose in place tends to swap vocabulary and preserve shape, because
the draft in front of the model anchors what it produces. Above a threshold the
review skill stops editing:

1. Reduce the piece to claims and facts. An outline, with no sentence kept
   intact.
2. Dispatch `raven-prose-reviewer` with the outline only. The subagent never
   receives the original draft.
3. The subagent writes fresh against the tier 2 rules.
4. Review the result through the normal three passes.

**Threshold.** Four or more structural tells inside one section, or a whole
document read where the shape rather than the wording is the problem.

The number four is an estimate, not a measurement. It is the first thing to
revisit once the write-time rules have run for a few weeks. Recording it here so
the revisit is deliberate rather than accidental.

**Subagent definition.** `common/.claude/agents/raven-prose-reviewer.md` plus
its Codex tree twin, since `test_both_adapter_trees_ship_the_same_agents`
requires parity. `model: sonnet`. `tools: Read` only — it writes from an outline
and has no reason to run commands or touch the filesystem.

### Tier 4: reference

```
reference/words.md                    the growable table + measurement procedure
reference/vale/.vale.ini              config template
reference/vale/styles/Raven/*.yml     substitution rules
```

The Raven Vale style covers the measured repo words only: `canonical`,
`surface` as a verb, `durable`, `posture`, `materially`, `adjudicate`,
`vacuous`. Each is a `substitution` rule whose message carries the keep-test.
Generic model-register rules defer to the third-party `vale-ai-tells` package
rather than being reimplemented.

`vale sync` fetches that package over the network. Raven has no other
network-fetched rule dependency, so the `.vale.ini` template references it in a
commented block with a note describing what syncing pulls in. Opting in is an
explicit edit by the consumer.

### Context budget changes

`scripts/self-check.py`:

- `THRESHOLDS`: add `common/.claude/rules/raven-prose.md: 75`
- `SHARED`: add the same path so it counts toward every language profile
- `PROFILES`: raise all nine by 75. Python currently sits at 1915 against 1918,
  so it becomes 1993. The other eight shift by the same amount.
- `SKILL_DESCRIPTION_AGGREGATE_LIMIT`: 392 to 435. Current usage is 388, leaving
  four words of headroom for two new skill descriptions.
- Install-shape list: add `.claude/agents/raven-prose-reviewer.md`

`common/AGENTS.md` is not modified. It is budgeted at 1110 words, the tier 1
rules file already points at the skill, and a second mention would cost context
in nine profiles while buying nothing.

### Self-application

A skill that violates its own rules has no standing. Published controlled-
language skills have been dismissed on exactly this basis, their READMEs
carrying the tells they claim to remove.

`self-check.py` gains a step running the Raven Vale style over
`raven-prose.md`, both `SKILL.md` files, and the subagent definition. Skipped
with a notice when Vale is absent so CI without Vale stays green.

## Error Handling

| condition | behavior |
|---|---|
| Vale not installed | Print a skip notice. Exit 0. Never fail a gate. |
| Vale installed, style missing | Report the missing path. Exit 0. |
| `vale sync` fails (offline) | Report it. Fall back to the Raven style alone. |
| Subagent dispatch fails | Report it. Fall back to in-place editing with a warning that shape problems will likely survive. |
| Target file is code, not prose | Skip per the "when not to apply" list. |

## Testing

- No-collision test for `raven-prose.md` in `test_rule_ownership.py`, mirroring
  the existing security-rules test.
- Symlink integrity across all nine language trees, guarded with `skipUnless`
  rather than vendored, per the existing shared-symlink CI constraint.
- Vale-absent path exits 0 and prints the skip notice.
- Self-application: shipped prose files pass the shipped style.
- Skill and rule budgets: covered by the existing unbudgeted-file check, which
  fails loudly on any always-loaded file with no threshold entry.
- Adapter tree parity for the subagent: covered by
  `test_both_adapter_trees_ship_the_same_agents`.

## Measurement

The baseline exists. The counts in the Motivation section came from a `rg`
sweep over `git log` body prose across 400 commits. That procedure goes in
`reference/words.md` so it can be re-run against commits made after this lands.

Expansion of the word table is driven by that measurement rather than by
guessing. Words are added because they rose, not because they sound inflated.

## Migration and Compatibility

Additive. No existing file changes behavior. Downstream repos receive the new
rule and skills on `raven upgrade`; the orphan-removal path is not involved
because nothing is removed.

The context cost is 65 words per session in every language profile, plus two
skill descriptions in the always-loaded skill index.

## Open Questions

1. **The four-tell rebuild threshold** is an estimate. Revisit after the first
   measurement pass.
2. **The uniform-rhythm test** ("three consecutive sentences within ~5 words")
   uses a number chosen rather than measured. It may fire constantly on
   legitimately terse prose.
3. **"Do not lecture"** comes from a guide for magazine argument. Telling an
   instruction skill not to lecture is a tension the wording change does not
   resolve, and the fit is untested.
4. **The rebuild path costs a subagent dispatch** for what is often a single
   paragraph. Whether that trade is worth it is unknown until it runs.
