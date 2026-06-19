import contextlib
import io
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from helpers import raven


class GitHookInstallerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.destination = Path(self.tmp.name)
        subprocess.run(
            ["git", "init", str(self.destination)],
            capture_output=True,
            check=True,
        )
        self.git_hooks_src = self.destination / ".raven" / "git-hooks"
        self.git_hooks_src.mkdir(parents=True)
        self.git_hooks_dir = self.destination / ".git" / "hooks"
        self.git_hooks_dir.mkdir(exist_ok=True)

    def _write_hook(self, name: str, content: str = "#!/bin/sh\n") -> Path:
        hook = self.git_hooks_src / name
        hook.write_text(content, encoding="utf-8")
        hook.chmod(0o644)
        return hook

    def test_installs_hook_as_symlink_in_git_hooks(self):
        self._write_hook("commit-msg")

        installed = raven.install_git_hooks(self.destination)

        link = self.git_hooks_dir / "commit-msg"
        self.assertEqual(installed, ["commit-msg"])
        self.assertTrue(link.is_symlink())
        self.assertEqual(link.resolve(), (self.git_hooks_src / "commit-msg").resolve())

    def test_makes_hook_file_executable(self):
        self._write_hook("commit-msg")

        raven.install_git_hooks(self.destination)

        hook_src = self.git_hooks_src / "commit-msg"
        self.assertTrue(hook_src.stat().st_mode & 0o111)

    def test_returns_empty_when_no_git_hooks_src_dir(self):
        self.git_hooks_src.rmdir()

        installed = raven.install_git_hooks(self.destination)

        self.assertEqual(installed, [])

    def test_returns_empty_when_not_a_git_repo(self):
        non_git = self.destination / "sub"
        non_git.mkdir()
        (non_git / ".raven" / "git-hooks").mkdir(parents=True)
        self._write_hook("commit-msg")

        installed = raven.install_git_hooks(non_git)

        self.assertEqual(installed, [])

    def test_does_not_overwrite_existing_regular_file(self):
        self._write_hook("commit-msg")
        existing = self.git_hooks_dir / "commit-msg"
        existing.write_text("# user hook\n", encoding="utf-8")
        stderr = io.StringIO()

        with contextlib.redirect_stderr(stderr):
            installed = raven.install_git_hooks(self.destination)

        self.assertEqual(installed, [])
        self.assertEqual(existing.read_text(encoding="utf-8"), "# user hook\n")
        self.assertIn("already exists as a regular file", stderr.getvalue())

    def test_idempotent_when_symlink_already_correct(self):
        self._write_hook("commit-msg")
        raven.install_git_hooks(self.destination)

        installed = raven.install_git_hooks(self.destination)

        self.assertEqual(installed, ["commit-msg"])

    def test_updates_stale_symlink(self):
        self._write_hook("commit-msg")
        stale_target = self.git_hooks_src.parent / "old-commit-msg"
        stale_target.write_text("# stale\n", encoding="utf-8")
        link = self.git_hooks_dir / "commit-msg"
        link.symlink_to(str(stale_target))

        installed = raven.install_git_hooks(self.destination)

        self.assertEqual(installed, ["commit-msg"])
        self.assertEqual(link.resolve(), (self.git_hooks_src / "commit-msg").resolve())

    def test_installs_into_custom_core_hooks_path(self):
        custom_hooks = self.destination / ".githooks"
        custom_hooks.mkdir()
        subprocess.run(
            ["git", "-C", str(self.destination), "config", "core.hooksPath", ".githooks"],
            check=True,
        )
        self._write_hook("commit-msg")

        installed = raven.install_git_hooks(self.destination)

        self.assertEqual(installed, ["commit-msg"])
        link = custom_hooks / "commit-msg"
        self.assertTrue(link.is_symlink())
        self.assertFalse((self.git_hooks_dir / "commit-msg").exists())

    def test_linked_worktree_installs_into_shared_hooks_dir(self):
        self._write_hook("commit-msg")
        worktree_dir = self.destination.parent / "linked-wt"
        subprocess.run(
            ["git", "-C", str(self.destination), "worktree", "add", str(worktree_dir)],
            capture_output=True,
            check=True,
        )
        self.addCleanup(
            lambda: subprocess.run(
                [
                    "git",
                    "-C",
                    str(self.destination),
                    "worktree",
                    "remove",
                    "--force",
                    str(worktree_dir),
                ],
                capture_output=True,
            )
        )
        wt_hooks_src = worktree_dir / ".raven" / "git-hooks"
        wt_hooks_src.mkdir(parents=True)
        (wt_hooks_src / "commit-msg").write_text("#!/bin/sh\n", encoding="utf-8")

        installed = raven.install_git_hooks(worktree_dir)

        shared_link = self.git_hooks_dir / "commit-msg"
        self.assertEqual(installed, ["commit-msg"])
        self.assertTrue(shared_link.is_symlink())

    def test_raven_git_hooks_path_included_in_hooks_component(self):
        self.assertIn(".raven/git-hooks", raven.COMPONENT_PATHS["hooks"])

    def test_gitleaks_pre_commit_hook_is_optional_when_missing(self):
        hook = raven.REPO_ROOT / "common" / ".raven" / "git-hooks" / "pre-commit"
        git_path = subprocess.run(
            ["which", "git"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        bin_dir = self.destination / "bin"
        bin_dir.mkdir()
        (bin_dir / "git").symlink_to(git_path)

        env = {k: v for k, v in os.environ.items() if k != "PATH"}
        env["PATH"] = str(bin_dir)
        result = subprocess.run(
            ["/bin/sh", str(hook)],
            cwd=self.destination,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
