from __future__ import annotations

import argparse
import platform
import sys
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from .apply import (
    classify,
    claude_symlink_adoption_needed,
    find_path_collisions,
    prompt_for_claude_symlink_adoption,
)
from .assess import build_assess_findings
from .blocks import pending_merge_paths, remove_merge_artifacts
from .config import ConfigError, _update_config_platform, default_config_text, load_config
from .constants import (
    CLAUDE_BACKUP_PATH,
    CLAUDE_PATH,
    CONFIG_PATH,
    DEFAULT_EXCLUDES,
    MANIFEST_PATH,
    MERGE_DIR,
    NON_TEMPLATE_DIRS,
    REPO_ROOT,
    _any_exists,
)
from .doctor import build_doctor_findings
from .findings import exit_code
from .git_hooks import detect_hook_manager, git_hooks_dir, hook_manager_guidance, install_git_hooks
from .manifest import load_manifest, update_manifest
from .models import ApplyPlan, RavenConfig
from .orphans import classify_orphans
from .plan import (
    apply_plan,
    build_apply_plan,
    claude_symlink_conflict,
    normalize_override,
    print_apply_summary,
    print_dry_run_plan,
    print_section,
)
from .report import render_human, render_json, supports_unicode_marks
from .template import entries_for_destination


def list_language_templates() -> list[str]:
    return sorted(
        d.name
        for d in REPO_ROOT.iterdir()
        if d.is_dir() and not d.name.startswith(".") and d.name not in NON_TEMPLATE_DIRS
    )


def select_language_interactively() -> str:
    if not sys.stdin.isatty():
        print(
            "error: language required; pass it as an argument (e.g. raven install python)",
            file=sys.stderr,
        )
        sys.exit(2)
    languages = list_language_templates()
    if not languages:
        print("error: no language templates found in Raven repo", file=sys.stderr)
        sys.exit(2)
    print("Available language templates:")
    for i, lang in enumerate(languages, 1):
        print(f"  {i}. {lang}")
    while True:
        try:
            raw = input("Select language: ").strip()
        except EOFError:
            print(
                "error: language required; pass it as an argument (e.g. raven install python)",
                file=sys.stderr,
            )
            sys.exit(2)
        try:
            idx = int(raw) - 1
            if 0 <= idx < len(languages):
                return languages[idx]
        except ValueError:
            pass
        print(f"  Enter a number between 1 and {len(languages)}.")


def _parse_install_language(items: list[str]) -> tuple[str | None, list[str]]:
    if not items:
        return None, []
    first = items[0]
    if first in list_language_templates():
        return first, items[1:]
    return None, items


def _load_config_or_report(destination: Path) -> RavenConfig | None:
    """Load config, reporting a malformed file as an error instead of raising."""
    try:
        return load_config(destination)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return None


def _config_template_or_report(destination: Path, config: RavenConfig) -> str | None:
    """Template name from an existing config, or None (after reporting) if absent.

    A present config that yields no template (a missing ``template`` line or an
    unreadable file) must not silently fall back to the first language template.
    """
    if config.template is None:
        print(
            f"error: {destination / CONFIG_PATH} does not configure a template; "
            "set a valid `template` value or re-run `raven install <language>`.",
            file=sys.stderr,
        )
        return None
    return config.template


def _planned_write_paths(plan: ApplyPlan) -> list[str]:
    """Destination-relative paths a live apply of ``plan`` would create or write."""
    paths: set[str] = set(plan.will_copy) | set(plan.will_upgrade) | set(plan.requested_overrides)
    paths.add(CONFIG_PATH.as_posix())
    paths.add(MANIFEST_PATH.as_posix())
    paths.update((MERGE_DIR / relative).as_posix() for relative in plan.guided_merge_paths)
    if plan.adopt_claude_symlink:
        paths.add(CLAUDE_PATH)
    return sorted(paths)


