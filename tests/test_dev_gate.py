"""Tests for the root justfile's dev-environment gate: the `test` recipe's
launcher override (`PYTHON`/`RAVEN_PYTHON`) and its missing-test-runner
diagnostic (issue #168).

These invoke the real `just` binary against a copy of the root justfile in an
isolated temp directory (not `REPO_ROOT`). That is deliberate, not
incidental: this repo's ambient `python` can itself have pytest installed
(machine-dependent), and the `test` recipe's job -- both before and after a
fix -- is to run `python -m pytest` with no path argument. Run that with
`cwd=REPO_ROOT` from inside a test process and, on such a machine, it
collects and re-runs this entire suite, including this file, which invokes
`just test` again -- unbounded recursion, not a slow test. An isolated temp
directory has no `tests/` for pytest to discover, so even a justfile that
(pre-fix) ignores its launcher override entirely and always shells out to
pytest can only ever collect zero tests there.

These tests are gated by `HAVE_JUST` and are skipped wherever `just` is not
on `PATH`. CI installs `just` in the `checks` job (see
`.github/workflows/ci.yml`), so this coverage runs there too, not just
locally.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

from helpers import REPO_ROOT

HAVE_JUST = shutil.which("just") is not None

JUSTFILE = REPO_ROOT / "justfile"


class _IsolatedJustfileCase(unittest.TestCase):
    """Base: copies the real root justfile into an empty temp directory.

    `cwd` is that temp directory -- see the module docstring for why running
    `just test` there, rather than against `REPO_ROOT`, is load-bearing.
    """

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.workdir = Path(tmp.name)
        shutil.copy(JUSTFILE, self.workdir / "justfile")


@unittest.skipUnless(HAVE_JUST, "just not installed")
class MissingTestRunnerDiagnosticTest(_IsolatedJustfileCase):
    def test_nonexistent_launcher_fails_with_bootstrap_message_not_traceback(self) -> None:
        # A launcher override that does not resolve to a real interpreter must
        # be caught by a probe before `just test` ever tries to run pytest
        # under it -- otherwise the failure surfaces as a raw
        # FileNotFoundError/traceback instead of an actionable message.
        env = dict(os.environ)
        env["RAVEN_PYTHON"] = "/nonexistent/python"
        result = subprocess.run(
            ["just", "test"],
            cwd=self.workdir,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        combined = result.stdout + result.stderr
        self.assertNotEqual(result.returncode, 0, combined)
        self.assertNotIn("Traceback", combined)
        self.assertNotIn("ModuleNotFoundError", combined)
        # The message must name the precise bootstrap command, not just say
        # "pytest missing".
        self.assertIn("uv sync", combined)
        self.assertIn("just test", combined)
        # ...and the override form's own bootstrap, for contributors not on uv.
        self.assertIn("pip install --group dev", combined)

    def test_absent_uv_points_at_the_uv_installer_not_at_uv_sync(self) -> None:
        # The fresh-clone case the issue is really about: with no `uv` on PATH,
        # naming `uv sync` as the bootstrap hands the contributor a second
        # `command not found`, so the message must name installing uv instead.
        just = shutil.which("just")
        assert just is not None  # guarded by skipUnless
        env = dict(os.environ)
        env["PATH"] = "/usr/bin:/bin"
        env["RAVEN_PYTHON"] = "/nonexistent/python"
        result = subprocess.run(
            [just, "test"],
            cwd=self.workdir,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        combined = result.stdout + result.stderr
        self.assertNotEqual(result.returncode, 0, combined)
        self.assertNotIn("Traceback", combined)
        self.assertIn("docs.astral.sh/uv", combined)
        self.assertNotIn("uv sync", combined)


@unittest.skipUnless(HAVE_JUST, "just not installed")
class LauncherOverrideTest(_IsolatedJustfileCase):
    """`RAVEN_PYTHON`/`PYTHON` must actually be honored by the `test` recipe.

    Uses a fake `python` shim rather than a real interpreter: even in the
    isolated workdir, a real launcher running real pytest with no path
    argument would fall back to collecting from its own cwd, which is not
    what this test is checking. The shim proves the recipe actually invokes
    the configured launcher's `-m pytest`, nothing more.
    """

    def setUp(self) -> None:
        super().setUp()
        shim = self.workdir / "fake-python"
        shim.write_text(
            "#!/usr/bin/env sh\n"
            "if [ \"$1\" = '-c' ]; then\n"
            "    exit 0\n"
            "fi\n"
            "if [ \"$1\" = '-m' ] && [ \"$2\" = 'pytest' ]; then\n"
            "    echo FAKE_PYTEST_RAN\n"
            "    exit 0\n"
            "fi\n"
            "exit 1\n",
            encoding="utf-8",
        )
        shim.chmod(shim.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
        self.shim = shim

    def test_raven_python_env_override_is_used(self) -> None:
        env = dict(os.environ)
        env["RAVEN_PYTHON"] = str(self.shim)
        result = subprocess.run(
            ["just", "test"],
            cwd=self.workdir,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("FAKE_PYTEST_RAN", result.stdout)

    def test_python_just_variable_override_is_used(self) -> None:
        # The per-invocation override form: `just PYTHON='...' test`.
        result = subprocess.run(
            ["just", f"PYTHON={self.shim}", "test"],
            cwd=self.workdir,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("FAKE_PYTEST_RAN", result.stdout)


@unittest.skipUnless(HAVE_JUST, "just not installed")
class DefaultLauncherTest(_IsolatedJustfileCase):
    def test_default_python_variable_uses_uv_dev_group(self) -> None:
        # `--evaluate` only resolves the variable's text; it does not execute
        # the recipe, so this is safe against a real `uv`/`python` on PATH
        # regardless of workdir.
        result = subprocess.run(
            ["just", "--evaluate", "PYTHON"],
            cwd=self.workdir,
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertEqual(result.stdout.strip(), "uv run --group dev python")


@unittest.skipUnless(HAVE_JUST, "just not installed")
class ArgvIndirectionSecurityTest(_IsolatedJustfileCase):
    """Regression test for #182.

    `{{PYTHON}}` interpolation happens before the shell ever parses the
    recipe body's text, so a `PYTHON`/`RAVEN_PYTHON` value containing shell
    metacharacters (`;`, an embedded `"`, ...) used to become live shell
    syntax instead of inert data. The fix routes the value through `just`'s
    `set positional-arguments` plus a recipe-dependency parameter (`test:
    (_test PYTHON)`), so it reaches the shell only as an opaque argv string
    ($1), never as re-parsed shell text -- while unquoted `$1` expansion
    still word-splits a legitimate multi-word value (like the default `uv
    run --group dev python`) into separate argv entries.
    """

    def test_shell_metacharacters_in_raven_python_are_not_executed(self) -> None:
        # The issue's own repro: if this value were ever re-parsed as shell
        # text, `touch INJECTED` would run as a separate command after the
        # (deliberately empty) `python3 -c ""`.
        env = dict(os.environ)
        env["RAVEN_PYTHON"] = 'python3 -c "" ; touch INJECTED ; true'
        result = subprocess.run(
            ["just", "test"],
            cwd=self.workdir,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        combined = result.stdout + result.stderr
        # The load-bearing assertion: no injected command ever ran.
        self.assertFalse((self.workdir / "INJECTED").exists(), combined)
        self.assertNotIn("Traceback", combined)
        # Note: the exit code itself is deliberately NOT asserted here.
        # Word-splitting this value gives `python3 -c "" ; touch INJECTED ;
        # true -c 'import pytest'`: real `python3`'s own `-c` option
        # consumes the very next token (the literal two-character string
        # `""`) as its program and exits 0, treating everything after
        # (including the later literal `-c 'import pytest'`) as inert
        # `sys.argv` -- never re-invoked as more flags. So this particular
        # payload happens to make both the probe and the real run exit 0
        # without ever executing `import pytest` or `-m pytest` for real.
        # That is a quirk of `python3 -c ""` being a trivially valid no-op,
        # not a sign that shell metacharacters were reinterpreted -- the
        # security property under test is `;`/`touch INJECTED` never
        # running as shell syntax, which the assertion above covers.

    def test_multiword_launcher_value_still_splits_into_argv(self) -> None:
        # Positive control: the fix must not break the legitimate
        # multi-word case it exists to preserve. A shim invoked as
        # "<shim> extra-word" must receive "extra-word" as its own argv
        # entry ($1 inside the shim), proving word-splitting still works
        # end-to-end after routing PYTHON through positional-arguments.
        shim = self.workdir / "fake-python"
        shim.write_text(
            "#!/usr/bin/env sh\n"
            "if [ \"$1\" = 'extra-word' ] && [ \"$2\" = '-c' ]; then\n"
            "    exit 0\n"
            "fi\n"
            "if [ \"$1\" = 'extra-word' ] && [ \"$2\" = '-m' ] && [ \"$3\" = 'pytest' ]; then\n"
            "    echo FAKE_PYTEST_RAN\n"
            "    exit 0\n"
            "fi\n"
            "exit 1\n",
            encoding="utf-8",
        )
        shim.chmod(shim.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
        env = dict(os.environ)
        env["RAVEN_PYTHON"] = f"{shim} extra-word"
        result = subprocess.run(
            ["just", "test"],
            cwd=self.workdir,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("FAKE_PYTEST_RAN", result.stdout)


if __name__ == "__main__":
    unittest.main()
