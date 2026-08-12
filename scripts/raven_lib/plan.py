"""Turn a `Classification` plus override flags into an `ApplyPlan`, then execute or report it.

Every report has a `render_*`/`print_*` pair -- see the module comment below --
and `apply_plan` is the one function here that actually writes to the
destination; everything else is either pure planning or pure text rendering.
"""

from __future__ import annotations

import sys
from pathlib import Path

from .apply import (
    adopt_claude_symlink,
    claude_symlink_adoption_needed,
    copy_paths,
)
from .blocks import write_guided_merge_artifacts
from .constants import CLAUDE_BACKUP_PATH, CLAUDE_PATH, _any_exists
from .manifest import update_manifest
from .models import (
    ApplyPlan,
    Classification,
    DeactivatedClassification,
    OrphanClassification,
    RavenConfig,
    TemplateEntry,
)
from .orphans import remove_orphans

# Rendering is kept separate from printing throughout this module: each
# `render_*` returns the exact text its `print_*` counterpart emits, so the
# report content can be asserted directly instead of through captured stdout.
# This mirrors report.py, where `render_human`/`render_json` build a string and
# the caller prints it. The `print_*` functions remain the module's public
# surface; nothing about the CLI's output or call sites changes.


def render_section(title: str, paths: list[str]) -> str:
    """A titled list of paths, or "(none)" under the title when the list is empty."""
    if not paths:
        return f"{title}\n  (none)"
    return "\n".join([title, *(f"  {path}" for path in paths)])


def print_section(title: str, paths: list[str]) -> None:
    """Print `render_section`'s output."""
    print(render_section(title, paths))


def render_apply_summary(
    copied: list[str],
    upgraded: list[str],
    overwritten: list[str],
    adopted_claude: list[str],
    identical: list[str],
    needs_merge: list[str],
    unknown_existing: list[str],
    removed_orphans: list[str],
    orphan_modified: list[str],
    removed_deactivated: list[str] | None = None,
    deactivated_preserved: list[str] | None = None,
) -> str:
    """The post-apply summary report text: only sections with content are included."""
    removed_deactivated = removed_deactivated or []
    deactivated_preserved = deactivated_preserved or []
    sections = [render_section(f"Copied {len(copied)} file(s):", copied)]

    if upgraded:
        sections.append(
            render_section(f"Upgraded {len(upgraded)} unchanged Raven-managed file(s):", upgraded)
        )

    if overwritten:
        sections.append(
            render_section(
                f"Overwrote {len(overwritten)} explicitly requested file(s):", overwritten
            )
        )

    if adopted_claude:
        sections.append(
            render_section(
                "Adopted CLAUDE.md compatibility symlink; original file was backed up:",
                adopted_claude,
            )
        )

    if identical:
        sections.append(render_section("Already up to date; not copied:", identical))

    if needs_merge:
        sections.append(
            render_section(
                "!!! Manual merge still required: you locally modified these Raven-managed files, "
                "so the upgrade left them untouched. See .raven/merge/<file>.diff for what changed. !!!",
                needs_merge,
            )
        )

    if unknown_existing:
        sections.append(
            render_section(
                "!!! Manual merge still required: these files exist but Raven does not manage them; "
                "the template ships its own version. Compare .raven/merge/<file>.diff before merging. !!!",
                unknown_existing,
            )
        )

    if removed_orphans:
        sections.append(
            render_section(
                f"Removed {len(removed_orphans)} orphaned file(s) the template no longer ships:",
                removed_orphans,
            )
        )

    if orphan_modified:
        sections.append(
            render_section(
                "Orphaned but left in place because you modified them "
                "(template no longer ships these; remove manually if unwanted):",
                orphan_modified,
            )
        )

    if removed_deactivated:
        sections.append(
            render_section(
                f"Removed {len(removed_deactivated)} skill(s) deactivated by config "
                "(still shipped by the template, but not selected by the current "
                "platform/template):",
                removed_deactivated,
            )
        )

    if deactivated_preserved:
        sections.append(
            render_section(
                "Deactivated by config but left in place because you modified them "
                "(still shipped by the template; remove manually if unwanted):",
                deactivated_preserved,
            )
        )

    return "\n\n".join(sections)