def _run(
    destination: Path,
    template_name: str,
    include_readme: bool,
    dry_run: bool,
    requested_overrides: list[str],
    adopt_claude_symlink_requested: bool = False,
    prompt_claude_symlink: bool = True,
    platform_override: str | None = None,
    write_config: Callable[[], int] | None = None,
) -> int:
    config = load_config(destination)
    if platform_override is not None:
        # The effective config reflects the requested platform's skill gating
        # for both dry-run previews and the live plan; the durable write happens
        # only after validation passes (see write_config below).
        config = replace(config, platform=platform_override)
    # Fresh installs have config.template=None until after _create_config writes it.
    # Apply the template being installed so template-gated skills are correctly
    # included or excluded in both dry-run and live runs.
    config = replace(config, template=config.template or template_name)
    template = REPO_ROOT / template_name
    excludes = set() if include_readme else DEFAULT_EXCLUDES

    if not template.is_dir():
        print(f"Unknown language template: {template_name}", file=sys.stderr)
        return 2

    requested_overrides_norm = sorted(
        {n for path in requested_overrides if (n := normalize_override(path))}
    )
    entries = entries_for_destination(template, excludes, config, destination)
    invalid_overrides = [path for path in requested_overrides_norm if path not in entries]
    if invalid_overrides:
        print(
            "Invalid override path(s); each override must be an included file in the selected template:",
            file=sys.stderr,
        )
        for path in invalid_overrides:
            print(f"  {path}", file=sys.stderr)
        return 2

    manifest = load_manifest(destination)
    classification = classify(
        template, destination, excludes, config, manifest=manifest, entries=entries
    )
    orphans = classify_orphans(template, destination, manifest)
    existing_overrides = {p for p in requested_overrides_norm if _any_exists(destination / p)}
    symlink_adoption_needed = claude_symlink_adoption_needed(destination, entries)
    adopt_claude_symlink = False
    if symlink_adoption_needed and claude_symlink_conflict(
        classification, requested_overrides_norm
    ):
        if adopt_claude_symlink_requested:
            adopt_claude_symlink = True
        elif not dry_run and prompt_claude_symlink:
            adopt_claude_symlink = prompt_for_claude_symlink_adoption(destination)
    plan = build_apply_plan(
        classification,
        requested_overrides_norm,
        existing_overrides,
        adopt_claude_symlink=adopt_claude_symlink,
    )

    # Preflight the whole write set before printing the plan or touching the
    # destination, so a path collision fails the same way for dry-run and live
    # and never leaves a partial install behind.
    collisions = find_path_collisions(destination, _planned_write_paths(plan))
    if collisions:
        print(
            "error: existing paths block directories Raven must create; nothing was written:",
            file=sys.stderr,
        )
        for path in collisions:
            reason = (
                "is a symlink; writes would escape the destination"
                if (destination / path).is_symlink()
                else "exists but is not a directory"
            )
            print(f"  {path} ({reason})", file=sys.stderr)
        return 2

    print(f"Template: {template}")
    print(f"Destination: {destination}")
    print(f"Config: {destination / CONFIG_PATH}")
    print()

    if dry_run:
        return print_dry_run_plan(destination, classification, entries, plan, orphans)

    # Validation has passed. Reject a doomed symlink adoption before any durable
    # write, then write configuration only once the request is known good, so a
    # rejected install leaves config and managed files unchanged.
    if plan.adopt_claude_symlink and _any_exists(destination / CLAUDE_BACKUP_PATH):
        print(
            f"error: {CLAUDE_BACKUP_PATH} already exists; "
            "remove it before adopting the CLAUDE.md symlink.",
            file=sys.stderr,
        )
        return 2

    if write_config is not None:
        rc = write_config()
        if rc != 0:
            return rc

    rc, adopted_claude, merge_artifacts, removed_orphans = apply_plan(
        destination,
        template_name,
        template,
        excludes,
        config,
        manifest,
        entries,
        plan,
        orphans,
    )
    if rc != 0:
        return rc

    git_hooks_installed = install_git_hooks(destination)

    print_apply_summary(
        plan.copied,
        plan.will_upgrade,
        plan.overwritten,
        adopted_claude,
        plan.identical,
        plan.needs_merge,
        plan.unknown_existing,
        removed_orphans,
        orphans.orphan_modified,
    )
    if merge_artifacts:
        print()
        print_section(
            "Wrote guided merge artifacts to .raven/merge/ "
            "(review each .diff or .patch, merge what applies, then delete them):",
            merge_artifacts,
        )
    if git_hooks_installed:
        print()
        # install_git_hooks only reports installed hooks once it has resolved a
        # concrete hooks dir, so this cannot be None here.
        hooks_dir = git_hooks_dir(destination)
        assert hooks_dir is not None
        try:
            hooks_label = hooks_dir.relative_to(destination)
        except ValueError:
            hooks_label = hooks_dir
        print_section("Installed git hooks:", [f"{hooks_label}/{h}" for h in git_hooks_installed])
    else:
        manager = detect_hook_manager(destination)
        if manager:
            print()
            print_section(
                f"Hook manager detected ({manager}) -- Raven's hooks were not installed:",
                [hook_manager_guidance(manager)],
            )

    return 0


