"""Tests for #238: a shipped ``common/.ignore`` merged append-only into a
destination's own ``.ignore``, never whole-file copied.

ripgrep, fd and ast-grep share the ``ignore`` crate and skip dot-directories
unless a negation says otherwise, so without this file every ``.agents/``,
``.claude/``, ``.codex/`` and ``.raven/`` path Raven just installed is invisible
to the three tools Raven's own retrieval ladder names first. Raven's checkout
has carried a root ``.ignore`` for years; no template shipped one.

One class per concern:

* ``IgnoreShippedContentTests`` pins the shipped template against the
  directories Raven actually installs into, so a new Raven-owned dot-directory
  fails here until ``common/.ignore`` covers it.
* ``IgnoreInstallTests`` drives the installer end to end -- clean install,
  pre-existing unrelated content, repeated runs.
* ``IgnoreBlockFormattingTests`` is the #217 conditional-separator behaviour,
  the same three cases ``test_gitattributes.py`` pins for ``.gitattributes``.
* ``IgnoreHomeDirectoryGuardTests`` covers the one destination that must not
  get the file -- ``$HOME`` itself, where ``!.claude/`` would un-hide Claude
  Code's multi-gigabyte runtime state -- and, more importantly, that every
  subdirectory of home still does.
* ``IgnoreMergeOnlySafetyTests`` is the destructive case: a destination's own
  ``.ignore`` must never be deleted as an orphan, removed as deactivated,
  reported as drift, or turned into a copy/upgrade entry.
* ``IgnoreSearchabilityTests`` runs the real ``rg``/``fd``/``ast-grep``
  binaries against an installed destination, which is the acceptance criterion
  itself rather than a proxy for it. Skipped per tool when the binary is absent.
"""

from __future__ import annotations

import contextlib
import io
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from helpers import REPO_ROOT, RavenTestCase, raven
from raven_lib.deactivated import classify_deactivated
from raven_lib.doctor import drift_findings
from raven_lib.orphans import classify_orphans

COMMON = REPO_ROOT / "common"
SHIPPED_IGNORE = COMMON / raven.IGNORE_PATH

# The dot-directories Raven installs guidance into. Pinned by hand, not derived
# from a walk: adding a Raven-owned dot-directory should fail this test until
# common/.ignore un-hides it, rather than pass by construction.
RAVEN_DOT_DIRECTORIES = (".agents", ".claude", ".codex", ".raven")


def _required_lines(text: str) -> list[str]:
    return [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


class IgnoreShippedContentTests(unittest.TestCase):
    def setUp(self):
        self.text = SHIPPED_IGNORE.read_text(encoding="utf-8")

    def test_every_raven_dot_directory_is_negated(self):
        lines = _required_lines(self.text)
        self.assertEqual(lines, [f"!{name}/" for name in RAVEN_DOT_DIRECTORIES])

    def test_every_shipped_line_is_a_negation(self):
        # A non-negation line could hide a path the destination was searching
        # before Raven arrived. Only `!` lines are safe to append blind.
        for line in _required_lines(self.text):
            self.assertTrue(line.startswith("!"), f"non-negation line in common/.ignore: {line!r}")

    def test_the_shipped_file_explains_itself(self):
        self.assertTrue(self.text.startswith("#"), "common/.ignore should open with a comment")
        for tool in ("ripgrep", "fd", "ast-grep"):
            self.assertIn(tool, self.text)

    def test_the_repository_root_ignore_names_all_three_tools(self):
        # Raven's own root .ignore is the file this behaviour was copied from;
        # its comment named only ripgrep/fd while ast-grep shares the crate.
        root_text = (REPO_ROOT / raven.IGNORE_PATH).read_text(encoding="utf-8")
        for tool in ("ripgrep", "fd", "ast-grep"):
            self.assertIn(tool, root_text)


class IgnoreInstallTests(RavenTestCase):
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

        installed = self.destination / raven.IGNORE_PATH
        self.assertTrue(installed.is_file())
        lines = installed.read_text(encoding="utf-8").splitlines()
        for required in _required_lines(SHIPPED_IGNORE.read_text(encoding="utf-8")):
            self.assertIn(required, lines)

    def test_existing_ignore_content_is_preserved(self):
        (self.destination / raven.IGNORE_PATH).write_text(
            "# pre-existing, unrelated to Raven\nvendor/\n!build/generated/\n", encoding="utf-8"
        )

        rc, output = self._install()
        self.assertEqual(rc, 0, output)

        lines = (self.destination / raven.IGNORE_PATH).read_text(encoding="utf-8").splitlines()
        self.assertIn("vendor/", lines)
        self.assertIn("!build/generated/", lines)
        self.assertIn("# pre-existing, unrelated to Raven", lines)
        self.assertIn("!.agents/", lines)
        self.assertIn("!.raven/", lines)

    def test_a_line_the_destination_already_has_is_not_duplicated(self):
        (self.destination / raven.IGNORE_PATH).write_text("!.claude/\n", encoding="utf-8")

        rc, output = self._install()
        self.assertEqual(rc, 0, output)

        lines = (self.destination / raven.IGNORE_PATH).read_text(encoding="utf-8").splitlines()
        self.assertEqual(lines.count("!.claude/"), 1)

    def test_repeated_install_is_idempotent(self):
        self._install()
        first = (self.destination / raven.IGNORE_PATH).read_text(encoding="utf-8")

        # `_run` is the shared entry point behind both `cmd_install` and
        # `cmd_upgrade`; running it against an already-installed destination is
        # what `raven upgrade` does.
        rc, output = self._install()
        self.assertEqual(rc, 0, output)
        second = (self.destination / raven.IGNORE_PATH).read_text(encoding="utf-8")

        self.assertEqual(first, second)
        non_blank = [line for line in second.splitlines() if line.strip()]
        self.assertEqual(len(non_blank), len(set(non_blank)), "duplicate line(s) after a re-run")


class IgnoreBlockFormattingTests(unittest.TestCase):
    """#217's conditional separator, applied to ``.ignore``.

    A file created from nothing must not open on a blank line; a file appended
    to must be separated from its existing content by exactly one.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.destination = Path(self.tmp.name)

    def _merge(self) -> str:
        raven.ensure_ignore_lines(self.destination)
        return (self.destination / raven.IGNORE_PATH).read_text(encoding="utf-8")

    def test_a_created_file_has_no_leading_blank_line(self):
        text = self._merge()
        self.assertTrue(
            text.startswith("# Raven:"),
            f"generated file should open with the header comment, got {text[:40]!r}",
        )

    def test_appending_separates_from_existing_content_with_one_blank_line(self):
        (self.destination / raven.IGNORE_PATH).write_text("vendor/\n", encoding="utf-8")

        text = self._merge()

        self.assertTrue(
            text.startswith("vendor/\n\n# Raven:"),
            f"expected exactly one blank line before the header, got {text[:48]!r}",
        )

    def test_appending_to_content_without_a_trailing_newline_stays_well_formed(self):
        (self.destination / raven.IGNORE_PATH).write_text("vendor/", encoding="utf-8")

        text = self._merge()

        self.assertIn("vendor/", text.splitlines())
        self.assertTrue(
            text.startswith("vendor/\n\n# Raven:"),
            f"expected the missing newline to be supplied, got {text[:48]!r}",
        )

    def test_every_required_line_is_still_written(self):
        text = self._merge()
        for line in _required_lines(SHIPPED_IGNORE.read_text(encoding="utf-8")):
            self.assertIn(line, text.splitlines())

    def test_the_header_says_why_the_lines_are_there(self):
        header = next(line for line in self._merge().splitlines() if line.startswith("# Raven:"))
        self.assertIn("search", header)


class IgnoreHomeDirectoryGuardTests(unittest.TestCase):
    """The home directory itself is the one destination that must not get the file.

    ``~/.claude`` is Claude Code's runtime state -- conversation transcripts,
    job output, plugins, caches -- measured in gigabytes, not the guidance
    Raven ships. The ``dotfiles`` template's target "may be ``~/.config``, a
    ``dotfiles/`` repository, or any home-directory config layout", so ``$HOME``
    itself is a reachable destination, and ``!.claude/`` written there would
    make every search from the home directory drag through all of it.

    A negation for a Raven-owned subpath does not solve this: the hidden-file
    filter drops ``.claude/`` before its children are considered, so
    ``!.claude/docs/`` alone matches nothing. Skipping the file entirely at
    ``$HOME`` is the whole fix.

    ``Path.home`` is patched in every test here; none of them reads or writes
    the developer's real home directory.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name) / "fake-home"
        self.home.mkdir()
        patcher = mock.patch.object(Path, "home", classmethod(lambda cls: self.home))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_the_home_directory_itself_gets_no_ignore_file(self):
        raven.ensure_ignore_lines(self.home)

        self.assertFalse(
            (self.home / raven.IGNORE_PATH).exists(),
            "writing !.claude/ at $HOME un-hides Claude Code's runtime state",
        )

    def test_a_subdirectory_of_home_still_gets_the_file(self):
        # The regression that matters: nearly every repository lives under the
        # home directory, and an over-broad guard would disable the feature for
        # all of them.
        project = self.home / "Developer" / "some-project"
        project.mkdir(parents=True)

        raven.ensure_ignore_lines(project)

        lines = (project / raven.IGNORE_PATH).read_text(encoding="utf-8").splitlines()
        self.assertIn("!.claude/", lines)
        self.assertIn("!.agents/", lines)

    def test_a_dotfiles_style_subdirectory_of_home_still_gets_the_file(self):
        for name in (".config", "dotfiles"):
            with self.subTest(name=name):
                target = self.home / name
                target.mkdir()

                raven.ensure_ignore_lines(target)

                self.assertTrue((target / raven.IGNORE_PATH).is_file())

    def test_an_existing_ignore_at_home_is_left_byte_for_byte_unchanged(self):
        existing = "# my own rules\nnode_modules/\n"
        target = self.home / raven.IGNORE_PATH
        target.write_bytes(existing.encode("utf-8"))

        raven.ensure_ignore_lines(self.home)

        self.assertEqual(target.read_bytes(), existing.encode("utf-8"))

    def test_a_symlink_or_unresolved_path_to_home_is_still_recognized(self):
        # The comparison resolves both sides, so a path that reaches home by a
        # different spelling is caught too.
        indirect = self.home / "sub" / ".."
        (self.home / "sub").mkdir()

        raven.ensure_ignore_lines(indirect)

        self.assertFalse((self.home / raven.IGNORE_PATH).exists())

    def test_an_unavailable_home_directory_does_not_break_the_merge(self):
        # `Path.home()` raises when no home can be determined. That must read
        # as "this destination is not home", not crash an install.
        project = self.home / "project"
        project.mkdir()
        with mock.patch.object(
            Path, "home", classmethod(lambda cls: (_ for _ in ()).throw(RuntimeError("no home")))
        ):
            raven.ensure_ignore_lines(project)

        self.assertTrue((project / raven.IGNORE_PATH).is_file())


class IgnoreMergeOnlySafetyTests(RavenTestCase):
    """A merge-only path must survive every classification that can delete a file.

    ``classify_orphans`` removes manifest-tracked files the template no longer
    ships. If ``.ignore`` ever reached the manifest, a later upgrade would
    delete a file the user owns. It cannot, because merge-only paths never
    become managed entries -- these tests are what says so.
    """

    USER_LINES = "# my own ignore rules\nvendor/\nfixtures/large/\n"

    def _install(self):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            rc = raven._run(
                self.destination,
                raven.load_config(self.destination),
                "python",
                False,
                False,
                [],
            )
        self.assertEqual(rc, 0, out.getvalue())
        return out.getvalue()

    def test_ignore_is_treated_as_merge_only(self):
        self.assertIn(raven.IGNORE_PATH, raven.MERGE_ONLY_TEMPLATE_PATHS)

    def test_the_walk_never_yields_ignore_as_a_copyable_entry(self):
        entries = raven.iter_template_entries(COMMON, set())
        self.assertNotIn(raven.IGNORE_PATH, {entry.relative for entry in entries})

    def test_classification_never_buckets_ignore(self):
        (self.destination / raven.IGNORE_PATH).write_text(self.USER_LINES, encoding="utf-8")

        classification = raven.classify(self.template, self.destination, self.excludes)

        for bucket in (
            classification.will_copy,
            classification.will_upgrade,
            classification.identical,
            classification.unknown_existing,
            classification.needs_merge,
        ):
            self.assertNotIn(raven.IGNORE_PATH, bucket)

    def test_a_pre_existing_ignore_survives_install_then_upgrade(self):
        target = self.destination / raven.IGNORE_PATH
        target.write_text(self.USER_LINES, encoding="utf-8")

        self._install()
        self._install()

        self.assertTrue(target.is_file(), ".ignore was deleted")
        lines = target.read_text(encoding="utf-8").splitlines()
        for user_line in self.USER_LINES.splitlines():
            self.assertIn(user_line, lines)
        self.assertIn("!.agents/", lines)

    def test_ignore_never_enters_the_manifest(self):
        self._install()

        manifest = raven.load_manifest(self.destination)

        self.assertNotIn(raven.IGNORE_PATH, manifest.get("files", {}))

    def test_ignore_is_never_an_orphan(self):
        self._install()

        orphans = classify_orphans(
            self.template, self.destination, raven.load_manifest(self.destination)
        )

        for bucket in (orphans.will_remove, orphans.orphan_modified, orphans.already_gone):
            self.assertNotIn(raven.IGNORE_PATH, bucket)

    def test_ignore_is_never_deactivated(self):
        self._install()

        deactivated = classify_deactivated(
            self.template,
            self.destination,
            raven.load_manifest(self.destination),
            raven.load_config(self.destination),
        )

        for bucket in (deactivated.removable, deactivated.preserved):
            self.assertNotIn(raven.IGNORE_PATH, bucket)

    def test_a_customized_ignore_is_never_reported_as_drift(self):
        self._install()
        target = self.destination / raven.IGNORE_PATH
        target.write_text(target.read_text(encoding="utf-8") + "!.mine/\n", encoding="utf-8")

        findings = drift_findings(self.destination)

        for finding in findings:
            self.assertNotIn(raven.IGNORE_PATH, finding.title)
            self.assertNotIn(raven.IGNORE_PATH, finding.detail)


class IgnoreSearchabilityTests(RavenTestCase):
    """The acceptance criterion, run against the real binaries.

    Each tool is asked for a string that exists only under a dot-directory,
    with no ``--hidden`` or ``--no-ignore`` flag. With the shipped ``.ignore``
    in place it must find the file; with the file removed it must not -- the
    negative half is what proves the ``.ignore`` is doing the work rather than
    some unrelated default.
    """

    NEEDLE = "raven_ignore_searchability_needle"

    def setUp(self):
        super().setUp()
        with contextlib.redirect_stdout(io.StringIO()) as out:
            rc = raven._run(
                self.destination,
                raven.load_config(self.destination),
                "python",
                False,
                False,
                [],
            )
        self.assertEqual(rc, 0, out.getvalue())
        self.needle_file = self.destination / ".agents" / f"{self.NEEDLE}.py"
        self.needle_file.write_text(f'{self.NEEDLE} = "x"\n', encoding="utf-8")

    def _run(self, *argv: str) -> str:
        result = subprocess.run(
            list(argv),
            cwd=str(self.destination),
            capture_output=True,
            text=True,
            check=False,
        )
        return result.stdout

    def _assert_both_directions(self, *argv: str) -> None:
        self.assertIn(
            self.NEEDLE,
            self._run(*argv),
            f"{argv[0]} did not see .agents/ with the shipped .ignore in place",
        )
        (self.destination / raven.IGNORE_PATH).unlink()
        self.assertNotIn(
            self.NEEDLE,
            self._run(*argv),
            f"{argv[0]} still saw .agents/ without an .ignore -- the test proves nothing",
        )

    @unittest.skipUnless(shutil.which("rg"), "ripgrep not installed")
    def test_ripgrep_searches_installed_guidance_by_default(self):
        self._assert_both_directions("rg", "--files-with-matches", self.NEEDLE, ".")

    @unittest.skipUnless(shutil.which("fd"), "fd not installed")
    def test_fd_finds_installed_guidance_by_default(self):
        self._assert_both_directions("fd", self.NEEDLE, ".")

    @unittest.skipUnless(shutil.which("ast-grep"), "ast-grep not installed")
    def test_ast_grep_matches_installed_guidance_by_default(self):
        self._assert_both_directions(
            "ast-grep", "run", "--lang", "python", "--pattern", f"{self.NEEDLE} = $V", "."
        )


if __name__ == "__main__":
    unittest.main()
