import unittest

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


if __name__ == "__main__":
    unittest.main()
