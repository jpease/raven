import argparse
import contextlib
import io
import json
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

from helpers import (
    LSP_DEFAULTS,
    REPO_ROOT,
    RavenTestCase,
    lsp_doc_command,
    lsp_mcp_args,
    raven,
)
from raven_lib.constants import STARTER_TOOL_CONFIG_PATHS


class TemplateTests(RavenTestCase):
    def test_starter_tool_configs_are_copied_when_missing(self):
        expected = {
            "python": ["pyproject.toml"],
            "typescript": ["eslint.config.mjs", "prettier.config.mjs"],
            "go": [".golangci.yml"],
            "rust": ["rustfmt.toml"],
            "swift": [".swiftlint.yml"],
            "elixir": [".credo.exs", ".formatter.exs"],
            "lua": ["stylua.toml", ".luacheckrc"],
            "ruby": [".rubocop.yml"],
        }

        for language, paths in expected.items():
            with self.subTest(language=language):
                template = REPO_ROOT / language
                entries = raven.entries_for_destination(
                    template,
                    self.excludes,
                    raven.load_config(self.destination),
                    self.destination,
                )
                classification = raven.classify(
                    template,
                    self.destination,
                    self.excludes,
                    raven.load_config(self.destination),
                    entries=entries,
                )

                for path in paths:
                    self.assertIn(path, classification.will_copy)

    def test_every_starter_tool_config_path_ships_in_some_template(self):
        languages = raven.list_language_templates()
        shipped = set()
        for language in languages:
            for relative in STARTER_TOOL_CONFIG_PATHS:
                if (REPO_ROOT / language / relative).exists():
                    shipped.add(relative)

        missing = STARTER_TOOL_CONFIG_PATHS - shipped
        self.assertFalse(
            missing,
            f"STARTER_TOOL_CONFIG_PATHS entries not shipped by any template: {sorted(missing)}",
        )

    def test_existing_starter_tool_config_is_skipped_without_merge(self):
        target = self.destination / "pyproject.toml"
        target.write_text("[project]\nname = \"local-project\"\n", encoding="utf-8")

        entries = raven.entries_for_destination(
            self.template,
            self.excludes,
            raven.load_config(self.destination),
            self.destination,
        )
        classification = raven.classify(
            self.template,
            self.destination,
            self.excludes,
            raven.load_config(self.destination),
            entries=entries,
        )

        self.assertNotIn("pyproject.toml", entries)
        self.assertNotIn("pyproject.toml", classification.will_copy)
        self.assertNotIn("pyproject.toml", classification.unknown_existing)
        self.assertEqual(
            target.read_text(encoding="utf-8"), "[project]\nname = \"local-project\"\n"
        )

    def test_config_can_disable_starter_tool_configs(self):
        config_path = self.destination / ".raven" / "config.toml"
        config_path.parent.mkdir()
        config_path.write_text(
            """
schema = 1
template = "python"

[components]
tool_configs = false
""".strip()
            + "\n",
            encoding="utf-8",
        )

        config = raven.load_config(self.destination)
        entries = [
            entry.relative
            for entry in raven.iter_template_entries(self.template, self.excludes, config)
        ]

        self.assertNotIn("pyproject.toml", entries)
        self.assertIn("justfile", entries)

    def test_claude_skills_remap_honors_per_skill_excludes(self):
        skills_dir = self.destination / ".claude" / "skills"
        skills_dir.mkdir(parents=True)
        (skills_dir / "keep-me.txt").write_text("placeholder\n", encoding="utf-8")

        config_path = self.destination / ".raven" / "config.toml"
        config_path.parent.mkdir()
        config_path.write_text(
            """
schema = 1
template = "python"

[exclude]
paths = [".claude/skills/raven-plan/**"]
""".strip()
            + "\n",
            encoding="utf-8",
        )

        config = raven.load_config(self.destination)
        entries = raven.entries_for_destination(
            self.template, self.excludes, config, self.destination
        )

        self.assertFalse(
            any(relative.startswith(".claude/skills/raven-plan/") for relative in entries)
        )
        self.assertTrue(
            any(relative.startswith(".agents/skills/raven-plan/") for relative in entries)
        )
        self.assertTrue(
            any(relative.startswith(".claude/skills/raven-commit/") for relative in entries)
        )

    def test_all_language_templates_install_and_upgrade_cleanly(self):
        languages = raven.list_language_templates()

        self.assertIn("python", languages)
        self.assertIn("swift", languages)
        self.assertIn("go", languages)
        self.assertIn("rust", languages)
        self.assertIn("typescript", languages)
        self.assertIn("elixir", languages)
        for language in languages:
            with self.subTest(language=language), tempfile.TemporaryDirectory() as tmp:
                destination = Path(tmp)
                install_output = io.StringIO()
                upgrade_output = io.StringIO()

                with contextlib.redirect_stdout(install_output):
                    install_rc = raven.cmd_install(
                        argparse.Namespace(
                            destination=str(destination),
                            args=[language],
                            include_readme=False,
                            dry_run=False,
                            adopt_claude_symlink=False,
                        )
                    )
                with contextlib.redirect_stdout(upgrade_output):
                    upgrade_rc = raven.cmd_upgrade(
                        argparse.Namespace(
                            destination=str(destination),
                            overrides=[],
                            include_readme=False,
                            dry_run=True,
                            adopt_claude_symlink=False,
                        )
                    )

                self.assertEqual(install_rc, 0, install_output.getvalue())
                self.assertEqual(upgrade_rc, 0, upgrade_output.getvalue())
                self.assertTrue((destination / "AGENTS.md").is_file())
                self.assertTrue((destination / "CLAUDE.md").is_symlink())
                self.assertEqual(os.readlink(destination / "CLAUDE.md"), "AGENTS.md")
                self.assertTrue((destination / ".claude" / "skills").is_symlink())
                self.assertEqual(
                    os.readlink(destination / ".claude" / "skills"), "../.agents/skills"
                )
                self.assertTrue((destination / ".codex" / "config.toml").is_file())
                self.assertTrue((destination / ".codex" / "hooks.json").is_file())
                self.assertTrue(
                    (
                        destination / ".agents" / "skills" / "raven-security-review" / "SKILL.md"
                    ).is_file()
                )
                self.assertTrue(
                    (destination / ".codex" / "agents" / "raven-security-reviewer.toml").is_file()
                )
                self.assertTrue((destination / ".codex" / "rules" / "raven.rules").is_file())
                self.assertIn("Already up to date", upgrade_output.getvalue())
                self.assertIn(
                    "Manual merge required (locally modified Raven-managed files; "
                    "will be left untouched):\n  (none)",
                    upgrade_output.getvalue(),
                )
                self.assertIn(
                    "Manual merge required (existing files Raven does not manage; "
                    "template ships its own version):\n  (none)",
                    upgrade_output.getvalue(),
                )

    def test_hook_commands_are_project_anchored(self):
        def commands_in(node):
            commands = []
            if isinstance(node, dict):
                command = node.get("command")
                if isinstance(command, str):
                    commands.append(command)
                for value in node.values():
                    commands.extend(commands_in(value))
            elif isinstance(node, list):
                for value in node:
                    commands.extend(commands_in(value))
            return commands

        cases = [
            (
                REPO_ROOT / "common" / ".claude" / "settings.json",
                "$CLAUDE_PROJECT_DIR/",
                "python .claude/",
            ),
            (
                REPO_ROOT / "common" / ".codex" / "hooks.json",
                "json.loads(payload)['cwd']",
                "python .codex/",
            ),
        ]

        for path, required_anchor, forbidden_prefix in cases:
            with self.subTest(path=path):
                commands = commands_in(json.loads(path.read_text(encoding="utf-8")))
                raven_commands = [command for command in commands if "raven-" in command]

                self.assertTrue(raven_commands)
                for command in raven_commands:
                    self.assertIn(required_anchor, command)
                    self.assertNotIn(forbidden_prefix, command)

    def test_codex_bash_guard_runs_outside_project_worktree(self):
        config = json.loads(
            (REPO_ROOT / "common" / ".codex" / "hooks.json").read_text(encoding="utf-8")
        )
        command = config["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
        payload = {
            "cwd": str(REPO_ROOT),
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": "git status --short"},
        }

        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                command,
                cwd=tmp,
                input=json.dumps(payload),
                capture_output=True,
                text=True,
                shell=True,
                check=False,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")

    def test_codex_hook_launcher_preserves_payload_and_arguments(self):
        config = json.loads(
            (REPO_ROOT / "common" / ".codex" / "hooks.json").read_text(encoding="utf-8")
        )
        command = config["hooks"]["SessionStart"][0]["hooks"][0]["command"]

        with tempfile.TemporaryDirectory() as project_tmp, tempfile.TemporaryDirectory() as cwd_tmp:
            project = Path(project_tmp)
            subprocess.run(
                ["git", "init", "-q", str(project)],
                capture_output=True,
                text=True,
                check=True,
            )
            subprocess.run(
                ["git", "-C", str(project), "config", "core.bare", "true"],
                capture_output=True,
                text=True,
                check=True,
            )
            script = project / ".codex" / "scripts" / "raven-capability-roster.py"
            script.parent.mkdir(parents=True)
            script.write_text(
                "import json, sys\n"
                "print(json.dumps({'argv': sys.argv[1:], 'payload': json.load(sys.stdin)}))\n",
                encoding="utf-8",
            )
            session_cwd = project / "nested" / "worktree"
            session_cwd.mkdir(parents=True)
            payload = {"cwd": str(session_cwd), "hook_event_name": "SessionStart"}

            result = subprocess.run(
                command,
                cwd=cwd_tmp,
                input=json.dumps(payload),
                capture_output=True,
                text=True,
                shell=True,
                check=False,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual(output["argv"], [])
        self.assertEqual(output["payload"], payload)

    def test_templates_have_no_broken_symlinks(self):
        for language in raven.list_language_templates():
            template = REPO_ROOT / language
            with self.subTest(language=language):
                broken = []
                for current, dirnames, filenames in os.walk(template, followlinks=False):
                    for name in dirnames + filenames:
                        candidate = Path(current) / name
                        if candidate.is_symlink() and not candidate.exists():
                            broken.append(candidate.relative_to(template).as_posix())
                self.assertEqual(broken, [])

    def test_language_templates_define_specific_lsp_mcp_defaults(self):
        expected = {language: lsp_mcp_args(language) for language in LSP_DEFAULTS}

        for language, args in expected.items():
            with self.subTest(language=language):
                config = json.loads(
                    (REPO_ROOT / language / ".mcp.json").read_text(encoding="utf-8")
                )
                lsp = config["mcpServers"]["lsp"]

                self.assertEqual(lsp["command"], "mcp-language-server")
                self.assertEqual(lsp["args"], args)

    def test_language_templates_define_specific_codex_lsp_mcp_defaults(self):
        expected = {language: lsp_mcp_args(language) for language in LSP_DEFAULTS}

        for language, args in expected.items():
            with self.subTest(language=language):
                config = raven.parse_simple_toml(
                    (REPO_ROOT / language / ".codex" / "config.toml").read_text(encoding="utf-8")
                )
                lsp = config["mcp_servers.lsp"]
                assert isinstance(lsp, dict)  # parse_simple_toml values are typed object

                self.assertEqual(lsp["command"], "mcp-language-server")
                self.assertEqual(lsp["args"], args)

    def test_readme_lsp_table_matches_the_shipped_defaults(self):
        # The README table was the one place naming these servers that nothing
        # checked, so it could describe a server no template installs.
        readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        for language in LSP_DEFAULTS:
            with self.subTest(language=language):
                row = re.search(rf"^\|\s*{language}\s*\|([^|]*)\|", readme, re.M | re.I)
                self.assertIsNotNone(row, f"README has no LSP table row for {language}")
                assert row is not None
                self.assertIn(
                    lsp_doc_command(language),
                    row.group(1),
                    f"README's {language} row disagrees with the shipped .mcp.json",
                )

    def test_lsp_reference_doc_names_the_shipped_server_for_every_template(self):
        # raven-lsp-mcp.md is the agent-facing reference; a server named here
        # that no template ships sends the reader to install the wrong thing.
        doc = (REPO_ROOT / "common" / ".claude" / "docs" / "raven-lsp-mcp.md").read_text(
            encoding="utf-8"
        )
        for language, (server, _) in LSP_DEFAULTS.items():
            with self.subTest(language=language):
                self.assertIn(
                    server,
                    doc,
                    f"raven-lsp-mcp.md never mentions {language}'s shipped server {server!r}",
                )

    def test_common_mcp_json_servers_ship_in_every_language_template(self):
        # common/.mcp.json is never installed directly (each language tree ships
        # its own real .mcp.json so it can set a language-specific "lsp" server),
        # but it documents the shared server set every tree must include. Guard
        # against it drifting from what trees actually ship, per #83.
        common_servers = json.loads(
            (REPO_ROOT / "common" / ".mcp.json").read_text(encoding="utf-8")
        )["mcpServers"]

        for language in raven.list_language_templates():
            with self.subTest(language=language):
                tree_servers = json.loads(
                    (REPO_ROOT / language / ".mcp.json").read_text(encoding="utf-8")
                )["mcpServers"]

                for name, config in common_servers.items():
                    self.assertIn(name, tree_servers)
                    self.assertEqual(tree_servers[name], config)

    def test_dotfiles_stack_shape(self):
        languages = raven.list_language_templates()
        self.assertIn("dotfiles", languages)

        stack = REPO_ROOT / "dotfiles"

        # Stack-local rule exists as a real file.
        rule = stack / ".claude" / "rules" / "raven-dotfiles.md"
        self.assertTrue(rule.is_file())

        # .mcp.json ships semgrep/semble/gitnexus but intentionally no lsp server.
        mcp = json.loads((stack / ".mcp.json").read_text(encoding="utf-8"))
        servers = mcp["mcpServers"]
        self.assertIn("semgrep", servers)
        self.assertIn("semble", servers)
        self.assertIn("gitnexus", servers)
        self.assertNotIn("lsp", servers)

        # Global, description-gated skill lives in common/.
        skill = REPO_ROOT / "common" / ".agents" / "skills" / "raven-dotfiles" / "SKILL.md"
        self.assertTrue(skill.is_file())

        # v1 intentionally ships no justfile and no quality doc for this stack.
        self.assertFalse((stack / "justfile").exists())
        self.assertFalse((stack / ".claude" / "docs" / "raven-dotfiles-quality.md").exists())


if __name__ == "__main__":
    unittest.main()
