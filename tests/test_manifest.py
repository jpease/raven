import argparse
import contextlib
import hashlib
import io
import json
import subprocess
import unittest
from typing import ClassVar
from unittest import mock

from helpers import REPO_ROOT, RavenTestCase, install_ns, raven, upgrade_ns


def _completed(returncode, stdout=""):
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout)


class GitRefTests(unittest.TestCase):
    """#243 -- git_ref must mark a manifest recorded from an uncommitted
    checkout, so fleet and doctor never treat it as the clean commit it
    shares a sha with.
    """

    def test_clean_checkout_returns_bare_sha(self):
        with mock.patch(
            "raven_lib.manifest.subprocess.run",
            side_effect=[_completed(0, "1588b719ad69\n"), _completed(0, "")],
        ):
            self.assertEqual(raven.git_ref(), "1588b719ad69")

    def test_dirty_checkout_appends_dirty_suffix(self):
        with mock.patch(
            "raven_lib.manifest.subprocess.run",
            side_effect=[
                _completed(0, "1588b719ad69\n"),
                _completed(0, " M scripts/raven_lib/manifest.py\n"),
            ],
        ):
            self.assertEqual(raven.git_ref(), "1588b719ad69-dirty")

    def test_outside_a_git_repo_is_unknown_and_skips_status_check(self):
        with mock.patch(
            "raven_lib.manifest.subprocess.run", side_effect=[_completed(128, "")]
        ) as run:
            self.assertEqual(raven.git_ref(), "unknown")
            self.assertEqual(run.call_count, 1)


class ManifestTests(RavenTestCase):
    def test_manifest_allows_upgrade_for_unchanged_managed_file(self):
        path = ".claude/scripts/raven-tool-check.py"
        raven.copy_paths(self.template, self.destination, [path])
        raven.update_manifest(
            self.destination,
            "python",
            self.template,
            self.excludes,
            raven.load_config(self.destination),
            [path],
        )

        # Model a file installed from an older template: its recorded baseline
        # (installed == source) predates the current, newer template file.
        target = self.destination / path
        target.write_text("old template content\n", encoding="utf-8")
        old_hash = raven.file_sha256(target)
        manifest = raven.load_manifest(self.destination)
        manifest["files"][path]["installedSha256"] = old_hash
        manifest["files"][path]["sourceSha256"] = old_hash
        raven.save_manifest(self.destination, manifest)

        classification = raven.classify(self.template, self.destination, self.excludes)

        self.assertIn(path, classification.will_upgrade)
        self.assertNotIn(path, classification.needs_merge)

    def test_local_edit_with_unchanged_template_is_local_only_not_merge(self):
        path = ".claude/scripts/raven-tool-check.py"
        raven.copy_paths(self.template, self.destination, [path])
        raven.update_manifest(
            self.destination,
            "python",
            self.template,
            self.excludes,
            raven.load_config(self.destination),
            [path],
        )

        target = self.destination / path
        target.write_text("local user edit\n", encoding="utf-8")

        classification = raven.classify(self.template, self.destination, self.excludes)

        # The template is unchanged from the recorded baseline, so there is
        # nothing upstream to merge: the local edit is left untouched, not forced
        # into a guided merge.
        self.assertIn(path, classification.local_only)
        self.assertNotIn(path, classification.needs_merge)
        self.assertNotIn(path, classification.will_upgrade)

    def test_final_newline_only_diff_upgrades_instead_of_merging(self):
        path = ".claude/scripts/raven-tool-check.py"
        raven.copy_paths(self.template, self.destination, [path])
        raven.update_manifest(
            self.destination,
            "python",
            self.template,
            self.excludes,
            raven.load_config(self.destination),
            [path],
        )

        # Install differs from the template only by its final newline, and the
        # baseline differs from both (so the 3-way reconcile would otherwise say
        # needs_merge -- a genuine both-changed conflict).
        target = self.destination / path
        template_text = (self.template / path).read_text(encoding="utf-8")
        self.assertTrue(template_text.endswith("\n"))
        target.write_text(template_text.rstrip("\n"), encoding="utf-8")
        manifest = raven.load_manifest(self.destination)
        manifest["files"][path]["installedSha256"] = "0" * 64
        manifest["files"][path]["sourceSha256"] = "0" * 64
        raven.save_manifest(self.destination, manifest)

        classification = raven.classify(self.template, self.destination, self.excludes)

        # A newline-only difference is cosmetic: take the template, no guided merge.
        self.assertIn(path, classification.will_upgrade)
        self.assertNotIn(path, classification.needs_merge)

    def test_update_manifest_records_file_hashes(self):
        path = ".claude/scripts/raven-tool-check.py"
        raven.copy_paths(self.template, self.destination, [path])
        raven.update_manifest(
            self.destination,
            "python",
            self.template,
            self.excludes,
            raven.load_config(self.destination),
            [path],
        )

        manifest_path = self.destination / ".raven" / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        self.assertEqual(manifest["schema"], 1)
        self.assertEqual(manifest["template"], "python")
        self.assertEqual(manifest["files"][path]["kind"], "file")
        self.assertEqual(
            manifest["files"][path]["installedSha256"],
            raven.file_sha256(self.destination / path),
        )

    def test_parse_record_parses_valid_and_rejects_malformed(self):
        record = raven.parse_record(
            {"kind": "symlink", "installedSha256": "abc", "target": "AGENTS.md", "extra": 1}
        )
        assert record is not None  # narrow Optional for the type checker
        self.assertEqual(record.kind, "symlink")
        self.assertEqual(record.installed_sha256, "abc")
        self.assertEqual(record.target, "AGENTS.md")

        self.assertIsNone(raven.parse_record("not a dict"))
        self.assertIsNone(raven.parse_record({"kind": "file"}))  # missing installedSha256
        self.assertIsNone(raven.parse_record({"installedSha256": "abc"}))  # missing kind
        # Files have no target.
        file_record = raven.parse_record({"kind": "file", "installedSha256": "abc"})
        assert file_record is not None  # narrow Optional for the type checker
        self.assertIsNone(file_record.target)

    def test_load_manifest_warns_and_defaults_on_invalid_json(self):
        manifest_path = self.destination / ".raven" / "manifest.json"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text("{not valid json", encoding="utf-8")
        err = io.StringIO()

        with contextlib.redirect_stderr(err):
            manifest = raven.load_manifest(self.destination)

        self.assertEqual(manifest, {"schema": 1, "files": {}})
        self.assertIn("warning", err.getvalue())

    def test_update_manifest_can_adopt_identical_existing_file(self):
        path = ".claude/scripts/raven-tool-check.py"
        raven.copy_paths(self.template, self.destination, [path])

        classification = raven.classify(self.template, self.destination, self.excludes)
        raven.update_manifest(
            self.destination,
            "python",
            self.template,
            self.excludes,
            raven.load_config(self.destination),
            classification.identical,
        )

        manifest = raven.load_manifest(self.destination)

        self.assertIn(path, manifest["files"])
        self.assertEqual(
            manifest["files"][path]["installedSha256"],
            raven.file_sha256(self.destination / path),
        )


class ManifestGateToolsTests(RavenTestCase):
    def test_apply_records_resolved_gate_tools(self):
        raven.cli.cmd_install(install_ns(self.destination, "python"))
        manifest = json.loads((self.destination / ".raven" / "manifest.json").read_text("utf-8"))
        self.assertEqual(manifest["gateTools"], ["ruff", "pyright"])

    def test_recorded_tools_match_the_gate_spec(self):
        # Derived from GATE_DATA, never hand-listed, so a gate change here
        # cannot silently diverge from what the roster reports.
        raven.cli.cmd_install(install_ns(self.destination, "python"))
        manifest = json.loads((self.destination / ".raven" / "manifest.json").read_text("utf-8"))
        spec = raven.gates.gate_spec_for("python")
        assert spec is not None
        self.assertEqual(manifest["gateTools"], list(spec.tools))

    def test_upgrade_records_gate_tools_for_a_manifest_that_lacks_them(self):
        raven.cli.cmd_install(install_ns(self.destination, "python"))
        path = self.destination / ".raven" / "manifest.json"
        manifest = json.loads(path.read_text("utf-8"))
        del manifest["gateTools"]
        path.write_text(json.dumps(manifest), encoding="utf-8")
        raven.cli.cmd_upgrade(upgrade_ns(self.destination))
        refreshed = json.loads(path.read_text("utf-8"))
        self.assertEqual(refreshed["gateTools"], ["ruff", "pyright"])


