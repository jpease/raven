"""Tests for the pure report renderers in raven_lib.plan.

These previously could only be reached through captured stdout, which made the
report's shape (which sections appear, in what order, separated how) awkward to
assert and easy to get subtly wrong. The `render_*` functions return the same
text the `print_*` functions emit, so the content is asserted directly here.
"""

import contextlib
import io
import unittest

from helpers import raven  # noqa: F401  (ensures scripts/ is on sys.path)
from raven_lib.models import (
    ApplyPlan,
    Classification,
    DeactivatedClassification,
    OrphanClassification,
)
from raven_lib.plan import (
    print_dry_run_summary,
    print_section,
    render_apply_summary,
    render_dry_run_plan,
    render_dry_run_summary,
    render_section,
)


def classification(**overrides) -> Classification:
    fields = {
        "will_copy": [],
        "will_upgrade": [],
        "identical": [],
        "needs_merge": [],
        "unknown_existing": [],
        "excluded": [],
        "local_only": [],
    }
    fields.update(overrides)
    return Classification(**fields)


def apply_plan(**overrides) -> ApplyPlan:
    effective = overrides.pop("effective_classification", None) or classification()
    fields = {
        "requested_overrides": [],
        "overwritten": [],
        "newly_copied_overrides": [],
        "will_copy": [],
        "will_upgrade": [],
        "identical": [],
        "needs_merge": [],
        "unknown_existing": [],
        "effective_classification": effective,
        "adopt_claude_symlink": False,
        "guided_merge_paths": [],
    }
    fields.update(overrides)
    return ApplyPlan(**fields)


def orphan_classification(**overrides) -> OrphanClassification:
    fields = {"will_remove": [], "orphan_modified": [], "already_gone": []}
    fields.update(overrides)
    return OrphanClassification(**fields)


def deactivated_classification(**overrides) -> DeactivatedClassification:
    fields = {"removable": [], "preserved": [], "absent": []}
    fields.update(overrides)
    return DeactivatedClassification(**fields)


class RenderSectionTest(unittest.TestCase):
    def test_lists_each_path_indented_under_the_title(self):
        self.assertEqual(
            render_section("Title:", ["a.md", "b/c.md"]),
            "Title:\n  a.md\n  b/c.md",
        )

    def test_an_empty_list_still_reports_the_section(self):
        # A silently omitted section reads as "nothing to say here"; "(none)"
        # says the question was asked and the answer was zero.
        self.assertEqual(render_section("Title:", []), "Title:\n  (none)")

    def test_no_trailing_newline_so_callers_control_separation(self):
        self.assertFalse(render_section("Title:", ["a"]).endswith("\n"))


class RenderDryRunSummaryTest(unittest.TestCase):
    def test_always_reports_the_five_core_sections_and_the_preview_notice(self):
        text = render_dry_run_summary(classification())
        for expected in (
            "Will copy new Raven files:",
            "Will upgrade unchanged Raven-managed files:",
            "Already up to date; will not copy:",
            "Manual merge required (locally modified",
            "Manual merge required (existing files Raven does not manage",
            "Preview only.",
        ):
            self.assertIn(expected, text)

    def test_local_only_section_appears_only_when_there_is_local_customization(self):
        heading = "Locally customized; template unchanged"
        self.assertNotIn(heading, render_dry_run_summary(classification()))
        self.assertIn(heading, render_dry_run_summary(classification(local_only=["a.md"])))

    def test_sections_are_separated_by_a_blank_line(self):
        text = render_dry_run_summary(classification(will_copy=["a.md"]))
        self.assertIn("  a.md\n\nWill upgrade unchanged Raven-managed files:", text)


