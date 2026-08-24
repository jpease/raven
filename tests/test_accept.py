import argparse
import contextlib
import io
import json
import subprocess
from pathlib import Path

from helpers import RavenTestCase, raven
from raven_lib.cli import classify_accept_requests
from raven_lib.doctor import build_doctor_findings


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
            raven._run(
                self.destination, raven.load_config(self.destination), "python", False, False, []
            )

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

    def test_accept_clears_stale_merge_artifacts_no_longer_managed(self):
        # Reproduces #74: a file with pending merge artifacts that later
        # leaves the template set (component disabled / config excluded)
        # could never be cleared -- `accept` unconditionally skipped it and
        # `doctor` warned forever.
        self._install()
        mcp = self.destination / ".mcp.json"
        mcp.write_text('{"local": "kept"}\n', encoding="utf-8")
        entries = raven.entries_for_destination(
            self.template, self.excludes, raven.load_config(self.destination), self.destination
        )
        raven.write_guided_merge_artifacts(self.destination, entries, [".mcp.json"])
        self.assertIn(".mcp.json", raven.pending_merge_paths(self.destination))
        installed_sha_before = self._manifest()["files"][".mcp.json"]["installedSha256"]

        config_path = self.destination / ".raven" / "config.toml"
        config_text = config_path.read_text(encoding="utf-8")
        config_path.write_text(
            config_text + '\n[exclude]\npaths = [".mcp.json"]\n', encoding="utf-8"
        )

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            rc = raven.cmd_accept(self._ns())

        self.assertEqual(rc, 0)
        self.assertIn(".mcp.json", output.getvalue())
        self.assertNotIn(".mcp.json", raven.pending_merge_paths(self.destination))
        self.assertFalse((self.destination / ".raven" / "merge").exists())
        # Artifacts are cleared, but the stale path is never recorded as an
        # accepted baseline -- it's no longer Raven-managed.
        self.assertEqual(
            self._manifest()["files"][".mcp.json"]["installedSha256"], installed_sha_before
        )

    def test_accept_nothing_pending_is_noop(self):
        self._install()
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            rc = raven.cmd_accept(self._ns())

        self.assertEqual(rc, 0)
        self.assertIn("Nothing to accept", output.getvalue())


class AcceptGatedPathTests(RavenTestCase):
    """#179: `raven accept` must work on config-gated (deactivated) paths.

    Before this fix, `cmd_accept` looked every requested path up against
    `entries_for_destination(..., config, ...)` built with the *real*
    config, which excludes gated paths by definition -- so accepting a
    deactivated-but-still-shipped skill was always refused with "not a
    Raven-managed template file", even though the file is still on disk and
    still shipped by the template.
    """

    def _install(self, platform):
        config_path = self.destination / ".raven" / "config.toml"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(
            raven.default_config_text("python", False, platform), encoding="utf-8"
        )
        with contextlib.redirect_stdout(io.StringIO()):
            raven._run(
                self.destination, raven.load_config(self.destination), "python", False, False, []
            )

    def _switch_platform(self, platform):
        from raven_lib.config import _update_config_platform
        from raven_lib.constants import CONFIG_PATH

        _update_config_platform(self.destination / CONFIG_PATH, platform)

    def _manifest(self):
        return json.loads(
            (self.destination / ".raven" / "manifest.json").read_text(encoding="utf-8")
        )

    def _sha(self, path):
        fingerprint = raven.destination_fingerprint(path)
        assert fingerprint is not None
        return fingerprint.sha256

    def test_accept_on_gated_path_records_baseline_instead_of_being_skipped(self):
        self._install("github")
        rel = ".agents/skills/raven-github-issues/SKILL.md"
        self._switch_platform("gitlab")

        with contextlib.redirect_stdout(io.StringIO()) as buf:
            rc = raven.cmd_accept(
                argparse.Namespace(
                    destination=str(self.destination),
                    paths=[rel],
                    dry_run=False,
                    include_readme=False,
                )
            )
        output = buf.getvalue()
        self.assertEqual(rc, 0)
        self.assertNotIn("not a Raven-managed template file", output)
        self.assertIn(rel, output)

        manifest = self._manifest()
        self.assertIn(rel, manifest["files"])
        record = manifest["files"][rel]
        self.assertEqual(record["installedSha256"], self._sha(self.destination / rel))
        self.assertEqual(record["installedSha256"], record["sourceSha256"])

    def test_accept_still_refuses_genuinely_unmanaged_path(self):
        # Regression guard: the merge is narrowly scoped to gated-but-shipped
        # paths only, never to project-owned / non-Raven files.
        self._install("github")
        unmanaged = self.destination / "docs" / "not-ravens.md"
        unmanaged.parent.mkdir(parents=True, exist_ok=True)
        unmanaged.write_text("project-owned\n", encoding="utf-8")

        with contextlib.redirect_stdout(io.StringIO()) as buf:
            rc = raven.cmd_accept(
                argparse.Namespace(
                    destination=str(self.destination),
                    paths=["docs/not-ravens.md"],
                    dry_run=False,
                    include_readme=False,
                )
            )
        output = buf.getvalue()
        self.assertEqual(rc, 0)
        self.assertIn("not a Raven-managed template file", output)
        self.assertNotIn("docs/not-ravens.md", self._manifest()["files"])


