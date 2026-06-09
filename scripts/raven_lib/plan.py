from __future__ import annotations

import sys
from pathlib import Path

from .apply import (
    adopt_claude_symlink,
    claude_symlink_adoption_needed,
    copy_paths,
    prompt_for_claude_symlink_adoption,
)
from .blocks import write_guided_merge_artifacts
from .constants import CLAUDE_BACKUP_PATH, CLAUDE_PATH, ROOT_INSTRUCTION_FILES
from .manifest import update_manifest
from .models import ApplyPlan, Classification, RavenConfig, TemplateEntry


def print_section(title: str, paths: list[str]) -> None:
    print(title)
    if not paths:
        print("  (none)")
        return
    for path in paths:
        print(f"  {path}")


def print_apply_summary(
    copied: list[str],
    upgraded: list[str],
    overwritten: list[str],
    adopted_claude: list[str],
    identical: list[str],
    needs_merge: list[str],
    unknown_existing: list[str],
) -> None:
    print_section(f"Copied {len(copied)} file(s):", copied)

    if upgraded:
        print()
        print_section(f"Upgraded {len(upgraded)} unchanged Raven-managed file(s):", upgraded)

    if overwritten:
        print()
        print_section(f"Overwrote {len(overwritten)} explicitly requested file(s):", overwritten)

    if adopted_claude:
        print()
        print_section(
            "Adopted CLAUDE.md compatibility symlink; original file was backed up:", adopted_claude
        )

    if identical:
        print()
        print_section("Already up to date; not copied:", identical)

    if needs_merge:
        print()
        print_section(
            "!!! Manual merge still required for locally modified Raven-managed files. These were not copied. !!!",
            needs_merge,
        )

    if unknown_existing:
        print()
        print_section(
            "!!! Manual merge still required for existing files not known to be Raven-managed. "
            "These were not copied. !!!",
            unknown_existing,
        )


def print_dry_run_summary(classification: Classification) -> None:
    print_section("Will copy new Raven files:", classification.will_copy)
    print()
    print_section("Will upgrade unchanged Raven-managed files:", classification.will_upgrade)
    print()
    print_section("Already up to date; will not copy:", classification.identical)
    print()
    print_section(
        "Manual merge required; locally modified Raven-managed files:", classification.needs_merge
    )
    print()
    print_section(
        "Manual merge required; existing files not known to be Raven-managed:",
        classification.unknown_existing,
    )
    print()
    print("Preview only. Re-run without --dry-run to copy and upgrade files listed above.")


def _without(paths: list[str], excluded: set[str]) -> list[str]:
    return sorted(set(paths) - excluded)


def build_apply_plan(
    destination: Path,
    classification: Classification,
    requested_overrides: list[str],
    existing_overrides: set[str],
    symlink_adoption_needed: bool,
    adopt_claude_symlink_requested: bool,
    *,
    dry_run: bool,
    prompt_claude_symlink: bool,
) -> ApplyPlan:
    override_set = set(requested_overrides)
    overwritten = sorted(path for path in requested_overrides if path in existing_overrides)
    newly_copied_overrides = sorted(path for path in requested_overrides if path not in overwritten)
    will_copy = _without(classification.will_copy, override_set)
    will_upgrade = _without(classification.will_upgrade, override_set)
    identical = _without(classification.identical, override_set)
    needs_merge = _without(classification.needs_merge, override_set)
    unknown_existing = _without(classification.unknown_existing, override_set)

    adopt_symlink = False
    claude_conflicts = set(needs_merge) | set(unknown_existing)
    if CLAUDE_PATH in claude_conflicts and symlink_adoption_needed:
        if adopt_claude_symlink_requested:
            adopt_symlink = True
        elif not dry_run and prompt_claude_symlink:
            adopt_symlink = prompt_for_claude_symlink_adoption(destination)

    if adopt_symlink:
        needs_merge = [path for path in needs_merge if path != CLAUDE_PATH]
        unknown_existing = [path for path in unknown_existing if path != CLAUDE_PATH]

    effective_classification = Classification(
        will_copy=will_copy,
        will_upgrade=will_upgrade,
        identical=identical,
        needs_merge=needs_merge,
        unknown_existing=unknown_existing,
        excluded=classification.excluded,
    )
    guided_merge_paths = sorted((set(needs_merge) | set(unknown_existing)) & ROOT_INSTRUCTION_FILES)

    return ApplyPlan(
        requested_overrides=requested_overrides,
        overwritten=overwritten,
        newly_copied_overrides=newly_copied_overrides,
        will_copy=will_copy,
        will_upgrade=will_upgrade,
        identical=identical,
        needs_merge=needs_merge,
        unknown_existing=unknown_existing,
        effective_classification=effective_classification,
        adopt_claude_symlink=adopt_symlink,
        guided_merge_paths=guided_merge_paths,
    )


