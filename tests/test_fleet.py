"""Tests for the fleet registry and `raven fleet`.

Every test pins ``RAVEN_HOME`` at a temporary directory. Reading or writing the
developer's real ``~/.raven/repos.json`` from a test run would both corrupt
their fleet view and make these assertions depend on it.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from raven_lib import fleet
from raven_lib.cli import cmd_fleet
from raven_lib.findings import Severity


class FleetTestCase(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.TemporaryDirectory()
        self.addCleanup(self.home.cleanup)
        self.repos = tempfile.TemporaryDirectory()
        self.addCleanup(self.repos.cleanup)
        patcher = mock.patch.dict(os.environ, {"RAVEN_HOME": self.home.name})
        patcher.start()
        self.addCleanup(patcher.stop)

    def _repo(self, name: str, *, template="python", version="abc123def456"):
        """A directory that looks enough like a Raven install for fleet to read."""
        path = Path(self.repos.name) / name
        (path / ".raven").mkdir(parents=True)
        (path / ".raven" / "config.toml").write_text(
            f'schema = 1\ntemplate = "{template}"\n', encoding="utf-8"
        )
        (path / ".raven" / "manifest.json").write_text(
            json.dumps({"schema": 1, "files": {}, "template": template, "ravenVersion": version}),
            encoding="utf-8",
        )
        return path

    def _findings(self):
        return fleet.build_fleet_findings()

    def _severity_for(self, substring):
        matches = [f for f in self._findings() if substring in f.title]
        self.assertEqual(len(matches), 1, f"expected exactly one finding naming {substring!r}")
        return matches[0].severity


class RegistryTests(FleetTestCase):
    def test_an_absent_registry_reads_as_empty(self):
        self.assertEqual(fleet.load_registry(), [])

    def test_register_then_load_round_trips(self):
        repo = self._repo("a")
        self.assertTrue(fleet.register(repo))
        self.assertEqual(fleet.load_registry(), [repo.resolve()])

    def test_registering_twice_is_a_no_op(self):
        repo = self._repo("a")
        fleet.register(repo)
        self.assertFalse(fleet.register(repo), "a second register should report no change")
        self.assertEqual(len(fleet.load_registry()), 1)

    def test_a_corrupt_registry_reads_as_empty_rather_than_raising(self):
        # A convenience file must never break the command that writes it.
        fleet.registry_path().parent.mkdir(parents=True, exist_ok=True)
        fleet.registry_path().write_text("{not json", encoding="utf-8")
        self.assertEqual(fleet.load_registry(), [])

    def test_an_unknown_schema_reads_as_empty(self):
        fleet.registry_path().parent.mkdir(parents=True, exist_ok=True)
        fleet.registry_path().write_text(
            json.dumps({"schema": 99, "repos": ["/somewhere"]}), encoding="utf-8"
        )
        self.assertEqual(fleet.load_registry(), [])

    def test_non_string_entries_are_dropped_not_fatal(self):
        fleet.registry_path().parent.mkdir(parents=True, exist_ok=True)
        fleet.registry_path().write_text(
            json.dumps({"schema": 1, "repos": ["/a", 7, None, ""]}), encoding="utf-8"
        )
        self.assertEqual(fleet.load_registry(), [Path("/a")])

    def test_raven_home_env_overrides_the_default(self):
        self.assertEqual(fleet.raven_home(), Path(self.home.name))


class FleetFindingTests(FleetTestCase):
    def test_an_empty_registry_is_informational_not_a_warning(self):
        findings = self._findings()
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].severity, Severity.INFO)
        self.assertEqual(findings[0].id, "fleet.empty")

    def test_a_repo_at_the_current_sha_is_ok(self):
        repo = self._repo("current", version="deadbeef1234")
        fleet.register(repo)
        with mock.patch.object(fleet, "git_ref", return_value="deadbeef1234"):
            self.assertEqual(self._severity_for("current"), Severity.OK)

    def test_a_dirty_recorded_install_warns_even_if_it_string_matches_current(self):
        # #243: a manifest recorded from an uncommitted Raven checkout has no
        # commit whose content it actually matches. It must never read as
        # "current", even in the coincidental case where the live checkout is
        # still dirty at the same sha and the strings match exactly.
        repo = self._repo("dirty", version="deadbeef1234-dirty")
        fleet.register(repo)
        with mock.patch.object(fleet, "git_ref", return_value="deadbeef1234-dirty"):
            finding = next(f for f in self._findings() if "uncommitted checkout" in f.title)
            self.assertEqual(finding.severity, Severity.WARN)
            self.assertTrue(finding.id.startswith("fleet.dirty."))
            self.assertIn("raven upgrade", finding.fix or "")

    def test_a_repo_behind_the_current_sha_warns(self):
        repo = self._repo("old", version="111111111111")
        fleet.register(repo)
        with mock.patch.object(fleet, "git_ref", return_value="222222222222"):
            findings = [f for f in self._findings() if "old" in f.title]
            self.assertEqual(findings[0].severity, Severity.WARN)
            self.assertIn("installed 111111111111, current 222222222222", findings[0].detail)

    def test_the_behind_fix_names_the_repository_to_cd_into(self):
        # The whole point of a fleet view is knowing where to go next.
        repo = self._repo("old", version="111111111111")
        fleet.register(repo)
        with mock.patch.object(fleet, "git_ref", return_value="222222222222"):
            finding = next(f for f in self._findings() if "old" in f.title)
            self.assertIn(str(repo.resolve()), finding.fix or "")
            self.assertIn("raven upgrade", finding.fix or "")

    def test_a_registered_path_that_is_gone_warns_and_points_at_prune(self):
        missing = Path(self.repos.name) / "vanished"
        fleet.save_registry([missing])
        finding = next(f for f in self._findings() if "vanished" in f.title)
        self.assertEqual(finding.severity, Severity.WARN)
        self.assertIn("--prune", finding.fix or "")

    def test_a_repo_whose_manifest_records_no_version_warns(self):
        repo = self._repo("nover")
        (repo / ".raven" / "manifest.json").write_text(
            json.dumps({"schema": 1, "files": {}, "template": "python"}), encoding="utf-8"
        )
        fleet.register(repo)
        self.assertEqual(self._severity_for("nover"), Severity.WARN)

    def test_a_non_git_raven_checkout_reports_the_pin_without_judging_it(self):
        # "cannot tell" is a weaker claim than "behind", the same rule doctor
        # applies to an unreadable plugin registry.
        repo = self._repo("pinned", version="333333333333")
        fleet.register(repo)
        with mock.patch.object(fleet, "git_ref", return_value="unknown"):
            self.assertEqual(self._severity_for("pinned"), Severity.INFO)

    def test_the_template_name_appears_in_every_repo_finding(self):
        repo = self._repo("goapp", template="go", version="444444444444")
        fleet.register(repo)
        with mock.patch.object(fleet, "git_ref", return_value="444444444444"):
            self.assertIn("(go)", next(f for f in self._findings() if "goapp" in f.title).title)

    def test_stale_paths_lists_only_the_gone_ones(self):
        live = self._repo("live")
        missing = Path(self.repos.name) / "dead"
        fleet.save_registry([live.resolve(), missing])
        self.assertEqual(fleet.stale_paths(), [missing])


class FleetCommandTests(FleetTestCase):
    def _run(self, **kwargs):
        args = argparse.Namespace(json=False, prune=False, **kwargs)
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            rc = cmd_fleet(args)
        return rc, buffer.getvalue()

    def test_fleet_exits_zero_when_a_repo_is_merely_behind(self):
        # Being behind is a report, not a broken install: same rule doctor
        # follows, where only an `error` finding changes the exit code.
        repo = self._repo("old", version="111111111111")
        fleet.register(repo)
        with mock.patch.object(fleet, "git_ref", return_value="222222222222"):
            rc, output = self._run()
        self.assertEqual(rc, 0)
        self.assertIn("is behind", output)

    def test_json_output_parses_and_carries_the_findings(self):
        repo = self._repo("old", version="111111111111")
        fleet.register(repo)
        args = argparse.Namespace(json=True, prune=False)
        buffer = io.StringIO()
        with (
            mock.patch.object(fleet, "git_ref", return_value="222222222222"),
            contextlib.redirect_stdout(buffer),
        ):
            cmd_fleet(args)
        payload = json.loads(buffer.getvalue())
        self.assertEqual(payload["command"], "fleet")
        self.assertTrue(any("is behind" in f["title"] for f in payload["findings"]))

    def test_prune_forgets_only_the_gone_repositories(self):
        live = self._repo("live")
        missing = Path(self.repos.name) / "dead"
        fleet.save_registry([live.resolve(), missing])
        args = argparse.Namespace(json=False, prune=True)
        with contextlib.redirect_stdout(io.StringIO()):
            rc = cmd_fleet(args)
        self.assertEqual(rc, 0)
        self.assertEqual(fleet.load_registry(), [live.resolve()])

    def test_prune_with_nothing_stale_says_so_and_changes_nothing(self):
        live = self._repo("live")
        fleet.save_registry([live.resolve()])
        args = argparse.Namespace(json=False, prune=True)
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            rc = cmd_fleet(args)
        self.assertEqual(rc, 0)
        self.assertIn("Nothing to prune", buffer.getvalue())
        self.assertEqual(fleet.load_registry(), [live.resolve()])

    def test_fleet_never_writes_into_a_registered_repository(self):
        """`fleet` is a report. Nothing it does may touch the repos it lists."""
        repo = self._repo("watched")
        fleet.register(repo)
        before = {p: p.stat().st_mtime_ns for p in repo.rglob("*") if p.is_file()}
        with contextlib.redirect_stdout(io.StringIO()):
            cmd_fleet(argparse.Namespace(json=False, prune=False))
        after = {p: p.stat().st_mtime_ns for p in repo.rglob("*") if p.is_file()}
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
