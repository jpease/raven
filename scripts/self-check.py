#!/usr/bin/env python3

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RAVEN_SCRIPT = REPO_ROOT / "scripts" / "raven.py"


def run(label: str, args: list[str]) -> subprocess.CompletedProcess[str]:
    print(f"==> {label}")
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    result = subprocess.run(
        args,
        cwd=REPO_ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    print(result.stdout, end="")
    if result.returncode != 0:
        raise SystemExit(result.returncode)
    return result


def load_raven_module():
    scripts_dir = str(RAVEN_SCRIPT.parent)
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    import raven_lib

    return raven_lib


def validate_installed_shape() -> None:
    print("==> validate installed RAVEN shape")
    raven = load_raven_module()
    agents = REPO_ROOT / "AGENTS.md"
    claude = REPO_ROOT / "CLAUDE.md"
    claude_skills = REPO_ROOT / ".claude" / "skills"

    if not agents.is_file():
        raise SystemExit("AGENTS.md is missing")
    block = raven.find_raven_block(agents.read_text(encoding="utf-8"))
    if block is None:
        raise SystemExit("AGENTS.md is missing a RAVEN-managed block")
    if not raven.raven_block_is_unchanged(block):
        raise SystemExit("AGENTS.md RAVEN-managed block was edited directly")
    if not claude.is_symlink() or os.readlink(claude) != "AGENTS.md":
        raise SystemExit("CLAUDE.md must be a symlink to AGENTS.md")
    if not claude_skills.is_symlink() or os.readlink(claude_skills) != "../.agents/skills":
        raise SystemExit(".claude/skills must be a symlink to ../.agents/skills")
    print("installed shape ok")


def main() -> int:
    validate_installed_shape()
    run(
        "RAVEN self-upgrade dry run",
        [sys.executable, str(RAVEN_SCRIPT), "--destination", ".", "upgrade", "--dry-run"],
    )
    run(
        "RAVEN self-upgrade apply",
        [sys.executable, str(RAVEN_SCRIPT), "--destination", ".", "upgrade"],
    )
    validate_installed_shape()
    run("ruff format check", [sys.executable, "-m", "ruff", "format", "--check", "."])
    run("ruff lint", [sys.executable, "-m", "ruff", "check", "."])
    run("unit tests", [sys.executable, "-m", "unittest", "discover", "-s", "tests"])
    print("RAVEN self-check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
