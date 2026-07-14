from __future__ import annotations

import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from raven_lib.constants import KIND_FILE, KIND_SYMLINK
from raven_lib.models import Fingerprint, ManifestRecord
from raven_lib.orphans import (
    _unmodified_baseline,
    classify_orphans,
    remove_orphans,
    shipped_relatives,
)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class ShippedRelativesTests(unittest.TestCase):
    def test_includes_starter_config_even_when_present_on_disk(self) -> None:
        # entries_for_destination pops an existing starter config; shipped_relatives
        # must still count it as shipped so it is never treated as an orphan.
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        template = Path(tmp.name) / "template"
        dest = Path(tmp.name) / "dest"
        # A real starter-config path shipped by every template.
        from raven_lib.constants import STARTER_TOOL_CONFIG_PATHS

        starter = sorted(STARTER_TOOL_CONFIG_PATHS)[0]
        _write(template / starter, "shipped\n")
        _write(dest / starter, "user copy\n")
        self.assertIn(starter, shipped_relatives(template, dest))


class ClassifyOrphansTests(unittest.TestCase):
    def _setup(self) -> tuple[Path, Path]:
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        template = Path(tmp.name) / "template"
        dest = Path(tmp.name) / "dest"
        template.mkdir()
        dest.mkdir()
        return template, dest

    def test_clean_orphan_is_will_remove(self) -> None:
        template, dest = self._setup()
        from raven_lib.hashing import file_sha256

        target = dest / "docs" / "dropped.md"
        _write(target, "content\n")
        sha = file_sha256(target)
        manifest = {
            "schema": 1,
            "files": {
                "docs/dropped.md": {
                    "kind": "file",
                    "installedSha256": sha,
                    "sourceSha256": sha,
                }
            },
        }
        result = classify_orphans(template, dest, manifest)
        self.assertEqual(result.will_remove, ["docs/dropped.md"])
        self.assertEqual(result.orphan_modified, [])

    def test_locally_modified_orphan_is_reported_not_removed(self) -> None:
        template, dest = self._setup()
        target = dest / "docs" / "dropped.md"
        _write(target, "user edited this\n")
        manifest = {
            "schema": 1,
            "files": {
                "docs/dropped.md": {
                    "kind": "file",
                    "installedSha256": "a" * 64,  # baseline the user diverged from
                    "sourceSha256": "a" * 64,
                }
            },
        }
        result = classify_orphans(template, dest, manifest)
        self.assertEqual(result.orphan_modified, ["docs/dropped.md"])
        self.assertEqual(result.will_remove, [])

    def test_customized_baseline_is_reported_not_removed(self) -> None:
        template, dest = self._setup()
        from raven_lib.hashing import file_sha256

        target = dest / "docs" / "dropped.md"
        _write(target, "accepted merge\n")
        sha = file_sha256(target)
        manifest = {
            "schema": 1,
            "files": {
                "docs/dropped.md": {
                    "kind": "file",
                    "installedSha256": sha,
                    "sourceSha256": "b" * 64,  # installed != source: a customization
                }
            },
        }
        result = classify_orphans(template, dest, manifest)
        self.assertEqual(result.orphan_modified, ["docs/dropped.md"])
        self.assertEqual(result.will_remove, [])

    def test_missing_on_disk_is_already_gone(self) -> None:
        template, dest = self._setup()
        manifest = {
            "schema": 1,
            "files": {
                "docs/dropped.md": {
                    "kind": "file",
                    "installedSha256": "a" * 64,
                    "sourceSha256": "a" * 64,
                }
            },
        }
        result = classify_orphans(template, dest, manifest)
        self.assertEqual(result.already_gone, ["docs/dropped.md"])
        self.assertEqual(result.will_remove, [])

    def test_still_shipped_file_is_not_an_orphan(self) -> None:
        template, dest = self._setup()
        from raven_lib.hashing import file_sha256

        _write(template / "docs" / "kept.md", "content\n")
        target = dest / "docs" / "kept.md"
        _write(target, "content\n")
        sha = file_sha256(target)
        manifest = {
            "schema": 1,
            "files": {
                "docs/kept.md": {
                    "kind": "file",
                    "installedSha256": sha,
                    "sourceSha256": sha,
                }
            },
        }
        result = classify_orphans(template, dest, manifest)
        self.assertEqual(result.will_remove, [])
        self.assertEqual(result.orphan_modified, [])
        self.assertEqual(result.already_gone, [])

    def test_legacy_record_without_source_sha_is_not_removed(self) -> None:
        template, dest = self._setup()
        from raven_lib.hashing import file_sha256

        target = dest / "docs" / "dropped.md"
        _write(target, "content\n")
        sha = file_sha256(target)
        manifest = {
            "schema": 1,
            "files": {"docs/dropped.md": {"kind": "file", "installedSha256": sha}},
        }
        result = classify_orphans(template, dest, manifest)
        self.assertEqual(result.orphan_modified, ["docs/dropped.md"])
        self.assertEqual(result.will_remove, [])

    def test_absolute_key_is_ignored_not_classified(self) -> None:
        # A crafted absolute manifest key must never be classified: dry-run must
        # not even NAME an external path, let alone stage it for deletion.
        template, dest = self._setup()
        from raven_lib.hashing import file_sha256

        outside = dest.parent / "evil.md"  # a sibling of dest, outside it
        _write(outside, "content\n")
        sha = file_sha256(outside)
        key = str(outside)  # absolute path
        manifest = {
            "schema": 1,
            "files": {key: {"kind": "file", "installedSha256": sha, "sourceSha256": sha}},
        }
        result = classify_orphans(template, dest, manifest)
        self.assertNotIn(key, result.will_remove)
        self.assertNotIn(key, result.orphan_modified)
        self.assertNotIn(key, result.already_gone)
        self.assertTrue(outside.exists())

    def test_symlinked_ancestor_escape_is_ignored_not_classified(self) -> None:
        # A relative key whose parent traverses a symlinked directory escapes the
        # destination when joined. Classification must reject it, not fingerprint
        # (and thereby name) the external target.
        template, dest = self._setup()
        from raven_lib.hashing import file_sha256

        outside_dir = dest.parent / "outside"
        secret = outside_dir / "secret.md"
        _write(secret, "content\n")
        sha = file_sha256(secret)
        (dest / "link").symlink_to(outside_dir, target_is_directory=True)
        key = "link/secret.md"
        manifest = {
            "schema": 1,
            "files": {key: {"kind": "file", "installedSha256": sha, "sourceSha256": sha}},
        }
        result = classify_orphans(template, dest, manifest)
        self.assertNotIn(key, result.will_remove)
        self.assertNotIn(key, result.orphan_modified)
        self.assertNotIn(key, result.already_gone)
        self.assertTrue(secret.exists())