def _resolve_destination(args: argparse.Namespace) -> Path | None:
    destination = Path(args.destination).expanduser().resolve()
    if not destination.is_dir():
        print(f"error: destination directory does not exist: {destination}", file=sys.stderr)
        return None
    return destination


def _create_config(
    destination: Path, language: str, platform: str | None, include_readme: bool = False
) -> int:
    """Write a fresh .raven/config.toml for a known-missing destination config."""
    if language not in list_language_templates():
        print(f"error: unknown language template: {language}", file=sys.stderr)
        return 2
    path = destination / CONFIG_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        default_config_text(language, include_readme, platform or "none"), encoding="utf-8"
    )
    print(f"Created {destination / CONFIG_PATH}")
    return 0


def cmd_init(args: argparse.Namespace) -> int:
    destination = _resolve_destination(args)
    if destination is None:
        return 2
    config = _load_config_or_report(destination)
    if config is None:
        return 2
    if config.exists:
        print(
            f"error: config already exists at {destination / CONFIG_PATH}; "
            "run `raven upgrade` to update managed files.",
            file=sys.stderr,
        )
        return 2
    language = args.language or select_language_interactively()
    return _create_config(destination, language, getattr(args, "platform", None))


def cmd_install(args: argparse.Namespace) -> int:
    destination = _resolve_destination(args)
    if destination is None:
        return 2

    install_items = getattr(args, "args", None)
    if install_items is None:
        install_items = ([args.language] if args.language is not None else []) + args.overrides
    language_arg, overrides = _parse_install_language(install_items)
    config = _load_config_or_report(destination)
    if config is None:
        return 2

    platform = getattr(args, "platform", None)
    # Stage the durable config write as a callback so _run can defer it until the
    # whole request validates; a rejected install must change nothing on disk.
    if config.exists:
        template_name = _config_template_or_report(destination, config)
        if template_name is None:
            return 2
        if language_arg is not None and language_arg != template_name:
            print(
                f"error: {destination / CONFIG_PATH} already configures template "
                f"'{template_name}'; '{language_arg}' conflicts with it. Edit or remove "
                "the config to switch languages.",
                file=sys.stderr,
            )
            return 2
        include_readme = args.include_readme or config.include_readme

        def write_config() -> int:
            if platform is not None:
                _update_config_platform(destination / CONFIG_PATH, platform)
            return 0
    else:
        language = language_arg or select_language_interactively()
        template_name = language
        include_readme = args.include_readme

        def write_config() -> int:
            return _create_config(destination, language, platform, include_readme)

    return _run(
        destination,
        template_name,
        include_readme,
        args.dry_run,
        overrides,
        adopt_claude_symlink_requested=args.adopt_claude_symlink,
        platform_override=platform,
        write_config=write_config,
    )


