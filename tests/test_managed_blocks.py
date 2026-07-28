import hashlib
import tempfile
import unittest
from pathlib import Path

from helpers import RavenTestCase, raven

# Table with a *compact* separator row, the style raven's own templates use.
# Only the separator line is restyled in these tests: padding the header or
# body cells is a different (still "upgradeable") case, pinned by
# ManagedBlocksTests.test_markdown_table_formatting_in_agents_block_is_repairable.
_TABLE_SOURCE = "# RAVEN guidance\n\n| Need | First tool |\n|---|---|\n| Exact string | `rg` |\n"
_COMPACT_SEPARATOR = "|---|---|"
_PADDED_SEPARATOR = "| --- | --- |"


def _legacy_managed_block(content: str) -> str:
    """Build a managed block carrying the *pre-#118* declared sha256.

    The old algorithm is transcribed here rather than imported so this stays a
    fixture of what destination repos already have on disk, and so a change to
    ``legacy_raven_block_sha256`` shows up as a test failure instead of being
    silently mirrored.
    """
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


class ManagedBlocksTests(RavenTestCase):
    def test_applied_agents_block_can_be_safely_upgraded_without_touching_local_content(self):
        old_source = self.destination / "old" / "AGENTS.md"
        new_source = self.destination / "new" / "AGENTS.md"
        old_source.parent.mkdir()
        new_source.parent.mkdir()
        old_source.write_text("# Old RAVEN guidance\n", encoding="utf-8")
        new_source.write_text("# New RAVEN guidance\n", encoding="utf-8")
        old_entry = raven.TemplateEntry("AGENTS.md", old_source)
        new_entry = raven.TemplateEntry("AGENTS.md", new_source)
        target = self.destination / "AGENTS.md"
        target.write_text(
            "# Local guidance before\n"
            + raven.raven_managed_block(old_entry.source.read_text(encoding="utf-8"))
            + "\n# Local guidance after\n",
            encoding="utf-8",
        )

        classification = raven.classify(
            self.template,
            self.destination,
            self.excludes,
            entries={"AGENTS.md": new_entry},
        )
        raven.copy_paths(
            self.template,
            self.destination,
            ["AGENTS.md"],
            entries={"AGENTS.md": new_entry},
            update_managed_blocks=True,
        )

        updated = target.read_text(encoding="utf-8")
        self.assertIn("AGENTS.md", classification.will_upgrade)
        self.assertIn("# Local guidance before", updated)
        self.assertIn("# New RAVEN guidance", updated)
        self.assertNotIn("# Old RAVEN guidance", updated)
        self.assertIn("# Local guidance after", updated)

    def test_modified_agents_block_requires_merge_instead_of_upgrade(self):
        source = self.destination / "source" / "AGENTS.md"
        source.parent.mkdir()
        source.write_text("# RAVEN guidance\n", encoding="utf-8")
        target = self.destination / "AGENTS.md"
        target.write_text(
            raven.raven_managed_block(source.read_text(encoding="utf-8")).replace(
                "# RAVEN guidance", "# Locally edited RAVEN guidance"
            ),
            encoding="utf-8",
        )

        classification = raven.classify(
            self.template,
            self.destination,
            self.excludes,
            entries={"AGENTS.md": raven.TemplateEntry("AGENTS.md", source)},
        )

        self.assertIn("AGENTS.md", classification.needs_merge)
        self.assertNotIn("AGENTS.md", classification.will_upgrade)

    def test_whitespace_only_agents_block_formatting_is_repairable(self):
        source = self.destination / "source" / "AGENTS.md"
        source.parent.mkdir()
        source.write_text(
            "# RAVEN guidance\n\n- Use targeted retrieval before reading files.\n", encoding="utf-8"
        )
        target = self.destination / "AGENTS.md"
        formatted = raven.raven_managed_block(source.read_text(encoding="utf-8"))
        formatted = formatted.replace("# RAVEN guidance", "# RAVEN guidance   ")
        formatted = formatted.replace(
            "targeted retrieval before reading files", "targeted retrieval before\nreading files"
        )
        target.write_text("# Local guidance\n" + formatted + "\n", encoding="utf-8")

        classification = raven.classify(
            self.template,
            self.destination,
            self.excludes,
            entries={"AGENTS.md": raven.TemplateEntry("AGENTS.md", source)},
        )
        raven.copy_paths(
            self.template,
            self.destination,
            ["AGENTS.md"],
            entries={"AGENTS.md": raven.TemplateEntry("AGENTS.md", source)},
            update_managed_blocks=True,
        )

        block = raven.find_raven_block(target.read_text(encoding="utf-8"))
        self.assertIn("AGENTS.md", classification.will_upgrade)
        self.assertNotIn("AGENTS.md", classification.needs_merge)
        self.assertIsNotNone(block)
        assert block is not None  # narrow Optional for the type checker
        self.assertTrue(raven.raven_block_is_unchanged(block))
        self.assertIn(
            "- Use targeted retrieval before reading files.", target.read_text(encoding="utf-8")
        )

    def test_markdown_table_formatting_in_agents_block_is_not_upgrade_noise(self):
        """Issue #118 — a prettier-formatted table block is the same block.

        Was ``test_markdown_table_formatting_in_agents_block_is_repairable``,
        which asserted this restyle classifies "will upgrade" and gets repaired
        back to the template's compact style on every run. That *is* the
        behavior #118 exists to remove: the repo's own formatter re-pads the
        table immediately afterwards, so the repair never converges and
        `upgrade --dry-run` never goes quiet. The block is not damaged and
        needs no repair; it must classify "identical" and be left alone.

        What survives from the original: it is never ``needs_merge``, and the
        block still reads as unchanged.
        """
        source = self.destination / "source" / "AGENTS.md"
        source.parent.mkdir()
        source.write_text(
            "# RAVEN guidance\n\n| Need | First tool |\n|---|---|\n| Exact string | `rg` |\n",
            encoding="utf-8",
        )
        target = self.destination / "AGENTS.md"
        # A full prettier-style pass: padded separator *and* padded cells in
        # every row, not just the separator line.
        formatted = raven.raven_managed_block(source.read_text(encoding="utf-8"))
        formatted = formatted.replace("|---|---|", "| ---------------- | ---------- |")
        formatted = formatted.replace("| Need | First tool |", "| Need         | First tool |")
        formatted = formatted.replace("| Exact string | `rg` |", "| Exact string | `rg`       |")
        target.write_text("# Local guidance\n" + formatted + "\n", encoding="utf-8")
        before = target.read_text(encoding="utf-8")

        classification = raven.classify(
            self.template,
            self.destination,
            self.excludes,
            entries={"AGENTS.md": raven.TemplateEntry("AGENTS.md", source)},
        )
        raven.copy_paths(
            self.template,
            self.destination,
            classification.will_upgrade,
            entries={"AGENTS.md": raven.TemplateEntry("AGENTS.md", source)},
            update_managed_blocks=True,
        )

        block = raven.find_raven_block(target.read_text(encoding="utf-8"))
        self.assertIn("AGENTS.md", classification.identical)
        self.assertNotIn("AGENTS.md", classification.will_upgrade)
        self.assertNotIn("AGENTS.md", classification.needs_merge)
        self.assertIsNotNone(block)
        assert block is not None  # narrow Optional for the type checker
        self.assertTrue(raven.raven_block_is_unchanged(block))
        # No repair churn: an upgrade run leaves the formatter's bytes in place.
        self.assertEqual(target.read_text(encoding="utf-8"), before)

    def test_table_cell_content_edit_in_agents_block_is_still_caught(self):
        """The counterpart guard: cell *padding* is styling, cell *text* is not."""
        source = self.destination / "source" / "AGENTS.md"
        source.parent.mkdir()
        source.write_text(
            "# RAVEN guidance\n\n| Need | First tool |\n|---|---|\n| Exact string | `rg` |\n",
            encoding="utf-8",
        )
        target = self.destination / "AGENTS.md"
        edited = raven.raven_managed_block(source.read_text(encoding="utf-8"))
        edited = edited.replace("| Exact string | `rg` |", "| Exact string  |  `fd` |")
        target.write_text("# Local guidance\n" + edited + "\n", encoding="utf-8")

        classification = raven.classify(
            self.template,
            self.destination,
            self.excludes,
            entries={"AGENTS.md": raven.TemplateEntry("AGENTS.md", source)},
        )

        self.assertIn("AGENTS.md", classification.needs_merge)
        self.assertNotIn("AGENTS.md", classification.identical)

    def test_matching_agents_block_with_bad_hash_is_repairable(self):
        source = self.destination / "source" / "AGENTS.md"
        source.parent.mkdir()
        source.write_text("# RAVEN guidance\n", encoding="utf-8")
        target = self.destination / "AGENTS.md"
        target.write_text(
            "# Local guidance\n"
            "<!-- RAVEN:BEGIN sha256=0000000000000000000000000000000000000000000000000000000000000000 -->\n"
            "# RAVEN guidance\n"
            "<!-- RAVEN:END -->\n",
            encoding="utf-8",
        )

        classification = raven.classify(
            self.template,
            self.destination,
            self.excludes,
            entries={"AGENTS.md": raven.TemplateEntry("AGENTS.md", source)},
        )
        raven.copy_paths(
            self.template,
            self.destination,
            ["AGENTS.md"],
            entries={"AGENTS.md": raven.TemplateEntry("AGENTS.md", source)},
            update_managed_blocks=True,
        )

        block = raven.find_raven_block(target.read_text(encoding="utf-8"))
        self.assertIn("AGENTS.md", classification.will_upgrade)
        self.assertNotIn("AGENTS.md", classification.needs_merge)
        self.assertIsNotNone(block)
        assert block is not None  # narrow Optional for the type checker
        self.assertTrue(raven.raven_block_is_unchanged(block))

    def test_matching_agents_block_without_hash_is_repairable(self):
        source = self.destination / "source" / "AGENTS.md"
        source.parent.mkdir()
        source.write_text("# RAVEN guidance\n", encoding="utf-8")
        target = self.destination / "AGENTS.md"
        target.write_text(
            "# Local guidance\n<!-- RAVEN:BEGIN -->\n# RAVEN guidance\n<!-- RAVEN:END -->\n",
            encoding="utf-8",
        )

        classification = raven.classify(
            self.template,
            self.destination,
            self.excludes,
            entries={"AGENTS.md": raven.TemplateEntry("AGENTS.md", source)},
        )

        self.assertIn("AGENTS.md", classification.will_upgrade)
        self.assertNotIn("AGENTS.md", classification.needs_merge)


