import contextlib
import io
import os
import unittest
from pathlib import Path

from helpers import UNIFIED_ADAPTER_HOOKS, UNIFIED_ADAPTER_SCRIPTS, RavenTestCase, raven
from raven_lib.cli import _adoption_decision, _build_run_plan, invalid_overrides

# Which byte-identical files each adapter subdirectory unifies (issue #165).
UNIFIED_BY_SUBDIR = {
    "scripts": set(UNIFIED_ADAPTER_SCRIPTS),
    "hooks": set(UNIFIED_ADAPTER_HOOKS),
}


class ApplyTests(RavenTestCase):
    def test_classifies_missing_identical_and_unknown_existing_files(self):
        (self.destination / "AGENTS.md").write_text(
            (self.template / "AGENTS.md").read_text(), encoding="utf-8"
        )
        (self.destination / "CLAUDE.md").write_text("custom\n", encoding="utf-8")

        classification = raven.classify(
            self.template,
            self.destination,
            self.excludes,
        )

        self.assertIn(".claude/scripts/raven-tool-check.py", classification.will_copy)
        self.assertIn("AGENTS.md", classification.identical)
        self.assertIn("CLAUDE.md", classification.unknown_existing)
        self.assertEqual(classification.needs_merge, [])
        self.assertEqual(classification.excluded, ["README.md"])

    def test_apply_preserves_compatibility_symlinks(self):
        paths = [
            ".agents/skills/raven-tool-bootstrap/SKILL.md",
            ".claude/skills",
            "CLAUDE.md",
        ]

        raven.copy_paths(self.template, self.destination, paths)

        claude_skills = self.destination / ".claude" / "skills"
        claude_md = self.destination / "CLAUDE.md"

        self.assertTrue(
            (
                self.destination / ".agents" / "skills" / "raven-tool-bootstrap" / "SKILL.md"
            ).is_file()
        )
        self.assertTrue(claude_skills.is_symlink())
        self.assertEqual(os.readlink(claude_skills), "../.agents/skills")
        self.assertTrue((claude_skills / "raven-tool-bootstrap" / "SKILL.md").is_file())
        # CLAUDE.md is a plain @AGENTS.md import file, not a symlink (#253).
        self.assertFalse(claude_md.is_symlink())
        self.assertEqual(claude_md.read_text(encoding="utf-8").strip(), "@AGENTS.md")

    def test_override_path_can_overwrite_one_changed_file(self):
        target = self.destination / ".claude" / "scripts" / "raven-tool-check.py"
        target.parent.mkdir(parents=True)
        target.write_text("custom\n", encoding="utf-8")

        raven.copy_paths(self.template, self.destination, [".claude/scripts/raven-tool-check.py"])

        self.assertEqual(
            target.read_text(encoding="utf-8"),
            (self.template / ".claude" / "scripts" / "raven-tool-check.py").read_text(
                encoding="utf-8"
            ),
        )

    def test_config_can_disable_components_and_exclude_paths(self):
        config_path = self.destination / ".raven" / "config.toml"
        config_path.parent.mkdir()
        config_path.write_text(
            """
schema = 1
template = "python"

[components]
hooks = false
mcp = false

[exclude]
paths = [".claude/agents/raven-security-reviewer.md"]
""".strip()
            + "\n",
            encoding="utf-8",
        )

        config = raven.load_config(self.destination)
        entries = [
            entry.relative
            for entry in raven.iter_template_entries(self.template, self.excludes, config)
        ]

        self.assertNotIn(".mcp.json", entries)
        self.assertFalse(any(path.startswith(".claude/hooks/") for path in entries))
        self.assertNotIn(".claude/agents/raven-security-reviewer.md", entries)
        self.assertIn(".claude/agents/raven-test-debugger.md", entries)

    def test_disabling_adapter_hooks_keeps_adapter_scripts(self):
        # Adapter helper scripts (raven-session.py, raven-skeleton.py,
        # raven-tool-check.py) are called by skills, not only by hooks, so
        # turning hook enforcement off must not silently remove them. They have
        # their own `scripts` switch; see config.toml.tmpl.
        config_path = self.destination / ".raven" / "config.toml"
        config_path.parent.mkdir()
        config_path.write_text(
            """
schema = 1
template = "python"

[components.claude]
hooks = false

[components.codex]
hooks = false
""".strip()
            + "\n",
            encoding="utf-8",
        )

        config = raven.load_config(self.destination)
        entries = [
            entry.relative
            for entry in raven.iter_template_entries(self.template, self.excludes, config)
        ]

        self.assertFalse(any(path.startswith(".claude/hooks/") for path in entries))
        self.assertFalse(any(path.startswith(".codex/hooks/") for path in entries))
        self.assertTrue(any(path.startswith(".claude/scripts/") for path in entries))
        self.assertTrue(any(path.startswith(".codex/scripts/") for path in entries))

    def test_config_can_disable_adapter_scripts_independently(self):
        config_path = self.destination / ".raven" / "config.toml"
        config_path.parent.mkdir()
        config_path.write_text(
            """
schema = 1
template = "python"

[components.claude]
scripts = false

[components.codex]
scripts = false
""".strip()
            + "\n",
            encoding="utf-8",
        )

        config = raven.load_config(self.destination)
        entries = [
            entry.relative
            for entry in raven.iter_template_entries(self.template, self.excludes, config)
        ]

        self.assertFalse(any(path.startswith(".claude/scripts/") for path in entries))
        self.assertFalse(any(path.startswith(".codex/scripts/") for path in entries))
        self.assertTrue(any(path.startswith(".claude/hooks/") for path in entries))
        self.assertTrue(any(path.startswith(".codex/hooks/") for path in entries))

    def _assert_codex_subdir_materializes_alone(self, subdir: str) -> None:
        """Install `.codex/<subdir>` with the Claude counterpart switched off.

        The regression the issue #165 design exists to prevent. The two adapters
        now share one copy of each byte-identical file, linked inside the
        template -- but `.claude/<subdir>` and `.codex/<subdir>` are
        independently toggleable components, so a Codex-only destination must
        receive real files, never symlinks into a `.claude/<subdir>/` that was
        never installed. See helpers.codex_symlink_target.
        """
        config_path = self.destination / ".raven" / "config.toml"
        config_path.parent.mkdir(exist_ok=True)
        config_path.write_text(
            f"""
schema = 1
template = "python"

[components.claude]
{subdir} = false
""".strip()
            + "\n",
            encoding="utf-8",
        )

        config = raven.load_config(self.destination)
        entries = [
            entry.relative
            for entry in raven.iter_template_entries(self.template, self.excludes, config)
        ]
        codex_paths = sorted(path for path in entries if path.startswith(f".codex/{subdir}/"))
        self.assertTrue(codex_paths, f"expected the Codex {subdir} to still install")
        self.assertFalse(any(path.startswith(f".claude/{subdir}/") for path in entries))

        raven.copy_paths(self.template, self.destination, codex_paths)

        self.assertFalse(
            (self.destination / ".claude" / subdir).exists(),
            f"the Claude {subdir} component was disabled; nothing may install it",
        )
        unified = UNIFIED_BY_SUBDIR[subdir]
        self.assertTrue(
            unified.issubset({Path(path).name for path in codex_paths}),
            "a unified file stopped installing under the Codex adapter",
        )
        for relative in codex_paths:
            name = Path(relative).name
            with self.subTest(path=relative):
                installed = self.destination / relative
                self.assertFalse(
                    installed.is_symlink(),
                    f"{relative} installed as a symlink; it would dangle here",
                )
                self.assertTrue(installed.is_file())
                if name not in unified:
                    # A non-unified file (e.g. the Claude-only read guard) has
                    # no canonical cross-adapter copy, so only the unified
                    # ones can be compared byte-for-byte with it.
                    continue
                canonical = raven.REPO_ROOT / "common" / ".claude" / subdir / name
                self.assertEqual(installed.read_bytes(), canonical.read_bytes())

    def test_codex_scripts_materialize_without_the_claude_adapter(self):
        self._assert_codex_subdir_materializes_alone("scripts")

    def test_codex_hooks_materialize_without_the_claude_adapter(self):
        self._assert_codex_subdir_materializes_alone("hooks")

    def test_config_can_disable_agent_specific_components(self):
        config_path = self.destination / ".raven" / "config.toml"
        config_path.parent.mkdir()
        config_path.write_text(
            """
schema = 1
template = "python"

[components.claude]
settings = false
hooks = false
scripts = false
subagents = false
rules = false

[components.codex]
config = false
hooks = false
scripts = false
subagents = false
rules = false
""".strip()
            + "\n",
            encoding="utf-8",
        )

        config = raven.load_config(self.destination)
        entries = [
            entry.relative
            for entry in raven.iter_template_entries(self.template, self.excludes, config)
        ]

        self.assertNotIn(".claude/settings.json", entries)
        self.assertFalse(any(path.startswith(".claude/hooks/") for path in entries))
        self.assertFalse(any(path.startswith(".claude/scripts/") for path in entries))
        self.assertFalse(any(path.startswith(".claude/agents/") for path in entries))
        self.assertFalse(any(path.startswith(".claude/rules/") for path in entries))
        self.assertNotIn(".codex/config.toml", entries)
        self.assertNotIn(".codex/hooks.json", entries)
        self.assertFalse(any(path.startswith(".codex/hooks/") for path in entries))
        self.assertFalse(any(path.startswith(".codex/scripts/") for path in entries))
        self.assertFalse(any(path.startswith(".codex/agents/") for path in entries))
        self.assertFalse(any(path.startswith(".codex/rules/") for path in entries))
        self.assertIn(".agents/skills/raven-tool-bootstrap/SKILL.md", entries)

    def test_excludes_generated_files_anywhere(self):
        template = self.destination / "template"
        template.mkdir()
        (template / "keep.txt").write_text("keep\n", encoding="utf-8")
        (template / ".DS_Store").write_text("ignore\n", encoding="utf-8")
        cache = template / "pkg" / "__pycache__"
        cache.mkdir(parents=True)
        (cache / "ignored.pyc").write_text("ignore\n", encoding="utf-8")
        ruff_cache = template / ".ruff_cache"
        ruff_cache.mkdir()
        (ruff_cache / "ignored").write_text("ignore\n", encoding="utf-8")

        entries = raven.iter_template_entries(template, set())

        self.assertEqual([entry.relative for entry in entries], ["keep.txt"])

    def test_conflict_fixture_preserves_existing_files_and_writes_guidance(self):
        (self.destination / "AGENTS.md").write_text("# Existing AGENTS\n", encoding="utf-8")
        (self.destination / "CLAUDE.md").write_text("# Existing CLAUDE\n", encoding="utf-8")
        existing_skill = self.destination / ".claude" / "skills" / "existing-skill"
        existing_skill.mkdir(parents=True)
        (existing_skill / "SKILL.md").write_text("existing skill\n", encoding="utf-8")
        output = io.StringIO()

        with contextlib.redirect_stdout(output):
            rc = raven._run(
                self.destination,
                raven.load_config(self.destination),
                "python",
                False,
                False,
                [],
                adopt_claude_requested=False,
                prompt_claude=False,
            )

        self.assertEqual(rc, 0, output.getvalue())
        self.assertEqual(
            (self.destination / "AGENTS.md").read_text(encoding="utf-8"), "# Existing AGENTS\n"
        )
        self.assertEqual(
            (self.destination / "CLAUDE.md").read_text(encoding="utf-8"), "# Existing CLAUDE\n"
        )
        self.assertEqual(
            (existing_skill / "SKILL.md").read_text(encoding="utf-8"), "existing skill\n"
        )
        self.assertTrue(
            (
                self.destination / ".claude" / "skills" / "raven-tool-bootstrap" / "SKILL.md"
            ).is_file()
        )
        self.assertTrue((self.destination / ".raven" / "merge" / "AGENTS.md.patch").is_file())
        self.assertTrue((self.destination / ".raven" / "merge" / "CLAUDE.md.raven").is_file())
        self.assertIn("Manual merge still required", output.getvalue())


