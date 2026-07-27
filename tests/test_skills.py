import re
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


class AntipatternRegistrySkillTests(unittest.TestCase):
    """Guards the anti-pattern registry and its promotion wiring into
    raven-review-pr, added for issue #123.

    Reads the canonical sources directly (not the installed root copies)
    since `common/` is where edits must land.
    """

    def setUp(self):
        registry_path = REPO_ROOT / "common" / ".claude" / "docs" / "raven-antipatterns.md"
        self.registry = registry_path.read_text(encoding="utf-8")
        self.registry_lower = self.registry.lower()

        review_pr_path = (
            REPO_ROOT / "common" / ".agents" / "skills" / "raven-review-pr" / "SKILL.md"
        )
        self.review_pr = review_pr_path.read_text(encoding="utf-8")
        self.review_pr_lower = self.review_pr.lower()

    @staticmethod
    def _section_region(text_lower, heading):
        start = text_lower.find(heading)
        if start == -1:
            raise AssertionError(f"expected a {heading!r} section")
        next_heading = text_lower.find("\n## ", start + len(heading))
        end = next_heading if next_heading != -1 else len(text_lower)
        return text_lower[start:end]

    def test_registry_stays_proportionate(self):
        self.assertLess(
            len(self.registry.splitlines()),
            100,
            "raven-antipatterns.md is a shipped stub, not a place to accumulate "
            "prescribed patterns -- it should stay small",
        )

    def test_review_pr_stays_proportionate(self):
        self.assertLess(
            len(self.review_pr.splitlines()),
            50,
            "raven-review-pr/SKILL.md should stay skimmable after the record-and-promote addition",
        )

    def test_registry_documents_entry_format(self):
        self.assertIn("status", self.registry_lower)
        self.assertIn("pattern", self.registry_lower)
        self.assertIn("why", self.registry_lower)
        self.assertIn("instead", self.registry_lower)

    def test_registry_requires_two_observations_before_recording(self):
        self.assertIn(
            "more than once",
            self.registry_lower,
            "expected the two-strikes rule: record on the second observation, not the first",
        )
        self.assertIn(
            "first sighting",
            self.registry_lower,
            "expected an explicit contrast with recording on first sighting",
        )

    def test_registry_documents_status_lifecycle(self):
        self.assertIn("observed", self.registry_lower)
        self.assertIn("promoted to", self.registry_lower)
        self.assertIn("retired", self.registry_lower)

    def test_registry_documents_retirement_so_entries_do_not_accumulate(self):
        self.assertIn("retire", self.registry_lower)
        self.assertIn(
            "delete",
            self.registry_lower,
            "expected explicit guidance that retired entries are removed, "
            "not just relabeled forever",
        )

    def test_registry_degrades_gracefully_without_semgrep(self):
        self.assertIn("semgrep", self.registry_lower)
        self.assertIn(
            "not require",
            self.registry_lower,
            "expected the registry to say Semgrep is not required, per the "
            "non-goal of not requiring Semgrep",
        )

    def test_registry_ships_no_prescribed_patterns(self):
        entry_headings = self.registry.count("\n### ")
        self.assertEqual(
            entry_headings,
            1,
            "expected exactly one illustrative template entry and no "
            "prescribed anti-patterns shipped in the canonical template",
        )
        self.assertIn(
            "illustrative",
            self.registry_lower,
            "expected the single shipped entry to be explicitly marked as a template, "
            "not a real observation",
        )

    def test_review_pr_gains_a_step_referencing_the_registry_by_path(self):
        region = self._section_region(self.review_pr_lower, "## process")

        self.assertIn(".claude/docs/raven-antipatterns.md", self.review_pr)
        self.assertIn("antipatterns.md", region)

    def test_review_pr_promotes_recurring_findings_to_semgrep(self):
        region = self._section_region(self.review_pr_lower, "## process")

        self.assertIn("semgrep", region)
        self.assertIn("promot", region)

    def test_review_pr_promotion_does_not_require_semgrep(self):
        region = self._section_region(self.review_pr_lower, "## process")

        self.assertTrue(
            "not configured" in region or "skip promotion" in region,
            "expected the promotion step to degrade gracefully when Semgrep "
            "is unavailable, per the non-goal of not requiring Semgrep",
        )


