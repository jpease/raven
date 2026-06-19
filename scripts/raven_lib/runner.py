from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


@dataclass(frozen=True)
class RunResult:
    ok: bool
    code: int
    stdout: str
    stderr: str
    found: bool
    timed_out: bool


def run_command(command: list[str], cwd: Path, timeout: int = 120) -> RunResult:
    executable = shutil.which(command[0])
    if executable is None:
        return RunResult(ok=False, code=127, stdout="", stderr="", found=False, timed_out=False)
    try:
        completed = subprocess.run(
            [executable, *command[1:]],
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return RunResult(ok=False, code=124, stdout="", stderr="", found=True, timed_out=True)
    return RunResult(
        ok=completed.returncode == 0,
        code=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
        found=True,
        timed_out=False,
    )


Runner = Callable[[list[str], Path], RunResult]
