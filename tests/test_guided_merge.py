import contextlib
import io
import shutil
import subprocess
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

    def test_guided_merge_artifacts_for_modified_non_instruction_file(self):
        original = '{"mcpServers": {"local": "keep me"}}\n'
        (self.destination / ".mcp.json").write_text(original, encoding="utf-8")
        entries = raven.entries_for_destination(
            self.template,
            self.excludes,
            raven.load_config(self.destination),
            self.destination,
        )

        written = raven.write_guided_merge_artifacts(self.destination, entries, [".mcp.json"])

        # Raven never touches the user's file.
        self.assertEqual((self.destination / ".mcp.json").read_text(encoding="utf-8"), original)
        # Template copy + informational diff + instructions, but no appliable patch:
        # an append-only managed block would corrupt arbitrary JSON/TOML files.
        self.assertIn(".raven/merge/.mcp.json.raven", written)
        self.assertIn(".raven/merge/.mcp.json.diff", written)
        self.assertIn(".raven/merge/.mcp.json.instructions.md", written)
        self.assertNotIn(".raven/merge/.mcp.json.patch", written)
        diff = (self.destination / ".raven" / "merge" / ".mcp.json.diff").read_text(
            encoding="utf-8"
        )
        self.assertIn("keep me", diff)
        self.assertIn("@@", diff)
        instructions = (
            self.destination / ".raven" / "merge" / ".mcp.json.instructions.md"
        ).read_text(encoding="utf-8")
        self.assertIn(".raven/merge/.mcp.json.diff", instructions)
        self.assertNotIn("patch -p1", instructions)

    def test_guided_merge_artifacts_handle_non_utf8_existing_file(self):
        (self.destination / ".mcp.json").write_bytes(b'{"local": true}\n\xff\xfe binary byte')
        entries = raven.entries_for_destination(
            self.template,
            self.excludes,
            raven.load_config(self.destination),
            self.destination,
        )

        written = raven.write_guided_merge_artifacts(self.destination, entries, [".mcp.json"])

        self.assertIn(".raven/merge/.mcp.json.raven", written)
        self.assertIn(".raven/merge/.mcp.json.instructions.md", written)
        self.assertNotIn(".raven/merge/.mcp.json.diff", written)
        instructions = (
            self.destination / ".raven" / "merge" / ".mcp.json.instructions.md"
        ).read_text(encoding="utf-8")
        self.assertIn("could not generate an automatic text patch", instructions)

    def test_guided_merge_artifacts_handle_nested_paths(self):
        (self.destination / ".codex").mkdir()
        (self.destination / ".codex" / "config.toml").write_text("local = true\n", encoding="utf-8")
        entries = raven.entries_for_destination(
            self.template,
            self.excludes,
            raven.load_config(self.destination),
            self.destination,
        )

        written = raven.write_guided_merge_artifacts(
            self.destination, entries, [".codex/config.toml"]
        )

        self.assertIn(".raven/merge/.codex/config.toml.raven", written)
        self.assertIn(".raven/merge/.codex/config.toml.diff", written)
        self.assertTrue(
            (self.destination / ".raven" / "merge" / ".codex" / "config.toml.diff").is_file()
        )

    def test_unified_diff_text_shows_local_and_template(self):
        diff = raven.unified_diff_text("x.toml", "old = 1\n", "new = 2\n")

        self.assertIn("-old = 1", diff)
        self.assertIn("+new = 2", diff)
        self.assertIn("x.toml", diff)

    def test_instructions_with_diff_describe_manual_merge(self):
        body = raven.guided_merge_instructions(
            ".mcp.json", ".raven/merge/.mcp.json.raven", None, ".raven/merge/.mcp.json.diff"
        )

        self.assertIn("# Guided Raven merge for `.mcp.json`", body)
        self.assertIn(".raven/merge/.mcp.json.diff", body)
        self.assertIn("manually", body.lower())
        self.assertNotIn("patch -p1", body)
        self.assertNotIn("## Recommended automatic merge", body)

    def test_run_writes_merge_helpers_for_conflicting_non_instruction_file(self):
        (self.destination / ".mcp.json").write_text('{"local": true}\n', encoding="utf-8")
        output = io.StringIO()

        with contextlib.redirect_stdout(output):
            rc = raven._run(self.destination, "python", False, False, [])

        self.assertEqual(rc, 0)
        self.assertTrue((self.destination / ".raven" / "merge" / ".mcp.json.diff").is_file())
        self.assertIn("Wrote guided merge artifacts", output.getvalue())

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

    def test_instructions_with_patch_describe_automatic_merge(self):
        body = raven.guided_merge_instructions(
            "AGENTS.md", ".raven/merge/AGENTS.md.raven", ".raven/merge/AGENTS.md.patch"
        )
        self.assertIn("# Guided Raven merge for `AGENTS.md`", body)
        self.assertIn("patch --dry-run -p1 < .raven/merge/AGENTS.md.patch", body)
        self.assertIn("## Manual merge option", body)

    def test_instructions_without_patch_omit_patch_commands(self):
        body = raven.guided_merge_instructions("CLAUDE.md", ".raven/merge/CLAUDE.md.raven", None)
        self.assertIn("could not generate an automatic text patch", body)
        self.assertNotIn("patch --dry-run", body)
        self.assertNotIn("## Recommended automatic merge", body)

    def test_generated_agents_patch_marks_block_with_hash(self):
        raven_text = "# RAVEN guidance\n"

        patch = raven.append_patch_text("AGENTS.md", "# Existing\n", raven_text)

        self.assertIn("RAVEN:BEGIN sha256=", patch)
        self.assertIn("RAVEN:END", patch)

    def test_instructions_say_replace_when_block_exists(self):
        appended = raven.guided_merge_instructions(
            "AGENTS.md", ".raven/merge/AGENTS.md.raven", ".raven/merge/AGENTS.md.patch"
        )
        replaced = raven.guided_merge_instructions(
            "AGENTS.md",
            ".raven/merge/AGENTS.md.raven",
            ".raven/merge/AGENTS.md.patch",
            replaces_block=True,
        )
        self.assertIn("appends a `RAVEN:BEGIN`", appended)
        self.assertIn("replaces the existing `RAVEN:BEGIN`", replaced)
        self.assertNotIn("appends a `RAVEN:BEGIN`", replaced)

    def test_patch_for_file_without_block_appends(self):
        # No existing block: the patch appends one (an all-addition hunk).
        patch = raven.append_patch_text("AGENTS.md", "# Existing\n\nlocal\n", "# RAVEN\n")
        self.assertNotIn("\n-", patch)  # no deletion lines -> pure append
        self.assertIn("+<!-- RAVEN:BEGIN", patch)

    def test_patch_for_file_with_existing_block_replaces_not_appends(self):
        # #55: an instruction file that already has a RAVEN block must get a patch
        # that REPLACES that block, not one that appends a duplicate.
        existing = (
            "# Local guidance\n\nkeep me\n\n"
            "<!-- RAVEN:BEGIN sha256=" + "0" * 64 + " -->\n"
            "# AGENTS.md\n\nOld or edited guidance.\n"
            "<!-- RAVEN:END -->\n"
        )
        patch = raven.append_patch_text("AGENTS.md", existing, "# AGENTS.md\n\nNew guidance.\n")

        # A replace hunk deletes the old block markers and adds new ones.
        self.assertIn("-<!-- RAVEN:BEGIN", patch)
        self.assertIn("-<!-- RAVEN:END -->", patch)
        self.assertIn("+<!-- RAVEN:BEGIN", patch)

    def test_generated_replace_patch_applies_to_exactly_one_block(self):
        # End-to-end: applying the generated patch must leave exactly ONE managed
        # block (the #55 regression: the old code produced two).
        if shutil.which("patch") is None:
            self.skipTest("patch not installed")
        existing = (
            "# Local guidance\n\nkeep me\n\n"
            "<!-- RAVEN:BEGIN sha256=" + "0" * 64 + " -->\n"
            "# AGENTS.md\n\nOld guidance.\n"
            "<!-- RAVEN:END -->\n"
        )
        target = self.destination / "AGENTS.md"
        target.write_text(existing, encoding="utf-8")
        patch_text = raven.append_patch_text(
            "AGENTS.md", existing, "# AGENTS.md\n\nNew guidance.\n"
        )
        patch_file = self.destination / "block.patch"
        patch_file.write_text(patch_text, encoding="utf-8")

        result = subprocess.run(
            ["patch", "-p1", "-i", str(patch_file)],
            cwd=self.destination,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

        merged = target.read_text(encoding="utf-8")
        self.assertEqual(merged.count("<!-- RAVEN:BEGIN"), 1, merged)
        self.assertIn("New guidance.", merged)
        self.assertNotIn("Old guidance.", merged)
        self.assertIn("keep me", merged)  # local content preserved


if __name__ == "__main__":
    unittest.main()
