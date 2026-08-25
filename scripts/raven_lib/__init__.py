"""Raven's installer/upgrader library: package boundary and its public re-export surface.

Sub-modules keep single responsibilities (config parsing, manifest tracking, block
diffing, apply planning, ...); this file is the only place that assembles them into
one flat namespace, via ``__all__``, for ``raven.py`` and the test suite to import
from. It owns no logic of its own.
"""

from __future__ import annotations

from .apply import (
    adopt_claude_symlink,
    adopt_settings_json,
    classify,
    claude_symlink_adoption_needed,
    copy_paths,
    find_path_collisions,
    find_state_symlink_collisions,
    prompt_for_claude_symlink_adoption,
    prompt_for_settings_json_adoption,
    prompt_for_template_switch,
    reconcile_state,
)
from .assess import build_assess_findings
from .blocks import (
    append_patch_text,
    block_content_matches,
    block_managed_state,
    comparison_block_content,
    ensure_gitattributes_lines,
    ensure_ignore_lines,
    ensure_settings_local_gitignored,
    find_raven_block,
    guided_merge_instructions,
    normalized_block_content,
    pending_merge_paths,
    raven_block_is_unchanged,
    raven_block_sha256,
    raven_managed_block,
    remove_merge_artifacts,
    unified_diff_text,
    update_raven_block,
    write_guided_merge_artifacts,
)
from .cli import (
    _run,
    cmd_accept,
    cmd_doctor,
    cmd_fleet,
    cmd_init,
    cmd_install,
    cmd_upgrade,
    list_language_templates,
    main,
    select_language_interactively,
)
from .config import (
    ConfigError,
    _update_config_platform,
    build_config,
    component_disabled,
    config_excluded,
    default_config_text,
    load_config,
    parse_simple_toml,
    path_within,
    platform_excluded,
    replace_platform_line,
    template_excluded,
)
from .constants import (
    CLAUDE_BACKUP_PATH,
    CLAUDE_COMPONENT_PATHS,
    CLAUDE_PATH,
    CODEX_COMPONENT_PATHS,
    COMPONENT_PATHS,
    CONFIG_PATH,
    DEFAULT_CLAUDE_COMPONENTS,
    DEFAULT_CODEX_COMPONENTS,
    DEFAULT_COMPONENTS,
    DEFAULT_EXCLUDES,
    EXCLUDED_NAMES,
    GITATTRIBUTES_PATH,
    IGNORE_PATH,
    KIND_FILE,
    KIND_SYMLINK,
    MANIFEST_PATH,
    MERGE_DIR,
    MERGE_ONLY_TEMPLATE_PATHS,
    NON_TEMPLATE_DIRS,
    RAVEN_BLOCK_BEGIN_RE,
    RAVEN_BLOCK_END,
    REPO_ROOT,
    ROOT_INSTRUCTION_FILES,
    SETTINGS_JSON_BACKUP_PATH,
    SETTINGS_JSON_PATH,
    STARTER_TOOL_CONFIG_PATHS,
    _any_exists,
)
from .doctor import build_doctor_findings, merge_only_tracking_findings
from .findings import Finding, Severity, exit_code, summarize
from .fleet import build_fleet_findings, load_registry, register, registry_path
from .gates import gate_spec_for
from .git_hooks import detect_hook_manager, git_hooks_dir, hook_manager_guidance, install_git_hooks
from .hashing import (
    destination_fingerprint,
    entry_fingerprint,
    file_sha256,
    same_content,
    sha256_bytes,
)
from .manifest import (
    git_ref,
    load_manifest,
    parse_record,
    save_manifest,
    update_manifest,
)
from .models import (
    ApplyPlan,
    Classification,
    Fingerprint,
    ManifestRecord,
    RavenBlock,
    RavenConfig,
    SourceSpec,
    TemplateEntry,
)
from .plan import (
    apply_plan,
    build_apply_plan,
    claude_symlink_conflict,
    normalize_override,
    print_apply_summary,
    print_dry_run_plan,
    print_section,
    settings_json_adoption_conflict,
)
from .report import render_human, render_json
from .template import (
    entries_for_destination,
    iter_template_entries,
)
from .tracking import untracked_merge_only_paths

