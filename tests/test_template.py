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
from unittest import mock

from helpers import (
    LSP_DEFAULTS,
    REPO_ROOT,
    RavenTestCase,
    install_ns,
    lsp_doc_command,
    lsp_mcp_args,
    raven,
    upgrade_ns,
)
from raven_lib.constants import EXPECTED_TEMPLATE_SYMLINKS, STARTER_TOOL_CONFIG_PATHS
from raven_lib.template import broken_template_symlinks, should_preserve_symlink


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
                self.assertTrue((destination / ".gitattributes").is_file())
                self.assertIn(
                    "* text=auto", (destination / ".gitattributes").read_text(encoding="utf-8")
                )
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

    def test_tooling_doc_lsp_table_matches_the_shipped_defaults(self):
        # This table was the one place naming these servers that nothing
        # checked, so it could describe a server no template installs.
        doc_path = REPO_ROOT / "docs" / "tooling.md"
        doc = doc_path.read_text(encoding="utf-8")
        for language in LSP_DEFAULTS:
            with self.subTest(language=language):
                row = re.search(rf"^\|\s*{language}\s*\|([^|]*)\|", doc, re.M | re.I)
                self.assertIsNotNone(row, f"docs/tooling.md has no LSP table row for {language}")
                assert row is not None
                self.assertIn(
                    lsp_doc_command(language),
                    row.group(1),
                    f"docs/tooling.md's {language} row disagrees with the shipped .mcp.json",
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

        # .mcp.json ships semgrep/gitnexus but intentionally no lsp server.
        mcp = json.loads((stack / ".mcp.json").read_text(encoding="utf-8"))
        servers = mcp["mcpServers"]
        self.assertIn("semgrep", servers)
        self.assertIn("gitnexus", servers)
        self.assertNotIn("lsp", servers)

        # Global, description-gated skill lives in common/.
        skill = REPO_ROOT / "common" / ".agents" / "skills" / "raven-dotfiles" / "SKILL.md"
        self.assertTrue(skill.is_file())

        # v1 intentionally ships no justfile and no quality doc for this stack.
        self.assertFalse((stack / "justfile").exists())
        self.assertFalse((stack / ".claude" / "docs" / "raven-dotfiles-quality.md").exists())

    def test_generic_stack_shape(self):
        # Issue #224 -- the common-only template. `dotfiles` is the same shape
        # carrying one domain rules file; `generic` carries none, so a repo with
        # no language stack (static site, docs tree, infra config) can install
        # the shared guardrails without inheriting gates it cannot run.
        languages = raven.list_language_templates()
        self.assertIn("generic", languages)

        stack = REPO_ROOT / "generic"

        # Owns no rules file at all -- that absence is the whole point, and it
        # is what keeps `generic` out of self-check's context-budget profiles.
        rules = stack / ".claude" / "rules"
        owned_rules = [p.name for p in sorted(rules.iterdir()) if not p.is_symlink()]
        self.assertEqual(owned_rules, [], f"generic must own no rules file, found {owned_rules}")
        self.assertFalse((rules / "raven-generic.md").exists())

        # Still ships the two shared rules every tree gets, as symlinks.
        for name in ("raven-prose.md", "raven-security.md"):
            with self.subTest(rule=name):
                self.assertTrue((rules / name).is_symlink())

        # .mcp.json ships semgrep/gitnexus and, like dotfiles, no lsp server:
        # there is no language to point mcp-language-server at.
        mcp = json.loads((stack / ".mcp.json").read_text(encoding="utf-8"))
        servers = mcp["mcpServers"]
        self.assertIn("semgrep", servers)
        self.assertIn("gitnexus", servers)
        self.assertNotIn("lsp", servers)

        codex_config = (stack / ".codex" / "config.toml").read_text(encoding="utf-8")
        self.assertNotIn("mcp_servers.lsp", codex_config)

        # No build system means no gate to run and no starter tool config to seed.
        self.assertFalse((stack / "justfile").exists())
        self.assertFalse((stack / ".claude" / "docs" / "raven-generic-quality.md").exists())
        for starter in STARTER_TOOL_CONFIG_PATHS:
            with self.subTest(starter=starter):
                self.assertFalse((stack / starter).exists())

        # Carries no dotfiles-domain content -- the two trees stay distinct.
        self.assertFalse((stack / ".claude" / "rules" / "raven-dotfiles.md").exists())


# ---------------------------------------------------------------------------
# #177 -- a checkout made without symlink support materializes every template
# symlink as a regular file whose content is the target path string. Raven does
# not support such a checkout: it refuses up front rather than copying that
# placeholder text into a destination as if it were real content.
# ---------------------------------------------------------------------------
class ExpectedTemplateSymlinkRegistryTests(unittest.TestCase):
    def test_registry_matches_the_symlinks_common_actually_ships(self):
        # Canary: adding (or removing) a symlink under common/ without updating
        # EXPECTED_TEMPLATE_SYMLINKS silently shrinks the preflight's coverage.
        # followlinks=False so a directory symlink (.claude/skills) is detected
        # as an entry rather than recursed through.
        common = REPO_ROOT / "common"
        found = set()
        for current, dirnames, filenames in os.walk(common, followlinks=False):
            for name in dirnames + filenames:
                candidate = Path(current) / name
                if candidate.is_symlink():
                    found.add(candidate.relative_to(common).as_posix())

        self.assertEqual(found, set(EXPECTED_TEMPLATE_SYMLINKS))

    def test_healthy_checkout_reports_nothing_broken(self):
        self.assertEqual(broken_template_symlinks(REPO_ROOT / "common"), [])


class BrokenTemplateSymlinkDetectionTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.common = Path(self._tmp.name) / "common"

    def _flatten(self, relative: str) -> None:
        """Write ``relative`` the way a no-symlink git checkout would: as a
        regular file whose entire content is the symlink target string.
        """
        path = self.common / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("../../../common/.claude/whatever\n", encoding="utf-8")

    def _link(self, relative: str) -> None:
        path = self.common / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        real = path.parent / f"real-{path.name}"
        real.write_text("real content\n", encoding="utf-8")
        path.symlink_to(real.name)

    def test_flattened_entries_are_reported_and_healthy_ones_are_not(self):
        self._flatten(".codex/scripts/raven-tool-check.py")
        self._flatten(".codex/hooks/raven-pre-bash-guard.py")
        self._link("CLAUDE.md")

        self.assertEqual(
            broken_template_symlinks(self.common),
            [".codex/hooks/raven-pre-bash-guard.py", ".codex/scripts/raven-tool-check.py"],
        )

    def test_absent_entries_are_not_reported_as_flattened(self):
        # A path that is simply missing is a different (and, for the throwaway
        # template trees the tests build, entirely normal) condition. Only a
        # path that exists *and is not a symlink* is evidence of a checkout that
        # dropped symlink support.
        self.assertEqual(broken_template_symlinks(self.common), [])

    def test_flattened_directory_symlink_is_reported(self):
        path = self.common / ".claude" / "skills"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("../.agents/skills\n", encoding="utf-8")

        self.assertEqual(broken_template_symlinks(self.common), [".claude/skills"])


class SymlinkContainmentTests(unittest.TestCase):
    """`should_preserve_symlink` must resolve the target, not prefix-match it."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.common = self.root / "root" / "common"
        (self.common / ".codex" / "hooks").mkdir(parents=True)
        (self.common / ".claude" / "hooks").mkdir(parents=True)

    def test_target_escaping_common_is_preserved_not_dereferenced(self):
        # `../../../common/../../victim/secret.txt` textually starts with a
        # climb back into common/, which the old prefix regex accepted -- so the
        # installer would have dereferenced it and copied an arbitrary file from
        # outside the template tree into the destination as real content.
        victim = self.root / "victim"
        victim.mkdir()
        (victim / "secret.txt").write_text("top secret\n", encoding="utf-8")

        evil = self.common / ".codex" / "hooks" / "evil.py"
        evil.symlink_to("../../../common/../../victim/secret.txt")
        # Precondition: the crafted target really does escape and really does
        # resolve to the victim file, so the assertion below is about
        # containment rather than a dangling link.
        self.assertEqual(evil.resolve().read_text(encoding="utf-8"), "top secret\n")

        self.assertTrue(should_preserve_symlink(evil, common_root=self.common))

    def test_genuine_internal_cross_link_is_still_dereferenced(self):
        # The positive control: an honest climb back into common/ must keep its
        # existing classification (copied as a real file at the destination).
        (self.common / ".claude" / "hooks" / "guard.py").write_text("real\n", encoding="utf-8")
        link = self.common / ".codex" / "hooks" / "guard.py"
        link.symlink_to("../../../common/.claude/hooks/guard.py")

        self.assertFalse(should_preserve_symlink(link, common_root=self.common))

    def test_sibling_target_inside_common_is_still_preserved(self):
        # common/.claude/skills -> ../.agents/skills and common/CLAUDE.md ->
        # AGENTS.md both *resolve* inside common/ but are not `../common/`
        # cross-links: they are the destination-relative links Raven installs as
        # symlinks. Resolving-and-containing alone would wrongly flatten them.
        (self.common / ".agents").mkdir()
        (self.common / ".agents" / "skills").mkdir()
        skills = self.common / ".claude" / "skills"
        skills.symlink_to("../.agents/skills")
        (self.common / "AGENTS.md").write_text("# A\n", encoding="utf-8")
        claude = self.common / "CLAUDE.md"
        claude.symlink_to("AGENTS.md")

        self.assertTrue(should_preserve_symlink(skills, common_root=self.common))
        self.assertTrue(should_preserve_symlink(claude, common_root=self.common))

    def test_default_common_root_is_the_repo_checkout(self):
        # The single-argument form every production call site uses keeps
        # working, resolving against REPO_ROOT / "common".
        link = REPO_ROOT / "common" / ".codex" / "scripts" / "raven-tool-check.py"
        self.assertFalse(should_preserve_symlink(link))

    def test_non_symlink_is_never_preserved(self):
        plain = self.common / ".codex" / "hooks" / "plain.py"
        plain.write_text("x\n", encoding="utf-8")
        self.assertFalse(should_preserve_symlink(plain, common_root=self.common))


class NoSymlinkCheckoutPreflightTests(RavenTestCase):
    """install/upgrade/accept refuse outright against a flattened checkout."""

    #: What git writes in place of the symlink when the checkout cannot create
    #: one: the target path, as the file's entire content.
    PLACEHOLDER = "../../../common/.claude/scripts/raven-tool-check.py"

    def setUp(self):
        super().setUp()
        self._fake_repo_tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._fake_repo_tmp.cleanup)
        self.fake_repo_root = Path(self._fake_repo_tmp.name)

        template_dir = self.fake_repo_root / "lang"
        template_dir.mkdir(parents=True)
        (template_dir / "AGENTS.md").write_text("root instructions\n", encoding="utf-8")

        flattened = self.fake_repo_root / "common" / ".codex" / "scripts" / "raven-tool-check.py"
        flattened.parent.mkdir(parents=True)
        flattened.write_text(self.PLACEHOLDER, encoding="utf-8")

        patcher = mock.patch("raven_lib.cli.REPO_ROOT", self.fake_repo_root)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _config(self):
        (self.destination / ".raven").mkdir(parents=True, exist_ok=True)
        (self.destination / ".raven" / "config.toml").write_text(
            'schema = 1\ntemplate = "lang"\n', encoding="utf-8"
        )

    def _run(self, command, namespace):
        err = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            rc = command(namespace)
        return rc, err.getvalue()

    def _assert_refused(self, rc, err):
        self.assertEqual(rc, 2, err)
        self.assertIn(".codex/scripts/raven-tool-check.py", err)
        self.assertIn("core.symlinks", err)
        self.assertIn("Developer Mode", err)

    def test_install_refuses_and_writes_nothing(self):
        rc, err = self._run(raven.cmd_install, install_ns(self.destination, language="lang"))
        self._assert_refused(rc, err)
        self.assertFalse((self.destination / "AGENTS.md").exists())
        self.assertFalse((self.destination / ".raven").exists())

    def test_install_dry_run_refuses_identically(self):
        rc, err = self._run(
            raven.cmd_install, install_ns(self.destination, language="lang", dry_run=True)
        )
        self._assert_refused(rc, err)

    def test_upgrade_refuses(self):
        self._config()
        rc, err = self._run(raven.cmd_upgrade, upgrade_ns(self.destination))
        self._assert_refused(rc, err)
        self.assertFalse((self.destination / "AGENTS.md").exists())

    def test_upgrade_dry_run_refuses(self):
        self._config()
        rc, err = self._run(raven.cmd_upgrade, upgrade_ns(self.destination, dry_run=True))
        self._assert_refused(rc, err)

    def test_accept_refuses_before_recording_a_bogus_baseline(self):
        # accept copies nothing, but it *hashes* template content into the
        # manifest baseline -- recording the placeholder text's hash as the
        # accepted source would make the corruption look like the truth.
        self._config()
        rc, err = self._run(
            raven.cmd_accept,
            argparse.Namespace(
                destination=str(self.destination),
                paths=[],
                dry_run=False,
                include_readme=False,
            ),
        )
        self._assert_refused(rc, err)
        self.assertFalse((self.destination / ".raven" / "manifest.json").exists())

    def test_healthy_checkout_still_installs(self):
        # Proves the preflight is a real gate rather than an unconditional
        # refusal: repair the flattened entry and the same install succeeds.
        flattened = self.fake_repo_root / "common" / ".codex" / "scripts" / "raven-tool-check.py"
        flattened.unlink()
        real = flattened.parent / "real.py"
        real.write_text("print('real')\n", encoding="utf-8")
        flattened.symlink_to("real.py")

        rc, err = self._run(raven.cmd_install, install_ns(self.destination, language="lang"))
        self.assertEqual(rc, 0, err)
        self.assertTrue((self.destination / "AGENTS.md").is_file())


if __name__ == "__main__":
    unittest.main()
