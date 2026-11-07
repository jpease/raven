"""Tests for `raven-review-prose.py`, the raven-review-prose skill's helper.

The skill once carried these steps as inline shell. Each test class below pins
a case that shell got wrong: a mistyped base labelled every line in scope,
working-tree line numbers were blamed against HEAD, and case-sensitive,
line-at-a-time patterns missed "At its core" and wrapped clauses.
"""

from __future__ import annotations

import io
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from helpers import REPO_ROOT, load_script_module

SCRIPT = REPO_ROOT / "common" / ".claude" / "scripts" / "raven-review-prose.py"
CODEX_SCRIPT = REPO_ROOT / "common" / ".codex" / "scripts" / "raven-review-prose.py"


def _module():
    return load_script_module("raven_review_prose", SCRIPT)


def _checks(text: str, *only: str) -> list[tuple[int, str, str]]:
    module = _module()
    return module.sweep_text(text, only or module.CHECKS)


class SweepTests(unittest.TestCase):
    def test_sentence_opening_essence_phrase_matches(self):
        hits = _checks("Intro.\n\nAt its core, the parser is a loop.\n", "essence")
        self.assertEqual([(n, c) for n, c, _ in hits], [(3, "essence")])

    def test_participle_wrapped_onto_the_next_line_matches_on_the_comma_line(self):
        text = "The cache now expires entries,\nensuring nothing stale survives.\n"
        hits = _checks(text, "participle")
        self.assertEqual([(n, c) for n, c, _ in hits], [(1, "participle")])

    def test_title_case_heading_contrast_matches(self):
        hits = _checks("# Title\n\n## Correctness, Not Speed\n\nBody.\n", "contrast-heading")
        self.assertEqual([(n, c) for n, c, _ in hits], [(3, "contrast-heading")])

    def test_heading_does_not_join_the_line_after_it(self):
        hits = _checks("## Fast path,\nnot taken here.\n", "contrast-heading")
        self.assertEqual(hits, [])

    def test_fenced_and_inline_code_are_not_prose(self):
        text = (
            "Use the `rather than` form sparingly.\n"
            "\n"
            "```bash\n"
            "echo 'at its core, rather than this'\n"
            "```\n"
        )
        self.assertEqual(_checks(text, "contrast", "essence"), [])

    def test_front_matter_delimiter_ends_a_paragraph(self):
        hits = _checks("---\nname: x\n---\n\nPlain rather than fancy.\n", "contrast")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0][0], 5)
        self.assertNotIn("---", hits[0][2])

    def test_heading_contrast_on_a_named_thing_still_matches_beside_code(self):
        # Masking inline code must leave ", not" outside the span visible.
        hits = _checks("## Repo root, not `cwd`\n", "contrast-heading")
        self.assertEqual(len(hits), 1)

    def test_long_words_include_sentence_openers_and_skip_identifiers(self):
        text = (
            "Additionally the configuration loads.\n"
            "See `raven-capability-roster.py` and getConfiguration at https://example.com/documentation.\n"
            "The configuration again.\n"
        )
        words = [(n, d) for n, c, d in _checks(text, "long-word")]
        self.assertEqual(words, [(1, "additionally"), (1, "configuration")])

    def test_stakes_phrase_matches_across_a_line_break(self):
        hits = _checks("This release changes\neverything.\n", "stakes")
        self.assertEqual([(n, c) for n, c, _ in hits], [(1, "stakes")])

    def test_cli_exit_codes(self):
        with tempfile.TemporaryDirectory() as tmp:
            clean = Path(tmp) / "clean.md"
            clean.write_text("Short words.\n", encoding="utf-8")
            dirty = Path(tmp) / "dirty.md"
            dirty.write_text("It boils down to luck.\n", encoding="utf-8")
            module = _module()
            with redirect_stdout(io.StringIO()):
                self.assertEqual(module.main(["sweep", str(clean)]), 0)
            out = io.StringIO()
            with redirect_stdout(out):
                self.assertEqual(module.main(["sweep", "--only", "essence", str(dirty)]), 1)
            self.assertIn(f"{dirty}:1: essence:", out.getvalue())
            with redirect_stdout(io.StringIO()):
                self.assertEqual(module.main(["sweep", str(Path(tmp) / "missing.md")]), 2)


class GitRepoTestCase(unittest.TestCase):
    def setUp(self):
        # A hook-driven test run may inherit GIT_DIR/GIT_INDEX_FILE, which
        # would point git at the outer repo instead of the temp one.
        for var in [k for k in os.environ if k.startswith("GIT_")]:
            self.addCleanup(os.environ.__setitem__, var, os.environ[var])
            del os.environ[var]
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name)
        self._git("init", "-q")

    def _git(self, *args: str) -> str:
        return subprocess.run(
            ["git", "-c", "user.email=t@example.com", "-c", "user.name=T", *args],
            cwd=self.repo,
            capture_output=True,
            text=True,
            check=True,
        ).stdout

    def _commit(self, path: str, content: str, message: str) -> None:
        (self.repo / path).write_text(content, encoding="utf-8")
        self._git("add", "--", path)
        self._git("commit", "-q", "-m", message)

    def _run(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            cwd=self.repo,
            capture_output=True,
            text=True,
            check=False,
        )


