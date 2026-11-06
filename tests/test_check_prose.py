"""Behavioral tests for `scripts/check-prose.py`.

The checker reads `git ls-files`, so each test plants files in a real
temporary git repository and stages them.
"""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from helpers import REPO_ROOT, load_script_module

CHECKER_PATH = REPO_ROOT / "scripts" / "check-prose.py"


def _words(n: int, prefix: str = "w") -> str:
    """Filler prose; vary `prefix` so repeated paragraphs do not trip the repeat check."""
    return " ".join(f"{prefix}{i}" for i in range(n))


class ProseRepoTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name)
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        self.module = load_script_module("check_prose_under_test", CHECKER_PATH)

    def stage(self, path: str, content: str) -> None:
        target = self.repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        subprocess.run(["git", "-C", str(self.repo), "add", "--", path], check=True)

    def findings(self) -> list[tuple[str, int, str]]:
        return self.module.find_findings(self.repo)

    def messages(self) -> list[str]:
        return [f"{path}:{line}: {message}" for path, line, message in self.findings()]


class ParagraphBudgetTests(ProseRepoTestCase):
    def test_paragraph_over_limit_reports_its_first_line(self) -> None:
        self.stage("docs/guide.md", f"# Guide\n\nshort intro\n\n{_words(60)}\n{_words(61)}\n")
        self.assertEqual(
            [(path, line) for path, line, _ in self.findings()],
            [("docs/guide.md", 5)],
        )
        self.assertIn("121 words", self.messages()[0])

    def test_paragraph_at_limit_passes(self) -> None:
        self.stage("docs/guide.md", f"{_words(120)}\n")
        self.assertEqual(self.findings(), [])

    def test_each_list_item_is_budgeted_separately(self) -> None:
        self.stage("docs/guide.md", f"- {_words(100)}\n- {_words(100)}\n")
        self.assertEqual(self.findings(), [])

    def test_fenced_code_does_not_count(self) -> None:
        self.stage("docs/guide.md", f"```text\n{_words(500)}\n```\n")
        self.assertEqual(self.findings(), [])

    def test_marker_on_any_paragraph_line_suppresses_it(self) -> None:
        self.stage("docs/guide.md", f"{_words(70)}\n{_words(70)} <!-- raven-hygiene: allow -->\n")
        self.assertEqual(self.findings(), [])

    def test_marker_quoted_in_inline_code_does_not_suppress(self) -> None:
        self.stage(
            "docs/guide.md", f"{_words(70)}\nthe `raven-hygiene: allow` marker {_words(70)}\n"
        )
        self.assertEqual(len(self.findings()), 1)


class DocumentAndSectionBudgetTests(ProseRepoTestCase):
    def test_document_over_limit_is_reported_once(self) -> None:
        body = "\n\n".join(_words(100, f"p{k}w") for k in range(26))
        self.stage("common/.claude/docs/raven-x.md", body + "\n")
        self.assertEqual(len(self.findings()), 1)
        self.assertIn("2600 words (limit 2500)", self.messages()[0])

    def test_agents_section_counts_its_subsections(self) -> None:
        self.stage(
            "AGENTS.md",
            f"## Rules\n\n{_words(100)}\n\n### Detail\n\n{_words(100, 'd')}\n\n"
            f"### More\n\n{_words(101, 'm')}\n\n## Next\n\n{_words(10, 'n')}\n",
        )
        self.assertEqual(
            self.findings(),
            [("AGENTS.md", 1, self.module.MSG_SECTION.format(title="Rules", n=301))],
        )

    def test_root_agents_managed_block_is_not_budgeted(self) -> None:
        self.stage(
            "AGENTS.md",
            f"## Local\n\n{_words(10)}\n\n<!-- RAVEN:BEGIN sha256=x -->\n## Managed\n\n"
            f"{_words(200)}\n\n{_words(200)}\n<!-- RAVEN:END -->\n",
        )
        self.assertEqual(self.findings(), [])

    def test_section_budget_applies_only_to_agents_files(self) -> None:
        self.stage("docs/guide.md", f"## Big\n\n{_words(100)}\n\n{_words(100)}\n\n{_words(101)}\n")
        self.assertEqual(self.findings(), [])

    def test_shipped_skill_over_cap_is_reported(self) -> None:
        body = "\n\n".join(_words(100, f"p{k}w") for k in range(13))
        self.stage("common/.agents/skills/raven-x/SKILL.md", body + "\n")
        self.stage("project-skills/x/SKILL.md", body + "\n")
        self.assertEqual(
            self.findings(),
            [("common/.agents/skills/raven-x/SKILL.md", 1, self.module.MSG_SKILL.format(n=1300))],
        )


