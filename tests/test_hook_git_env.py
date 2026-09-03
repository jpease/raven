"""The shipped hooks must not pass git's exported environment down to the gate.

Git sets `GIT_DIR` (and friends) for every hook it runs. Neither `git -C <dir>`
nor `cd` overrides an exported `GIT_DIR`, so anything the hook invokes inherits
a pointer at the real repository. A gate whose test suite builds throwaway git
fixtures then has its `git -C "$sandbox" config user.email ...` land in the real
`.git/config`. Observed downstream as ~50 commits authored by a fixture identity
with commit signing silently disabled, and durable: a linked worktree shares the
same config file.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import unittest
from pathlib import Path

from helpers import REPO_ROOT, RavenTestCase

HOOKS_SRC = REPO_ROOT / "common" / ".raven" / "git-hooks"
_GUARDED = ("pre-commit", "pre-push")
_VARS = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_COMMON_DIR",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
)


class GuardPresenceTests(unittest.TestCase):
    def test_both_gate_hooks_unset_the_inherited_git_environment(self):
        for name in _GUARDED:
            text = (HOOKS_SRC / name).read_text(encoding="utf-8")
            with self.subTest(hook=name):
                for var in _VARS:
                    self.assertIn(var, text, f"{name} does not unset {var}")

    def test_the_unset_precedes_the_first_git_invocation(self):
        # Unsetting after the hook has already shelled out to git would leave
        # that first call redirected, which is the whole failure mode.
        for name in _GUARDED:
            text = (HOOKS_SRC / name).read_text(encoding="utf-8")
            lines = [ln for ln in text.splitlines() if not ln.strip().startswith("#")]
            unset_at = next(i for i, ln in enumerate(lines) if ln.startswith("unset GIT_DIR"))
            git_at = next(
                (i for i, ln in enumerate(lines) if "git " in ln and not ln.startswith("unset")),
                len(lines),
            )
            with self.subTest(hook=name):
                self.assertLess(unset_at, git_at, f"{name} calls git before unsetting GIT_DIR")


@unittest.skipUnless(shutil.which("git"), "git is required")
class PoisonedEnvironmentTests(RavenTestCase):
    """End-to-end: a poisoned GIT_DIR must not reach the gate the hook runs."""

    def _run_hook(self, name: str, extra_env: dict) -> str:
        repo = self.destination
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        (repo / "justfile").write_text("check-fast:\n    @true\n", encoding="utf-8")

        bin_dir = Path(self.destination).parent / "bin"
        bin_dir.mkdir(exist_ok=True)
        seen = bin_dir / "seen.txt"
        # A fake `just` that records whatever git environment reached it.
        (bin_dir / "just").write_text(
            f'#!/bin/sh\nprintf "GIT_DIR=[%s]\\n" "${{GIT_DIR-}}" > {seen}\nexit 0\n',
            encoding="utf-8",
        )
        (bin_dir / "just").chmod(0o755)

        hook = repo / "hook"
        hook.write_text((HOOKS_SRC / name).read_text(encoding="utf-8"), encoding="utf-8")
        hook.chmod(0o755)

        env = {k: v for k, v in os.environ.items() if k != "PATH"}
        env["PATH"] = os.pathsep.join([str(bin_dir), "/usr/bin", "/bin"])
        env.update(extra_env)
        subprocess.run(
            ["sh", str(hook)],
            cwd=repo,
            env=env,
            input="",
            capture_output=True,
            text=True,
            check=False,
        )
        return seen.read_text(encoding="utf-8") if seen.exists() else ""

    def test_pre_commit_does_not_forward_a_poisoned_git_dir(self):
        decoy = str(Path(self.destination).parent / "someone-elses.git")
        observed = self._run_hook("pre-commit", {"GIT_DIR": decoy})
        self.assertIn("GIT_DIR=[]", observed, f"gate saw a git environment: {observed!r}")