class UnmodifiedBaselineTests(unittest.TestCase):
    """Direct-call coverage for the symlink branches of the safety gate.

    These lock in the checks that prevent an orphaned symlink from being
    auto-removed unless its kind and target still match the recorded baseline.
    """

    def test_kind_mismatch_is_not_unmodified(self) -> None:
        sha = "a" * 64
        record = ManifestRecord(
            kind=KIND_SYMLINK, installed_sha256=sha, source_sha256=sha, target="a"
        )
        fingerprint = Fingerprint(kind=KIND_FILE, sha256=sha)
        self.assertFalse(_unmodified_baseline(record, fingerprint))

    def test_symlink_target_mismatch_is_not_unmodified(self) -> None:
        sha = "a" * 64
        record = ManifestRecord(
            kind=KIND_SYMLINK, installed_sha256=sha, source_sha256=sha, target="a"
        )
        fingerprint = Fingerprint(kind=KIND_SYMLINK, sha256=sha, target="b")
        self.assertFalse(_unmodified_baseline(record, fingerprint))

    def test_symlink_clean_match_is_unmodified(self) -> None:
        sha = "a" * 64
        record = ManifestRecord(
            kind=KIND_SYMLINK, installed_sha256=sha, source_sha256=sha, target="a"
        )
        fingerprint = Fingerprint(kind=KIND_SYMLINK, sha256=sha, target="a")
        self.assertTrue(_unmodified_baseline(record, fingerprint))


