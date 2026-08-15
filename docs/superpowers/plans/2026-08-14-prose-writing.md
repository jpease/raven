# Prose Writing Guidance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship four tiers of prose guidance — an always-loaded rules file, a writing skill, a review skill with a rebuild path, and a reference tier with an optional Vale style.

**Architecture:** Content lives in `common/` and each language tree symlinks to it. Tier 1 pays context on every session in nine language profiles, so it is capped at 75 words and holds a pointer to tier 2. Tiers 2 and 3 load only when invoked. Tier 4 loads only when read. Vale is optional everywhere and its absence never fails a gate.

**Tech Stack:** Python 3.9+ stdlib, `unittest` run through `pytest`, `ruff`, `just`, POSIX symlinks, optional Vale (Go binary).

**Spec:** `docs/superpowers/specs/2026-08-14-prose-writing-design.md`

## Global Constraints

- Runtime code targets Python 3.9+ and uses only the standard library. No `tomllib`.
- Shipped templates depend only on Raven, Claude, and Codex. Never on a user-local tool.
- Vale absent must print a notice and exit 0. Never fail a gate on a missing optional tool.
- `common/` is canonical. Language trees symlink to it; never copy a shared file into a tree.
- Commits follow Conventional Commits. Never add `Co-Authored-By`, `Generated-by`, or any AI-attribution footer — the `commit-msg` hook rejects them.
- No home-directory absolute paths in any committed file. `scripts/check-staged-hygiene.py` blocks them at commit time.
- Never name a private downstream repository. Refer to repos by role.
- Test command is `just test`. Lint is `just lint`. Full gate is `uv run --group dev python scripts/self-check.py`.
- The nine language trees are: `python`, `typescript`, `go`, `rust`, `swift`, `elixir`, `lua`, `ruby`, `dotfiles`.

---

### Task 1: Tier 1 rules file, symlinks, and budgets

**Files:**
- Create: `common/.claude/rules/raven-prose.md`
- Create: 9 symlinks at `<lang>/.claude/rules/raven-prose.md`
- Modify: `scripts/self-check.py` (`_TREE_SYMLINKS_TO_COMMON`, `THRESHOLDS`, `SHARED`, `PROFILES`)
- Test: `tests/test_rule_ownership.py`

**Interfaces:**
- Consumes: nothing.
- Produces: the path `common/.claude/rules/raven-prose.md`, referenced by Task 6's Vale self-application step.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_rule_ownership.py`, after `test_common_security_rules_file_has_no_collision`:

```python
    def test_common_prose_rules_file_has_no_collision(self):
        self._assert_no_collision(REPO_ROOT / "common" / ".claude" / "rules" / "raven-prose.md")
```

Create `tests/test_prose_rules.py`:

```python
import unittest

from helpers import REPO_ROOT

LANGUAGE_TREES = [
    "python",
    "typescript",
    "go",
    "rust",
    "swift",
    "elixir",
    "lua",
    "ruby",
    "dotfiles",
]

CANONICAL = REPO_ROOT / "common" / ".claude" / "rules" / "raven-prose.md"

# Matches THRESHOLDS in scripts/self-check.py. `validate_context_budget`
# counts with len(text.split()), which treats each "-" bullet marker as a
# token, so seven bullets cost seven words before any prose.
WORD_BUDGET = 75


class ProseRulesTests(unittest.TestCase):
    def test_canonical_file_exists(self):
        self.assertTrue(CANONICAL.exists(), f"missing {CANONICAL}")

    def test_canonical_file_is_within_word_budget(self):
        count = len(CANONICAL.read_text(encoding="utf-8").split())
        self.assertLessEqual(
            count,
            WORD_BUDGET,
            f"raven-prose.md is {count} words (budget {WORD_BUDGET}); "
            "tier 1 is frozen -- put new guidance in the write-prose skill instead",
        )

    def test_canonical_file_points_at_the_writing_skill(self):
        text = CANONICAL.read_text(encoding="utf-8")
        self.assertIn(
            "raven-write-prose",
            text,
            "tier 1 must point at tier 2; without the pointer the depth is unreachable",
        )

    def test_every_language_tree_symlinks_to_common(self):
        for tree in LANGUAGE_TREES:
            link = REPO_ROOT / tree / ".claude" / "rules" / "raven-prose.md"
            with self.subTest(tree=tree):
                self.assertTrue(
                    link.is_symlink(), f"{link} is not a symlink -- do not copy shared files"
                )
                self.assertEqual(
                    link.resolve(),
                    CANONICAL.resolve(),
                    f"{link} resolves outside common/",
                )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `just test -- tests/test_prose_rules.py tests/test_rule_ownership.py`
Expected: FAIL — `missing .../common/.claude/rules/raven-prose.md`

- [ ] **Step 3: Create the canonical rules file**

Create `common/.claude/rules/raven-prose.md` with exactly this content (65 words):

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

The `## `-level heading set must not collide with `common/AGENTS.md`. This file uses a single `# ` heading and no `## ` headings, so it cannot collide.

- [ ] **Step 4: Create the nine symlinks**

```bash
for tree in python typescript go rust swift elixir lua ruby dotfiles; do
  ln -s ../../../common/.claude/rules/raven-prose.md "$tree/.claude/rules/raven-prose.md"
done
```

Verify each resolves:

```bash
for tree in python typescript go rust swift elixir lua ruby dotfiles; do
  test -f "$tree/.claude/rules/raven-prose.md" || echo "BROKEN: $tree"
done
```

Expected: no output.

- [ ] **Step 5: Register the shared path in self-check**

In `scripts/self-check.py`, add to `_TREE_SYMLINKS_TO_COMMON` in sorted position, immediately before `".claude/rules/raven-security.md"`:

