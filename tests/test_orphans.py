from __future__ import annotations

import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from raven_lib.orphans import classify_orphans, shipped_relatives


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


if __name__ == "__main__":
    unittest.main()
