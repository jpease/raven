import re
import unittest

from helpers import REPO_ROOT, RavenTestCase, raven


def section_region(text_lower, heading):
    """Return the slice of ``text_lower`` from ``heading`` up to the next
    ``## `` heading outside a fenced code block (or end of string).

    ``heading`` must already be a lowercase ``## ...`` string, since callers
    pass a pre-lowered copy of the document. Single module-level helper used
    by every skill-guidance test class below -- previously this existed as
    four near-duplicate copies under two names and two signatures.

    Fenced blocks are skipped because several skills document a markdown
    template inside a fence, and the template's own ``## `` lines would
    otherwise end the region at the first one, silently shrinking it to the
    prose above the fence. That misfires in both directions: an ``assertIn``
    fails confusingly for a phrase that is in the section, and an
    ``assertNotIn`` passes for a phrase sitting just past the cut.

    Fence tracking is deliberately simple -- any line whose first non-space
    characters are ``` or ~~~ toggles the state. A fence opened with a longer
    run to embed a shorter one would defeat it; no shipped skill does that,
    and the alternative is a markdown parser in a test helper.
    """
    start = text_lower.find(heading)
    if start == -1:
        raise AssertionError(f"expected a {heading!r} section")
    body_start = start + len(heading)
    in_fence = False
    position = 0
    for line in text_lower[body_start:].splitlines(keepends=True):
        stripped = line.lstrip()
        if stripped.startswith(("```", "~~~")):
            in_fence = not in_fence
        elif not in_fence and line.startswith("## "):
            return text_lower[start : body_start + position]
        position += len(line)
    return text_lower[start:]


class SectionRegionTests(unittest.TestCase):
    """Guards the helper every skill-guidance test below depends on.

    Its failure mode is silent: a region cut short still supports assertions,
    it just answers them about less of the document than the caller meant.
    """

    def test_fenced_headings_do_not_end_the_region(self):
        text = "## shape\n\n```markdown\n## goal\n\n## scope\n```\n\nafter the fence\n\n## next\n"
        region = section_region(text, "## shape")

        self.assertIn("## scope", region, "a heading inside the fence must not cut the region")
        self.assertIn("after the fence", region, "prose below the fence belongs to the section")
        self.assertNotIn("## next", region, "the real next heading still ends the region")

    def test_unfenced_heading_still_ends_the_region(self):
        region = section_region("## one\n\nbody\n\n## two\n\nother\n", "## one")

        self.assertIn("body", region)
        self.assertNotIn("other", region)

    def test_missing_heading_is_an_explicit_failure(self):
        with self.assertRaises(AssertionError):
            section_region("## one\n\nbody\n", "## absent")


SKILLS_DIR = REPO_ROOT / "common" / ".claude" / "skills"

#: Shipped skills allowed to pin a model, mapped to the reason. Empty by
#: design -- see the class docstring below and issue #208.
MODEL_PINNED_SKILLS: dict[str, str] = {}