```text
    ".claude/rules/raven-prose.md",
```

- [ ] **Step 6: Add the context budget threshold**

In `validate_context_budget`, add to `THRESHOLDS` under the `# shared rules files` comment:

```python
        "common/.claude/rules/raven-prose.md": 75,
```

- [ ] **Step 7: Add the file to every language profile's aggregate**

In `validate_aggregate_budget`, add to `SHARED`:

```python
    SHARED = [
        "common/AGENTS.md",
        "common/.claude/rules/raven-prose.md",
        "common/.claude/rules/raven-security.md",
    ]
```

Then raise every entry in `PROFILES` by 75:

```python
    PROFILES: dict[str, tuple[int, str]] = {
        # language: (aggregate word budget, language rules file)
        "python": (1993, "python/.claude/rules/raven-python.md"),
        "elixir": (2123, "elixir/.claude/rules/raven-elixir.md"),
        "rust": (2053, "rust/.claude/rules/raven-rust.md"),
        "swift": (1893, "swift/.claude/rules/raven-swift.md"),
        "typescript": (1913, "typescript/.claude/rules/raven-typescript.md"),
        "go": (2073, "go/.claude/rules/raven-go.md"),
        "lua": (1913, "lua/.claude/rules/raven-lua.md"),
        "ruby": (2083, "ruby/.claude/rules/raven-ruby.md"),
        "dotfiles": (1747, "dotfiles/.claude/rules/raven-dotfiles.md"),
    }
```

- [ ] **Step 8: Run the tests to verify they pass**

Run: `just test -- tests/test_prose_rules.py tests/test_rule_ownership.py`
Expected: PASS

- [ ] **Step 9: Run the budget validators**

Run: `uv run --group dev python scripts/self-check.py`
Expected: `context budget ok` and `aggregate context budget ok` both print. If `aggregate context budget exceeded` prints, the arithmetic in Step 7 is wrong — read the reported total and set that profile's limit to it.

- [ ] **Step 10: Commit**

```bash
git add common/.claude/rules/raven-prose.md \
        python/.claude/rules/raven-prose.md \
        typescript/.claude/rules/raven-prose.md \
        go/.claude/rules/raven-prose.md \
        rust/.claude/rules/raven-prose.md \
        swift/.claude/rules/raven-prose.md \
        elixir/.claude/rules/raven-prose.md \
        lua/.claude/rules/raven-prose.md \
        ruby/.claude/rules/raven-prose.md \
        dotfiles/.claude/rules/raven-prose.md \
        scripts/self-check.py \
        tests/test_prose_rules.py \
        tests/test_rule_ownership.py
git commit -m "feat(prose): add always-loaded prose rules file

Raven ships no guidance for how agents write English. A sweep over 400
commits of body prose finds 35 uses of \"canonical\", 25 of \"surface\" as a
verb, and 14 of \"explicitly\", while the template library itself is clean.
The tics live in commit messages and chat, so the rule has to be
always-loaded rather than skill-gated.

Cap it at 75 words and point at raven-write-prose for depth. Tier 1 pays
context in all nine language profiles on every session; growing it both
costs context and pushes the rule further from the model's attention."
```

---

### Task 2: The writing skill and the word reference

**Files:**
- Create: `common/.agents/skills/raven-write-prose/SKILL.md`
- Create: `common/.agents/skills/raven-write-prose/reference/words.md`
- Modify: `scripts/self-check.py:345` (`SKILL_DESCRIPTION_AGGREGATE_LIMIT`)
- Test: `tests/test_prose_rules.py`

**Interfaces:**
- Consumes: `raven-prose.md` from Task 1, which names this skill.
- Produces: skill directory `raven-write-prose/` and `reference/words.md`, both referenced by Task 3's Vale style and Task 4's review skill.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_prose_rules.py`, before the `if __name__` block:

```python
SKILLS = REPO_ROOT / "common" / ".agents" / "skills"
WRITE_SKILL = SKILLS / "raven-write-prose" / "SKILL.md"
WORDS_REF = SKILLS / "raven-write-prose" / "reference" / "words.md"

# Matches SKILL_DESCRIPTION_PER_SKILL_LIMIT in scripts/self-check.py.
DESCRIPTION_WORD_CAP = 30


def _frontmatter_description(path):
    """Return the frontmatter description of a SKILL.md as a single string."""
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0].strip() != "---":
        raise AssertionError(f"{path} has no frontmatter")
    collected = []
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if line.startswith("description:"):
            collected.append(line[len("description:") :].strip())
        elif collected and line.startswith((" ", "\t")):
            collected.append(line.strip())
        elif collected:
            break
    if not collected:
        raise AssertionError(f"{path} has no description in frontmatter")
    return " ".join(collected)


class WriteProseSkillTests(unittest.TestCase):
    def test_skill_exists(self):
        self.assertTrue(WRITE_SKILL.exists(), f"missing {WRITE_SKILL}")

    def test_description_is_within_the_per_skill_cap(self):
        count = len(_frontmatter_description(WRITE_SKILL).split())
        self.assertLessEqual(count, DESCRIPTION_WORD_CAP, f"description is {count} words")

    def test_skill_documents_every_tell(self):
        text = WRITE_SKILL.read_text(encoding="utf-8")
        for tell in [
            "Signposting",
            "Throat-clearing",
            "Tricolon",
            "not X, but Y",
            "Uniform rhythm",
            "Symmetric hedge",
            "dependent heading",
            "Restating close",
            "Bulletification",
            "No specifics",
            "Unearned confidence",
            "Long-word default",
        ]:
            with self.subTest(tell=tell):
                self.assertIn(tell, text)

    def test_word_reference_exists_and_carries_the_measurement_procedure(self):
        self.assertTrue(WORDS_REF.exists(), f"missing {WORDS_REF}")
        text = WORDS_REF.read_text(encoding="utf-8")
        self.assertIn("rg", text, "the measurement procedure must be runnable, not described")
        self.assertIn("git log", text)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `just test -- tests/test_prose_rules.py::WriteProseSkillTests`
