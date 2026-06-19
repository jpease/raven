from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path


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
            capture_output=True,
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

# Short budget for `tool --version` style availability probes.
PROBE_TIMEOUT_SECONDS = 15
# Generous budget for executing real quality gates (test suites, builds).
GATE_TIMEOUT_SECONDS = 600


def make_runner(timeout: int) -> Runner:
    """Build a Runner that invokes run_command with a fixed timeout."""

    def runner(command: list[str], cwd: Path) -> RunResult:
        return run_command(command, cwd, timeout=timeout)

    return runner


probe_runner = make_runner(PROBE_TIMEOUT_SECONDS)
gate_runner = make_runner(GATE_TIMEOUT_SECONDS)
