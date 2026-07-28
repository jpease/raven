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
from raven_lib.models import ApplyPlan, Classification, OrphanClassification
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


class PrintDelegatesToRenderTest(unittest.TestCase):
    """The print_* functions stay the module's public surface; they must emit
    exactly what the renderer produces, or the split has introduced a second
    place where the report's wording lives."""

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
