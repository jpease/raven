import argparse
import contextlib
import io
import json
import subprocess

from helpers import RavenTestCase, raven


class AcceptCommandTests(RavenTestCase):
    def _ns(self, paths=None, dry_run=False):
        return argparse.Namespace(
            destination=str(self.destination),
            paths=paths or [],
            dry_run=dry_run,
            include_readme=False,
        )

    def _manifest(self):
        return json.loads(
            (self.destination / ".raven" / "manifest.json").read_text(encoding="utf-8")
        )

    def _sha(self, path):
        fingerprint = raven.destination_fingerprint(path)
        assert fingerprint is not None
        return fingerprint.sha256

    def _install(self):
        config_path = self.destination / ".raven" / "config.toml"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(raven.default_config_text("python", False, "none"), encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()):
            raven._run(self.destination, "python", False, False, [])

    def test_accept_records_current_file_as_baseline(self):
        self._install()
        mcp = self.destination / ".mcp.json"
        mcp.write_text('{"local": "kept"}\n', encoding="utf-8")

        with contextlib.redirect_stdout(io.StringIO()):
            rc = raven.cmd_accept(self._ns(paths=[".mcp.json"]))

        self.assertEqual(rc, 0)
        rec = self._manifest()["files"][".mcp.json"]
        self.assertEqual(rec["installedSha256"], self._sha(mcp))
        self.assertEqual(rec["sourceSha256"], self._sha(self.template / ".mcp.json"))

    def test_accept_stops_reprompt_after_template_drift(self):
        self._install()
        mcp = self.destination / ".mcp.json"
        mcp.write_text('{"local": "kept"}\n', encoding="utf-8")
        # Simulate Raven's template having changed since the last reconcile.
        mpath = self.destination / ".raven" / "manifest.json"
        manifest = json.loads(mpath.read_text(encoding="utf-8"))
        manifest["files"][".mcp.json"]["sourceSha256"] = "0" * 64
        mpath.write_text(json.dumps(manifest), encoding="utf-8")

        before = raven.classify(self.template, self.destination, self.excludes)
        self.assertIn(".mcp.json", before.needs_merge)

        # Surface the merge artifacts, then accept (no args -> all pending).
        entries = raven.entries_for_destination(
            self.template, self.excludes, raven.load_config(self.destination), self.destination
        )
        raven.write_guided_merge_artifacts(self.destination, entries, [".mcp.json"])
        with contextlib.redirect_stdout(io.StringIO()):
            rc = raven.cmd_accept(self._ns())
        self.assertEqual(rc, 0)

        after = raven.classify(self.template, self.destination, self.excludes)
        self.assertIn(".mcp.json", after.identical)
        self.assertNotIn(".mcp.json", after.needs_merge)
        self.assertFalse((self.destination / ".raven" / "merge").exists())

    def test_accept_stops_reprompt_for_modified_managed_block(self):
        # Reproduces #63: a pre-existing AGENTS.md that predates Raven gets a
        # guided-merge patch instead of being overwritten. Applying that patch
        # inserts a RAVEN managed block; editing inside it and accepting must
        # stop future upgrades from re-prompting.
        (self.destination / "AGENTS.md").write_text(
            "# Local preamble\n\nSome existing local guidance.\n", encoding="utf-8"
        )
        self._install()

        patch_file = self.destination / ".raven" / "merge" / "AGENTS.md.patch"
        result = subprocess.run(
            ["patch", "-p1", "-i", str(patch_file)],
            cwd=self.destination,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

        text = (self.destination / "AGENTS.md").read_text(encoding="utf-8")
        block = raven.find_raven_block(text)
        assert block is not None
        lines = text.splitlines()
        edited_content_lines = block.content.splitlines()
        edited_content_lines[0] = edited_content_lines[0] + " (locally edited)"
        new_lines = lines[: block.start + 1] + edited_content_lines + lines[block.end :]
        (self.destination / "AGENTS.md").write_text(
            "\n".join(new_lines) + ("\n" if text.endswith("\n") else ""), encoding="utf-8"
        )

        before = raven.classify(self.template, self.destination, self.excludes)
        self.assertIn("AGENTS.md", before.needs_merge)

        entries = raven.entries_for_destination(
            self.template, self.excludes, raven.load_config(self.destination), self.destination
        )
        raven.write_guided_merge_artifacts(self.destination, entries, ["AGENTS.md"])
        with contextlib.redirect_stdout(io.StringIO()):
            rc = raven.cmd_accept(self._ns())
        self.assertEqual(rc, 0)
        self.assertFalse((self.destination / ".raven" / "merge").exists())

        after = raven.classify(self.template, self.destination, self.excludes)
        self.assertNotIn("AGENTS.md", after.needs_merge)
        self.assertIn("AGENTS.md", after.identical)

        # A second upgrade cycle must not resurrect the merge prompt (#63).
        again = raven.classify(self.template, self.destination, self.excludes)
        self.assertNotIn("AGENTS.md", again.needs_merge)
        self.assertFalse((self.destination / ".raven" / "merge").exists())

    def test_accept_no_args_removes_all_pending_artifacts(self):
        self._install()
        (self.destination / ".mcp.json").write_text('{"a": 1}\n', encoding="utf-8")
        (self.destination / ".codex" / "config.toml").write_text("a = 1\n", encoding="utf-8")
        entries = raven.entries_for_destination(
            self.template, self.excludes, raven.load_config(self.destination), self.destination
        )
        raven.write_guided_merge_artifacts(
            self.destination, entries, [".mcp.json", ".codex/config.toml"]
        )

        with contextlib.redirect_stdout(io.StringIO()):
            rc = raven.cmd_accept(self._ns())

        self.assertEqual(rc, 0)
        self.assertFalse((self.destination / ".raven" / "merge").exists())
        files = self._manifest()["files"]
        self.assertEqual(
            files[".mcp.json"]["installedSha256"], self._sha(self.destination / ".mcp.json")
        )
        self.assertEqual(
            files[".codex/config.toml"]["installedSha256"],
            self._sha(self.destination / ".codex" / "config.toml"),
        )

    def test_accept_dry_run_changes_nothing(self):
        self._install()
        mcp = self.destination / ".mcp.json"
        mcp.write_text('{"local": "kept"}\n', encoding="utf-8")
        before = self._manifest()["files"][".mcp.json"]["installedSha256"]

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            rc = raven.cmd_accept(self._ns(paths=[".mcp.json"], dry_run=True))

        self.assertEqual(rc, 0)
        self.assertIn(".mcp.json", output.getvalue())
        self.assertEqual(self._manifest()["files"][".mcp.json"]["installedSha256"], before)

    def test_accept_skips_unknown_path(self):
        self._install()
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            rc = raven.cmd_accept(self._ns(paths=["does/not/exist.txt"]))

        self.assertEqual(rc, 0)
        self.assertIn("does/not/exist.txt", output.getvalue())
        self.assertNotIn("does/not/exist.txt", self._manifest()["files"])

    def test_accept_nothing_pending_is_noop(self):
        self._install()
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            rc = raven.cmd_accept(self._ns())

        self.assertEqual(rc, 0)
        self.assertIn("Nothing to accept", output.getvalue())