Expected: FAIL — `missing .../raven-write-prose/SKILL.md`

- [ ] **Step 3: Write the skill**

Create `common/.agents/skills/raven-write-prose/SKILL.md`:

````markdown
---
name: raven-write-prose
description: Use when drafting or editing prose — comments, READMEs, docs, specs, commit messages, issue bodies. Applies plain-language rules and removes machine-writing tells.
---

# Write Prose

Write prose a human would write. Plain words are part of that. The larger part is structure: what marks text as machine-written is rhythm, list length, hedging, and signposting, and a vocabulary swap reaches none of it.

## Spine: Orwell's six rules

1. Never use a metaphor, simile or other figure of speech which you are used to seeing in print.
2. Never use a long word where a short one will do.
3. If it is possible to cut a word out, always cut it out.
4. Never use the passive where you can use the active.
5. Never use a foreign phrase, a scientific word or a jargon word if you can think of an everyday English equivalent.
6. Break any of these rules sooner than say anything outright barbarous.

## The twelve tells

Each row names the artifact, gives a test you can run, and gives the fix. Run the tests; do not judge by feel.

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

The long-word sweep is Orwell's rules 2 and 5 made mechanical. Run it on anything you write. Most hits are technical terms with no shorter form and get kept; the sweep exists to make you ask the question of each one rather than only of words someone already listed.

## Tone

- Do not be stuffy.
- Argue with evidence rather than assertion.
- Do not be too pleased with yourself.
- Do not lecture.
- Get straight in.

## Match the voice

Read the surrounding file before writing and match its register. A terse codebase does not get essay comments. A file with a deliberate voice keeps it.

## Borrowed guidance gets translated

When you take a rule from an external style guide, rewrite it in plain words before using it. Copying a source word for word is the most common way inflated vocabulary enters. These five tone rules came from a magazine guide that words two of them as "do not be hectoring" and "do not be too didactic" — both fail Orwell's rules 2 and 5.

## When not to apply

- Quotations. Preserve the original wording.
- Code, error strings, and log output.
- Proper nouns and product names.
- Established terms with no plain equivalent.
- Any file whose existing voice is deliberate.

## Vocabulary

Read `reference/words.md` when doing a vocabulary pass. It holds the flagged-word table with a keep-test for each, and the procedure for measuring which words to add.
````

- [ ] **Step 4: Write the word reference**

Create `common/.agents/skills/raven-write-prose/reference/words.md`:

````markdown
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
````

- [ ] **Step 5: Raise the skill-description aggregate limit**

Run the current total first:

```bash
uv run --group dev python -c "
import importlib.util
spec = importlib.util.spec_from_file_location('sc', 'scripts/self-check.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
m.validate_skill_description_budget()"
```

Expected before this task: `skill description budget ok (388 words)`. Adding this skill's 22-word description brings it to 410, over the 392 limit.

In `scripts/self-check.py:345`, change:

```python
SKILL_DESCRIPTION_AGGREGATE_LIMIT = 435
```

435 covers this skill's 22 words and Task 4's review skill, with headroom.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `just test -- tests/test_prose_rules.py`
Expected: PASS

- [ ] **Step 7: Verify the skill passes its own long-word sweep**

Run: `rg -oN '\b[a-z]{9,}\b' common/.agents/skills/raven-write-prose/SKILL.md | sort -u`

Triage every hit. Words with no shorter everyday form (`vocabulary`, `mechanical`, `technical`, `structure`) stay. Any word with a shorter equivalent is a defect — fix it before committing. A skill that fails its own rules has no standing.

- [ ] **Step 8: Commit**

```bash
git add common/.agents/skills/raven-write-prose/ scripts/self-check.py tests/test_prose_rules.py
git commit -m "feat(prose): add the raven-write-prose skill

Tier 1 is capped at 75 words and can only carry a pointer. This is what
it points at: Orwell's six rules as the spine, twelve structural tells
with a runnable test each, and the flagged-word table behind a reference
file that costs nothing until read.

The twelfth tell is a long-word sweep. A word list only finds words
someone already thought to add; the sweep lists every candidate and asks
one question of each. It is why the table can stay at seven words."
```

---

### Task 3: The optional Vale style

**Files:**
- Create: `common/.agents/skills/raven-write-prose/reference/vale/.vale.ini`
- Create: `common/.agents/skills/raven-write-prose/reference/vale/styles/Raven/PlainWords.yml`
- Create: `common/.agents/skills/raven-write-prose/reference/vale/styles/Raven/KeepTest.yml`
- Test: `tests/test_prose_rules.py`

**Interfaces:**
- Consumes: the word table from Task 2's `reference/words.md`.
- Produces: `reference/vale/` and the style name `Raven`, consumed by Task 6's self-application step.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_prose_rules.py`:

