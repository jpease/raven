"""Language rules are path-scoped for Claude Code; the rest stay always loaded.

Claude Code loads a rule whose frontmatter fails to parse unconditionally and
without an error, so the globs are pinned here rather than only checked for
shape.
"""

import re
import unittest

from helpers import REPO_ROOT

PINNED_PATHS = {
    "python": [
        "**/*.py",
        "**/*.pyi",
        "**/pyproject.toml",
        "**/setup.cfg",
        "**/requirements*.txt",
        "**/tox.ini",
        "**/pytest.ini",
    ],
    "typescript": [
        "**/*.{ts,tsx,mts,cts}",
        "**/*.{js,jsx,mjs,cjs}",
        "**/package.json",
        "**/tsconfig*.json",
        "**/eslint.config.*",
        "**/prettier.config.*",
    ],
    "go": ["**/*.go", "**/go.mod", "**/go.work", "**/.golangci.yml"],
    "rust": ["**/*.rs", "**/Cargo.toml", "**/rustfmt.toml", "**/clippy.toml"],
    "swift": ["**/*.swift", "**/project.yml", "**/.swiftlint.yml", "**/.swift-format"],
    "elixir": ["**/*.{ex,exs}", "**/*.{heex,eex,leex}"],
    "lua": ["**/*.lua", "**/*.rockspec", "**/.luacheckrc", "**/stylua.toml", "**/.stylua.toml"],
    "ruby": ["**/*.{rb,rake,gemspec,ru}", "**/Gemfile", "**/Rakefile", "**/.rubocop.yml"],
}

ALWAYS_LOADED = (
    REPO_ROOT / "common" / ".claude" / "rules" / "raven-comments.md",
    REPO_ROOT / "common" / ".claude" / "rules" / "raven-prose.md",
    REPO_ROOT / "dotfiles" / ".claude" / "rules" / "raven-dotfiles.md",
)

FRONTMATTER_RE = re.compile(r"\A---\n(.*?)^---\n", re.DOTALL | re.MULTILINE)
GLOB_LINE_RE = re.compile(r'^  - "([^"\n]+)"$')
IMPORT_RE = re.compile(r"(?<![\w`])@[\w./~-]*[\w/]")
FENCE_RE = re.compile(r"^```.*?^```", re.DOTALL | re.MULTILINE)
SPAN_RE = re.compile(r"`[^`\n]*`")


def rules_path(lang):
    return REPO_ROOT / lang / ".claude" / "rules" / f"raven-{lang}.md"


def frontmatter_lines(path):
    match = FRONTMATTER_RE.match(path.read_text(encoding="utf-8"))
    assert match is not None, f"{path.name} has no frontmatter"
    return match.group(1).splitlines()


def safety_rules():
    text = (REPO_ROOT / "common" / "AGENTS.md").read_text(encoding="utf-8")
    return text.split("## Safety Rules", 1)[1].split("\n## ", 1)[0]


class RuleScopingTests(unittest.TestCase):
    def test_language_rules_carry_pinned_paths(self):
        for lang, globs in PINNED_PATHS.items():
            with self.subTest(lang=lang):
                lines = frontmatter_lines(rules_path(lang))
                parsed = [m.group(1) for line in lines[1:] if (m := GLOB_LINE_RE.match(line))]
                self.assertEqual(parsed, globs)

    def test_frontmatter_uses_documented_subset(self):
        for lang in PINNED_PATHS:
            with self.subTest(lang=lang):
                lines = frontmatter_lines(rules_path(lang))
                self.assertEqual(lines[0], "paths:")
                self.assertTrue(lines[1:], "paths list is empty")
                for line in lines[1:]:
                    self.assertRegex(line, GLOB_LINE_RE)

    def test_always_loaded_rules_have_no_frontmatter(self):
        for path in ALWAYS_LOADED:
            with self.subTest(rule=path.name):
                self.assertIsNone(FRONTMATTER_RE.match(path.read_text(encoding="utf-8")))

    def test_rules_files_have_no_imports(self):
        for path in [*map(rules_path, PINNED_PATHS), *ALWAYS_LOADED]:
            with self.subTest(rule=path.name):
                prose = SPAN_RE.sub("", FENCE_RE.sub("", path.read_text(encoding="utf-8")))
                self.assertIsNone(IMPORT_RE.search(prose))

    def test_agents_md_points_at_language_rules(self):
        text = (REPO_ROOT / "common" / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("`.claude/rules/raven-<lang>.md`", text)

    def test_safety_rules_carry_untrusted_input_rule(self):
        section = safety_rules()
        for phrase in (
            "untrusted prompt-injection input",
            "executable",
            "parameterized",
            "Gitleaks",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, section)
        self.assertEqual(sorted(REPO_ROOT.glob("*/.claude/rules/raven-security.md")), [])


if __name__ == "__main__":
    unittest.main()