__all__ = [
    # constants
    "REPO_ROOT",
    "DEFAULT_EXCLUDES",
    "EXCLUDED_NAMES",
    "CONFIG_PATH",
    "MANIFEST_PATH",
    "MERGE_DIR",
    "ROOT_INSTRUCTION_FILES",
    "CLAUDE_PATH",
    "CLAUDE_BACKUP_PATH",
    "SETTINGS_JSON_PATH",
    "SETTINGS_JSON_BACKUP_PATH",
    "GITATTRIBUTES_PATH",
    "IGNORE_PATH",
    "MERGE_ONLY_TEMPLATE_PATHS",
    "RAVEN_BLOCK_BEGIN_RE",
    "RAVEN_BLOCK_END",
    "DEFAULT_COMPONENTS",
    "DEFAULT_CLAUDE_COMPONENTS",
    "DEFAULT_CODEX_COMPONENTS",
    "COMPONENT_PATHS",
    "STARTER_TOOL_CONFIG_PATHS",
    "CLAUDE_COMPONENT_PATHS",
    "CODEX_COMPONENT_PATHS",
    "NON_TEMPLATE_DIRS",
    "KIND_FILE",
    "KIND_SYMLINK",
    "_any_exists",
    # models
    "TemplateEntry",
    "RavenConfig",
    "RavenBlock",
    "Classification",
    "ApplyPlan",
    "Fingerprint",
    "ManifestRecord",
    "SourceSpec",
    # config
    "ConfigError",
    "parse_simple_toml",
    "build_config",
    "load_config",
    "default_config_text",
    "path_within",
    "component_disabled",
    "config_excluded",
    "platform_excluded",
    "template_excluded",
    "replace_platform_line",
    "_update_config_platform",
    # template
    "iter_template_entries",
    "entries_for_destination",
    # hashing
    "sha256_bytes",
    "file_sha256",
    "entry_fingerprint",
    "destination_fingerprint",
    "same_content",
    # blocks
    "normalized_block_content",
    "comparison_block_content",
    "block_content_matches",
    "raven_block_sha256",
    "raven_managed_block",
    "find_raven_block",
    "raven_block_is_unchanged",
    "block_managed_state",
    "update_raven_block",
    "append_patch_text",
    "unified_diff_text",
    "guided_merge_instructions",
    "write_guided_merge_artifacts",
    "pending_merge_paths",
    "remove_merge_artifacts",
    "ensure_settings_local_gitignored",
    "ensure_gitattributes_lines",
    "ensure_ignore_lines",
    # manifest
    "load_manifest",
    "git_ref",
    "save_manifest",
    "update_manifest",
    "parse_record",
    # gates
    "gate_spec_for",
    # apply
    "classify",
    "copy_paths",
    "find_path_collisions",
    "find_state_symlink_collisions",
    "reconcile_state",
    "claude_symlink_adoption_needed",
    "adopt_claude_symlink",
    "prompt_for_claude_symlink_adoption",
    "adopt_settings_json",
    "prompt_for_settings_json_adoption",
    "prompt_for_template_switch",
    # plan
    "print_section",
    "print_apply_summary",
    "build_apply_plan",
    "claude_symlink_conflict",
    "settings_json_adoption_conflict",
    "print_dry_run_plan",
    "apply_plan",
    "normalize_override",
    # git_hooks
    "detect_hook_manager",
    "git_hooks_dir",
    "hook_manager_guidance",
    "install_git_hooks",
    # cli
    "_run",
    "list_language_templates",
    "select_language_interactively",
    "cmd_init",
    "cmd_install",
    "cmd_upgrade",
    "cmd_accept",
    "cmd_doctor",
    "cmd_fleet",
    "main",
    # findings
    "Finding",
    "Severity",
    "exit_code",
    "summarize",
    # report
    "render_human",
    "render_json",
    # doctor / assess
    "build_doctor_findings",
    "build_assess_findings",
    # fleet
    "build_fleet_findings",
    "load_registry",
    "register",
    "registry_path",
    "merge_only_tracking_findings",
    "untracked_merge_only_paths",
]