class ManifestBlockPreservationTests(RavenTestCase):
    """Issue #139: an automatic upgrade must not silently absorb outside-block
    drift into the manifest baseline for a managed-block file that classifies
    "identical" only because its RAVEN block matches the template -- Raven
    never touched the outside-block content on that path. Explicit
    ``raven accept`` must keep recording the full on-disk state exactly as
    before; only the automatic upgrade/apply path changes.
    """

    def _install(self):
        config_path = self.destination / ".raven" / "config.toml"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(raven.default_config_text("python", False, "none"), encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()):
            raven._run(
                self.destination, raven.load_config(self.destination), "python", False, False, []
            )

    def _accept_agents_md(self):
        with contextlib.redirect_stdout(io.StringIO()):
            rc = raven.cmd_accept(
                argparse.Namespace(
                    destination=str(self.destination),
                    paths=["AGENTS.md"],
                    dry_run=False,
                    include_readme=False,
                )
            )
        self.assertEqual(rc, 0)

    def _manifest_files(self):
        return json.loads(
            (self.destination / ".raven" / "manifest.json").read_text(encoding="utf-8")
        )["files"]

    def _install_and_accept_agents_md_with_managed_block(self):
        """AGENTS.md with local preamble plus an accepted, template-matching block.

        Mirrors #63's guided-merge flow (see test_accept.py): a pre-existing
        AGENTS.md gets a RAVEN block appended via patch rather than overwritten,
        then explicitly accepted to record the initial baseline.
        """
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
        self._accept_agents_md()

    def test_upgrade_preserves_installed_sha_for_identical_managed_block(self):
        self._install_and_accept_agents_md_with_managed_block()

        baseline_sha = self._manifest_files()["AGENTS.md"]["installedSha256"]
        agents_md = self.destination / "AGENTS.md"
        self.assertEqual(baseline_sha, raven.file_sha256(agents_md))

        # Edit only outside the RAVEN block; the block itself stays byte-identical
        # to the template, so this file classifies "identical" via block_state,
        # not whole-file content_matches.
        with agents_md.open("a", encoding="utf-8") as f:
            f.write("\nAn outside-block edit made after acceptance.\n")

        classification = raven.classify(self.template, self.destination, self.excludes)
        self.assertIn("AGENTS.md", classification.identical)

        with contextlib.redirect_stdout(io.StringIO()):
            rc = raven.cmd_upgrade(upgrade_ns(self.destination))
        self.assertEqual(rc, 0)

        after_upgrade_sha = self._manifest_files()["AGENTS.md"]["installedSha256"]
        # The automatic upgrade path writes nothing outside the block, so it must
        # not silently absorb the outside-block edit into the recorded baseline.
        self.assertEqual(after_upgrade_sha, baseline_sha)
        self.assertNotEqual(after_upgrade_sha, raven.file_sha256(agents_md))

    def test_accept_still_records_full_state_after_outside_block_edit(self):
        self._install_and_accept_agents_md_with_managed_block()

        agents_md = self.destination / "AGENTS.md"
        with agents_md.open("a", encoding="utf-8") as f:
            f.write("\nAn outside-block edit made after acceptance.\n")

        classification = raven.classify(self.template, self.destination, self.excludes)
        self.assertIn("AGENTS.md", classification.identical)

        self._accept_agents_md()

        after_accept_sha = self._manifest_files()["AGENTS.md"]["installedSha256"]
        # Explicit `raven accept` keeps blessing the full current on-disk
        # content -- its own call site is unchanged by the upgrade-path fix.
        self.assertEqual(after_accept_sha, raven.file_sha256(agents_md))


if __name__ == "__main__":
    unittest.main()


class RepoBaselineDriftTests(unittest.TestCase):
    """Assert every installed file still hashes to the baseline the manifest records (#232).

    `raven upgrade` only compares a destination file whose *template* side also
    changed, so a file edited in place stays invisible until someone touches
    its source under `common/`. Upgrade then reads the destination as
    user-customized, writes a guided merge, and fails an unrelated commit with
    `UNCONVERGED`.

    Three commits did exactly that. b2d014c196b1 (docs(doc-sync): tell authors
    not to restate config-owned values, 2026-08-20) and e76c2e562e01
    (docs(agent-compat): note config.toml pins are deliberate, not overhead,
    2026-08-20) each added real guidance to an installed copy and never to the
    template, so every downstream project was missing it. 5bce264b1b54
    (Formatting, 2026-06-19) repadded a Markdown table in a third, which
    surfaced two months later on a commit that had nothing to do with it.

    Checking the whole manifest at once fails in the commit that breaks it,
    which is the only commit whose author knows what the edit was for.
    """

    #: The three paths that legitimately diverge, each for a stated reason.
    #: Two mirror `self-check.py`'s `_APPROVED_CUSTOMIZATION`; `AGENTS.md` is
    #: managed only between its RAVEN:BEGIN/RAVEN:END markers, so the
    #: project-specific instructions above the block are drift by design.
    ALLOWED: ClassVar[dict[str, str]] = {
        "AGENTS.md": "managed only inside the RAVEN block; project instructions sit above it",
        "justfile": "carries repo-only recipes (`hygiene`, `relaxation`) no template ships",
        "pyproject.toml": "this repo's own project config, richer than the starter template",
    }

    def test_every_installed_file_matches_its_recorded_baseline(self):
        manifest = json.loads((REPO_ROOT / ".raven" / "manifest.json").read_text(encoding="utf-8"))
        drifted: list[str] = []

        def walk(node: object) -> None:
            if not isinstance(node, dict):
                return
            for key, value in node.items():
                if not isinstance(value, dict):
                    continue
                recorded = value.get("installedSha256")
                if not isinstance(recorded, str):
                    walk(value)
                    continue
                path = REPO_ROOT / key
                # A symlink's target is tracked at its own canonical path, and
                # a path the manifest lists but that is absent is a different
                # failure (`raven doctor` reports it as missing, not drifted).
                if not path.is_file() or path.is_symlink():
                    continue
                actual = hashlib.sha256(path.read_bytes()).hexdigest()
                if actual != recorded and key not in self.ALLOWED:
                    drifted.append(key)

        walk(manifest)
        self.assertEqual(
            sorted(drifted),
            [],
            "installed file(s) no longer match .raven/manifest.json. Reconcile before "
            "committing: promote the destination's content into common/ if the edit "
            "belongs in the template, or restore the destination if it does not, then "
            "run scripts/self-check.py and `raven accept`.",
        )
