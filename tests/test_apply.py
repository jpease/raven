import contextlib
import io
import os
import unittest

from helpers import RavenTestCase, raven


class ApplyTests(RavenTestCase):
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


def _classification(**overrides):
    fields = {
        "will_copy": [],
        "will_upgrade": [],
        "identical": [],
        "needs_merge": [],
        "unknown_existing": [],
        "excluded": [],
    }
    fields.update(overrides)
    return raven.Classification(**fields)


class BuildApplyPlanTests(unittest.TestCase):
    def test_claude_symlink_conflict_respects_overrides(self):
        classification = _classification(needs_merge=["CLAUDE.md", "AGENTS.md"])
        self.assertTrue(raven.claude_symlink_conflict(classification, []))
        # An explicit override for CLAUDE.md removes it from the conflict set.
        self.assertFalse(raven.claude_symlink_conflict(classification, ["CLAUDE.md"]))

    def test_build_apply_plan_is_pure_and_routes_overrides(self):
        classification = _classification(
            will_copy=["a.md"], will_upgrade=["b.md"], needs_merge=["c.md"]
        )
        plan = raven.build_apply_plan(
            classification,
            ["c.md"],
            existing_overrides={"c.md"},
            adopt_claude_symlink=False,
        )
        self.assertEqual(plan.will_copy, ["a.md"])
        self.assertEqual(plan.overwritten, ["c.md"])
        self.assertEqual(plan.needs_merge, [])  # removed by override
        self.assertFalse(plan.adopt_claude_symlink)

    def test_build_apply_plan_adopts_claude_symlink_when_decided(self):
        classification = _classification(needs_merge=["CLAUDE.md"])
        plan = raven.build_apply_plan(
            classification, [], existing_overrides=set(), adopt_claude_symlink=True
        )
        self.assertTrue(plan.adopt_claude_symlink)
        self.assertNotIn("CLAUDE.md", plan.needs_merge)


if __name__ == "__main__":
    unittest.main()
