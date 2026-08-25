"""Cross-checks between docs/commands.md, docs/upgrading.md, README.md, and
what the CLI actually does (#244, #241).

`docs/commands.md` bills itself as the full reference but silently omitted
three real flags, and `docs/upgrading.md` hand-copied `render_dry_run_summary`'s
bucket list once and let it drift. The bucket-list check follows the same
scan-the-real-source pattern as `test_gitattributes.py`'s shipped-coverage
tests: derive the truth from code, not from a second hand-maintained copy.

README.md also never said that `install` writes git hooks that gate every
commit and push -- that one is a plain presence check, since "does this doc
name the three hooks" has no single source of truth in code to scan instead.
"""

from __future__ import annotations

import re
import unittest

from helpers import REPO_ROOT
from raven_lib.models import Classification
from raven_lib.plan import render_dry_run_summary

COMMANDS_DOC = REPO_ROOT / "docs" / "commands.md"
UPGRADING_DOC = REPO_ROOT / "docs" / "upgrading.md"
README_DOC = REPO_ROOT / "README.md"


class CommandsDocMentionsEveryFlagTests(unittest.TestCase):
    def setUp(self):
        self.text = COMMANDS_DOC.read_text(encoding="utf-8")

    def test_mentions_destination(self):
        self.assertIn("--destination", self.text)

    def test_mentions_platform(self):
        self.assertIn("--platform", self.text)

    def test_mentions_include_readme(self):
        self.assertIn("--include-readme", self.text)


class GitHooksAreDocumentedTests(unittest.TestCase):
    """#241 -- install silently starts gating every commit and push; both
    docs must say so, name the three hooks, and say .gitignore is touched.
    """

    def test_readme_names_all_three_hooks_and_gitignore(self):
        text = README_DOC.read_text(encoding="utf-8")
        for hook in ("commit-msg", "pre-commit", "pre-push"):
            self.assertIn(hook, text)
        self.assertIn(".gitignore", text)

    def test_commands_doc_install_section_mentions_git_hooks(self):
        text = COMMANDS_DOC.read_text(encoding="utf-8")
        install_section = text.split("## `raven install")[1].split("\n## ")[0]
        self.assertIn("git hooks", install_section)
        self.assertIn("pre-push", install_section)


def _doc_dry_run_buckets() -> list[str]:
    """The bucket list under "## What an upgrade changes" in upgrading.md.

    Bullets may wrap across lines (two-space-indented continuations); this
    joins each bullet back into one line before returning it.
    """
    text = UPGRADING_DOC.read_text(encoding="utf-8")
    match = re.search(r"sorts every file into one of these buckets:\n\n(.+?)\n\n", text, re.DOTALL)
    assert match is not None, "expected a bucket list after the 'sorts every file' sentence"
    buckets = []
    for line in match.group(1).splitlines():
        if line.startswith("- "):
            buckets.append(line[2:].rstrip())
        elif line.startswith("  ") and buckets:
            buckets[-1] += " " + line.strip()
    return buckets


def _renderer_section_titles() -> list[str]:
    """Every section title `render_dry_run_summary` can emit, code as source of truth.

    Every bucket populated, so both conditional sections (local_only,
    needs_adoption) are present alongside the five unconditional ones.
    """
    classification = Classification(
        will_copy=["a"],
        will_upgrade=["b"],
        identical=["c"],
        needs_merge=["d"],
        unknown_existing=["e"],
        excluded=["f"],
        local_only=["g"],
        needs_adoption=["h"],
    )
    rendered = render_dry_run_summary(classification)
    titles = []
    for section in rendered.split("\n\n"):
        first_line = section.splitlines()[0]
        if first_line.endswith(":"):
            titles.append(first_line[:-1])
    return titles


class UpgradingDocBucketListMatchesRendererTests(unittest.TestCase):
    def test_doc_lists_exactly_the_sections_the_renderer_can_emit(self):
        doc_buckets = [re.sub(r"[`*]", "", b) for b in _doc_dry_run_buckets()]
        renderer_titles = [re.sub(r"[`*]", "", t) for t in _renderer_section_titles()]
        self.assertEqual(
            sorted(doc_buckets),
            sorted(renderer_titles),
            "docs/upgrading.md's bucket list no longer matches "
            "plan.render_dry_run_summary's section titles",
        )

    def test_excluded_paths_are_not_rendered_and_the_doc_does_not_claim_a_bucket_for_them(self):
        # #244: render_dry_run_summary never surfaces `Classification.excluded`
        # -- confirm that stays true, and that the doc makes no claim of an
        # "Excluded template or configured files" bucket that does not exist.
        classification = Classification(
            will_copy=[],
            will_upgrade=[],
            identical=[],
            needs_merge=[],
            unknown_existing=[],
            excluded=["some/excluded/path"],
        )
        rendered = render_dry_run_summary(classification)
        self.assertNotIn("some/excluded/path", rendered)
        self.assertNotIn("Excluded", UPGRADING_DOC.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
