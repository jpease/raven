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
    "generic",
]

CANONICAL = REPO_ROOT / "common" / ".claude" / "rules" / "raven-comments.md"

# Matches THRESHOLDS in scripts/self-check.py. `validate_context_budget`
# counts with len(text.split()), which treats each "-" bullet marker as a
# token, so each bullet costs a word before any prose.
WORD_BUDGET = 75


class CommentRulesTests(unittest.TestCase):
    def test_canonical_file_exists(self):
        self.assertTrue(CANONICAL.exists(), f"missing {CANONICAL}")

    def test_canonical_file_is_within_word_budget(self):
        count = len(CANONICAL.read_text(encoding="utf-8").split())
        self.assertLessEqual(
            count,
            WORD_BUDGET,
            f"raven-comments.md is {count} words (budget {WORD_BUDGET}); this file "
            "is loaded for every language, so a word here costs nine profiles",
        )

    def test_canonical_file_names_the_restatement_failure(self):
        """The highest-frequency failure, and the one an agent will not self-
        diagnose: a comment that says in English what the next line says in
        code reads as diligence while adding nothing.
        """
        text = CANONICAL.read_text(encoding="utf-8").lower()
        self.assertIn("restating", text)

    def test_canonical_file_names_the_staleness_failure(self):
        """Correctness outranks style: a comment that no longer describes its
        code misinforms every later reader, which no amount of good phrasing
        repairs.
        """
        text = CANONICAL.read_text(encoding="utf-8").lower()
        self.assertIn("no longer matches", text)

    def test_every_language_tree_symlinks_to_common(self):
        for tree in LANGUAGE_TREES:
            link = REPO_ROOT / tree / ".claude" / "rules" / "raven-comments.md"
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