def cmd_upgrade(args: argparse.Namespace) -> int:
    destination = _resolve_destination(args)
    if destination is None:
        return 2
    config = _load_config_or_report(destination)
    if config is None:
        return 2
    if not config.exists:
        print(
            "error: no .raven/config.toml found; run `raven install <language>` "
            "to set up Raven first.",
            file=sys.stderr,
        )
        return 2
    template_name = _config_template_or_report(destination, config)
    if template_name is None:
        return 2
    include_readme = args.include_readme or config.include_readme
    return _run(
        destination,
        template_name,
        include_readme,
        args.dry_run,
        args.overrides,
        adopt_claude_symlink_requested=args.adopt_claude_symlink,
    )


def cmd_accept(args: argparse.Namespace) -> int:
    destination = _resolve_destination(args)
    if destination is None:
        return 2
    config = _load_config_or_report(destination)
    if config is None:
        return 2
    if not config.exists:
        print(
            "error: no .raven/config.toml found; run `raven install <language>` first.",
            file=sys.stderr,
        )
        return 2
    template_name = _config_template_or_report(destination, config)
    if template_name is None:
        return 2
    template = REPO_ROOT / template_name
    include_readme = getattr(args, "include_readme", False) or config.include_readme
    excludes = set() if include_readme else DEFAULT_EXCLUDES
    config = replace(config, template=config.template or template_name)
    entries = entries_for_destination(template, excludes, config, destination)

    requested = (
        [normalize_override(path) for path in args.paths]
        if args.paths
        else pending_merge_paths(destination)
    )
    if not requested:
        print(
            "Nothing to accept: no paths given and no pending merges under "
            f"{MERGE_DIR.as_posix()}/."
        )
        return 0

    pending = set(pending_merge_paths(destination))
    accepted: list[str] = []
    stale: list[str] = []
    skipped: list[str] = []
    for relative in requested:
        if entries.get(relative) is None:
            if relative in pending:
                stale.append(relative)
            else:
                skipped.append(f"{relative} (not a Raven-managed template file)")
        elif not _any_exists(destination / relative):
            skipped.append(f"{relative} (no such file in destination)")
        else:
            accepted.append(relative)

    if args.dry_run:
        print_section("Would record as the accepted Raven baseline:", accepted)
        if stale:
            print()
            print_section("Would clear stale merge artifacts (no longer Raven-managed):", stale)
        if skipped:
            print()
            print_section("Would skip:", skipped)
        print(
            "\nPreview only. Re-run without --dry-run to update the manifest and remove artifacts."
        )
        return 0

    removed: list[str] = []
    if accepted:
        manifest = load_manifest(destination)
        update_manifest(
            destination,
            template_name,
            template,
            excludes,
            config,
            accepted,
            manifest=manifest,
            entries=entries,
        )
        removed.extend(remove_merge_artifacts(destination, accepted))
    if stale:
        removed.extend(remove_merge_artifacts(destination, stale))
        removed.sort()

    print_section("Recorded accepted Raven baseline for:", accepted)
    if removed:
        print()
        print_section("Removed merge artifacts:", removed)
    if stale:
        print()
        print_section("Cleared stale merge artifacts (no longer Raven-managed):", stale)
    if skipped:
        print()
        print_section("Skipped:", skipped)
    return 0


def _os_name() -> str:
    name = platform.system().lower()
    if name == "darwin":
        return "darwin"
    if name == "windows":
        return "windows"
    return "linux"


def _ascii_marks_needed() -> bool:
    return not supports_unicode_marks(getattr(sys.stdout, "encoding", None))


def cmd_doctor(args: argparse.Namespace) -> int:
    destination = _resolve_destination(args)
    if destination is None:
        return 2
    findings = build_doctor_findings(destination)
    output = (
        render_json("doctor", _os_name(), findings)
        if args.json
        else render_human("doctor", _os_name(), findings, ascii_marks=_ascii_marks_needed())
    )
    print(output)
    return exit_code(findings)


def cmd_assess(args: argparse.Namespace) -> int:
    destination = _resolve_destination(args)
    if destination is None:
        return 2
    findings = build_assess_findings(destination, run=args.run)
    output = (
        render_json("assess", _os_name(), findings)
        if args.json
        else render_human("assess", _os_name(), findings, ascii_marks=_ascii_marks_needed())
    )
    print(output)
    return exit_code(findings)


