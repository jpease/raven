import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path

from helpers import REPO_ROOT, load_script_module

SELF_CHECK = REPO_ROOT / "scripts" / "self-check.py"

# The three always-loaded files that make up the "python" language profile in
# validate_aggregate_budget(). Other profiles share AGENTS.md + security
# but point at a different language rules file; leaving those language
# files absent makes the validator skip those profiles, so a test only needs
# to populate this one profile to drive the pass/fail paths.
PYTHON_PROFILE_FILES = (
    "common/AGENTS.md",
    "common/.claude/rules/raven-security.md",
    "python/.claude/rules/raven-python.md",
)

# Mirrors the "python" cap in validate_aggregate_budget(). Kept here so the
# test's word totals straddle the real threshold; update both together if the
# budget changes.
PYTHON_BUDGET = 1918


def _write_words(path: Path, count: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(" ".join(["word"] * count), encoding="utf-8")


class AggregateBudgetTest(unittest.TestCase):
    def setUp(self) -> None:
        # load_script_module returns a fresh module instance per call, so
        # monkeypatching REPO_ROOT here is isolated to this test.
        self.module = load_script_module("self_check_under_test", SELF_CHECK)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.module.REPO_ROOT = self.root

    def _populate(self, words_per_file: int) -> None:
        for rel in PYTHON_PROFILE_FILES:
            _write_words(self.root / rel, words_per_file)

    def test_passes_when_profile_sum_under_budget(self) -> None:
        # 3 * 250 = 750, comfortably under the 1918 python cap.
        self._populate(250)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.module.validate_aggregate_budget()
        self.assertIn("aggregate context budget ok", buf.getvalue())

    def test_raises_when_profile_sum_exceeds_budget(self) -> None:
        # 3 * 700 = 2100, just over the 1918 python cap.
        self.assertGreater(700 * len(PYTHON_PROFILE_FILES), PYTHON_BUDGET)
        self._populate(700)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), self.assertRaises(SystemExit):
            self.module.validate_aggregate_budget()
        self.assertIn("python", buf.getvalue())


class TemplateDiscoveryGuardTest(unittest.TestCase):
    """Regression tests for issue #73: a template's rules file must be
    covered by THRESHOLDS/PROFILES, or the checks must fail loudly instead
    of silently skipping it.
    """

    def setUp(self) -> None:
        self.module = load_script_module("self_check_under_test", SELF_CHECK)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.module.REPO_ROOT = self.root

    def test_context_budget_raises_for_unbudgeted_language(self) -> None:
        _write_words(self.root / "newlang/.claude/rules/raven-newlang.md", 10)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), self.assertRaises(SystemExit) as ctx:
            self.module.validate_context_budget()
        self.assertIn("newlang", str(ctx.exception))

    def test_aggregate_budget_raises_for_unprofiled_language(self) -> None:
        _write_words(self.root / "newlang/.claude/rules/raven-newlang.md", 10)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), self.assertRaises(SystemExit) as ctx:
            self.module.validate_aggregate_budget()
        self.assertIn("newlang", str(ctx.exception))

    def test_context_budget_covers_all_real_template_languages(self) -> None:
        # Runs against the real repo (no REPO_ROOT monkeypatch): if go, lua,
        # or dotfiles ever drop out of THRESHOLDS again, the discovery guard
        # raises instead of silently passing.
        module = load_script_module("self_check_real_repo", SELF_CHECK)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            module.validate_context_budget()
        self.assertIn("context budget ok", buf.getvalue())

    def test_aggregate_budget_covers_all_real_template_languages(self) -> None:
        module = load_script_module("self_check_real_repo", SELF_CHECK)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            module.validate_aggregate_budget()
        self.assertIn("aggregate context budget ok", buf.getvalue())


