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
