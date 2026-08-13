"""Behavioral tests for `scripts/check-guidance.py` (issue #164).

The checker's two categories both key off `git ls-files '*.md'`, so tests
that plant a defect build a real temporary git repository and commit into it
-- a hand-written string fed straight to the parsing functions would not
exercise the same code path a real doc lives behind.

The CLI-contract category is validated against the *real* parser via
`raven_lib.cli.build_parser`, so those tests import it directly rather than
hardcoding the subcommand/flag lists issue #164 calls out as measured ground
truth (kept here only as assertions to catch drift, never as the source the
checker itself reads from).
"""

from __future__ import annotations

import io
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from helpers import REPO_ROOT, load_script_module

CHECKER_PATH = REPO_ROOT / "scripts" / "check-guidance.py"


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.email=guidance-test@example.com",
            "-c",
            "user.name=Guidance Test",
            *args,
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def _commit(repo: Path, path: str, content: str) -> None:
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    _git(repo, "add", "--", path)
    _git(repo, "commit", "-q", "-m", f"add {path}")


class GuidanceRepoTestCase(unittest.TestCase):
    """A temporary real git repo, so `git ls-files` behaves like it would for real docs."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name)
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        self.module = load_script_module("check_guidance_under_test", CHECKER_PATH)


class MarkdownLinkFindingsTests(GuidanceRepoTestCase):
    def test_broken_relative_link_reports_file_and_line(self) -> None:
        _commit(
            self.repo,
            "docs/plan.md",
            "intro\n\nSee [the guide](does/not/exist.md) for details.\n",
        )

        findings = self.module.find_markdown_link_findings(self.repo)

        self.assertEqual(len(findings), 1, findings)
        path, line_no, message = findings[0]
        self.assertEqual(path, "docs/plan.md")
        self.assertEqual(line_no, 3)
        self.assertIn("does/not/exist.md", message)
        self.assertIn("missing file", message)

    def test_working_relative_link_is_not_a_finding(self) -> None:
        _commit(self.repo, "README.md", "See [target](target.md).\n")
        _commit(self.repo, "target.md", "# Target\n")

        findings = self.module.find_markdown_link_findings(self.repo)

        self.assertEqual(findings, [])

    def test_link_resolves_relative_to_the_linking_file_not_repo_root(self) -> None:
        # sibling.md sits next to nested/doc.md, not at repo root -- only
        # correct if resolution uses the linking file's own directory.
        _commit(self.repo, "nested/doc.md", "See [sibling](sibling.md).\n")
        _commit(self.repo, "nested/sibling.md", "# Sibling\n")

        findings = self.module.find_markdown_link_findings(self.repo)

        self.assertEqual(findings, [])

    def test_fragment_is_stripped_and_only_the_file_part_is_checked(self) -> None:
        # Anchor resolution is out of scope (issue #164); an arbitrary,
        # possibly-nonexistent fragment must not fail the check on its own.
        _commit(self.repo, "README.md", "See [target](target.md#nonexistent-heading).\n")
        _commit(self.repo, "target.md", "# Target\n")

        findings = self.module.find_markdown_link_findings(self.repo)

        self.assertEqual(findings, [])

    def test_external_link_is_ignored(self) -> None:
        _commit(self.repo, "README.md", "See [docs](https://example.com/missing).\n")

        findings = self.module.find_markdown_link_findings(self.repo)

        self.assertEqual(findings, [])

    def test_anchor_only_link_is_ignored(self) -> None:
        _commit(self.repo, "README.md", "See [section below](#some-section).\n")

        findings = self.module.find_markdown_link_findings(self.repo)

        self.assertEqual(findings, [])

    def test_broken_symlink_target_is_reported_distinctly_from_missing(self) -> None:
        _commit(self.repo, "README.md", "See [target](broken-link.md).\n")
        # A symlink git tracks whose target does not exist -- distinct from a
        # link whose target was never there at all (this repo uses symlinks
        # heavily, so the two are worth telling apart in the message).
        (self.repo / "broken-link.md").symlink_to("does-not-exist.md")
        _git(self.repo, "add", "--", "README.md", "broken-link.md")
        _git(self.repo, "commit", "-q", "-m", "add broken symlink")

        findings = self.module.find_markdown_link_findings(self.repo)

        self.assertEqual(len(findings), 1, findings)
        self.assertIn("broken symlink", findings[0][2])

    def test_multiple_links_on_one_file_report_each_with_correct_line(self) -> None:
        _commit(
            self.repo,
            "README.md",
            "line one\n[good](real.md)\n[bad](missing-one.md)\nmore text\n[also bad](missing-two.md)\n",
        )
        _commit(self.repo, "real.md", "# Real\n")

        findings = self.module.find_markdown_link_findings(self.repo)

        self.assertEqual(len(findings), 2, findings)
        by_line = {line_no: message for _, line_no, message in findings}
        self.assertIn(3, by_line)
        self.assertIn("missing-one.md", by_line[3])
        self.assertIn(5, by_line)
        self.assertIn("missing-two.md", by_line[5])

    def test_symlinked_directory_is_validated_once_not_per_symlink(self) -> None:
        # git tracks a symlinked directory as a single blob and does not
        # enumerate files beneath it -- `git ls-files '*.md'` therefore never
        # yields the same doc twice under two different tree paths.
        _commit(self.repo, "common/docs/guide.md", "See [target](target.md).\n")
        _commit(self.repo, "common/docs/target.md", "# Target\n")
        (self.repo / "lang").mkdir()
        (self.repo / "lang" / "docs").symlink_to("../common/docs")
        _git(self.repo, "add", "--", "lang/docs")
        _git(self.repo, "commit", "-q", "-m", "symlink lang/docs to common/docs")

        tracked = self.module._tracked_markdown_files(self.repo)

        self.assertEqual(tracked.count("common/docs/guide.md"), 1)
        self.assertNotIn("lang/docs/guide.md", tracked)


class CliDocFindingsTests(GuidanceRepoTestCase):
    def test_undefined_flag_reports_file_and_line(self) -> None:
        _commit(
            self.repo,
            "README.md",
            "intro\n\n```sh\nraven doctor --not-a-real-flag\n```\n",
        )

        findings = self.module.find_cli_doc_findings(self.repo)

        self.assertEqual(len(findings), 1, findings)
        path, line_no, message = findings[0]
        self.assertEqual(path, "README.md")
        self.assertEqual(line_no, 4)
        self.assertIn("--not-a-real-flag", message)

    def test_undefined_subcommand_reports_file_and_line(self) -> None:
        _commit(
            self.repo,
            "README.md",
            "```sh\nraven frobnicate\n```\n",
        )

        findings = self.module.find_cli_doc_findings(self.repo)

        self.assertEqual(len(findings), 1, findings)
        path, line_no, message = findings[0]
        self.assertEqual(path, "README.md")
        self.assertEqual(line_no, 2)
        self.assertIn("frobnicate", message)

    def test_flag_valid_for_a_different_subcommand_is_reported(self) -> None:
        # --dry-run is real, but not defined on `doctor` -- judgment call:
        # this must fail, distinctly from an outright-unknown flag.
        _commit(self.repo, "README.md", "```sh\nraven doctor --dry-run\n```\n")

        findings = self.module.find_cli_doc_findings(self.repo)

        self.assertEqual(len(findings), 1, findings)
        self.assertIn("--dry-run", findings[0][2])
        self.assertIn("different subcommand", findings[0][2])

    def test_valid_documented_forms_all_pass(self) -> None:
        content = "\n".join(
            [
                "```sh",
                "raven install <language> --dry-run",
                "raven upgrade .claude/scripts/raven-tool-check.py",
                "raven accept .mcp.json  # or accept specific paths",
                "raven assess --json   # machine-readable output (combine with --run)",
                "raven doctor          # human-readable report",
                'python scripts/raven.py --destination "$destination" install python --platform github',
                "raven init rust",
                "```",
                "",
            ]
        )
        _commit(self.repo, "README.md", content)

        findings = self.module.find_cli_doc_findings(self.repo)

        self.assertEqual(findings, [], findings)

    def test_global_flag_before_subcommand_is_accepted(self) -> None:
        _commit(
            self.repo,
            "README.md",
            "```sh\npython scripts/raven.py --destination /tmp/x install python\n```\n",
        )

        findings = self.module.find_cli_doc_findings(self.repo)

        self.assertEqual(findings, [])

    def test_env_assignment_prefix_is_stripped_before_recognition(self) -> None:
        _commit(
            self.repo,
            "SKILL.md",
            "```sh\nPYTHONDONTWRITEBYTECODE=1 python scripts/raven.py install python --dry-run\n```\n",
        )

        findings = self.module.find_cli_doc_findings(self.repo)

        self.assertEqual(findings, [])

    def test_prose_mentioning_a_flag_without_backticks_is_not_parsed(self) -> None:
        # Judgment call: a sentence merely mentioning --json in prose (no
        # backticks, no fence) must not be treated as an invocation at all --
        # if it were, this would need to resolve to *some* subcommand, and
        # there isn't one to check it against.
        _commit(
            self.repo,
            "README.md",
            "Pass --json to raven assess for machine-readable output.\n",
        )

        findings = self.module.find_cli_doc_findings(self.repo)

        self.assertEqual(findings, [])

    def test_inline_code_span_invocation_is_recognized(self) -> None:
        _commit(
            self.repo,
            "README.md",
            "Run `raven doctor --not-a-real-flag` to check.\n",
        )

        findings = self.module.find_cli_doc_findings(self.repo)

        self.assertEqual(len(findings), 1, findings)
        self.assertEqual(findings[0][1], 1)

    def test_bracket_placeholder_flag_notation_is_not_validated(self) -> None:
        # `[--dry-run]` is optional-argument notation, not a literal
        # invocation of the flag -- it must not be flagged even though the
        # bracketed spelling isn't a real argparse flag string.
        _commit(
            self.repo,
            "spec.md",
            "```\nraven install [language] [overrides...] [--dry-run] [--include-readme]\n```\n",
        )

        findings = self.module.find_cli_doc_findings(self.repo)

        self.assertEqual(findings, [])

    def test_plain_mention_of_raven_with_no_subcommand_is_harmless(self) -> None:
        _commit(self.repo, "README.md", "Run `raven` and follow the prompts.\n")

        findings = self.module.find_cli_doc_findings(self.repo)

        self.assertEqual(findings, [])


class BuildParserContractTests(unittest.TestCase):
    """Ground truth measured for issue #164 -- asserted here to catch drift,
    never restated inside check-guidance.py itself.
    """

    def setUp(self) -> None:
        sys.path.insert(0, str(REPO_ROOT / "scripts"))
        from raven_lib.cli import build_parser

        self.module = load_script_module("check_guidance_contract", CHECKER_PATH)
        self.parser = build_parser()

    def test_subcommands_match_measured_ground_truth(self) -> None:
        subcommands, _, _, _ = self.module._parser_maps(self.parser)
        self.assertEqual(subcommands, {"accept", "assess", "doctor", "init", "install", "upgrade"})

    def test_flags_match_measured_ground_truth(self) -> None:
        _, per_command, global_flags, _ = self.module._parser_maps(self.parser)
        all_flags: set[str] = set(global_flags)
        for flags in per_command.values():
            all_flags |= flags
        all_flags -= {"-h", "--help", "-d"}
        self.assertEqual(
            all_flags,
            {
                "--adopt-claude-symlink",
                "--confirm-template-switch",
                "--destination",
                "--dry-run",
                "--include-readme",
                "--json",
                "--platform",
                "--run",
            },
        )


class RealRepoCleanPassTests(unittest.TestCase):
    """Issue #164 measured 0 broken links and 0 undefined-flag docs on this
    repository as it stands -- no baseline suppression list is needed or
    permitted. This must stay true.
    """

    def setUp(self) -> None:
        self.module = load_script_module("check_guidance_real_repo", CHECKER_PATH)

    def test_real_repo_has_no_broken_markdown_links(self) -> None:
        findings = self.module.find_markdown_link_findings()
        self.assertEqual(findings, [], findings)

    def test_real_repo_has_no_undefined_cli_flags_documented(self) -> None:
        findings = self.module.find_cli_doc_findings()
        self.assertEqual(findings, [], findings)

    def test_main_passes_clean_on_the_real_repo(self) -> None:
        buf = io.StringIO()
        with redirect_stdout(buf):
            exit_code = self.module.main()
        self.assertEqual(exit_code, 0)
        self.assertIn("ok", buf.getvalue())


class SubprocessInvocationTests(unittest.TestCase):
    """The script must also work invoked standalone (not just imported), since
    it is documented as callable both ways.
    """

    def test_standalone_invocation_on_real_repo_exits_zero(self) -> None:
        result = subprocess.run(
            [sys.executable, str(CHECKER_PATH)],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