def _classification(**overrides):
    fields = {
        "will_copy": [],
        "will_upgrade": [],
        "identical": [],
        "needs_merge": [],
        "unknown_existing": [],
        "excluded": [],
    }
    fields.update(overrides)
    return raven.Classification(**fields)


class BuildApplyPlanTests(unittest.TestCase):
    def test_claude_symlink_conflict_respects_overrides(self):
        classification = _classification(needs_merge=["CLAUDE.md", "AGENTS.md"])
        self.assertTrue(raven.claude_conflict(classification, []))
        # An explicit override for CLAUDE.md removes it from the conflict set.
        self.assertFalse(raven.claude_conflict(classification, ["CLAUDE.md"]))

    def test_build_apply_plan_is_pure_and_routes_overrides(self):
        classification = _classification(
            will_copy=["a.md"], will_upgrade=["b.md"], needs_merge=["c.md"]
        )
        plan = raven.build_apply_plan(
            classification,
            ["c.md"],
            existing_overrides={"c.md"},
            adopt_claude=False,
        )
        self.assertEqual(plan.will_copy, ["a.md"])
        self.assertEqual(plan.overwritten, ["c.md"])
        self.assertEqual(plan.needs_merge, [])  # removed by override
        self.assertFalse(plan.adopt_claude)

    def test_build_apply_plan_adopts_claude_symlink_when_decided(self):
        classification = _classification(needs_merge=["CLAUDE.md"])
        plan = raven.build_apply_plan(
            classification, [], existing_overrides=set(), adopt_claude=True
        )
        self.assertTrue(plan.adopt_claude)
        self.assertNotIn("CLAUDE.md", plan.needs_merge)

    def test_local_only_files_get_no_guided_merge(self):
        classification = _classification(local_only=["notes.md"], needs_merge=["real.md"])
        plan = raven.build_apply_plan(
            classification, [], existing_overrides=set(), adopt_claude=False
        )
        # local_only is left untouched: it carries no merge artifact, while a
        # genuine needs_merge file still does.
        self.assertNotIn("notes.md", plan.guided_merge_paths)
        self.assertIn("real.md", plan.guided_merge_paths)
        self.assertEqual(plan.effective_classification.local_only, ["notes.md"])


