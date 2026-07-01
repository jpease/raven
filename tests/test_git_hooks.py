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
        # Git hooks run with GIT_DIR/GIT_INDEX_FILE/etc. exported. If this suite
        # runs inside a hook (e.g. the pre-commit `just check`), those inherited
        # vars would point git at the outer repo instead of the temp repo these
        # tests create, so strip them for the duration of each test.
        for var in [k for k in os.environ if k.startswith("GIT_")]:
            self.addCleanup(os.environ.__setitem__, var, os.environ[var])
            del os.environ[var]

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

    def _hook_env(self, bin_dir: Path) -> dict[str, str]:
        # Build a PATH where bin_dir (the chosen `git` plus any fake `just`) wins,
        # but the system dirs a wrapper-style `git` needs stay resolvable. With
        # only bin_dir on PATH, a `git` that shells out to `/usr/bin/env bash`
        # (e.g. Apple's `/usr/bin/git` -> `xcrun`) fails `rev-parse`, so the hook
        # short-circuits via `|| exit 0` before ever reaching `just` -- making the
        # failing-`just` tests pass for the wrong reason (issue #54). `just` does
        # not live in /usr/bin or /bin, so the "just missing" tests still see it
        # absent, and bin_dir-first keeps a fake `just` ahead of any system one.
        env = {k: v for k, v in os.environ.items() if k != "PATH"}
        env["PATH"] = os.pathsep.join([str(bin_dir), "/usr/bin", "/bin"])
        return env

    def _prepare_verified_repo(self, just_exit: int):
        # Make an initial commit so HEAD resolves, and put the fake `git`/`just`
        # in a bin dir OUTSIDE the repo so they do not show up as untracked files
        # that would dirty the tree (the skip path requires a clean tree). Returns
        # (env, head_sha, stamp_path).
        subprocess.run(
            [
                "git",
                "-C",
                str(self.destination),
                "-c",
                "user.email=raven@example.com",
                "-c",
                "user.name=Raven Test",
                "commit",
                "--allow-empty",
                "-m",
                "init",
            ],
            capture_output=True,
            check=True,
        )
        head = subprocess.run(
            ["git", "-C", str(self.destination), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        bin_tmp = tempfile.TemporaryDirectory()
        self.addCleanup(bin_tmp.cleanup)
        bin_dir = Path(bin_tmp.name)
        git_path = subprocess.run(
            ["which", "git"], capture_output=True, text=True, check=True
        ).stdout.strip()
        (bin_dir / "git").symlink_to(git_path)
        fake_just = bin_dir / "just"
        fake_just.write_text(f"#!/bin/sh\nexit {just_exit}\n", encoding="utf-8")
        fake_just.chmod(0o755)
        env = self._hook_env(bin_dir)
        stamp = self.destination / ".git" / "raven-pre-push-verified"
        return env, head, stamp

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
        # A linked worktree branches from a commit; create one (with an inline
        # identity so the test does not depend on global git config) so
        # `worktree add` does not race on an unborn HEAD. If git still cannot
        # create the worktree here, skip with a clear reason rather than failing.
        subprocess.run(
            [
                "git",
                "-C",
                str(self.destination),
                "-c",
                "user.email=raven@example.com",
                "-c",
                "user.name=Raven Test",
                "commit",
                "--allow-empty",
                "-m",
                "init",
            ],
            capture_output=True,
            check=True,
        )
        worktree_dir = self.destination.parent / "linked-wt"
        added = subprocess.run(
            ["git", "-C", str(self.destination), "worktree", "add", str(worktree_dir)],
            capture_output=True,
            text=True,
            check=False,
        )
        if added.returncode != 0:
            self.skipTest(f"git could not create a linked worktree here: {added.stderr.strip()}")
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

        env = self._hook_env(bin_dir)
        result = subprocess.run(
            ["/bin/sh", str(hook)],
            cwd=self.destination,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_install_targets_destination_despite_inherited_git_dir(self):
        # Reproduces the corruption: running inside another repo's hook exports
        # GIT_DIR/GIT_INDEX_FILE. install_git_hooks must still target the passed
        # destination, never the repo named by the ambient environment.
        self._write_hook("pre-commit", "#!/bin/sh\njust check\n")
        decoy_tmp = tempfile.TemporaryDirectory()
        self.addCleanup(decoy_tmp.cleanup)
        decoy = Path(decoy_tmp.name)
        subprocess.run(["git", "init", str(decoy)], capture_output=True, check=True)
        os.environ["GIT_DIR"] = str(decoy / ".git")
        os.environ["GIT_INDEX_FILE"] = str(decoy / ".git" / "index")
        self.addCleanup(os.environ.pop, "GIT_DIR", None)
        self.addCleanup(os.environ.pop, "GIT_INDEX_FILE", None)

        installed = raven.install_git_hooks(self.destination)

        self.assertEqual(installed, ["pre-commit"])
        self.assertTrue((self.destination / ".git" / "hooks" / "pre-commit").is_symlink())
        # The decoy repo named by GIT_DIR must be left untouched.
        self.assertFalse((decoy / ".git" / "hooks" / "pre-commit").exists())

    def test_pre_commit_hook_blocks_when_just_check_fails(self):
        hook = raven.REPO_ROOT / "common" / ".raven" / "git-hooks" / "pre-commit"
        git_path = subprocess.run(
            ["which", "git"], capture_output=True, text=True, check=True
        ).stdout.strip()
        bin_dir = self.destination / "bin"
        bin_dir.mkdir()
        (bin_dir / "git").symlink_to(git_path)
        # A `just` that fails must abort the commit -- the whole point of running
        # `just check` in the hook.
        fake_just = bin_dir / "just"
        fake_just.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
        fake_just.chmod(0o755)

        env = self._hook_env(bin_dir)
        result = subprocess.run(
            ["/bin/sh", str(hook)],
            cwd=self.destination,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertNotEqual(result.returncode, 0)

    def test_hook_division_pre_commit_is_fast_pre_push_is_full(self):
        # The split is the whole point: pre-commit runs only the fast subset so
        # the commit loop stays quick, while pre-push runs the full gate so the
        # expensive tests run exactly once before code leaves the machine.
        hooks = raven.REPO_ROOT / "common" / ".raven" / "git-hooks"
        pre_commit = (hooks / "pre-commit").read_text(encoding="utf-8")
        pre_push = (hooks / "pre-push").read_text(encoding="utf-8")
        self.assertIn("just check-fast", pre_commit)
        self.assertNotIn("just check ", pre_commit)
        self.assertIn("just check", pre_push)
        self.assertNotIn("just check-fast", pre_push)

    # A normal push: one ref with a non-zero local SHA. The all-zero remote SHA
    # (new branch) is irrelevant -- only the local SHA decides if work is leaving.
    _PUSH_STDIN = (
        "refs/heads/main 1111111111111111111111111111111111111111 "
        "refs/heads/main 0000000000000000000000000000000000000000\n"
    )
    # A delete-only push: git sends "(delete)" with an all-zero local SHA.
    _DELETE_STDIN = (
        "(delete) 0000000000000000000000000000000000000000 "
        "refs/heads/old 2222222222222222222222222222222222222222\n"
    )

    def test_pre_push_hook_is_optional_when_just_missing(self):
        hook = raven.REPO_ROOT / "common" / ".raven" / "git-hooks" / "pre-push"
        git_path = subprocess.run(
            ["which", "git"], capture_output=True, text=True, check=True
        ).stdout.strip()
        bin_dir = self.destination / "bin"
        bin_dir.mkdir()
        (bin_dir / "git").symlink_to(git_path)

        env = self._hook_env(bin_dir)
        result = subprocess.run(
            ["/bin/sh", str(hook)],
            cwd=self.destination,
            env=env,
            input=self._PUSH_STDIN,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_pre_push_hook_blocks_when_just_check_fails(self):
        hook = raven.REPO_ROOT / "common" / ".raven" / "git-hooks" / "pre-push"
        git_path = subprocess.run(
            ["which", "git"], capture_output=True, text=True, check=True
        ).stdout.strip()
        bin_dir = self.destination / "bin"
        bin_dir.mkdir()
        (bin_dir / "git").symlink_to(git_path)
        # A failing `just check` must abort the push -- the last gate before code
        # leaves the machine.
        fake_just = bin_dir / "just"
        fake_just.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
        fake_just.chmod(0o755)

        env = self._hook_env(bin_dir)
        result = subprocess.run(
            ["/bin/sh", str(hook)],
            cwd=self.destination,
            env=env,
            input=self._PUSH_STDIN,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertNotEqual(result.returncode, 0)

    def test_pre_push_hook_skips_heavy_checks_for_delete_only_push(self):
        # A delete-only push (all local SHAs zero) ships no code, so the hook must
        # exit 0 without ever running `just check` -- even one rigged to fail.
        hook = raven.REPO_ROOT / "common" / ".raven" / "git-hooks" / "pre-push"
        git_path = subprocess.run(
            ["which", "git"], capture_output=True, text=True, check=True
        ).stdout.strip()
        bin_dir = self.destination / "bin"
        bin_dir.mkdir()
        (bin_dir / "git").symlink_to(git_path)
        fake_just = bin_dir / "just"
        fake_just.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
        fake_just.chmod(0o755)

        env = self._hook_env(bin_dir)
        result = subprocess.run(
            ["/bin/sh", str(hook)],
            cwd=self.destination,
            env=env,
            input=self._DELETE_STDIN,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_pre_push_hook_skips_heavy_checks_when_nothing_to_push(self):
        # Empty stdin (no refs in the push range) must also short-circuit before
        # the gate runs.
        hook = raven.REPO_ROOT / "common" / ".raven" / "git-hooks" / "pre-push"
        git_path = subprocess.run(
            ["which", "git"], capture_output=True, text=True, check=True
        ).stdout.strip()
        bin_dir = self.destination / "bin"
        bin_dir.mkdir()
        (bin_dir / "git").symlink_to(git_path)
        fake_just = bin_dir / "just"
        fake_just.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
        fake_just.chmod(0o755)

        env = self._hook_env(bin_dir)
        result = subprocess.run(
            ["/bin/sh", str(hook)],
            cwd=self.destination,
            env=env,
            input="",
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_pre_push_skips_when_head_verified_and_tree_clean(self):
        # Stamp records the current HEAD and the tree is clean, so the hook must
        # skip the gate entirely -- even a `just` rigged to fail is never run.
        hook = raven.REPO_ROOT / "common" / ".raven" / "git-hooks" / "pre-push"
        env, head, stamp = self._prepare_verified_repo(just_exit=1)
        stamp.write_text(head + "\n", encoding="utf-8")

        result = subprocess.run(
            ["/bin/sh", str(hook)],
            cwd=self.destination,
            env=env,
            input=self._PUSH_STDIN,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_pre_push_reruns_when_tree_dirty_despite_matching_stamp(self):
        # Stamp matches HEAD, but an uncommitted (untracked) change dirties the
        # tree, so the cached pass is invalid and the failing gate must run.
        hook = raven.REPO_ROOT / "common" / ".raven" / "git-hooks" / "pre-push"
        env, head, stamp = self._prepare_verified_repo(just_exit=1)
        stamp.write_text(head + "\n", encoding="utf-8")
        (self.destination / "scratch.txt").write_text("dirty\n", encoding="utf-8")

        result = subprocess.run(
            ["/bin/sh", str(hook)],
            cwd=self.destination,
            env=env,
            input=self._PUSH_STDIN,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertNotEqual(result.returncode, 0)

    def test_pre_push_reruns_when_head_differs_from_stamp(self):
        # Stamp holds a different SHA (e.g. a new commit since verification), so
        # the failing gate must run rather than skip.
        hook = raven.REPO_ROOT / "common" / ".raven" / "git-hooks" / "pre-push"
        env, _head, stamp = self._prepare_verified_repo(just_exit=1)
        stamp.write_text("0" * 40 + "\n", encoding="utf-8")

        result = subprocess.run(
            ["/bin/sh", str(hook)],
            cwd=self.destination,
            env=env,
            input=self._PUSH_STDIN,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
