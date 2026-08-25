"""Resolve Git's effective hooks directory and symlink Raven's git-hooks into it.

Detects when another hook manager (husky) or an external ``core.hooksPath`` owns
that directory and defers to it instead of installing -- Raven's hooks are then
written to ``.raven/git-hooks/`` but left unexecuted, with guidance printed on how
to wire them through the other manager.
"""

from __future__ import annotations

import os
import subprocess
import sys
from enum import Enum
from pathlib import Path

#: Filename of the shipped blanket-suppression checker under
#: ``.raven/git-hooks/lib/``, and the file extensions it has a detector for.
#: Deliberately a second copy of that script's own ``COVERED_SUFFIXES`` rather
#: than an import: the script ships into a destination repository, so reading
#: its table would mean importing destination code into the installer's own
#: process. ``test_doctor_copy_of_the_suffix_table_matches_the_shipped_one``
#: pins the two together, the same way the AI-attribution scanner's copied
#: patterns are pinned. `doctor.gate_relaxation_findings` is the only reader.
GATE_RELAXATION_SCRIPT = "check-gate-relaxation.py"
GATE_RELAXATION_SUFFIXES = (
    ".cts",
    ".ex",
    ".exs",
    ".go",
    ".js",
    ".jsx",
    ".lua",
    ".mts",
    ".py",
    ".pyi",
    ".rake",
    ".rb",
    ".rs",
    ".swift",
    ".ts",
    ".tsx",
)


def clean_git_env() -> dict[str, str]:
    """Environment with GIT_* removed.

    An inherited ``GIT_DIR``/``GIT_INDEX_FILE``/``GIT_WORK_TREE`` -- which git
    exports whenever it runs a hook -- takes precedence over ``git -C
    <destination>`` and would point discovery at the *outer* repository. Without
    this, ``install_git_hooks`` invoked from inside a hook (e.g. a pre-commit
    running the test suite) could install into the wrong repo's ``.git/hooks``.
    Stripping GIT_* makes the explicit ``destination`` authoritative.
    """
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def git_hooks_dir(destination: Path) -> Path | None:
    """Resolve Git's effective hooks directory for ``destination``.

    Honors ``core.hooksPath`` and the shared common Git directory used by linked
    worktrees, so callers inspect the same path Git itself uses. Returns ``None``
    when ``destination`` is not a usable Git repository.
    """
    hooks_dir, _ = _resolve_hooks_dir(destination)
    return hooks_dir


def _resolve_hooks_dir(destination: Path) -> tuple[Path | None, bool]:
    """Resolve the hooks dir and whether ``core.hooksPath`` escapes the repo.

    The second element is True only when an explicit ``core.hooksPath`` resolves
    outside the repo's toplevel (e.g. a user-global hooks dir) -- callers use this
    to avoid writing Raven's hooks where they would affect other repositories.
    """
    git_env = clean_git_env()
    try:
        # core.hooksPath overrides the default hooks location entirely.
        result = subprocess.run(
            ["git", "-C", str(destination), "config", "--get", "core.hooksPath"],
            capture_output=True,
            text=True,
            check=False,
            env=git_env,
        )
        if result.returncode == 0:
            hooks_path = result.stdout.strip()
            if hooks_path:
                # Git tilde-expands path-type config values; do the same, since an
                # unexpanded "~/..." is relative in Python's eyes and would
                # otherwise be joined onto the repo toplevel instead.
                p = Path(hooks_path).expanduser()
                toplevel_result = subprocess.run(
                    ["git", "-C", str(destination), "rev-parse", "--show-toplevel"],
                    capture_output=True,
                    text=True,
                    check=False,
                    env=git_env,
                )
                toplevel = (
                    Path(toplevel_result.stdout.strip()).resolve()
                    if toplevel_result.returncode == 0
                    else None
                )
                if not p.is_absolute():
                    if toplevel is None:
                        return None, False
                    p = toplevel / p
                resolved = p.resolve()
                outside_repo = toplevel is not None and not resolved.is_relative_to(toplevel)
                return resolved, outside_repo

        # Fall back to the common git directory, which is shared across linked worktrees.
        result = subprocess.run(
            ["git", "-C", str(destination), "rev-parse", "--git-common-dir"],
            capture_output=True,
            text=True,
            check=True,
            env=git_env,
        )
        git_common_dir = result.stdout.strip()
        hooks_dir = (destination / git_common_dir / "hooks").resolve()
        return (hooks_dir, False) if hooks_dir.parent.is_dir() else (None, False)
    except subprocess.CalledProcessError:
        return None, False


def _hooks_dir_manager(hooks_dir: Path) -> str | None:
    """Name of the hook manager that owns ``hooks_dir``, or None.

    Husky v9+ sets ``core.hooksPath`` to ``.husky/_``; husky v5-v8 (``husky
    install``) sets it to ``.husky`` directly. Either way that directory is
    husky's, not Raven's. This is the single seam where other managers can be
    recognized.
    """
    if hooks_dir.name == "_" and hooks_dir.parent.name == ".husky":
        return "husky"
    if hooks_dir.name == ".husky":
        return "husky"
    return None


