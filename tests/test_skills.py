import re
import unittest

from helpers import REPO_ROOT, RavenTestCase, raven


def section_region(text_lower, heading):
    """Return the slice of ``text_lower`` from ``heading`` up to the next
    ``## `` heading (or end of string).

    ``heading`` must already be a lowercase ``## ...`` string, since callers
    pass a pre-lowered copy of the document. Single module-level helper used
    by every skill-guidance test class below -- previously this existed as
    four near-duplicate copies under two names and two signatures.
    """
    start = text_lower.find(heading)
    if start == -1:
        raise AssertionError(f"expected a {heading!r} section")
    next_heading = text_lower.find("\n## ", start + len(heading))
    end = next_heading if next_heading != -1 else len(text_lower)
    return text_lower[start:end]


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

    def test_completion_criteria_require_end_state_verification_and_invariants(self):
        region = section_region(self.lowered, "## completion criteria")

        # "end state" and "verification command" are kept verbatim (not consolidated
        # into a section-existence check) because they are the substance of #121's
        # required triple, not decorative color -- issue #130's re-review of this
        # test suite.
        self.assertIn("end state", region, "expected a measurable end state requirement")
        self.assertIn(
            "verification command", region, "expected an explicit verification command requirement"
        )
        self.assertIn("invariant", region, "expected an invariant-constraints requirement")

    def test_prose_only_criteria_are_called_out_as_insufficient(self):
        region = section_region(self.lowered, "## completion criteria")

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
        """Recurrence must be demonstrable within a single review -- the
        doc must not rely on a reviewer remembering a first sighting from a
        prior, now-gone session (issue #128; was
        test_registry_requires_two_observations_before_recording asserting
        'more than once' / 'first sighting', a rule that silently required
        cross-session memory the registry does not have).

        Kept verbatim under issue #130's re-review: this exact area produced
        a real design defect while 10 tests passed, so the rule's precise
        shape is load-bearing, not decorative.
        """
        self.assertIn(
            "two instances",
            self.registry_lower,
            "expected the rule to require two cited instances before recording an entry",
        )
        self.assertIn(
            "same review",
            self.registry_lower,
            "expected recurrence to be demonstrable within one review, not "
            "remembered across sessions",
        )
        self.assertIn(
            "no memory across sessions",
            self.registry_lower,
            "expected the doc to admit its recurrence detection has no "
            "cross-session memory, so it stops implying a capability it lacks",
        )
        self.assertIn(
            "months apart",
            self.registry_lower,
            "expected the doc to state the cost plainly: recurrences whose "
            "two instances land months apart, across sessions, are never recorded",
        )

    def test_registry_documents_status_lifecycle(self):
        # "promoted to" is dropped in favor of the "promot" stem: the actual
        # authority gate on promotion (never write the check/gate yourself) is
        # covered verbatim by test_review_pr_recommends_but_never_applies_semgrep_promotion
        # below; this test only needs to confirm the three-state vocabulary survives.
        region = section_region(self.registry_lower, "## status lifecycle")
        self.assertIn("observed", region)
        self.assertIn("promot", region)
        self.assertIn("retired", region)

    def test_registry_documents_retirement_so_entries_do_not_accumulate(self):
        region = section_region(self.registry_lower, "## status lifecycle")
        self.assertIn("retire", region)
        self.assertIn(
            "delete",
            region,
            "expected explicit guidance that retired entries are removed, "
            "not just relabeled forever",
        )

    def test_registry_documents_that_semgrep_is_optional(self):
        # "not require" (prose) is dropped for a section-existence check: what
        # matters is that a dedicated section says promotion degrades gracefully,
        # not the exact sentence used to say it.
        region = section_region(self.registry_lower, "## semgrep is optional")
        self.assertIn("semgrep", region)

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
        region = section_region(self.review_pr_lower, "## process")

        self.assertIn(".claude/docs/raven-antipatterns.md", self.review_pr)
        self.assertIn("antipatterns.md", region)

    def test_review_pr_recommends_but_never_applies_semgrep_promotion(self):
        """Promotion is a recommendation the reviewer names for the user to
        authorize -- the skill must never write the Semgrep rule or gate
        wiring itself, per Pause And Ask (issue #127; was
        test_review_pr_promotes_recurring_findings_to_semgrep, which asserted
        the skill applying the promotion directly).

        Kept verbatim under issue #130's re-review: this is the write-authority
        gate. Removing it lets a review skill silently regain authority to
        modify CI.
        """
        region = section_region(self.review_pr_lower, "## process")

        self.assertIn("semgrep", region)
        self.assertIn("recommend", region)
        self.assertIn(
            "do not write",
            region,
            "expected an explicit disclaimer that the skill does not write "
            "the rule or gate change itself",
        )
        self.assertIn(
            "pause and ask",
            region,
            "expected an explicit reference to the Pause And Ask guardrail for the gate/CI change",
        )

    def test_review_pr_promotion_does_not_require_semgrep(self):
        region = section_region(self.review_pr_lower, "## process")

        self.assertTrue(
            "not configured" in region or "skip promotion" in region,
            "expected the promotion step to degrade gracefully when Semgrep "
            "is unavailable, per the non-goal of not requiring Semgrep",
        )

    def test_review_pr_registry_entry_requires_authorization(self):
        """Writing the registry entry itself is gated on explicit user
        authorization, so the review step cannot silently drift into
        unrequested doc edits (issue #127)."""
        region = section_region(self.review_pr_lower, "## process")

        self.assertIn(
            "authoriz",
            region,
            "expected the process section to require authorization before "
            "writing a registry entry or promoting a pattern",
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

    def test_required_constraints_demand_intent_not_derivable_from_the_diff(self):
        region = section_region(self.lowered, "## required constraints")

        # Kept verbatim under issue #130's re-review: this is the substance of
        # #122's constraint, not decorative wording.
        self.assertIn(
            "not derivable from the diff",
            region,
            "expected a Required Constraint that intent must add information "
            "the diff does not already carry",
        )

    def test_output_intent_line_has_a_none_escape_hatch(self):
        # Consolidates the former test_output_shape_includes_an_intent_line and
        # test_intent_has_an_explicit_no_design_decision_escape_hatch. "no design
        # decision" (the rationale prose) is dropped in favor of "intent: none"
        # (the literal syntax contract agents write) -- more mechanical, less
        # coupled to how the rationale is explained.
        region = section_region(self.lowered, "## output")

        self.assertIn("intent:", region, "expected an Intent line in the Output shape")
        self.assertIn(
            "intent: none",
            region,
            "expected an explicit 'Intent: none' escape hatch for changes with no "
            "design decision to report",
        )

    def test_rationalization_check_table_has_full_row_coverage(self):
        # "the code explains itself" / "silence is indistinguishable" (the
        # specific rebuttal wording) are dropped for a structural row-count
        # check: what matters is that the table still carries its full set of
        # rationalization rows, not the exact phrasing of any one rebuttal.
        region = section_region(self.lowered, "## rationalization check")

        self.assertGreaterEqual(
            region.count("\n|"),
            6,
            "expected a header/divider row plus at least 5 rationalization rows",
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

    def test_stays_under_line_ceiling(self):
        # Ceiling basis (issue #130): the general skill ceiling used elsewhere in
        # this file is ~50-65 lines, sized for a single-screen skimmable skill.
        # raven-debloat legitimately carries more structure than most skills (8
        # required sections: Skip When, Required Constraints, Process, Preflight,
        # Reduction Hierarchy, Anti-Gaming Self-Audit, Stop Conditions, Output), so
        # its ceiling is roomier -- roughly current size plus one iteration of
        # headroom, not a tight budget. It was raised here from <90 to <100 (the
        # same ceiling used for raven-antipatterns.md) because <90 left only 2
        # lines of headroom against the actual 87-line file, which meant the next
        # small, justified addition would fail this test on size alone rather than
        # on any real bloat signal.
        self.assertLess(
            len(self.content.splitlines()),
            100,
            "raven-debloat/SKILL.md legitimately needs more structure than most "
            "skills, but past ~100 lines it is duplicating AGENTS.md or over-explaining",
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
        region = section_region(self.lowered, "## skip when")

        self.assertIn(
            "diff",
            region,
            "expected Skip When to send per-diff cleanup elsewhere so this skill "
            "is not confused with a review-time simplify pass",
        )

    def test_preflight_establishes_a_baseline_before_any_deletion(self):
        # "before the first deletion" (prose claim about ordering) is dropped for
        # an actual structural ordering check: the baseline step must be the
        # first numbered item, not merely asserted to be first somewhere in text.
        # "static analysis" / "runtime check" are narrowed to single-word anchors.
        region = section_region(self.lowered, "## preflight")

        baseline_index = region.find("baseline")
        second_item_index = region.find("\n2.")
        self.assertNotEqual(baseline_index, -1, "expected Preflight to establish a baseline")
        self.assertNotEqual(
            second_item_index, -1, "expected Preflight to have at least two numbered steps"
        )
        self.assertLess(
            baseline_index,
            second_item_index,
            "expected the baseline check to be the first Preflight step, before any deletion",
        )
        self.assertIn("static", region)
        self.assertIn("runtime", region)

    def test_preflight_excludes_generated_and_vendored_code_from_candidates(self):
        # "irreducible floor" / "not candidates" (the framing prose) are dropped
        # for the concrete exclusion list itself -- deleting the whole bullet
        # still fails this test, deleting only its label no longer does.
        region = section_region(self.lowered, "## preflight")

        self.assertIn("generated", region)
        self.assertIn("vendored", region)
        self.assertIn("lockfile", region)

    def test_preflight_pins_formatting_so_reformatting_cannot_read_as_reduction(self):
        region = section_region(self.lowered, "## preflight")

        self.assertIn("formatt", region)
        self.assertIn("comparable", region)

    def test_dead_code_claims_require_semantic_evidence_rather_than_grep(self):
        # "lsp references" / "does not prove" are dropped for the named evidence
        # sources plus the named counterexample technique.
        region = section_region(self.lowered, "## required constraints")

        self.assertIn("lsp", region)
        self.assertIn("gitnexus", region)
        self.assertIn("text search", region)

    def test_no_automatic_deletion(self):
        # Kept verbatim under issue #130's re-review: this is raven-debloat's
        # confirm-before-removal guarantee.
        region = section_region(self.lowered, "## required constraints")

        self.assertIn("proposed and confirmed", region)
        self.assertIn("no automatic deletion", region)

    def test_subsystem_and_dependency_changes_route_to_pause_and_ask(self):
        # "deleting a subsystem" / "dependency addition" (the full trigger
        # phrases) are narrowed to single-word anchors ("subsystem", "dependency").
        # The count>=2 check on "pause and ask" itself -- the actual authority
        # gate -- is kept verbatim.
        region = section_region(self.lowered, "## required constraints")

        self.assertIn("subsystem", region)
        self.assertIn(
            "dependency",
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
        region = section_region(self.lowered, "## reduction hierarchy")

        self.assertGreaterEqual(
            region.count("gated"),
            3,
            "expected each gated tier marked inline, not only in a distant constraint",
        )
        self.assertGreaterEqual(region.count("pause and ask"), 3)

    def test_hierarchy_tiers_appear_in_ascending_numeric_order(self):
        # "in this order" / "do not skip ahead" (prose claims about ordering) are
        # dropped for an actual structural ordering check across all 8 tiers.
        region = section_region(self.lowered, "## reduction hierarchy")

        positions = [region.find(f"\n{n}. ") for n in range(1, 9)]
        self.assertTrue(
            all(p != -1 for p in positions),
            "expected 8 numbered tiers in the Reduction Hierarchy",
        )
        self.assertEqual(
            positions,
            sorted(positions),
            "expected the 8 tiers to appear in ascending numeric order",
        )

    def test_comment_hygiene_is_classified_as_cheap_not_structural(self):
        # "hygiene only" / "never counted as a reduction" (the rationale prose)
        # are dropped for a cross-section structural check: the comment-hygiene
        # tier must actually be named under the audit's "Cheap" classification,
        # which is a stronger, less wording-coupled check than matching the
        # rationale sentence in isolation.
        hierarchy = section_region(self.lowered, "## reduction hierarchy")
        audit = section_region(self.lowered, "## anti-gaming self-audit")

        self.assertIn("comment hygiene", hierarchy)
        self.assertIn("comment deletion", audit)

    def test_self_audit_classifies_structural_versus_cheap(self):
        region = section_region(self.lowered, "## anti-gaming self-audit")

        self.assertIn("structural", region)
        self.assertIn("cheap", region)

    def test_self_audit_forces_a_choice_between_gaming_and_a_dry_well(self):
        # "stop and report" / "gaming the metric" / "well is dry" (the full
        # phrases) are narrowed to single-word anchors covering the same
        # forced-choice concept.
        region = section_region(self.lowered, "## anti-gaming self-audit")

        self.assertIn(
            "stop",
            region,
            "expected the audit to be able to end the run, not merely advise",
        )
        self.assertIn(
            "gaming",
            region,
            "expected the audit to force an explicit choice between admitting "
            "metric gaming and declaring the structural well dry",
        )
        self.assertIn("dry", region)

    def test_self_audit_is_wired_into_the_process_rather_than_optional(self):
        region = section_region(self.lowered, "## process")

        self.assertIn(
            "self-audit",
            region,
            "expected the audit to be a numbered process step, so it is part of "
            "the loop rather than a section an agent may never reach",
        )

    def test_stop_conditions_cover_the_revert_retry_loop(self):
        # Strengthened under issue #130's re-review: asserting only that
        # "revert" appears in the section was near-tautological (the section
        # header itself is "Stop Conditions", and "revert" alone does not
        # distinguish the retry-loop rule from an unrelated mention of revert).
        # Requiring "revert" and "retry" together demands the actual concept.
        region = section_region(self.lowered, "## stop conditions")

        self.assertIn("revert", region)
        self.assertIn("retry", region)

    def test_rationalization_check_table_has_full_row_coverage(self):
        # "under-reach is a failure" (a specific rebuttal) is dropped for a
        # structural row-count check, consistent with the same consolidation
        # applied to raven-task-complete's Rationalization Check table.
        region = section_region(self.lowered, "## rationalization check")

        self.assertGreaterEqual(
            region.count("\n|"),
            6,
            "expected a header/divider row plus at least 5 rationalization rows",
        )

    def test_finding_nothing_is_a_legitimate_reportable_outcome(self):
        # The counterweight to a forced-choice audit: "nothing to remove" must be
        # a legitimate, evidence-backed outcome, or the skill becomes pressure to
        # delete. Mirrors raven-task-complete's `Intent: none` hatch.
        # "as a conclusion with evidence" / "never delete to have something to
        # report" / "no structural reduction available" (the full phrases) are
        # dropped for a cross-section presence check on the underlying concept.
        constraints = section_region(self.lowered, "## required constraints")
        output = section_region(self.lowered, "## output")

        self.assertIn("nothing structural", constraints)
        self.assertIn("structural reduction", output)

    def test_passing_tests_are_not_treated_as_design_health(self):
        # "green tests prove behavior" (the full sentence) is dropped for the
        # defined term it turns on.
        region = section_region(self.lowered, "## required constraints")

        self.assertIn("design health", region)

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

        Kept verbatim under issue #130's re-review, along with its two regex
        checks: this is the #124 no-target prohibition paired with its mechanical
        enforcement, not decorative wording.
        """
        constraints = section_region(self.lowered, "## required constraints")
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
