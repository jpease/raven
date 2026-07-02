from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def _clean_git_env() -> dict[str, str]:
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
    git_env = _clean_git_env()
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
            "hooks under a hook manager. To run Raven's gate, add `just check-fast` "
            "to .husky/pre-commit and `just check` to .husky/pre-push. Your hooks "
            "were left untouched."
        )
    if manager == "external-hooks-path":
        return (
            "core.hooksPath points outside this repository (a shared/global hooks "
            "directory). Raven does not install its own git hooks there, since "
            "that would affect every repository using that hooksPath. To run "
            "Raven's gate, add `just check-fast` and `just check` to your hooks "
            "in that directory."
        )
    return ""


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
        if hook_link.is_symlink() and os.readlink(hook_link) == rel:
            installed.append(hook_src.name)
            continue
        if hook_link.exists() and not hook_link.is_symlink():
            print(
                f"warning: {hook_link} already exists as a regular file and was left "
                "untouched. To run Raven's gate, add `just check` / `just check-fast` "
                "to it, or remove it to let Raven manage the hook.",
                file=sys.stderr,
            )
            continue
        if hook_link.is_symlink():
            hook_link.unlink()
        hook_link.symlink_to(rel)
        installed.append(hook_src.name)
    return installed
