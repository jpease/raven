import ast
import unittest

# helpers puts scripts/ on sys.path and imports the installer package as ``raven``.
from helpers import REPO_ROOT
from helpers import raven as raven_lib

INIT_PATH = REPO_ROOT / "scripts" / "raven_lib" / "__init__.py"

# Exports deliberately kept without a current consumer, name -> reason. Empty on
# purpose: an entry here is a considered decision to ship unused public surface,
# so it should be rare and always carry its justification.
EXPORTS_WITHOUT_CONSUMERS: dict[str, str] = {}


def _origin_modules() -> dict[str, str]:
    """Map each re-exported name to the module path it is defined in."""
    tree = ast.parse(INIT_PATH.read_text())
    origins: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module != "__future__":
            for alias in node.names:
                module = node.module.replace(".", "/")
                origins[alias.asname or alias.name] = f"scripts/raven_lib/{module}.py"
    return origins


def _referenced_names_by_file() -> dict[str, set[str]]:
    """Every identifier referenced in each first-party Python file.

    Collects ``Name`` ids and ``Attribute`` attrs, so both ``classify(...)`` and
    the ``raven.classify(...)`` form the tests use are counted as consumption.
    """
    referenced: dict[str, set[str]] = {}
    paths = sorted(REPO_ROOT.glob("scripts/**/*.py")) + sorted(REPO_ROOT.glob("tests/*.py"))
    for path in paths:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            # scripts/list_open_issues.py is a symlink to a file shared across
            # repos; it is legitimately absent in some checkouts (see the
            # skipUnless in test_list_open_issues.py). A file we cannot read
            # simply contributes no references.
            continue
        names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                names.add(node.id)
            elif isinstance(node, ast.Attribute):
                names.add(node.attr)
        referenced[str(path.relative_to(REPO_ROOT))] = names
    return referenced


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

    def test_every_export_has_a_consumer(self):
        """An export nothing imports is public surface with no public.

        The two tests above only check that ``__all__`` and the re-export list
        agree with each other, which a dead export satisfies perfectly -- that
        is how ``manifest_allows_upgrade`` stayed exported and uncalled until a
        debloat sweep found it. Consumption is the property worth guarding, so
        this asserts it directly.

        A symbol used only inside the module that defines it is not evidence
        for the export: the function may well be earning its place, while the
        line re-exporting it is not.
        """
        origins = _origin_modules()
        referenced = _referenced_names_by_file()

        orphans = {}
        for name in raven_lib.__all__:
            if name in EXPORTS_WITHOUT_CONSUMERS:
                continue
            home = origins.get(name)
            consumers = [
                path
                for path, names in referenced.items()
                if name in names and path != home and path != "scripts/raven_lib/__init__.py"
            ]
            if not consumers:
                orphans[name] = home or "unknown module"

        self.assertEqual(
            orphans,
            {},
            "exported from raven_lib but consumed by nothing outside the module "
            f"that defines it: {orphans}. Drop it from __all__ and the re-export "
            "list (the definition itself may still be earning its place), or add "
            "it to EXPORTS_WITHOUT_CONSUMERS with a reason",
        )

    def test_all_entries_are_importable(self):
        for name in raven_lib.__all__:
            self.assertTrue(
                hasattr(raven_lib, name),
                f"__all__ names {name!r} but it is not an attribute of raven_lib",
            )


if __name__ == "__main__":
    unittest.main()
