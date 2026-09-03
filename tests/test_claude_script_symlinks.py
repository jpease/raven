import os
import unittest

from helpers import (
    REPO_ROOT,
    UNIFIED_ADAPTER_HOOKS,
    UNIFIED_ADAPTER_SCRIPTS,
    RavenTestCase,
    codex_hook_symlink_target,
    codex_script_symlink_target,
    raven,
)
from raven_lib.template import should_preserve_symlink

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
    new common file was silently dropped until linked into all eight templates).
    """

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


class CodexScriptUnificationTests(RavenTestCase):
    """The byte-identical adapter scripts are stored once and linked, instead of
    being maintained as two copies a fix could land in only one of (issue #165).

    Unlike the whole-directory language-tree links above, these are per-file:
    `.codex/scripts/` also holds nothing else, but a future adapter-specific
    script must be able to sit beside them as a real file.
    """

    @staticmethod
    def _codex_script(name: str):
        return REPO_ROOT / "common" / ".codex" / "scripts" / name

    @staticmethod
    def _claude_script(name: str):
        return REPO_ROOT / "common" / ".claude" / "scripts" / name

    def test_codex_scripts_link_to_the_claude_copies(self):
        for name in UNIFIED_ADAPTER_SCRIPTS:
            with self.subTest(script=name):
                link = self._codex_script(name)
                self.assertTrue(link.is_symlink(), f"{link} should be a symlink, not a copy")
                self.assertEqual(
                    os.readlink(link).replace("\\", "/"),
                    codex_script_symlink_target(name),
                )

    def test_claude_copies_are_real_files(self):
        # The direction matters: a `grep` in a fresh clone must land on real
        # content, and the Claude tree is where the docs and skills point.
        for name in UNIFIED_ADAPTER_SCRIPTS:
            with self.subTest(script=name):
                script = self._claude_script(name)
                self.assertFalse(script.is_symlink(), f"{script} must hold the real content")
                self.assertTrue(script.is_file())

    def test_installer_dereferences_the_codex_script_links(self):
        # This is the assertion that protects destinations. If a target is ever
        # respelled so it no longer climbs through `common/`, the installer
        # preserves it as a symlink and a Codex-only install (Claude scripts
        # component disabled) gets a dangling link.
        for name in UNIFIED_ADAPTER_SCRIPTS:
            with self.subTest(script=name):
                script = self._codex_script(name)
                # Precondition, not decoration: should_preserve_symlink also
                # returns False for a plain file, so without this the assertion
                # below would pass for an un-unified copy too.
                self.assertTrue(script.is_symlink(), f"{name} is not linked at all")
                self.assertFalse(
                    should_preserve_symlink(script),
                    f"{name}: installer would ship this as a symlink instead of real content",
                )

    def test_byte_identical_codex_hooks_are_unified_too(self):
        # Same duplication, same fix: these hook scripts were byte-identical
        # copies (or, for `raven-session-checkpoint.py`, became byte-identical
        # once it learned to compute its own adapter directory at runtime
        # instead of hardcoding one -- issue #195). `raven-skeleton-read-guard.py`
        # is excluded because it is deliberately Claude-only, recorded in the
        # classification table in `.claude/docs/raven-agent-compatibility.md`.
        for name in UNIFIED_ADAPTER_HOOKS:
            with self.subTest(hook=name):
                link = REPO_ROOT / "common" / ".codex" / "hooks" / name
                self.assertTrue(link.is_symlink(), f"{name} is a duplicate copy again")
                self.assertEqual(
                    os.readlink(link).replace("\\", "/"),
                    codex_hook_symlink_target(name),
                )
                self.assertFalse(should_preserve_symlink(link))

    def test_read_guard_has_no_codex_counterpart(self):
        # The classification is only useful if it is enforced in both
        # directions: unifying this would be a behavior change, not a cleanup --
        # the read guard has no Codex counterpart at all (it is deliberately
        # Claude-only, per `.claude/docs/raven-agent-compatibility.md`'s
        # "Intentionally asymmetric" row).
        read_guard = REPO_ROOT / "common" / ".codex" / "hooks" / "raven-skeleton-read-guard.py"
        self.assertFalse(
            read_guard.exists() or read_guard.is_symlink(),
            "the Claude-only read guard must not gain a Codex counterpart",
        )

    def test_bash_truncator_has_no_codex_counterpart(self):
        # Same classification, same reason in kind: Codex's PostToolUse hook
        # cannot replace a tool result, so a `.codex/hooks/` copy would be a
        # hook that never does anything.
        truncator = REPO_ROOT / "common" / ".codex" / "hooks" / "raven-post-bash-truncate.py"
        self.assertFalse(
            truncator.exists() or truncator.is_symlink(),
            "the Claude-only Bash truncator must not gain a Codex counterpart",
        )

    def test_a_non_common_spelling_would_be_preserved(self):
        # Proves the check above has teeth rather than passing for every input:
        # the shorter sibling spelling resolves to the same file, but the
        # installer would preserve it, which is exactly the bug being guarded.
        link = self.destination / "raven-session.py"
        link.symlink_to("../../.claude/scripts/raven-session.py")

        self.assertTrue(should_preserve_symlink(link))


if __name__ == "__main__":
    unittest.main()
