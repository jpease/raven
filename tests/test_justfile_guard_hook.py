"""Issue #225 -- the `just` gates must skip when the repo ships no justfile.

`dotfiles` and `generic` deliberately ship no justfile. The hooks used to guard
their gate on `command -v just` alone, so on a machine that has `just` installed
`just check-fast` failed with "error: no justfile found" and the hook turned
that into a refused commit -- every commit, in every such install.

These tests drive a real `git commit` and a real `git push` rather than calling
the hook script directly: the guard sits inside the hook, and a test that runs
the script by hand cannot tell a blocked commit from a passing one. `just` is
stubbed so the result depends on the guard rather than on what the test machine
happens to have installed, and PATH is narrowed so an installed `gitleaks` (a
later, unrelated step in pre-commit) cannot influence the outcome.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from helpers import REPO_ROOT

HOOKS_SRC = REPO_ROOT / "common" / ".raven" / "git-hooks"

# Narrow PATH: the stub dir plus the system locations holding git. Anything the
# developer's machine installs elsewhere (gitleaks, a real just) stays invisible.
_SYSTEM_PATH = "/usr/bin:/bin:/usr/sbin:/sbin"


class JustfileGuardHookTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)

        # The stub records every invocation and fails, standing in for the real
        # `just check-fast` / `just check`. If the guard lets it run, the hook
        # refuses the operation and the log file exists. Built before the repo,
        # since _git() resolves `just` through the PATH set up here.
        self.stub_dir = root / "bin"
        self.stub_dir.mkdir()
        self.just_log = root / "just-invocations.log"
        stub = self.stub_dir / "just"
        stub.write_text(
            f"#!/usr/bin/env sh\nprintf \"%s\\n\" \"$*\" >> \"{self.just_log}\"\nexit 1\n",
            encoding="utf-8",
        )
        stub.chmod(0o755)

        self.repo = root / "repo"
        self.repo.mkdir()
        self.remote = root / "remote.git"
        subprocess.run(["git", "init", "-q", "--bare", str(self.remote)], check=True)
        self._git("init", "-q", ".")
        self._git("remote", "add", "origin", str(self.remote))

        hooks_dir = self.repo / ".git" / "hooks"
        hooks_dir.mkdir(parents=True, exist_ok=True)
        for name in ("pre-commit", "pre-push"):
            installed = hooks_dir / name
            shutil.copy2(HOOKS_SRC / name, installed)
            installed.chmod(0o755)

    def _env(self) -> dict[str, str]:
        return {
            "PATH": f"{self.stub_dir}:{_SYSTEM_PATH}",
            "HOME": self.tmp.name,
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@example.com",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@example.com",
        }

    def _git(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", *args],
            cwd=str(self.repo),
            capture_output=True,
            text=True,
            env=self._env(),
        )

    def _just_ran(self) -> bool:
        return self.just_log.exists()

    def _stage_a_page(self, name: str = "index.html") -> None:
        (self.repo / name).write_text("<!doctype html>\n<title>hi</title>\n", encoding="utf-8")
        self._git("add", "--", name)

    def _add_justfile(self) -> None:
        (self.repo / "justfile").write_text(
            "check-fast:\n    @true\n\ncheck:\n    @true\n", encoding="utf-8"
        )
        self._git("add", "--", "justfile")

    def _commit_count(self) -> int:
        result = self._git("rev-list", "--count", "HEAD")
        return int(result.stdout.strip()) if result.returncode == 0 else 0

    # --- pre-commit -------------------------------------------------------

    def test_commit_succeeds_with_no_justfile(self):
        self._stage_a_page()
        result = self._git("commit", "-m", "feat: add a page")
        self.assertEqual(
            result.returncode,
            0,
            f"commit was refused in a justfile-less repo:\n{result.stdout}\n{result.stderr}",
        )
        self.assertEqual(self._commit_count(), 1)
        self.assertFalse(self._just_ran(), "the gate ran despite there being no justfile")

    def test_commit_still_gated_when_a_justfile_exists(self):
        # The guard must not become a blanket skip: with a justfile present the
        # failing gate still blocks the commit.
        self._add_justfile()
        self._stage_a_page()
        result = self._git("commit", "-m", "feat: add a page")
        self.assertNotEqual(result.returncode, 0, "a failing gate should block the commit")
        self.assertEqual(self._commit_count(), 0)
        self.assertTrue(self._just_ran(), "the gate did not run despite a justfile being present")
        self.assertIn("check-fast", self.just_log.read_text(encoding="utf-8"))

    def test_commit_gated_when_just_justfile_points_elsewhere(self):
        # `just` resolves JUST_JUSTFILE ahead of the working directory, so the
        # guard honors it rather than reporting "no justfile" for a real setup.
        external = Path(self.tmp.name) / "external-justfile"
        external.write_text("check-fast:\n    @true\n", encoding="utf-8")
        self._stage_a_page()
        result = subprocess.run(
            ["git", "commit", "-m", "feat: add a page"],
            cwd=str(self.repo),
            capture_output=True,
            text=True,
            env={**self._env(), "JUST_JUSTFILE": str(external)},
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(self._just_ran(), "JUST_JUSTFILE was ignored by the guard")

    # --- pre-push ---------------------------------------------------------

    def test_push_succeeds_with_no_justfile(self):
        self._stage_a_page()
        commit = self._git("commit", "-m", "feat: add a page")
        self.assertEqual(commit.returncode, 0, commit.stderr)

        branch = self._git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
        result = self._git("push", "-q", "origin", branch)
        self.assertEqual(
            result.returncode,
            0,
            f"push was refused in a justfile-less repo:\n{result.stdout}\n{result.stderr}",
        )
        self.assertFalse(self._just_ran(), "the gate ran despite there being no justfile")

    def test_push_still_gated_when_a_justfile_exists(self):
        self._add_justfile()
        self._stage_a_page()
        commit = self._git("commit", "-m", "feat: add a page", "--no-verify")
        self.assertEqual(commit.returncode, 0, commit.stderr)

        branch = self._git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
        result = self._git("push", "-q", "origin", branch)
        self.assertNotEqual(result.returncode, 0, "a failing gate should block the push")
        self.assertTrue(self._just_ran(), "the gate did not run despite a justfile being present")
        self.assertIn("check", self.just_log.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
