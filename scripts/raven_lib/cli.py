from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .apply import classify, claude_symlink_adoption_needed
from .config import _update_config_platform, default_config_text, load_config
from .constants import CONFIG_PATH, DEFAULT_EXCLUDES, NON_TEMPLATE_DIRS, REPO_ROOT, _any_exists
from .git_hooks import install_git_hooks
from .manifest import load_manifest
from .plan import (
    apply_plan,
    build_apply_plan,
    normalize_override,
    print_apply_summary,
    print_dry_run_plan,
    print_section,
)
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
            idx = int(raw) - 1
            if 0 <= idx < len(languages):
                return languages[idx]
        except (ValueError, EOFError):
            pass
        print(f"  Enter a number between 1 and {len(languages)}.")


def _parse_install_language(items: list[str]) -> tuple[str | None, list[str]]:
    if not items:
        return None, []
    first = items[0]
    candidate = REPO_ROOT / first
    if candidate.is_dir() and first not in NON_TEMPLATE_DIRS and not first.startswith("."):
        return first, items[1:]
    return None, items


def _run(
    destination: Path,
    template_name: str,
    include_readme: bool,
    dry_run: bool,
    requested_overrides: list[str],
    adopt_claude_symlink_requested: bool = False,
    prompt_claude_symlink: bool = True,
) -> int:
    config = load_config(destination)
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
    existing_overrides = {p for p in requested_overrides_norm if _any_exists(destination / p)}
    symlink_adoption_needed = claude_symlink_adoption_needed(destination, entries)
    plan = build_apply_plan(
        destination,
        classification,
        requested_overrides_norm,
        existing_overrides,
        symlink_adoption_needed,
        adopt_claude_symlink_requested,
        dry_run=dry_run,
        prompt_claude_symlink=prompt_claude_symlink,
    )

    print(f"Template: {template}")
    print(f"Destination: {destination}")
    print(f"Config: {destination / CONFIG_PATH}")
    print()

    if dry_run:
        return print_dry_run_plan(destination, classification, entries, plan)

    rc, adopted_claude, merge_artifacts = apply_plan(
        destination,
        template_name,
        template,
        excludes,
        config,
        manifest,
        entries,
        plan,
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
    )
    if merge_artifacts:
        print()
        print_section(
            "Wrote guided merge artifacts for existing instruction files:", merge_artifacts
        )
    if git_hooks_installed:
        print()
        print_section("Installed git hooks:", [f".git/hooks/{h}" for h in git_hooks_installed])

    return 0


def cmd_init(args: argparse.Namespace) -> int:
    destination = Path(args.destination).expanduser().resolve()
    if not destination.is_dir():
        print(f"error: destination directory does not exist: {destination}", file=sys.stderr)
        return 2
    config = load_config(destination)
    if config.exists:
        print(
            f"error: config already exists at {destination / CONFIG_PATH}; "
            "run `raven upgrade` to update managed files.",
            file=sys.stderr,
        )
        return 2
    language = args.language or select_language_interactively()
    template = REPO_ROOT / language
    if not template.is_dir():
        print(f"error: unknown language template: {language}", file=sys.stderr)
        return 2
    path = destination / CONFIG_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    platform = getattr(args, "platform", None) or "none"
    path.write_text(default_config_text(language, False, platform), encoding="utf-8")
    print(f"Created {destination / CONFIG_PATH}")
    return 0


def cmd_install(args: argparse.Namespace) -> int:
    destination = Path(args.destination).expanduser().resolve()
    if not destination.is_dir():
        print(f"error: destination directory does not exist: {destination}", file=sys.stderr)
        return 2

    install_items = getattr(args, "args", None)
    if install_items is None:
        install_items = ([args.language] if args.language is not None else []) + args.overrides
    language_arg, overrides = _parse_install_language(install_items)
    config = load_config(destination)

    platform = getattr(args, "platform", None)
    if config.exists:
        template_name = config.template or list_language_templates()[0]
        include_readme = args.include_readme or config.include_readme
        if platform is not None:
            _update_config_platform(destination / CONFIG_PATH, platform)
    else:
        language = language_arg or select_language_interactively()
        template_name = language
        include_readme = args.include_readme
        if not args.dry_run:
            init_args = argparse.Namespace(
                destination=str(destination), language=language, platform=platform
            )
            rc = cmd_init(init_args)
            if rc != 0:
                return rc
            config = load_config(destination)

    return _run(
        destination,
        template_name,
        include_readme,
        args.dry_run,
        overrides,
        adopt_claude_symlink_requested=args.adopt_claude_symlink,
    )


def cmd_upgrade(args: argparse.Namespace) -> int:
    destination = Path(args.destination).expanduser().resolve()
    if not destination.is_dir():
        print(f"error: destination directory does not exist: {destination}", file=sys.stderr)
        return 2
    config = load_config(destination)
    if not config.exists:
        print(
            "error: no .raven/config.toml found; run `raven install <language>` "
            "to set up Raven first.",
            file=sys.stderr,
        )
        return 2
    template_name = config.template or list_language_templates()[0]
    include_readme = args.include_readme or config.include_readme
    return _run(
        destination,
        template_name,
        include_readme,
        args.dry_run,
        args.overrides,
        adopt_claude_symlink_requested=args.adopt_claude_symlink,
    )


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

Supported languages:
  {supported_languages}

Run "raven COMMAND --help" for command-specific arguments and examples.

If this repository's scripts directory is not on PATH yet, use:
  /path/to/raven/scripts/raven install python --dry-run

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

    args = parser.parse_args()

    if args.command == "init":
        return cmd_init(args)
    if args.command == "install":
        return cmd_install(args)
    if args.command == "upgrade":
        return cmd_upgrade(args)
    return 1