def print_dry_run_plan(
    destination: Path,
    classification: Classification,
    entries: dict[str, TemplateEntry],
    plan: ApplyPlan,
) -> int:
    if plan.requested_overrides:
        print_section("Would overwrite explicitly requested file(s):", plan.overwritten)
        print()
        print_section(
            "Would copy explicitly requested missing file(s):",
            plan.newly_copied_overrides,
        )
        print()
    if plan.adopt_claude_symlink:
        if (destination / CLAUDE_BACKUP_PATH).exists():
            print(
                f"error: {CLAUDE_BACKUP_PATH} already exists; "
                "remove it before adopting the CLAUDE.md symlink.",
                file=sys.stderr,
            )
            return 2
        print_section(
            "Would adopt CLAUDE.md compatibility symlink:", [CLAUDE_BACKUP_PATH, CLAUDE_PATH]
        )
        print()
    print_dry_run_summary(plan.effective_classification)
    if (
        not plan.adopt_claude_symlink
        and CLAUDE_PATH in set(classification.needs_merge) | set(classification.unknown_existing)
        and claude_symlink_adoption_needed(destination, entries)
    ):
        print()
        print(
            "CLAUDE.md exists as a regular destination file. Raven can leave it untouched, "
            "or you can rerun with --adopt-claude-symlink to move it to CLAUDE.md.bak and "
            "create the AGENTS.md symlink."
        )
    if plan.guided_merge_paths:
        print()
        print_section(
            "Would write guided merge artifacts for existing instruction files:",
            plan.guided_merge_paths,
        )
    return 0


def apply_plan(
    destination: Path,
    template_name: str,
    template: Path,
    excludes: set[str],
    config: RavenConfig,
    manifest: dict,
    entries: dict[str, TemplateEntry],
    plan: ApplyPlan,
) -> tuple[int, list[str], list[str]]:
    adopted_claude: list[str] = []
    if plan.adopt_claude_symlink:
        try:
            adopted_claude = adopt_claude_symlink(destination, entries)
        except FileExistsError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2, [], []

    try:
        if plan.requested_overrides:
            copy_paths(template, destination, plan.requested_overrides, config, entries=entries)
        if plan.will_copy:
            copy_paths(template, destination, plan.will_copy, config, entries=entries)
        if plan.will_upgrade:
            copy_paths(
                template,
                destination,
                plan.will_upgrade,
                config,
                entries=entries,
                update_managed_blocks=True,
            )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2, adopted_claude, []

    managed_paths = (
        plan.copied
        + plan.will_upgrade
        + plan.overwritten
        + plan.identical
        + ([CLAUDE_PATH] if adopted_claude else [])
    )
    if managed_paths:
        update_manifest(
            destination,
            template_name,
            template,
            excludes,
            config,
            managed_paths,
            manifest=manifest,
            entries=entries,
        )

    merge_artifacts = write_guided_merge_artifacts(destination, entries, plan.guided_merge_paths)
    return 0, adopted_claude, merge_artifacts


def normalize_override(path: str) -> str:
    normalized = path.strip().replace("\\", "/")
    if normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized
