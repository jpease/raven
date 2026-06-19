from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def _git_hooks_dir(destination: Path) -> Path | None:
    try:
        # core.hooksPath overrides the default hooks location entirely.
        result = subprocess.run(
            ["git", "-C", str(destination), "config", "--get", "core.hooksPath"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            hooks_path = result.stdout.strip()
            if hooks_path:
                p = Path(hooks_path)
                if not p.is_absolute():
                    toplevel = subprocess.run(
                        ["git", "-C", str(destination), "rev-parse", "--show-toplevel"],
                        capture_output=True,
                        text=True,
                        check=True,
                    ).stdout.strip()
                    p = Path(toplevel) / p
                return p.resolve()

        # Fall back to the common git directory, which is shared across linked worktrees.
        result = subprocess.run(
            ["git", "-C", str(destination), "rev-parse", "--git-common-dir"],
            capture_output=True,
            text=True,
            check=True,
        )
        git_common_dir = result.stdout.strip()
        hooks_dir = (destination / git_common_dir / "hooks").resolve()
        return hooks_dir if hooks_dir.parent.is_dir() else None
    except subprocess.CalledProcessError:
        return None


def install_git_hooks(destination: Path) -> list[str]:
    """Symlink .raven/git-hooks/* into .git/hooks/. Returns installed hook names."""
    git_hooks_src = destination / ".raven" / "git-hooks"
    if not git_hooks_src.is_dir():
        return []
    hooks_dir = _git_hooks_dir(destination)
    if hooks_dir is None:
        return []
    hooks_dir.mkdir(exist_ok=True)
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
                f"warning: .git/hooks/{hook_src.name} already exists as a regular file; "
                "remove it to let Raven manage it.",
                file=sys.stderr,
            )
            continue
        if hook_link.is_symlink():
            hook_link.unlink()
        hook_link.symlink_to(rel)
        installed.append(hook_src.name)
    return installed