class ClassifyAcceptRequestsTests(RavenTestCase):
    """`cmd_accept`'s per-path decision, exercised without capturing stdout."""

    def _entries(self, *relatives):
        return {rel: raven.TemplateEntry(rel, Path("/nonexistent") / rel) for rel in relatives}

    def test_buckets_managed_stale_and_unknown_paths(self):
        (self.destination / "AGENTS.md").write_text("here\n", encoding="utf-8")
        entries = self._entries("AGENTS.md", ".mcp.json")

        result = classify_accept_requests(
            ["AGENTS.md", ".mcp.json", "dropped.md", "random.txt"],
            entries,
            {"dropped.md"},
            self.destination,
        )

        self.assertEqual(result.accepted, ["AGENTS.md"])
        self.assertEqual(result.stale, ["dropped.md"])
        self.assertEqual(
            result.skipped,
            [
                ".mcp.json (no such file in destination)",
                "random.txt (not a Raven-managed template file)",
            ],
        )

    def test_no_requests_yields_empty_buckets(self):
        result = classify_accept_requests([], self._entries("AGENTS.md"), set(), self.destination)

        self.assertEqual(result.accepted, [])
        self.assertEqual(result.stale, [])
        self.assertEqual(result.skipped, [])

    def test_a_broken_symlink_still_counts_as_present(self):
        # `_any_exists` is lstat-based, so an unmanaged-but-linked file is
        # accepted rather than reported as missing -- matching what `cmd_accept`
        # has always done.
        (self.destination / "AGENTS.md").symlink_to("nowhere")

        result = classify_accept_requests(
            ["AGENTS.md"], self._entries("AGENTS.md"), set(), self.destination
        )

        self.assertEqual(result.accepted, ["AGENTS.md"])


class AcceptStarterToolConfigTests(RavenTestCase):
    """A starter tool config a project has edited must be acceptable.

    `entries_for_destination` drops a starter config the moment the destination
    has one, so install and upgrade never re-copy over a project's own config.
    Reusing that map in `accept` meant `doctor` could report an edited
    `pyproject.toml` as drift and name a fix -- `raven accept` -- that then
    refused the file as "not a Raven-managed template file". Recording a
    deliberately diverged file as the baseline is exactly what accept is for.
    """

    def _ns(self, paths=None, dry_run=False):
        return argparse.Namespace(
            destination=str(self.destination),
            paths=paths or [],
            dry_run=dry_run,
            include_readme=False,
        )

    def _install(self):
        config_path = self.destination / ".raven" / "config.toml"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(raven.default_config_text("python", False, "none"), encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()):
            raven._run(
                self.destination, raven.load_config(self.destination), "python", False, False, []
            )

    def _accept(self, paths):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            rc = raven.cmd_accept(self._ns(paths=paths))
        return rc, buffer.getvalue()

    def _manifest_entry(self, relative):
        manifest = json.loads(
            (self.destination / ".raven" / "manifest.json").read_text(encoding="utf-8")
        )
        return manifest["files"].get(relative)

    def test_an_edited_starter_config_can_be_accepted(self):
        self._install()
        pyproject = self.destination / "pyproject.toml"
        pyproject.write_text("[tool.ruff]\nline-length = 120\n", encoding="utf-8")

        rc, output = self._accept(["pyproject.toml"])

        self.assertEqual(rc, 0)
        self.assertNotIn("not a Raven-managed template file", output)
        entry = self._manifest_entry("pyproject.toml")
        self.assertIsNotNone(entry)
        assert entry is not None
        fingerprint = raven.destination_fingerprint(pyproject)
        assert fingerprint is not None
        self.assertEqual(entry["installedSha256"], fingerprint.sha256)

    def test_accepting_clears_the_drift_doctor_reported(self):
        """The end-to-end shape of the bug: doctor warns, its named fix works.

        Editing the file alone is only `local_only` -- informational, because
        nothing upstream moved. The WARN doctor emits, and whose fix line says
        `raven accept`, needs the template to have moved on as well, which is
        what the rewritten `sourceSha256` below stands in for.
        """
        self._install()
        pyproject = self.destination / "pyproject.toml"
        pyproject.write_text("[tool.ruff]\nline-length = 120\n", encoding="utf-8")
        manifest_path = self.destination / ".raven" / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["files"]["pyproject.toml"]["sourceSha256"] = "0" * 64
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        def modified():
            findings = build_doctor_findings(self.destination)
            return [
                f
                for f in findings
                if f.id == "doctor.drift.modified" and "pyproject.toml" in (f.detail or "")
            ]

        self.assertTrue(modified(), "expected doctor to report the edited starter config first")
        rc, output = self._accept(["pyproject.toml"])
        self.assertEqual(rc, 0)
        self.assertNotIn("not a Raven-managed template file", output)
        self.assertFalse(modified(), "accept did not clear the drift doctor named it for")

    def test_a_starter_config_the_destination_lacks_is_still_skipped(self):
        # Nothing on disk to record: the "no such file" path, not a silent pass.
        self._install()
        (self.destination / "pyproject.toml").unlink()
        rc, output = self._accept(["pyproject.toml"])
        self.assertEqual(rc, 0)
        self.assertIn("no such file in destination", output)

    def test_a_genuinely_unmanaged_path_is_still_refused(self):
        # The widening covers starter tool configs only; an arbitrary file the
        # template never ships must still be rejected.
        self._install()
        (self.destination / "not-ravens.txt").write_text("local\n", encoding="utf-8")
        rc, output = self._accept(["not-ravens.txt"])
        self.assertEqual(rc, 0)
        self.assertIn("not a Raven-managed template file", output)