class ContrastTests(ProseRepoTestCase):
    def test_second_contrast_in_a_section_is_reported(self) -> None:
        self.stage(
            "docs/guide.md",
            "## A\n\nIt is a prompt, not a control.\n\nIt is discovery, not proof.\n",
        )
        self.assertEqual(
            self.findings(),
            [("docs/guide.md", 5, self.module.MSG_CONTRAST.format(first=3))],
        )

    def test_a_new_heading_resets_the_count(self) -> None:
        self.stage(
            "docs/guide.md",
            "## A\n\nA prompt, not a control.\n\n### B\n\nDiscovery, not proof.\n",
        )
        self.assertEqual(self.findings(), [])

    def test_contrast_inside_inline_code_is_ignored(self) -> None:
        self.stage("docs/guide.md", "Use X, not Y.\n\nRun `echo a, not b` now.\n")
        self.assertEqual(self.findings(), [])


class IssueReferenceTests(ProseRepoTestCase):
    def test_bare_reference_in_shipped_guidance_is_reported(self) -> None:
        self.stage("common/.claude/docs/raven-x.md", "Fixed in #231.\n\nSee issue 12.\n")
        self.assertEqual([line for _, line, _ in self.findings()], [1, 3])

    def test_language_template_counts_as_shipped(self) -> None:
        self.stage("python/.claude/rules/raven-python.md", "Since #40.\n")
        self.assertEqual(len(self.findings()), 1)

    def test_repo_docs_may_reference_issues(self) -> None:
        self.stage("docs/guide.md", "Fixed in #231.\n")
        self.stage("README.md", "Fixed in #231.\n")
        self.stage("scripts/tool.py", "# Fixed in #231.\nx = 1\n")
        self.assertEqual(self.findings(), [])

    def test_root_agents_md_bans_issue_references(self) -> None:
        self.stage("AGENTS.md", "Fixed in #231.\n\nThe `#60` reporter.\n")
        self.assertEqual([(p, line) for p, line, _ in self.findings()], [("AGENTS.md", 1)])

    def test_shipped_non_markdown_text_is_scanned(self) -> None:
        self.stage("common/.claude/hooks/raven-x.py", '"""Since #12."""\n# see issue #34\nx = 1\n')
        self.stage("common/.gitattributes", "# eol rules (#206)\n")
        self.stage("scripts/raven_lib/data/config.toml.tmpl", "# protected paths (issue #247)\n")
        self.stage("common/.raven/git-hooks/commit-msg", "# suggest `Refs: #123`\n")
        self.assertEqual(
            sorted((p, line) for p, line, _ in self.findings()),
            [
                ("common/.claude/hooks/raven-x.py", 1),
                ("common/.claude/hooks/raven-x.py", 2),
                ("common/.gitattributes", 1),
                ("scripts/raven_lib/data/config.toml.tmpl", 1),
            ],
        )

    def test_linked_code_and_qualified_references_pass(self) -> None:
        self.stage(
            "common/.claude/docs/raven-x.md",
            "See [issue #2506](https://github.com/o/r/issues/2506).\n\n"
            "Write `Refs: #123`.\n\nTracked as owner/repo#9.\n",
        )
        self.assertEqual(self.findings(), [])


class EmphasisTests(ProseRepoTestCase):
    def test_shouted_directive_in_shipped_guidance_is_reported(self) -> None:
        self.stage("common/.claude/docs/raven-x.md", "You MUST run tests.\n\nNEVER skip.\n")
        self.assertEqual([line for _, line, _ in self.findings()], [1, 3])

    def test_described_style_code_and_repo_docs_pass(self) -> None:
        self.stage(
            "common/.claude/docs/raven-x.md",
            "It injects a MUST-style block.\n\nRun `grep NEVER`.\n",
        )
        self.stage("docs/guide.md", "You MUST run tests.\n")
        self.assertEqual(self.findings(), [])

    def test_root_agents_md_is_checked_above_the_managed_block_only(self) -> None:
        self.stage("AGENTS.md", "ALWAYS ask.\n\n<!-- RAVEN:BEGIN x -->\nNEVER mind.\n")
        self.assertEqual([(p, line) for p, line, _ in self.findings()], [("AGENTS.md", 1)])


class RepeatedSentenceTests(ProseRepoTestCase):
    RULE = "Run the narrowest relevant test before the full suite."

    def test_rule_restated_in_the_same_file_is_reported(self) -> None:
        self.stage(
            "common/.agents/skills/raven-x/SKILL.md",
            f"- {self.RULE}\n\nOther text.\n\nAs said: run the narrowest\n"
            "relevant `test` before the full suite!\n",
        )
        self.assertEqual(self.findings(), [])
        self.stage(
            "common/.agents/skills/raven-x/SKILL.md",
            f"- {self.RULE}\n\nOther text.\n\nRun the narrowest\nrelevant test before the full suite.\n",
        )
        self.assertEqual(
            self.findings(),
            [("common/.agents/skills/raven-x/SKILL.md", 5, self.module.MSG_REPEAT.format(first=1))],
        )

    def test_short_stock_phrases_and_other_files_pass(self) -> None:
        self.stage("common/a.md", "See below.\n\nSee below.\n\n" + self.RULE + "\n")
        self.stage("common/b.md", self.RULE + "\n")
        self.assertEqual(self.findings(), [])


