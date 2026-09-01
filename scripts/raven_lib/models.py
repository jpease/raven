"""Frozen dataclasses shared across the installer/upgrader: no behavior, just shape.

Each type documents the fields a stage of `template` -> `apply` -> `plan` -> `report`
hands to the next; grouping them here (rather than beside their producing function)
keeps the pipeline's data contracts visible in one place.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class TemplateEntry:
    """One template-relative file or symlink discovered by `iter_template_entries`."""

    relative: str
    source: Path
    copy_as_symlink: bool = False


@dataclass(frozen=True)
class Fingerprint:
    """Content identity of a file or symlink: KIND_FILE/KIND_SYMLINK + hash."""

    kind: str
    sha256: str
    target: str | None = None


@dataclass(frozen=True)
class ManifestRecord:
    """The upgrade-relevant fields of one entry in manifest.json's files map."""

    kind: str
    installed_sha256: str
    target: str | None = None
    source_sha256: str | None = None


@dataclass(frozen=True)
class SourceSpec:
    """One ``[sources.<name>]`` declaration: an externally-installed guidance library.

    The section suffix is the source's name (``[sources.superpowers]`` declares
    the plugin ``superpowers``), so this record carries no name field of its
    own. ``kind`` says how to look for it -- ``"claude-plugin"`` is the only
    recognized value today. ``required`` raises a missing source from WARN to
    ERROR in `doctor`, for a repository whose workflow genuinely depends on it.
    """

    kind: str
    required: bool = False


@dataclass(frozen=True)
class RavenConfig:
    """Parsed, defaulted view of ``.raven/config.toml`` (or its absence)."""

    template: str | None
    include_readme: bool
    components: dict[str, bool]
    claude_components: dict[str, bool]
    codex_components: dict[str, bool]
    exclude_paths: list[str]
    # None means the config has no explicit platform value (an absent
    # `[issue_tracker]` section, an absent `platform` key, or no config file
    # at all -- e.g. an install that predates platform gating). Distinct from
    # the explicit string "none": only an explicit value may drive
    # deactivation (see `deactivated._platform_gated`); unset never does.
    platform: str | None = None
    exists: bool = False
    # Appended last, after `exists`, and defaulted: `tests/test_orphans.py`
    # constructs RavenConfig positionally, so inserting a field anywhere
    # earlier would silently rebind those arguments. Keyed by the
    # `[sources.<name>]` section suffix; empty when the config declares none.
    sources: dict[str, SourceSpec] = field(default_factory=dict)


@dataclass(frozen=True)
class RavenBlock:
    """A located ``RAVEN:BEGIN``/``RAVEN:END`` managed block within a host file.

    ``start``/``end`` are line indices into the host file's text, so callers can
    splice a replacement without re-parsing. ``declared_sha256`` is the hash the
    BEGIN marker itself claims, which may be stale or absent -- it is not
    recomputed here, only carried, so drift detection can compare it against the
    actual content hash.
    """

    start: int
    end: int
    content: str
    declared_sha256: str | None


@dataclass(frozen=True)
class Classification:
    """Destination-relative paths bucketed by what an install/upgrade would do to each."""

    will_copy: list[str]
    will_upgrade: list[str]
    identical: list[str]
    needs_merge: list[str]
    unknown_existing: list[str]
    excluded: list[str]
    # Files the user modified locally while the template is unchanged from the
    # recorded baseline. There is nothing upstream to merge, so upgrade leaves
    # them untouched and writes no guided-merge artifact; doctor reports them
    # informationally rather than as drift requiring action.
    local_only: list[str] = field(default_factory=list)
    # Files that exist, differ from the template, and have no manifest record --
    # currently only ever `.claude/settings.json` (#200). Unlike
    # `unknown_existing`, these never get a guided-merge artifact: Raven can
    # take the file over outright (backup-then-replace) given consent, so there
    # is nothing to hand-merge. Left untouched without consent.
    needs_adoption: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class OrphanClassification:
    """Manifest-tracked files the current template no longer ships.

    ``will_remove``: destination still matches the recorded baseline and the
    baseline is not a customization, so upgrade can safely delete it.
    ``orphan_modified``: destination differs from the baseline or the baseline
    is a customization; upgrade reports and keeps it. ``already_gone``: the file
    is absent on disk, so only the stale manifest record needs pruning.
    """

    will_remove: list[str]
    orphan_modified: list[str]
    already_gone: list[str]


@dataclass(frozen=True)
class DeactivatedClassification:
    """Manifest-tracked skills the template still ships but the current config no longer selects.

    Distinct from `OrphanClassification`: the template has not stopped shipping
    these files -- `shipped_relatives` stays policy-neutral on purpose (see its
    docstring) -- a platform or template config change simply no longer selects
    them for installation, e.g. switching ``platform`` from ``"github"`` to
    ``"gitlab"`` deactivates ``raven-github-issues`` without the template
    dropping it. Uses its own vocabulary, deliberately distinct from
    `OrphanClassification`'s, so the two paths can never be confused for one
    another at a call site.

    ``removable``: destination still matches the recorded baseline and the
    baseline is not a customization, so upgrade can safely delete it.
    ``preserved``: destination differs from the baseline, or the baseline is a
    customization, or there is no trustworthy baseline to compare against;
    upgrade reports and keeps it, same rule as `OrphanClassification.
    orphan_modified`. ``absent``: the file is already gone on disk, so only the
    stale manifest record needs pruning.

    ``stale`` and ``customized`` (#179) are informational *subsets* of
    ``preserved`` -- every path in either is also in ``preserved`` -- not a
    replacement for it, so every existing consumer that only looks at
    ``preserved`` keeps working unchanged. They distinguish *why* a preserved
    candidate failed the baseline check: ``stale`` means the recorded
    baseline is simply out of date while the on-disk content matches the
    *current* template source exactly (safe to refresh via ``raven accept``,
    never auto-removed); ``customized`` means the record itself declares a
    customization (``installedSha256 != sourceSha256``, e.g. an accepted
    manual merge). A ``preserved`` path in neither subset is a genuine local
    edit: content differs from both the recorded baseline and the current
    template.
    """

    removable: list[str]
    preserved: list[str]
    absent: list[str]
    stale: list[str] = field(default_factory=list)
    customized: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ApplyPlan:
    """A `Classification` resolved against override flags into a concrete apply plan.

    ``effective_classification`` is the `Classification` actually acted on --
    overrides can move paths between buckets (e.g. force an upgrade of a file
    that would otherwise need a guided merge) -- while the top-level lists here
    reflect the plan post-override.
    """

    requested_overrides: list[str]
    overwritten: list[str]
    newly_copied_overrides: list[str]
    will_copy: list[str]
    will_upgrade: list[str]
    identical: list[str]
    needs_merge: list[str]
    unknown_existing: list[str]
    effective_classification: Classification
    adopt_claude: bool
    guided_merge_paths: list[str]
    # Defaulted (unlike `adopt_claude`) so existing callers/fixtures
    # that predate #200 keep constructing an `ApplyPlan` without naming it.
    adopt_settings_json: bool = False

    @property
    def copied(self) -> list[str]:
        """All paths this plan will write as new files: fresh copies plus copied overrides."""
        return self.will_copy + self.newly_copied_overrides
