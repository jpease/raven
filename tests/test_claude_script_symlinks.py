import os
import unittest

from helpers import REPO_ROOT, RavenTestCase, raven

COMMON_CLAUDE_SCRIPTS = REPO_ROOT / "common" / ".claude" / "scripts"


def _language_template_dirs():
    for entry in sorted(REPO_ROOT.iterdir()):
        if not entry.is_dir() or entry.name.startswith("."):
            continue
        if entry.name in raven.NON_TEMPLATE_DIRS:
            continue
        if (entry / ".claude" / "scripts").is_dir():
            yield entry


class ClaudeScriptSymlinkParityTests(RavenTestCase):
    """Each language template links Claude scripts per-file (unlike the Codex
    whole-directory symlink), so a new ``common/.claude/scripts`` file must be
    linked into every template. Without this guard a missing link silently
    drops the script from Claude installs (regression: raven-skeleton.py)."""

    def test_every_common_script_is_linked_into_every_language_template(self):
        common_scripts = [p.name for p in COMMON_CLAUDE_SCRIPTS.iterdir() if p.is_file()]
        self.assertTrue(common_scripts, "expected scripts under common/.claude/scripts")

        templates = list(_language_template_dirs())
        self.assertTrue(templates, "expected at least one language template")

        for template in templates:
            scripts_dir = template / ".claude" / "scripts"
            for script_name in common_scripts:
                link = scripts_dir / script_name
                with self.subTest(template=template.name, script=script_name):
                    self.assertTrue(
                        link.is_symlink(),
                        f"{link} is missing; add a symlink to ../../../common/.claude/scripts/",
                    )
                    target = os.readlink(link).replace("\\", "/")
                    self.assertEqual(target, f"../../../common/.claude/scripts/{script_name}")


if __name__ == "__main__":
    unittest.main()