class StrictFreshnessTest(unittest.TestCase):
    """Regression tests for issue #82: the weekly scheduled CI run must be
    able to fail on stale third-party setup docs instead of only logging a
    warning inside an otherwise-green run.
    """

    def setUp(self) -> None:
        self.module = load_script_module("self_check_under_test", SELF_CHECK)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.module.REPO_ROOT = self.root
        self.docs_dir = self.root / "common" / ".claude" / "docs"
        self.docs_dir.mkdir(parents=True)
        self.addCleanup(os.environ.pop, "RAVEN_SELF_CHECK_STRICT_FRESHNESS", None)

    def _write_doc(self, name: str, verified: str) -> None:
        (self.docs_dir / name).write_text(f"Last verified: {verified}\n", encoding="utf-8")

    def test_stale_doc_is_non_fatal_by_default(self) -> None:
        self._write_doc("raven-lsp-mcp.md", "2020-01-01")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.module.warn_stale_docs()
        self.assertIn("STALE", buf.getvalue())

    def test_stale_doc_raises_when_strict_env_set(self) -> None:
        self._write_doc("raven-lsp-mcp.md", "2020-01-01")
        os.environ["RAVEN_SELF_CHECK_STRICT_FRESHNESS"] = "1"
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), self.assertRaises(SystemExit):
            self.module.warn_stale_docs()
        self.assertIn("raven-lsp-mcp.md", buf.getvalue())

    def test_fresh_docs_do_not_raise_when_strict(self) -> None:
        today = self.module.datetime.date.today().isoformat()
        self._write_doc("raven-lsp-mcp.md", today)
        os.environ["RAVEN_SELF_CHECK_STRICT_FRESHNESS"] = "1"
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.module.warn_stale_docs()
        self.assertIn("freshness check ok", buf.getvalue())


class UpgradeConvergenceTest(unittest.TestCase):
    """The self-check runs `raven upgrade` against this repo and, before this,
    judged it purely on exit code. `upgrade` exits 0 when it leaves files
    needing a manual merge, so unresolved conflicts printed "ok" in CI and the
    AGENTS.md rule to treat unexpected self-upgrade output as a product issue
    had no enforcement behind it.

    Convergence is judged against an explicit allowlist rather than "zero
    drift": this repository is both the template source and an installed
    consumer, so some divergence is the dogfooding working as intended. The
    gate's job is to fail on drift nobody has approved.
    """

    def setUp(self) -> None:
        self.module = load_script_module("self_check_convergence", SELF_CHECK)

    @staticmethod
    def _finding(finding_id, severity, detail, category="Drift & freshness"):
        return {
            "id": finding_id,
            "severity": severity,
            "category": category,
            "title": "t",
            "detail": detail,
            "fix": None,
        }

    def test_approved_divergence_is_not_reported(self) -> None:
        findings = [self._finding("doctor.drift.modified", "warn", "justfile")]
        self.assertEqual(self.module.unconverged_paths(findings, {"justfile"}), [])

    def test_unapproved_drift_path_is_reported(self) -> None:
        findings = [
            self._finding("doctor.drift.pending", "warn", "justfile, .claude/rules/raven-python.md")
        ]
        self.assertEqual(
            self.module.unconverged_paths(findings, {"justfile"}),
            [".claude/rules/raven-python.md"],
        )

    def test_a_new_kind_of_drift_warning_is_reported_not_ignored(self) -> None:
        # The gate keys on category + severity, not on a hardcoded id list, so
        # a drift finding added to doctor later fails loudly instead of
        # slipping through an allowlist that never heard of it.
        findings = [self._finding("doctor.drift.something-new", "error", "a/b.md")]
        self.assertEqual(self.module.unconverged_paths(findings, set()), ["a/b.md"])

    def test_informational_and_ok_drift_are_not_convergence_failures(self) -> None:
        # `local` is template-unchanged local customization: nothing to merge.
        findings = [
            self._finding("doctor.drift.local", "info", ".codex/config.toml"),
            self._finding("doctor.drift.modified", "ok", "installed files match"),
        ]
        self.assertEqual(self.module.unconverged_paths(findings, set()), [])

    def test_non_drift_warnings_are_out_of_scope(self) -> None:
        # A missing optional tool is a real doctor warning but says nothing
        # about whether the upgrade converged.
        findings = [self._finding("doctor.tool.fd", "warn", "fd", category="Toolchain")]
        self.assertEqual(self.module.unconverged_paths(findings, set()), [])

    def test_version_drift_is_ignored_because_it_self_chases(self) -> None:
        # The manifest records the commit installed from, so every commit made
        # after a self-upgrade leaves this warning set in this repo. It is a
        # property of dogfooding, not unconverged state.
        findings = [self._finding("doctor.drift.version", "warn", "installed abc, current def")]
        self.assertEqual(self.module.unconverged_paths(findings, set()), [])

    def test_real_repo_has_converged_after_upgrade(self) -> None:
        # End-to-end: the allowlist shipped in self-check.py must actually
        # cover this repository's current state, or the gate is already red.
        module = load_script_module("self_check_convergence_real", SELF_CHECK)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            module.validate_upgrade_convergence()
        self.assertIn("upgrade convergence ok", buf.getvalue())


class DebtEntryStructureTest(unittest.TestCase):
    """Issue #162: a reconciliation-debt entry with no tracking issue reference
    is a structural error, not a silent pass -- it must fail loudly.
    """

    def setUp(self) -> None:
        self.module = load_script_module("self_check_debt_structure", SELF_CHECK)

    def test_real_debt_table_has_issue_references_for_every_entry(self) -> None:
        # Must not raise: the shipped table is well-formed.
        self.module._validate_debt_entries(self.module._RECONCILIATION_DEBT)

    def test_missing_issue_reference_raises(self) -> None:
        with self.assertRaises(SystemExit) as ctx:
            self.module._validate_debt_entries({"some/path.md": ""})
        self.assertIn("some/path.md", str(ctx.exception))

    def test_none_like_issue_reference_raises(self) -> None:
        # Whitespace-only counts as missing, not a silent pass.
        with self.assertRaises(SystemExit):
            self.module._validate_debt_entries({"some/path.md": "   "})

    def test_well_formed_entry_does_not_raise(self) -> None:
        self.module._validate_debt_entries({"some/path.md": "#999"})


class ConvergenceStateTest(unittest.TestCase):
    """Issue #162, Part 1 & 2: permanent customization and reconciliation debt
    are distinct representations with distinct output. This covers the four
    states a post-upgrade `raven doctor` run can leave self-check in:
    clean convergence, customization only, debt present, and unexpected
    drift. Each assertion below targets something the other three states do
    not produce, so a sabotage that breaks exactly one state trips exactly
    one test -- see the task report for the sabotage matrix.
    """

    def setUp(self) -> None:
        self.module = load_script_module("self_check_convergence_states", SELF_CHECK)
        self.addCleanup(os.environ.pop, "RAVEN_SELF_CHECK_STRICT_DEBT", None)

    @staticmethod
    def _finding(finding_id, severity, detail, category="Drift & freshness"):
        return {
            "id": finding_id,
            "severity": severity,
            "category": category,
            "title": "t",
            "detail": detail,
            "fix": None,
        }

    def _customization_path(self) -> str:
        return next(iter(self.module._APPROVED_CUSTOMIZATION))

    def _debt_path(self) -> str:
        return next(iter(self.module._RECONCILIATION_DEBT))

    def test_clean_convergence_reports_no_customization_and_no_debt(self) -> None:
        findings: list = []
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.module._report_convergence(findings)
        out = buf.getvalue()
        self.assertIn("upgrade convergence ok", out)
        # Distinguishes from the customization-only and debt-present states,
        # which both report a nonzero count of one kind or the other.
        self.assertIn("0 approved customization", out)
        self.assertIn("no reconciliation debt", out)
        self.assertNotIn("DEBT:", out)

    def test_customization_only_reports_count_but_no_debt(self) -> None:
        path = self._customization_path()
        findings = [self._finding("doctor.drift.modified", "warn", path)]
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.module._report_convergence(findings)
        out = buf.getvalue()
        self.assertIn("upgrade convergence ok", out)
        # Distinguishes from clean: a nonzero customization count.
        self.assertIn("1 approved customization", out)
        # Distinguishes from debt-present: no debt is named or flagged.
        self.assertIn("no reconciliation debt", out)
        self.assertNotIn("DEBT:", out)
        self.assertNotIn(self._debt_path(), out)

    def test_debt_present_names_the_entry_and_its_issue(self) -> None:
        path = self._debt_path()
        issue = self.module._RECONCILIATION_DEBT[path]
        findings = [self._finding("doctor.drift.pending", "warn", path)]
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.module._report_convergence(findings)
        out = buf.getvalue()
        self.assertIn("upgrade convergence ok", out)
        # Distinguishes from clean and customization-only: the debt path and
        # its tracking issue are both named, not merely counted.
        self.assertIn(path, out)
        self.assertIn(issue, out)
        self.assertIn("DEBT:", out)

    def test_unexpected_drift_raises_and_names_the_unapproved_path(self) -> None:
        findings = [self._finding("doctor.drift.modified", "warn", "some/unapproved/path.md")]
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), self.assertRaises(SystemExit) as ctx:
            self.module._report_convergence(findings)
        # Distinguishes from all three other states: this is the only one
        # that raises SystemExit at all.
        self.assertIn("some/unapproved/path.md", buf.getvalue() + str(ctx.exception))

    def test_debt_present_does_not_raise_by_default(self) -> None:
        path = self._debt_path()
        findings = [self._finding("doctor.drift.pending", "warn", path)]
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.module._report_convergence(findings)  # must not raise

    def test_strict_debt_env_var_fails_when_debt_remains(self) -> None:
        path = self._debt_path()
        issue = self.module._RECONCILIATION_DEBT[path]
        os.environ["RAVEN_SELF_CHECK_STRICT_DEBT"] = "1"
        findings = [self._finding("doctor.drift.pending", "warn", path)]
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), self.assertRaises(SystemExit) as ctx:
            self.module._report_convergence(findings)
        self.assertIn(path, str(ctx.exception))
        self.assertIn(issue, str(ctx.exception))

    def test_strict_debt_env_var_is_harmless_without_debt(self) -> None:
        os.environ["RAVEN_SELF_CHECK_STRICT_DEBT"] = "1"
        findings: list = []
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.module._report_convergence(findings)  # must not raise