def detect_hook_manager(destination: Path) -> str | None:
    """The hook manager owning ``destination``'s effective hooks dir, or None."""
    hooks_dir, outside_repo = _resolve_hooks_dir(destination)
    if hooks_dir is None:
        return None
    manager = _hooks_dir_manager(hooks_dir)
    if manager is not None:
        return manager
    return "external-hooks-path" if outside_repo else None


def hook_manager_guidance(manager: str) -> str:
    """Human guidance for wiring Raven's gate through ``manager``."""
    if manager == "husky":
        return (
            "Detected husky (core.hooksPath). Raven does not install its own git "
            "hooks under a hook manager, so the scripts in .raven/git-hooks/ are "
            "written and upgraded but never executed -- fixes landing there take "
            "effect only once something invokes them. To run Raven's gate, add "
            "`just check-fast` to .husky/pre-commit and `just check` to "
            ".husky/pre-push. Your hooks were left untouched."
        )
    if manager == "external-hooks-path":
        return (
            "core.hooksPath points outside this repository (a shared/global hooks "
            "directory). Raven does not install its own git hooks there, since "
            "that would affect every repository using that hooksPath. The scripts "
            "in .raven/git-hooks/ are still written and upgraded, but nothing "
            "executes them. To run Raven's gate, add `just check-fast` and `just "
            "check` to your hooks in that directory."
        )
    return ""


class HookLinkAction(str, Enum):
    """What to do about one hook path in the git hooks directory."""

    ALREADY_LINKED = "already-linked"
    LEAVE_REGULAR_FILE = "leave-regular-file"
    REPLACE_SYMLINK = "replace-symlink"
    CREATE = "create"


def hook_link_action(
    *,
    exists: bool,
    is_symlink: bool,
    link_target: str | None,
    expected_target: str,
) -> HookLinkAction:
    """Decide what to do about one hook path, given what is already there.

    Pure: the caller performs the filesystem queries and passes the answers in.
    The four cases are easy to get subtly wrong -- in particular ``exists``
    follows symlinks, so a *broken* symlink reports ``exists=False`` and must
    still be replaced rather than treated as an empty slot -- and this is code
    that unlinks files in the user's ``.git`` directory. Separating the decision
    from the mutation lets every case be asserted without creating one.
    """
    if is_symlink and link_target == expected_target:
        return HookLinkAction.ALREADY_LINKED
    if exists and not is_symlink:
        return HookLinkAction.LEAVE_REGULAR_FILE
    if is_symlink:
        return HookLinkAction.REPLACE_SYMLINK
    return HookLinkAction.CREATE


def install_git_hooks(destination: Path) -> list[str]:
    """Symlink .raven/git-hooks/* into the effective git hooks dir. Returns installed hook names."""
    git_hooks_src = destination / ".raven" / "git-hooks"
    if not git_hooks_src.is_dir():
        return []
    hooks_dir, outside_repo = _resolve_hooks_dir(destination)
    if hooks_dir is None:
        return []
    if outside_repo or _hooks_dir_manager(hooks_dir) is not None:
        # A hook manager (e.g. husky) owns this directory, or it lives outside
        # the repo (a user-global hooksPath); do not symlink into it.
        return []
    try:
        hooks_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print(
            f"warning: could not create hooks directory {hooks_dir}: {exc}. "
            "Git hooks were not installed.",
            file=sys.stderr,
        )
        return []
    installed: list[str] = []
    for hook_src in sorted(git_hooks_src.iterdir()):
        if hook_src.name.startswith(".") or not hook_src.is_file():
            continue
        hook_src.chmod(hook_src.stat().st_mode | 0o111)
        hook_link = hooks_dir / hook_src.name
        rel = os.path.relpath(hook_src, hooks_dir)
        is_symlink = hook_link.is_symlink()
        action = hook_link_action(
            exists=hook_link.exists(),
            is_symlink=is_symlink,
            link_target=os.readlink(hook_link) if is_symlink else None,
            expected_target=rel,
        )
        if action is HookLinkAction.ALREADY_LINKED:
            installed.append(hook_src.name)
            continue
        if action is HookLinkAction.LEAVE_REGULAR_FILE:
            print(
                f"warning: {hook_link} already exists as a regular file and was left "
                "untouched. To run Raven's gate, add `just check` / `just check-fast` "
                "to it, or remove it to let Raven manage the hook.",
                file=sys.stderr,
            )
            continue
        if action is HookLinkAction.REPLACE_SYMLINK:
            hook_link.unlink()
        hook_link.symlink_to(rel)
        installed.append(hook_src.name)
    return installed
