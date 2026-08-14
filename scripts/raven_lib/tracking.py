"""Report merge-only paths that git does not track.

Raven merges ``MERGE_ONLY_TEMPLATE_PATHS`` into files it does not own rather
than installing them as managed template entries, so they are deliberately
absent from ``manifest.json`` -- the right ownership call (#206), since most
destinations already keep their own ``.gitattributes`` for unrelated reasons.

The side effect is that no manifest-driven listing, diff, or convergence check
mentions them, and git honors a working-tree ``.gitattributes`` whether or not
it is tracked. A merge-only path can therefore stay untracked indefinitely with
no local symptom of any kind: every rule applies in the tree that generated it
and in no other clone (#216). That inverts the point of the ``eol=lf`` rules,
which exist to protect a *Windows* checkout -- necessarily a different clone
from the one where Raven wrote the file.

This module only reports. Staging into a user's index is not Raven's call.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from .constants import MERGE_ONLY_TEMPLATE_PATHS
from .git_hooks import clean_git_env


def _git(destination: Path, *args: str) -> subprocess.CompletedProcess:
    """Run one read-only git query against ``destination``.

    Uses ``clean_git_env`` for the same reason ``git_hooks`` does: an inherited
    ``GIT_DIR``/``GIT_WORK_TREE`` -- exported by git whenever it runs a hook --
    outranks ``git -C`` and would answer for the *outer* repository. Raven's own
    pre-commit hook runs the test suite, so that is a reachable path here, not a
    hypothetical one.
    """
    return subprocess.run(
        ["git", "-C", str(destination), *args],
        capture_output=True,
        text=True,
        check=False,
        env=clean_git_env(),
    )


def _has_work_tree(destination: Path) -> bool:
    """Whether ``destination`` is inside a git work tree.

    False for a plain directory (Raven installs into those too) and for a bare
    repository, where no working-tree file can be untracked in the first place.
    """
    result = _git(destination, "rev-parse", "--is-inside-work-tree")
    return result.returncode == 0 and result.stdout.strip() == "true"


def untracked_merge_only_paths(destination: Path) -> list[str]:
    """Merge-only paths present on disk that git does not track, sorted.

    Empty -- never a finding -- when git is unavailable, when ``destination`` is
    not a work tree, or when the path is deliberately gitignored. Each of those
    is a legitimate state a user chose or an environment Raven cannot inspect,
    and reporting them would make the check noise rather than signal.
    """
    try:
        if not _has_work_tree(destination):
            return []
        untracked = []
        for relative in sorted(MERGE_ONLY_TEMPLATE_PATHS):
            if not (destination / relative).is_file():
                continue
            if _git(destination, "ls-files", "--error-unmatch", "--", relative).returncode == 0:
                continue
            if _git(destination, "check-ignore", "-q", "--", relative).returncode == 0:
                continue
            untracked.append(relative)
        return untracked
    except OSError:
        # No git binary on PATH. Raven does not require one, and a missing tool
        # is the toolchain check's business, not this check's.
        return []
