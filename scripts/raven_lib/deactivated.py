"""Classify manifest-tracked skills the current config no longer selects.

An orphan (see ``orphans.py``) means the template stopped shipping a file at
all. A *deactivated* skill is a different, narrower situation: the template
still ships the file -- it would appear in ``shipped_relatives`` -- but this
destination's ``.raven/config.toml`` platform gate no longer selects it for
installation (``config.platform_excluded`` returns True for it). Switching
``platform`` from ``"github"`` to ``"gitlab"`` is the canonical example:
``raven-github-issues`` is still part of every template, it is just no longer
the active choice for this repository.

This module is deliberately its own classification path, not a variant of
``classify_orphans``: folding config-gated files into the orphan set would
make every config toggle look like a template removal, so a platform typo or
a transient config-read failure could delete user-visible files. The only
thing shared with ``orphans.py`` is the safety mechanism --
``unmodified_baseline`` -- that gates automatic removal; the shipped/orphan
sets themselves stay separate.

Scope is deliberately platform-only, matching issue #160: ``config.
template_excluded`` (the ``raven-dotfiles`` template gate) is not covered
here. The mechanism would be identical (see ``_platform_gated`` below), but
extending it needs its own review -- it is a separate config axis with its
own set of transitions to verify, and folding it in silently would mean this
change starts reporting drift for installs it was never asked to look at. A
future issue can extend ``_platform_gated`` (or add a sibling predicate) to
also call ``template_excluded``, and should add its own transition tests
(e.g. a template switch away from ``dotfiles``) the way this issue added the
four platform-transition tests.
"""

from __future__ import annotations

from pathlib import Path

from .config import platform_excluded
from .hashing import destination_fingerprint
from .manifest import parse_record
from .models import DeactivatedClassification, RavenConfig
from .orphans import _safe_relative, shipped_relatives, unmodified_baseline


def _platform_gated(relative: str, config: RavenConfig) -> bool:
    """Whether ``relative`` is currently excluded by the platform gate.

    Deliberately narrower than ``config.config_excluded``: it covers only the
    finite, hardcoded platform-gated skill directories (``platform_excluded``),
    never component toggles, the template gate, or arbitrary ``exclude_paths``
    globs. Those match much wider path sets (or, per this module's docstring,
    are an intentionally separate future extension), so folding them in here
    would let a much wider config change drive file removal.
    """
    return platform_excluded(relative, config)


def classify_deactivated(
    template: Path, destination: Path, manifest: dict, config: RavenConfig
) -> DeactivatedClassification:
    """Bucket manifest-tracked files the template still ships but this config no longer selects.

    The candidate set is the intersection of three things: manifest-tracked
    keys, still shipped by the template (``shipped_relatives``), and currently
    gated by platform config (``_platform_gated``). This is the deliberate
    complement of the orphan set -- it is never derived by subtracting the
    shipped set from the tracked set, which is exactly the ``classify_orphans``
    computation this function must not duplicate or feed into.

    Each candidate then goes through the same baseline-hash safety gate
    ``classify_orphans`` uses (via the shared ``unmodified_baseline``): an
    exact, non-customized match is safely removable by ``upgrade``; anything
    else -- a local edit, a customized baseline, or a legacy record with no
    trustworthy ``sourceSha256`` -- is reported and preserved, never deleted.
    An absent file only needs its stale manifest record pruned.

    Callers are trusted to have already validated ``config``: every call site
    in this codebase loads config through a path that reports and aborts on
    ``ConfigError`` before reaching here (``cli._load_config_or_report`` and
    ``doctor.build_doctor_findings`` both short-circuit on a config read
    failure), so a config that fails to parse never reaches this function and
    can never be misread as "everything is deactivated". A malformed
    ``manifest["files"]`` (not a dict) degrades to an empty classification
    rather than raising, matching ``classify_orphans``.
    """
    tracked = manifest.get("files", {})
    if not isinstance(tracked, dict):
        return DeactivatedClassification([], [], [])
    shipped = shipped_relatives(template, destination)
    candidates = sorted(key for key in tracked if key in shipped and _platform_gated(key, config))

    removable: list[str] = []
    preserved: list[str] = []
    absent: list[str] = []
    for relative in candidates:
        target = _safe_relative(destination, relative)
        if target is None:
            continue
        record = parse_record(tracked.get(relative))
        fingerprint = destination_fingerprint(target)
        if fingerprint is None:
            absent.append(relative)
        elif record is not None and unmodified_baseline(record, fingerprint):
            removable.append(relative)
        else:
            preserved.append(relative)
    return DeactivatedClassification(removable, preserved, absent)