def _entries(*relatives):
    return {rel: raven.TemplateEntry(rel, Path("/nonexistent") / rel) for rel in relatives}


class InvalidOverridesTests(unittest.TestCase):
    """`invalid_overrides` decides which override paths `_run` must reject."""

    def test_no_requested_overrides_are_all_valid(self):
        self.assertEqual(invalid_overrides(_entries("AGENTS.md"), []), [])

    def test_only_paths_absent_from_entries_are_invalid(self):
        entries = _entries("AGENTS.md", ".mcp.json")
        self.assertEqual(
            invalid_overrides(entries, [".mcp.json", "nope.md", "AGENTS.md", "docs/gone.md"]),
            ["nope.md", "docs/gone.md"],
        )

    def test_empty_entries_make_every_request_invalid(self):
        self.assertEqual(invalid_overrides({}, ["AGENTS.md"]), ["AGENTS.md"])


class SymlinkAdoptionDecisionTests(unittest.TestCase):
    """The CLAUDE.md symlink-adoption decision, separated from the prompt."""

    def test_skips_when_adoption_is_not_needed(self):
        for requested in (False, True):
            for conflict in (False, True):
                self.assertEqual(
                    _adoption_decision(needed=False, conflict=conflict, requested=requested),
                    "skip",
                )

    def test_skips_when_needed_but_no_conflict(self):
        for requested in (False, True):
            self.assertEqual(
                _adoption_decision(needed=True, conflict=False, requested=requested),
                "skip",
            )

    def test_auto_adopts_when_pre_authorized(self):
        self.assertEqual(_adoption_decision(needed=True, conflict=True, requested=True), "auto")

    def test_prompts_when_needed_and_conflicting_but_not_pre_authorized(self):
        self.assertEqual(_adoption_decision(needed=True, conflict=True, requested=False), "prompt")


