import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RAVEN_PATH = REPO_ROOT / "scripts" / "raven.py"

sys.path.insert(0, str(REPO_ROOT / "scripts"))
import raven_lib as raven  # noqa: E402,F401


class RavenTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.destination = Path(self.tmp.name)
        self.template = REPO_ROOT / "python"
        self.excludes = {"README.md"}
