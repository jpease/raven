import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from helpers import REPO_ROOT, load_script_module

SELF_CHECK = REPO_ROOT / "scripts" / "self-check.py"

# The four always-loaded files that make up the "python" language profile in
# validate_aggregate_budget(). Other profiles share AGENTS.md + security +
# tests but point at a different language rules file; leaving those language
# files absent makes the validator skip those profiles, so a test only needs
# to populate this one profile to drive the pass/fail paths.
PYTHON_PROFILE_FILES = (
    "common/AGENTS.md",
    "common/.claude/rules/raven-security.md",
    "common/.claude/rules/raven-tests.md",
    "python/.claude/rules/raven-python.md",
)

# Mirrors the "python" cap in validate_aggregate_budget(). Kept here so the
# test's word totals straddle the real threshold; update both together if the
# budget changes.
PYTHON_BUDGET = 1950


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
        # 4 * 250 = 1000, comfortably under the 1950 python cap.
        self._populate(250)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.module.validate_aggregate_budget()
        self.assertIn("aggregate context budget ok", buf.getvalue())

    def test_raises_when_profile_sum_exceeds_budget(self) -> None:
        # 4 * 500 = 2000, just over the 1950 python cap.
        self.assertGreater(500 * len(PYTHON_PROFILE_FILES), PYTHON_BUDGET)
        self._populate(500)
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


if __name__ == "__main__":
    unittest.main()
