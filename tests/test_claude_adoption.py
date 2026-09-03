import contextlib
import hashlib
import io
import unittest

from helpers import RavenTestCase, raven


class ClaudeAdoptionTests(RavenTestCase):
    """CLAUDE.md is a plain one-line ``@AGENTS.md`` import file, not a symlink (#253).

    Covers adopting an existing hand-written CLAUDE.md (mirrors the
    .claude/settings.json adoption flow) and migrating a repo installed before
    #253, whose CLAUDE.md is still the old symlink.
    """

    def test_adopt_claude_md_backs_up_existing_file_and_writes_import(self):
        (self.destination / "CLAUDE.md").write_text("custom claude guidance\n", encoding="utf-8")
        entries = raven.entries_for_destination(
            self.template,
            self.excludes,
            raven.load_config(self.destination),
            self.destination,
        )

        changed = raven.adopt_claude_md(self.destination, entries)

        self.assertEqual(changed, ["CLAUDE.md.bak", "CLAUDE.md"])
        self.assertEqual(
            (self.destination / "CLAUDE.md.bak").read_text(encoding="utf-8"),
            "custom claude guidance\n",
        )
        self.assertFalse((self.destination / "CLAUDE.md").is_symlink())
        self.assertEqual(
            (self.destination / "CLAUDE.md").read_text(encoding="utf-8").strip(), "@AGENTS.md"
        )

    def test_adopt_claude_md_refuses_to_overwrite_existing_backup(self):
        (self.destination / "CLAUDE.md").write_text("custom claude guidance\n", encoding="utf-8")
        (self.destination / "CLAUDE.md.bak").write_text("existing backup\n", encoding="utf-8")
        entries = raven.entries_for_destination(
            self.template,
            self.excludes,
            raven.load_config(self.destination),
            self.destination,
        )

        with self.assertRaises(FileExistsError):
            raven.adopt_claude_md(self.destination, entries)

        self.assertEqual(
            (self.destination / "CLAUDE.md").read_text(encoding="utf-8"), "custom claude guidance\n"
        )
        self.assertEqual(
            (self.destination / "CLAUDE.md.bak").read_text(encoding="utf-8"), "existing backup\n"
        )

    def test_run_with_adopt_claude_does_not_report_claude_manual_merge(self):
        (self.destination / "AGENTS.md").write_text("# Existing AGENTS\n", encoding="utf-8")
        (self.destination / "CLAUDE.md").write_text("custom claude guidance\n", encoding="utf-8")
        output = io.StringIO()

        with contextlib.redirect_stdout(output):
            rc = raven._run(
                self.destination,
                raven.load_config(self.destination),
                "python",
                False,
                False,
                [],
                adopt_claude_requested=True,
                prompt_claude=False,
            )

        self.assertEqual(rc, 0)
        self.assertFalse((self.destination / "CLAUDE.md").is_symlink())
        self.assertEqual(
            (self.destination / "CLAUDE.md.bak").read_text(encoding="utf-8"),
            "custom claude guidance\n",
        )
        self.assertIn("Adopted CLAUDE.md as Raven-managed", output.getvalue())
        self.assertNotIn(
            "  CLAUDE.md\n", output.getvalue().split("Wrote guided merge artifacts", 1)[-1]
        )

    def test_run_with_adopt_claude_fails_if_backup_exists(self):
        (self.destination / "AGENTS.md").write_text("# Existing AGENTS\n", encoding="utf-8")
        (self.destination / "CLAUDE.md").write_text("custom claude guidance\n", encoding="utf-8")
        (self.destination / "CLAUDE.md.bak").write_text("existing backup\n", encoding="utf-8")
        output = io.StringIO()

        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            rc = raven._run(
                self.destination,
                raven.load_config(self.destination),
                "python",
                False,
                False,
                [],
                adopt_claude_requested=True,
                prompt_claude=False,
            )

        self.assertEqual(rc, 2)
        self.assertFalse((self.destination / "CLAUDE.md").is_symlink())
        self.assertEqual(
            (self.destination / "CLAUDE.md.bak").read_text(encoding="utf-8"), "existing backup\n"
        )
        self.assertIn("CLAUDE.md.bak already exists", output.getvalue())

    def test_dry_run_with_adopt_claude_reports_backup_without_writing(self):
        (self.destination / "AGENTS.md").write_text("# Existing AGENTS\n", encoding="utf-8")
        (self.destination / "CLAUDE.md").write_text("custom claude guidance\n", encoding="utf-8")
        output = io.StringIO()

        with contextlib.redirect_stdout(output):
            rc = raven._run(
                self.destination,
                raven.load_config(self.destination),
                "python",
                False,
                True,
                [],
                adopt_claude_requested=True,
                prompt_claude=False,
            )

        self.assertEqual(rc, 0)
        self.assertFalse((self.destination / "CLAUDE.md").is_symlink())
        self.assertFalse((self.destination / "CLAUDE.md.bak").exists())
        self.assertIn("Would adopt CLAUDE.md as Raven-managed", output.getvalue())

    def test_dry_run_with_adopt_claude_fails_if_backup_exists(self):
        (self.destination / "AGENTS.md").write_text("# Existing AGENTS\n", encoding="utf-8")
        (self.destination / "CLAUDE.md").write_text("custom claude guidance\n", encoding="utf-8")
        (self.destination / "CLAUDE.md.bak").write_text("existing backup\n", encoding="utf-8")
        output = io.StringIO()

        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            rc = raven._run(
                self.destination,
                raven.load_config(self.destination),
                "python",
                False,
                True,
                [],
                adopt_claude_requested=True,
                prompt_claude=False,
            )

        self.assertEqual(rc, 2)
        self.assertFalse((self.destination / "CLAUDE.md").is_symlink())
        self.assertEqual(
            (self.destination / "CLAUDE.md.bak").read_text(encoding="utf-8"), "existing backup\n"
        )
        self.assertIn("CLAUDE.md.bak already exists", output.getvalue())

    def test_dry_run_with_adopt_claude_fails_if_backup_is_broken_symlink(self):
        (self.destination / "AGENTS.md").write_text("# Existing AGENTS\n", encoding="utf-8")
        (self.destination / "CLAUDE.md").write_text("custom claude guidance\n", encoding="utf-8")
        missing_target = self.destination / "missing-target"
        (self.destination / "CLAUDE.md.bak").symlink_to(missing_target)
        output = io.StringIO()

        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            rc = raven._run(
                self.destination,
                raven.load_config(self.destination),
                "python",
                False,
                True,
                [],
                adopt_claude_requested=True,
                prompt_claude=False,
            )

        self.assertEqual(rc, 2)
        self.assertIn("CLAUDE.md.bak already exists", output.getvalue())
        self.assertTrue((self.destination / "AGENTS.md").is_file())
        self.assertFalse((self.destination / "CLAUDE.md").is_symlink())
        self.assertTrue((self.destination / "CLAUDE.md.bak").is_symlink())

    def test_run_with_adopt_claude_fails_if_backup_is_broken_symlink(self):
        (self.destination / "AGENTS.md").write_text("# Existing AGENTS\n", encoding="utf-8")
        (self.destination / "CLAUDE.md").write_text("custom claude guidance\n", encoding="utf-8")
        missing_target = self.destination / "missing-target"
        (self.destination / "CLAUDE.md.bak").symlink_to(missing_target)
        output = io.StringIO()

        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            rc = raven._run(
                self.destination,
                raven.load_config(self.destination),
                "python",
                False,
                False,
                [],
                adopt_claude_requested=True,
                prompt_claude=False,
            )

        self.assertEqual(rc, 2)
        self.assertIn("CLAUDE.md.bak already exists", output.getvalue())
        self.assertTrue((self.destination / "AGENTS.md").is_file())
        self.assertFalse((self.destination / "CLAUDE.md").is_symlink())
        self.assertTrue((self.destination / "CLAUDE.md.bak").is_symlink())

    def test_dry_run_with_adopt_claude_fails_if_backup_is_valid_symlink(self):
        (self.destination / "AGENTS.md").write_text("# Existing AGENTS\n", encoding="utf-8")
        (self.destination / "CLAUDE.md").write_text("custom claude guidance\n", encoding="utf-8")
        real_target = self.destination / "real-backup-target.md"
        real_target.write_text("real backup contents\n", encoding="utf-8")
        (self.destination / "CLAUDE.md.bak").symlink_to(real_target)
        output = io.StringIO()

        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            rc = raven._run(
                self.destination,
                raven.load_config(self.destination),
                "python",
                False,
                True,
                [],
                adopt_claude_requested=True,
                prompt_claude=False,
            )

        self.assertEqual(rc, 2)
        self.assertIn("CLAUDE.md.bak already exists", output.getvalue())
        self.assertTrue((self.destination / "AGENTS.md").is_file())
        self.assertFalse((self.destination / "CLAUDE.md").is_symlink())
        self.assertTrue((self.destination / "CLAUDE.md.bak").is_symlink())