class RemoveOrphansTests(unittest.TestCase):
    def test_removes_file_and_prunes_empty_parent(self) -> None:
        with TemporaryDirectory() as tmp:
            dest = Path(tmp)
            target = dest / "docs" / "sub" / "dropped.md"
            _write(target, "x\n")
            from raven_lib.orphans import remove_orphans

            removed = remove_orphans(dest, ["docs/sub/dropped.md"])
            self.assertEqual(removed, ["docs/sub/dropped.md"])
            self.assertFalse(target.exists())
            # Now-empty parents are pruned...
            self.assertFalse((dest / "docs" / "sub").exists())
            self.assertFalse((dest / "docs").exists())
            # ...but the destination root is never removed.
            self.assertTrue(dest.exists())

    def test_keeps_parent_with_other_files(self) -> None:
        with TemporaryDirectory() as tmp:
            dest = Path(tmp)
            _write(dest / "docs" / "dropped.md", "x\n")
            _write(dest / "docs" / "kept.md", "y\n")
            from raven_lib.orphans import remove_orphans

            remove_orphans(dest, ["docs/dropped.md"])
            self.assertTrue((dest / "docs" / "kept.md").exists())
            self.assertTrue((dest / "docs").exists())

    def test_removes_symlink_orphan(self) -> None:
        with TemporaryDirectory() as tmp:
            dest = Path(tmp)
            (dest / "docs").mkdir()
            link = dest / "docs" / "link.md"
            link.symlink_to("../common/real.md")
            from raven_lib.orphans import remove_orphans

            removed = remove_orphans(dest, ["docs/link.md"])
            self.assertEqual(removed, ["docs/link.md"])
            self.assertFalse(link.is_symlink())

    def test_rejects_path_traversal_key(self) -> None:
        # Defense-in-depth: the delete primitive must fail closed even on a
        # malformed manifest key that tries to escape the destination root.
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            dest = root / "dest"
            dest.mkdir()
            sentinel = root / "evil.md"
            _write(sentinel, "outside the destination\n")
            from raven_lib.orphans import remove_orphans

            removed = remove_orphans(dest, ["../evil.md"])
            self.assertEqual(removed, [])
            self.assertTrue(sentinel.exists())

    def test_rejects_absolute_key(self) -> None:
        # An absolute manifest key discards the destination when joined; the
        # delete primitive must fail closed and leave the external file intact.
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            dest = root / "dest"
            dest.mkdir()
            outside = root / "evil.md"
            _write(outside, "outside the destination\n")

            removed = remove_orphans(dest, [str(outside)])
            self.assertEqual(removed, [])
            self.assertTrue(outside.exists())

    def test_rejects_symlinked_ancestor_key(self) -> None:
        # A relative key routed through a symlinked ancestor directory resolves
        # outside the destination; removal must not follow it and delete the
        # external target.
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            dest = root / "dest"
            dest.mkdir()
            outside_dir = root / "outside"
            secret = outside_dir / "secret.md"
            _write(secret, "precious\n")
            (dest / "link").symlink_to(outside_dir, target_is_directory=True)

            removed = remove_orphans(dest, ["link/secret.md"])
            self.assertEqual(removed, [])
            self.assertTrue(secret.exists())

    def test_rejects_non_canonical_keys(self) -> None:
        # Non-canonical forms (leading ./, trailing/doubled slash, bare dot,
        # empty, backslash) are rejected. A legit file is only ever removable via
        # its canonical key, so rejecting these cannot lose a real orphan.
        with TemporaryDirectory() as tmp:
            dest = Path(tmp)
            _write(dest / "a.md", "x\n")
            for key in ["./a.md", "a.md/", "sub//a.md", ".", "", "sub\\a.md"]:
                removed = remove_orphans(dest, [key])
                self.assertEqual(removed, [], f"non-canonical key not rejected: {key!r}")
            self.assertTrue((dest / "a.md").exists())


class UpdateManifestRemoveTests(unittest.TestCase):
    def test_remove_pops_records_before_save(self) -> None:
        with TemporaryDirectory() as tmp:
            dest = Path(tmp)
            (dest / ".raven").mkdir()
            import json

            (dest / ".raven" / "manifest.json").write_text(
                json.dumps(
                    {
                        "schema": 1,
                        "files": {
                            "docs/gone.md": {"kind": "file", "installedSha256": "a" * 64},
                            "docs/kept.md": {"kind": "file", "installedSha256": "b" * 64},
                        },
                    }
                ),
                encoding="utf-8",
            )
            from raven_lib.manifest import load_manifest, update_manifest
            from raven_lib.models import RavenConfig

            config = RavenConfig(None, False, {}, {}, {}, [])
            template = dest / "template"
            template.mkdir()
            update_manifest(dest, "python", template, set(), config, [], remove=["docs/gone.md"])
            files = load_manifest(dest)["files"]
            self.assertNotIn("docs/gone.md", files)
            self.assertIn("docs/kept.md", files)


if __name__ == "__main__":
    unittest.main()