```python
VALE_DIR = SKILLS / "raven-write-prose" / "reference" / "vale"


class ValeStyleTests(unittest.TestCase):
    def test_config_and_styles_exist(self):
        self.assertTrue((VALE_DIR / ".vale.ini").exists())
        self.assertTrue((VALE_DIR / "styles" / "Raven" / "PlainWords.yml").exists())
        self.assertTrue((VALE_DIR / "styles" / "Raven" / "KeepTest.yml").exists())

    def test_hard_ban_words_are_substitutions_not_keep_tests(self):
        text = (VALE_DIR / "styles" / "Raven" / "PlainWords.yml").read_text(encoding="utf-8")
        self.assertIn("extends: substitution", text)
        for word in ["adjudicate", "vacuous"]:
            with self.subTest(word=word):
                self.assertIn(word, text)

    def test_keep_test_words_are_suggestions_not_errors(self):
        text = (VALE_DIR / "styles" / "Raven" / "KeepTest.yml").read_text(encoding="utf-8")
        self.assertIn("extends: existence", text)
        self.assertIn("level: suggestion", text)
        self.assertIn("canonical", text)

    def test_third_party_package_is_commented_out(self):
        """vale sync fetches over the network. Opting in is an explicit
        consumer edit, never a shipped default."""
        lines = (VALE_DIR / ".vale.ini").read_text(encoding="utf-8").splitlines()
        active = [ln for ln in lines if ln.strip() and not ln.strip().startswith("#")]
        self.assertFalse(
            [ln for ln in active if ln.strip().startswith("Packages")],
            "Packages must stay commented out -- it fetches a third-party rule package over the network",
        )
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `just test -- tests/test_prose_rules.py::ValeStyleTests`
Expected: FAIL — the `.vale.ini` assertion fails first.

- [ ] **Step 3: Write the config**

Create `common/.agents/skills/raven-write-prose/reference/vale/.vale.ini`:

```ini
StylesPath = styles
MinAlertLevel = suggestion

[*.md]
BasedOnStyles = Raven

# Generic model-register rules live in a third-party package. Running
# `vale sync` fetches it over the network, which is a dependency Raven has
# nowhere else, so it ships commented out. Uncomment to opt in.
# Packages = https://github.com/tbhb/vale-ai-tells/releases/latest/download/AITells.zip
```

- [ ] **Step 4: Write the hard-ban rules**

Create `common/.agents/skills/raven-write-prose/reference/vale/styles/Raven/PlainWords.yml`:

```yaml
extends: substitution
message: "Use '%s' instead of '%s'."
level: warning
ignorecase: true
swap:
  adjudicate: decide
  vacuous: empty
  utilise: use
  utilize: use
```

- [ ] **Step 5: Write the keep-test rules**

Create `common/.agents/skills/raven-write-prose/reference/vale/styles/Raven/KeepTest.yml`:

```yaml
extends: existence
message: "'%s' has a keep-test in reference/words.md. Confirm it passes, or rewrite."
level: suggestion
ignorecase: true
tokens:
  - canonical\w*
  - durabl\w*
  - posture
  - materiall\w*
  - surfac(e|es|ed|ing)
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `just test -- tests/test_prose_rules.py::ValeStyleTests`
Expected: PASS

- [ ] **Step 7: Verify the style parses if Vale is installed**

```bash
if command -v vale >/dev/null 2>&1; then
  (cd common/.agents/skills/raven-write-prose/reference/vale && vale ls-config >/dev/null && echo "style parses")
else
  echo "vale not installed, skipping -- this is not a failure"
fi
```

Expected: either `style parses` or the skip notice. A YAML parse error here is a real defect; fix it before committing.

- [ ] **Step 8: Commit**

```bash
git add common/.agents/skills/raven-write-prose/reference/vale/ tests/test_prose_rules.py
git commit -m "feat(prose): add an optional Vale style for the flagged words

Hard bans are substitutions; words with a keep-test are suggestions
carrying the test in the message, so a correct use of \"canonical\" in
raven-authority-map reads as a prompt rather than a violation.

The style stays at seven words on purpose. Generic model-register rules
defer to a third-party package, and that package ships commented out
because vale sync fetches over a network path Raven has nowhere else."
```

---

### Task 4: The review skill

**Files:**
- Create: `common/.agents/skills/raven-review-prose/SKILL.md`
- Test: `tests/test_prose_rules.py`

**Interfaces:**
- Consumes: the twelve tells from Task 2's SKILL.md, the Vale style name `Raven` from Task 3.
- Produces: the rebuild-path contract that Task 5's subagent implements — the subagent receives an outline only and never the original draft.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_prose_rules.py`:

```python
REVIEW_SKILL = SKILLS / "raven-review-prose" / "SKILL.md"


class ReviewProseSkillTests(unittest.TestCase):
    def test_skill_exists(self):
        self.assertTrue(REVIEW_SKILL.exists(), f"missing {REVIEW_SKILL}")

    def test_description_is_within_the_per_skill_cap(self):
        count = len(_frontmatter_description(REVIEW_SKILL).split())
        self.assertLessEqual(count, DESCRIPTION_WORD_CAP, f"description is {count} words")

    def test_vale_absence_is_documented_as_non_fatal(self):
        text = REVIEW_SKILL.read_text(encoding="utf-8")
        self.assertIn("not installed", text)
        self.assertIn("continue", text.lower())

    def test_rebuild_path_withholds_the_original_draft(self):
        """The whole point of the rebuild path. A subagent that sees the
        original keys off it and swaps vocabulary while keeping the shape."""
        text = REVIEW_SKILL.read_text(encoding="utf-8")
        self.assertIn("raven-prose-reviewer", text)
        self.assertIn("never", text.lower())
        self.assertIn("outline", text.lower())
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `just test -- tests/test_prose_rules.py::ReviewProseSkillTests`
Expected: FAIL — `missing .../raven-review-prose/SKILL.md`

- [ ] **Step 3: Write the skill**

Create `common/.agents/skills/raven-review-prose/SKILL.md`:

````markdown
---
name: raven-review-prose
description: Use when reviewing prose for machine-writing tells and inflated vocabulary, or when a draft needs rebuilding rather than editing.
---

# Review Prose

Three passes, cheapest first. Stop at any pass that resolves the piece.

## Pass 1: Vale, if installed

```bash
if command -v vale >/dev/null 2>&1; then
  vale --config=<path-to>/reference/vale/.vale.ini --output=line FILE
