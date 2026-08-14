"""Tests for #206: a shipped ``common/.gitattributes`` merged append-only into a
destination's own ``.gitattributes``, never whole-file copied.

Two concerns, kept in separate test classes:

* ``GitattributesShippedCoverageTests`` derives the set of paths that need an
  explicit ``eol=lf`` entry by scanning the real shipped
  ``common/.raven/git-hooks/`` tree, instead of restating a hand-typed list
  that could silently drift from reality. A newly added extensionless
  shebang git-hook entry point, or a new ``.raven/git-hooks/lib/*.py`` file,
  fails this test until ``common/.gitattributes`` is updated to cover it. A
  newly added ``*.sh`` file needs no such update -- the blanket ``*.sh text
  eol=lf`` rule covers it by construction -- but a regression that removed or
  narrowed that blanket rule would still be caught here.
* ``GitattributesInstallTests`` exercises the installer end to end: a clean
  install writes every required line, an existing destination
  ``.gitattributes`` with unrelated content keeps every existing line and
  gains only the missing Raven ones, and repeated installs/upgrades are
  idempotent (no duplicate lines).
"""

from __future__ import annotations

import contextlib
import fnmatch
import io
import unittest
from pathlib import Path

from helpers import REPO_ROOT, RavenTestCase, raven

COMMON = REPO_ROOT / "common"
GIT_HOOKS_DIR = COMMON / ".raven" / "git-hooks"


def _shebang_extensionless_relatives(git_hooks_dir: Path) -> list[str]:
    """Extensionless files directly under ``git_hooks_dir`` whose first line is a shebang.

    These are git's actual hook entry points -- git invokes them directly by
    path, relying on their own ``#!`` line, so the ``*.sh`` glob (which cannot
    match an extensionless name) does not cover them.
    """
    relatives = []
    for entry in sorted(git_hooks_dir.iterdir()):
        if not entry.is_file() or "." in entry.name:
            continue
        with entry.open("rb") as f:
            first_line = f.readline()
        if first_line.startswith(b"#!"):
            relatives.append(f".raven/git-hooks/{entry.name}")
    return relatives


def _lib_python_relatives(lib_dir: Path) -> list[str]:
    """``.py`` files directly under ``.raven/git-hooks/lib/``.

    Always invoked as ``python3 "$path"`` from a calling shell hook (explicit
    interpreter, shebang irrelevant), so ``eol=lf`` is not correctness-critical
    here the way it is for the extensionless entry points above -- but they get
    an explicit entry anyway so the directory does not have a confusing
    partial-coverage split between visually identical siblings.
    """
    return sorted(f".raven/git-hooks/lib/{p.name}" for p in lib_dir.iterdir() if p.suffix == ".py")


def _gitattributes_eol_lf_patterns(text: str) -> list[str]:
    """Patterns from ``.gitattributes`` text whose attribute list includes ``eol=lf``."""
    patterns = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if "eol=lf" in parts[1:]:
            patterns.append(parts[0])
    return patterns


def _covered_by_eol_lf(relative: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(relative, pattern) for pattern in patterns)


class GitattributesShippedCoverageTests(unittest.TestCase):
    def setUp(self):
        self.gitattributes_text = (COMMON / ".gitattributes").read_text(encoding="utf-8")
        self.patterns = _gitattributes_eol_lf_patterns(self.gitattributes_text)

    def test_every_sh_file_under_common_is_covered_by_the_blanket_glob(self):
        sh_files = sorted(
            str(p.relative_to(COMMON)) for p in COMMON.rglob("*.sh") if not p.is_symlink()
        )
        self.assertTrue(sh_files, "expected at least one .sh file under common/ to exercise this")
        uncovered = [p for p in sh_files if not _covered_by_eol_lf(p, self.patterns)]
        self.assertEqual(uncovered, [], f".sh files with no eol=lf coverage: {uncovered}")

    def test_git_hook_entry_points_and_lib_python_files_are_covered(self):
        required = sorted(
            _shebang_extensionless_relatives(GIT_HOOKS_DIR)
            + _lib_python_relatives(GIT_HOOKS_DIR / "lib")
        )
        self.assertTrue(required, "expected at least one required path from the scan")
        uncovered = [p for p in required if not _covered_by_eol_lf(p, self.patterns)]
        self.assertEqual(
            uncovered,
            [],
            f"missing an eol=lf .gitattributes entry for: {uncovered} -- add one to "
            "common/.gitattributes",
        )

    def test_scan_finds_exactly_the_three_entry_points_and_three_lib_files(self):
        # Pins the scan's own result, not the .gitattributes coverage (the two
        # tests above already assert that) -- so a change to the shipped
        # git-hooks tree that this scan silently stops seeing (a bug in the
        # scan itself, not in .gitattributes) is caught here instead.
        self.assertEqual(
            _shebang_extensionless_relatives(GIT_HOOKS_DIR),
            [
                ".raven/git-hooks/commit-msg",
                ".raven/git-hooks/pre-commit",
                ".raven/git-hooks/pre-push",
            ],
        )
        self.assertEqual(
            _lib_python_relatives(GIT_HOOKS_DIR / "lib"),
            [
                ".raven/git-hooks/lib/check-ai-attribution-content.py",
                ".raven/git-hooks/lib/check-managed-block-integrity.py",
                ".raven/git-hooks/lib/raven_config.py",
            ],
        )


class GitattributesInstallTests(RavenTestCase):
    def _install(self, **kwargs):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            rc = raven._run(
                self.destination,
                raven.load_config(self.destination),
                "python",
                False,
                False,
                [],
                **kwargs,
            )
        return rc, out.getvalue()

    def test_clean_install_writes_every_required_line(self):
        rc, output = self._install()
        self.assertEqual(rc, 0, output)

        gitattributes = self.destination / ".gitattributes"
        self.assertTrue(gitattributes.is_file())
        installed_lines = set(gitattributes.read_text(encoding="utf-8").splitlines())
        required_lines = [
            line.strip()
            for line in (COMMON / ".gitattributes").read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        self.assertTrue(required_lines)
        for pattern_line in required_lines:
            self.assertIn(pattern_line, installed_lines)

    def test_existing_gitattributes_content_is_preserved(self):
        (self.destination / ".gitattributes").write_text(
            "# pre-existing, unrelated to Raven\n*.png binary\n*.bin -diff\n", encoding="utf-8"
        )

        rc, output = self._install()
        self.assertEqual(rc, 0, output)

        text = (self.destination / ".gitattributes").read_text(encoding="utf-8")
        lines = text.splitlines()
        self.assertIn("*.png binary", lines)
        self.assertIn("*.bin -diff", lines)
        self.assertIn("* text=auto", lines)
        self.assertIn(".raven/git-hooks/pre-commit text eol=lf", lines)

    def test_repeated_install_is_idempotent(self):
        self._install()
        first_text = (self.destination / ".gitattributes").read_text(encoding="utf-8")

        # `_run` (`_install`'s helper above) is the shared entry point both
        # `cmd_install` and `cmd_upgrade` call into -- running it again against
        # an already-installed destination is what `raven upgrade` does.
        rc, output = self._install()
        self.assertEqual(rc, 0, output)
        second_text = (self.destination / ".gitattributes").read_text(encoding="utf-8")

        self.assertEqual(first_text, second_text)
        lines = second_text.splitlines()
        non_blank = [line for line in lines if line.strip()]
        self.assertEqual(len(non_blank), len(set(non_blank)), "duplicate line(s) after a re-run")

    def test_disabling_hooks_component_skips_gitattributes_merge(self):
        (self.destination / ".raven").mkdir()
        (self.destination / ".raven" / "config.toml").write_text(
            """
schema = 1
template = "python"

[components]
hooks = false
""".strip()
            + "\n",
            encoding="utf-8",
        )

        rc, output = self._install()
        self.assertEqual(rc, 0, output)
        self.assertFalse((self.destination / ".gitattributes").exists())


if __name__ == "__main__":
    unittest.main()