def main() -> int:
    supported_languages = ", ".join(list_language_templates())
    parser = argparse.ArgumentParser(
        prog="raven",
        usage="raven [OPTIONS] COMMAND [ARGS]...",
        description="Apply and safely upgrade Raven agent-instruction templates in a destination repository.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
Common commands:
  raven install <language> --dry-run
  raven install <language>
  raven upgrade --dry-run
  raven upgrade
  raven upgrade .claude/scripts/raven-tool-check.py
  raven accept
  raven doctor
  raven assess
  raven assess --run

Supported languages:
  {supported_languages}

Run "raven COMMAND --help" for command-specific arguments and examples.

If this repository's scripts directory is not on PATH yet, use:
  /path/to/raven/scripts/raven install python --dry-run
  /path/to/raven/scripts/raven install go --dry-run

File safety:
  - Dry runs never write files.
  - Existing project files are not overwritten by default.
  - Explicit override paths force-copy Raven-owned files.
  - Unchanged Raven-managed files can be upgraded automatically.
  - Locally changed Raven-managed files are reported for manual merge.
""",
    )
    parser.add_argument(
        "-d",
        "--destination",
        default=".",
        help="destination repository root; defaults to the current directory",
    )

    subparsers = parser.add_subparsers(
        dest="command", title="commands", metavar="COMMAND", required=True
    )

    init_parser = subparsers.add_parser(
        "init",
        usage="raven init [OPTIONS] [language]",
        help="create .raven/config.toml only",
        description="Create the destination repo's self-documented .raven/config.toml without copying template files.",
    )
    init_parser.add_argument(
        "language",
        nargs="?",
        default=None,
        help="language template (e.g. python, swift, rust, typescript, elixir); prompts interactively if omitted",
    )
    init_parser.add_argument(
        "--platform",
        choices=["github", "gitlab", "none"],
        default=None,
        help="issue-tracker platform: github, gitlab, or none (default: none)",
    )

    install_parser = subparsers.add_parser(
        "install",
        usage="raven install [OPTIONS] [language] [override ...]",
        help="first-time apply; creates config if needed and copies safe Raven files",
        description=(
            "Install a language template into the destination repo. Run with --dry-run first.\n"
            "Existing files are preserved unless they are explicitly named as override paths or\n"
            "--adopt-claude-symlink is approved for CLAUDE.md."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
Examples:
  raven install python --dry-run
  raven install python
  raven install go --dry-run
  raven install python --adopt-claude-symlink
  raven install python .claude/scripts/raven-tool-check.py

Language:
  Supported languages: {supported_languages}
  If no config exists, language is required in non-interactive shells.

Overrides:
  Override paths are template-relative files to force-copy. Use them only for
  files you know are Raven-owned.

AGENTS.md and CLAUDE.md:
  AGENTS.md is canonical; CLAUDE.md is normally installed as a symlink to it.
  If CLAUDE.md already exists, Raven leaves it untouched unless you pass
  --adopt-claude-symlink, which moves it to CLAUDE.md.bak first.
""",
    )
    install_parser.add_argument(
        "language",
        nargs="?",
        default=None,
        help="language template to install; prompts interactively if omitted and no config exists",
    )
    install_parser.add_argument(
        "overrides",
        nargs="*",
        metavar="override",
        help="template-relative file paths to force-copy",
    )
    install_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="preview categories, conflicts, and merge artifacts without writing files",
    )
    install_parser.add_argument(
        "--include-readme",
        action="store_true",
        help="include the language template README.md; overrides config include_readme=false",
    )
    install_parser.add_argument(
        "--adopt-claude-symlink",
        action="store_true",
        help=(
            "if CLAUDE.md exists, move it to CLAUDE.md.bak and create the CLAUDE.md -> "
            "AGENTS.md symlink; fails if backup exists"
        ),
    )
    install_parser.add_argument(
        "--platform",
        choices=["github", "gitlab", "none"],
        default=None,
        help="issue-tracker platform: github, gitlab, or none; updates existing config if already installed",
    )

    upgrade_parser = subparsers.add_parser(
        "upgrade",
        usage="raven upgrade [OPTIONS] [override ...]",
        help="apply newer Raven template files using manifest-safe upgrade rules",
        description=(
            "Upgrade an existing Raven installation using .raven/config.toml and .raven/manifest.json.\n"
            "Only unchanged Raven-managed files are upgraded automatically; local edits require manual merge."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  raven upgrade --dry-run
  raven upgrade
  raven upgrade --adopt-claude-symlink
  raven upgrade .claude/scripts/raven-tool-check.py

Override paths force-copy specific template-relative files. Use them only for
files you know are Raven-owned.

AGENTS.md and CLAUDE.md:
  AGENTS.md is canonical; CLAUDE.md is normally installed as a symlink to it.
  If CLAUDE.md already exists, Raven leaves it untouched unless you pass
  --adopt-claude-symlink, which moves it to CLAUDE.md.bak first.
""",
    )
    upgrade_parser.add_argument(
        "overrides",
        nargs="*",
        help="template-relative Raven-owned paths to force-copy even if locally modified",
    )
    upgrade_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="preview upgrade categories, conflicts, and merge artifacts without writing files",
    )
    upgrade_parser.add_argument(
        "--include-readme",
        action="store_true",
        help="include the language template README.md; overrides config include_readme=false",
    )
    upgrade_parser.add_argument(
        "--adopt-claude-symlink",
        action="store_true",
        help=(
            "if CLAUDE.md exists, move it to CLAUDE.md.bak and create the CLAUDE.md -> "
            "AGENTS.md symlink; fails if backup exists"
        ),
    )

    accept_parser = subparsers.add_parser(
        "accept",
        usage="raven accept [OPTIONS] [path ...]",
        help="record manually merged files as the accepted Raven baseline",
        description=(
            "After manually merging a conflicting file, record its current content as the\n"
            "accepted baseline so future upgrades stop prompting until the template changes."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  raven accept                      # accept every pending merge under .raven/merge/
  raven accept .mcp.json            # accept a specific file
  raven accept --dry-run

With no paths, Raven accepts every file that still has guided-merge artifacts under
.raven/merge/. Accepting records the current file as installed and the current
template as its source, then removes the merge artifacts.
""",
    )
    accept_parser.add_argument(
        "paths",
        nargs="*",
        help="destination-relative paths to accept; defaults to all pending merges",
    )
    accept_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="preview which files would be recorded; change nothing",
    )
    accept_parser.add_argument(
        "--include-readme",
        action="store_true",
        help="include the language template README.md when resolving template entries",
    )

    doctor_parser = subparsers.add_parser(
        "doctor",
        usage="raven doctor [OPTIONS]",
        help="diagnose Raven's install and the local toolchain",
        description=(
            "Read-only diagnostics for Raven's own installation and the local tooling.\n"
            "Exits non-zero only when the Raven install itself is broken."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    doctor_parser.add_argument("--json", action="store_true", help="print machine-readable JSON")

    assess_parser = subparsers.add_parser(
        "assess",
        usage="raven assess [OPTIONS]",
        help="grade the project against the active template's standards",
        description=(
            "Read-only scorecard of how well this project conforms to Raven's gate and\n"
            "convention expectations. Static by default; --run executes the gates."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    assess_parser.add_argument(
        "--run", action="store_true", help="execute the quality gates for a true pass/fail verdict"
    )
    assess_parser.add_argument("--json", action="store_true", help="print machine-readable JSON")

    args = parser.parse_args()

    if args.command == "init":
        return cmd_init(args)
    if args.command == "install":
        return cmd_install(args)
    if args.command == "upgrade":
        return cmd_upgrade(args)
    if args.command == "accept":
        return cmd_accept(args)
    if args.command == "doctor":
        return cmd_doctor(args)
    if args.command == "assess":
        return cmd_assess(args)
    return 1