class CommentBlockTests(ProseRepoTestCase):
    def test_comment_block_over_limit_is_reported(self) -> None:
        comment = "".join(f"# line {i}\n" for i in range(11))
        self.stage("scripts/tool.py", f"import os\n\n{comment}x = 1\n")
        self.assertEqual(
            self.findings(),
            [("scripts/tool.py", 3, self.module.MSG_COMMENT.format(n=11))],
        )

    def test_comment_block_at_limit_and_shebang_pass(self) -> None:
        comment = "".join(f"# line {i}\n" for i in range(10))
        self.stage("scripts/tool.py", f"#!/usr/bin/env python3\n{comment}x = 1\n")
        self.assertEqual(self.findings(), [])

    def test_tests_are_out_of_scope(self) -> None:
        comment = "".join(f"# line {i}\n" for i in range(20))
        self.stage("tests/test_tool.py", comment)
        self.assertEqual(self.findings(), [])


class StagedContentTests(ProseRepoTestCase):
    def test_checks_the_staged_text_not_the_working_tree(self) -> None:
        self.stage("docs/guide.md", f"{_words(130)}\n")
        (self.repo / "docs/guide.md").write_text("short now\n", encoding="utf-8")
        self.assertEqual(len(self.findings()), 1)

    def test_a_fix_left_unstaged_does_not_pass(self) -> None:
        self.stage("docs/guide.md", "short\n")
        (self.repo / "docs/guide.md").write_text(f"{_words(130)}\n", encoding="utf-8")
        self.assertEqual(self.findings(), [])


class MarkerBudgetTests(ProseRepoTestCase):
    def test_markers_over_budget_are_reported(self) -> None:
        over = self.module.MARKER_BUDGET + 1
        self.stage(
            "scripts/tool.py", "".join(f"x{i} = 1  # raven-hygiene: allow\n" for i in range(over))
        )
        self.assertEqual(self.findings(), [("(tree)", 0, self.module.MSG_MARKERS.format(n=over))])

    def test_tests_quoted_markers_and_install_copies_do_not_count(self) -> None:
        many = "".join(f"x{i} = 1  # raven-hygiene: allow\n" for i in range(50))
        self.stage("tests/test_x.py", many)
        self.stage(".claude/hooks/x.py", many)
        self.stage("docs/guide.md", "Use the `raven-hygiene: allow` marker.\n\n" * 50)
        self.assertEqual(self.findings(), [])

    def test_a_marker_approving_a_limit_raise_does_not_count(self) -> None:
        over = self.module.MARKER_BUDGET + 1
        lines = "".join(
            f'    "k{i}": 9,  # raven-hygiene: allow -- measured\n' for i in range(over)
        )
        self.stage("evals/scenarios.py", "FIXED_COST_OVERHEAD_CEILINGS = {\n" + lines + "}\n")
        self.stage(
            "evals/other.py", "".join(f"x{i} = 1  # raven-hygiene: allow\n" for i in range(over))
        )
        self.assertEqual(self.findings(), [("(tree)", 0, self.module.MSG_MARKERS.format(n=over))])


class PlanArtifactTests(ProseRepoTestCase):
    def test_staged_plan_is_reported_before_commit(self) -> None:
        self.stage("docs/superpowers/plans/2026-01-01-x.md", "plan\n")
        self.stage(".raven/plans/y.md", "plan\n")
        self.assertEqual(
            sorted(path for path, _, _ in self.findings()),
            [".raven/plans/y.md", "docs/superpowers/plans/2026-01-01-x.md"],
        )

    def test_symlinked_markdown_is_scanned_once(self) -> None:
        self.stage("common/docs/a.md", "It is X, not Y.\n\nAnd A, not B.\n")
        (self.repo / "python").mkdir()
        (self.repo / "python" / "a.md").symlink_to("../common/docs/a.md")
        subprocess.run(["git", "-C", str(self.repo), "add", "python/a.md"], check=True)
        self.assertEqual([path for path, _, _ in self.findings()], ["common/docs/a.md"])


class RealRepositoryScopeTests(unittest.TestCase):
    def test_scope_covers_shipped_guidance_and_runtime(self) -> None:
        module = load_script_module("check_prose_real_repo", CHECKER_PATH)
        paths = [entry.path for entry in module.tracked_files() if entry.regular]
        markdown = [p for p in paths if module.is_covered_markdown(p)]
        python = [p for p in paths if module.is_covered_python(p)]
        self.assertGreaterEqual(len(markdown), 90)
        self.assertGreaterEqual(len(python), 50)
        self.assertIn("common/AGENTS.md", markdown)
        self.assertIn("scripts/raven_lib/cli.py", python)


if __name__ == "__main__":
    unittest.main()