else
  echo "vale not installed; skipping the word pass"
fi
```

When Vale is not installed, print that one line and continue to pass 2. A missing optional tool never fails a review.

Vale covers the word half only. It cannot see a tricolon, a restating conclusion, or a dependent heading.

## Pass 2: the structural pass

Walk all twelve tells from `raven-write-prose`. Run each test rather than judging by feel. The long-word sweep is the one most often skipped and the one that finds the most:

```bash
rg -oN '\b[a-z]{9,}\b' FILE | sort -u
```

## Pass 3: verdict

Report findings, or escalate to rebuild.

Report each finding in this shape:

```
Structural (README.md, para 3)
  Original:  "It's not about speed. It's about correctness."
  Suggested: "Correctness matters more than speed here."
  Reason:    not-X-but-Y construction
```

## When to rebuild instead of edit

Editing bad prose in place mostly swaps vocabulary and preserves shape, because the draft in front of you anchors what you produce.

Escalate to rebuild when either holds:

- Four or more structural tells fire inside one section.
- Reading the whole document, the shape is the problem rather than the wording.

Below that, edit in place.

## The rebuild path

1. Reduce the piece to claims and facts. An outline, with no sentence kept intact.
2. Dispatch `raven-prose-reviewer` with the outline only. The subagent never receives the original draft — that is the entire mechanism, and passing the draft defeats it.
3. The subagent writes fresh against the `raven-write-prose` rules.
4. Review its output through passes 1 and 2.

If the dispatch fails, fall back to editing in place and say plainly in your report that shape problems will likely survive.

## When not to apply

Skip quotations, code, error strings, log output, proper nouns, and any file whose existing voice is deliberate. Read the `when not to apply` section of `raven-write-prose` before flagging anything in these categories.
````

- [ ] **Step 4: Run the tests to verify they pass**

Run: `just test -- tests/test_prose_rules.py::ReviewProseSkillTests`
Expected: PASS

- [ ] **Step 5: Verify the skill passes its own sweep**

Run: `rg -oN '\b[a-z]{9,}\b' common/.agents/skills/raven-review-prose/SKILL.md | sort -u`

Triage every hit as in Task 2 Step 7.

- [ ] **Step 6: Commit**

```bash
git add common/.agents/skills/raven-review-prose/ tests/test_prose_rules.py
git commit -m "feat(prose): add the raven-review-prose skill

Three passes, cheapest first: Vale for words when installed, the twelve
tells by hand, then a verdict. Vale absent prints one line and continues.

Above four structural tells in a section the skill stops editing and
rebuilds instead. Editing bad prose in place mostly swaps vocabulary and
keeps the shape, because the draft anchors what gets written -- so the
rebuild path reduces the piece to an outline and hands only that to a
subagent that never sees the original."
```

---

### Task 5: The rebuild subagent, both adapters

**Files:**
- Create: `common/.claude/agents/raven-prose-reviewer.md`
- Create: `common/.codex/agents/raven-prose-reviewer.toml`
- Create: 9 symlinks at `<lang>/.claude/agents/raven-prose-reviewer.md`
- Modify: `scripts/self-check.py` (`_TREE_SYMLINKS_TO_COMMON`)
- Modify: `tests/test_skills.py:1117` (agent count assertion)

**Interfaces:**
- Consumes: the rebuild contract from Task 4 — outline in, fresh prose out.
- Produces: agent name `raven-prose-reviewer` (Claude) and `raven_prose_reviewer` (Codex).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_prose_rules.py`:

```python
CLAUDE_AGENTS = REPO_ROOT / "common" / ".claude" / "agents"
CODEX_AGENTS = REPO_ROOT / "common" / ".codex" / "agents"


class ProseReviewerAgentTests(unittest.TestCase):
    def test_both_adapters_ship_the_agent(self):
        self.assertTrue((CLAUDE_AGENTS / "raven-prose-reviewer.md").exists())
        self.assertTrue((CODEX_AGENTS / "raven-prose-reviewer.toml").exists())

    def test_agent_is_read_only(self):
        """It writes prose from an outline. It has no reason to run commands
        or touch the filesystem."""
        claude = (CLAUDE_AGENTS / "raven-prose-reviewer.md").read_text(encoding="utf-8")
        self.assertIn("tools: Read", claude)
        self.assertNotIn("Bash", claude)
        codex = (CODEX_AGENTS / "raven-prose-reviewer.toml").read_text(encoding="utf-8")
        self.assertIn('sandbox_mode = "read-only"', codex)

    def test_both_adapters_carry_the_out_of_scope_contract(self):
        for path in [
            CLAUDE_AGENTS / "raven-prose-reviewer.md",
            CODEX_AGENTS / "raven-prose-reviewer.toml",
        ]:
            with self.subTest(path=path.name):
                self.assertIn("Out Of Scope Findings", path.read_text(encoding="utf-8"))

    def test_every_language_tree_symlinks_the_agent(self):
        canonical = CLAUDE_AGENTS / "raven-prose-reviewer.md"
        for tree in LANGUAGE_TREES:
            link = REPO_ROOT / tree / ".claude" / "agents" / "raven-prose-reviewer.md"
            with self.subTest(tree=tree):
                self.assertTrue(link.is_symlink(), f"{link} is not a symlink")
                self.assertEqual(link.resolve(), canonical.resolve())
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `just test -- tests/test_prose_rules.py::ProseReviewerAgentTests`
Expected: FAIL — the Claude agent file does not exist.

- [ ] **Step 3: Write the Claude adapter**

Create `common/.claude/agents/raven-prose-reviewer.md`:

```markdown
---
name: raven-prose-reviewer
description: Writes prose fresh from an outline, without seeing the draft it replaces.
model: sonnet
tools: Read
---

