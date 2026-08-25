"""Regression coverage for #240: the suite must never touch the real fleet registry.

Every other fleet test (`test_fleet.py`) pins `RAVEN_HOME` itself, which would
mask a regression in the suite-wide pin `conftest.py` provides -- the whole
point of that pin is to cover modules that install for reasons unrelated to
fleet and never think to override it. This test deliberately does *not* set
`RAVEN_HOME` locally, so it only passes if the session-wide autouse fixture in
`conftest.py` is doing its job.
"""

from __future__ import annotations

import contextlib
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from helpers import install_ns, raven


class RealFleetRegistryUntouchedTests(unittest.TestCase):
    def test_a_real_install_never_writes_the_developers_actual_registry(self):
        # Resolve the real path the same way raven_lib.fleet.raven_home does
        # when RAVEN_HOME is unset, without importing fleet or relying on it
        # to prove its own fix.
        real_registry = Path(os.path.expanduser("~")) / ".raven" / "repos.json"
        before = real_registry.read_bytes() if real_registry.exists() else None

        with tempfile.TemporaryDirectory() as destination:
            with (
                contextlib.redirect_stdout(io.StringIO()),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                rc = raven.cmd_install(install_ns(Path(destination)))
            self.assertEqual(rc, 0)

        after = real_registry.read_bytes() if real_registry.exists() else None
        self.assertEqual(
            before,
            after,
            "a real cmd_install wrote to the developer's actual ~/.raven/repos.json",
        )


if __name__ == "__main__":
    unittest.main()
