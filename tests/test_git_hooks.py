from __future__ import annotations

import contextlib
import io
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from helpers import attribution_line, install_ns, push_plan_line, raven, upgrade_ns
from raven_lib.git_hooks import HookLinkAction, hook_link_action


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
        #
        # The hook resolves the shared cache script relative to the repo root,
        # exactly as an installed project's `.raven/git-hooks/lib/` sibling
        # would -- materialize and commit it here (before HEAD is captured) so
        # a real (just_exit=0) hook run can find and execute it without an
        # untracked file dirtying the tree it is about to check as clean.
        lib_dir = self.git_hooks_src / "lib"
        lib_dir.mkdir(parents=True, exist_ok=True)
        cache_script = lib_dir / "with-verified-cache.sh"
        cache_script.write_text(self._cache_script().read_text(encoding="utf-8"), encoding="utf-8")
        cache_script.chmod(0o755)
        subprocess.run(
            ["git", "-C", str(self.destination), "add", "-A"],
            capture_output=True,
            check=True,
        )
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
        stamp = self.destination / ".git" / "verified-check"
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

    def _bin_dir_with_git(self) -> Path:
        git_path = subprocess.run(
            ["which", "git"], capture_output=True, text=True, check=True
        ).stdout.strip()
        bin_dir = self.destination / "bin"
        bin_dir.mkdir(exist_ok=True)
        if not (bin_dir / "git").exists():
            (bin_dir / "git").symlink_to(git_path)
        return bin_dir

    def test_pre_commit_hook_falls_back_to_protect_on_pre_8_19_gitleaks(self):
        # gitleaks < 8.19 has no `git` subcommand and exits with a cobra
        # "unknown command" error indistinguishable from a real leak (issue #81).
        # The hook must recognize that failure and retry with the older
        # `protect` subcommand instead of blocking every commit.
        bin_dir = self._bin_dir_with_git()
        fake_gitleaks = bin_dir / "gitleaks"
        fake_gitleaks.write_text(
            "#!/bin/sh\n"
            'if [ "$1" = "git" ]; then\n'
            '    echo \'Error: unknown command "git" for "gitleaks"\' >&2\n'
            "    exit 1\n"
            'elif [ "$1" = "protect" ]; then\n'
            "    exit 0\n"
            "fi\n"
            "exit 1\n",
            encoding="utf-8",
        )
        fake_gitleaks.chmod(0o755)

        env = self._hook_env(bin_dir)
        result = subprocess.run(
            ["/bin/sh", str(raven.REPO_ROOT / "common" / ".raven" / "git-hooks" / "pre-commit")],
            cwd=self.destination,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_pre_commit_hook_blocks_on_detected_leak_with_modern_gitleaks(self):
        # A real leak from a modern gitleaks (the `git` subcommand exists and
        # runs) must still block the commit -- the fallback must not swallow
        # genuine findings.
        bin_dir = self._bin_dir_with_git()
        fake_gitleaks = bin_dir / "gitleaks"
        fake_gitleaks.write_text(
            "#!/bin/sh\n"
            'if [ "$1" = "git" ]; then\n'
            "    echo 'leak detected' >&2\n"
            "    exit 1\n"
            "fi\n"
            "exit 1\n",
            encoding="utf-8",
        )
        fake_gitleaks.chmod(0o755)

        env = self._hook_env(bin_dir)
        result = subprocess.run(
            ["/bin/sh", str(raven.REPO_ROOT / "common" / ".raven" / "git-hooks" / "pre-commit")],
            cwd=self.destination,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertNotEqual(result.returncode, 0)

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

    @staticmethod
    def _push_stdin(local_sha: str) -> str:
        # Same shape as _PUSH_STDIN but with a caller-chosen local SHA, so tests
        # can assert on whether that SHA does or does not match HEAD.
        return (
            f"refs/heads/main {local_sha} "
            "refs/heads/main 0000000000000000000000000000000000000000\n"
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
        # Stamp records the current HEAD and the tree is clean, and the pushed
        # ref *is* that HEAD, so the hook must skip the gate entirely -- even a
        # `just` rigged to fail is never run.
        hook = raven.REPO_ROOT / "common" / ".raven" / "git-hooks" / "pre-push"
        env, head, stamp = self._prepare_verified_repo(just_exit=1)
        stamp.write_text(head + "\n", encoding="utf-8")

        result = subprocess.run(
            ["/bin/sh", str(hook)],
            cwd=self.destination,
            env=env,
            input=self._push_stdin(head),
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
            input=self._push_stdin(head),
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertNotEqual(result.returncode, 0)

    def test_pre_push_reruns_when_head_differs_from_stamp(self):
        # Stamp holds a different SHA (e.g. a new commit since verification), so
        # the failing gate must run rather than skip.
        hook = raven.REPO_ROOT / "common" / ".raven" / "git-hooks" / "pre-push"
        env, head, stamp = self._prepare_verified_repo(just_exit=1)
        stamp.write_text("0" * 40 + "\n", encoding="utf-8")

        result = subprocess.run(
            ["/bin/sh", str(hook)],
            cwd=self.destination,
            env=env,
            input=self._push_stdin(head),
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertNotEqual(result.returncode, 0)

    def test_pre_push_reruns_when_pushed_sha_does_not_match_head(self):
        # Regression for issue #80: a stamp that matches THIS worktree's HEAD
        # must not vouch for a push whose local SHA is a different commit (e.g.
        # `git push origin feature` from a worktree sitting on `main`, or a
        # commit made in another worktree sharing this git dir). The failing
        # gate must run rather than skip, even though the stamp and tree are
        # otherwise valid.
        hook = raven.REPO_ROOT / "common" / ".raven" / "git-hooks" / "pre-push"
        env, head, stamp = self._prepare_verified_repo(just_exit=1)
        stamp.write_text(head + "\n", encoding="utf-8")
        other_sha = "3" * 40
        self.assertNotEqual(other_sha, head)

        result = subprocess.run(
            ["/bin/sh", str(hook)],
            cwd=self.destination,
            env=env,
            input=self._push_stdin(other_sha),
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertNotEqual(result.returncode, 0)

    def test_pre_push_writes_stamp_after_clean_pass(self):
        # A clean tree and a passing gate must record HEAD in the stamp so the
        # next push of the same commit can skip.
        hook = raven.REPO_ROOT / "common" / ".raven" / "git-hooks" / "pre-push"
        env, head, stamp = self._prepare_verified_repo(just_exit=0)
        self.assertFalse(stamp.exists())

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
        self.assertTrue(stamp.exists())
        self.assertEqual(stamp.read_text(encoding="utf-8").strip(), head)

    def test_pre_push_does_not_write_stamp_when_gate_fails(self):
        # A failing gate must not stamp -- a cached "pass" would let unverified
        # code push on the next attempt.
        hook = raven.REPO_ROOT / "common" / ".raven" / "git-hooks" / "pre-push"
        env, _head, stamp = self._prepare_verified_repo(just_exit=1)

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
        self.assertFalse(stamp.exists())

    # ---- pre-push attribution scan over the actual push plan (issue #126) ----
    #
    # These use their own fixture rather than _prepare_verified_repo, which
    # deliberately installs only with-verified-cache.sh (leaving pre-push's
    # `[ -f "$attribution_check" ]` guard false, so the scanner is skipped in
    # every stamp test). Here the real scanner IS installed and `just` is kept
    # off PATH, so the scanner alone decides the hook's exit status.

    _ZERO_SHA = "0" * 40

    def _prepare_attribution_repo(self, scanner_body: str | None = None) -> dict[str, str]:
        # Materialize the scanner where pre-push resolves it (repo-root
        # relative), and put `git` in a bin dir OUTSIDE the repo with no `just`
        # so the heavy gate is skipped. `scanner_body` swaps in a stand-in
        # script for tests that need to observe whether it ran at all.
        lib_dir = self.git_hooks_src / "lib"
        lib_dir.mkdir(parents=True, exist_ok=True)
        scanner = lib_dir / "check-ai-attribution-content.py"
        if scanner_body is None:
            source = (
                raven.REPO_ROOT
                / "common"
                / ".raven"
                / "git-hooks"
                / "lib"
                / "check-ai-attribution-content.py"
            )
            scanner_body = source.read_text(encoding="utf-8")
        scanner.write_text(scanner_body, encoding="utf-8")
        scanner.chmod(0o755)

        bin_tmp = tempfile.TemporaryDirectory()
        self.addCleanup(bin_tmp.cleanup)
        bin_dir = Path(bin_tmp.name)
        git_path = subprocess.run(
            ["which", "git"], capture_output=True, text=True, check=True
        ).stdout.strip()
        (bin_dir / "git").symlink_to(git_path)
        return self._hook_env(bin_dir)

    def _repo_git(self, *args: str) -> str:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(self.destination),
                "-c",
                "user.email=raven@example.com",
                "-c",
                "user.name=Raven Test",
                *args,
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()

    def _repo_commit(self, path: str, content: str, message: str) -> str:
        (self.destination / path).write_text(content, encoding="utf-8")
        self._repo_git("add", "--", path)
        self._repo_git("commit", "-q", "-m", message)
        return self._repo_git("rev-parse", "HEAD")

    def _run_pre_push(self, env: dict[str, str], plan: str, remote: str = "origin"):
        hook = raven.REPO_ROOT / "common" / ".raven" / "git-hooks" / "pre-push"
        return subprocess.run(
            ["/bin/sh", str(hook), remote, f"https://example.invalid/{remote}.git"],
            cwd=self.destination,
            env=env,
            input=plan,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_pre_push_blocks_attribution_content_on_non_checked_out_branch(self):
        # Regression for issue #126: the scan must follow the refs Git is
        # actually pushing, not the checked-out branch's upstream range. With
        # `main` checked out, `git push origin feature` used to scan
        # origin/main..HEAD (i.e. main), find nothing, and let the content ship.
        env = self._prepare_attribution_repo()
        base = self._repo_commit("README.md", "# repo\n", "init")
        default_branch = self._repo_git("rev-parse", "--abbrev-ref", "HEAD")
        self._repo_git("update-ref", f"refs/remotes/origin/{default_branch}", base)
        self._repo_git("checkout", "-q", "-b", "feature")
        feature = self._repo_commit(
            "notes.py",
            attribution_line("Copilot", verb="Implemented", prep="with") + "print('hi')\n",
            "feature work",
        )
        self._repo_git("checkout", "-q", default_branch)

        result = self._run_pre_push(
            env, push_plan_line("refs/heads/feature", feature, self._ZERO_SHA)
        )

        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Forbidden AI attribution content", result.stderr)

    def test_pre_push_allows_clean_content_on_non_checked_out_branch(self):
        # The mirror of the regression: a clean pushed ref must not be blocked.
        env = self._prepare_attribution_repo()
        base = self._repo_commit("README.md", "# repo\n", "init")
        default_branch = self._repo_git("rev-parse", "--abbrev-ref", "HEAD")
        self._repo_git("update-ref", f"refs/remotes/origin/{default_branch}", base)
        self._repo_git("checkout", "-q", "-b", "feature")
        feature = self._repo_commit("notes.py", "print('hi')\n", "feature work")
        self._repo_git("checkout", "-q", default_branch)

        result = self._run_pre_push(
            env, push_plan_line("refs/heads/feature", feature, self._ZERO_SHA)
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_pre_push_scans_every_ref_of_a_multi_ref_push(self):
        # `git push --all` sends several updates; a hit on any of them must
        # fail the push, including one that is not the first line.
        env = self._prepare_attribution_repo()
        base = self._repo_commit("README.md", "# repo\n", "init")
        default_branch = self._repo_git("rev-parse", "--abbrev-ref", "HEAD")
        self._repo_git("update-ref", f"refs/remotes/origin/{default_branch}", base)
        self._repo_git("checkout", "-q", "-b", "clean-branch")
        clean = self._repo_commit("clean.py", "print('ok')\n", "clean work")
        self._repo_git("checkout", "-q", default_branch)
        self._repo_git("checkout", "-q", "-b", "dirty-branch")
        dirty = self._repo_commit(
            "dirty.py", attribution_line("Gemini") + "print('hi')\n", "dirty work"
        )
        self._repo_git("checkout", "-q", default_branch)

        plan = push_plan_line("refs/heads/clean-branch", clean, self._ZERO_SHA) + push_plan_line(
            "refs/heads/dirty-branch", dirty, self._ZERO_SHA
        )
        result = self._run_pre_push(env, plan)

        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Gemini", result.stderr)

    def test_pre_push_new_branch_push_blocks_new_attribution_content(self):
        # All-zero remote SHA (new branch) must still be scanned, not skipped.
        env = self._prepare_attribution_repo()
        base = self._repo_commit("README.md", "# repo\n", "init")
        default_branch = self._repo_git("rev-parse", "--abbrev-ref", "HEAD")
        self._repo_git("update-ref", f"refs/remotes/origin/{default_branch}", base)
        self._repo_git("checkout", "-q", "-b", "brand-new")
        new_sha = self._repo_commit(
            "notes.py", attribution_line("Claude") + "print('hi')\n", "new work"
        )

        result = self._run_pre_push(
            env, push_plan_line("refs/heads/brand-new", new_sha, self._ZERO_SHA)
        )

        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Claude", result.stderr)

    def test_pre_push_new_branch_push_does_not_rescan_already_pushed_history(self):
        # Boundedness: a new branch has no remote SHA to diff from, so a naive
        # implementation walks back to the root commit and flags every historical
        # mention. The scan must stop at commits the remote already has.
        env = self._prepare_attribution_repo()
        self._repo_commit("README.md", "# repo\n", "init")
        published = self._repo_commit(
            "legacy.py",
            attribution_line("Gemini") + "print('legacy')\n",
            "historical mention",
        )
        default_branch = self._repo_git("rev-parse", "--abbrev-ref", "HEAD")
        self._repo_git("update-ref", f"refs/remotes/origin/{default_branch}", published)
        self._repo_git("checkout", "-q", "-b", "brand-new")
        new_sha = self._repo_commit("clean.py", "print('ok')\n", "clean work")

        result = self._run_pre_push(
            env, push_plan_line("refs/heads/brand-new", new_sha, self._ZERO_SHA)
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("Gemini", result.stderr)

    def test_pre_push_bounds_new_branch_push_by_the_named_remote(self):
        # The remote name comes from Git's first hook argument; bounding must use
        # it rather than a hard-coded `origin`. Here only `fork` has tracking
        # refs, so a hard-coded origin lookup would leave the scan unbounded and
        # flag the already-pushed historical mention.
        env = self._prepare_attribution_repo()
        self._repo_commit("README.md", "# repo\n", "init")
        published = self._repo_commit(
            "legacy.py",
            attribution_line("Gemini") + "print('legacy')\n",
            "historical mention",
        )
        default_branch = self._repo_git("rev-parse", "--abbrev-ref", "HEAD")
        self._repo_git("update-ref", f"refs/remotes/fork/{default_branch}", published)
        self._repo_git("checkout", "-q", "-b", "brand-new")
        clean = self._repo_commit("clean.py", "print('ok')\n", "clean work")

        clean_result = self._run_pre_push(
            env, push_plan_line("refs/heads/brand-new", clean, self._ZERO_SHA), remote="fork"
        )
        self.assertEqual(clean_result.returncode, 0, clean_result.stdout + clean_result.stderr)
        self.assertNotIn("Gemini", clean_result.stderr)

        flagged = self._repo_commit(
            "notes.py", attribution_line("Claude") + "print('hi')\n", "new work"
        )
        blocked = self._run_pre_push(
            env, push_plan_line("refs/heads/brand-new", flagged, self._ZERO_SHA), remote="fork"
        )
        self.assertNotEqual(blocked.returncode, 0, blocked.stdout + blocked.stderr)
        self.assertIn("Claude", blocked.stderr)

    def test_pre_push_force_push_scans_rewritten_commits(self):
        # A force-push's remote SHA is not an ancestor of the local SHA. The
        # rewritten commits are new objects entering the remote's history, so
        # they must be scanned.
        env = self._prepare_attribution_repo()
        base = self._repo_commit("README.md", "# repo\n", "init")
        default_branch = self._repo_git("rev-parse", "--abbrev-ref", "HEAD")
        published = self._repo_commit("notes.py", "print('hi')\n", "original work")
        self._repo_git("update-ref", f"refs/remotes/origin/{default_branch}", published)
        self._repo_git("reset", "-q", "--hard", base)
        rewritten = self._repo_commit(
            "notes.py",
            attribution_line("Claude") + "print('hi')\n",
            "rewritten work",
        )
        self.assertNotEqual(rewritten, published)

        result = self._run_pre_push(
            env, push_plan_line(f"refs/heads/{default_branch}", rewritten, published)
        )

        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Claude", result.stderr)

    def test_pre_push_fast_forward_push_scans_only_the_new_commits(self):
        # The ordinary case: remote SHA is an ancestor, so the scan covers the
        # commits being added and nothing already on the remote.
        env = self._prepare_attribution_repo()
        self._repo_commit("README.md", "# repo\n", "init")
        published = self._repo_commit(
            "legacy.py",
            attribution_line("Gemini") + "print('legacy')\n",
            "historical mention",
        )
        default_branch = self._repo_git("rev-parse", "--abbrev-ref", "HEAD")
        self._repo_git("update-ref", f"refs/remotes/origin/{default_branch}", published)
        added = self._repo_commit("notes.py", "print('hi')\n", "new work")

        result = self._run_pre_push(
            env, push_plan_line(f"refs/heads/{default_branch}", added, published)
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("Gemini", result.stderr)

    def test_pre_push_unresolvable_pushed_sha_lets_the_push_proceed(self):
        # Fail-open: a local SHA this repo cannot resolve (e.g. an alternate-object
        # or partial-clone oddity) cannot be evaluated, so the scan must skip it
        # rather than block. It must also NOT silently fall back to a
        # HEAD-relative range -- HEAD here carries content that would be flagged.
        env = self._prepare_attribution_repo()
        base = self._repo_commit("README.md", "# repo\n", "init")
        default_branch = self._repo_git("rev-parse", "--abbrev-ref", "HEAD")
        self._repo_git("update-ref", f"refs/remotes/origin/{default_branch}", base)
        self._repo_commit("notes.py", attribution_line("Claude") + "print('hi')\n", "work")

        result = self._run_pre_push(env, self._PUSH_STDIN)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_pre_push_delete_only_push_never_invokes_the_attribution_scan(self):
        # The delete-only short-circuit must still fire ahead of the scan: a
        # stand-in scanner rigged to fail must never run.
        marker = self.destination / "scanner-ran"
        env = self._prepare_attribution_repo(
            scanner_body=(
                "#!/usr/bin/env python3\n"
                "from pathlib import Path\n"
                f"Path({str(marker)!r}).write_text('ran')\n"
                "raise SystemExit(1)\n"
            )
        )
        self._repo_commit("README.md", "# repo\n", "init")

        result = self._run_pre_push(env, self._DELETE_STDIN)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(marker.exists())

    def test_pre_push_feeds_the_push_plan_to_the_attribution_scan(self):
        # The plan Git writes on stdin must reach the scanner intact -- both ref
        # updates and the remote name -- and stdin must survive being consumed by
        # the hook's own delete-only/refs_match_head loop.
        record = self.destination / "scanner-args"
        env = self._prepare_attribution_repo(
            scanner_body=(
                "#!/usr/bin/env python3\n"
                "import sys\n"
                "from pathlib import Path\n"
                f"Path({str(record)!r}).write_text(repr(sys.argv[1:]) + '\\n' + sys.stdin.read())\n"
            )
        )
        head = self._repo_commit("README.md", "# repo\n", "init")
        plan = push_plan_line("refs/heads/one", head, self._ZERO_SHA) + push_plan_line(
            "refs/heads/two", head, "2" * 40
        )

        result = self._run_pre_push(env, plan, remote="upstream")

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        recorded = record.read_text(encoding="utf-8")
        self.assertIn("upstream", recorded)
        self.assertIn(f"refs/heads/one {head} refs/heads/one {self._ZERO_SHA}", recorded)
        self.assertIn(f"refs/heads/two {head} refs/heads/two {'2' * 40}", recorded)

    def _justfiles_with_install_hooks(self):
        root = raven.REPO_ROOT
        candidates = [root / "justfile", *sorted(root.glob("*/justfile"))]
        return [
            p
            for p in candidates
            if p.is_file() and "install-hooks:" in p.read_text(encoding="utf-8")
        ]

    @staticmethod
    def _extract_recipe(text: str, name: str) -> str:
        # Capture the recipe header plus its indented body up to the first blank
        # line (the install-hooks body is a single shell block with no internal
        # blank lines).
        out: list[str] = []
        capturing = False
        for line in text.splitlines():
            if line.startswith(f"{name}:"):
                capturing = True
                out.append(line)
                continue
            if capturing:
                if line.strip() == "":
                    break
                out.append(line)
        return "\n".join(out)

    def test_install_hooks_recipe_honors_core_hooks_path(self):
        # The recipe must resolve Git's effective hooks dir (which honors
        # core.hooksPath) rather than hard-coding .git/hooks, so hooks land where
        # Git will actually run them. Guards all language justfiles against drift.
        justfiles = self._justfiles_with_install_hooks()
        self.assertGreaterEqual(len(justfiles), 8, [str(p) for p in justfiles])
        for jf in justfiles:
            recipe = self._extract_recipe(jf.read_text(encoding="utf-8"), "install-hooks")
            self.assertIn("git rev-parse --git-path hooks", recipe, str(jf))
            self.assertNotIn(".git/hooks/", recipe, f"{jf} still hard-codes .git/hooks/")

    def test_just_install_hooks_writes_into_custom_hooks_path(self):
        # End-to-end: with core.hooksPath set, `just install-hooks` must write the
        # hooks into that directory, not the ignored .git/hooks default.
        if shutil.which("just") is None:
            self.skipTest("just not installed")
        justfile = raven.REPO_ROOT / "python" / "justfile"
        (self.destination / "justfile").write_text(
            justfile.read_text(encoding="utf-8"), encoding="utf-8"
        )
        subprocess.run(
            ["git", "-C", str(self.destination), "config", "core.hooksPath", ".githooks"],
            capture_output=True,
            check=True,
        )

        result = subprocess.run(
            ["just", "install-hooks"],
            cwd=self.destination,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.destination / ".githooks" / "pre-commit").is_file())
        self.assertTrue((self.destination / ".githooks" / "pre-push").is_file())
        self.assertFalse((self.destination / ".git" / "hooks" / "pre-commit").exists())

    def _set_husky(self):
        (self.destination / ".husky" / "_").mkdir(parents=True)
        subprocess.run(
            ["git", "-C", str(self.destination), "config", "core.hooksPath", ".husky/_"],
            capture_output=True,
            check=True,
        )

    def test_detect_hook_manager_identifies_husky(self):
        self._set_husky()
        self.assertEqual(raven.detect_hook_manager(self.destination), "husky")

    def test_detect_hook_manager_none_for_normal_and_githooks(self):
        self.assertIsNone(raven.detect_hook_manager(self.destination))
        (self.destination / ".githooks").mkdir()
        subprocess.run(
            ["git", "-C", str(self.destination), "config", "core.hooksPath", ".githooks"],
            capture_output=True,
            check=True,
        )
        self.assertIsNone(raven.detect_hook_manager(self.destination))

    def test_install_skips_and_writes_nothing_under_husky(self):
        self._write_hook("pre-push", "#!/bin/sh\njust check\n")
        self._set_husky()

        installed = raven.install_git_hooks(self.destination)

        self.assertEqual(installed, [])
        self.assertFalse((self.destination / ".husky" / "_" / "pre-push").exists())

    def test_hook_manager_guidance_husky_names_husky_hooks(self):
        text = raven.hook_manager_guidance("husky")
        self.assertIn(".husky/pre-commit", text)
        self.assertIn(".husky/pre-push", text)

    def _set_husky_v5_v8(self):
        # husky install (v5-v8) sets core.hooksPath directly to .husky, not
        # .husky/_ (that wrapper subdirectory is a v9+ convention).
        (self.destination / ".husky").mkdir(parents=True)
        subprocess.run(
            ["git", "-C", str(self.destination), "config", "core.hooksPath", ".husky"],
            capture_output=True,
            check=True,
        )

    def test_detect_hook_manager_identifies_husky_v5_v8_direct_layout(self):
        self._set_husky_v5_v8()
        self.assertEqual(raven.detect_hook_manager(self.destination), "husky")

    def test_install_skips_and_writes_nothing_under_husky_v5_v8_direct_layout(self):
        self._write_hook("pre-push", "#!/bin/sh\njust check\n")
        self._set_husky_v5_v8()

        installed = raven.install_git_hooks(self.destination)

        self.assertEqual(installed, [])
        self.assertFalse((self.destination / ".husky" / "pre-push").exists())

    def test_install_creates_missing_nested_parent_for_in_repo_hooks_path(self):
        # An in-repo core.hooksPath whose parent directories do not exist yet
        # must not crash -- Raven should create them, same as it would for the
        # top-level hooks dir.
        subprocess.run(
            [
                "git",
                "-C",
                str(self.destination),
                "config",
                "core.hooksPath",
                "nested/missing/hooks",
            ],
            capture_output=True,
            check=True,
        )
        self._write_hook("commit-msg")

        installed = raven.install_git_hooks(self.destination)

        self.assertEqual(installed, ["commit-msg"])
        link = self.destination / "nested" / "missing" / "hooks" / "commit-msg"
        self.assertTrue(link.is_symlink())

    def test_install_skips_hooks_path_outside_repo(self):
        # A user-global core.hooksPath (e.g. set via --global) must not be
        # written into -- doing so would affect every repo using that path.
        global_hooks = self.destination.parent / "global-githooks"
        global_hooks.mkdir()
        self.addCleanup(shutil.rmtree, global_hooks, True)
        subprocess.run(
            ["git", "-C", str(self.destination), "config", "core.hooksPath", str(global_hooks)],
            capture_output=True,
            check=True,
        )
        self._write_hook("commit-msg")

        installed = raven.install_git_hooks(self.destination)

        self.assertEqual(installed, [])
        self.assertFalse((global_hooks / "commit-msg").exists())

    def test_install_does_not_crash_on_missing_global_hooks_path_parent(self):
        # Reproduces the reported crash: an absolute core.hooksPath whose
        # parent does not exist on disk must degrade gracefully, not traceback.
        missing_global_hooks = self.destination.parent / "does-not-exist-yet" / "githooks"
        self.addCleanup(shutil.rmtree, missing_global_hooks.parent, True)
        subprocess.run(
            [
                "git",
                "-C",
                str(self.destination),
                "config",
                "core.hooksPath",
                str(missing_global_hooks),
            ],
            capture_output=True,
            check=True,
        )
        self._write_hook("commit-msg")

        installed = raven.install_git_hooks(self.destination)

        self.assertEqual(installed, [])
        self.assertFalse(missing_global_hooks.exists())

    def test_detect_hook_manager_identifies_external_hooks_path(self):
        global_hooks = self.destination.parent / "global-githooks-detect"
        global_hooks.mkdir()
        self.addCleanup(shutil.rmtree, global_hooks, True)
        subprocess.run(
            ["git", "-C", str(self.destination), "config", "core.hooksPath", str(global_hooks)],
            capture_output=True,
            check=True,
        )

        self.assertEqual(raven.detect_hook_manager(self.destination), "external-hooks-path")

    def test_hook_manager_guidance_external_hooks_path_names_gate_commands(self):
        text = raven.hook_manager_guidance("external-hooks-path")
        self.assertIn("just check-fast", text)
        self.assertIn("just check", text)

    def test_git_hooks_dir_reports_actual_custom_path(self):
        custom_hooks = self.destination / ".githooks"
        custom_hooks.mkdir()
        subprocess.run(
            ["git", "-C", str(self.destination), "config", "core.hooksPath", ".githooks"],
            check=True,
        )

        self.assertEqual(raven.git_hooks_dir(self.destination), custom_hooks.resolve())

    def test_regular_file_warning_points_to_wiring(self):
        self._write_hook("pre-commit")
        existing = self.git_hooks_dir / "pre-commit"
        existing.write_text("#!/bin/sh\nmy own hook\n", encoding="utf-8")
        stderr = io.StringIO()

        with contextlib.redirect_stderr(stderr):
            installed = raven.install_git_hooks(self.destination)

        self.assertEqual(installed, [])
        msg = stderr.getvalue()
        self.assertIn("already exists as a regular file", msg)  # preserved substring
        self.assertIn("add `just check`", msg)  # no longer just "remove it"

    # -- shared with-verified-cache.sh script (crediting manual `just check` runs) --

    _CACHE_SCRIPT = "common/.raven/git-hooks/lib/with-verified-cache.sh"

    def _cache_script(self) -> Path:
        return raven.REPO_ROOT / self._CACHE_SCRIPT

    def test_cache_script_writes_stamp_when_head_resolves_and_tree_clean(self):
        # This is what a manual `just check` now runs on success -- it must
        # record HEAD exactly like the pre-push hook's own caching does.
        script = self._cache_script()
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
        stamp = self.destination / ".git" / "verified-check"
        self.assertFalse(stamp.exists())

        result = subprocess.run(
            ["/bin/sh", str(script), "check", "true"],
            cwd=self.destination,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(stamp.exists())
        self.assertEqual(stamp.read_text(encoding="utf-8").strip(), head)

    def test_cache_script_does_not_write_when_tree_dirty(self):
        # A cached pass must never vouch for uncommitted work -- same invariant
        # the pre-push hook itself enforces before writing.
        script = self._cache_script()
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
        (self.destination / "scratch.txt").write_text("dirty\n", encoding="utf-8")
        stamp = self.destination / ".git" / "verified-check"

        result = subprocess.run(
            ["/bin/sh", str(script), "check", "true"],
            cwd=self.destination,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(stamp.exists())

    def test_cache_script_does_not_write_without_a_resolvable_head(self):
        # An unborn HEAD (no commits yet) must not produce a stamp file.
        script = self._cache_script()
        stamp = self.destination / ".git" / "verified-check"

        result = subprocess.run(
            ["/bin/sh", str(script), "check", "true"],
            cwd=self.destination,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(stamp.exists())

    def test_cache_script_skips_and_reports_on_cache_hit(self):
        # A cache hit must not re-run the wrapped command, and should say so on
        # stderr so a skipped run is visible rather than silently identical to
        # a real one.
        script = self._cache_script()
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
        stamp = self.destination / ".git" / "verified-check"
        first = subprocess.run(
            ["/bin/sh", str(script), "check", "true"],
            cwd=self.destination,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertTrue(stamp.exists())

        second = subprocess.run(
            ["/bin/sh", str(script), "check", "sh", "-c", "exit 1"],
            cwd=self.destination,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertIn("skipping", second.stderr)

    def test_cache_script_force_always_runs_but_still_writes_stamp(self):
        # --force is what pre-push uses when refs_match_head=0: the cache must
        # never satisfy a skip, but a real success is still worth recording.
        script = self._cache_script()
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
        stamp = self.destination / ".git" / "verified-check"
        marker = self.destination / "ran.txt"

        subprocess.run(
            ["/bin/sh", str(script), "check", "true"],
            cwd=self.destination,
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertTrue(stamp.exists())

        result = subprocess.run(
            ["/bin/sh", str(script), "--force", "check", "sh", "-c", f"touch {marker}"],
            cwd=self.destination,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(marker.exists(), "the wrapped command must still run under --force")

    def test_pre_push_skips_after_manual_check_stamps_same_head(self):
        # The core new behavior: a manual `just check` run (simulated here by
        # invoking the shared cache script directly, exactly as the `check`
        # recipe now does on success) must earn the same push-time skip as a
        # run triggered by the hook itself.
        hook = raven.REPO_ROOT / "common" / ".raven" / "git-hooks" / "pre-push"
        env, head, stamp = self._prepare_verified_repo(just_exit=1)
        self.assertFalse(stamp.exists())

        manual_check = subprocess.run(
            ["/bin/sh", str(self._cache_script()), "check", "true"],
            cwd=self.destination,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(manual_check.returncode, 0, manual_check.stderr)
        self.assertTrue(stamp.exists())

        # `just` is rigged to exit 1 here -- if the hook actually invoked it,
        # this push would fail. A 0 means the hook trusted the manual stamp.
        push_result = subprocess.run(
            ["/bin/sh", str(hook)],
            cwd=self.destination,
            env=env,
            input=self._push_stdin(head),
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(push_result.returncode, 0, push_result.stderr)

    def test_check_recipes_call_shared_cache_script_not_check_fast(self):
        # Only the full-gate `check` target may credit the stamp; narrower
        # targets like `check-fast` must not, since they are not a full
        # verification pass.
        root = raven.REPO_ROOT
        candidates = [root / "justfile", *sorted(root.glob("*/justfile"))]
        justfiles = [
            p for p in candidates if p.is_file() and "check:" in p.read_text(encoding="utf-8")
        ]
        self.assertGreaterEqual(len(justfiles), 8, [str(p) for p in justfiles])
        for jf in justfiles:
            text = jf.read_text(encoding="utf-8")
            check_recipe = self._extract_recipe(text, "check")
            check_fast_recipe = self._extract_recipe(text, "check-fast")
            self.assertIn("with-verified-cache.sh", check_recipe, str(jf))
            self.assertNotIn("with-verified-cache.sh", check_fast_recipe, str(jf))

    def test_pre_push_comment_notes_stamp_may_originate_from_manual_run(self):
        pre_push = (raven.REPO_ROOT / "common" / ".raven" / "git-hooks" / "pre-push").read_text(
            encoding="utf-8"
        )
        self.assertIn("manual", pre_push.lower())


class HookManagerNoticeTests(unittest.TestCase):
    """What `install` and `upgrade` tell the user when a hook manager owns the hooks dir.

    Under husky or an out-of-repo `core.hooksPath`, Raven still writes
    `.raven/git-hooks/` but installs no symlinks, so nothing ever executes
    those scripts. The notice has to say that, on every run that reports what
    a template does -- including `--dry-run`, which is the run someone makes
    while deciding whether a hook fix is worth taking.
    """

    def setUp(self):
        # Git hooks export GIT_DIR/GIT_INDEX_FILE/etc. If this suite runs inside
        # a hook (the pre-commit `just check`), those would point git at the
        # outer repo instead of the temp repo below. Same guard as
        # GitHookInstallerTests.
        for var in [k for k in os.environ if k.startswith("GIT_")]:
            self.addCleanup(os.environ.__setitem__, var, os.environ[var])
            del os.environ[var]

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.destination = Path(self.tmp.name)
        subprocess.run(["git", "init", str(self.destination)], capture_output=True, check=True)
        (self.destination / ".husky" / "_").mkdir(parents=True)
        subprocess.run(
            ["git", "-C", str(self.destination), "config", "core.hooksPath", ".husky/_"],
            capture_output=True,
            check=True,
        )

    def _run_cmd(self, command, namespace) -> str:
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            rc = command(namespace)
        self.assertEqual(rc, 0, out.getvalue())
        return out.getvalue()

    def _install(self) -> str:
        return self._run_cmd(raven.cmd_install, install_ns(self.destination))

    def _assert_notice(self, output: str) -> None:
        self.assertIn("husky", output)
        self.assertIn(".raven/git-hooks", output)

    def test_guidance_husky_names_the_inert_vendored_hooks(self):
        text = raven.hook_manager_guidance("husky")
        self.assertIn(".raven/git-hooks", text)

    def test_guidance_external_hooks_path_names_the_inert_vendored_hooks(self):
        text = raven.hook_manager_guidance("external-hooks-path")
        self.assertIn(".raven/git-hooks", text)

    def test_install_reports_hook_manager(self):
        self._assert_notice(self._install())

    def test_install_dry_run_reports_hook_manager(self):
        self._assert_notice(
            self._run_cmd(raven.cmd_install, install_ns(self.destination, dry_run=True))
        )

    def test_upgrade_reports_hook_manager(self):
        self._install()
        self._assert_notice(self._run_cmd(raven.cmd_upgrade, upgrade_ns(self.destination)))

    def test_upgrade_dry_run_reports_hook_manager(self):
        self._install()
        self._assert_notice(
            self._run_cmd(raven.cmd_upgrade, upgrade_ns(self.destination, dry_run=True))
        )

    def test_no_notice_without_a_hook_manager(self):
        subprocess.run(
            ["git", "-C", str(self.destination), "config", "--unset", "core.hooksPath"],
            capture_output=True,
            check=True,
        )
        output = self._run_cmd(raven.cmd_install, install_ns(self.destination, dry_run=True))
        self.assertNotIn("Hook manager detected", output)


class HookLinkActionTests(unittest.TestCase):
    """The decision `install_git_hooks` makes for each hook path.

    This chooses when to unlink a file inside the user's `.git` directory, so
    every case is asserted directly rather than inferred from the handful of
    end-to-end installs above.
    """

    def test_nothing_present_is_created(self):
        self.assertIs(
            hook_link_action(
                exists=False, is_symlink=False, link_target=None, expected_target="../../x"
            ),
            HookLinkAction.CREATE,
        )

    def test_correct_symlink_is_left_alone(self):
        self.assertIs(
            hook_link_action(
                exists=True, is_symlink=True, link_target="../../x", expected_target="../../x"
            ),
            HookLinkAction.ALREADY_LINKED,
        )

    def test_symlink_to_the_wrong_target_is_replaced(self):
        self.assertIs(
            hook_link_action(
                exists=True, is_symlink=True, link_target="../../other", expected_target="../../x"
            ),
            HookLinkAction.REPLACE_SYMLINK,
        )

    def test_regular_file_is_never_touched(self):
        # Someone else's hook. Raven warns and leaves it; overwriting it would
        # silently discard hook logic the user wrote.
        self.assertIs(
            hook_link_action(
                exists=True, is_symlink=False, link_target=None, expected_target="../../x"
            ),
            HookLinkAction.LEAVE_REGULAR_FILE,
        )

    def test_broken_symlink_is_replaced_not_treated_as_empty(self):
        # `exists` follows symlinks, so a dangling link reports exists=False.
        # It must still be unlinked before the new one is created -- treating it
        # as an empty slot would make symlink_to fail with FileExistsError.
        self.assertIs(
            hook_link_action(
                exists=False, is_symlink=True, link_target="../../gone", expected_target="../../x"
            ),
            HookLinkAction.REPLACE_SYMLINK,
        )

    def test_broken_symlink_already_pointing_at_the_target_is_left_alone(self):
        # The source file may not exist yet at decision time; the link is still
        # spelled correctly, so there is nothing to do.
        self.assertIs(
            hook_link_action(
                exists=False, is_symlink=True, link_target="../../x", expected_target="../../x"
            ),
            HookLinkAction.ALREADY_LINKED,
        )


if __name__ == "__main__":
    unittest.main()