You receive an outline of claims and facts. You do not receive the draft it came from, and you must not ask for it. Seeing the original would anchor your wording and shape, which is the failure this agent exists to avoid.

Write the piece fresh from the outline.

Follow the `raven-write-prose` rules:

- Orwell's six rules, especially: no long word where a short one will do, cut every cuttable word, active over passive.
- No signposting, no throat-clearing, no restating close.
- Vary sentence length. Do not default every list to three items.
- Avoid `not X, but Y`.
- Cite specifics. Numbers, names, paths.
- Say what you do not know rather than writing around it.

Before returning, run the long-word check on your own output: list every word of nine letters or more and ask whether a shorter everyday word exists. Replace the ones where it does.

Return the finished prose and nothing else. No preamble, no explanation of your choices.

Always end your return with an `## Out Of Scope Findings` section listing anything you noticed outside the assigned scope, each with file/line evidence. Write `none` under the heading when there is nothing. Do not omit the section — the caller treats its absence as an incomplete return.
```

- [ ] **Step 4: Write the Codex adapter**

Create `common/.codex/agents/raven-prose-reviewer.toml`:

```toml
name = "raven_prose_reviewer"
description = "Writes prose fresh from an outline, without seeing the draft it replaces."
model_reasoning_effort = "medium"
sandbox_mode = "read-only"
developer_instructions = """
You receive an outline of claims and facts. You do not receive the draft it came
from, and you must not ask for it. Seeing the original would anchor your wording
and shape, which is the failure this agent exists to avoid.

Write the piece fresh from the outline.

Follow the raven-write-prose rules:
- Orwell's six rules, especially: no long word where a short one will do, cut
  every cuttable word, active over passive.
- No signposting, no throat-clearing, no restating close.
- Vary sentence length. Do not default every list to three items.
- Avoid "not X, but Y".
- Cite specifics. Numbers, names, paths.
- Say what you do not know rather than writing around it.

Before returning, run the long-word check on your own output: list every word of
nine letters or more and ask whether a shorter everyday word exists. Replace the
ones where it does.

Return the finished prose and nothing else. No preamble, no explanation of your
choices.

Always end your return with an "## Out Of Scope Findings" section listing anything
you noticed outside the assigned scope, each with file/line evidence. Write none
under the heading when there is nothing. Do not omit the section -- the caller
treats its absence as an incomplete return.
"""
```

- [ ] **Step 5: Create the nine symlinks**

```bash
for tree in python typescript go rust swift elixir lua ruby dotfiles; do
  ln -s ../../../common/.claude/agents/raven-prose-reviewer.md \
        "$tree/.claude/agents/raven-prose-reviewer.md"
done
```

- [ ] **Step 6: Register the shared path**

In `scripts/self-check.py`, add to `_TREE_SYMLINKS_TO_COMMON` in sorted position, immediately before `".claude/agents/raven-refactor-reviewer.md"`:

```text
    ".claude/agents/raven-prose-reviewer.md",
```

- [ ] **Step 7: Update the hardcoded agent count**

`tests/test_skills.py:1117` asserts `len(paths) == 8` for 4 Claude plus 4 Codex agents. There are now 5 of each. Change:

```python
        self.assertEqual(
            len(paths),
            10,
            f"expected 5 Claude + 5 Codex agent contracts, found {len(paths)}",
        )
```

- [ ] **Step 8: Run the tests to verify they pass**

Run: `just test -- tests/test_prose_rules.py tests/test_skills.py`
Expected: PASS, including `test_both_adapter_trees_ship_the_same_agents` and `test_every_agent_requires_the_out_of_scope_section`.

- [ ] **Step 9: Commit**

```bash
git add common/.claude/agents/raven-prose-reviewer.md \
        common/.codex/agents/raven-prose-reviewer.toml \
        python/.claude/agents/raven-prose-reviewer.md \
        typescript/.claude/agents/raven-prose-reviewer.md \
        go/.claude/agents/raven-prose-reviewer.md \
        rust/.claude/agents/raven-prose-reviewer.md \
        swift/.claude/agents/raven-prose-reviewer.md \
        elixir/.claude/agents/raven-prose-reviewer.md \
        lua/.claude/agents/raven-prose-reviewer.md \
        ruby/.claude/agents/raven-prose-reviewer.md \
        dotfiles/.claude/agents/raven-prose-reviewer.md \
        scripts/self-check.py tests/test_skills.py tests/test_prose_rules.py
git commit -m "feat(prose): add the raven-prose-reviewer rebuild subagent

The review skill's rebuild path needs an agent that has not read the
draft it is replacing. This is it: outline in, finished prose out, Read
tools only because it has no reason to run a command.

Ships in both adapter trees since test_both_adapter_trees_ship_the_same_agents
requires parity, which also moves the hardcoded contract count from 8 to 10."
```

---

### Task 6: Vale self-application in the gate

**Files:**
- Modify: `scripts/self-check.py` (new `validate_prose_style` function and its call site)
- Test: `tests/test_self_check.py`

**Interfaces:**
- Consumes: the `Raven` Vale style from Task 3, all prose files from Tasks 1, 2, 4, and 5.
- Produces: nothing downstream.

- [ ] **Step 1: Write the failing test**

`tests/test_self_check.py` already imports `contextlib`, `io`, and `load_script_module` from `helpers`, and loads the script with `load_script_module("self_check_under_test", SELF_CHECK)` (see its line 38). Add `from unittest import mock` to the imports, then append:

```python
class ProseStyleValidationTests(unittest.TestCase):
    """A skill that violates its own rules has no standing. This gate is why
    the shipped prose stays honest -- and it must never fail on a missing
    optional tool."""

    def setUp(self):
        self.module = load_script_module("self_check_under_test", SELF_CHECK)

    def test_missing_vale_is_reported_and_non_fatal(self):
        with mock.patch.object(self.module.shutil, "which", return_value=None):
            with contextlib.redirect_stdout(io.StringIO()) as out:
                self.module.validate_prose_style()
        self.assertIn("vale not installed", out.getvalue())

    def test_targets_cover_every_shipped_prose_file(self):
        targets = self.module.prose_style_targets()
        names = {p.name for p in targets}
        self.assertIn("raven-prose.md", names)
        self.assertIn("raven-prose-reviewer.md", names)
        self.assertEqual(
            len([p for p in targets if p.name == "SKILL.md"]),
            2,
            "both prose skills must be checked against the style they ship",
        )
