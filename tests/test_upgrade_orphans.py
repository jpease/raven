"""End-to-end coverage for issue #97 Task 3: orphan handling wired into
``raven upgrade``.

These tests drive the real ``cmd_install``/``cmd_upgrade`` CLI entry points
(the same harness ``tests/test_installer_safety.py`` uses) against a
throwaway, single-use language template rather than the real ``python``
template under ``REPO_ROOT``: the real template is immutable and these tests
need to remove a file from the template between install and upgrade to
simulate "the template no longer ships this file".
"""

from __future__ import annotations

import argparse
import contextlib
import io
import os
import re
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from helpers import RavenTestCase, raven
from raven_lib.cli import _template_switch_decision
from raven_lib.manifest import load_manifest


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _install_ns(
    destination: Path,
    *,
    language: str | None,
    confirm_template_switch: bool = False,
) -> argparse.Namespace:
    return argparse.Namespace(
        destination=str(destination),
        language=language,
        args=None,
        overrides=[],
        dry_run=False,
        include_readme=False,
        adopt_claude_symlink=False,
        confirm_template_switch=confirm_template_switch,
        platform=None,
    )


def _upgrade_ns(
    destination: Path,
    *,
    dry_run: bool = False,
    confirm_template_switch: bool = False,
) -> argparse.Namespace:
    return argparse.Namespace(
        destination=str(destination),
        overrides=[],
        dry_run=dry_run,
        include_readme=False,
        adopt_claude_symlink=False,
        confirm_template_switch=confirm_template_switch,
    )


class UpgradeOrphanTests(RavenTestCase):
    def setUp(self) -> None:
        super().setUp()
        # A fake REPO_ROOT containing one throwaway language template
        # ("lang"), so the test can delete a file from it between install
        # and upgrade without touching the real, immutable python template.
        self._fake_repo_tmp = TemporaryDirectory()
        self.addCleanup(self._fake_repo_tmp.cleanup)
        self.fake_repo_root = Path(self._fake_repo_tmp.name)
        self.template_dir = self.fake_repo_root / "lang"
        _write(self.template_dir / "AGENTS.md", "root instructions\n")
        _write(self.template_dir / "docs" / "dropped.md", "shipped content\n")
        patcher = mock.patch("raven_lib.cli.REPO_ROOT", self.fake_repo_root)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _install(self) -> None:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            rc = raven.cmd_install(_install_ns(self.destination, language="lang"))
        self.assertEqual(rc, 0)

    def _upgrade(self) -> tuple[int, str]:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
            rc = raven.cmd_upgrade(_upgrade_ns(self.destination))
        return rc, buf.getvalue()

    def test_clean_orphan_removed_and_reported(self) -> None:
        self._install()
        dropped = self.destination / "docs" / "dropped.md"
        self.assertTrue(dropped.exists())
        self.assertIn("docs/dropped.md", load_manifest(self.destination)["files"])

        # Template stops shipping docs/dropped.md.
        (self.template_dir / "docs" / "dropped.md").unlink()

        rc, output = self._upgrade()
        self.assertEqual(rc, 0)
        self.assertFalse(dropped.exists())
        self.assertNotIn("docs/dropped.md", load_manifest(self.destination)["files"])
        self.assertIn("Removed 1 orphaned file(s)", output)
        self.assertIn("docs/dropped.md", output)

    def test_modified_orphan_kept_and_reported(self) -> None:
        self._install()
        dropped = self.destination / "docs" / "dropped.md"
        dropped.write_text("user edited this locally\n", encoding="utf-8")

        (self.template_dir / "docs" / "dropped.md").unlink()

        rc, output = self._upgrade()
        self.assertEqual(rc, 0)
        self.assertTrue(dropped.exists())
        self.assertEqual(dropped.read_text(encoding="utf-8"), "user edited this locally\n")
        # A locally modified orphan keeps its manifest record; it was never
        # removed, so there is nothing stale to prune.
        self.assertIn("docs/dropped.md", load_manifest(self.destination)["files"])
        self.assertIn(
            "Orphaned but left in place because you modified them",
            output,
        )
        self.assertIn("docs/dropped.md", output)

    def test_existing_starter_config_never_removed(self) -> None:
        from raven_lib.constants import STARTER_TOOL_CONFIG_PATHS

        starter = sorted(STARTER_TOOL_CONFIG_PATHS)[0]
        _write(self.template_dir / starter, "shipped\n")
        self._install()
        starter_path = self.destination / starter
        self.assertTrue(starter_path.exists())
        self.assertIn(starter, load_manifest(self.destination)["files"])

        # Upgrade against the same (full) template: the starter config is
        # still shipped, so it must never be classified as an orphan, let
        # alone removed.
        rc, output = self._upgrade()
        self.assertEqual(rc, 0)
        self.assertTrue(starter_path.exists())
        self.assertEqual(starter_path.read_text(encoding="utf-8"), "shipped\n")
        self.assertIn(starter, load_manifest(self.destination)["files"])
        self.assertNotIn("Removed", output)

    def test_absolute_manifest_key_never_deletes_external_file(self) -> None:
        # A crafted/corrupted manifest with an absolute key pointing outside the
        # destination must never lead a live upgrade to name or delete that file.
        from raven_lib.hashing import file_sha256
        from raven_lib.manifest import save_manifest

        self._install()
        outside = self.fake_repo_root / "evil.md"  # outside the destination
        _write(outside, "precious\n")
        sha = file_sha256(outside)

        manifest = load_manifest(self.destination)
        manifest["files"][str(outside)] = {
            "kind": "file",
            "installedSha256": sha,
            "sourceSha256": sha,
        }
        save_manifest(self.destination, manifest)

        rc, output = self._upgrade()
        self.assertEqual(rc, 0)
        self.assertTrue(outside.exists(), "live upgrade deleted a file outside the destination")
        self.assertNotIn(str(outside), output)

    @unittest.skipIf(
        sys.platform.startswith("win"),
        "read-only directories behave differently on Windows",
    )
    @unittest.skipIf(
        hasattr(os, "geteuid") and os.geteuid() == 0,
        "running as root bypasses permission checks",
    )
    def test_read_only_parent_reports_error_and_retains_manifest_record(self) -> None:
        # When a file's parent directory is read-only, raven upgrade must report
        # a clean error and non-zero exit rather than a traceback. The file
        # remains on disk, its manifest record is retained (so the next run can
        # retry), and copies/upgrades that succeeded still land and update the
        # manifest for everything that worked (#183).
        self._install()
        dropped = self.destination / "docs" / "dropped.md"
        self.assertTrue(dropped.exists())
        self.assertIn("docs/dropped.md", load_manifest(self.destination)["files"])

        # Template stops shipping docs/dropped.md.
        (self.template_dir / "docs" / "dropped.md").unlink()
        # Make the parent directory read-only to block orphan removal.
        locked_dir = dropped.parent
        locked_dir.chmod(0o555)

        try:
            err = io.StringIO()
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
                rc = raven.cmd_upgrade(_upgrade_ns(self.destination))
            err_output = err.getvalue()

            # Non-zero exit code signals the error.
            self.assertEqual(rc, 1)
            # File still exists because unlink was blocked.
            self.assertTrue(dropped.exists())
            # Manifest record is retained because the file was not removed.
            self.assertIn("docs/dropped.md", load_manifest(self.destination)["files"])
            # Error is reported to stderr with the path and reason.
            self.assertIn("error:", err_output)
            self.assertIn("docs/dropped.md", err_output)
            # No traceback should appear (just the error message).
            self.assertNotIn("Traceback", err_output)
        finally:
            # Restore permissions so TemporaryDirectory can clean up.
            locked_dir.chmod(0o755)


# ---------------------------------------------------------------------------
# #175 — switching `template` in .raven/config.toml is a supported workflow, but
# it makes every file the new template does not ship look like an orphan. Two
# separate defences: starter tool configs are never orphans at all, and a
# detected switch refuses the whole run unless it is confirmed.
# ---------------------------------------------------------------------------


class TemplateSwitchTests(RavenTestCase):
    """python -> dotfiles, in miniature: `lang_a` ships files `lang_b` does not."""

    def setUp(self) -> None:
        super().setUp()
        from raven_lib.constants import STARTER_TOOL_CONFIG_PATHS

        self.starter = "pyproject.toml"
        self.assertIn(self.starter, STARTER_TOOL_CONFIG_PATHS)
        self._fake_repo_tmp = TemporaryDirectory()
        self.addCleanup(self._fake_repo_tmp.cleanup)
        self.fake_repo_root = Path(self._fake_repo_tmp.name)
        for name in ("lang_a", "lang_b"):
            _write(self.fake_repo_root / name / "AGENTS.md", "root instructions\n")
        # Only lang_a ships these: a starter tool config (never an orphan) and
        # an ordinary template file (a genuine orphan once confirmed).
        _write(self.fake_repo_root / "lang_a" / self.starter, "[project]\nname = 'x'\n")
        _write(self.fake_repo_root / "lang_a" / "justfile", "default:\n    @echo hi\n")
        patcher = mock.patch("raven_lib.cli.REPO_ROOT", self.fake_repo_root)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.starter_path = self.destination / self.starter
        self.justfile_path = self.destination / "justfile"

    def _install(self, language: str = "lang_a") -> None:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            rc = raven.cmd_install(_install_ns(self.destination, language=language))
        self.assertEqual(rc, 0)
        self.assertTrue(self.starter_path.exists())
        self.assertTrue(self.justfile_path.exists())

    def _switch_config_template(self, template_name: str) -> None:
        from raven_lib.constants import CONFIG_PATH

        config_path = self.destination / CONFIG_PATH
        text = config_path.read_text(encoding="utf-8")
        new_text = re.sub(
            r'(?m)^template\s*=\s*".*"$', f'template = "{template_name}"', text, count=1
        )
        self.assertNotEqual(text, new_text)  # the substitution actually matched
        config_path.write_text(new_text, encoding="utf-8")

    def _upgrade(self, **kwargs: bool) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = raven.cmd_upgrade(_upgrade_ns(self.destination, **kwargs))
        return rc, out.getvalue(), err.getvalue()

    def _assert_nothing_removed(self) -> None:
        self.assertTrue(self.starter_path.exists())
        self.assertTrue(self.justfile_path.exists())
        tracked = load_manifest(self.destination)["files"]
        self.assertIn(self.starter, tracked)
        self.assertIn("justfile", tracked)

    def test_switch_refused_without_confirmation(self) -> None:
        self._install()
        self._switch_config_template("lang_b")

        rc, _out, err = self._upgrade()
        self.assertEqual(rc, 2)
        self._assert_nothing_removed()
        self.assertIn("lang_a", err)
        self.assertIn("lang_b", err)
        self.assertIn("--confirm-template-switch", err)

    def test_switch_refused_in_dry_run_without_confirmation(self) -> None:
        # A dry run never writes, but it must not preview a template switch as
        # a routine upgrade either -- and it must never block on stdin.
        self._install()
        self._switch_config_template("lang_b")

        with mock.patch("builtins.input", side_effect=AssertionError("prompted in dry-run")):
            rc, _out, err = self._upgrade(dry_run=True)
        self.assertEqual(rc, 2)
        self._assert_nothing_removed()
        self.assertIn("--confirm-template-switch", err)

    def test_bare_install_refuses_switch_too(self) -> None:
        # `raven install` with no language re-applies whatever config.template
        # now says, so it reaches the same orphan removal as upgrade.
        self._install()
        self._switch_config_template("lang_b")

        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = raven.cmd_install(_install_ns(self.destination, language=None))
        self.assertEqual(rc, 2)
        self._assert_nothing_removed()
        self.assertIn("--confirm-template-switch", err.getvalue())

    def test_confirmed_switch_keeps_starter_config_and_orphans_the_rest(self) -> None:
        self._install()
        self._switch_config_template("lang_b")

        rc, out, _err = self._upgrade(confirm_template_switch=True)
        self.assertEqual(rc, 0)
        # A starter tool config is never an orphan, even though lang_b does not
        # ship one and the file still matches its recorded baseline exactly.
        self.assertTrue(self.starter_path.exists())
        self.assertIn(self.starter, load_manifest(self.destination)["files"])
        # An ordinary template file the new template does not ship is a genuine
        # orphan; removing it is what the confirmation authorized.
        self.assertFalse(self.justfile_path.exists())
        self.assertNotIn("justfile", load_manifest(self.destination)["files"])
        self.assertIn("Removed 1 orphaned file(s)", out)

    def test_interactive_confirmation_allows_the_switch(self) -> None:
        self._install()
        self._switch_config_template("lang_b")

        with (
            mock.patch("sys.stdin.isatty", return_value=True),
            mock.patch("builtins.input", side_effect=["y"]),
        ):
            rc, _out, _err = self._upgrade()
        self.assertEqual(rc, 0)
        self.assertTrue(self.starter_path.exists())
        self.assertFalse(self.justfile_path.exists())

    def test_interactive_decline_refuses_the_switch(self) -> None:
        self._install()
        self._switch_config_template("lang_b")

        with (
            mock.patch("sys.stdin.isatty", return_value=True),
            mock.patch("builtins.input", side_effect=["n"]),
        ):
            rc, _out, err = self._upgrade()
        self.assertEqual(rc, 2)
        self._assert_nothing_removed()
        self.assertIn("--confirm-template-switch", err)

    def test_same_template_upgrade_is_never_gated(self) -> None:
        # The common case must not prompt or refuse: no switch, no gate.
        self._install()
        with mock.patch("builtins.input", side_effect=AssertionError("prompted without a switch")):
            rc, _out, _err = self._upgrade()
        self.assertEqual(rc, 0)
        self._assert_nothing_removed()

    def test_fresh_install_is_never_treated_as_a_switch(self) -> None:
        # No manifest yet means no prior template, which is not a mismatch.
        with mock.patch("builtins.input", side_effect=AssertionError("prompted on fresh install")):
            self._install()


class TemplateSwitchDecisionTests(unittest.TestCase):
    def test_missing_or_matching_prior_template_is_skip(self) -> None:
        for prior in (None, "", "lang_a", 17):
            with self.subTest(prior=prior):
                self.assertEqual(
                    _template_switch_decision(
                        prior_template=prior, template_name="lang_a", requested=False
                    ),
                    "skip",
                )

    def test_mismatch_prompts_unless_pre_authorized(self) -> None:
        self.assertEqual(
            _template_switch_decision(
                prior_template="lang_a", template_name="lang_b", requested=False
            ),
            "prompt",
        )
        self.assertEqual(
            _template_switch_decision(
                prior_template="lang_a", template_name="lang_b", requested=True
            ),
            "auto",
        )


class TemplateSwitchPromptTests(unittest.TestCase):
    def _prompt(self) -> bool:
        return raven.prompt_for_template_switch("lang_a", "lang_b")

    def test_non_interactive_declines_without_reading_stdin(self) -> None:
        with (
            mock.patch("sys.stdin.isatty", return_value=False),
            mock.patch("builtins.input", side_effect=AssertionError("read stdin without a tty")),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertFalse(self._prompt())

    def test_accepts_y_and_yes(self) -> None:
        for answer in ("y", "Y", "yes"):
            with (
                self.subTest(answer=answer),
                mock.patch("sys.stdin.isatty", return_value=True),
                mock.patch("builtins.input", side_effect=[answer]),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertTrue(self._prompt())

    def test_declines_on_no_empty_or_eof(self) -> None:
        for answer in ("n", "no", ""):
            with (
                self.subTest(answer=answer),
                mock.patch("sys.stdin.isatty", return_value=True),
                mock.patch("builtins.input", side_effect=[answer]),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertFalse(self._prompt())
        with (
            mock.patch("sys.stdin.isatty", return_value=True),
            mock.patch("builtins.input", side_effect=EOFError),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertFalse(self._prompt())

    def test_reprompts_on_unrecognized_answer(self) -> None:
        with (
            mock.patch("sys.stdin.isatty", return_value=True),
            mock.patch("builtins.input", side_effect=["maybe", "y"]) as prompt,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertTrue(self._prompt())
        self.assertEqual(prompt.call_count, 2)


if __name__ == "__main__":
    unittest.main()