class BuildRunPlanTests(RavenTestCase):
    """`_build_run_plan` computes every precondition `_run` checks before writing."""

    def _plan(self, adopt_claude=False):
        return _build_run_plan(
            self.destination,
            _classification(will_copy=["AGENTS.md"]),
            [],
            set(),
            adopt_claude,
        )

    def test_clean_destination_has_no_blocking_preconditions(self):
        run_plan = self._plan()

        self.assertEqual(run_plan.collisions, [])
        self.assertEqual(run_plan.state_symlinks, [])
        self.assertFalse(run_plan.backup_conflict)
        self.assertEqual(run_plan.plan.will_copy, ["AGENTS.md"])

    def test_reports_ancestor_collision_for_state_writes(self):
        (self.destination / ".raven").write_text("not a directory\n", encoding="utf-8")

        self.assertEqual(self._plan().collisions, [".raven"])

    def test_reports_symlinked_state_files(self):
        (self.destination / ".raven").mkdir()
        (self.destination / ".raven" / "config.toml").symlink_to("/outside/config.toml")

        run_plan = self._plan()

        self.assertEqual(run_plan.collisions, [])
        self.assertEqual(run_plan.state_symlinks, [".raven/config.toml"])

    def test_backup_conflict_only_when_adopting_over_an_existing_backup(self):
        (self.destination / raven.CLAUDE_BACKUP_PATH).write_text("old\n", encoding="utf-8")

        self.assertFalse(self._plan(adopt_claude=False).backup_conflict)
        self.assertTrue(self._plan(adopt_claude=True).backup_conflict)

    def test_no_backup_conflict_when_adopting_without_a_backup(self):
        self.assertFalse(self._plan(adopt_claude=True).backup_conflict)


class SettingsJsonClassificationTests(RavenTestCase):
    """#200: a pre-existing hand-written .claude/settings.json needs adoption
    consent instead of falling into the generic unknown_existing/guided-merge
    path that every other untracked file (e.g. .mcp.json) still uses.
    """

    def test_pre_existing_untracked_settings_json_needs_adoption(self):
        (self.destination / ".claude").mkdir(parents=True)
        (self.destination / ".claude" / "settings.json").write_text(
            '{"custom": true}\n', encoding="utf-8"
        )

        classification = raven.classify(self.template, self.destination, self.excludes)

        self.assertIn(".claude/settings.json", classification.needs_adoption)
        self.assertNotIn(".claude/settings.json", classification.unknown_existing)
        self.assertNotIn(".claude/settings.json", classification.needs_merge)

    def test_settings_json_content_identical_to_template_is_identical(self):
        template_settings = (self.template / ".claude" / "settings.json").read_text(
            encoding="utf-8"
        )
        (self.destination / ".claude").mkdir(parents=True)
        (self.destination / ".claude" / "settings.json").write_text(
            template_settings, encoding="utf-8"
        )

        classification = raven.classify(self.template, self.destination, self.excludes)

        self.assertIn(".claude/settings.json", classification.identical)
        self.assertNotIn(".claude/settings.json", classification.needs_adoption)

    def test_missing_settings_json_still_will_copy(self):
        classification = raven.classify(self.template, self.destination, self.excludes)

        self.assertIn(".claude/settings.json", classification.will_copy)
        self.assertNotIn(".claude/settings.json", classification.needs_adoption)