```

`SELF_CHECK` is the module-level constant `tests/test_self_check.py` already defines for the script path. Reuse it rather than rebuilding the path.

- [ ] **Step 2: Run the test to verify it fails**

Run: `just test -- tests/test_self_check.py::ProseStyleValidationTests`
Expected: FAIL — `module 'self-check' has no attribute 'validate_prose_style'`

- [ ] **Step 3: Implement the validator**

Add to `scripts/self-check.py`, after `validate_skill_description_budget`:

```python
def prose_style_targets() -> list[Path]:
    """Shipped prose files the Raven Vale style is applied to.

    Kept as a function rather than a constant so tests can assert coverage
    without duplicating the list.
    """
    skills = REPO_ROOT / "common" / ".agents" / "skills"
    return [
        REPO_ROOT / "common" / ".claude" / "rules" / "raven-prose.md",
        skills / "raven-write-prose" / "SKILL.md",
        skills / "raven-review-prose" / "SKILL.md",
        REPO_ROOT / "common" / ".claude" / "agents" / "raven-prose-reviewer.md",
    ]


def validate_prose_style() -> None:
    """Fail if shipped prose violates the prose style Raven itself ships.

    Vale is optional. A missing binary prints a notice and returns, because
    templates must stay installable without a Go toolchain.
    """
    print("==> validate shipped prose against the Raven Vale style")

    if shutil.which("vale") is None:
        print("  vale not installed, skipping prose style check")
        return

    config = (
        REPO_ROOT
        / "common"
        / ".agents"
        / "skills"
        / "raven-write-prose"
        / "reference"
        / "vale"
        / ".vale.ini"
    )
    if not config.exists():
        print(f"  WARNING: {config.relative_to(REPO_ROOT)} not found, skipping")
        return

    missing = [str(p.relative_to(REPO_ROOT)) for p in prose_style_targets() if not p.exists()]
    if missing:
        raise SystemExit(f"Prose style targets missing: {', '.join(sorted(missing))}.")

    result = subprocess.run(
        ["vale", f"--config={config}", "--output=line", "--minAlertLevel=error"]
        + [str(p) for p in prose_style_targets()],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        print(result.stdout)
        raise SystemExit(
            "Shipped prose violates the Raven Vale style. A prose skill that "
            "fails its own rules has no standing -- fix the prose, not the style."
        )
    print("prose style ok")
```

`scripts/self-check.py` already imports both `shutil` (line 16) and `subprocess` (line 17). No new imports are needed.

Note the `--minAlertLevel=error` flag: the keep-test rules are `suggestion` level and must not fail the gate, since a correct `canonical` in shipped prose is expected.

- [ ] **Step 4: Wire it into the run**

In `main()` at `scripts/self-check.py:706`, insert the call between `validate_skill_description_budget()` (line 714) and `warn_stale_docs()`:

```python
    validate_context_budget()
    validate_aggregate_budget()
    validate_skill_description_budget()
    validate_prose_style()
    warn_stale_docs()
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `just test -- tests/test_self_check.py::ProseStyleValidationTests`
Expected: PASS

- [ ] **Step 6: Run the full gate**

Run: `uv run --group dev python scripts/self-check.py`
Expected: passes end to end. With Vale absent it prints `vale not installed, skipping prose style check`; with Vale present it prints `prose style ok`.

- [ ] **Step 7: Commit**

```bash
git add scripts/self-check.py tests/test_self_check.py
git commit -m "feat(prose): check shipped prose against the style it ships

Published controlled-language skills get dismissed when their own READMEs
carry the tells they claim to remove. This gate stops that here: the
rules file, both skills, and the subagent are all checked against the
Raven Vale style.

Runs at error level only, so the keep-test rules stay advisory -- a
correct \"canonical\" in shipped prose is expected, not a violation. Vale
absent prints a notice and returns, keeping CI green without a Go
toolchain."
```

---

### Task 7: Documentation sync and full verification

**Files:**
- Modify: `README.md`
- Modify: `common/AGENTS.md` — **only if** Step 2 finds a concrete gap. Default is no change.

**Interfaces:**
- Consumes: everything from Tasks 1 through 6.
- Produces: nothing downstream.

- [ ] **Step 1: Update the README**

Find the section listing shipped skills and add both entries alongside the existing ones, matching the surrounding format exactly. Read the neighbouring lines first and match their voice — that is the `match the voice` rule from the skill this task is documenting.

- [ ] **Step 2: Decide on AGENTS.md**

Do not add a prose section to `common/AGENTS.md`. It is budgeted at 1110 words, the tier 1 rules file already names `raven-write-prose`, and a second mention costs context in nine profiles while buying nothing.

Change it only if the skill index alone leaves the skills undiscoverable in practice. If you do change it, raise the `common/AGENTS.md` threshold in `THRESHOLDS` and every affected `PROFILES` entry to match, and say so in the commit body.

- [ ] **Step 3: Verify the README's own prose**

Run: `rg -oN '\b[a-z]{9,}\b' README.md | sort -u`

Triage only the lines this task added. Do not restyle unrelated README prose — `raven-doc-sync` forbids rewriting unrelated docs for style.

- [ ] **Step 4: Run the full gate**

Run: `uv run --group dev python scripts/self-check.py`
Expected: install shape valid, `context budget ok`, `aggregate context budget ok`, `skill description budget ok`, prose style ok or skipped, `upgrade --dry-run` clean, upgrade applied, full test suite passing.

- [ ] **Step 5: Verify the self-upgrade produced no surprise diff**

Run: `git status --short`

Expected: only `.raven/manifest.json` may differ. A manifest diff limited to `ravenVersion` or a timestamp is self-chasing noise — discard it. A content-hash change is real and means a template file changed unexpectedly; investigate before committing.

- [ ] **Step 6: Run lint and format checks**

Run: `just lint && just fmt-check`
Expected: both pass.

- [ ] **Step 7: Commit**

```bash
git add README.md
git commit -m "docs: document the prose writing skills

Add raven-write-prose and raven-review-prose to the shipped-skill list.

AGENTS.md is deliberately unchanged: the tier 1 rules file already names
the writing skill, and a second mention would cost context in all nine
language profiles for no gain."
```

---

### Task 8: Cold-context validation of the shipped skill

The skill's audience is someone who was not present when it was written. Every
earlier task was authored by someone carrying that context, so none of them
test whether the shipped text works on its own. This task does.

**Files:**
- Create: `docs/superpowers/plans/2026-08-14-prose-writing-coldrun.md` (findings record)
- Modify: `common/.agents/skills/raven-write-prose/SKILL.md` — only if the run finds a defect

**Interfaces:**
- Consumes: the finished `raven-write-prose/SKILL.md` from Task 2.
- Produces: a findings record, and skill fixes if warranted.

- [ ] **Step 1: Dispatch a cold subagent**

Use the Agent tool with `subagent_type: "general-purpose"`. Do NOT use
`subagent_type: "fork"` — a fork inherits this conversation's context, which is
the exact thing being controlled for.

The brief must contain the full text of `raven-write-prose/SKILL.md` and nothing
else about this project's history. Prompt:

```
Read these writing rules, then follow them.

<paste the full contents of common/.agents/skills/raven-write-prose/SKILL.md>

Task: write a 300-word README section introducing a command-line tool that
checks a repository's documentation for broken links. Invent plausible
specifics -- flag names, exit codes, output format. Return only the section.

End your return with an "## Out Of Scope Findings" section listing anything you
noticed outside the assigned scope, each with evidence. Write none under the
heading when there is nothing.
```

- [ ] **Step 2: Grade the output against all twelve tells**

Run the mechanical tests yourself on the returned text. Do not ask the subagent
to grade itself — it will grade against its own intent rather than the artifact.

```bash
# save the returned section to a scratch file first
rg -oN '\b[a-z]{9,}\b' SCRATCH.md | sort -u          # long-word sweep
rg -ni "not [a-z ]{1,30} but |isn't [a-z ]{1,20} it's" SCRATCH.md
rg -c '^' SCRATCH.md                                  # then read for rhythm
```

Check the remaining tells by reading: signposting, throat-clearing, tricolon
counts, symmetric hedges, heading independence, restating close,
bulletification, specifics present, admitted uncertainty.

- [ ] **Step 3: Record the result**

Write `docs/superpowers/plans/2026-08-14-prose-writing-coldrun.md` with the date,
the exact prompt used, the returned text, and a table of which tells fired.

Record the real numbers. A run where nine tells fire is more useful than a run
reported as broadly fine.

- [ ] **Step 4: Decide what the result means**

- **Zero hard-ban words and two or fewer structural tells:** the skill works.
  Record it and stop.
- **Three or more structural tells:** the skill is documentation rather than a
  working guardrail. Identify which tells failed to transfer, and fix the skill
  by making those tests more concrete — not by adding more rules. A longer skill
  is the failure mode here, not the fix.
- **Any hard-ban word:** the word table is not reaching the writer. Check whether
  the SKILL.md pointer to `reference/words.md` is explicit enough about when to
  read it.

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/plans/2026-08-14-prose-writing-coldrun.md
# add the SKILL.md too if Step 4 changed it
git commit -m "test(prose): record a cold-context run of the write-prose skill

Every other task was written by someone carrying the context the skill is
meant to replace, so none of them test the shipped text on its own. This
run gives a subagent the SKILL.md and nothing else, then grades the
output against all twelve tells.

Recording the real counts rather than a verdict, so a later revision can
tell whether it improved."
```

---

## Verification Checklist

Run after all seven tasks land:

- [ ] `uv run --group dev python scripts/self-check.py` passes end to end
- [ ] `just test` passes
- [ ] `just lint && just fmt-check` pass
- [ ] All nine trees resolve both new symlinks: `for t in python typescript go rust swift elixir lua ruby dotfiles; do test -f "$t/.claude/rules/raven-prose.md" && test -f "$t/.claude/agents/raven-prose-reviewer.md" || echo "BROKEN: $t"; done`
- [ ] `common/.claude/rules/raven-prose.md` is 75 words or fewer
- [ ] Both new SKILL.md files pass their own long-word sweep
- [ ] No home-directory absolute path in any committed file
- [ ] No AI-attribution footer in any commit

## Known Open Questions

Carried from the spec. Do not resolve them during implementation; they need measurement that does not exist yet.

1. The four-tell rebuild threshold in Task 4 is an estimate.
2. The uniform-rhythm distance (~5 words) in Task 2 was chosen, not measured. It may fire constantly on legitimately terse prose.
3. "Do not lecture" inside a skill whose purpose is instruction is a tension the wording change does not resolve.
4. Whether a subagent dispatch earns its cost on a single paragraph is unknown until it runs.
