import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "common" / ".claude" / "scripts" / "raven-session.py"


def load_session():
    spec = importlib.util.spec_from_file_location("raven_session", SCRIPT_PATH)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


class SessionInitTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.raven_dir = self.root / ".raven"
        self.raven_dir.mkdir()
        self.session_file = self.raven_dir / "session.md"

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, args: list[str]) -> int:
        mod = load_session()
        import os

        orig = os.getcwd()
        os.chdir(self.root)
        try:
            return mod.main(args)
        finally:
            os.chdir(orig)

    def test_init_creates_session_file(self):
        rc = self._run(["--init", "greenfield", "unit-a", "unit-b"])
        self.assertEqual(rc, 0)
        self.assertTrue(self.session_file.exists())

    def test_init_records_project_type(self):
        self._run(["--init", "brownfield", "unit-a"])
        content = self.session_file.read_text()
        self.assertIn("**Project Type:** brownfield", content)

    def test_init_records_units_with_first_as_current(self):
        self._run(["--init", "greenfield", "unit-a", "unit-b", "unit-c"])
        content = self.session_file.read_text()
        self.assertIn("- [ ] unit-a (current)", content)
        self.assertIn("- [ ] unit-b", content)
        self.assertIn("- [ ] unit-c", content)

    def test_init_fails_if_session_already_exists(self):
        self._run(["--init", "greenfield", "unit-a"])
        rc = self._run(["--init", "greenfield", "unit-b"])
        self.assertNotEqual(rc, 0)

    def test_status_prints_current_unit(self):
        self._run(["--init", "greenfield", "unit-a", "unit-b"])
        import io
        from contextlib import redirect_stdout

        f = io.StringIO()
        with redirect_stdout(f):
            self._run(["--status"])
        output = f.getvalue()
        self.assertIn("unit-a", output)
        self.assertIn("current", output.lower())
