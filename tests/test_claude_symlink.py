import contextlib
import io
import os
import unittest

from helpers import RavenTestCase, raven


class ClaudeSymlinkTests(RavenTestCase):
    def test_adopt_claude_symlink_backs_up_existing_file_and_creates_symlink(self):
        (self.destination / "CLAUDE.md").write_text("custom claude guidance\n", encoding="utf-8")
        entries = raven.entries_for_destination(
            self.template,
            self.excludes,
            raven.load_config(self.destination),
            self.destination,
        )

        changed = raven.adopt_claude_symlink(self.destination, entries)

        self.assertEqual(changed, ["CLAUDE.md.bak", "CLAUDE.md"])
        self.assertEqual(
            (self.destination / "CLAUDE.md.bak").read_text(encoding="utf-8"),
            "custom claude guidance\n",
        )
        self.assertTrue((self.destination / "CLAUDE.md").is_symlink())
        self.assertEqual(os.readlink(self.destination / "CLAUDE.md"), "AGENTS.md")

    def test_adopt_claude_symlink_refuses_to_overwrite_existing_backup(self):
        (self.destination / "CLAUDE.md").write_text("custom claude guidance\n", encoding="utf-8")
        (self.destination / "CLAUDE.md.bak").write_text("existing backup\n", encoding="utf-8")
        entries = raven.entries_for_destination(
            self.template,
            self.excludes,
            raven.load_config(self.destination),
            self.destination,
        )

        with self.assertRaises(FileExistsError):
            raven.adopt_claude_symlink(self.destination, entries)

        self.assertEqual(
            (self.destination / "CLAUDE.md").read_text(encoding="utf-8"), "custom claude guidance\n"
        )
        self.assertEqual(
            (self.destination / "CLAUDE.md.bak").read_text(encoding="utf-8"), "existing backup\n"
        )

    def test_run_with_adopt_claude_symlink_does_not_report_claude_manual_merge(self):
        (self.destination / "AGENTS.md").write_text("# Existing AGENTS\n", encoding="utf-8")
        (self.destination / "CLAUDE.md").write_text("custom claude guidance\n", encoding="utf-8")
        output = io.StringIO()

        with contextlib.redirect_stdout(output):
            rc = raven._run(
                self.destination,
                "python",
                False,
                False,
                [],
                adopt_claude_symlink_requested=True,
                prompt_claude_symlink=False,
            )

        self.assertEqual(rc, 0)
        self.assertTrue((self.destination / "CLAUDE.md").is_symlink())
        self.assertEqual(
            (self.destination / "CLAUDE.md.bak").read_text(encoding="utf-8"),
            "custom claude guidance\n",
        )
        self.assertIn("Adopted CLAUDE.md compatibility symlink", output.getvalue())
        self.assertNotIn(
            "  CLAUDE.md\n", output.getvalue().split("Wrote guided merge artifacts", 1)[-1]
        )

    def test_run_with_adopt_claude_symlink_fails_if_backup_exists(self):
        (self.destination / "AGENTS.md").write_text("# Existing AGENTS\n", encoding="utf-8")
        (self.destination / "CLAUDE.md").write_text("custom claude guidance\n", encoding="utf-8")
        (self.destination / "CLAUDE.md.bak").write_text("existing backup\n", encoding="utf-8")
        output = io.StringIO()

        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            rc = raven._run(
                self.destination,
                "python",
                False,
                False,
                [],
                adopt_claude_symlink_requested=True,
                prompt_claude_symlink=False,
            )

        self.assertEqual(rc, 2)
        self.assertFalse((self.destination / "CLAUDE.md").is_symlink())
        self.assertEqual(
            (self.destination / "CLAUDE.md.bak").read_text(encoding="utf-8"), "existing backup\n"
        )
        self.assertIn("CLAUDE.md.bak already exists", output.getvalue())

    def test_dry_run_with_adopt_claude_symlink_reports_backup_without_writing(self):
        (self.destination / "AGENTS.md").write_text("# Existing AGENTS\n", encoding="utf-8")
        (self.destination / "CLAUDE.md").write_text("custom claude guidance\n", encoding="utf-8")
        output = io.StringIO()

        with contextlib.redirect_stdout(output):
            rc = raven._run(
                self.destination,
                "python",
                False,
                True,
                [],
                adopt_claude_symlink_requested=True,
                prompt_claude_symlink=False,
            )

        self.assertEqual(rc, 0)
        self.assertFalse((self.destination / "CLAUDE.md").is_symlink())
        self.assertFalse((self.destination / "CLAUDE.md.bak").exists())
        self.assertIn("Would adopt CLAUDE.md compatibility symlink", output.getvalue())

    def test_dry_run_with_adopt_claude_symlink_fails_if_backup_exists(self):
        (self.destination / "AGENTS.md").write_text("# Existing AGENTS\n", encoding="utf-8")
        (self.destination / "CLAUDE.md").write_text("custom claude guidance\n", encoding="utf-8")
        (self.destination / "CLAUDE.md.bak").write_text("existing backup\n", encoding="utf-8")
        output = io.StringIO()

        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            rc = raven._run(
                self.destination,
                "python",
                False,
                True,
                [],
                adopt_claude_symlink_requested=True,
                prompt_claude_symlink=False,
            )

        self.assertEqual(rc, 2)
        self.assertFalse((self.destination / "CLAUDE.md").is_symlink())
        self.assertEqual(
            (self.destination / "CLAUDE.md.bak").read_text(encoding="utf-8"), "existing backup\n"
        )
        self.assertIn("CLAUDE.md.bak already exists", output.getvalue())

    def test_dry_run_with_adopt_claude_symlink_fails_if_backup_is_broken_symlink(self):
        (self.destination / "AGENTS.md").write_text("# Existing AGENTS\n", encoding="utf-8")
        (self.destination / "CLAUDE.md").write_text("custom claude guidance\n", encoding="utf-8")
        missing_target = self.destination / "missing-target"
        (self.destination / "CLAUDE.md.bak").symlink_to(missing_target)
        output = io.StringIO()

        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            rc = raven._run(
                self.destination,
                "python",
                False,
                True,
                [],
                adopt_claude_symlink_requested=True,
                prompt_claude_symlink=False,
            )

        self.assertEqual(rc, 2)
        self.assertIn("CLAUDE.md.bak already exists", output.getvalue())
        self.assertTrue((self.destination / "AGENTS.md").is_file())
        self.assertFalse((self.destination / "CLAUDE.md").is_symlink())
        self.assertTrue((self.destination / "CLAUDE.md.bak").is_symlink())
        self.assertEqual(os.readlink(self.destination / "CLAUDE.md.bak"), str(missing_target))

    def test_run_with_adopt_claude_symlink_fails_if_backup_is_broken_symlink(self):
        (self.destination / "AGENTS.md").write_text("# Existing AGENTS\n", encoding="utf-8")
        (self.destination / "CLAUDE.md").write_text("custom claude guidance\n", encoding="utf-8")
        missing_target = self.destination / "missing-target"
        (self.destination / "CLAUDE.md.bak").symlink_to(missing_target)
        output = io.StringIO()

        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            rc = raven._run(
                self.destination,
                "python",
                False,
                False,
                [],
                adopt_claude_symlink_requested=True,
                prompt_claude_symlink=False,
            )

        self.assertEqual(rc, 2)
        self.assertIn("CLAUDE.md.bak already exists", output.getvalue())
        self.assertTrue((self.destination / "AGENTS.md").is_file())
        self.assertFalse((self.destination / "CLAUDE.md").is_symlink())
        self.assertTrue((self.destination / "CLAUDE.md.bak").is_symlink())
        self.assertEqual(os.readlink(self.destination / "CLAUDE.md.bak"), str(missing_target))

    def test_dry_run_with_adopt_claude_symlink_fails_if_backup_is_valid_symlink(self):
        (self.destination / "AGENTS.md").write_text("# Existing AGENTS\n", encoding="utf-8")
        (self.destination / "CLAUDE.md").write_text("custom claude guidance\n", encoding="utf-8")
        real_target = self.destination / "real-backup-target.md"
        real_target.write_text("real backup contents\n", encoding="utf-8")
        (self.destination / "CLAUDE.md.bak").symlink_to(real_target)
        output = io.StringIO()

        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            rc = raven._run(
                self.destination,
                "python",
                False,
                True,
                [],
                adopt_claude_symlink_requested=True,
                prompt_claude_symlink=False,
            )

        self.assertEqual(rc, 2)
        self.assertIn("CLAUDE.md.bak already exists", output.getvalue())
        self.assertTrue((self.destination / "AGENTS.md").is_file())
        self.assertFalse((self.destination / "CLAUDE.md").is_symlink())
        self.assertTrue((self.destination / "CLAUDE.md.bak").is_symlink())
        self.assertEqual(os.readlink(self.destination / "CLAUDE.md.bak"), str(real_target))


if __name__ == "__main__":
    unittest.main()
