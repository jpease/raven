import unittest

from helpers import REPO_ROOT, RavenTestCase, raven


class SkillsTests(RavenTestCase):
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


class ImplementFeatureSkillTests(unittest.TestCase):
    """Guards the scope-ceiling guardrail added for issue #120.

    Reads the canonical skill source directly (not the installed root
    copy) since `common/.agents/skills/` is where edits must land.
    """

    def setUp(self):
        path = REPO_ROOT / "common" / ".agents" / "skills" / "raven-implement-feature" / "SKILL.md"
        self.content = path.read_text(encoding="utf-8")

    def test_stays_under_line_ceiling(self):
        self.assertLess(
            len(self.content.splitlines()),
            50,
            "raven-implement-feature/SKILL.md should stay skimmable, under ~50 lines",
        )

    def test_scope_ceiling_is_declared_before_the_implementation_step(self):
        lowered = self.content.lower()
        ceiling_index = lowered.find("scope ceiling")
        implement_index = lowered.find("implement using existing conventions")

        self.assertNotEqual(ceiling_index, -1, "expected a 'scope ceiling' anchor in the skill")
        self.assertNotEqual(
            implement_index, -1, "expected the 'implement using existing conventions' step"
        )
        self.assertLess(
            ceiling_index,
            implement_index,
            "scope ceiling must be stated before the implementation step, not after",
        )


if __name__ == "__main__":
    unittest.main()
