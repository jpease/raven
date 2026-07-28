from __future__ import annotations

import hashlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from helpers import REPO_ROOT, load_script_module, raven

SCRIPT_PATH = (
    REPO_ROOT / "common" / ".raven" / "git-hooks" / "lib" / "check-managed-block-integrity.py"
)
INSTALLED_SCRIPT_PATH = (
    REPO_ROOT / ".raven" / "git-hooks" / "lib" / "check-managed-block-integrity.py"
)

# Same table fixture as tests/test_managed_blocks.py: a compact separator row
# restyled the way a downstream markdown formatter would restyle it.
_TABLE_SOURCE = "# RAVEN guidance\n\n| Need | First tool |\n|---|---|\n| Exact string | `rg` |\n"
_COMPACT_SEPARATOR = "|---|---|"
_PADDED_SEPARATOR = "| --- | --- |"


def _legacy_managed_block(content: str) -> str:
    """A managed block carrying the pre-#118 declared sha256 (transcribed)."""
    normalized = raven.normalized_block_content(content)
    sha = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return "\n".join(
        [
            "",
            f"<!-- RAVEN:BEGIN sha256={sha} -->",
            *normalized.splitlines(),
            "<!-- RAVEN:END -->",
        ]
    )


class ManagedBlockIntegrityHookTests(unittest.TestCase):
    SCRIPT_PATH = SCRIPT_PATH

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name)
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)

    def _write(self, path: str, content: str) -> None:
        (self.repo / path).write_text(content, encoding="utf-8")

    def _symlink(self, path: str, target: str) -> None:
        (self.repo / path).symlink_to(target)

    def _stage(self, path: str) -> None:
        subprocess.run(["git", "add", "--", path], cwd=str(self.repo), check=True)

    def _stage_deletion(self, path: str) -> None:
        """Stage removal of an already-staged path, leaving the worktree file in place."""
        subprocess.run(["git", "rm", "-q", "--cached", "--", path], cwd=str(self.repo), check=True)

    def _run(self) -> tuple[int, str]:
        result = subprocess.run(
            [sys.executable, str(self.SCRIPT_PATH)],
            capture_output=True,
            text=True,
            cwd=str(self.repo),
        )
        return result.returncode, result.stderr

    def test_allows_unmodified_managed_block(self):
        self._write("AGENTS.md", raven.raven_managed_block("# Guidance\n"))
        self._stage("AGENTS.md")
        rc, _ = self._run()
        self.assertEqual(rc, 0)

    def test_blocks_directly_edited_managed_block(self):
        block = raven.raven_managed_block("# Guidance\n")
        tampered = block.replace("# Guidance", "# Guidance (hand-edited)")
        self._write("AGENTS.md", tampered)
        self._stage("AGENTS.md")
        rc, err = self._run()
        self.assertEqual(rc, 1)
        self.assertIn("AGENTS.md", err)
        self.assertIn("edited directly", err)

    def test_allows_file_with_no_managed_block(self):
        self._write("AGENTS.md", "# Plain guidance, no managed block\n")
        self._stage("AGENTS.md")
        rc, _ = self._run()
        self.assertEqual(rc, 0)

    def test_skips_symlinked_claude_md(self):
        block = raven.raven_managed_block("# Guidance\n")
        tampered = block.replace("# Guidance", "# Guidance (hand-edited)")
        self._write("AGENTS.md", tampered)
        self._stage("AGENTS.md")
        self._symlink("CLAUDE.md", "AGENTS.md")
        self._stage("CLAUDE.md")
        # AGENTS.md itself is still tampered, so this should still fail --
        # this test only proves the symlink target isn't double-reported.
        rc, err = self._run()
        self.assertEqual(rc, 1)
        self.assertEqual(err.count("edited directly"), 1)

    def test_checks_claude_md_when_it_is_a_real_file(self):
        block = raven.raven_managed_block("# Guidance\n")
        tampered = block.replace("# Guidance", "# Guidance (hand-edited)")
        self._write("CLAUDE.md", tampered)
        self._stage("CLAUDE.md")
        rc, err = self._run()
        self.assertEqual(rc, 1)
        self.assertIn("CLAUDE.md", err)

    def test_blocks_staged_tamper_even_when_worktree_is_restored(self):
        # Regression guard for the index-vs-worktree bypass: tamper the block,
        # stage it, then restore the working copy to valid text (e.g. as
        # `raven upgrade` would). The staged content -- what would actually be
        # committed -- is still tampered, so the hook must still fail.
        valid = raven.raven_managed_block("# Guidance\n")
        tampered = valid.replace("# Guidance", "# Guidance (hand-edited)")
        self._write("AGENTS.md", tampered)
        self._stage("AGENTS.md")
        self._write("AGENTS.md", valid)
        rc, err = self._run()
        self.assertEqual(rc, 1)
        self.assertIn("AGENTS.md", err)
        self.assertIn("edited directly", err)

    def test_allows_staged_valid_block_even_when_worktree_is_tampered(self):
        # Mirror of the regression guard: the index holds a valid block, only
        # the on-disk copy is tampered. The commit itself is clean, so the
        # hook must pass -- proving it checks the index rather than the
        # worktree (or both).
        valid = raven.raven_managed_block("# Guidance\n")
        tampered = valid.replace("# Guidance", "# Guidance (hand-edited)")
        self._write("AGENTS.md", valid)
        self._stage("AGENTS.md")
        self._write("AGENTS.md", tampered)
        rc, _ = self._run()
        self.assertEqual(rc, 0)

    def test_skips_file_absent_from_index(self):
        # Present on disk, tampered, but never staged: nothing under this
        # name is being committed, so the hook must not fail on it.
        block = raven.raven_managed_block("# Guidance\n")
        tampered = block.replace("# Guidance", "# Guidance (hand-edited)")
        self._write("AGENTS.md", tampered)
        rc, _ = self._run()
        self.assertEqual(rc, 0)

    def test_skips_staged_deletion(self):
        block = raven.raven_managed_block("# Guidance\n")
        tampered = block.replace("# Guidance", "# Guidance (hand-edited)")
        self._write("AGENTS.md", tampered)
        self._stage("AGENTS.md")
        self._stage_deletion("AGENTS.md")
        rc, _ = self._run()
        self.assertEqual(rc, 0)

    def test_script_is_executable(self):
        self.assertTrue(self.SCRIPT_PATH.stat().st_mode & 0o111)

    def test_installed_script_is_executable(self):
        self.assertTrue(INSTALLED_SCRIPT_PATH.stat().st_mode & 0o111)

    # --- issue #118: normalization-invariant identity -------------------

    def test_allows_table_separator_restyled_block(self):
        restyled = raven.raven_managed_block(_TABLE_SOURCE).replace(
            _COMPACT_SEPARATOR, _PADDED_SEPARATOR
        )
        self._write("AGENTS.md", restyled)
        self._stage("AGENTS.md")
        rc, err = self._run()
        self.assertEqual(rc, 0, err)

    def _prettier(self, text: str) -> str:
        """A full prettier-style pass: padded separator *and* padded cells."""
        return (
            text.replace(_COMPACT_SEPARATOR, "| ------------ | ---------- |")
            .replace("| Need | First tool |", "| Need         | First tool |")
            .replace("| Exact string | `rg` |", "| Exact string | `rg`       |")
        )

    def test_allows_fully_prettier_formatted_block(self):
        self._write("AGENTS.md", self._prettier(raven.raven_managed_block(_TABLE_SOURCE)))
        self._stage("AGENTS.md")
        rc, err = self._run()
        self.assertEqual(rc, 0, err)

    def test_blocks_prose_edit_in_a_prettier_formatted_block(self):
        tampered = self._prettier(raven.raven_managed_block(_TABLE_SOURCE)).replace(
            "# RAVEN guidance", "# RAVEN guidance (hand-edited)"
        )
        self._write("AGENTS.md", tampered)
        self._stage("AGENTS.md")
        rc, err = self._run()
        self.assertEqual(rc, 1)
        self.assertIn("edited directly", err)

    def test_blocks_table_cell_content_edit(self):
        tampered = self._prettier(raven.raven_managed_block(_TABLE_SOURCE)).replace(
            "`rg`       |", "`fd`       |"
        )
        self._write("AGENTS.md", tampered)
        self._stage("AGENTS.md")
        rc, err = self._run()
        self.assertEqual(rc, 1)
        self.assertIn("edited directly", err)

    def test_blocks_prose_edit_hidden_behind_a_table_restyle(self):
        tampered = (
            raven.raven_managed_block(_TABLE_SOURCE)
            .replace(_COMPACT_SEPARATOR, _PADDED_SEPARATOR)
            .replace("# RAVEN guidance", "# RAVEN guidance (hand-edited)")
        )
        self._write("AGENTS.md", tampered)
        self._stage("AGENTS.md")
        rc, err = self._run()
        self.assertEqual(rc, 1)
        self.assertIn("edited directly", err)

    def test_allows_untouched_legacy_sha_block(self):
        self._write("AGENTS.md", _legacy_managed_block(_TABLE_SOURCE))
        self._stage("AGENTS.md")
        rc, err = self._run()
        self.assertEqual(rc, 0, err)

    def test_blocks_prose_edit_in_a_legacy_sha_block(self):
        tampered = _legacy_managed_block(_TABLE_SOURCE).replace(
            "# RAVEN guidance", "# RAVEN guidance (hand-edited)"
        )
        self._write("AGENTS.md", tampered)
        self._stage("AGENTS.md")
        rc, err = self._run()
        self.assertEqual(rc, 1)
        self.assertIn("edited directly", err)


# --- library/hook normalization drift guard (issue #118) -------------------
#
# check-managed-block-integrity.py is a standalone reimplementation of the
# managed-block identity rules -- destination repos have no scripts/raven_lib
# to import. That makes the normalization and both hash algorithms exist twice,
# and a fix applied to only one copy fails silently: the library would call a
# block clean while the hook blocks the commit, or worse, the reverse.
#
# Same shape as the Codex launcher guard (#129): a pure comparison function,
# proven against deliberately drifted stubs so a green result means something.

hook = load_script_module("check_managed_block_integrity", SCRIPT_PATH)

NORMALIZATION_PARITY_INPUTS = (
    "",
    "\n\n\n",
    "# Guidance\n",
    "# Guidance   \n- item\t\n",
    "# Guidance\r\n- item\r\n",
    "# Guidance\r- item\r",
    "\n\n# Guidance\n\n\n- item\n\n\n",
    _TABLE_SOURCE,
    "| Need | First tool |\n| --- | --- |\n| Exact string | `rg` |\n",
    "| Need | First tool |\n| ---------- | ------------------ |\n",
    "|:---|---:|:---:|\n",
    "|:-------|-------:|\n",
    "| not | a | separator |\n",
    "|--|\n",
    "Use targeted retrieval.\n",
    "Use targeted\nretrieval.\n",
    "- alpha\n- beta\n",
    "- alpha - beta\n",
    "Require safe mode.\n",
    "Require safemode.\n",
    "  indented | --- | line\n",
    "trailing pipe missing | --- \n",
    "| Need         | First tool |\n| ------------ | ---------- |\n| Exact | `rg`  |\n",
    "|a|b|\n",
    "|   a   |   b   |\n",
    "| a b |\n",
    "| a  b |\n",
    "||\n",
    "| |\n",
    "|\n",
    "Run `rg foo |  wc -l` to count.\n",
    "Match `^(alpha|beta)$`  carefully.\n",
    "| leading pipe only, no trailing\n",
    "no leading pipe, trailing only |\n",
)