class ClaudeSymlinkMigrationTests(RavenTestCase):
    """A repo installed before #253 has CLAUDE.md as a real symlink to AGENTS.md.

    Regression coverage for the bug this migration surfaced: `Path.is_file()`
    and `Path.read_text()` both transparently follow a symlink, so without a
    guard in `block_managed_state()`, reading a still-symlinked CLAUDE.md
    during upgrade reads *AGENTS.md's own content* -- which then spuriously
    parses as a managed block and, if "updated" in place, splices AGENTS.md's
    text into CLAUDE.md. These tests build that exact pre-#253 on-disk shape
    and assert upgrade replaces it cleanly instead.
    """

    def _install_then_revert_to_symlink(self):
        """Install normally (new shape), then hand-revert CLAUDE.md to the old symlink shape."""
        with contextlib.redirect_stdout(io.StringIO()):
            rc = raven._run(
                self.destination,
                raven.load_config(self.destination),
                "python",
                False,
                False,
                [],
            )
        self.assertEqual(rc, 0)
        agents_content = (self.destination / "AGENTS.md").read_text(encoding="utf-8")

        (self.destination / "CLAUDE.md").unlink()
        (self.destination / "CLAUDE.md").symlink_to("AGENTS.md")

        manifest = raven.load_manifest(self.destination)
        symlink_sha = hashlib.sha256(b"symlink:AGENTS.md").hexdigest()
        manifest["files"]["CLAUDE.md"] = {
            "kind": "symlink",
            "target": "AGENTS.md",
            "sourceSha256": symlink_sha,
            "installedSha256": symlink_sha,
        }
        raven.save_manifest(self.destination, manifest)
        return agents_content

    def test_upgrade_replaces_symlinked_claude_md_with_plain_import_file(self):
        agents_content = self._install_then_revert_to_symlink()

        with contextlib.redirect_stdout(io.StringIO()):
            rc = raven._run(
                self.destination,
                raven.load_config(self.destination),
                "python",
                False,
                False,
                [],
            )

        self.assertEqual(rc, 0)
        claude = self.destination / "CLAUDE.md"
        self.assertFalse(claude.is_symlink())
        self.assertEqual(claude.read_text(encoding="utf-8").strip(), "@AGENTS.md")
        # The regression this guards against: AGENTS.md's own content must be
        # completely untouched by the CLAUDE.md rewrite.
        self.assertEqual(
            (self.destination / "AGENTS.md").read_text(encoding="utf-8"), agents_content
        )

    def test_a_symlink_reappearing_after_migration_is_re_migrated(self):
        """The manifest already records the plain file; only the tree reverted (#261).

        This is the shape a partial commit plus a later `git reset --hard`
        leaves behind: `raven upgrade` migrates CLAUDE.md and writes the
        manifest, only the manifest gets staged, and the reset restores the
        committed symlink. The baseline then says "plain file" while the tree
        says "symlink", and the template has not changed since -- which used to
        classify as `local_only` and be left alone on every future upgrade.

        A symlink is never a valid local customization of a path the template
        ships as a regular file: it is the pre-#253 shape that breaks on a
        Windows checkout without symlink support, which is the whole reason
        #253 stopped installing one.
        """
        with contextlib.redirect_stdout(io.StringIO()):
            rc = raven._run(
                self.destination,
                raven.load_config(self.destination),
                "python",
                False,
                False,
                [],
            )
        self.assertEqual(rc, 0)
        claude = self.destination / "CLAUDE.md"
        self.assertFalse(claude.is_symlink())

        # Revert only the tree, leaving the manifest on the migrated baseline.
        claude.unlink()
        claude.symlink_to("AGENTS.md")
        record = raven.load_manifest(self.destination)["files"]["CLAUDE.md"]
        self.assertEqual(record["kind"], "file")

        with contextlib.redirect_stdout(io.StringIO()):
            rc = raven._run(
                self.destination,
                raven.load_config(self.destination),
                "python",
                False,
                False,
                [],
            )

        self.assertEqual(rc, 0)
        self.assertFalse(claude.is_symlink(), "upgrade left the reverted symlink in place")
        self.assertEqual(claude.read_text(encoding="utf-8").strip(), "@AGENTS.md")

    def test_dry_run_reports_symlinked_claude_md_as_an_upgrade(self):
        self._install_then_revert_to_symlink()
        output = io.StringIO()

        with contextlib.redirect_stdout(output):
            rc = raven._run(
                self.destination,
                raven.load_config(self.destination),
                "python",
                False,
                True,
                [],
            )

        self.assertEqual(rc, 0)
        self.assertIn("CLAUDE.md", output.getvalue())
        # Nothing written on a dry run: still the old symlink shape.
        self.assertTrue((self.destination / "CLAUDE.md").is_symlink())


if __name__ == "__main__":
    unittest.main()
