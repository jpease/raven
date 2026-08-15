import re
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
            "Closing flourish",
        ]:
            with self.subTest(tell=tell):
                self.assertIn(tell, text)

    def test_word_reference_exists_and_carries_the_measurement_procedure(self):
        self.assertTrue(WORDS_REF.exists(), f"missing {WORDS_REF}")
        text = WORDS_REF.read_text(encoding="utf-8")
        self.assertIn("rg", text, "the measurement procedure must be runnable, not described")
        self.assertIn("git log", text)


VALE_DIR = SKILLS / "raven-write-prose" / "reference" / "vale"


class ValeStyleTests(unittest.TestCase):
    def test_config_and_styles_exist(self):
        self.assertTrue((VALE_DIR / ".vale.ini").exists())
        self.assertTrue((VALE_DIR / "styles" / "Raven" / "PlainWords.yml").exists())
        self.assertTrue((VALE_DIR / "styles" / "Raven" / "KeepTest.yml").exists())
        self.assertTrue((VALE_DIR / "styles" / "Raven" / "Vacuous.yml").exists())

    def test_hard_ban_words_fail_the_gate(self):
        """The gate runs at warning, so a hard ban must be warning or above.

        `vacuous` has its own file rather than a PlainWords entry: the
        one-word swap PlainWords can express is wrong for the sense the word
        gets used in, since "passes vacuously" is not "passes emptily".
        """
        plain = (VALE_DIR / "styles" / "Raven" / "PlainWords.yml").read_text(encoding="utf-8")
        self.assertIn("extends: substitution", plain)
        self.assertIn("level: warning", plain)
        self.assertIn("adjudicate", plain)

        vac = (VALE_DIR / "styles" / "Raven" / "Vacuous.yml").read_text(encoding="utf-8")
        self.assertIn("level: warning", vac)
        self.assertIn("vacuous(ly)?", vac)

    def test_a_hard_ban_is_never_downgraded_to_a_suggestion(self):
        """Both words were briefly moved to keep-tests on the strength of a
        repo that turned out to have learned them from an agent. Assert the
        shape so a future move is a deliberate test change, not a quiet one.
        """
        keep = (VALE_DIR / "styles" / "Raven" / "KeepTest.yml").read_text(encoding="utf-8")
        tokens = keep.split("tokens:", 1)[-1]
        for word in ["adjudicat", "vacuous"]:
            with self.subTest(word=word):
                self.assertNotIn(word, tokens, f"{word} is a hard ban, not a suggestion")

    def test_keep_test_words_are_suggestions_not_errors(self):
        text = (VALE_DIR / "styles" / "Raven" / "KeepTest.yml").read_text(encoding="utf-8")
        self.assertIn("extends: existence", text)
        self.assertIn("level: suggestion", text)
        self.assertIn("canonical", text)

    def test_third_party_package_is_commented_out(self):
        """Vale sync fetches over the network. Opting in is an explicit
        consumer edit, never a shipped default.
        """
        lines = (VALE_DIR / ".vale.ini").read_text(encoding="utf-8").splitlines()
        active = [ln for ln in lines if ln.strip() and not ln.strip().startswith("#")]
        self.assertFalse(
            [ln for ln in active if ln.strip().startswith("Packages")],
            "Packages must stay commented out -- it fetches a third-party rule package over the network",
        )


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
        original keys off it and swaps words while keeping the shape.
        """
        text = REVIEW_SKILL.read_text(encoding="utf-8")
        self.assertIn("raven-prose-reviewer", text)
        self.assertIn("never", text.lower())
        self.assertIn("outline", text.lower())


CLAUDE_AGENTS = REPO_ROOT / "common" / ".claude" / "agents"
CODEX_AGENTS = REPO_ROOT / "common" / ".codex" / "agents"


class ProseReviewerAgentTests(unittest.TestCase):
    def test_both_adapters_ship_the_agent(self):
        self.assertTrue((CLAUDE_AGENTS / "raven-prose-reviewer.md").exists())
        self.assertTrue((CODEX_AGENTS / "raven-prose-reviewer.toml").exists())

    def test_agent_is_read_only(self):
        """It writes prose from an outline. It has no reason to run commands
        or touch the filesystem.
        """
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


FRONTMATTER_KEY_RE = re.compile(r"^([A-Za-z][\w-]*):\s*(.*)$")


def _frontmatter_lines(path):
    """Yield the lines between the opening and closing `---` of a file."""
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0].strip() != "---":
        return []
    out = []
    for line in lines[1:]:
        if line.strip() == "---":
            return out
        out.append(line)
    return []


class FrontmatterValidityTests(unittest.TestCase):
    """An unquoted YAML scalar holding ": " parses as a nested mapping, which
    is a YAML error. Claude Code tolerates it, so it goes unnoticed until a
    strict consumer chokes -- Vale aborts its whole run on one such file,
    silently skipping every file after it.

    Checked without PyYAML on purpose: the runtime is stdlib-only and this
    catches the one failure mode that has actually occurred.
    """

    def _files(self):
        paths = sorted(SKILLS.glob("*/SKILL.md"))
        paths += sorted((REPO_ROOT / "common" / ".claude" / "agents").glob("*.md"))
        self.assertTrue(paths, "expected shipped skills and agents to exist")
        return paths

    def test_no_frontmatter_value_holds_an_unquoted_colon_space(self):
        offenders = []
        for path in self._files():
            for line in _frontmatter_lines(path):
                match = FRONTMATTER_KEY_RE.match(line)
                if not match:
                    continue
                value = match.group(2)
                if value[:1] in {'"', "'"}:
                    continue
                if ": " in value:
                    offenders.append(f"{path.relative_to(REPO_ROOT)}: {line.strip()[:70]}")
        self.assertFalse(
            offenders,
            "unquoted frontmatter value contains ': ', which is invalid YAML. "
            "Quote the value or replace the colon with a dash:\n  " + "\n  ".join(offenders),
        )

    def test_every_file_has_frontmatter(self):
        missing = [
            str(p.relative_to(REPO_ROOT)) for p in self._files() if not _frontmatter_lines(p)
        ]
        self.assertFalse(missing, f"files with no parseable frontmatter: {missing}")


if __name__ == "__main__":
    unittest.main()