def find_normalization_drift(normalize, block_sha, legacy_sha) -> list[str]:
    """Compare a hook-side implementation triple against the library's.

    Pure and callable with stubs, which is what lets the tests below prove the
    guard actually fails on divergence rather than only ever seeing agreement.
    Returns human-readable problem strings; empty means no drift.
    """
    problems: list[str] = []
    for text in NORMALIZATION_PARITY_INPUTS:
        expected_normalized = raven.blocks.identity_block_content(text)
        if normalize(text) != expected_normalized:
            problems.append(
                f"identity normalization differs for {text!r}: "
                f"hook={normalize(text)!r} library={expected_normalized!r}"
            )
        expected_sha = raven.raven_block_sha256(text)
        if block_sha(text) != expected_sha:
            problems.append(f"current block sha differs for {text!r}")
        expected_legacy = raven.blocks.legacy_raven_block_sha256(text)
        if legacy_sha(text) != expected_legacy:
            problems.append(f"legacy block sha differs for {text!r}")
    return problems


class HookLibraryNormalizationParityTests(unittest.TestCase):
    def test_hook_matches_library(self):
        problems = find_normalization_drift(
            hook._identity_block_content, hook._block_sha256, hook._legacy_block_sha256
        )
        self.assertEqual(problems, [])

    def test_guard_detects_normalization_drift(self):
        # A hook that forgot all table folding -- the original #118 bug.
        problems = find_normalization_drift(
            hook._normalized_block_content, hook._block_sha256, hook._legacy_block_sha256
        )
        self.assertTrue(
            any("identity normalization differs" in p for p in problems),
            problems,
        )

    def test_guard_detects_partial_normalization_drift(self):
        # The subtler regression: separator folding kept, cell-padding folding
        # dropped. This is what the hook looked like mid-fix, and a guard that
        # only caught the all-or-nothing case would have waved it through.
        def separator_only(text: str) -> str:
            lines = []
            for line in hook._normalized_block_content(text).split("\n"):
                folded = hook._normalize_markdown_table_separator(line)
                lines.append(folded if folded is not None else line)
            return "\n".join(lines)

        problems = find_normalization_drift(
            separator_only, hook._block_sha256, hook._legacy_block_sha256
        )
        self.assertTrue(
            any("identity normalization differs" in p for p in problems),
            problems,
        )

    def test_guard_detects_current_sha_drift(self):
        # A hook still hashing the legacy normalization.
        problems = find_normalization_drift(
            hook._identity_block_content, hook._legacy_block_sha256, hook._legacy_block_sha256
        )
        self.assertTrue(any("current block sha differs" in p for p in problems), problems)

    def test_guard_detects_legacy_sha_drift(self):
        problems = find_normalization_drift(
            hook._identity_block_content, hook._block_sha256, hook._block_sha256
        )
        self.assertTrue(any("legacy block sha differs" in p for p in problems), problems)

    def test_parity_inputs_actually_exercise_the_difference(self):
        # Guards the fixture set: if no input distinguished the two algorithms,
        # every drift test above would pass vacuously.
        self.assertTrue(
            any(
                raven.blocks.legacy_raven_block_sha256(text) != raven.raven_block_sha256(text)
                for text in NORMALIZATION_PARITY_INPUTS
            )
        )

    def test_installed_hook_matches_canonical_source(self):
        # Upgrade regenerates the installed copy, but the manual-merge safety
        # net leaves a locally modified installed file alone, so a hand-edit
        # there could drift permanently without tripping self-check.
        self.assertEqual(
            INSTALLED_SCRIPT_PATH.read_text(encoding="utf-8"),
            SCRIPT_PATH.read_text(encoding="utf-8"),
        )


if __name__ == "__main__":
    unittest.main()
