import os
import unittest

from helpers import REPO_ROOT, RavenTestCase, raven

# Subdirectories under .claude that language templates link per-file (unlike the
# Codex whole-directory symlink). A new file in common/.claude/<subdir> must be
# linked into every template, or it silently drops from Claude installs.
PER_FILE_LINKED_SUBDIRS = ("scripts", "hooks")


def _language_template_dirs():
    for entry in sorted(REPO_ROOT.iterdir()):
        if not entry.is_dir() or entry.name.startswith("."):
            continue
        if entry.name in raven.NON_TEMPLATE_DIRS:
            continue
        if (entry / ".claude").is_dir():
            yield entry


class ClaudePerFileSymlinkParityTests(RavenTestCase):
    """Guard the per-file Claude symlink convention for scripts and hooks.
    Regression: raven-skeleton.py (scripts) and raven-skeleton-read-guard.py
    (hooks) each needed linking into all templates."""

    def test_every_common_file_is_linked_into_every_language_template(self):
        templates = list(_language_template_dirs())
        self.assertTrue(templates, "expected at least one language template")

        for subdir in PER_FILE_LINKED_SUBDIRS:
            common_dir = REPO_ROOT / "common" / ".claude" / subdir
            common_files = [p.name for p in common_dir.iterdir() if p.is_file()]
            self.assertTrue(common_files, f"expected files under common/.claude/{subdir}")

            for template in templates:
                target_dir = template / ".claude" / subdir
                for name in common_files:
                    link = target_dir / name
                    with self.subTest(template=template.name, subdir=subdir, file=name):
                        self.assertTrue(
                            link.is_symlink(),
                            f"{link} is missing; add a symlink to "
                            f"../../../common/.claude/{subdir}/{name}",
                        )
                        target = os.readlink(link).replace("\\", "/")
                        self.assertEqual(target, f"../../../common/.claude/{subdir}/{name}")


if __name__ == "__main__":
    unittest.main()