class AntipatternRegistrySymlinkTests(unittest.TestCase):
    """Guards the per-file symlink from every language tree into the
    canonical registry doc, added for issue #123.

    This duplicates part of what `scripts/self-check.py`'s
    `validate_symlink_canonicality()` checks once the path is added to its
    hand-maintained `_TREE_SYMLINKS_TO_COMMON` list -- but it does not
    depend on that list being kept in sync. The list is exactly the
    fragile part (a shared doc added without a matching list entry is
    silently never checked by self-check), so a pytest test that hardcodes
    the invariant directly has independent value: it runs in the fast
    inner loop and on every CI job, and it fails even if the list entry
    is forgotten entirely.
    """

    def test_all_language_trees_symlink_to_the_canonical_registry(self):
        canonical = (REPO_ROOT / "common" / ".claude" / "docs" / "raven-antipatterns.md").resolve()
        self.assertTrue(canonical.is_file(), "expected the canonical registry doc to exist")

        language_dirs = [
            "dotfiles",
            "elixir",
            "go",
            "lua",
            "python",
            "rust",
            "swift",
            "typescript",
        ]
        for lang in language_dirs:
            path = REPO_ROOT / lang / ".claude" / "docs" / "raven-antipatterns.md"
            with self.subTest(lang=lang):
                self.assertTrue(path.is_symlink(), f"{path} should be a symlink, not a real file")
                self.assertEqual(
                    path.resolve(),
                    canonical,
                    f"{path} should resolve to the canonical common/ file",
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


class DebloatSkillTests(unittest.TestCase):
    """Guards the subtractive-maintenance skill added for issue #124.

    Reads the canonical skill source directly (not the installed root
    copy) since `common/.agents/skills/` is where edits must land.
    """

    def setUp(self):
        path = REPO_ROOT / "common" / ".agents" / "skills" / "raven-debloat" / "SKILL.md"
        self.content = path.read_text(encoding="utf-8")
        self.lowered = self.content.lower()

    def _section_region(self, heading):
        start = self.lowered.find(heading)
        self.assertNotEqual(start, -1, f"expected a {heading!r} section")
        next_heading = self.lowered.find("\n## ", start + len(heading))
        end = next_heading if next_heading != -1 else len(self.lowered)
        return self.lowered[start:end]

    def test_stays_under_line_ceiling(self):
        self.assertLess(
            len(self.content.splitlines()),
            90,
            "raven-debloat/SKILL.md legitimately needs more structure than most "
            "skills, but past ~90 lines it is duplicating AGENTS.md or over-explaining",
        )

    def test_description_stays_well_under_the_per_skill_cap(self):
        # This skill's addition is what forced the aggregate skill-index budget in
        # scripts/self-check.py upward. Hold its own description tight so the
        # raise stays the one-off it was justified as.
        match = re.search(r"^description:\s*(.*)$", self.content, re.M)
        self.assertIsNotNone(match, "expected a description: line in the frontmatter")
        assert match is not None
        self.assertLessEqual(
            len(match.group(1).split()),
            15,
            "raven-debloat's description must stay at 15 words or fewer",
        )

    def test_declares_the_required_sections(self):
        for heading in (
            "## skip when",
            "## required constraints",
            "## process",
            "## preflight",
            "## reduction hierarchy",
            "## anti-gaming self-audit",
            "## stop conditions",
            "## output",
        ):
            with self.subTest(heading=heading):
                self.assertIn(heading, self.lowered)

    def test_reads_as_area_maintenance_not_a_per_diff_cleanup_pass(self):
        # The confusable neighbour is a /simplify-style pass over a working diff.
        # Assert the boundary is drawn in Skip When, where an agent actually
        # checks applicability, not buried in prose.
        region = self._section_region("## skip when")

        self.assertIn(
            "diff",
            region,
            "expected Skip When to send per-diff cleanup elsewhere so this skill "
            "is not confused with a review-time simplify pass",
        )

    def test_preflight_requires_a_verified_green_baseline_before_the_first_deletion(self):
        region = self._section_region("## preflight")

        self.assertIn(
            "before the first deletion",
            region,
            "expected preflight to be explicitly ordered before any deletion",
        )
        self.assertIn("static analysis", region)
        self.assertIn("runtime check", region)
        self.assertIn("baseline", region)

    def test_preflight_excludes_the_irreducible_floor_from_candidates(self):
        region = self._section_region("## preflight")

        self.assertIn("irreducible floor", region)
        self.assertIn("generated", region)
        self.assertIn(
            "not candidates",
            region,
            "expected generated/vendored/scaffolding code ruled out as candidates",
        )

    def test_preflight_pins_formatting_so_reformatting_cannot_read_as_reduction(self):
        region = self._section_region("## preflight")

        self.assertIn("formatt", region)
        self.assertIn("comparable", region)

    def test_dead_code_claims_require_semantic_evidence_rather_than_grep(self):
        region = self._section_region("## required constraints")

        self.assertIn("lsp references", region)
        self.assertIn(
            "does not prove",
            region,
            "expected text search to be explicitly insufficient as dead-code evidence",
        )

    def test_no_automatic_deletion(self):
        region = self._section_region("## required constraints")

        self.assertIn("proposed and confirmed", region)
        self.assertIn("no automatic deletion", region)

    def test_subsystem_deletion_and_library_adoption_route_to_pause_and_ask(self):
        region = self._section_region("## required constraints")

        self.assertIn("deleting a subsystem", region)
        self.assertIn(
            "dependency addition",
            region,
            "expected library adoption named as a dependency addition, "
            "which is what makes it a Pause And Ask item",
        )
        self.assertGreaterEqual(
            region.count("pause and ask"),
            2,
            "expected both gated cases routed to AGENTS.md Pause And Ask by name",
        )

    def test_gated_hierarchy_tiers_are_marked_inline_at_the_point_of_use(self):
        # The failure guarded against is an agent reading tier 6 in isolation,
        # concluding a mature library is obviously better, and adding a
        # dependency. A constraint 40 lines earlier does not stop that; an
        # inline marker on the tier itself does.
        region = self._section_region("## reduction hierarchy")

        self.assertGreaterEqual(
            region.count("gated"),
            3,
            "expected each gated tier marked inline, not only in a distant constraint",
        )
        self.assertGreaterEqual(region.count("pause and ask"), 3)

    def test_hierarchy_is_ordered_and_forbids_skipping_to_riskier_tiers(self):
        region = self._section_region("## reduction hierarchy")

        self.assertIn("in this order", region)
        self.assertIn("do not skip ahead", region)

    def test_comment_hygiene_never_counts_as_reduction(self):
        region = self._section_region("## reduction hierarchy")

        self.assertIn("hygiene only", region)
        self.assertIn("never counted as a reduction", region)

    def test_self_audit_classifies_structural_versus_cheap(self):
        region = self._section_region("## anti-gaming self-audit")

        self.assertIn("structural", region)
        self.assertIn("cheap", region)

    def test_self_audit_can_terminate_the_run(self):
        region = self._section_region("## anti-gaming self-audit")

        self.assertIn(
            "stop and report",
            region,
            "expected the audit to be able to end the run, not merely advise",
        )
        self.assertIn(
            "gaming the metric",
            region,
            "expected the audit to force an explicit choice between admitting "
            "metric gaming and declaring the structural well dry",
        )
        self.assertIn("well is dry", region)

    def test_self_audit_is_wired_into_the_process_rather_than_optional(self):
        region = self._section_region("## process")

        self.assertIn(
            "self-audit",
            region,
            "expected the audit to be a numbered process step, so it is part of "
            "the loop rather than a section an agent may never reach",
        )

    def test_stop_conditions_cover_the_revert_retry_loop(self):
        region = self._section_region("## stop conditions")

        self.assertIn("revert", region)

    def test_under_reach_is_named_as_a_failure_mode(self):
        region = self._section_region("## rationalization check")

        self.assertIn(
            "under-reach is a failure",
            region,
            "expected a Rationalization Check row rebutting 'too risky, "
            "I'll leave it and report success'",
        )

    def test_finding_nothing_structural_is_a_reportable_conclusion(self):
        # The counterweight to naming under-reach a failure: "nothing to remove"
        # must be a legitimate, evidence-backed outcome, or the skill becomes
        # pressure to delete. Mirrors raven-task-complete's `Intent: none` hatch.
        constraints = self._section_region("## required constraints")
        output = self._section_region("## output")

        self.assertIn("as a conclusion with evidence", constraints)
        self.assertIn(
            "never delete to have something to report",
            constraints,
            "expected the no-findings hatch paired with an explicit ban on "
            "deleting for the sake of having a result",
        )
        self.assertIn("no structural reduction available", output)

    def test_green_tests_are_not_treated_as_design_health(self):
        self.assertIn("green tests prove behavior", self.lowered)

    def test_composition_with_sibling_skills_is_stated_by_name(self):
        self.assertIn("raven-write-tests", self.content)
        self.assertIn("raven-safe-refactor", self.content)

    def test_sets_no_sloc_target(self):
        """Acceptance criterion 5, as one positive and two mechanical checks.

        "Assert no number appears" would be theatre -- the file has a numbered
        hierarchy, so digits are expected, and a naive digit ban would either
        never fail or fail constantly. What is actually worth catching is the
        concrete regression: someone lifts the source run's ``-31.7%`` (or
        similar) out of the issue and into the shipped text, or writes an
        explicit size goal. Both forms carry a number attached to a unit, so:

        1. Positive -- the prohibition is stated in Required Constraints, so
           removing it is a deliberate, reviewable edit rather than drift.
        2. No percentage figure anywhere. This skill has no legitimate use for
           one; any percentage here is a reduction figure.
        3. No numeric line/SLOC figure anywhere, which is the other way a
           target gets written down.

        Honest limitation: this cannot catch a digit-free prose target ("aim to
        halve this module"). No robust regex distinguishes that from legitimate
        prose, so check 1 carries that case -- the stated prohibition is what a
        reviewer and the agent both read.
        """
        constraints = self._section_region("## required constraints")
        self.assertIn("no sloc target", constraints)
        self.assertIn("never a goal", constraints)

        self.assertEqual(
            re.findall(r"\d+(?:\.\d+)?\s*%", self.content),
            [],
            "no percentage figure belongs in this skill -- a reduction "
            "percentage in shipped text is a target by implication",
        )
        self.assertEqual(
            re.findall(r"\b\d[\d,.]*\s*k?\s*(?:sloc|loc|lines?)\b", self.lowered),
            [],
            "no numeric line/SLOC figure belongs in this skill",
        )


if __name__ == "__main__":
    unittest.main()