class SettingsJsonAdoptionUnitTests(RavenTestCase):
    """Unit tests for `adopt_settings_json`, mirroring `ClaudeSymlinkTests`."""

    def _entries(self):
        return raven.entries_for_destination(
            self.template, self.excludes, raven.load_config(self.destination), self.destination
        )

    def test_first_install_writes_template_with_no_backup(self):
        entries = self._entries()

        changed = raven.adopt_settings_json(self.destination, entries)

        self.assertEqual(changed, [".claude/settings.json"])
        self.assertFalse((self.destination / ".claude" / "settings.json.bak").exists())
        self.assertEqual(
            (self.destination / ".claude" / "settings.json").read_text(encoding="utf-8"),
            (self.template / ".claude" / "settings.json").read_text(encoding="utf-8"),
        )

    def test_backs_up_existing_file_byte_for_byte(self):
        (self.destination / ".claude").mkdir(parents=True)
        original = '{"custom": "hand-written", "keep": [1, 2, 3]}\n'
        (self.destination / ".claude" / "settings.json").write_text(original, encoding="utf-8")
        entries = self._entries()

        changed = raven.adopt_settings_json(self.destination, entries)

        self.assertEqual(changed, [".claude/settings.json.bak", ".claude/settings.json"])
        # Byte-for-byte: the backup must be provably lossless.
        self.assertEqual(
            (self.destination / ".claude" / "settings.json.bak").read_bytes(),
            original.encode("utf-8"),
        )
        self.assertEqual(
            (self.destination / ".claude" / "settings.json").read_text(encoding="utf-8"),
            (self.template / ".claude" / "settings.json").read_text(encoding="utf-8"),
        )

    def test_refuses_to_overwrite_existing_backup(self):
        (self.destination / ".claude").mkdir(parents=True)
        (self.destination / ".claude" / "settings.json").write_text(
            '{"custom": true}\n', encoding="utf-8"
        )
        (self.destination / ".claude" / "settings.json.bak").write_text(
            "existing backup\n", encoding="utf-8"
        )
        entries = self._entries()

        with self.assertRaises(FileExistsError):
            raven.adopt_settings_json(self.destination, entries)

        self.assertEqual(
            (self.destination / ".claude" / "settings.json").read_text(encoding="utf-8"),
            '{"custom": true}\n',
        )
        self.assertEqual(
            (self.destination / ".claude" / "settings.json.bak").read_text(encoding="utf-8"),
            "existing backup\n",
        )

    def test_already_matching_template_is_a_noop(self):
        (self.destination / ".claude").mkdir(parents=True)
        (self.destination / ".claude" / "settings.json").write_text(
            (self.template / ".claude" / "settings.json").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        entries = self._entries()

        changed = raven.adopt_settings_json(self.destination, entries)

        self.assertEqual(changed, [])
        self.assertFalse((self.destination / ".claude" / "settings.json.bak").exists())


class SettingsJsonAdoptionRunTests(RavenTestCase):
    """`_run`-level integration for .claude/settings.json adoption (#200)."""

    def test_run_leaves_pre_existing_settings_json_untouched_without_consent(self):
        (self.destination / "AGENTS.md").write_text("# Existing AGENTS\n", encoding="utf-8")
        (self.destination / ".claude").mkdir(parents=True)
        original = '{"custom": true}\n'
        (self.destination / ".claude" / "settings.json").write_text(original, encoding="utf-8")
        output = io.StringIO()

        with contextlib.redirect_stdout(output):
            rc = raven._run(
                self.destination,
                raven.load_config(self.destination),
                "python",
                False,
                False,
                [],
                prompt_settings_json=False,
            )

        self.assertEqual(rc, 0)
        self.assertEqual(
            (self.destination / ".claude" / "settings.json").read_text(encoding="utf-8"), original
        )
        self.assertFalse((self.destination / ".claude" / "settings.json.bak").exists())
        # No merge artifact for this path: adoption, not guided merge, is the fix.
        self.assertFalse(
            (self.destination / ".raven" / "merge" / ".claude" / "settings.json.diff").exists()
        )
        self.assertIn("--adopt-settings-json", output.getvalue())

    def test_run_with_adopt_settings_json_backs_up_and_installs_template(self):
        (self.destination / "AGENTS.md").write_text("# Existing AGENTS\n", encoding="utf-8")
        (self.destination / ".claude").mkdir(parents=True)
        original = '{"custom": true}\n'
        (self.destination / ".claude" / "settings.json").write_text(original, encoding="utf-8")
        output = io.StringIO()

        with contextlib.redirect_stdout(output):
            rc = raven._run(
                self.destination,
                raven.load_config(self.destination),
                "python",
                False,
                False,
                [],
                adopt_settings_json_requested=True,
                prompt_settings_json=False,
            )

        self.assertEqual(rc, 0)
        self.assertEqual(
            (self.destination / ".claude" / "settings.json.bak").read_text(encoding="utf-8"),
            original,
        )
        self.assertEqual(
            (self.destination / ".claude" / "settings.json").read_text(encoding="utf-8"),
            (self.template / ".claude" / "settings.json").read_text(encoding="utf-8"),
        )
        self.assertIn("Adopted .claude/settings.json", output.getvalue())
        manifest = raven.load_manifest(self.destination)
        self.assertIn(".claude/settings.json", manifest.get("files", {}))

    def test_run_with_adopt_settings_json_fails_if_backup_exists(self):
        (self.destination / "AGENTS.md").write_text("# Existing AGENTS\n", encoding="utf-8")
        (self.destination / ".claude").mkdir(parents=True)
        (self.destination / ".claude" / "settings.json").write_text(
            '{"custom": true}\n', encoding="utf-8"
        )
        (self.destination / ".claude" / "settings.json.bak").write_text(
            "existing backup\n", encoding="utf-8"
        )
        output = io.StringIO()

        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            rc = raven._run(
                self.destination,
                raven.load_config(self.destination),
                "python",
                False,
                False,
                [],
                adopt_settings_json_requested=True,
                prompt_settings_json=False,
            )

        self.assertEqual(rc, 2)
        self.assertEqual(
            (self.destination / ".claude" / "settings.json").read_text(encoding="utf-8"),
            '{"custom": true}\n',
        )
        self.assertEqual(
            (self.destination / ".claude" / "settings.json.bak").read_text(encoding="utf-8"),
            "existing backup\n",
        )
        self.assertIn("settings.json.bak already exists", output.getvalue())

    def test_dry_run_with_adopt_settings_json_reports_without_writing(self):
        (self.destination / "AGENTS.md").write_text("# Existing AGENTS\n", encoding="utf-8")
        (self.destination / ".claude").mkdir(parents=True)
        original = '{"custom": true}\n'
        (self.destination / ".claude" / "settings.json").write_text(original, encoding="utf-8")
        output = io.StringIO()

        with contextlib.redirect_stdout(output):
            rc = raven._run(
                self.destination,
                raven.load_config(self.destination),
                "python",
                False,
                True,
                [],
                adopt_settings_json_requested=True,
                prompt_settings_json=False,
            )

        self.assertEqual(rc, 0)
        self.assertEqual(
            (self.destination / ".claude" / "settings.json").read_text(encoding="utf-8"), original
        )
        self.assertFalse((self.destination / ".claude" / "settings.json.bak").exists())
        self.assertIn("Would adopt .claude/settings.json", output.getvalue())

    def test_clean_install_writes_settings_json_as_managed_no_merge_artifact(self):
        output = io.StringIO()

        with contextlib.redirect_stdout(output):
            rc = raven._run(
                self.destination, raven.load_config(self.destination), "python", False, False, []
            )

        self.assertEqual(rc, 0)
        self.assertTrue((self.destination / ".claude" / "settings.json").is_file())
        manifest = raven.load_manifest(self.destination)
        self.assertIn(".claude/settings.json", manifest.get("files", {}))
        self.assertFalse((self.destination / ".raven" / "merge").exists())

    def test_first_install_gitignores_settings_local_json(self):
        with contextlib.redirect_stdout(io.StringIO()):
            raven._run(
                self.destination, raven.load_config(self.destination), "python", False, False, []
            )

        gitignore = (self.destination / ".gitignore").read_text(encoding="utf-8")
        self.assertIn(".claude/settings.local.json", gitignore.splitlines())

    def test_adoption_gitignores_settings_local_json(self):
        (self.destination / "AGENTS.md").write_text("# Existing AGENTS\n", encoding="utf-8")
        (self.destination / ".claude").mkdir(parents=True)
        (self.destination / ".claude" / "settings.json").write_text(
            '{"custom": true}\n', encoding="utf-8"
        )

        with contextlib.redirect_stdout(io.StringIO()):
            raven._run(
                self.destination,
                raven.load_config(self.destination),
                "python",
                False,
                False,
                [],
                adopt_settings_json_requested=True,
                prompt_settings_json=False,
            )

        gitignore = (self.destination / ".gitignore").read_text(encoding="utf-8")
        self.assertIn(".claude/settings.local.json", gitignore.splitlines())

    def test_upgrade_after_local_hand_edit_uses_reconcile_state_not_new_code(self):
        # Decision #4: once adopted, reconcile_state's existing 3-way logic
        # must own this file on every subsequent run -- a local hand-edit after
        # adoption with the template unchanged is `local_only`, exactly like
        # any other Raven-managed file, with no #200-specific code involved.
        (self.destination / "AGENTS.md").write_text("# Existing AGENTS\n", encoding="utf-8")
        (self.destination / ".claude").mkdir(parents=True)
        (self.destination / ".claude" / "settings.json").write_text(
            '{"custom": true}\n', encoding="utf-8"
        )
        with contextlib.redirect_stdout(io.StringIO()):
            raven._run(
                self.destination,
                raven.load_config(self.destination),
                "python",
                False,
                False,
                [],
                adopt_settings_json_requested=True,
                prompt_settings_json=False,
            )

        (self.destination / ".claude" / "settings.json").write_text(
            '{"hand-edited-after-adoption": true}\n', encoding="utf-8"
        )

        classification = raven.classify(self.template, self.destination, self.excludes)

        self.assertIn(".claude/settings.json", classification.local_only)
        self.assertNotIn(".claude/settings.json", classification.unknown_existing)
        self.assertNotIn(".claude/settings.json", classification.needs_adoption)
        self.assertNotIn(".claude/settings.json", classification.needs_merge)

    def test_second_run_after_adoption_is_identical_never_unknown_existing_or_re_prompted(self):
        # Decision #4 / judgment call #4: prove the second `raven upgrade`
        # after adoption classifies the file as identical (upgrade-clean, like
        # any other template file), never re-prompts, and never double-backs-up.
        (self.destination / "AGENTS.md").write_text("# Existing AGENTS\n", encoding="utf-8")
        (self.destination / ".claude").mkdir(parents=True)
        original = '{"custom": true}\n'
        (self.destination / ".claude" / "settings.json").write_text(original, encoding="utf-8")

        with contextlib.redirect_stdout(io.StringIO()):
            first_rc = raven._run(
                self.destination,
                raven.load_config(self.destination),
                "python",
                False,
                False,
                [],
                adopt_settings_json_requested=True,
                prompt_settings_json=False,
            )
        self.assertEqual(first_rc, 0)

        classification = raven.classify(self.template, self.destination, self.excludes)
        self.assertIn(".claude/settings.json", classification.identical)
        self.assertNotIn(".claude/settings.json", classification.unknown_existing)
        self.assertNotIn(".claude/settings.json", classification.needs_adoption)

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            second_rc = raven._run(
                self.destination,
                raven.load_config(self.destination),
                "python",
                False,
                False,
                [],
                # No adopt_settings_json_requested and no prompt override: if
                # the second run still needed consent, a non-interactive test
                # process answers "no" to any prompt reached, which would then
                # surface as a spurious re-adoption request in the output.
            )

        self.assertEqual(second_rc, 0)
        self.assertNotIn("Adopted .claude/settings.json", output.getvalue())
        self.assertNotIn("--adopt-settings-json", output.getvalue())
        # The original backup from the first adoption is untouched -- no
        # second backup was ever attempted.
        self.assertEqual(
            (self.destination / ".claude" / "settings.json.bak").read_text(encoding="utf-8"),
            original,
        )


class BuildApplyPlanSettingsJsonTests(unittest.TestCase):
    """`build_apply_plan`'s settings.json adoption branch, isolated from the filesystem."""

    def test_adopts_settings_json_when_decided(self):
        classification = _classification(needs_adoption=[".claude/settings.json"])
        plan = raven.build_apply_plan(
            classification,
            [],
            existing_overrides=set(),
            adopt_claude=False,
            adopt_settings_json=True,
        )
        self.assertTrue(plan.adopt_settings_json)
        self.assertNotIn(".claude/settings.json", plan.effective_classification.needs_adoption)

    def test_leaves_needs_adoption_when_not_decided(self):
        classification = _classification(needs_adoption=[".claude/settings.json"])
        plan = raven.build_apply_plan(
            classification,
            [],
            existing_overrides=set(),
            adopt_claude=False,
            adopt_settings_json=False,
        )
        self.assertFalse(plan.adopt_settings_json)
        self.assertIn(".claude/settings.json", plan.effective_classification.needs_adoption)

    def test_override_removes_settings_json_from_needs_adoption(self):
        classification = _classification(needs_adoption=[".claude/settings.json"])
        plan = raven.build_apply_plan(
            classification,
            [".claude/settings.json"],
            existing_overrides={".claude/settings.json"},
            adopt_claude=False,
            adopt_settings_json=False,
        )
        self.assertNotIn(".claude/settings.json", plan.effective_classification.needs_adoption)
        self.assertIn(".claude/settings.json", plan.overwritten)


if __name__ == "__main__":
    unittest.main()
