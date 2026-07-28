import importlib.util
import sys
import tempfile
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path
from typing import Any, cast

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
    # Register before exec so the module can resolve its own namespace -- e.g.
    # @dataclass under ``from __future__ import annotations`` looks the module up
    # in sys.modules to evaluate string annotations. This mirrors the import
    # system's own loading order.
    sys.modules[name] = module
    # spec_from_file_location yields a SourceFileLoader; cast past the
    # importlib.abc.Loader base, whose typeshed stub omits exec_module.
    cast(SourceFileLoader, spec.loader).exec_module(module)
    return module


def attribution_line(tool: str = "Claude", verb: str = "Generated", prep: str = "by") -> str:
    """Build an AI-attribution line that the scanners under test must reject.

    Assembled at runtime rather than written as one literal, so no test file's
    own source contains the exact phrase -- the AI-attribution content scan runs
    on this repository too (see pre-commit/pre-push), and a literal here would
    fail Raven's own gate. That constraint is the reason this lives in one
    place: it was previously duplicated, where a well-meaning "simplify it to a
    string" edit in either copy would break the repo's own commit path.
    """
    return f"# {verb} {prep} {tool}\n"


def push_plan_line(ref: str, local_sha: str, remote_sha: str) -> str:
    """Build one line of the ref plan Git feeds a pre-push hook on stdin.

    The format is ``<local-ref> <local-sha> <remote-ref> <remote-sha>``. Issue
    #126 was a scan that read the checked-out branch instead of this plan, so
    tests that drive a pre-push hook must supply the real thing.
    """
    return f"{ref} {local_sha} {ref} {remote_sha}\n"


class RavenTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.destination = Path(self.tmp.name)
        self.template = REPO_ROOT / "python"
        self.excludes = {"README.md"}
