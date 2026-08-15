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
        """Vale sync fetches over the network. Opting in is an explicit
        consumer edit, never a shipped default.
        """
        lines = (VALE_DIR / ".vale.ini").read_text(encoding="utf-8").splitlines()
        active = [ln for ln in lines if ln.strip() and not ln.strip().startswith("#")]
        self.assertFalse(
            [ln for ln in active if ln.strip().startswith("Packages")],
            "Packages must stay commented out -- it fetches a third-party rule package over the network",
        )


if __name__ == "__main__":
    unittest.main()
