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


class PlanSkillTests(unittest.TestCase):
    """Guards the machine-checkable completion-criteria requirement added for issue #121.

    Reads the canonical skill source directly (not the installed root
    copy) since `common/.agents/skills/` is where edits must land.
    """

    def setUp(self):
        path = REPO_ROOT / "common" / ".agents" / "skills" / "raven-plan" / "SKILL.md"
        self.content = path.read_text(encoding="utf-8")
        self.lowered = self.content.lower()

    def test_stays_proportionate(self):
        self.assertLess(
            len(self.content.splitlines()),
            65,
            "raven-plan/SKILL.md should stay skimmable even after the completion-criteria addition",
        )

    def _completion_criteria_region(self):
        start = self.lowered.find("## completion criteria")
        self.assertNotEqual(start, -1, "expected a '## Completion Criteria' section")
        next_heading = self.lowered.find("\n## ", start + len("## completion criteria"))
        end = next_heading if next_heading != -1 else len(self.lowered)
        return self.lowered[start:end]

    def test_completion_criteria_require_end_state_verification_and_invariants(self):
        region = self._completion_criteria_region()

        # Tighter than issue #120's ordering-only anchor: this asserts all three
        # required elements live inside the Completion Criteria section itself,
        # not merely somewhere in the file. Presence-anywhere would pass even if
        # "invariants" only showed up in an unrelated section, which would not
        # demonstrate the triple is actually required together as one unit.
        self.assertIn("end state", region, "expected a measurable end state requirement")
        self.assertIn(
            "verification command", region, "expected an explicit verification command requirement"
        )
        self.assertIn("invariant", region, "expected an invariant-constraints requirement")

    def test_prose_only_criteria_are_called_out_as_insufficient(self):
        region = self._completion_criteria_region()

        self.assertIn(
            "prose-only",
            region,
            "expected prose-only completion criteria to be explicitly named",
        )
        self.assertIn(
            "insufficient",
            region,
            "expected prose-only criteria to be called out as insufficient",
        )


class TaskCompleteSkillTests(unittest.TestCase):
    """Guards the design-intent capture added for issue #122.

    Reads the canonical skill source directly (not the installed root
    copy) since `common/.agents/skills/` is where edits must land.
    """

    def setUp(self):
        path = REPO_ROOT / "common" / ".agents" / "skills" / "raven-task-complete" / "SKILL.md"
        self.content = path.read_text(encoding="utf-8")
        self.lowered = self.content.lower()

    def test_stays_under_line_ceiling(self):
        self.assertLess(
            len(self.content.splitlines()),
            65,
            "raven-task-complete/SKILL.md should stay under ~65 lines",
        )

    def _section_region(self, heading):
        start = self.lowered.find(heading)
        self.assertNotEqual(start, -1, f"expected a {heading!r} section")
        next_heading = self.lowered.find("\n## ", start + len(heading))
        end = next_heading if next_heading != -1 else len(self.lowered)
        return self.lowered[start:end]

    def test_required_constraints_demand_intent_not_derivable_from_the_diff(self):
        region = self._section_region("## required constraints")

        self.assertIn(
            "not derivable from the diff",
            region,
            "expected a Required Constraint that intent must add information "
            "the diff does not already carry",
        )

    def test_output_shape_includes_an_intent_line(self):
        region = self._section_region("## output")

        self.assertIn("intent:", region, "expected an Intent line in the Output shape")

    def test_intent_has_an_explicit_no_design_decision_escape_hatch(self):
        region = self._section_region("## output")

        self.assertIn(
            "no design decision",
            region,
            "expected an explicit escape hatch for changes with no design decision to report",
        )

    def test_rationalization_check_covers_code_explains_itself(self):
        region = self._section_region("## rationalization check")

        self.assertIn(
            "the code explains itself",
            region,
            "expected a Rationalization Check row rebutting 'the code explains itself'",
        )
        self.assertIn(
            "silence is indistinguishable",
            region,
            "expected the rebuttal to note that silence looks the same as having no reason",
        )


if __name__ == "__main__":
    unittest.main()