class ScopeTests(GitRepoTestCase):
    def setUp(self):
        super().setUp()
        self._commit("doc.md", "old line one\nold line two\n", "base")
        self._git("branch", "base")

    def test_pre_existing_and_branch_lines(self):
        self._commit("doc.md", "old line one\nold line two\nbranch line\n", "branch")
        result = self._run("scope", "--base", "base", "doc.md:1-3")
        self.assertEqual(result.returncode, 0, result.stderr)
        verdicts = [line.split(": ", 1)[1].split(" (")[0] for line in result.stdout.splitlines()]
        self.assertEqual(verdicts, ["pre-existing", "pre-existing", "in scope"])

    def test_uncommitted_line_uses_working_tree_numbering(self):
        # Blaming HEAD with a working-tree line number labelled the new first
        # line with HEAD's first line, which predates the base.
        (self.repo / "doc.md").write_text(
            "new line\nold line one\nold line two\n", encoding="utf-8"
        )
        result = self._run("scope", "--base", "base", "doc.md:1", "doc.md:3")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines()[0], "doc.md:1: in scope (not committed yet)")
        self.assertIn("doc.md:3: pre-existing", result.stdout)

    def test_moved_lines_trace_back_to_their_author(self):
        block = "".join(
            f"moved paragraph line {i} with plenty of text to match\n" for i in range(4)
        )
        self._commit("long.md", "first\n" + block + "last\n", "long base")
        self._git("branch", "-f", "base")
        self._commit("long.md", "first\nlast\n" + block, "move block")
        result = self._run("scope", "--base", "base", "long.md:3-6")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.count("pre-existing"), 4, result.stdout)

    def test_unknown_base_fails_instead_of_labelling_everything_in_scope(self):
        result = self._run("scope", "--base", "no-such-ref", "doc.md:1")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertIn("no-such-ref", result.stderr)

    def test_line_past_end_of_file_is_an_error(self):
        result = self._run("scope", "--base", "base", "doc.md:9")
        self.assertEqual(result.returncode, 2)
        self.assertNotIn("in scope", result.stdout)

    def test_malformed_target_is_an_error(self):
        result = self._run("scope", "--base", "base", "doc.md")
        self.assertEqual(result.returncode, 2)
        self.assertIn("FILE:LINE", result.stderr)

    def test_file_head_does_not_track_is_all_in_scope(self):
        (self.repo / "new.md").write_text("one\ntwo\n", encoding="utf-8")
        result = self._run("scope", "--base", "base", "new.md:1-2")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            ["new.md:1: in scope (not committed yet)", "new.md:2: in scope (not committed yet)"],
        )
        past_end = self._run("scope", "--base", "base", "new.md:3")
        self.assertEqual(past_end.returncode, 2)
        self.assertEqual(past_end.stdout, "")


class SubjectsTests(GitRepoTestCase):
    def test_title_case_contrast_subject_is_reported(self):
        self._commit("a.txt", "a\n", "Fix: Correctness, Not Speed")
        self._commit("b.txt", "b\n", "add the b file")
        result = self._run("subjects", "-n", "10")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("Correctness, Not Speed", result.stdout)
        self.assertNotIn("add the b file", result.stdout)


class ValeTests(unittest.TestCase):
    def test_missing_vale_skips_and_succeeds(self):
        module = _module()
        out = io.StringIO()
        with patch.object(module.shutil, "which", return_value=None), redirect_stdout(out):
            self.assertEqual(module.main(["vale", "README.md"]), 0)
        self.assertEqual(out.getvalue(), "vale not installed; skipping the word pass\n")

    def test_unsynced_packages_are_named(self):
        module = _module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "styles" / "proselint").mkdir(parents=True)
            config = root / ".vale.ini"
            config.write_text(
                "StylesPath = styles\n"
                "# Packages = commented, out\n"
                "Packages = proselint, write-good, https://example.com/x/AITells.zip\n"
                "\n[*.md]\nPackages = ignored\n",
                encoding="utf-8",
            )
            self.assertEqual(module.unsynced_packages(config), ["write-good", "AITells"])

    def test_default_config_resolves_from_every_adapter_path(self):
        expected = "common/.agents/skills/raven-write-prose/reference/vale/.vale.ini"
        for script in (SCRIPT, CODEX_SCRIPT):
            with self.subTest(script=script):
                module = load_script_module("raven_review_prose_adapter", script)
                config = module.default_vale_config()
                self.assertTrue(config.is_file(), config)
                self.assertTrue(config.as_posix().endswith(expected), config)

    def test_shipped_config_declares_packages_the_check_can_read(self):
        module = _module()
        config = module.default_vale_config()
        declared = set(module.unsynced_packages(config)) | {
            p.name for p in (config.parent / "styles").iterdir() if p.is_dir()
        }
        self.assertTrue({"proselint", "write-good", "Readability"} <= declared)


if __name__ == "__main__":
    unittest.main()
