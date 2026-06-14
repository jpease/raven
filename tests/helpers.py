import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
RAVEN_PATH = REPO_ROOT / "scripts" / "raven.py"

sys.path.insert(0, str(REPO_ROOT / "scripts"))
import raven_lib as raven  # noqa: E402,F401


def load_script_module(name: str, path: Path) -> Any:
    """Load a standalone Raven script as a module for testing.

    Returns the module typed as ``Any`` on purpose: a script loaded from a
    file path has no importable static type, and these tests intentionally
    read and monkeypatch its attributes. Centralizing the import keeps the
    ``spec``/``loader`` None-checks in one Pyright-friendly place.
    """
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"could not load module {name!r} from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RavenTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.destination = Path(self.tmp.name)
        self.template = REPO_ROOT / "python"
        self.excludes = {"README.md"}