# Read from self-check.py rather than restated here. The mirrored copies drifted
# (362 vs a real 376) and left the aggregate fixture clearing the true limit by
# only 4 words -- it still failed for the right reason, but the next raise would
# have quietly pushed the fixture under the limit and turned that test green
# against a budget it was no longer exercising.
_budget_module = load_script_module("self_check_budget_caps", SELF_CHECK)
SKILL_DESC_AGGREGATE = _budget_module.SKILL_DESCRIPTION_AGGREGATE_LIMIT
SKILL_DESC_PER_SKILL = _budget_module.SKILL_DESCRIPTION_PER_SKILL_LIMIT


class SkillDescriptionBudgetTest(unittest.TestCase):
    """Issue #92: skill `description:` frontmatter is injected into every
    session's skill index, an always-loaded surface the file/aggregate rules
    budgets never counted. Cap the sum and each single description.
    """

    def setUp(self) -> None:
        self.module = load_script_module("self_check_under_test", SELF_CHECK)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.module.REPO_ROOT = self.root

    def _write_skill(self, name: str, description: str) -> None:
        path = self.root / "common" / ".agents" / "skills" / name / "SKILL.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            f"---\nname: {name}\ndescription: {description}\n---\n\nBody.\n",
            encoding="utf-8",
        )

    def test_passes_on_real_tree(self) -> None:
        module = load_script_module("self_check_real_repo", SELF_CHECK)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            module.validate_skill_description_budget()
        self.assertIn("skill description budget ok", buf.getvalue())

    def test_raises_when_single_description_exceeds_cap(self) -> None:
        over = SKILL_DESC_PER_SKILL + 5
        self._write_skill("raven-example", "word " * over)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), self.assertRaises(SystemExit):
            self.module.validate_skill_description_budget()
        self.assertIn("raven-example", buf.getvalue())

    def test_raises_when_aggregate_exceeds_budget(self) -> None:
        # Each description stays under the per-skill cap, but their sum clears
        # the aggregate limit — the case per-file caps alone cannot catch.
        per_skill = 20
        skill_count = SKILL_DESC_AGGREGATE // per_skill + 1
        self.assertLessEqual(per_skill, SKILL_DESC_PER_SKILL)
        self.assertGreater(per_skill * skill_count, SKILL_DESC_AGGREGATE)
        for i in range(skill_count):
            self._write_skill(f"raven-skill-{i}", "word " * per_skill)
        with self.assertRaises(SystemExit) as ctx:
            self.module.validate_skill_description_budget()
        self.assertIn("budget exceeded", str(ctx.exception))

    def test_raises_when_description_frontmatter_missing(self) -> None:
        path = self.root / "common" / ".agents" / "skills" / "raven-broken" / "SKILL.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("---\nname: raven-broken\n---\n\nBody.\n", encoding="utf-8")
        with self.assertRaises(SystemExit) as ctx:
            self.module.validate_skill_description_budget()
        self.assertIn("raven-broken", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
