"""Project-declared protected paths in the edit guard (issue #247).

`AGENTS.md`'s Pause-And-Ask categories are prose. `[edit_guard]
protected_paths` in `.raven/config.toml` is the mechanical backstop for the
ones a project can spell as paths: on Claude Code a matching edit escalates to
a permission prompt, on Codex it adds a warning to context. End-to-end tests
copy the hook into an installed layout under each adapter directory, because
the hook reads both its config and its adapter identity from where it lives.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

from helpers import REPO_ROOT, RavenTestCase, load_script_module

HOOK = REPO_ROOT / "common" / ".claude" / "hooks" / "raven-pre-edit-guard.py"
RAVEN_CONFIG = REPO_ROOT / "common" / ".raven" / "git-hooks" / "lib" / "raven_config.py"


def _module():
    return load_script_module("raven_pre_edit_guard", HOOK)


class ParseTests(RavenTestCase):
    def test_absent_section_means_no_patterns_and_ask(self):
        self.assertEqual(_module().parse_protected_paths("[skeleton]\n"), ([], "ask"))

    def test_reads_an_array_in_either_quote_style(self):
        text = "[edit_guard]\nprotected_paths = [\"migrations/*\", 'infra/*.tf']\n"
        self.assertEqual(
            _module().parse_protected_paths(text), (["migrations/*", "infra/*.tf"], "ask")
        )

    def test_decision_warn_is_honored_and_garbage_falls_back_to_ask(self):
        module = _module()
        base = '[edit_guard]\nprotected_paths = ["a/*"]\n'
        self.assertEqual(
            module.parse_protected_paths(base + 'protected_paths_decision = "warn"\n')[1],
            "warn",
        )
        self.assertEqual(
            module.parse_protected_paths(base + 'protected_paths_decision = "block"\n')[1],
            "ask",
        )

    def test_a_commented_out_example_declares_nothing(self):
        text = '[edit_guard]\n# protected_paths = ["migrations/*"]\n'
        self.assertEqual(_module().parse_protected_paths(text), ([], "ask"))


class MatchTests(RavenTestCase):
    def test_relative_paths_inside_the_root(self):
        module = _module()
        root = Path("/repo")
        self.assertEqual(module.relative_to_root("/repo/src/auth/x.py", root), "src/auth/x.py")
        self.assertEqual(module.relative_to_root("src/auth/x.py", root), "src/auth/x.py")
        self.assertEqual(module.relative_to_root("src\\auth\\x.py", root), "src/auth/x.py")

    def test_star_crosses_directories(self):
        module = _module()
        patterns = ["migrations/*", "infra/*.tf"]
        self.assertEqual(
            module.matching_protected_pattern("migrations/0001_init.py", patterns), "migrations/*"
        )
        self.assertEqual(
            module.matching_protected_pattern("migrations/2024/0002.py", patterns), "migrations/*"
        )
        self.assertEqual(
            module.matching_protected_pattern("infra/prod/main.tf", patterns), "infra/*.tf"
        )
        self.assertIsNone(module.matching_protected_pattern("src/app.py", patterns))


class EndToEndTests(RavenTestCase):
    def _install(self, adapter: str, config: str) -> Path:
        hooks = self.destination / adapter / "hooks"
        hooks.mkdir(parents=True, exist_ok=True)
        shutil.copy(HOOK, hooks / HOOK.name)
        lib = self.destination / ".raven" / "git-hooks" / "lib"
        lib.mkdir(parents=True, exist_ok=True)
        shutil.copy(RAVEN_CONFIG, lib / RAVEN_CONFIG.name)
        (self.destination / ".raven" / "config.toml").write_text(config, encoding="utf-8")
        return hooks / HOOK.name

    def _run(self, hook: Path, path: str) -> subprocess.CompletedProcess:
        payload = {
            "hook_event_name": "PreToolUse",
            "tool_name": "Edit",
            "tool_input": {"file_path": path},
        }
        return subprocess.run(
            [sys.executable, str(hook)],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            cwd=self.destination,
            check=False,
        )

    PROTECTED = '[edit_guard]\nprotected_paths = ["migrations/*"]\n'

    def test_claude_escalates_a_protected_edit_to_a_prompt(self):
        hook = self._install(".claude", self.PROTECTED)
        result = self._run(hook, str(self.destination / "migrations" / "0001.py"))
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)["hookSpecificOutput"]
        self.assertEqual(output["permissionDecision"], "ask")
        self.assertIn("migrations/*", output["permissionDecisionReason"])
        self.assertIn("Pause and ask", output["permissionDecisionReason"])

    def test_warn_decision_adds_context_instead(self):
        hook = self._install(".claude", self.PROTECTED + 'protected_paths_decision = "warn"\n')
        result = self._run(hook, "migrations/0001.py")
        output = json.loads(result.stdout)["hookSpecificOutput"]
        self.assertNotIn("permissionDecision", output)
        self.assertIn("migrations/*", output["additionalContext"])

    def test_codex_gets_context_because_it_has_no_ask(self):
        hook = self._install(".codex", self.PROTECTED)
        result = self._run(hook, "migrations/0001.py")
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)["hookSpecificOutput"]
        self.assertNotIn("permissionDecision", output)
        self.assertIn("migrations/*", output["additionalContext"])

    def test_an_unlisted_path_passes_silently(self):
        hook = self._install(".claude", self.PROTECTED)
        result = self._run(hook, "src/app.py")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")

    def test_no_config_section_changes_nothing(self):
        hook = self._install(".claude", "[skeleton]\n")
        self.assertEqual(self._run(hook, "migrations/0001.py").stdout, "")

    def test_secret_paths_are_still_denied_ahead_of_the_list(self):
        hook = self._install(".claude", '[edit_guard]\nprotected_paths = ["*"]\n')
        result = self._run(hook, ".env")
        output = json.loads(result.stdout)["hookSpecificOutput"]
        self.assertEqual(output["permissionDecision"], "deny")

    def test_the_caution_tier_now_reaches_the_model(self):
        # It used to print to stderr on exit 0, which Claude Code writes to
        # the debug log and never shows the model.
        hook = self._install(".claude", "[skeleton]\n")
        result = self._run(hook, "package-lock.json")
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)["hookSpecificOutput"]
        self.assertIn("High-churn", output["additionalContext"])
        self.assertEqual(result.stderr, "")
