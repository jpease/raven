import ast
import unittest

# helpers puts scripts/ on sys.path and imports the installer package as ``raven``.
from helpers import REPO_ROOT
from helpers import raven as raven_lib

INIT_PATH = REPO_ROOT / "scripts" / "raven_lib" / "__init__.py"


def _reexported_names() -> set[str]:
    """Names pulled into the package namespace via ``from .module import ...``.

    Excludes ``from __future__`` imports, which are not part of the public API.
    """
    tree = ast.parse(INIT_PATH.read_text())
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module != "__future__":
            names.update(alias.asname or alias.name for alias in node.names)
    return names


class PackageApiTests(unittest.TestCase):
    """Guard the hand-maintained re-export facade in ``raven_lib/__init__.py``.

    The package re-exports submodule symbols and lists them in ``__all__`` by
    hand, so the two can silently drift. These tests keep them in lockstep.
    """

    def test_all_matches_reexports(self):
        reexported = _reexported_names()
        declared = set(raven_lib.__all__)

        missing_from_all = sorted(reexported - declared)
        self.assertEqual(
            missing_from_all,
            [],
            f"re-exported but absent from __all__: {missing_from_all}",
        )

        not_reexported = sorted(declared - reexported)
        self.assertEqual(
            not_reexported,
            [],
            f"listed in __all__ but not re-exported: {not_reexported}",
        )

    def test_all_entries_are_importable(self):
        for name in raven_lib.__all__:
            self.assertTrue(
                hasattr(raven_lib, name),
                f"__all__ names {name!r} but it is not an attribute of raven_lib",
            )


if __name__ == "__main__":
    unittest.main()