class SkillModelOverrideTests(unittest.TestCase):
    """A shipped skill must not pin `model:` without a recorded reason.

    Claude Code documents the field as turn-scoped, not skill-scoped: "The
    override applies for the rest of the current turn and is not saved to
    settings; the session model resumes on your next prompt"
    (code.claude.com/docs/en/skills.md, fetched 2026-08-13). So `model: haiku`
    on a skill does not buy a cheap skill -- it downgrades every step that
    follows it in the same turn, including the review and verification work a
    Raven skill most often precedes. None of the shipped skills is terminal:
    even the end-of-unit ones (`raven-commit`, `raven-context-hygiene`) are
    routinely invoked mid-turn with work still to come.

    A future skill that genuinely wants a smaller model should either accept
    that turn-wide scope deliberately and register here, or use `context:
    fork`, which scopes the model to a forked subagent instead.
    """

    def _skill_files(self):
        files = sorted(SKILLS_DIR.glob("*/SKILL.md"))
        self.assertNotEqual(files, [], f"no shipped skills found under {SKILLS_DIR}")
        return files

    def test_no_shipped_skill_pins_a_model_without_a_recorded_reason(self):
        for path in self._skill_files():
            with self.subTest(skill=path.parent.name):
                pinned = re.search(
                    r"^model:\s*(\S+)", path.read_text(encoding="utf-8"), re.MULTILINE
                )
                if path.parent.name in MODEL_PINNED_SKILLS:
                    self.assertIsNotNone(
                        pinned, "listed in MODEL_PINNED_SKILLS but pins no model -- drop the entry"
                    )
                    continue
                self.assertIsNone(
                    pinned,
                    f"{path.parent.name} pins model: {pinned.group(1) if pinned else ''} -- the "
                    "override lasts the rest of the turn, not just the skill (issue #208). "
                    "Remove it, use context: fork, or register it in MODEL_PINNED_SKILLS.",
                )


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
    """Guards the scope-ceiling guardrail added for issue #120, and the
    test-before-implementation ordering fixed for issue #132.

    Reads the canonical skill source directly (not the installed root
    copy) since `common/.agents/skills/` is where edits must land.
    """

    def setUp(self):
        path = REPO_ROOT / "common" / ".agents" / "skills" / "raven-implement-feature" / "SKILL.md"
        self.content = path.read_text(encoding="utf-8")

        write_tests_path = (
            REPO_ROOT / "common" / ".agents" / "skills" / "raven-write-tests" / "SKILL.md"
        )
        self.write_tests_content = write_tests_path.read_text(encoding="utf-8")

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

    def test_agrees_with_raven_write_tests_on_test_implementation_ordering(self):
        """Issue #132: raven-write-tests and raven-implement-feature previously
        gave opposite orderings of the tests-vs-implementation step -- both are
        `raven-*` skills, so AGENTS.md's "prefer the raven-* skill" precedence
        rule cannot arbitrate between them.

        Steps are located by string search rather than step number, since the
        numbering has already shifted once (issue #120) and will again. The
        expected direction is derived from raven-write-tests' own Required
        Constraints sentence -- the skill that owns this policy -- rather than
        hardcoded here, so the test also catches raven-write-tests drifting to
        the opposite ordering, not only raven-implement-feature doing so.
        """
        write_tests_lower = self.write_tests_content.lower()
        implement_lower = self.content.lower()

        # raven-write-tests owns the policy, so assert it still states it. Read
        # the ordering-bearing clause directly rather than inferring direction
        # from where two phrases happen to fall in the file: "do not change the
        # implementation before you add or update tests" states the same policy
        # with the phrases reversed, and an index comparison would read that as
        # test-after and then demand raven-implement-feature match the misread
        # -- enforcing the contradiction instead of catching it.
        self.assertIn(
            "before changing the implementation",
            write_tests_lower,
            "expected raven-write-tests to state that tests come before the "
            "implementation; if that policy genuinely changed, this test is the "
            "deliberate place to change it",
        )

        if_tests_index = implement_lower.find("add or update tests")
        if_implementation_index = implement_lower.find("implement using existing conventions")
        self.assertNotEqual(
            if_tests_index, -1, "expected raven-implement-feature to have a tests step"
        )
        self.assertNotEqual(
            if_implementation_index,
            -1,
            "expected raven-implement-feature to have an implementation step",
        )

        self.assertLess(
            if_tests_index,
            if_implementation_index,
            "raven-implement-feature must order its tests step before its "
            "implementation step, matching the policy raven-write-tests states "
            "-- the two shipped skills must not disagree",
        )

    def process_steps(self):
        """Return the skill's Process section as a list of numbered-step strings.

        Ordering assertions above compare character offsets, which cannot
        express "a step sits between these two steps" -- an anchor phrase can
        land mid-step and still satisfy an offset comparison. Splitting into
        steps first makes the between-ness structural instead.
        """
        region = section_region(self.content.lower(), "## process")
        return [step.strip() for step in re.split(r"\n\d+\. ", region)[1:]]

    def test_a_red_run_step_falls_between_the_tests_and_implementation_steps(self):
        """Issue #132 moved the tests step above the implementation step but left
        the "expect the new test to fail" clause attached to the run-tests step
        that stayed below it -- asking for an observation whose window had
        already closed. Test-first without an observed red run cannot distinguish
        a correct new test from one that would have passed anyway.
        """
        steps = self.process_steps()
        tests_step = next(i for i, s in enumerate(steps) if "add or update tests" in s)
        implement_step = next(
            i for i, s in enumerate(steps) if "implement using existing conventions" in s
        )

        between = steps[tests_step + 1 : implement_step]
        self.assertTrue(
            any("run" in step and "fail" in step for step in between),
            "expected a step between the tests step and the implementation step "
            "that runs the new tests and confirms they fail -- test-first is only "
            "meaningful if the red state is actually observed",
        )

    def test_the_post_implementation_step_does_not_ask_to_observe_a_failure(self):
        """The regression guard for the #132 drift itself: once implementation has
        landed, an instruction to expect failure is unfollowable, so it must not
        survive on any step below the implementation step.
        """
        steps = self.process_steps()
        implement_step = next(
            i for i, s in enumerate(steps) if "implement using existing conventions" in s
        )

        for step in steps[implement_step + 1 :]:
            self.assertNotIn(
                "fail",
                step,
                "a step after the implementation step must not ask to expect or "
                "observe a test failure -- by then the red state is unobservable",
            )


class WriteTestsSkillTests(unittest.TestCase):
    """Guards the red-observation requirement.

    raven-write-tests owns test policy, so the requirement lives here rather
    than inline in raven-implement-feature: bugfix work reaches this skill via
    raven-debug-failure without passing through the feature skill at all, and
    duplicating the policy in two `raven-*` skills is what issue #132 had to
    untangle.
    """

    def setUp(self):
        path = REPO_ROOT / "common" / ".agents" / "skills" / "raven-write-tests" / "SKILL.md"
        self.content = path.read_text(encoding="utf-8")
        self.lowered = self.content.lower()

    def test_constraints_require_observing_the_new_test_fail_before_implementing(self):
        region = section_region(self.lowered, "## required constraints")

        self.assertTrue(
            any(
                "run" in line and "fail" in line
                for line in region.splitlines()
                if line.startswith("- ")
            ),
            "expected a Required Constraint that the new test is run and seen to "
            "fail before the implementation lands -- stating the ordering alone "
            "leaves an unrun test indistinguishable from one that always passed",
        )

    def test_the_red_run_names_the_wrong_reason_failure_modes(self):
        """A red run only proves anything if the failure is the asserted behavior.
        Raven ships Swift, Go, and TypeScript trees where a brand-new test's first
        failure is routinely a compile or collection error, which proves nothing.
        """
        region = section_region(self.lowered, "## required constraints")

        self.assertTrue(
            any(term in region for term in ("compile", "import", "collection", "fixture")),
            "expected the red-run constraint to name a wrong-reason failure mode "
            "(compile/import/collection/fixture error), not just 'must fail'",
        )

    def test_rationalization_check_table_has_full_row_coverage(self):
        # Structural row count, consistent with the same check on
        # raven-task-complete and raven-debloat: what matters is that the table
        # keeps its full set of rows, not any one rebuttal's phrasing.
        region = section_region(self.lowered, "## rationalization check")

        self.assertGreaterEqual(
            region.count("\n|"),
            7,
            "expected a header/divider row plus at least 5 rationalization rows, "
            "including one for skipping the red run",
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
            85,
            "raven-plan/SKILL.md should stay skimmable even after the completion-criteria, "
            "interrogation, and fresh-context additions",
        )

    def test_interrogation_precedes_writing_the_plan(self):
        region = section_region(self.lowered, "## interrogate first")

        self.assertIn(
            "propose the first approach yourself",
            region,
            "expected the agent to propose the first approach rather than react to the user's",
        )
        self.assertIn(
            "write no code",
            region,
            "expected an explicit no-code rule during the design discussion",
        )

    def test_interrogation_runs_a_pre_mortem_for_pause_and_ask_work(self):
        # Pause And Ask names the categories to stop at; nothing asked the
        # planner to name the failure the category stands for before choosing
        # an approach, which is what makes the stop a judgment instead of a
        # label match.
        region = section_region(self.lowered, "## interrogate first")

        self.assertIn(
            "pre-mortem",
            region,
            "expected a pre-mortem question during interrogation",
        )
        self.assertIn(
            "pause and ask",
            region,
            "expected the pre-mortem to be scoped to the AGENTS.md Pause And Ask "
            "categories rather than fired on every plan",
        )

    def test_alternatives_require_one_generated_by_inverting_a_constraint(self):
        # Alternatives filled by varying the chosen approach are one design in
        # three costumes -- the same failure as writing them afterwards, which
        # the section above already guards.
        region = section_region(self.lowered, "## durable plan shape")

        self.assertIn(
            "inverting a constraint",
            region,
            "expected at least one alternative to come from inverting a constraint",
        )

    def test_plan_shape_records_rejected_alternatives(self):
        region = section_region(self.lowered, "## durable plan shape")

        self.assertIn(
            "## alternatives (approach rejected / why / what would reopen it)",
            region,
            "expected the plan template to carry an Alternatives section",
        )
        self.assertIn(
            "while the argument is live",
            region,
            "expected Alternatives to be filled during the design discussion, "
            "not reconstructed afterwards",
        )

    def test_fresh_context_check_is_a_negative_control(self):
        region = section_region(self.lowered, "## fresh-context check")

        # The check is worthless if the reader carries the authoring session's
        # context, and worthless again if holes are patched in chat instead of
        # in the artifact. Both halves are guarded verbatim.
        self.assertIn(
            "no conversation history",
            region,
            "expected the fresh reader to be denied the authoring session's context",
        )
        self.assertIn(
            "write the answer into the plan",
            region,
            "expected holes to be closed in the artifact rather than in chat",
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
        unrequested doc edits (issue #127).
        """
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
            "generic",
            "go",
            "lua",
            "python",
            "ruby",
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
        # Raised from 65 when the discovered-work disposition step landed: the
        # step, its rationalization row, and its Output line cost 6 lines,
        # taking the file from 58 to 64 -- inside the old ceiling by a single
        # line, which is no headroom at all. Headroom here is one iteration,
        # not a budget to spend.
        self.assertLess(
            len(self.content.splitlines()),
            75,
            "raven-task-complete/SKILL.md should stay under ~75 lines",
        )

    def test_process_requires_dispositioning_discovered_work(self):
        # The gate: without a step here, nothing forces the agent to account for
        # findings at the one moment it still has full recall of them.
        region = section_region(self.lowered, "## process")
        self.assertIn(
            "raven-triage-discovery",
            region,
            "expected a Process step routing discovered work to raven-triage-discovery",
        )

    def test_output_requires_stating_discovered_work(self):
        region = section_region(self.lowered, "## output")
        self.assertIn(
            "discovered work",
            region,
            "expected the Output contract to require stating discovered work, "
            "so silence is not a passing state",
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


class TriageDiscoverySkillTests(unittest.TestCase):
    """Guards the discovered-work disposition contract.

    Reads the canonical skill source directly (not the installed root
    copy) since `common/.agents/skills/` is where edits must land.
    """

    def setUp(self):
        path = REPO_ROOT / "common" / ".agents" / "skills" / "raven-triage-discovery" / "SKILL.md"
        self.content = path.read_text(encoding="utf-8")
        self.lowered = self.content.lower()

    def test_stays_under_line_ceiling(self):
        # Same basis as raven-task-complete: this is invoked mid-task, so its
        # cost is paid at the moment context is scarcest. Keep it short.
        self.assertLess(
            len(self.content.splitlines()),
            75,
            "raven-triage-discovery/SKILL.md should stay under ~75 lines",
        )

    def test_declares_the_required_sections(self):
        for heading in (
            "## skip when",
            "## required constraints",
            "## dispositions",
            "## filing",
            "## rationalization check",
            "## output",
        ):
            with self.subTest(heading=heading):
                self.assertIn(heading, self.lowered)

    def test_dispositions_table_names_all_three_buckets(self):
        region = section_region(self.lowered, "## dispositions")
        for bucket in ("fold in", "file", "drop"):
            with self.subTest(bucket=bucket):
                self.assertIn(
                    bucket,
                    region,
                    f"the disposition table must name the {bucket.upper()} bucket",
                )

    def test_comment_only_is_prohibited_as_a_disposition(self):
        # The substance of the whole skill: commenting on the issue or epic is
        # the observed failure mode, so the prohibition is load-bearing text,
        # not decorative wording.
        region = section_region(self.lowered, "## required constraints")
        self.assertIn(
            "is not a disposition",
            region,
            "expected a Required Constraint stating that a comment on the "
            "issue or its epic is not a disposition",
        )

    def test_ambiguity_resolves_to_filing(self):
        # Without a stated tiebreak, ambiguous findings drift to the cheapest
        # action -- which is exactly how they became comments.
        region = section_region(self.lowered, "## required constraints")
        self.assertIn(
            "is unclear, file",
            region,
            "expected a Required Constraint resolving FILE-vs-DROP ambiguity toward FILE",
        )


class IssueSkillTriageReferenceTests(unittest.TestCase):
    """Both issue skills must delegate the disposition decision.

    The rule they used to own -- "if new durable work is discovered: create
    follow-up issues" -- left `durable` undefined, and these skills are
    platform-gated, so neither ships at platform=none. The definition lives
    in raven-triage-discovery; these skills supply only tracker mechanics.
    """

    SKILLS_DIR = REPO_ROOT / "common" / ".agents" / "skills"

    def _skill(self, name):
        return (self.SKILLS_DIR / name / "SKILL.md").read_text(encoding="utf-8").lower()

    def test_both_issue_skills_route_discovered_work_to_the_triage_skill(self):
        for name in ("raven-github-issues", "raven-gitlab-issues"):
            with self.subTest(skill=name):
                self.assertIn(
                    "raven-triage-discovery",
                    self._skill(name),
                    "issue skill must route discovered work to "
                    "raven-triage-discovery rather than restating a vague rule",
                )

    def test_neither_issue_skill_still_carries_the_undefined_durable_rule(self):
        for name in ("raven-github-issues", "raven-gitlab-issues"):
            with self.subTest(skill=name):
                self.assertNotIn(
                    "new durable work is discovered",
                    self._skill(name),
                    "the undefined 'durable work' phrasing is what let findings "
                    "drift to comments; it must not survive alongside the "
                    "replacement rule",
                )

    def test_both_issue_skills_prohibit_the_comment_as_terminal_record(self):
        for name in ("raven-github-issues", "raven-gitlab-issues"):
            with self.subTest(skill=name):
                self.assertIn(
                    "pointer to a filed issue",
                    self._skill(name),
                    "issue skills must state that a comment is legitimate only "
                    "as a pointer to a filed issue",
                )


class SubagentOutOfScopeContractTests(unittest.TestCase):
    """Every shipped reviewer agent must return out-of-scope findings.

    Nothing else keeps `common/.claude/agents/*.md` and
    `common/.codex/agents/*.toml` in sync -- they carry the same prose in
    two formats, so a change applied to one silently diverges from the
    other. This class is the only guard on that pair.
    """

    CLAUDE_DIR = REPO_ROOT / "common" / ".claude" / "agents"
    CODEX_DIR = REPO_ROOT / "common" / ".codex" / "agents"
    REQUIRED = "## out of scope findings"

    def test_both_adapter_trees_ship_the_same_agents(self):
        claude = {p.stem for p in self.CLAUDE_DIR.glob("raven-*.md")}
        codex = {p.stem for p in self.CODEX_DIR.glob("raven-*.toml")}
        self.assertTrue(claude, "expected common/.claude/agents to ship raven-* agents")
        self.assertEqual(
            claude,
            codex,
            "adapter agent trees have diverged; one harness would ship a reviewer the other lacks",
        )

    def test_every_agent_requires_the_out_of_scope_section(self):
        paths = sorted(self.CLAUDE_DIR.glob("raven-*.md")) + sorted(
            self.CODEX_DIR.glob("raven-*.toml")
        )
        self.assertEqual(
            len(paths),
            10,
            f"expected 5 Claude + 5 Codex agent contracts, found {len(paths)}",
        )
        for path in paths:
            with self.subTest(agent=f"{path.parent.name}/{path.name}"):
                self.assertIn(
                    self.REQUIRED,
                    path.read_text(encoding="utf-8").lower(),
                    "agent contract must require an '## Out Of Scope Findings' "
                    "section; without it the parent silently absorbs whatever "
                    "the sub-agent noticed but was not asked about",
                )


class AdapterNeutralScriptReferenceTests(unittest.TestCase):
    """`.agents/skills/` is the agent-neutral canonical tree (see
    `.claude/docs/raven-agent-compatibility.md`), but the helper scripts it
    invokes are installed per adapter: `.claude/scripts/` for Claude Code and
    `.codex/scripts/` for Codex. A canonical skill that names only the Claude
    path sends a Codex-only install at a file that was never installed.

    `raven-skeleton` established the fix: name both adapter paths wherever a
    helper script is invoked. This test holds every canonical skill to it.
    """

    SKILLS_DIR = REPO_ROOT / "common" / ".agents" / "skills"

    def test_every_skill_naming_a_claude_script_also_names_the_codex_one(self):
        offenders = []
        for skill in sorted(self.SKILLS_DIR.glob("*/SKILL.md")):
            text = skill.read_text(encoding="utf-8")
            claude_scripts = set(re.findall(r"\.claude/scripts/([\w.-]+)", text))
            codex_scripts = set(re.findall(r"\.codex/scripts/([\w.-]+)", text))
            missing = claude_scripts - codex_scripts
            if missing:
                offenders.append(f"{skill.parent.name}: {', '.join(sorted(missing))}")
        self.assertEqual(
            offenders,
            [],
            "canonical skills naming a .claude/scripts/ helper without its "
            ".codex/scripts/ counterpart (Codex-only installs would follow a "
            f"path that does not exist): {offenders}",
        )

    def test_the_adapter_script_directories_ship_the_same_helpers(self):
        # The branch the skills document is only honest if both adapters
        # actually ship the helper. Compare the shipped trees, not the prose.
        claude = {p.name for p in (REPO_ROOT / "common" / ".claude" / "scripts").glob("raven-*")}
        codex = {p.name for p in (REPO_ROOT / "common" / ".codex" / "scripts").glob("raven-*")}
        self.assertTrue(claude, "expected common/.claude/scripts to ship raven-* helpers")
        self.assertEqual(
            claude,
            codex,
            "adapter script trees have diverged; a skill branching on adapter "
            "would point Codex at a helper it never receives",
        )


class ContextHygieneSkillTests(unittest.TestCase):
    """Guards the harness-aware fix for the unconditional /clear interrupt
    (issue #145): the manual /clear-or-/compact prompt must become
    conditional on whether the current harness states it manages context
    automatically, without losing the manual offer for harnesses that don't
    make that claim.

    Reads the canonical skill source directly (not an installed copy),
    since `common/.agents/skills/` is where edits must land.
    """

    def setUp(self):
        path = REPO_ROOT / "common" / ".agents" / "skills" / "raven-context-hygiene" / "SKILL.md"
        self.content = path.read_text(encoding="utf-8")
        self.lowered = self.content.lower()

    def test_process_still_offers_the_manual_clear_compact_choice(self):
        # The unfamiliar-harness path must not lose the explicit offer --
        # only Claude Code's unconditional interrupt was the bug.
        region = section_region(self.lowered, "## process")
        self.assertIn("/clear", region)
        self.assertIn("/compact", region)

    def test_process_keys_off_harness_stated_auto_compaction(self):
        # The fix's substance: the agent checks its own harness's stated
        # behavior (Claude Code states context is summarized/compacted
        # automatically) before deciding whether to interrupt.
        region = section_region(self.lowered, "## process")
        self.assertIn(
            "automatically",
            region,
            "expected Process to key off harness-stated automatic context management",
        )

    def test_manual_prompt_is_no_longer_an_unconditional_step(self):
        # The bug: step 2 was a bare "Ask: ..." with no condition attached.
        # Guard against regressing to that literal shape -- the ask must be
        # gated behind a not-managed-automatically branch, not simply be
        # the next numbered step.
        region = section_region(self.lowered, "## process")
        self.assertNotIn(
            "\n2. ask:",
            region,
            "the /clear prompt must be conditional, not an unconditional step 2",
        )

    def test_fallback_branch_does_not_name_harness_products(self):
        # Issue #163: the fallback branch (harnesses that don't make capability
        # claims) must not name specific products as examples of lacking context
        # management. The capability-check branch (line 19) can name Claude Code
        # as a positive illustration, but the fallback branch must use generic
        # terms ("unfamiliar harness") instead of "Codex" or other product names.
        region = section_region(self.lowered, "## process")
        # Extract just the "if not" fallback clause
        if_not_start = region.find("- if not (")
        self.assertNotEqual(if_not_start, -1, "expected to find the 'if not' fallback clause")
        if_not_clause = region[if_not_start:]
        next_bullet = if_not_clause.find("\n   - if")
        if_not_clause = if_not_clause if next_bullet == -1 else if_not_clause[:next_bullet]
        # A denylist rather than a single name: the criterion is that *no*
        # harness is named here, and an unlisted newcomer only weakens this
        # test, never breaks an honest commit.
        for product in ("codex", "cursor", "windsurf", "copilot", "aider", "cline", "gemini"):
            self.assertNotIn(
                product,
                if_not_clause,
                f"fallback branch must not name {product} as a harness lacking "
                "automatic context management",
            )


class SecurityReviewSkillTests(unittest.TestCase):
    """Guards issue #161: the Required Constraints bullets must name each
    Semgrep interface (MCP scan, MCP custom-rule, CLI) with the invocation
    it actually supports, instead of presenting `--config auto` and `p/*`
    registry ruleset names as if they were arguments to the MCP scan tool.

    Reads the canonical skill source directly (not an installed copy),
    since `common/.agents/skills/` is where edits must land. Assertions
    pin Raven's own prose hygiene -- something Raven owns and can always
    fix -- not the third-party Semgrep MCP server's argument schema, which
    is out of Raven's control and deliberately left unpinned (see issue
    #161's non-goals).
    """

    def setUp(self):
        path = REPO_ROOT / "common" / ".agents" / "skills" / "raven-security-review" / "SKILL.md"
        self.content = path.read_text(encoding="utf-8")
        self.lowered = self.content.lower()

    def test_mcp_scan_tool_never_appears_with_a_cli_config_flag_or_ruleset(self):
        # `mcp__semgrep__semgrep_scan` (and its `_with_custom_rule` sibling,
        # a substring match) take no config argument -- neither must ever
        # share a line with a `--config` flag or a `p/*` registry ruleset
        # name, both of which are CLI-only forms.
        for line in self.content.splitlines():
            if "mcp__semgrep__semgrep_scan" not in line:
                continue
            self.assertNotIn(
                "--config",
                line,
                f"MCP scan bullet must not carry a CLI --config flag: {line!r}",
            )
            self.assertNotRegex(
                line,
                r"`p/[\w-]+`",
                f"MCP scan bullet must not carry a CLI p/* ruleset name: {line!r}",
            )

    def test_config_and_ruleset_forms_appear_only_in_cli_context(self):
        for line in self.content.splitlines():
            if "--config" not in line and not re.search(r"`p/[\w-]+`", line):
                continue
            self.assertIn(
                "CLI",
                line,
                f"--config/p/* forms must be presented in a CLI-labeled bullet: {line!r}",
            )
            self.assertRegex(
                line,
                r"semgrep --config",
                f"expected the bare `semgrep --config ...` CLI invocation form: {line!r}",
            )

    def test_custom_rule_tool_is_described_as_taking_an_inline_rule(self):
        region = section_region(self.lowered, "## required constraints")
        self.assertIn("semgrep_scan_with_custom_rule", region)
        self.assertIn(
            "inline rule",
            region,
            "expected semgrep_scan_with_custom_rule to be described as taking "
            "an inline rule body, not a registry ruleset name",
        )


if __name__ == "__main__":
    unittest.main()
