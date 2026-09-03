"""The Read secret guard: the 21 `Read()` deny rules, moved into a hook (#260)."""

from __future__ import annotations

import json
import os
import subprocess
import sys

from helpers import REPO_ROOT, RavenTestCase, load_script_module

HOOK = REPO_ROOT / "common" / ".claude" / "hooks" / "raven-pre-read-secret-guard.py"


def _module():
    return load_script_module("raven_pre_read_secret_guard", HOOK)


class MatchTests(RavenTestCase):
    def test_every_ported_rule_still_matches_something(self):
        module = _module()
        cases = {
            "*.pem": "certs/server.pem",
            "*.key": "certs/server.key",
            "*.p12": "bundle.p12",
            "*.pfx": "bundle.pfx",
            "*.crt": "ca.crt",
            "*.cer": "ca.cer",
            ".env": ".env",
            ".env.*": ".env.production",
            ".envrc": ".envrc",
            "secrets.*": "secrets.yaml",
            "credentials.*": "credentials.json",
        }
        for rule, path in cases.items():
            with self.subTest(rule=rule):
                self.assertEqual(module.matches(path), rule)

    def test_depth_is_still_covered(self):
        # The whole point of the gitignore-style rules being kept: a nested
        # .env was covered without a `**/` entry, and still is.
        self.assertEqual(_module().matches("packages/api/.env"), ".env")

    def test_container_directories_are_covered(self):
        module = _module()
        self.assertEqual(module.matches("secrets/deploy.yaml"), "secrets/**")
        self.assertEqual(module.matches("app/credentials/aws.json"), "credentials/**")

    def test_env_example_is_deliberately_covered(self):
        # Same decision as the rule this replaces (#213): enumerating the
        # secret-bearing variants would leave an unlisted one exposed.
        self.assertEqual(_module().matches(".env.example"), ".env.*")

    def test_ordinary_paths_pass(self):
        module = _module()
        for path in ("README.md", "src/app.py", "certs/README.md", "environment.py"):
            with self.subTest(path=path):
                self.assertIsNone(module.matches(path))


class EndToEndTests(RavenTestCase):
    def _run(self, file_path: str, cwd: str | None = None) -> str:
        payload = {
            "hook_event_name": "PreToolUse",
            "tool_name": "Read",
            "tool_input": {"file_path": file_path},
            "cwd": cwd or str(self.destination),
        }
        result = subprocess.run(
            [sys.executable, str(HOOK)],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            env=dict(os.environ),
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def test_a_secret_read_is_denied_with_the_rule_named(self):
        output = json.loads(self._run(".env"))["hookSpecificOutput"]
        self.assertEqual(output["permissionDecision"], "deny")
        self.assertIn("`.env`", output["permissionDecisionReason"])

    def test_an_ordinary_read_is_silent(self):
        self.assertEqual(self._run("src/app.py"), "")

    def test_config_can_turn_it_off(self):
        (self.destination / ".raven").mkdir(exist_ok=True)
        (self.destination / ".raven" / "config.toml").write_text(
            "[hooks]\nblock_secret_reads = false\n", encoding="utf-8"
        )
        self.assertEqual(self._run(".env"), "")

    def test_config_absent_defaults_to_enabled(self):
        self.assertNotEqual(self._run(".env"), "")

    def test_malformed_payload_is_silent(self):
        result = subprocess.run(
            [sys.executable, str(HOOK)],
            input="not json",
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")


class SettingsParityTests(RavenTestCase):
    def test_no_read_deny_rules_remain_in_shipped_settings(self):
        # The prompt in #260 came from these existing at all; if one is ever
        # added back, the recursive-search escalation returns with it.
        settings = json.loads(
            (REPO_ROOT / "common" / ".claude" / "settings.json").read_text(encoding="utf-8")
        )
        offenders = [r for r in settings["permissions"]["deny"] if r.startswith("Read(")]
        self.assertEqual(offenders, [])

    def test_the_hook_is_wired_on_the_read_matcher(self):
        settings = json.loads(
            (REPO_ROOT / "common" / ".claude" / "settings.json").read_text(encoding="utf-8")
        )
        commands = [
            hook["command"]
            for group in settings["hooks"]["PreToolUse"]
            if group.get("matcher") == "Read"
            for hook in group["hooks"]
        ]
        self.assertTrue(
            any("raven-pre-read-secret-guard.py" in c for c in commands),
            commands,
        )
