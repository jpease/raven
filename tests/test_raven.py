import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RAVEN_PATH = REPO_ROOT / "scripts" / "raven.py"


def load_raven():
    spec = importlib.util.spec_from_file_location("raven", RAVEN_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


raven = load_raven()


class RavenTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.destination = Path(self.tmp.name)
        self.template = REPO_ROOT / "python"
        self.excludes = {"README.md"}

    def test_classifies_missing_identical_and_unknown_existing_files(self):
        (self.destination / "AGENTS.md").write_text(
            (self.template / "AGENTS.md").read_text(), encoding="utf-8"
        )
        (self.destination / "CLAUDE.md").write_text("custom\n", encoding="utf-8")

        classification = raven.classify(
            self.template,
            self.destination,
            self.excludes,
        )

        self.assertIn(".claude/scripts/raven-tool-check.py", classification.will_copy)
        self.assertIn("AGENTS.md", classification.identical)
        self.assertIn("CLAUDE.md", classification.unknown_existing)
        self.assertEqual(classification.needs_merge, [])
        self.assertEqual(classification.excluded, ["README.md"])

    def test_apply_preserves_compatibility_symlinks(self):
        paths = [
            ".agents/skills/raven-tool-bootstrap/SKILL.md",
            ".claude/skills",
            "CLAUDE.md",
        ]

        raven.copy_paths(self.template, self.destination, paths)

        claude_skills = self.destination / ".claude" / "skills"
        claude_md = self.destination / "CLAUDE.md"

        self.assertTrue(
            (
                self.destination / ".agents" / "skills" / "raven-tool-bootstrap" / "SKILL.md"
            ).is_file()
        )
        self.assertTrue(claude_skills.is_symlink())
        self.assertEqual(os.readlink(claude_skills), "../.agents/skills")
        self.assertTrue((claude_skills / "raven-tool-bootstrap" / "SKILL.md").is_file())
        self.assertTrue(claude_md.is_symlink())
        self.assertEqual(os.readlink(claude_md), "AGENTS.md")

    def test_override_path_can_overwrite_one_changed_file(self):
        target = self.destination / ".claude" / "scripts" / "raven-tool-check.py"
        target.parent.mkdir(parents=True)
        target.write_text("custom\n", encoding="utf-8")

        raven.copy_paths(self.template, self.destination, [".claude/scripts/raven-tool-check.py"])

        self.assertEqual(
            target.read_text(encoding="utf-8"),
            (self.template / ".claude" / "scripts" / "raven-tool-check.py").read_text(
                encoding="utf-8"
            ),
        )

    def test_manifest_allows_upgrade_for_unchanged_managed_file(self):
        path = ".claude/scripts/raven-tool-check.py"
        raven.copy_paths(self.template, self.destination, [path])
        raven.update_manifest(
            self.destination,
            "python",
            self.template,
            self.excludes,
            raven.load_config(self.destination),
            [path],
        )

        target = self.destination / path
        target.write_text("old template content\n", encoding="utf-8")
        manifest = raven.load_manifest(self.destination)
        manifest["files"][path]["installedSha256"] = raven.file_sha256(target)
        raven.save_manifest(self.destination, manifest)

        classification = raven.classify(self.template, self.destination, self.excludes)

        self.assertIn(path, classification.will_upgrade)
        self.assertNotIn(path, classification.needs_merge)

    def test_manifest_requires_merge_for_locally_modified_managed_file(self):
        path = ".claude/scripts/raven-tool-check.py"
        raven.copy_paths(self.template, self.destination, [path])
        raven.update_manifest(
            self.destination,
            "python",
            self.template,
            self.excludes,
            raven.load_config(self.destination),
            [path],
        )

        target = self.destination / path
        target.write_text("local user edit\n", encoding="utf-8")

        classification = raven.classify(self.template, self.destination, self.excludes)

        self.assertIn(path, classification.needs_merge)
        self.assertNotIn(path, classification.will_upgrade)

    def test_update_manifest_records_file_hashes(self):
        path = ".claude/scripts/raven-tool-check.py"
        raven.copy_paths(self.template, self.destination, [path])
        raven.update_manifest(
            self.destination,
            "python",
            self.template,
            self.excludes,
            raven.load_config(self.destination),
            [path],
        )

        manifest_path = self.destination / ".raven" / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        self.assertEqual(manifest["schema"], 1)
        self.assertEqual(manifest["template"], "python")
        self.assertEqual(manifest["files"][path]["kind"], "file")
        self.assertEqual(
            manifest["files"][path]["installedSha256"],
            raven.file_sha256(self.destination / path),
        )

    def test_update_manifest_can_adopt_identical_existing_file(self):
        path = ".claude/scripts/raven-tool-check.py"
        raven.copy_paths(self.template, self.destination, [path])

        classification = raven.classify(self.template, self.destination, self.excludes)
        raven.update_manifest(
            self.destination,
            "python",
            self.template,
            self.excludes,
            raven.load_config(self.destination),
            classification.identical,
        )

        manifest = raven.load_manifest(self.destination)

        self.assertIn(path, manifest["files"])
        self.assertEqual(
            manifest["files"][path]["installedSha256"],
            raven.file_sha256(self.destination / path),
        )

    def test_config_can_disable_components_and_exclude_paths(self):
        config_path = self.destination / ".raven" / "config.toml"
        config_path.parent.mkdir()
        config_path.write_text(
            """
schema = 1
template = "python"

[components]
hooks = false
mcp = false

[exclude]
paths = [".claude/agents/raven-security-reviewer.md"]
""".strip()
            + "\n",
            encoding="utf-8",
        )

        config = raven.load_config(self.destination)
        entries = [
            entry.relative
            for entry in raven.iter_template_entries(self.template, self.excludes, config)
        ]

        self.assertNotIn(".mcp.json", entries)
        self.assertFalse(any(path.startswith(".claude/hooks/") for path in entries))
        self.assertNotIn(".claude/agents/raven-security-reviewer.md", entries)
        self.assertIn(".claude/agents/raven-test-debugger.md", entries)

    def test_starter_tool_configs_are_copied_when_missing(self):
        expected = {
            "python": ["pyproject.toml"],
            "typescript": ["eslint.config.mjs", "prettier.config.mjs"],
            "rust": ["rustfmt.toml"],
            "swift": [".swiftlint.yml"],
            "elixir": [".formatter.exs"],
        }

        for language, paths in expected.items():
            with self.subTest(language=language):
                template = REPO_ROOT / language
                entries = raven.entries_for_destination(
                    template,
                    self.excludes,
                    raven.load_config(self.destination),
                    self.destination,
                )
                classification = raven.classify(
                    template,
                    self.destination,
                    self.excludes,
                    raven.load_config(self.destination),
                    entries=entries,
                )

                for path in paths:
                    self.assertIn(path, classification.will_copy)

    def test_existing_starter_tool_config_is_skipped_without_merge(self):
        target = self.destination / "pyproject.toml"
        target.write_text("[project]\nname = \"local-project\"\n", encoding="utf-8")

        entries = raven.entries_for_destination(
            self.template,
            self.excludes,
            raven.load_config(self.destination),
            self.destination,
        )
        classification = raven.classify(
            self.template,
            self.destination,
            self.excludes,
            raven.load_config(self.destination),
            entries=entries,
        )

        self.assertNotIn("pyproject.toml", entries)
        self.assertNotIn("pyproject.toml", classification.will_copy)
        self.assertNotIn("pyproject.toml", classification.unknown_existing)
        self.assertEqual(
            target.read_text(encoding="utf-8"), "[project]\nname = \"local-project\"\n"
        )

    def test_config_can_disable_starter_tool_configs(self):
        config_path = self.destination / ".raven" / "config.toml"
        config_path.parent.mkdir()
        config_path.write_text(
            """
schema = 1
template = "python"

[components]
tool_configs = false
""".strip()
            + "\n",
            encoding="utf-8",
        )

        config = raven.load_config(self.destination)
        entries = [
            entry.relative
            for entry in raven.iter_template_entries(self.template, self.excludes, config)
        ]

        self.assertNotIn("pyproject.toml", entries)
        self.assertIn("justfile", entries)

    def test_existing_claude_skills_directory_gets_raven_skill_files(self):
        existing = self.destination / ".claude" / "skills" / "existing-skill"
        existing.mkdir(parents=True)
        (existing / "SKILL.md").write_text("existing\n", encoding="utf-8")

        entries = raven.entries_for_destination(
            self.template,
            self.excludes,
            raven.load_config(self.destination),
            self.destination,
        )
        classification = raven.classify(
            self.template,
            self.destination,
            self.excludes,
            raven.load_config(self.destination),
            entries=entries,
        )

        self.assertIn(".claude/skills/raven-tool-bootstrap/SKILL.md", classification.will_copy)
        self.assertNotIn(".claude/skills", classification.unknown_existing)

    def test_copy_into_existing_claude_skills_directory_preserves_existing_content(self):
        existing = self.destination / ".claude" / "skills" / "existing-skill"
        existing.mkdir(parents=True)
        (existing / "SKILL.md").write_text("existing\n", encoding="utf-8")
        entries = raven.entries_for_destination(
            self.template,
            self.excludes,
            raven.load_config(self.destination),
            self.destination,
        )
        path = ".claude/skills/raven-tool-bootstrap/SKILL.md"

        raven.copy_paths(
            self.template,
            self.destination,
            [path],
            raven.load_config(self.destination),
            entries=entries,
        )

        self.assertEqual((existing / "SKILL.md").read_text(encoding="utf-8"), "existing\n")
        self.assertTrue((self.destination / path).is_file())

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

    def test_adopt_claude_symlink_backs_up_existing_file_and_creates_symlink(self):
        (self.destination / "CLAUDE.md").write_text("custom claude guidance\n", encoding="utf-8")
        entries = raven.entries_for_destination(
            self.template,
            self.excludes,
            raven.load_config(self.destination),
            self.destination,
        )

        changed = raven.adopt_claude_symlink(self.destination, entries)

        self.assertEqual(changed, ["CLAUDE.md.bak", "CLAUDE.md"])
        self.assertEqual(
            (self.destination / "CLAUDE.md.bak").read_text(encoding="utf-8"),
            "custom claude guidance\n",
        )
        self.assertTrue((self.destination / "CLAUDE.md").is_symlink())
        self.assertEqual(os.readlink(self.destination / "CLAUDE.md"), "AGENTS.md")

    def test_adopt_claude_symlink_refuses_to_overwrite_existing_backup(self):
        (self.destination / "CLAUDE.md").write_text("custom claude guidance\n", encoding="utf-8")
        (self.destination / "CLAUDE.md.bak").write_text("existing backup\n", encoding="utf-8")
        entries = raven.entries_for_destination(
            self.template,
            self.excludes,
            raven.load_config(self.destination),
            self.destination,
        )

        with self.assertRaises(FileExistsError):
            raven.adopt_claude_symlink(self.destination, entries)

        self.assertEqual(
            (self.destination / "CLAUDE.md").read_text(encoding="utf-8"), "custom claude guidance\n"
        )
        self.assertEqual(
            (self.destination / "CLAUDE.md.bak").read_text(encoding="utf-8"), "existing backup\n"
        )

    def test_run_with_adopt_claude_symlink_does_not_report_claude_manual_merge(self):
        (self.destination / "AGENTS.md").write_text("# Existing AGENTS\n", encoding="utf-8")
        (self.destination / "CLAUDE.md").write_text("custom claude guidance\n", encoding="utf-8")
        output = io.StringIO()

        with contextlib.redirect_stdout(output):
            rc = raven._run(
                self.destination,
                "python",
                False,
                False,
                [],
                adopt_claude_symlink_requested=True,
                prompt_claude_symlink=False,
            )

        self.assertEqual(rc, 0)
        self.assertTrue((self.destination / "CLAUDE.md").is_symlink())
        self.assertEqual(
            (self.destination / "CLAUDE.md.bak").read_text(encoding="utf-8"),
            "custom claude guidance\n",
        )
        self.assertIn("Adopted CLAUDE.md compatibility symlink", output.getvalue())
        self.assertNotIn(
            "  CLAUDE.md\n", output.getvalue().split("Wrote guided merge artifacts", 1)[-1]
        )

    def test_run_with_adopt_claude_symlink_fails_if_backup_exists(self):
        (self.destination / "AGENTS.md").write_text("# Existing AGENTS\n", encoding="utf-8")
        (self.destination / "CLAUDE.md").write_text("custom claude guidance\n", encoding="utf-8")
        (self.destination / "CLAUDE.md.bak").write_text("existing backup\n", encoding="utf-8")
        output = io.StringIO()

        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            rc = raven._run(
                self.destination,
                "python",
                False,
                False,
                [],
                adopt_claude_symlink_requested=True,
                prompt_claude_symlink=False,
            )

        self.assertEqual(rc, 2)
        self.assertFalse((self.destination / "CLAUDE.md").is_symlink())
        self.assertEqual(
            (self.destination / "CLAUDE.md.bak").read_text(encoding="utf-8"), "existing backup\n"
        )
        self.assertIn("CLAUDE.md.bak already exists", output.getvalue())

    def test_dry_run_with_adopt_claude_symlink_reports_backup_without_writing(self):
        (self.destination / "AGENTS.md").write_text("# Existing AGENTS\n", encoding="utf-8")
        (self.destination / "CLAUDE.md").write_text("custom claude guidance\n", encoding="utf-8")
        output = io.StringIO()

        with contextlib.redirect_stdout(output):
            rc = raven._run(
                self.destination,
                "python",
                False,
                True,
                [],
                adopt_claude_symlink_requested=True,
                prompt_claude_symlink=False,
            )

        self.assertEqual(rc, 0)
        self.assertFalse((self.destination / "CLAUDE.md").is_symlink())
        self.assertFalse((self.destination / "CLAUDE.md.bak").exists())
        self.assertIn("Would adopt CLAUDE.md compatibility symlink", output.getvalue())

    def test_dry_run_with_adopt_claude_symlink_fails_if_backup_exists(self):
        (self.destination / "AGENTS.md").write_text("# Existing AGENTS\n", encoding="utf-8")
        (self.destination / "CLAUDE.md").write_text("custom claude guidance\n", encoding="utf-8")
        (self.destination / "CLAUDE.md.bak").write_text("existing backup\n", encoding="utf-8")
        output = io.StringIO()

        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            rc = raven._run(
                self.destination,
                "python",
                False,
                True,
                [],
                adopt_claude_symlink_requested=True,
                prompt_claude_symlink=False,
            )

        self.assertEqual(rc, 2)
        self.assertFalse((self.destination / "CLAUDE.md").is_symlink())
        self.assertEqual(
            (self.destination / "CLAUDE.md.bak").read_text(encoding="utf-8"), "existing backup\n"
        )
        self.assertIn("CLAUDE.md.bak already exists", output.getvalue())

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

    def test_default_config_is_self_documenting(self):
        text = raven.default_config_text("rust", False)

        self.assertIn('template = "rust"', text)
        self.assertIn("# Language template", text)
        self.assertIn("[components.claude]", text)
        self.assertIn("[components.codex]", text)
        self.assertIn("# Codex project config", text)
        self.assertIn("tool_configs = true", text)
        self.assertIn("[exclude]", text)

    def test_default_config_includes_lifecycle_section(self):
        config = raven.default_config_text("python", False)
        self.assertIn("[lifecycle]", config)
        self.assertIn("checkpoint_enforcement = true", config)

    def test_default_config_includes_issue_tracker_section(self):
        config = raven.default_config_text("python", False)
        self.assertIn("[issue_tracker]", config)
        self.assertIn('platform = "none"', config)

    def test_default_config_embeds_github_platform(self):
        config = raven.default_config_text("python", False, "github")
        self.assertIn('platform = "github"', config)
        # The comment block contains "# platform = "none""; check the active (uncommented) line.
        self.assertNotIn('\nplatform = "none"', config)

    def test_default_config_embeds_gitlab_platform(self):
        config = raven.default_config_text("python", False, "gitlab")
        self.assertIn('platform = "gitlab"', config)

    def test_update_config_platform_replaces_platform_value(self):
        config_path = self.destination / ".raven" / "config.toml"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(raven.default_config_text("python", False, "none"), encoding="utf-8")

        raven._update_config_platform(config_path, "github")

        text = config_path.read_text(encoding="utf-8")
        self.assertIn('platform = "github"', text)
        self.assertNotIn('\nplatform = "none"', text)

    def test_init_with_platform_writes_platform_to_config(self):
        import argparse

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            rc = raven.cmd_init(
                argparse.Namespace(
                    destination=str(self.destination), language="python", platform="github"
                )
            )
        self.assertEqual(rc, 0)
        text = (self.destination / ".raven" / "config.toml").read_text(encoding="utf-8")
        self.assertIn('platform = "github"', text)

    def test_install_platform_flag_updates_existing_config(self):
        import argparse

        (self.destination / ".raven").mkdir(parents=True, exist_ok=True)
        config_path = self.destination / ".raven" / "config.toml"
        config_path.write_text(raven.default_config_text("python", False, "none"), encoding="utf-8")
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            rc = raven.cmd_install(
                argparse.Namespace(
                    destination=str(self.destination),
                    language=None,
                    args=None,
                    overrides=[],
                    dry_run=False,
                    include_readme=False,
                    adopt_claude_symlink=False,
                    platform="github",
                )
            )
        self.assertEqual(rc, 0)
        self.assertIn('platform = "github"', config_path.read_text(encoding="utf-8"))

    def test_config_can_disable_agent_specific_components(self):
        config_path = self.destination / ".raven" / "config.toml"
        config_path.parent.mkdir()
        config_path.write_text(
            """
schema = 1
template = "python"

[components.claude]
settings = false
hooks = false
subagents = false
rules = false

[components.codex]
config = false
hooks = false
subagents = false
rules = false
""".strip()
            + "\n",
            encoding="utf-8",
        )

        config = raven.load_config(self.destination)
        entries = [
            entry.relative
            for entry in raven.iter_template_entries(self.template, self.excludes, config)
        ]

        self.assertNotIn(".claude/settings.json", entries)
        self.assertFalse(any(path.startswith(".claude/hooks/") for path in entries))
        self.assertFalse(any(path.startswith(".claude/scripts/") for path in entries))
        self.assertFalse(any(path.startswith(".claude/agents/") for path in entries))
        self.assertFalse(any(path.startswith(".claude/rules/") for path in entries))
        self.assertNotIn(".codex/config.toml", entries)
        self.assertNotIn(".codex/hooks.json", entries)
        self.assertFalse(any(path.startswith(".codex/hooks/") for path in entries))
        self.assertFalse(any(path.startswith(".codex/scripts/") for path in entries))
        self.assertFalse(any(path.startswith(".codex/agents/") for path in entries))
        self.assertFalse(any(path.startswith(".codex/rules/") for path in entries))
        self.assertIn(".agents/skills/raven-tool-bootstrap/SKILL.md", entries)

    def test_excludes_generated_files_anywhere(self):
        template = self.destination / "template"
        template.mkdir()
        (template / "keep.txt").write_text("keep\n", encoding="utf-8")
        (template / ".DS_Store").write_text("ignore\n", encoding="utf-8")
        cache = template / "pkg" / "__pycache__"
        cache.mkdir(parents=True)
        (cache / "ignored.pyc").write_text("ignore\n", encoding="utf-8")
        ruff_cache = template / ".ruff_cache"
        ruff_cache.mkdir()
        (ruff_cache / "ignored").write_text("ignore\n", encoding="utf-8")

        entries = raven.iter_template_entries(template, set())

        self.assertEqual([entry.relative for entry in entries], ["keep.txt"])

    def test_all_language_templates_install_and_upgrade_cleanly(self):
        languages = raven.list_language_templates()

        self.assertIn("python", languages)
        self.assertIn("swift", languages)
        self.assertIn("rust", languages)
        self.assertIn("typescript", languages)
        self.assertIn("elixir", languages)
        for language in languages:
            with self.subTest(language=language), tempfile.TemporaryDirectory() as tmp:
                destination = Path(tmp)
                install_output = io.StringIO()
                upgrade_output = io.StringIO()

                with contextlib.redirect_stdout(install_output):
                    install_rc = raven.cmd_install(
                        type(
                            "Args",
                            (),
                            {
                                "destination": str(destination),
                                "args": [language],
                                "include_readme": False,
                                "dry_run": False,
                                "adopt_claude_symlink": False,
                            },
                        )()
                    )
                with contextlib.redirect_stdout(upgrade_output):
                    upgrade_rc = raven.cmd_upgrade(
                        type(
                            "Args",
                            (),
                            {
                                "destination": str(destination),
                                "overrides": [],
                                "include_readme": False,
                                "dry_run": True,
                                "adopt_claude_symlink": False,
                            },
                        )()
                    )

                self.assertEqual(install_rc, 0, install_output.getvalue())
                self.assertEqual(upgrade_rc, 0, upgrade_output.getvalue())
                self.assertTrue((destination / "AGENTS.md").is_file())
                self.assertTrue((destination / "CLAUDE.md").is_symlink())
                self.assertEqual(os.readlink(destination / "CLAUDE.md"), "AGENTS.md")
                self.assertTrue((destination / ".claude" / "skills").is_symlink())
                self.assertEqual(
                    os.readlink(destination / ".claude" / "skills"), "../.agents/skills"
                )
                self.assertTrue((destination / ".codex" / "config.toml").is_file())
                self.assertTrue((destination / ".codex" / "hooks.json").is_file())
                self.assertTrue(
                    (destination / ".codex" / "agents" / "raven-security-reviewer.toml").is_file()
                )
                self.assertTrue((destination / ".codex" / "rules" / "raven.rules").is_file())
                self.assertIn("Already up to date", upgrade_output.getvalue())
                self.assertIn(
                    "Manual merge required; locally modified Raven-managed files:\n  (none)",
                    upgrade_output.getvalue(),
                )
                self.assertIn(
                    "Manual merge required; existing files not known to be Raven-managed:\n  (none)",
                    upgrade_output.getvalue(),
                )

    def test_templates_have_no_broken_symlinks(self):
        for language in raven.list_language_templates():
            template = REPO_ROOT / language
            with self.subTest(language=language):
                broken = []
                for current, dirnames, filenames in os.walk(template, followlinks=False):
                    for name in dirnames + filenames:
                        candidate = Path(current) / name
                        if candidate.is_symlink() and not candidate.exists():
                            broken.append(candidate.relative_to(template).as_posix())
                self.assertEqual(broken, [])

    def test_language_templates_define_specific_lsp_mcp_defaults(self):
        expected = {
            "python": ["--workspace", ".", "--lsp", "pyright-langserver", "--", "--stdio"],
            "typescript": [
                "--workspace",
                ".",
                "--lsp",
                "typescript-language-server",
                "--",
                "--stdio",
            ],
            "rust": ["--workspace", ".", "--lsp", "rust-analyzer"],
            "swift": ["--workspace", ".", "--lsp", "sourcekit-lsp"],
            "elixir": ["--workspace", ".", "--lsp", "expert"],
        }

        for language, args in expected.items():
            with self.subTest(language=language):
                config = json.loads(
                    (REPO_ROOT / language / ".mcp.json").read_text(encoding="utf-8")
                )
                lsp = config["mcpServers"]["lsp"]

                self.assertEqual(lsp["command"], "mcp-language-server")
                self.assertEqual(lsp["args"], args)

    def test_language_templates_define_specific_codex_lsp_mcp_defaults(self):
        expected = {
            "python": ["--workspace", ".", "--lsp", "pyright-langserver", "--", "--stdio"],
            "typescript": [
                "--workspace",
                ".",
                "--lsp",
                "typescript-language-server",
                "--",
                "--stdio",
            ],
            "rust": ["--workspace", ".", "--lsp", "rust-analyzer"],
            "swift": ["--workspace", ".", "--lsp", "sourcekit-lsp"],
            "elixir": ["--workspace", ".", "--lsp", "expert"],
        }

        for language, args in expected.items():
            with self.subTest(language=language):
                config = raven.parse_simple_toml(
                    (REPO_ROOT / language / ".codex" / "config.toml").read_text(encoding="utf-8")
                )
                lsp = config["mcp_servers.lsp"]

                self.assertEqual(lsp["command"], "mcp-language-server")
                self.assertEqual(lsp["args"], args)

    def test_conflict_fixture_preserves_existing_files_and_writes_guidance(self):
        (self.destination / "AGENTS.md").write_text("# Existing AGENTS\n", encoding="utf-8")
        (self.destination / "CLAUDE.md").write_text("# Existing CLAUDE\n", encoding="utf-8")
        existing_skill = self.destination / ".claude" / "skills" / "existing-skill"
        existing_skill.mkdir(parents=True)
        (existing_skill / "SKILL.md").write_text("existing skill\n", encoding="utf-8")
        output = io.StringIO()

        with contextlib.redirect_stdout(output):
            rc = raven._run(
                self.destination,
                "python",
                False,
                False,
                [],
                adopt_claude_symlink_requested=False,
                prompt_claude_symlink=False,
            )

        self.assertEqual(rc, 0, output.getvalue())
        self.assertEqual(
            (self.destination / "AGENTS.md").read_text(encoding="utf-8"), "# Existing AGENTS\n"
        )
        self.assertEqual(
            (self.destination / "CLAUDE.md").read_text(encoding="utf-8"), "# Existing CLAUDE\n"
        )
        self.assertEqual(
            (existing_skill / "SKILL.md").read_text(encoding="utf-8"), "existing skill\n"
        )
        self.assertTrue(
            (
                self.destination / ".claude" / "skills" / "raven-tool-bootstrap" / "SKILL.md"
            ).is_file()
        )
        self.assertTrue((self.destination / ".raven" / "merge" / "AGENTS.md.patch").is_file())
        self.assertTrue((self.destination / ".raven" / "merge" / "CLAUDE.md.raven").is_file())
        self.assertIn("Manual merge still required", output.getvalue())

    def test_self_check_script_exists_and_is_executable(self):
        script = REPO_ROOT / "scripts" / "self-check.py"

        self.assertTrue(script.is_file())
        self.assertTrue(os.access(script, os.X_OK))

    def test_raven_wrapper_exists_and_delegates_to_cli(self):
        script = REPO_ROOT / "scripts" / "raven"

        self.assertTrue(script.is_file())
        self.assertTrue(os.access(script, os.X_OK))
        result = subprocess.run(
            [str(script), "--help"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("Raven", result.stdout)
        self.assertIn("install", result.stdout)
        self.assertIn("usage: raven [OPTIONS] COMMAND [ARGS]...", result.stdout)
        self.assertIn("--destination DESTINATION", result.stdout)
        self.assertIn("raven install <language> --dry-run", result.stdout)
        self.assertIn("raven upgrade .claude/scripts/raven-tool-check.py", result.stdout)
        self.assertIn("Explicit override paths force-copy Raven-owned files.", result.stdout)
        self.assertIn("Supported languages:", result.stdout)
        self.assertIn("File safety:", result.stdout)
        self.assertNotIn("Safety model:", result.stdout)

    def test_install_help_names_language_and_overrides(self):
        result = subprocess.run(
            [sys.executable, str(RAVEN_PATH), "install", "--help"],
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0)
        self.assertIn("usage: raven install [OPTIONS] [language] [override ...]", result.stdout)
        self.assertIn("language template to install", result.stdout)
        self.assertIn("template-relative file paths to force-copy", result.stdout)
        self.assertIn("Supported languages:", result.stdout)
        self.assertNotIn("language_or_path", result.stdout)

    def test_hooks_tolerate_null_tool_input(self):
        hooks = [
            "raven-post-bash-summarize.py",
            "raven-pre-bash-guard.py",
            "raven-pre-edit-guard.py",
            "raven-post-edit-format.py",
        ]
        payload = json.dumps({"tool_input": None})

        for hook in hooks:
            with self.subTest(hook=hook):
                result = subprocess.run(
                    [sys.executable, str(REPO_ROOT / "common" / ".claude" / "hooks" / hook)],
                    input=payload,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_hooks_tolerate_non_dict_tool_input(self):
        hooks = [
            "raven-post-bash-summarize.py",
            "raven-pre-bash-guard.py",
            "raven-pre-edit-guard.py",
            "raven-post-edit-format.py",
        ]
        payload = json.dumps({"tool_input": "unexpected"})

        for hook in hooks:
            with self.subTest(hook=hook):
                result = subprocess.run(
                    [sys.executable, str(REPO_ROOT / "common" / ".claude" / "hooks" / hook)],
                    input=payload,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_codex_pre_hooks_emit_deny_payload_for_blocked_actions(self):
        cases = [
            (
                "raven-pre-bash-guard.py",
                {
                    "hook_event_name": "PreToolUse",
                    "tool_name": "Bash",
                    "tool_input": {"command": "git reset --hard"},
                },
            ),
            (
                "raven-pre-edit-guard.py",
                {
                    "hook_event_name": "PreToolUse",
                    "tool_name": "apply_patch",
                    "tool_input": {"file_path": ".env"},
                },
            ),
        ]

        for hook, payload in cases:
            with self.subTest(hook=hook):
                result = subprocess.run(
                    [sys.executable, str(REPO_ROOT / "common" / ".codex" / "hooks" / hook)],
                    input=json.dumps(payload),
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                response = json.loads(result.stdout)
                decision = response["hookSpecificOutput"]
                self.assertEqual(decision["hookEventName"], "PreToolUse")
                self.assertEqual(decision["permissionDecision"], "deny")

    def test_tool_check_script_imports_without_name_error(self):
        path = REPO_ROOT / "common" / ".claude" / "scripts" / "raven-tool-check.py"
        spec = importlib.util.spec_from_file_location("raven_tool_check", path)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None

        spec.loader.exec_module(module)

        self.assertEqual(module._DO_NOT_REMIND_KEY, "doNotRemind")

    def test_tool_check_parses_claude_mcp_server_names(self):
        path = REPO_ROOT / "common" / ".claude" / "scripts" / "raven-tool-check.py"
        spec = importlib.util.spec_from_file_location("raven_tool_check_parser", path)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        output = """Checking MCP server health...

semble: uvx --from semble[mcp] semble - ✗ Failed to connect
gitnexus: gitnexus mcp - ✓ Connected
[Conflicting scopes]
 └ [Warning] Server "gitnexus" is defined in multiple scopes
"""

        self.assertIn("semble", module._configured_mcp_server_names(output))
        self.assertIn("gitnexus", module._configured_mcp_server_names(output))

    def test_claude_mcp_config_files_are_parsed_without_cli(self):
        path = REPO_ROOT / "common" / ".claude" / "scripts" / "raven-tool-check.py"
        spec = importlib.util.spec_from_file_location("raven_tool_check_config", path)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)

        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / ".claude.json"
            config.write_text(
                json.dumps({"mcpServers": {"semble": {"command": "uvx"}}}), encoding="utf-8"
            )
            module._claude_mcp_config_paths = lambda: [config]
            module._claude_mcp_server_names_from_config.cache_clear()
            try:
                self.assertEqual(module.claude_mcp_server_status("semble"), "configured")
            finally:
                module._claude_mcp_server_names_from_config.cache_clear()

    def test_semble_can_be_available_from_claude_mcp_config_without_cli(self):
        path = REPO_ROOT / "common" / ".claude" / "scripts" / "raven-tool-check.py"
        spec = importlib.util.spec_from_file_location("raven_tool_check_semble", path)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        tool = next(tool for tool in module.TOOLS if tool["id"] == "semble")
        original_command_status = module.command_status
        original_status = module.claude_mcp_server_status
        module.command_status = lambda _command: "missing"
        module.claude_mcp_server_status = lambda name: (
            "configured" if name == "semble" else "not_configured"
        )
        try:
            available, source = module.check_tool_with_source(tool)
        finally:
            module.command_status = original_command_status
            module.claude_mcp_server_status = original_status

        self.assertTrue(available)
        self.assertEqual(source, "claude-mcp-config")

    def test_semble_can_be_available_from_codex_mcp_config_without_cli(self):
        path = REPO_ROOT / "common" / ".claude" / "scripts" / "raven-tool-check.py"
        spec = importlib.util.spec_from_file_location("raven_tool_check_semble_codex", path)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        tool = next(tool for tool in module.TOOLS if tool["id"] == "semble")
        original_command_status = module.command_status
        original_claude_status = module.claude_mcp_server_status
        original_codex_config = module._codex_mcp_server_names_from_config
        module.command_status = lambda _command: "missing"
        module.claude_mcp_server_status = lambda _name: "not_configured"
        module._codex_mcp_server_names_from_config = lambda: frozenset({"semble"})
        try:
            available, source = module.check_tool_with_source(tool)
        finally:
            module.command_status = original_command_status
            module.claude_mcp_server_status = original_claude_status
            module._codex_mcp_server_names_from_config = original_codex_config

        self.assertTrue(available)
        self.assertEqual(source, "codex-mcp-config")

    def test_slow_claude_mcp_check_does_not_crash_tool_check(self):
        path = REPO_ROOT / "common" / ".claude" / "scripts" / "raven-tool-check.py"
        spec = importlib.util.spec_from_file_location("raven_tool_check_timeout", path)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)

        original_which = module.shutil.which
        original_run = module.subprocess.run
        module.shutil.which = lambda name: (
            "/usr/bin/claude" if name == "claude" else original_which(name)
        )

        def timeout_run(*_args, **_kwargs):
            raise module.subprocess.TimeoutExpired(["claude", "mcp", "list"], timeout=3)

        module.subprocess.run = timeout_run
        module.RUN_CLAUDE_MCP_CLI = True
        module._claude_mcp_server_names.cache_clear()
        module._claude_mcp_server_names_from_config.cache_clear()
        module._claude_mcp_server_names_from_cli.cache_clear()
        module._claude_mcp_config_paths = lambda: []
        try:
            self.assertEqual(module.claude_mcp_server_status("semble"), "timed_out")
            self.assertFalse(module.claude_mcp_server_configured("semble"))
        finally:
            module._claude_mcp_server_names.cache_clear()
            module._claude_mcp_server_names_from_config.cache_clear()
            module._claude_mcp_server_names_from_cli.cache_clear()
            module.shutil.which = original_which
            module.subprocess.run = original_run

    def test_command_timeout_counts_as_unavailable(self):
        path = REPO_ROOT / "common" / ".claude" / "scripts" / "raven-tool-check.py"
        spec = importlib.util.spec_from_file_location("raven_tool_check_command_timeout", path)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)

        original_which = module.shutil.which
        original_run = module.subprocess.run
        module.shutil.which = lambda name: f"/usr/bin/{name}"
        module.RUN_COMMAND_PROBES = True

        def timeout_run(*_args, **_kwargs):
            raise module.subprocess.TimeoutExpired(["tool", "--version"], timeout=3)

        module.subprocess.run = timeout_run
        try:
            self.assertEqual(module.command_status(["tool", "--version"]), "timed_out")
            self.assertFalse(module.command_works(["tool", "--version"]))
        finally:
            module.shutil.which = original_which
            module.subprocess.run = original_run


class GitHookInstallerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.destination = Path(self.tmp.name)
        subprocess.run(
            ["git", "init", str(self.destination)],
            capture_output=True,
            check=True,
        )
        self.git_hooks_src = self.destination / ".raven" / "git-hooks"
        self.git_hooks_src.mkdir(parents=True)
        self.git_hooks_dir = self.destination / ".git" / "hooks"
        self.git_hooks_dir.mkdir(exist_ok=True)

    def _write_hook(self, name: str, content: str = "#!/bin/sh\n") -> Path:
        hook = self.git_hooks_src / name
        hook.write_text(content, encoding="utf-8")
        hook.chmod(0o644)
        return hook

    def test_installs_hook_as_symlink_in_git_hooks(self):
        self._write_hook("commit-msg")

        installed = raven.install_git_hooks(self.destination)

        link = self.git_hooks_dir / "commit-msg"
        self.assertEqual(installed, ["commit-msg"])
        self.assertTrue(link.is_symlink())
        self.assertEqual(link.resolve(), (self.git_hooks_src / "commit-msg").resolve())

    def test_makes_hook_file_executable(self):
        self._write_hook("commit-msg")

        raven.install_git_hooks(self.destination)

        hook_src = self.git_hooks_src / "commit-msg"
        self.assertTrue(hook_src.stat().st_mode & 0o111)

    def test_returns_empty_when_no_git_hooks_src_dir(self):
        self.git_hooks_src.rmdir()

        installed = raven.install_git_hooks(self.destination)

        self.assertEqual(installed, [])

    def test_returns_empty_when_not_a_git_repo(self):
        non_git = self.destination / "sub"
        non_git.mkdir()
        (non_git / ".raven" / "git-hooks").mkdir(parents=True)
        self._write_hook("commit-msg")

        installed = raven.install_git_hooks(non_git)

        self.assertEqual(installed, [])

    def test_does_not_overwrite_existing_regular_file(self):
        self._write_hook("commit-msg")
        existing = self.git_hooks_dir / "commit-msg"
        existing.write_text("# user hook\n", encoding="utf-8")
        stderr = io.StringIO()

        with contextlib.redirect_stderr(stderr):
            installed = raven.install_git_hooks(self.destination)

        self.assertEqual(installed, [])
        self.assertEqual(existing.read_text(encoding="utf-8"), "# user hook\n")
        self.assertIn("already exists as a regular file", stderr.getvalue())

    def test_idempotent_when_symlink_already_correct(self):
        self._write_hook("commit-msg")
        raven.install_git_hooks(self.destination)

        installed = raven.install_git_hooks(self.destination)

        self.assertEqual(installed, ["commit-msg"])

    def test_updates_stale_symlink(self):
        self._write_hook("commit-msg")
        stale_target = self.git_hooks_src.parent / "old-commit-msg"
        stale_target.write_text("# stale\n", encoding="utf-8")
        link = self.git_hooks_dir / "commit-msg"
        link.symlink_to(str(stale_target))

        installed = raven.install_git_hooks(self.destination)

        self.assertEqual(installed, ["commit-msg"])
        self.assertEqual(link.resolve(), (self.git_hooks_src / "commit-msg").resolve())

    def test_raven_git_hooks_path_included_in_hooks_component(self):
        self.assertIn(".raven/git-hooks", raven.COMPONENT_PATHS["hooks"])


class CommitMsgHookTests(unittest.TestCase):
    HOOK_PATH = REPO_ROOT / "common" / ".raven" / "git-hooks" / "commit-msg"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.msg_file = Path(self.tmp.name) / "COMMIT_EDITMSG"

    def _run_hook(self, message: str) -> tuple[str, int]:
        self.msg_file.write_text(message, encoding="utf-8")
        result = subprocess.run(
            [sys.executable, str(self.HOOK_PATH), str(self.msg_file)],
            capture_output=True,
            text=True,
        )
        return self.msg_file.read_text(encoding="utf-8"), result.returncode

    def test_strips_claude_co_authored_by(self):
        msg = "feat: add thing\n\nCo-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>\n"
        out, rc = self._run_hook(msg)
        self.assertEqual(rc, 0)
        self.assertNotIn("Co-Authored-By", out)
        self.assertIn("feat: add thing", out)

    def test_strips_copilot_co_authored_by(self):
        msg = "fix: bug\n\nCo-Authored-By: GitHub Copilot <noreply@github.com>\n"
        out, rc = self._run_hook(msg)
        self.assertEqual(rc, 0)
        self.assertNotIn("Co-Authored-By", out)

    def test_strips_codex_co_authored_by(self):
        msg = "chore: update\n\nCo-authored-by: OpenAI Codex <noreply@openai.com>\n"
        out, rc = self._run_hook(msg)
        self.assertEqual(rc, 0)
        self.assertNotIn("Co-authored-by", out)

    def test_strips_generated_by_trailer(self):
        msg = "docs: update\n\nGenerated-by: Claude\n"
        out, rc = self._run_hook(msg)
        self.assertEqual(rc, 0)
        self.assertNotIn("Generated-by", out)

    def test_removes_trailing_blank_lines_after_strip(self):
        msg = "feat: add thing\n\nCo-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>\n"
        out, rc = self._run_hook(msg)
        self.assertEqual(rc, 0)
        self.assertFalse(out.endswith("\n\n"))

    def test_preserves_human_co_authored_by(self):
        msg = "feat: pair program\n\nCo-Authored-By: Alice Smith <alice@example.com>\n"
        out, rc = self._run_hook(msg)
        self.assertEqual(rc, 0)
        self.assertIn("Co-Authored-By: Alice Smith", out)

    def test_does_not_modify_clean_message(self):
        msg = "feat: clean commit\n\nSome body text.\n"
        out, rc = self._run_hook(msg)
        self.assertEqual(rc, 0)
        self.assertEqual(out, msg)

    def test_strips_anthropic_domain_trailer(self):
        msg = "fix: patch\n\nCo-Authored-By: SomeBot <bot@anthropic.com>\n"
        out, rc = self._run_hook(msg)
        self.assertEqual(rc, 0)
        self.assertNotIn("anthropic.com", out)

    def test_strips_openai_domain_trailer(self):
        msg = "fix: patch\n\nCo-Authored-By: SomeBot <bot@openai.com>\n"
        out, rc = self._run_hook(msg)
        self.assertEqual(rc, 0)
        self.assertNotIn("openai.com", out)

    def test_hook_is_executable(self):
        self.assertTrue(self.HOOK_PATH.stat().st_mode & 0o111)

    def test_respects_strip_ai_attribution_false_in_config(self):
        # Write a repo with strip_ai_attribution = false and run hook inside it.
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            subprocess.run(["git", "init", str(repo)], capture_output=True, check=True)
            raven_dir = repo / ".raven"
            raven_dir.mkdir()
            (raven_dir / "config.toml").write_text(
                "[git_hooks]\nstrip_ai_attribution = false\n", encoding="utf-8"
            )
            msg_file = repo / "COMMIT_EDITMSG"
            msg = "feat: thing\n\nCo-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>\n"
            msg_file.write_text(msg, encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(self.HOOK_PATH), str(msg_file)],
                capture_output=True,
                text=True,
                cwd=str(repo),
            )
        self.assertEqual(result.returncode, 0)
        self.assertIn(
            "Co-Authored-By", msg_file.read_text(encoding="utf-8") if msg_file.exists() else msg
        )

    def test_default_strips_when_no_config(self):
        msg = "feat: add thing\n\nCo-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>\n"
        out, rc = self._run_hook(msg)
        self.assertEqual(rc, 0)
        self.assertNotIn("Co-Authored-By", out)

    def test_config_section_in_default_config_text(self):
        config_text = raven.default_config_text("python", False)
        self.assertIn("[git_hooks]", config_text)
        self.assertIn("strip_ai_attribution = true", config_text)


if __name__ == "__main__":
    unittest.main()
