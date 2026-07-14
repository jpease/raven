"""Regression tests for epic #29 — installer failures must be safe and deterministic.

Covers:
- #30 reject malformed config instead of falling back to the default template
- #31 validate install requests before writing any configuration
- #32 preflight destination path collisions before copying files
- #68 EOF at the interactive prompt, case-variant template names, and
  conflicting explicit languages
"""

import argparse
import contextlib
import io
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from helpers import RavenTestCase, raven
from raven_lib.findings import Severity


def _install_ns(
    destination,
    *,
    language=None,
    overrides=None,
    dry_run=False,
    platform=None,
    include_readme=False,
):
    return argparse.Namespace(
        destination=str(destination),
        language=language,
        args=None,
        overrides=overrides or [],
        dry_run=dry_run,
        include_readme=include_readme,
        adopt_claude_symlink=False,
        platform=platform,
    )


def _upgrade_ns(destination, *, overrides=None, dry_run=False):
    return argparse.Namespace(
        destination=str(destination),
        overrides=overrides or [],
        dry_run=dry_run,
        include_readme=False,
        adopt_claude_symlink=False,
    )


def _write_config(destination, text):
    config_path = destination / ".raven" / "config.toml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(text, encoding="utf-8")
    return config_path


def _tree(destination):
    return sorted(p.relative_to(destination).as_posix() for p in destination.rglob("*"))


# ---------------------------------------------------------------------------
# #30 — Reject malformed config instead of selecting the default template
# ---------------------------------------------------------------------------
class MalformedConfigTests(RavenTestCase):
    def test_parse_simple_toml_rejects_malformed_line(self):
        with self.assertRaises(raven.ConfigError):
            raven.parse_simple_toml("this is not valid toml\n")

    def test_load_config_raises_with_path_context(self):
        _write_config(self.destination, "this is not valid toml\n")
        with self.assertRaises(raven.ConfigError) as ctx:
            raven.load_config(self.destination)
        self.assertIn("config.toml", str(ctx.exception))

    def test_upgrade_dry_run_reports_error_and_no_template_fallback(self):
        _write_config(self.destination, "this is not valid toml\n")
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            rc = raven.cmd_upgrade(_upgrade_ns(self.destination, dry_run=True))
        self.assertEqual(rc, 2)
        self.assertIn("not valid Raven config", err.getvalue())
        # Must not silently plan an install of the first language template.
        self.assertNotIn("Template:", err.getvalue())

    def test_install_rejects_malformed_config(self):
        _write_config(self.destination, "garbage\n")
        with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
            rc = raven.cmd_install(_install_ns(self.destination))
        self.assertEqual(rc, 2)

    def test_missing_template_value_does_not_fall_back(self):
        # A structurally valid config with no template line must error, not
        # default to the first language template.
        _write_config(self.destination, 'schema = 1\n[issue_tracker]\nplatform = "none"\n')
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            rc = raven.cmd_upgrade(_upgrade_ns(self.destination))
        self.assertEqual(rc, 2)
        self.assertIn("does not configure a template", err.getvalue())

    def test_doctor_reports_malformed_config_without_crashing(self):
        _write_config(self.destination, "garbage\n")
        findings = raven.build_doctor_findings(self.destination)
        self.assertTrue(
            any(f.severity is Severity.ERROR and "malformed" in f.title.lower() for f in findings)
        )

    def test_assess_reports_malformed_config_without_crashing(self):
        _write_config(self.destination, "garbage\n")
        findings = raven.build_assess_findings(self.destination, run=False)
        self.assertTrue(
            any(f.severity is Severity.ERROR and "malformed" in f.title.lower() for f in findings)
        )


# ---------------------------------------------------------------------------
# #31 — Validate install requests before writing configuration
# ---------------------------------------------------------------------------
class InstallValidationTests(RavenTestCase):
    def test_fresh_install_rejected_override_writes_nothing(self):
        before = _tree(self.destination)
        with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
            rc = raven.cmd_install(
                _install_ns(self.destination, language="python", overrides=["does/not/exist"])
            )
        self.assertEqual(rc, 2)
        self.assertFalse((self.destination / ".raven" / "config.toml").exists())
        self.assertEqual(_tree(self.destination), before)

    def test_existing_config_rejected_install_does_not_change_platform(self):
        config_path = _write_config(
            self.destination, raven.default_config_text("python", False, "none")
        )
        before_bytes = config_path.read_bytes()
        with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
            rc = raven.cmd_install(
                _install_ns(self.destination, overrides=["does/not/exist"], platform="github")
            )
        self.assertEqual(rc, 2)
        # Config bytes are unchanged: the rejected request never reached the write.
        self.assertEqual(config_path.read_bytes(), before_bytes)

    def test_successful_install_still_writes_config(self):
        with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
            rc = raven.cmd_install(_install_ns(self.destination, language="python"))
        self.assertEqual(rc, 0)
        self.assertTrue((self.destination / ".raven" / "config.toml").exists())
        self.assertTrue((self.destination / "AGENTS.md").exists())

    def test_fresh_install_with_include_readme_persists_flag_in_config(self):
        # Regression for #65: --include-readme on a fresh install must survive
        # into config.toml, not just the one-off copy, so later plain
        # `raven upgrade` runs keep including README.md.
        with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
            rc = raven.cmd_install(
                _install_ns(self.destination, language="python", include_readme=True)
            )
        self.assertEqual(rc, 0)
        config_path = self.destination / ".raven" / "config.toml"
        self.assertTrue(config_path.exists())
        self.assertIn("include_readme = true", config_path.read_text(encoding="utf-8"))
        self.assertEqual(raven.load_config(self.destination).include_readme, True)


# ---------------------------------------------------------------------------
# #32 — Preflight destination path collisions before copying files
# ---------------------------------------------------------------------------
class PathCollisionTests(RavenTestCase):
    def test_find_path_collisions_detects_non_directory_ancestor(self):
        (self.destination / ".claude").mkdir()
        (self.destination / ".claude" / "docs").write_text("x", encoding="utf-8")
        collisions = raven.find_path_collisions(
            self.destination, [".claude/docs/raven-namespace.md"]
        )
        self.assertEqual(collisions, [".claude/docs"])

    def test_find_path_collisions_rejects_symlink_to_directory(self):
        # A symlinked ancestor resolves through to its target, so writes beneath
        # it escape the destination tree. Treat it as a collision even though it
        # points at a real directory.
        real = self.destination / "real_dir"
        real.mkdir()
        (self.destination / ".claude").symlink_to(real)
        collisions = raven.find_path_collisions(self.destination, [".claude/docs/x.md"])
        self.assertEqual(collisions, [".claude"])

    def test_find_path_collisions_reports_early_and_late_targets(self):
        (self.destination / ".agents").write_text("x", encoding="utf-8")
        (self.destination / "zzz").write_text("x", encoding="utf-8")
        collisions = raven.find_path_collisions(
            self.destination, [".agents/skills/s.md", "zzz/deep/late.md"]
        )
        self.assertEqual(collisions, [".agents", "zzz"])

    def test_install_collision_leaves_destination_unchanged(self):
        (self.destination / ".claude").mkdir()
        (self.destination / ".claude" / "docs").write_text("planted", encoding="utf-8")
        before = _tree(self.destination)
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            rc = raven.cmd_install(_install_ns(self.destination, language="python"))
        self.assertEqual(rc, 2)
        self.assertIn(".claude/docs", err.getvalue())
        self.assertNotIn("Traceback", err.getvalue())
        # Nothing was written: no config, no managed files, planted file intact.
        self.assertEqual(_tree(self.destination), before)
        self.assertEqual(
            (self.destination / ".claude" / "docs").read_text(encoding="utf-8"), "planted"
        )

    def test_dry_run_reports_collision_and_writes_nothing(self):
        (self.destination / ".agents").write_text("planted", encoding="utf-8")
        before = _tree(self.destination)
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            rc = raven.cmd_install(_install_ns(self.destination, language="python", dry_run=True))
        self.assertEqual(rc, 2)
        self.assertIn(".agents", err.getvalue())
        self.assertEqual(_tree(self.destination), before)


# ---------------------------------------------------------------------------
# #45 — Block writes through ancestor directory symlinks
# ---------------------------------------------------------------------------
class AncestorSymlinkContainmentTests(RavenTestCase):
    def _external_dir(self):
        external = tempfile.TemporaryDirectory()
        self.addCleanup(external.cleanup)
        return Path(external.name)

    def test_install_through_claude_ancestor_symlink_writes_nothing_external(self):
        external = self._external_dir()
        (self.destination / ".claude").symlink_to(external)
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            rc = raven.cmd_install(_install_ns(self.destination, language="python"))
        self.assertEqual(rc, 2)
        self.assertIn(".claude", err.getvalue())
        self.assertNotIn("Traceback", err.getvalue())
        # The external directory the symlink points at is untouched.
        self.assertEqual(list(external.iterdir()), [])
        # No config was written either.
        self.assertFalse((self.destination / ".raven" / "config.toml").exists())

    def test_upgrade_through_raven_ancestor_symlink_writes_nothing_external(self):
        # A symlinked .raven would redirect config, manifest, and merge-state
        # writes outside the destination.
        external = self._external_dir()
        (external / "config.toml").write_text(
            raven.default_config_text("python", False, "none"), encoding="utf-8"
        )
        (self.destination / ".raven").symlink_to(external)
        before = sorted(p.name for p in external.iterdir())
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            rc = raven.cmd_upgrade(_upgrade_ns(self.destination))
        self.assertEqual(rc, 2)
        self.assertIn(".raven", err.getvalue())
        self.assertNotIn("Traceback", err.getvalue())
        # No manifest or merge artifacts were written through the symlink.
        self.assertEqual(sorted(p.name for p in external.iterdir()), before)

    def test_dry_run_reports_ancestor_symlink_and_writes_nothing(self):
        external = self._external_dir()
        (self.destination / ".claude").symlink_to(external)
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            rc = raven.cmd_install(_install_ns(self.destination, language="python", dry_run=True))
        self.assertEqual(rc, 2)
        self.assertIn(".claude", err.getvalue())
        self.assertEqual(list(external.iterdir()), [])


# ---------------------------------------------------------------------------
# #101 — Block writes through a symlinked final state file (.raven is a real dir)
# ---------------------------------------------------------------------------
class StateFileSymlinkContainmentTests(RavenTestCase):
    """A symlinked .raven/config.toml or .raven/manifest.json (while .raven is a
    real directory) must not let Raven read/write through it to an external file.

    The ancestor collision check only inspects directories, so it never sees a
    symlinked *final* state file; these tests cover that gap.
    """

    def _external_dir(self):
        external = tempfile.TemporaryDirectory()
        self.addCleanup(external.cleanup)
        return Path(external.name)

    def _install_python(self):
        with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
            rc = raven.cmd_install(_install_ns(self.destination, language="python"))
        self.assertEqual(rc, 0)

    def test_find_state_symlink_collisions_flags_symlinked_state_path(self):
        (self.destination / ".raven").mkdir()
        real = self.destination / "elsewhere.json"
        real.write_text("{}", encoding="utf-8")
        (self.destination / ".raven" / "manifest.json").symlink_to(real)
        result = raven.find_state_symlink_collisions(
            self.destination, [".raven/manifest.json", ".raven/config.toml"]
        )
        self.assertEqual(result, [".raven/manifest.json"])

    def test_find_state_symlink_collisions_ignores_real_and_absent(self):
        (self.destination / ".raven").mkdir()
        (self.destination / ".raven" / "config.toml").write_text("x", encoding="utf-8")
        # config.toml is a real file; manifest.json is absent. Neither is a symlink.
        result = raven.find_state_symlink_collisions(
            self.destination, [".raven/config.toml", ".raven/manifest.json"]
        )
        self.assertEqual(result, [])

    def test_find_state_symlink_collisions_flags_broken_symlink(self):
        (self.destination / ".raven").mkdir()
        (self.destination / ".raven" / "manifest.json").symlink_to(self.destination / "gone.json")
        result = raven.find_state_symlink_collisions(self.destination, [".raven/manifest.json"])
        self.assertEqual(result, [".raven/manifest.json"])

    def test_upgrade_through_manifest_symlink_leaves_external_unchanged(self):
        self._install_python()
        external = self._external_dir()
        manifest_path = self.destination / ".raven" / "manifest.json"
        external_manifest = external / "manifest.json"
        external_manifest.write_bytes(manifest_path.read_bytes())
        manifest_path.unlink()
        manifest_path.symlink_to(external_manifest)
        before = external_manifest.read_bytes()

        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            rc = raven.cmd_upgrade(_upgrade_ns(self.destination))
        self.assertEqual(rc, 2)
        self.assertIn("manifest.json", err.getvalue())
        self.assertNotIn("Traceback", err.getvalue())
        # The external target the symlink points at is byte-for-byte unchanged,
        # and the link itself is preserved (nothing was rewritten through it).
        self.assertEqual(external_manifest.read_bytes(), before)
        self.assertTrue(manifest_path.is_symlink())

    def test_upgrade_dry_run_reports_manifest_symlink_and_writes_nothing(self):
        self._install_python()
        external = self._external_dir()
        manifest_path = self.destination / ".raven" / "manifest.json"
        external_manifest = external / "manifest.json"
        external_manifest.write_bytes(manifest_path.read_bytes())
        manifest_path.unlink()
        manifest_path.symlink_to(external_manifest)
        before = external_manifest.read_bytes()

        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            rc = raven.cmd_upgrade(_upgrade_ns(self.destination, dry_run=True))
        # Dry-run reports the same collision as live execution (parity) and
        # never touches the external file.
        self.assertEqual(rc, 2)
        self.assertIn("manifest.json", err.getvalue())
        self.assertEqual(external_manifest.read_bytes(), before)

    def test_upgrade_through_broken_manifest_symlink_is_rejected(self):
        self._install_python()
        external = self._external_dir()
        manifest_path = self.destination / ".raven" / "manifest.json"
        manifest_path.unlink()
        manifest_path.symlink_to(external / "does-not-exist.json")

        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            rc = raven.cmd_upgrade(_upgrade_ns(self.destination))
        self.assertEqual(rc, 2)
        self.assertIn("manifest.json", err.getvalue())
        self.assertNotIn("Traceback", err.getvalue())

    def test_install_through_config_symlink_leaves_external_unchanged(self):
        self._install_python()
        external = self._external_dir()
        config_path = self.destination / ".raven" / "config.toml"
        external_config = external / "config.toml"
        external_config.write_bytes(config_path.read_bytes())
        config_path.unlink()
        config_path.symlink_to(external_config)
        before = external_config.read_bytes()

        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            rc = raven.cmd_install(_install_ns(self.destination, platform="github"))
        self.assertEqual(rc, 2)
        self.assertIn("config.toml", err.getvalue())
        self.assertNotIn("Traceback", err.getvalue())
        # The external config's platform is not changed by the rejected install.
        self.assertEqual(external_config.read_bytes(), before)
        self.assertTrue(config_path.is_symlink())

    def test_save_manifest_replaces_symlink_in_place(self):
        # Durable containment for the cmd_accept path, which does not go through
        # the _run preflight: save_manifest must land on a real file inside the
        # destination rather than following a symlink out of it.
        external = self._external_dir()
        (self.destination / ".raven").mkdir()
        external_manifest = external / "manifest.json"
        external_manifest.write_text('{"schema": 1, "files": {}}\n', encoding="utf-8")
        before = external_manifest.read_bytes()
        manifest_path = self.destination / ".raven" / "manifest.json"
        manifest_path.symlink_to(external_manifest)

        raven.save_manifest(self.destination, {"schema": 1, "files": {"a": {}}})

        self.assertFalse(manifest_path.is_symlink())
        self.assertIn('"a"', manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(external_manifest.read_bytes(), before)


# ---------------------------------------------------------------------------
# #47 — Report unreadable Raven config as invalid
# ---------------------------------------------------------------------------
class UnreadableConfigTests(RavenTestCase):
    def _write_bytes(self, raw: bytes):
        config_path = self.destination / ".raven" / "config.toml"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_bytes(raw)
        return config_path

    def test_load_config_raises_on_invalid_utf8(self):
        self._write_bytes(b"\xff\xfe\x00")
        with self.assertRaises(raven.ConfigError) as ctx:
            raven.load_config(self.destination)
        self.assertIn("config.toml", str(ctx.exception))

    def test_load_config_raises_on_read_oserror(self):
        # A directory at the config path makes read_text raise IsADirectoryError
        # (an OSError), standing in for any I/O failure.
        (self.destination / ".raven").mkdir()
        (self.destination / ".raven" / "config.toml").mkdir()
        with self.assertRaises(raven.ConfigError):
            raven.load_config(self.destination)

    def test_doctor_reports_unreadable_config_as_single_error(self):
        self._write_bytes(b"\xff\xfe\x00")
        findings = raven.build_doctor_findings(self.destination)
        config_errors = [
            f for f in findings if f.id == "doctor.install.config" and f.severity is Severity.ERROR
        ]
        # Reported once, not five duplicate warnings.
        self.assertEqual(len(config_errors), 1)

    def test_doctor_cli_exits_non_zero_for_unreadable_config(self):
        self._write_bytes(b"\xff\xfe\x00")
        ns = argparse.Namespace(destination=str(self.destination), json=True)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            rc = raven.cmd_doctor(ns)
        self.assertNotEqual(rc, 0)

    def test_assess_reports_unreadable_config_as_error(self):
        self._write_bytes(b"\xff\xfe\x00")
        findings = raven.build_assess_findings(self.destination, run=False)
        self.assertTrue(any(f.severity is Severity.ERROR for f in findings))


# ---------------------------------------------------------------------------
# #68 — EOF, case-variant templates, and conflicting explicit languages
# ---------------------------------------------------------------------------
class LanguageHandlingTests(RavenTestCase):
    def test_select_language_eof_aborts_instead_of_looping(self):
        # Ctrl-D at the prompt must abort like the non-tty path, not loop
        # forever re-printing the range prompt on every EOFError.
        with (
            mock.patch("sys.stdin.isatty", return_value=True),
            mock.patch("builtins.input", side_effect=EOFError),
            contextlib.redirect_stdout(io.StringIO()),
            contextlib.redirect_stderr(io.StringIO()) as err,
            self.assertRaises(SystemExit) as ctx,
        ):
            raven.select_language_interactively()
        self.assertEqual(ctx.exception.code, 2)
        self.assertIn("language required", err.getvalue())

    def test_init_rejects_case_variant_language_name(self):
        # "Python" must not silently resolve to the "python" template
        # directory via a case-insensitive filesystem lookup.
        err = io.StringIO()
        ns = argparse.Namespace(destination=str(self.destination), language="Python")
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            rc = raven.cmd_init(ns)
        self.assertEqual(rc, 2)
        self.assertIn("unknown language template", err.getvalue())
        self.assertFalse((self.destination / ".raven" / "config.toml").exists())

    def test_install_rejects_case_variant_language_name(self):
        err = io.StringIO()
        with (
            contextlib.redirect_stderr(err),
            contextlib.redirect_stdout(io.StringIO()),
            self.assertRaises(SystemExit),
        ):
            raven.cmd_install(_install_ns(self.destination, language="Python"))
        self.assertFalse((self.destination / ".raven" / "config.toml").exists())

    def test_install_rejects_conflicting_explicit_language(self):
        _write_config(self.destination, raven.default_config_text("python", False, "none"))
        before = (self.destination / ".raven" / "config.toml").read_bytes()
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            rc = raven.cmd_install(_install_ns(self.destination, language="go"))
        self.assertEqual(rc, 2)
        self.assertIn("python", err.getvalue())
        self.assertIn("go", err.getvalue())
        # The configured template is untouched by the conflicting request.
        self.assertEqual((self.destination / ".raven" / "config.toml").read_bytes(), before)


# ---------------------------------------------------------------------------
# #70 — install_git_hooks core.hooksPath edge cases
# ---------------------------------------------------------------------------
class GitHooksInstallMessageTests(RavenTestCase):
    def test_install_reports_actual_custom_hooks_path_not_dot_git(self):
        # Regression: the success message hard-coded ".git/hooks/<h>" even when
        # core.hooksPath pointed elsewhere.
        subprocess.run(["git", "init", str(self.destination)], capture_output=True, check=True)
        (self.destination / ".githooks").mkdir()
        subprocess.run(
            ["git", "-C", str(self.destination), "config", "core.hooksPath", ".githooks"],
            capture_output=True,
            check=True,
        )
        out = io.StringIO()
        with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(out):
            rc = raven.cmd_install(_install_ns(self.destination, language="python"))
        self.assertEqual(rc, 0)
        stdout = out.getvalue()
        self.assertIn(".githooks/pre-commit", stdout)
        self.assertNotIn(".git/hooks/", stdout)


# ---------------------------------------------------------------------------
# #102 — `raven init` must preflight containment like install/upgrade
# ---------------------------------------------------------------------------
class InitContainmentTests(RavenTestCase):
    """`raven init` writes a fresh config; it must reject the same unsafe path
    shapes (symlinked ancestors, symlinked/broken final state files, non-dir
    ancestors) that install/upgrade already reject, and never write externally
    or raise an uncaught FileExistsError.
    """

    def _external_dir(self):
        external = tempfile.TemporaryDirectory()
        self.addCleanup(external.cleanup)
        return Path(external.name)

    def _init_ns(self, *, language="python", platform="github"):
        return argparse.Namespace(
            destination=str(self.destination), language=language, platform=platform
        )

    def test_init_through_raven_ancestor_symlink_writes_nothing_external(self):
        external = self._external_dir()
        (self.destination / ".raven").symlink_to(external)
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            rc = raven.cmd_init(self._init_ns())
        self.assertEqual(rc, 2)
        self.assertIn(".raven", err.getvalue())
        self.assertNotIn("Traceback", err.getvalue())
        # The external target the symlink points at is untouched.
        self.assertEqual(list(external.iterdir()), [])

    def test_init_with_regular_file_raven_exits_2_no_traceback(self):
        (self.destination / ".raven").write_text("not a directory", encoding="utf-8")
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            rc = raven.cmd_init(self._init_ns())
        # Must exit 2 with a diagnostic, not raise FileExistsError (rc 1 + traceback).
        self.assertEqual(rc, 2)
        self.assertIn(".raven", err.getvalue())
        self.assertNotIn("Traceback", err.getvalue())

    def test_init_through_broken_config_symlink_exits_2(self):
        (self.destination / ".raven").mkdir()
        (self.destination / ".raven" / "config.toml").symlink_to(self.destination / "gone.toml")
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            rc = raven.cmd_init(self._init_ns())
        self.assertEqual(rc, 2)
        self.assertIn("config.toml", err.getvalue())
        self.assertNotIn("Traceback", err.getvalue())

    def test_init_clean_destination_creates_config(self):
        out = io.StringIO()
        with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(out):
            rc = raven.cmd_init(self._init_ns())
        self.assertEqual(rc, 0)
        self.assertTrue((self.destination / ".raven" / "config.toml").exists())


if __name__ == "__main__":
    unittest.main()
