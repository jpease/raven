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
    of silently skipping it."""

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
    warning inside an otherwise-green run."""

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


# Mirrors the caps in validate_skill_description_budget(). Kept here so the
# test's word totals straddle the real thresholds; update both together if the
# budget changes.
SKILL_DESC_AGGREGATE = 362
SKILL_DESC_PER_SKILL = 30


class SkillDescriptionBudgetTest(unittest.TestCase):
    """Issue #92: skill `description:` frontmatter is injected into every
    session's skill index, an always-loaded surface the file/aggregate rules
    budgets never counted. Cap the sum and each single description."""

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