class RenderApplySummaryTest(unittest.TestCase):
    def _summary(self, **overrides) -> str:
        fields = {
            "copied": [],
            "upgraded": [],
            "overwritten": [],
            "adopted_claude": [],
            "identical": [],
            "needs_merge": [],
            "unknown_existing": [],
            "removed_orphans": [],
            "orphan_modified": [],
        }
        fields.update(overrides)
        return render_apply_summary(**fields)

    def test_reports_the_copied_count_even_when_nothing_was_copied(self):
        self.assertEqual(self._summary(), "Copied 0 file(s):\n  (none)")

    def test_optional_sections_are_omitted_when_empty(self):
        text = self._summary(copied=["a.md"])
        self.assertNotIn("Upgraded", text)
        self.assertNotIn("Already up to date", text)
        self.assertNotIn("Manual merge still required", text)

    def test_merge_warnings_are_marked_so_they_are_not_missed(self):
        # These are the two states where the upgrade deliberately left a file
        # alone; they must not read like routine progress lines.
        text = self._summary(needs_merge=["a.md"], unknown_existing=["b.md"])
        self.assertEqual(text.count("!!! Manual merge still required"), 2)

    def test_counts_reflect_the_paths_listed(self):
        text = self._summary(copied=["a", "b"], upgraded=["c"], removed_orphans=["d", "e", "f"])
        self.assertIn("Copied 2 file(s):", text)
        self.assertIn("Upgraded 1 unchanged Raven-managed file(s):", text)
        self.assertIn("Removed 3 orphaned file(s)", text)

    def test_omitted_deactivated_arguments_render_no_deactivated_section(self):
        # Backward-compat: existing callers that only pass the orphan args
        # must not crash, and must not gain a spurious empty section.
        text = self._summary()
        self.assertNotIn("deactivated by config", text)

    def test_deactivated_sections_distinguish_removed_from_preserved_and_from_orphans(self):
        text = self._summary(
            removed_deactivated=["skill-a.md"], deactivated_preserved=["skill-b.md"]
        )
        self.assertIn("Removed 1 skill(s) deactivated by config", text)
        self.assertIn("Deactivated by config but left in place because you modified them", text)
        self.assertIn("skill-a.md", text)
        self.assertIn("skill-b.md", text)
        self.assertNotIn("orphaned file(s) the template no longer ships", text)
        self.assertNotIn("Orphaned but left in place", text)

    def test_omitted_deactivated_stale_and_customized_render_no_section(self):
        # Backward-compat: existing callers that only pass deactivated_preserved
        # (or nothing) must not gain a spurious empty stale/customized section.
        text = self._summary(deactivated_preserved=["skill-b.md"])
        self.assertNotIn("stale", text.lower())
        self.assertNotIn("customiz", text.lower())

    def test_deactivated_stale_section_has_its_own_distinct_wording(self) -> None:
        # #179: a stale-but-pristine baseline must never be reported with the
        # "you modified them" wording used for a genuine local edit.
        text = self._summary(deactivated_stale=["skill-c.md"])
        self.assertIn("skill-c.md", text)
        self.assertIn("stale", text.lower())
        self.assertIn("raven accept", text)
        self.assertNotIn("you modified them", text)

    def test_deactivated_customized_section_has_its_own_distinct_wording(self) -> None:
        # #179: an accepted customization must never be reported with the
        # "you modified them" wording either.
        text = self._summary(deactivated_customized=["skill-d.md"])
        self.assertIn("skill-d.md", text)
        self.assertIn("accepted customization", text.lower())
        self.assertNotIn("you modified them", text)

    def test_deactivated_stale_and_customized_and_modified_are_all_distinct(self) -> None:
        text = self._summary(
            deactivated_preserved=["modified.md"],
            deactivated_stale=["stale.md"],
            deactivated_customized=["customized.md"],
        )
        for path in ("modified.md", "stale.md", "customized.md"):
            self.assertIn(path, text)
        self.assertIn("you modified them", text)
        self.assertIn("stale", text.lower())
        self.assertIn("accepted customization", text.lower())


