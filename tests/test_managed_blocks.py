import tempfile
import unittest
from pathlib import Path

from helpers import RavenTestCase, raven


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

    def test_markdown_table_formatting_in_agents_block_is_repairable(self):
        source = self.destination / "source" / "AGENTS.md"
        source.parent.mkdir()
        source.write_text(
            "# RAVEN guidance\n\n| Need | First tool |\n|---|---|\n| Exact string | `rg` |\n",
            encoding="utf-8",
        )
        target = self.destination / "AGENTS.md"
        formatted = raven.raven_managed_block(source.read_text(encoding="utf-8"))
        formatted = formatted.replace("<!-- RAVEN:BEGIN", "<!-- RAVEN:BEGIN")
        formatted = formatted.replace("|---|---|", "| ---------------- | ---------- |")
        formatted = formatted.replace("| Need | First tool |", "| Need         | First tool |")
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
        self.assertIn("|---|---|", target.read_text(encoding="utf-8"))

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
