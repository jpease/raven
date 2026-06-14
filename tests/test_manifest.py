import contextlib
import io
import json
import unittest

from helpers import RavenTestCase, raven


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

        target = self.destination / path
        target.write_text("old template content\n", encoding="utf-8")
        manifest = raven.load_manifest(self.destination)
        manifest["files"][path]["installedSha256"] = raven.file_sha256(target)
        raven.save_manifest(self.destination, manifest)

        classification = raven.classify(self.template, self.destination, self.excludes)

        self.assertIn(path, classification.will_upgrade)
        self.assertNotIn(path, classification.needs_merge)

    def test_manifest_requires_merge_for_locally_modified_managed_file(self):
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

        self.assertIn(path, classification.needs_merge)
        self.assertNotIn(path, classification.will_upgrade)

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


if __name__ == "__main__":
    unittest.main()