class TokenBoundaryTests(unittest.TestCase):
    """Issue #26 — whitespace normalization must not collapse token boundaries."""

    def _make_block(self, content: str) -> str:
        return raven.raven_managed_block(content)

    def test_safe_mode_space_versus_safemode_are_different(self):
        with_space = self._make_block("Require safe mode.\n")
        without_space = self._make_block("Require safemode.\n")

        self.assertFalse(raven.block_content_matches(with_space, without_space))

    def test_prose_token_split_across_lines_is_still_different(self):
        one_line = self._make_block("Use targeted retrieval.\n")
        split = self._make_block("Use targeted\nretrieval.\n")

        self.assertFalse(raven.block_content_matches(one_line, split))

    def test_trailing_spaces_and_blank_lines_are_still_upgradeable(self):
        original = self._make_block("# RAVEN guidance\n\n- Use targeted retrieval.\n")
        with_trailing = original.replace("# RAVEN guidance", "# RAVEN guidance   ")

        self.assertTrue(raven.block_content_matches(original, with_trailing))

    def test_token_boundary_edit_classified_as_modified_not_upgradeable(self):
        source_path = Path(tempfile.mkdtemp()) / "AGENTS.md"
        source_path.write_text("Require safe mode.\n", encoding="utf-8")
        entry = raven.TemplateEntry("AGENTS.md", source_path)

        target_path = source_path.parent / "dest" / "AGENTS.md"
        target_path.parent.mkdir()
        edited_block = raven.raven_managed_block("Require safe mode.\n").replace(
            "safe mode", "safemode"
        )
        target_path.write_text(edited_block, encoding="utf-8")

        state = raven.block_managed_state(entry, target_path)
        self.assertEqual(state, "modified")

    def test_non_utf8_destination_file_does_not_crash_block_managed_state(self):
        source_path = Path(tempfile.mkdtemp()) / "AGENTS.md"
        source_path.write_text("# RAVEN guidance\n", encoding="utf-8")
        entry = raven.TemplateEntry("AGENTS.md", source_path)

        target_path = source_path.parent / "dest" / "AGENTS.md"
        target_path.parent.mkdir()
        target_path.write_bytes(b"# Local guidance\n\xff\xfe binary byte\n")

        state = raven.block_managed_state(entry, target_path)
        self.assertIsNone(state)


class TableRestyleIdentityTests(RavenTestCase):
    """Issue #118 — a formatter's table restyle must not read as drift.

    The declared sha256 is the block's *identity*. Before #118 it hashed a
    rstrip-only normalization while ``block_content_matches`` folded markdown
    table separators, so a restyled-but-equivalent block was simultaneously
    "the same block" and "a different block": permanent `will upgrade` noise,
    a block that read as hand-edited, and a blocked commit.
    """

    def _entry_and_target(self, source_text: str, block_text: str):
        source = self.destination / "source" / "AGENTS.md"
        source.parent.mkdir(exist_ok=True)
        source.write_text(source_text, encoding="utf-8")
        target = self.destination / "AGENTS.md"
        target.write_text("# Local guidance\n" + block_text + "\n", encoding="utf-8")
        return raven.TemplateEntry("AGENTS.md", source), target

    def test_table_separator_restyle_classifies_identical(self):
        restyled = raven.raven_managed_block(_TABLE_SOURCE).replace(
            _COMPACT_SEPARATOR, _PADDED_SEPARATOR
        )
        entry, target = self._entry_and_target(_TABLE_SOURCE, restyled)

        self.assertEqual(raven.block_managed_state(entry, target), "identical")

    def test_table_separator_restyle_reads_as_unchanged(self):
        restyled = raven.raven_managed_block(_TABLE_SOURCE).replace(
            _COMPACT_SEPARATOR, _PADDED_SEPARATOR
        )
        block = raven.find_raven_block(restyled)
        assert block is not None  # narrow Optional for the type checker

        self.assertTrue(raven.raven_block_is_unchanged(block))

    def test_prose_edit_inside_restyled_table_block_is_still_modified(self):
        tampered = (
            raven.raven_managed_block(_TABLE_SOURCE)
            .replace(_COMPACT_SEPARATOR, _PADDED_SEPARATOR)
            .replace("# RAVEN guidance", "# RAVEN guidance (hand-edited)")
        )
        entry, target = self._entry_and_target(_TABLE_SOURCE, tampered)
        block = raven.find_raven_block(tampered)
        assert block is not None  # narrow Optional for the type checker

        self.assertFalse(raven.raven_block_is_unchanged(block))
        self.assertEqual(raven.block_managed_state(entry, target), "modified")


class LegacyBlockShaMigrationTests(RavenTestCase):
    """Issue #118 — blocks already written downstream must survive the change.

    ``PADDED_TABLE_SOURCE`` is a template whose own separator row is padded, so
    the legacy hash and the current hash genuinely differ for it. That is the
    only shape that needs a migrating rewrite; a compact-separator template
    (raven's own AGENTS.md included) hashes the same under both algorithms.
    """

    PADDED_TABLE_SOURCE = (
        "# RAVEN guidance\n\n| Need | First tool |\n| --- | --- |\n| Exact string | `rg` |\n"
    )

    def _entry_and_target(self, source_text: str, block_text: str):
        source = self.destination / "source" / "AGENTS.md"
        source.parent.mkdir(exist_ok=True)
        source.write_text(source_text, encoding="utf-8")
        target = self.destination / "AGENTS.md"
        target.write_text("# Local guidance\n" + block_text + "\n# After\n", encoding="utf-8")
        return raven.TemplateEntry("AGENTS.md", source), target

    def test_legacy_and_current_sha_differ_for_this_fixture(self):
        # Guards the fixture itself: if these ever coincide, the migration
        # tests below would pass vacuously.
        content = raven.normalized_block_content(self.PADDED_TABLE_SOURCE)
        self.assertNotEqual(
            raven.blocks.legacy_raven_block_sha256(content),
            raven.raven_block_sha256(content),
        )

    def test_untouched_legacy_block_still_reads_as_unchanged(self):
        block = raven.find_raven_block(_legacy_managed_block(self.PADDED_TABLE_SOURCE))
        assert block is not None  # narrow Optional for the type checker

        self.assertTrue(raven.raven_block_is_unchanged(block))

    def _upgrade_cycle(self, entries: dict) -> list[str]:
        """One `raven upgrade` round: classify, then copy only what it flagged."""
        classification = raven.classify(
            self.template, self.destination, self.excludes, entries=entries
        )
        raven.copy_paths(
            self.template,
            self.destination,
            classification.will_upgrade,
            entries=entries,
            update_managed_blocks=True,
        )
        return classification.will_upgrade

    def test_legacy_block_migrates_once_then_stays_identical(self):
        entry, target = self._entry_and_target(
            self.PADDED_TABLE_SOURCE, _legacy_managed_block(self.PADDED_TABLE_SOURCE)
        )
        entries = {"AGENTS.md": entry}

        self.assertEqual(raven.block_managed_state(entry, target), "upgradeable")
        self.assertIn("AGENTS.md", self._upgrade_cycle(entries))
        migrated = target.read_text(encoding="utf-8")

        self.assertEqual(raven.block_managed_state(entry, target), "identical")
        self.assertIn("# Local guidance", migrated)
        self.assertIn("# After", migrated)

        # A second upgrade must be a no-op: a migration that re-triggers every
        # run is the same permanent-noise bug in a new costume.
        self.assertNotIn("AGENTS.md", self._upgrade_cycle(entries))
        self.assertEqual(target.read_text(encoding="utf-8"), migrated)
        self.assertEqual(raven.block_managed_state(entry, target), "identical")

    def test_restyled_legacy_block_self_heals_in_one_upgrade(self):
        # Documented residual gap: a legacy-sha block a formatter has already
        # restyled matches neither hash, so it reads as tampered until the next
        # upgrade. Pin that it does in fact heal, and heals only once.
        restyled = _legacy_managed_block(self.PADDED_TABLE_SOURCE).replace(
            "| --- | --- |", "| ------ | ---------- |"
        )
        entry, target = self._entry_and_target(self.PADDED_TABLE_SOURCE, restyled)
        entries = {"AGENTS.md": entry}
        block = raven.find_raven_block(restyled)
        assert block is not None  # narrow Optional for the type checker

        self.assertFalse(raven.raven_block_is_unchanged(block))
        self.assertEqual(raven.block_managed_state(entry, target), "upgradeable")

        self.assertIn("AGENTS.md", self._upgrade_cycle(entries))
        self.assertEqual(raven.block_managed_state(entry, target), "identical")
        self.assertNotIn("AGENTS.md", self._upgrade_cycle(entries))

    def test_legacy_block_with_prose_edit_is_still_modified(self):
        tampered = _legacy_managed_block(self.PADDED_TABLE_SOURCE).replace(
            "# RAVEN guidance", "# RAVEN guidance (hand-edited)"
        )
        entry, target = self._entry_and_target(self.PADDED_TABLE_SOURCE, tampered)

        self.assertEqual(raven.block_managed_state(entry, target), "modified")


class IdentityNormalizationTests(unittest.TestCase):
    """The four properties the identity normalization must hold at once."""

    def _identity(self, text: str) -> str:
        return raven.blocks.identity_block_content(text)

    def test_table_separator_style_is_invariant(self):
        self.assertEqual(
            self._identity("| a | b |\n|---|---|\n| 1 | 2 |\n"),
            self._identity("| a | b |\n| --- | ------------ |\n| 1 | 2 |\n"),
        )

    def test_table_separator_alignment_colons_are_preserved(self):
        # Alignment is meaning, not styling: `:---:` must not fold into `---`.
        self.assertNotEqual(self._identity("|:---:|---|"), self._identity("|---|---|"))

    def test_table_cell_padding_is_invariant(self):
        self.assertEqual(
            self._identity("| Need | First tool |\n|---|---|\n| Exact string | `rg` |\n"),
            self._identity(
                "| Need         | First tool |\n"
                "| ------------ | ---------- |\n"
                "| Exact string | `rg`       |\n"
            ),
        )
        self.assertEqual(self._identity("|a|b|"), self._identity("|   a   |   b   |"))

    def test_whitespace_inside_a_table_cell_is_significant(self):
        # Cells are stripped, never collapsed: only padding adjacent to a
        # delimiter is styling. An internal token boundary still counts.
        self.assertNotEqual(self._identity("| a b |"), self._identity("| a  b |"))
        self.assertNotEqual(self._identity("| safe mode |"), self._identity("| safemode |"))

    def test_table_cell_text_edits_are_still_visible(self):
        self.assertNotEqual(self._identity("| a | b |"), self._identity("| a | c |"))
        self.assertNotEqual(self._identity("| a | b |"), self._identity("| a | b | c |"))

    def test_prose_containing_a_pipe_is_not_treated_as_a_table_row(self):
        # A line is a table row only when its stripped form both begins and
        # ends with `|`. Prose that merely contains a pipe -- a shell pipeline
        # in a code span, a regex alternation -- must keep its exact spacing.
        for prose in (
            "Run `rg foo |  wc -l` to count.",
            "Match `^(alpha|beta)$`  carefully.",
            "| leading pipe only, no trailing",
            "no leading pipe, trailing only |",
            "|",
        ):
            with self.subTest(prose=prose):
                self.assertEqual(self._identity(prose), prose)

    def test_pipe_prose_spacing_change_is_still_a_difference(self):
        self.assertNotEqual(
            self._identity("Run `rg foo |  wc -l` to count."),
            self._identity("Run `rg foo | wc -l` to count."),
        )

    def test_trailing_whitespace_is_invariant(self):
        self.assertEqual(
            self._identity("# Heading   \n- item\t\n"), self._identity("# Heading\n- item\n")
        )

    def test_newlines_are_preserved(self):
        self.assertNotEqual(
            self._identity("Use targeted\nretrieval."), self._identity("Use targeted retrieval.")
        )

    def test_separate_bullets_differ_from_one_joined_line(self):
        self.assertNotEqual(self._identity("- alpha\n- beta"), self._identity("- alpha - beta"))

    def test_comparison_block_content_keeps_its_permissive_behavior(self):
        # comparison_block_content is deliberately *not* the identity function:
        # it still collapses newlines, which is why it cannot be hashed.
        self.assertEqual(
            raven.comparison_block_content("- alpha\n- beta"),
            raven.comparison_block_content("- alpha - beta"),
        )


class ClassifyNonUtf8Tests(RavenTestCase):
    def test_non_utf8_agents_md_is_classified_instead_of_crashing(self):
        source = self.destination / "source" / "AGENTS.md"
        source.parent.mkdir()
        source.write_text("# RAVEN guidance\n", encoding="utf-8")
        target = self.destination / "AGENTS.md"
        target.write_bytes(b"# Local guidance\n\xff\xfe binary byte\n")

        classification = raven.classify(
            self.template,
            self.destination,
            self.excludes,
            entries={"AGENTS.md": raven.TemplateEntry("AGENTS.md", source)},
        )

        self.assertIn("AGENTS.md", classification.unknown_existing)


class SymlinkSafetyTests(RavenTestCase):
    """Issue #27 — writes must not follow destination symlinks outside the tree."""

    def _make_entry(self, name: str, content: str) -> raven.TemplateEntry:
        # Use a temp subdirectory, not self.template, to avoid polluting the real template tree.
        src = self.destination / "_src" / name
        src.parent.mkdir(parents=True, exist_ok=True)
        src.write_text(content, encoding="utf-8")
        return raven.TemplateEntry(name, src)

    def test_regular_copy_replaces_destination_symlink(self):
        external = self.destination / "external.txt"
        external.write_text("original\n", encoding="utf-8")
        target = self.destination / "owned.txt"
        target.symlink_to(external)

        entry = self._make_entry("owned.txt", "raven content\n")
        raven.copy_paths(
            self.template, self.destination, ["owned.txt"], entries={"owned.txt": entry}
        )

        self.assertFalse(target.is_symlink(), "symlink should have been replaced")
        self.assertEqual(target.read_text(encoding="utf-8"), "raven content\n")
        self.assertEqual(external.read_text(encoding="utf-8"), "original\n")

    def test_managed_block_upgrade_replaces_destination_symlink(self):
        source = self.destination / "source" / "AGENTS.md"
        source.parent.mkdir()
        source.write_text("# RAVEN guidance\n", encoding="utf-8")
        entry = raven.TemplateEntry("AGENTS.md", source)

        external = self.destination / "external_agents.md"
        external_content = (
            "# Local\n" + raven.raven_managed_block(source.read_text(encoding="utf-8")) + "\n"
        )
        external.write_text(external_content, encoding="utf-8")

        target = self.destination / "AGENTS.md"
        target.symlink_to(external)

        raven.copy_paths(
            self.template,
            self.destination,
            ["AGENTS.md"],
            entries={"AGENTS.md": entry},
            update_managed_blocks=True,
        )

        self.assertFalse(target.is_symlink(), "symlink should have been replaced")
        self.assertEqual(external.read_text(encoding="utf-8"), external_content)


if __name__ == "__main__":
    unittest.main()