def print_apply_summary(
    copied: list[str],
    upgraded: list[str],
    overwritten: list[str],
    adopted_claude: list[str],
    identical: list[str],
    needs_merge: list[str],
    unknown_existing: list[str],
    removed_orphans: list[str],
    orphan_modified: list[str],
    removed_deactivated: list[str] | None = None,
    deactivated_preserved: list[str] | None = None,
) -> None:
    """Print `render_apply_summary`'s output."""
    print(
        render_apply_summary(
            copied,
            upgraded,
            overwritten,
            adopted_claude,
            identical,
            needs_merge,
            unknown_existing,
            removed_orphans,
            orphan_modified,
            removed_deactivated,
            deactivated_preserved,
        )
    )


def render_dry_run_summary(classification: Classification) -> str:
    """The ``--dry-run`` preview text for a `Classification`, before any override handling."""
    sections = [
        render_section("Will copy new Raven files:", classification.will_copy),
        render_section("Will upgrade unchanged Raven-managed files:", classification.will_upgrade),
        render_section("Already up to date; will not copy:", classification.identical),
        render_section(
            "Manual merge required (locally modified Raven-managed files; will be left untouched):",
            classification.needs_merge,
        ),
        render_section(
            "Manual merge required (existing files Raven does not manage; template ships its own version):",
            classification.unknown_existing,
        ),
    ]
    if classification.local_only:
        sections.append(
            render_section(
                "Locally customized; template unchanged, so left untouched (no merge needed):",
                classification.local_only,
            )
        )
    sections.append(
        "Preview only. Re-run without --dry-run to copy and upgrade files listed above."
    )
    return "\n\n".join(sections)


def print_dry_run_summary(classification: Classification) -> None:
    """Print `render_dry_run_summary`'s output."""
    print(render_dry_run_summary(classification))


def _without(paths: list[str], excluded: set[str]) -> list[str]:
    return sorted(set(paths) - excluded)


def claude_symlink_conflict(classification: Classification, requested_overrides: list[str]) -> bool:
    """Whether CLAUDE.md ends up needing a manual merge after override removal."""
    override_set = set(requested_overrides)
    conflicts = (
        set(classification.needs_merge) | set(classification.unknown_existing)
    ) - override_set
    return CLAUDE_PATH in conflicts


def build_apply_plan(
    classification: Classification,
    requested_overrides: list[str],
    existing_overrides: set[str],
    *,
    adopt_claude_symlink: bool,
) -> ApplyPlan:
    """Resolve a `Classification` and override flags into the concrete `ApplyPlan` to execute.

    Requested overrides are pulled out of every classification bucket first
    (they get their own copy/overwrite handling), then CLAUDE.md is pulled out
    of ``needs_merge``/``unknown_existing`` when symlink adoption is requested,
    since adoption resolves that conflict a different way.
    """
    override_set = set(requested_overrides)
    overwritten = sorted(path for path in requested_overrides if path in existing_overrides)
    newly_copied_overrides = sorted(path for path in requested_overrides if path not in overwritten)
    will_copy = _without(classification.will_copy, override_set)
    will_upgrade = _without(classification.will_upgrade, override_set)
    identical = _without(classification.identical, override_set)
    needs_merge = _without(classification.needs_merge, override_set)
    unknown_existing = _without(classification.unknown_existing, override_set)
    local_only = _without(classification.local_only, override_set)

    adopt_symlink = adopt_claude_symlink
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
        local_only=local_only,
    )
    guided_merge_paths = sorted(set(needs_merge) | set(unknown_existing))

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


def render_dry_run_plan(
    plan: ApplyPlan,
    orphans: OrphanClassification,
    deactivated: DeactivatedClassification | None = None,
    *,
    show_claude_symlink_note: bool,
) -> str:
    """The dry-run report text.

    Pure: every filesystem question this report depends on is answered by the
    caller and arrives as ``show_claude_symlink_note``. That keeps the whole
    section-assembly -- which sections appear, in which order, with which
    wording -- testable without building a destination tree on disk.
    """
    deactivated = deactivated or DeactivatedClassification([], [], [])
    sections = []
    if plan.requested_overrides:
        sections.append(
            render_section("Would overwrite explicitly requested file(s):", plan.overwritten)
        )
        sections.append(
            render_section(
                "Would copy explicitly requested missing file(s):",
                plan.newly_copied_overrides,
            )
        )
    if plan.adopt_claude_symlink:
        sections.append(
            render_section(
                "Would adopt CLAUDE.md compatibility symlink:", [CLAUDE_BACKUP_PATH, CLAUDE_PATH]
            )
        )
    sections.append(render_dry_run_summary(plan.effective_classification))
    if show_claude_symlink_note:
        sections.append(
            "CLAUDE.md exists as a regular destination file. Raven can leave it untouched, "
            "or you can rerun with --adopt-claude-symlink to move it to CLAUDE.md.bak and "
            "create the AGENTS.md symlink."
        )
    if plan.guided_merge_paths:
        sections.append(
            render_section(
                "Would write guided merge artifacts to .raven/merge/ for these conflicting files "
                "(.patch for instruction files, .diff for others):",
                plan.guided_merge_paths,
            )
        )
    if orphans.will_remove:
        sections.append(
            render_section(
                "Will remove orphaned Raven files (template no longer ships them; "
                "destination still matches the recorded baseline):",
                orphans.will_remove,
            )
        )
    if orphans.orphan_modified:
        sections.append(
            render_section(
                "Orphaned but locally modified; left in place (template no longer "
                "ships them, but you changed them — delete manually if unwanted):",
                orphans.orphan_modified,
            )
        )
    if deactivated.removable:
        sections.append(
            render_section(
                "Would remove skill(s) deactivated by config (still shipped by the "
                "template, but not selected by the current platform/template):",
                deactivated.removable,
            )
        )
    if deactivated.preserved:
        sections.append(
            render_section(
                "Deactivated by config but locally modified; left in place (still "
                "shipped by the template — delete manually if unwanted):",
                deactivated.preserved,
            )
        )
    return "\n\n".join(sections)


