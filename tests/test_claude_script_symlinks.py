import os
import unittest

from helpers import REPO_ROOT, RavenTestCase, raven

# Subdirectories that language templates share from common via a whole-directory
# symlink, mirroring the .codex/* convention. Linking the directory (rather than
# each file) means a new file under common/.claude/<subdir> propagates to every
# template automatically, with no per-file wiring to forget.
WHOLE_DIR_LINKED_SUBDIRS = ("scripts", "hooks")


def _language_template_dirs():
    for entry in sorted(REPO_ROOT.iterdir()):
        if not entry.is_dir() or entry.name.startswith("."):
            continue
        if entry.name in raven.NON_TEMPLATE_DIRS:
            continue
        if (entry / ".claude").is_dir():
            yield entry


class ClaudeWholeDirSymlinkParityTests(RavenTestCase):
    """Each language template links common Claude scripts and hooks as a whole
    directory symlink, like .codex already does. The installer follows ../common
    symlinks and materializes real files, so installs are unaffected; this is
    purely about retiring per-file symlink maintenance (and the bug class where a
    new common file was silently dropped until linked into all eight templates)."""

    def test_scripts_and_hooks_are_whole_dir_symlinks_to_common(self):
        templates = list(_language_template_dirs())
        self.assertTrue(templates, "expected at least one language template")

        for template in templates:
            for subdir in WHOLE_DIR_LINKED_SUBDIRS:
                link = template / ".claude" / subdir
                with self.subTest(template=template.name, subdir=subdir):
                    self.assertTrue(
                        link.is_symlink(),
                        f"{link} should be a whole-directory symlink to "
                        f"../../common/.claude/{subdir}",
                    )
                    target = os.readlink(link).replace("\\", "/")
                    self.assertEqual(target, f"../../common/.claude/{subdir}")


if __name__ == "__main__":
    unittest.main()