class RenderDryRunPlanTest(unittest.TestCase):
    def test_minimal_plan_renders_just_the_summary(self):
        text = render_dry_run_plan(
            apply_plan(), orphan_classification(), show_claude_symlink_note=False
        )
        self.assertTrue(text.startswith("Will copy new Raven files:"))
        self.assertIn("Preview only.", text)

    def test_override_sections_appear_only_when_overrides_were_requested(self):
        heading = "Would overwrite explicitly requested file(s):"
        self.assertNotIn(
            heading,
            render_dry_run_plan(
                apply_plan(overwritten=["a.md"]),
                orphan_classification(),
                show_claude_symlink_note=False,
            ),
        )
        self.assertIn(
            heading,
            render_dry_run_plan(
                apply_plan(requested_overrides=["a.md"], overwritten=["a.md"]),
                orphan_classification(),
                show_claude_symlink_note=False,
            ),
        )

    def test_claude_symlink_note_is_controlled_by_the_caller(self):
        # The note depends on a filesystem probe the shell performs, so the
        # renderer must not try to decide it.
        note = "CLAUDE.md exists as a regular destination file."
        self.assertNotIn(
            note,
            render_dry_run_plan(
                apply_plan(), orphan_classification(), show_claude_symlink_note=False
            ),
        )
        self.assertIn(
            note,
            render_dry_run_plan(
                apply_plan(), orphan_classification(), show_claude_symlink_note=True
            ),
        )

    def test_adopting_the_symlink_lists_both_affected_paths(self):
        text = render_dry_run_plan(
            apply_plan(adopt_claude_symlink=True),
            orphan_classification(),
            show_claude_symlink_note=False,
        )
        self.assertIn("Would adopt CLAUDE.md compatibility symlink:", text)
        self.assertIn("CLAUDE.md.bak", text)
        self.assertIn("CLAUDE.md", text)

    def test_orphan_sections_distinguish_removable_from_locally_modified(self):
        text = render_dry_run_plan(
            apply_plan(),
            orphan_classification(will_remove=["gone.md"], orphan_modified=["kept.md"]),
            show_claude_symlink_note=False,
        )
        self.assertIn("Will remove orphaned Raven files", text)
        self.assertIn("Orphaned but locally modified; left in place", text)
        self.assertIn("gone.md", text)
        self.assertIn("kept.md", text)

    def test_omitted_deactivated_argument_renders_no_deactivated_section(self):
        # Backward-compat: existing callers that only pass orphans must not
        # crash, and must not gain a spurious empty section.
        text = render_dry_run_plan(
            apply_plan(), orphan_classification(), show_claude_symlink_note=False
        )
        self.assertNotIn("deactivated by config", text)

    def test_deactivated_sections_distinguish_removable_from_preserved_and_from_orphans(self):
        text = render_dry_run_plan(
            apply_plan(),
            orphan_classification(),
            deactivated_classification(removable=["skill-a.md"], preserved=["skill-b.md"]),
            show_claude_symlink_note=False,
        )
        self.assertIn("Would remove skill(s) deactivated by config", text)
        self.assertIn("Deactivated by config but locally modified; left in place", text)
        self.assertIn("skill-a.md", text)
        self.assertIn("skill-b.md", text)
        # Labeled distinctly from the orphan wording, per #160's acceptance
        # criteria: never described as the template no longer shipping it.
        self.assertNotIn("Will remove orphaned Raven files", text)
        self.assertNotIn("Orphaned but locally modified", text)

    def test_deactivated_stale_and_customized_get_their_own_sections(self) -> None:
        # #179: `preserved` (fails unmodified_baseline) is not one
        # undifferentiated bucket -- stale-baseline and accepted-customization
        # are informational subsets of it that must render with their own,
        # distinct wording, never "you modified them"/"locally modified".
        text = render_dry_run_plan(
            apply_plan(),
            orphan_classification(),
            deactivated_classification(
                preserved=["modified.md", "stale.md", "customized.md"],
                stale=["stale.md"],
                customized=["customized.md"],
            ),
            show_claude_symlink_note=False,
        )
        self.assertIn("modified.md", text)
        self.assertIn("stale.md", text)
        self.assertIn("customized.md", text)
        self.assertIn("Deactivated by config but locally modified; left in place", text)
        self.assertIn("raven accept", text)
        self.assertIn("accepted customization".lower(), text.lower())
        # The genuinely-modified section must list only the truly-modified
        # path, not the stale or customized ones.
        modified_section_start = text.index("Deactivated by config but locally modified")
        modified_section = text[modified_section_start : modified_section_start + 200]
        self.assertIn("modified.md", modified_section)
        self.assertNotIn("stale.md", modified_section)
        self.assertNotIn("customized.md", modified_section)

    def test_omitted_deactivated_stale_and_customized_render_no_extra_section(self) -> None:
        text = render_dry_run_plan(
            apply_plan(),
            orphan_classification(),
            deactivated_classification(preserved=["modified.md"]),
            show_claude_symlink_note=False,
        )
        self.assertNotIn("raven accept", text)
        self.assertNotIn("accepted customization", text.lower())


class PrintDelegatesToRenderTest(unittest.TestCase):
    """The print_* functions stay the module's public surface; they must emit
    exactly what the renderer produces, or the split has introduced a second
    place where the report's wording lives.
    """

    def test_print_section_emits_the_rendered_text(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            print_section("Title:", ["a.md"])
        self.assertEqual(buf.getvalue(), render_section("Title:", ["a.md"]) + "\n")

    def test_print_dry_run_summary_emits_the_rendered_text(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            print_dry_run_summary(classification(will_copy=["a.md"]))
        self.assertEqual(
            buf.getvalue(),
            render_dry_run_summary(classification(will_copy=["a.md"])) + "\n",
        )


if __name__ == "__main__":
    unittest.main()
