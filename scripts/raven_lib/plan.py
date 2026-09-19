"""Turn a `Classification` plus override flags into an `ApplyPlan`, then execute or report it.

Every report has a `render_*`/`print_*` pair -- see the module comment below --
and `apply_plan` is the one function here that actually writes to the
destination; everything else is either pure planning or pure text rendering.
"""

from __future__ import annotations

import sys
from pathlib import Path

from .apply import (
    adopt_file,
    adoption_needed,
    copy_paths,
)
from .blocks import (
    ensure_gitattributes_lines,
    ensure_ignore_lines,
    ensure_settings_local_gitignored,
    write_guided_merge_artifacts,
)
from .config import component_disabled
from .constants import (
    ADOPTABLE_BY_PATH,
    ADOPTABLE_FILES,
    GITATTRIBUTES_PATH,
    SETTINGS_JSON_PATH,
    AdoptableFile,
    _any_exists,
)
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
    adopted: list[str],
    identical: list[str],
    needs_merge: list[str],
    unknown_existing: list[str],
    removed_orphans: list[str],
    orphan_modified: list[str],
    removed_deactivated: list[str] | None = None,
    deactivated_preserved: list[str] | None = None,
    deactivated_stale: list[str] | None = None,
    deactivated_customized: list[str] | None = None,
    needs_adoption: list[str] | None = None,
) -> str:
    """The post-apply summary report text: only sections with content are included.

    ``adopted`` is every path an adoption wrote, backups included, in the
    order `apply_plan` wrote them.

    ``deactivated_preserved`` means, as of #179, only the genuinely-modified
    subset -- callers must exclude ``deactivated_stale``/``deactivated_
    customized`` from the raw `DeactivatedClassification.preserved` before
    passing it in. Those two are separate, informational dispositions with
    their own wording: a stale baseline is never described as "you modified
    them", and an accepted customization is a deliberate, acknowledged state.
    """
    removed_deactivated = removed_deactivated or []
    deactivated_preserved = deactivated_preserved or []
    deactivated_stale = deactivated_stale or []
    deactivated_customized = deactivated_customized or []
    needs_adoption = needs_adoption or []
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

    if adopted:
        sections.append(
            render_section(
                "Adopted as Raven-managed; each original file was backed up:",
                adopted,
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

    if needs_adoption:
        # The concrete invocation, not a `<path>` placeholder: this section is
        # the only place a live run tells the reader how to resolve these, and
        # they have to name each path anyway.
        adopt_flags = " ".join(f"--adopt {path}" for path in needs_adoption)
        sections.append(
            render_section(
                "!!! Needs consent to manage: these files exist but Raven does not yet own them, "
                f"and were left untouched (no merge artifact was written). Re-run with "
                f"`raven upgrade {adopt_flags}`, or accept the interactive prompt, to let Raven "
                "manage them. !!!",
                needs_adoption,
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

    if deactivated_stale:
        sections.append(
            render_section(
                "Deactivated by config; not removed because the recorded baseline is "
                "stale (on-disk content matches the current template exactly, so this "
                "was never a local edit) -- run `raven accept <path>` to refresh the "
                "baseline, then the next upgrade will remove it:",
                deactivated_stale,
            )
        )

    if deactivated_customized:
        sections.append(
            render_section(
                "Deactivated by config; kept as an accepted customization "
                "(recorded via `raven accept`; still shipped by the template):",
                deactivated_customized,
            )
        )

    return "\n\n".join(sections)


def print_apply_summary(
    copied: list[str],
    upgraded: list[str],
    overwritten: list[str],
    adopted: list[str],
    identical: list[str],
    needs_merge: list[str],
    unknown_existing: list[str],
    removed_orphans: list[str],
    orphan_modified: list[str],
    removed_deactivated: list[str] | None = None,
    deactivated_preserved: list[str] | None = None,
    deactivated_stale: list[str] | None = None,
    deactivated_customized: list[str] | None = None,
    needs_adoption: list[str] | None = None,
) -> None:
    """Print `render_apply_summary`'s output."""
    print(
        render_apply_summary(
            copied,
            upgraded,
            overwritten,
            adopted,
            identical,
            needs_merge,
            unknown_existing,
            removed_orphans,
            orphan_modified,
            removed_deactivated,
            deactivated_preserved,
            deactivated_stale,
            deactivated_customized,
            needs_adoption,
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
    if classification.needs_adoption:
        sections.append(
            render_section(
                "Needs consent to adopt as Raven-managed (existing file Raven does not yet own; "
                "left untouched, no merge artifact -- see `--adopt <path>`):",
                classification.needs_adoption,
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


def adoption_conflict(
    classification: Classification, requested_overrides: list[str], adoptable: AdoptableFile
) -> bool:
    """Whether ``adoptable`` still needs adoption consent after override removal.

    An explicit ``--override <path>`` already force-copies the file, so it
    resolves the question without any adoption prompt. What "unresolved" means
    depends on the kind: a ``root_instructions`` file is unresolved while it
    sits in ``needs_merge``/``unknown_existing`` (a guided merge would
    otherwise be written for it), a ``config`` file while it sits in
    ``needs_adoption``.
    """
    override_set = set(requested_overrides)
    if adoptable.kind == "config":
        return adoptable.path in (set(classification.needs_adoption) - override_set)
    conflicts = (
        set(classification.needs_merge) | set(classification.unknown_existing)
    ) - override_set
    return adoptable.path in conflicts


def build_apply_plan(
    classification: Classification,
    requested_overrides: list[str],
    existing_overrides: set[str],
    *,
    adopt_paths: list[str] | None = None,
) -> ApplyPlan:
    """Resolve a `Classification` and override flags into the concrete `ApplyPlan` to execute.

    Requested overrides are pulled out of every classification bucket first
    (they get their own copy/overwrite handling), then each adopted path is
    pulled out of whichever bucket held it -- ``needs_merge``/
    ``unknown_existing`` for a root instruction file, ``needs_adoption`` for a
    config file -- since each resolves its conflict a different way. Removal
    is keyed on the adoptable's own kind rather than on bucket membership, so
    a caller cannot turn a genuine local edit of a Raven-owned config into a
    silent overwrite by naming it here.
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
    needs_adoption = _without(classification.needs_adoption, override_set)

    adopted = sorted(set(adopt_paths or ()) - override_set)
    root_adopted = {p for p in adopted if ADOPTABLE_BY_PATH[p].kind == "root_instructions"}
    config_adopted = {p for p in adopted if ADOPTABLE_BY_PATH[p].kind == "config"}
    if root_adopted:
        needs_merge = [path for path in needs_merge if path not in root_adopted]
        unknown_existing = [path for path in unknown_existing if path not in root_adopted]
    if config_adopted:
        needs_adoption = [path for path in needs_adoption if path not in config_adopted]

    effective_classification = Classification(
        will_copy=will_copy,
        will_upgrade=will_upgrade,
        identical=identical,
        needs_merge=needs_merge,
        unknown_existing=unknown_existing,
        excluded=classification.excluded,
        local_only=local_only,
        needs_adoption=needs_adoption,
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
        guided_merge_paths=guided_merge_paths,
        adopt_paths=adopted,
    )


def render_dry_run_plan(
    plan: ApplyPlan,
    orphans: OrphanClassification,
    deactivated: DeactivatedClassification | None = None,
    *,
    adoption_notes: list[str] | None = None,
) -> str:
    """The dry-run report text.

    Pure: every filesystem question this report depends on is answered by the
    caller and arrives as ``adoption_notes`` -- the adoptable paths this run
    is *not* adopting but could, which `print_dry_run_plan` determines by
    probing the destination. That keeps the whole section-assembly -- which
    sections appear, in which order, with which wording -- testable without
    building a destination tree on disk.
    """
    deactivated = deactivated or DeactivatedClassification([], [], [], stale=[], customized=[])
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
    if plan.adopt_paths:
        writes: list[str] = []
        for path in plan.adopt_paths:
            writes.extend([ADOPTABLE_BY_PATH[path].backup_path, path])
        sections.append(
            render_section(
                "Would adopt as Raven-managed; each original file backed up:",
                writes,
            )
        )
    sections.append(render_dry_run_summary(plan.effective_classification))
    for path in adoption_notes or []:
        adoptable = ADOPTABLE_BY_PATH[path]
        sections.append(
            f"{path} exists but Raven does not own its content. Raven can leave it untouched, "
            f"or you can rerun with `--adopt {path}` to move it to {adoptable.backup_path} and "
            f"let Raven manage it. {adoptable.summary}"
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
    deactivated_modified = sorted(
        set(deactivated.preserved) - set(deactivated.stale) - set(deactivated.customized)
    )
    if deactivated_modified:
        sections.append(
            render_section(
                "Deactivated by config but locally modified; left in place (still "
                "shipped by the template — delete manually if unwanted):",
                deactivated_modified,
            )
        )
    if deactivated.stale:
        sections.append(
            render_section(
                "Deactivated by config; recorded baseline is stale but on-disk content "
                "matches the current template exactly (still shipped by the template) "
                "-- run `raven accept <path>` to refresh it, then a future upgrade will "
                "remove it:",
                deactivated.stale,
            )
        )
    if deactivated.customized:
        sections.append(
            render_section(
                "Deactivated by config; kept as an accepted customization (recorded "
                "via `raven accept`; still shipped by the template):",
                deactivated.customized,
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
    for path in plan.adopt_paths:
        adoptable = ADOPTABLE_BY_PATH[path]
        if _any_exists(destination / adoptable.backup_path):
            print(
                f"error: {adoptable.backup_path} already exists; remove it before adopting {path}.",
                file=sys.stderr,
            )
            return 2
    adoption_notes = [
        adoptable.path
        for adoptable in ADOPTABLE_FILES
        if adoptable.path not in plan.adopt_paths
        and _adoption_offerable(destination, classification, entries, adoptable)
    ]
    print(
        render_dry_run_plan(
            plan,
            orphans,
            deactivated,
            adoption_notes=adoption_notes,
        )
    )
    return 0


def _adoption_offerable(
    destination: Path,
    classification: Classification,
    entries: dict[str, TemplateEntry],
    adoptable: AdoptableFile,
) -> bool:
    """Whether ``adoptable`` is a live adoption offer for this destination.

    Same two-shape test `cli._run` applies when deciding whether to prompt: a
    config file is offerable while it sits in ``needs_adoption``; a root
    instruction file while it sits in ``needs_merge``/``unknown_existing``
    *and* the destination copy really differs from the template's.
    """
    if adoptable.kind == "config":
        return adoptable.path in set(classification.needs_adoption)
    return adoptable.path in set(classification.needs_merge) | set(
        classification.unknown_existing
    ) and adoption_needed(destination, entries, adoptable)


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

    Returns ``(exit_code, adopted, merge_artifacts, removed_orphans,
    removed_deactivated)``, where ``adopted`` is every path the adoptions
    wrote, backups included. Exit code 2 on an adoption-backup collision or a
    `ValueError` from `copy_paths` (an unsafe managed-block state) aborts
    before the manifest is touched, so a failed apply never records paths it
    did not actually write. Exit code 1 on an OSError during
    orphan/deactivated removal (e.g. a read-only parent directory) reports the
    failure without aborting: copies and upgrades land, the manifest is
    updated for everything that succeeded, failed paths are reported to stderr
    and omitted from removal, so their manifest records are retained for the
    next run to retry (#183).
    """
    adopted: list[str] = []
    adopted_targets: list[str] = []
    for path in plan.adopt_paths:
        adoptable = ADOPTABLE_BY_PATH[path]
        try:
            written = adopt_file(destination, entries, adoptable)
        except FileExistsError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2, adopted, [], [], []
        if written:
            adopted.extend(written)
            adopted_targets.append(path)

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
        return 2, adopted, [], [], []

    # Gitignore the user's local-overrides layer the moment Raven starts
    # owning settings.json -- fresh install or adoption -- not on every run
    # (see `ensure_settings_local_gitignored`).
    if SETTINGS_JSON_PATH in plan.will_copy or SETTINGS_JSON_PATH in adopted_targets:
        ensure_settings_local_gitignored(destination)

    # Merge Raven's required `.gitattributes` lines on every apply, not just
    # first install (#206): unlike the single fixed settings.local.json
    # gitignore entry above, `.gitattributes`' required set can grow in a
    # later Raven release, and an existing installation must pick up a newly
    # added line on its next upgrade -- that only happens if this runs every
    # time. Safe to do so: `ensure_gitattributes_lines` is a no-op read once
    # every required line is already present. Gated on the "hooks" component
    # (COMPONENT_PATHS registers `.gitattributes` there, see constants.py)
    # so a repo that declined hook enforcement is not handed .gitattributes
    # lines for hooks it never installed.
    if not component_disabled(GITATTRIBUTES_PATH, config):
        ensure_gitattributes_lines(destination)

    # `.ignore` merges on every apply for the same reason, and ungated (#238):
    # its negations cover `.agents/`, `.claude/`, `.codex/`, `.gemini/` and
    # `.raven/`, which span every component rather than belonging to one, and
    # `.raven/` exists in any installation regardless of what a config turns
    # off. A repo that declined a component keeps a negation for a directory
    # it does not have, which costs nothing -- an ignore rule for an absent
    # path is inert.
    ensure_ignore_lines(destination)

    failed_orphans: list[str] = []
    removed_orphans = remove_orphans(destination, orphans.will_remove, failed_orphans)
    # Deactivated-by-config skills reuse remove_orphans as-is: it is a pure
    # delete-and-prune-empty-parents filesystem primitive that does not care
    # *why* a path is being removed, only that the baseline safety gate
    # already cleared it (deactivated.removable, like orphans.will_remove, is
    # only ever populated by classify_deactivated's unmodified_baseline check).
    failed_deactivated: list[str] = []
    removed_deactivated = remove_orphans(destination, deactivated.removable, failed_deactivated)

    managed_paths = (
        plan.copied + plan.will_upgrade + plan.overwritten + plan.identical + adopted_targets
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
    # Return exit code 1 if any removals failed, otherwise 0.
    exit_code = 1 if (failed_orphans or failed_deactivated) else 0
    return (
        exit_code,
        adopted,
        merge_artifacts,
        removed_orphans,
        removed_deactivated,
    )


def normalize_override(path: str) -> str:
    """Normalize a user-supplied ``--override`` path to a template-relative POSIX form."""
    normalized = path.strip().replace("\\", "/")
    if normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized
