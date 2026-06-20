"""Regression tests for epic #29 — installer failures must be safe and deterministic.

Covers:
- #30 reject malformed config instead of falling back to the default template
- #31 validate install requests before writing any configuration
- #32 preflight destination path collisions before copying files
"""

import argparse
import contextlib
import io
import unittest

from helpers import RavenTestCase, raven
from raven_lib.findings import Severity


def _install_ns(destination, *, language=None, overrides=None, dry_run=False, platform=None):
    return argparse.Namespace(
        destination=str(destination),
        language=language,
        args=None,
        overrides=overrides or [],
        dry_run=dry_run,
        include_readme=False,
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

    def test_find_path_collisions_allows_symlink_to_directory(self):
        real = self.destination / "real_dir"
        real.mkdir()
        (self.destination / ".claude").symlink_to(real)
        collisions = raven.find_path_collisions(self.destination, [".claude/docs/x.md"])
        self.assertEqual(collisions, [])

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


if __name__ == "__main__":
    unittest.main()
