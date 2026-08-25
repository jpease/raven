"""Session-wide test isolation shared by every test module.

`raven_lib.fleet.raven_home` honors ``RAVEN_HOME`` to redirect Raven's
user-level state -- currently just the fleet registry, ``repos.json`` -- away
from the real ``~/.raven``. Only `tests/test_fleet.py` pinned it locally; any
other module that drives a real `cmd_install` or `cmd_upgrade` against a
throwaway destination registered that throwaway path into the developer's
actual registry on every test run (#240). Pin it here, once, for the whole
suite, so a module added later inherits the isolation instead of having to
remember it. A module (like `test_fleet.py`) that needs its own dedicated
temp directory per test still layers its own `RAVEN_HOME` override on top of
this one; nothing here should be removed to do that.
"""

from __future__ import annotations

import os
import tempfile
from unittest import mock

import pytest


@pytest.fixture(autouse=True, scope="session")
def _pin_raven_home_for_the_whole_suite():
    with tempfile.TemporaryDirectory() as home, mock.patch.dict(os.environ, {"RAVEN_HOME": home}):
        yield