def print_dry_run_plan(
    destination: Path,
    classification: Classification,
    entries: dict[str, TemplateEntry],
    plan: ApplyPlan,
    orphans: OrphanClassification,
    deactivated: DeactivatedClassification | None = None,
) -> int:
    """Imperative shell: the filesystem probes and the failure exit code.

    The report itself is built by ``render_dry_run_plan``.
    """
    if plan.adopt_claude_symlink and _any_exists(destination / CLAUDE_BACKUP_PATH):
        print(
            f"error: {CLAUDE_BACKUP_PATH} already exists; "
            "remove it before adopting the CLAUDE.md symlink.",
            file=sys.stderr,
        )
        return 2
    show_claude_symlink_note = (
        not plan.adopt_claude_symlink
        and CLAUDE_PATH in set(classification.needs_merge) | set(classification.unknown_existing)
        and claude_symlink_adoption_needed(destination, entries)
    )
    print(
        render_dry_run_plan(
            plan, orphans, deactivated, show_claude_symlink_note=show_claude_symlink_note
        )
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
    orphans: OrphanClassification,
    deactivated: DeactivatedClassification,
) -> tuple[int, list[str], list[str], list[str], list[str]]:
    """Execute an `ApplyPlan`: copy/upgrade files, remove orphans, update the manifest, write merges.

    Returns ``(exit_code, adopted_claude, merge_artifacts, removed_orphans,
    removed_deactivated)``. Exit code 2 on a CLAUDE.md-backup collision or a
    `ValueError` from `copy_paths` (an unsafe managed-block state) aborts
    before the manifest is touched, so a failed apply never records paths it
    did not actually write.
    """
    adopted_claude: list[str] = []
    if plan.adopt_claude_symlink:
        try:
            adopted_claude = adopt_claude_symlink(destination, entries)
        except FileExistsError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2, [], [], [], []

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
        return 2, adopted_claude, [], [], []

    removed_orphans = remove_orphans(destination, orphans.will_remove)
    # Deactivated-by-config skills reuse remove_orphans as-is: it is a pure
    # delete-and-prune-empty-parents filesystem primitive that does not care
    # *why* a path is being removed, only that the baseline safety gate
    # already cleared it (deactivated.removable, like orphans.will_remove, is
    # only ever populated by classify_deactivated's unmodified_baseline check).
    removed_deactivated = remove_orphans(destination, deactivated.removable)

    managed_paths = (
        plan.copied
        + plan.will_upgrade
        + plan.overwritten
        + plan.identical
        + ([CLAUDE_PATH] if adopted_claude else [])
    )
    stale_records = (
        removed_orphans + orphans.already_gone + removed_deactivated + deactivated.absent
    )
    if managed_paths or stale_records:
        update_manifest(
            destination,
            template_name,
            template,
            excludes,
            config,
            managed_paths,
            manifest=manifest,
            entries=entries,
            remove=stale_records,
            preserve_identical_block_baseline=True,
        )

    merge_artifacts = write_guided_merge_artifacts(destination, entries, plan.guided_merge_paths)
    return 0, adopted_claude, merge_artifacts, removed_orphans, removed_deactivated


def normalize_override(path: str) -> str:
    """Normalize a user-supplied ``--override`` path to a template-relative POSIX form."""
    normalized = path.strip().replace("\\", "/")
    if normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized
