import contextlib
import io
import unittest

from helpers import RavenTestCase, raven


class GuidedMergeTests(RavenTestCase):
    def test_guided_merge_artifacts_do_not_modify_existing_agents(self):
        original = "# Existing AGENTS\n\nKeep this local guidance.\n"
        (self.destination / "AGENTS.md").write_text(original, encoding="utf-8")
        entries = raven.entries_for_destination(
            self.template,
            self.excludes,
            raven.load_config(self.destination),
            self.destination,
        )

        written = raven.write_guided_merge_artifacts(self.destination, entries, ["AGENTS.md"])

        self.assertEqual((self.destination / "AGENTS.md").read_text(encoding="utf-8"), original)
        self.assertIn(".raven/merge/AGENTS.md.raven", written)
        self.assertIn(".raven/merge/AGENTS.md.instructions.md", written)
        self.assertIn(".raven/merge/AGENTS.md.patch", written)
        self.assertTrue((self.destination / ".raven" / "merge" / "AGENTS.md.raven").is_file())
        self.assertIn(
            "RAVEN:BEGIN",
            (self.destination / ".raven" / "merge" / "AGENTS.md.patch").read_text(encoding="utf-8"),
        )
        instructions = (
            self.destination / ".raven" / "merge" / "AGENTS.md.instructions.md"
        ).read_text(encoding="utf-8")
        self.assertIn("patch --dry-run -p1 < .raven/merge/AGENTS.md.patch", instructions)
        self.assertIn("patch -p1 < .raven/merge/AGENTS.md.patch", instructions)
        self.assertIn("Future Raven upgrades can update that block automatically", instructions)

    def test_guided_merge_artifacts_for_existing_claude_symlink_template_do_not_modify_file(self):
        original = "# Existing CLAUDE\n\nKeep this local guidance.\n"
        (self.destination / "CLAUDE.md").write_text(original, encoding="utf-8")
        entries = raven.entries_for_destination(
            self.template,
            self.excludes,
            raven.load_config(self.destination),
            self.destination,
        )

        written = raven.write_guided_merge_artifacts(self.destination, entries, ["CLAUDE.md"])

        self.assertEqual((self.destination / "CLAUDE.md").read_text(encoding="utf-8"), original)
        self.assertIn(".raven/merge/CLAUDE.md.raven", written)
        self.assertIn(".raven/merge/CLAUDE.md.instructions.md", written)
        self.assertNotIn(".raven/merge/CLAUDE.md.patch", written)
        self.assertIn(
            "symlink",
            (self.destination / ".raven" / "merge" / "CLAUDE.md.raven").read_text(encoding="utf-8"),
        )

    def test_dry_run_does_not_write_guided_merge_artifacts(self):
        (self.destination / "AGENTS.md").write_text("# Existing\n", encoding="utf-8")
        output = io.StringIO()

        with contextlib.redirect_stdout(output):
            rc = raven._run(self.destination, "python", False, True, [])

        self.assertEqual(rc, 0)
        self.assertIn("Would write guided merge artifacts", output.getvalue())
        self.assertFalse((self.destination / ".raven" / "merge").exists())
        self.assertEqual(
            (self.destination / "AGENTS.md").read_text(encoding="utf-8"), "# Existing\n"
        )

    def test_generated_agents_patch_marks_block_with_hash(self):
        raven_text = "# RAVEN guidance\n"

        patch = raven.append_patch_text("AGENTS.md", "# Existing\n", raven_text)

        self.assertIn("RAVEN:BEGIN sha256=", patch)
        self.assertIn("RAVEN:END", patch)


if __name__ == "__main__":
    unittest.main()
