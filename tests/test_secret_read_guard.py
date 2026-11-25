"""The Read secret guard: the 21 `Read()` deny rules, moved into a hook (#260)."""

from __future__ import annotations

import json
import os
import re
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


class TargetPathTests(RavenTestCase):
    def test_target_path_reads_uri_path_host_or_file_keys(self):
        target = _module()._target_path

        def mcp(uri):
            return {"tool_name": "read_mcp_resource", "tool_input": {"uri": uri}}

        self.assertEqual(target(mcp("file:///repo/.env")), "/repo/.env")
        self.assertEqual(target(mcp("file:///r/%2Eenv?raw=1")), "/r/.env")
        self.assertEqual(target(mcp("repo://x/secrets/a.json")), "/secrets/a.json")
        self.assertEqual(target(mcp("config://.env")), ".env")
        self.assertIsNone(target(mcp("")))
        self.assertIsNone(target({"tool_name": "read_mcp_resource", "tool_input": {"uri": 3}}))
        self.assertIsNone(target({"tool_name": "read_mcp_resource", "tool_input": {}}))
        self.assertEqual(target({"tool_name": "read_file", "tool_input": {"path": "a"}}), "a")


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
            env={k: v for k, v in os.environ.items() if k != "GEMINI_PROJECT_DIR"},
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def _run_gemini(
        self, file_path: str, key: str = "file_path", tool_name: str = "read_file"
    ) -> str:
        return self._run_gemini_input({key: file_path}, tool_name)

    def _run_gemini_input(self, tool_input: dict, tool_name: str) -> str:
        payload = {
            "hook_event_name": "BeforeTool",
            "tool_name": tool_name,
            "tool_input": tool_input,
            "cwd": str(self.destination),
        }
        result = subprocess.run(
            [sys.executable, str(HOOK)],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def _write_config(self, text: str) -> None:
        (self.destination / ".raven").mkdir(exist_ok=True)
        (self.destination / ".raven" / "config.toml").write_text(text, encoding="utf-8")

    def test_gemini_file_path_and_path_are_denied_in_gemini_shape(self):
        for path, key in (
            (".env", "file_path"),
            ("secrets/api.key", "file_path"),
            (".env", "path"),
        ):
            with self.subTest(path=path, key=key):
                output = json.loads(self._run_gemini(path, key))
                self.assertEqual(output["decision"], "deny")
                self.assertNotIn("hookSpecificOutput", output)
                self.assertIn("`", output["reason"])
                self.assertIn(path.split("/")[0] if "/" in path else path, output["reason"])

    def test_gemini_mcp_resource_uris_are_checked_by_path(self):
        for uri in (
            "file:///r/.env",
            "file:///r/%2Eenv",
            "file:///r/.env?raw=1",
            "config://.env",
            "repo://x/secrets/a.json",
        ):
            with self.subTest(uri=uri):
                output = json.loads(self._run_gemini(uri, "uri", "read_mcp_resource"))
                self.assertEqual(output["decision"], "deny")
                self.assertIn(uri, output["reason"])
        for tool_input in ({"uri": "postgres://db/schema"}, {}, {"uri": ""}, {"uri": 5}):
            with self.subTest(tool_input=tool_input):
                self.assertEqual(self._run_gemini_input(tool_input, "read_mcp_resource"), "")

    def test_gemini_mcp_prefixed_read_file_is_denied(self):
        output = json.loads(self._run_gemini("secrets/x", "path", "mcp_fs_read_file"))
        self.assertEqual(output["decision"], "deny")

    def test_gemini_ordinary_read_is_silent(self):
        self.assertEqual(self._run_gemini("src/app.py"), "")

    def test_deny_reasons_do_not_teach_a_bypass(self):
        claude = json.loads(self._run(".env"))["hookSpecificOutput"]["permissionDecisionReason"]
        gemini = json.loads(self._run_gemini(".env"))["reason"]
        for reason in (claude, gemini):
            self.assertNotIn("does not tool-Read", reason)
            self.assertIn("tell the user", reason)
            self.assertIn("do not read it through another tool or command", reason)

    def test_block_secret_reads_outside_hooks_table_is_ignored(self):
        self._write_config("[other]\nblock_secret_reads = false\n")
        self.assertNotEqual(self._run(".env"), "")

    def test_trailing_comment_still_disables(self):
        self._write_config("[hooks]\nblock_secret_reads = false  # note\n")
        self.assertEqual(self._run(".env"), "")

    def test_quoted_false_does_not_disable(self):
        self._write_config('[hooks]\nblock_secret_reads = "false"\n')
        self.assertNotEqual(self._run(".env"), "")

    def test_unreadable_config_fails_closed(self):
        (self.destination / ".raven").mkdir(exist_ok=True)
        (self.destination / ".raven" / "config.toml").write_bytes(
            b"[hooks]\nblock_secret_reads = false\n\xff\xfe"
        )
        self.assertNotEqual(self._run(".env"), "")

    def test_dotdot_path_is_denied(self):
        self.assertNotEqual(self._run("src/../.env"), "")

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

    def test_the_hook_is_wired_on_gemini_read_tools(self):
        settings = json.loads(
            (REPO_ROOT / "common" / ".gemini" / "settings.json").read_text(encoding="utf-8")
        )
        matchers = [
            group["matcher"]
            for group in settings["hooks"]["BeforeTool"]
            if any("raven-pre-read-secret-guard.py" in h["command"] for h in group["hooks"])
        ]
        self.assertEqual(len(matchers), 1)
        for name in ("read_file", "read_mcp_resource", "mcp_fs_read_file"):
            self.assertTrue(re.search(matchers[0], name), name)
        self.assertFalse(re.search(matchers[0], "run_shell_command"))
