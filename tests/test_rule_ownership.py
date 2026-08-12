import re
import unittest

from helpers import REPO_ROOT

HEADING_RE = re.compile(r"^## (.+)$", re.MULTILINE)


def heading_set(path):
    """Return the lowercase set of ``## ``-level heading text in ``path``."""
    text = path.read_text(encoding="utf-8")
    return {match.group(1).strip().lower() for match in HEADING_RE.finditer(text)}


class RuleOwnershipTests(unittest.TestCase):
    """No shipped `.claude/rules/*.md` file may reuse a `## ` heading that
    `common/AGENTS.md` already owns. AGENTS.md is the cross-cutting root
    instruction file; rules files are scoped extensions, and a duplicate
    heading makes it ambiguous which file governs that guardrail for a
    given install.
    """

    def setUp(self):
        self.agents_md = REPO_ROOT / "common" / "AGENTS.md"
        self.agents_headings = heading_set(self.agents_md)
        # Sanity check: fail loudly (not silently pass-by-omission) if the
        # fixture path or heading extraction ever breaks.
        self.assertTrue(self.agents_headings, f"expected {self.agents_md} to have ## headings")

    def _assert_no_collision(self, rules_path):
        rules_headings = heading_set(rules_path)
        collisions = rules_headings & self.agents_headings
        rel = rules_path.relative_to(REPO_ROOT)
        self.assertFalse(
            collisions,
            f"{rel} shares heading(s) {sorted(collisions)!r} with "
            f"common/AGENTS.md -- rename the rules-file heading so ownership "
            f"of that guardrail is unambiguous",
        )

    def test_common_security_rules_file_has_no_collision(self):
        self._assert_no_collision(REPO_ROOT / "common" / ".claude" / "rules" / "raven-security.md")

    def test_python_rules_file_has_no_collision(self):
        self._assert_no_collision(REPO_ROOT / "python" / ".claude" / "rules" / "raven-python.md")

    def test_elixir_rules_file_has_no_collision(self):
        self._assert_no_collision(REPO_ROOT / "elixir" / ".claude" / "rules" / "raven-elixir.md")

    def test_go_rules_file_has_no_collision(self):
        self._assert_no_collision(REPO_ROOT / "go" / ".claude" / "rules" / "raven-go.md")

    def test_lua_rules_file_has_no_collision(self):
        self._assert_no_collision(REPO_ROOT / "lua" / ".claude" / "rules" / "raven-lua.md")

    def test_ruby_rules_file_has_no_collision(self):
        self._assert_no_collision(REPO_ROOT / "ruby" / ".claude" / "rules" / "raven-ruby.md")

    def test_rust_rules_file_has_no_collision(self):
        self._assert_no_collision(REPO_ROOT / "rust" / ".claude" / "rules" / "raven-rust.md")

    def test_swift_rules_file_has_no_collision(self):
        self._assert_no_collision(REPO_ROOT / "swift" / ".claude" / "rules" / "raven-swift.md")

    def test_typescript_rules_file_has_no_collision(self):
        self._assert_no_collision(
            REPO_ROOT / "typescript" / ".claude" / "rules" / "raven-typescript.md"
        )

    def test_dotfiles_rules_file_has_no_collision(self):
        self._assert_no_collision(
            REPO_ROOT / "dotfiles" / ".claude" / "rules" / "raven-dotfiles.md"
        )


if __name__ == "__main__":
    unittest.main()
