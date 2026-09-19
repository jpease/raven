"""Classify destination files against the template and copy the ones an apply should write.

`classify` is the read-only decision step (what state is each path in?);
`copy_paths` and the adoption helpers are the write step that acts on
that classification. Keeping them separate lets `plan`/`doctor` classify without
risking a write.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Literal

from .blocks import (
    BlockState,
    block_managed_state,
    ensure_skill_mirrors_gitignored,
    update_raven_block,
)
from .constants import (
    ADOPTABLE_CONFIG_PATHS,
    KIND_FILE,
    KIND_SYMLINK,
    SKILLS_COMPAT_PATH,
    SKILLS_SOURCE_PATH,
    AdoptableFile,
    _any_exists,
)
from .hashing import destination_fingerprint, entry_fingerprint, file_sha256, same_content
from .manifest import load_manifest, parse_record
from .models import Classification, Fingerprint, ManifestRecord, RavenConfig, TemplateEntry
from .template import entries_for_destination, iter_template_entries

ClassifyState = Literal[
    "will_copy",
    "will_upgrade",
    "identical",
    "needs_merge",
    "unknown_existing",
    "local_only",
    "needs_adoption",
]


def _fingerprint_matches(fingerprint: Fingerprint | None, record: ManifestRecord) -> bool:
    """Whether the destination fingerprint equals the recorded installed baseline."""
    if fingerprint is None or fingerprint.kind != record.kind:
        return False
    if fingerprint.kind == KIND_SYMLINK and fingerprint.target != record.target:
        return False
    return fingerprint.sha256 == record.installed_sha256


def reconcile_state(
    record: ManifestRecord,
    fingerprint: Fingerprint | None,
    template_fp: Fingerprint | None,
) -> ClassifyState:
    """3-way reconcile of a tracked non-managed-block file against its baseline.

    ``record`` is the manifest baseline (the destination and template content
    Raven last reconciled), ``fingerprint`` is the current destination, and
    ``template_fp`` is the current template. A baseline where ``installed`` and
    ``source`` differ marks a file the user has customized (e.g. an accepted
    manual merge), which must be re-merged rather than overwritten.
    """
    if record.source_sha256 is None:
        # Legacy manifest predating sourceSha256: fall back to the 2-way rule.
        return "will_upgrade" if _fingerprint_matches(fingerprint, record) else "needs_merge"

    template_changed = template_fp is None or template_fp.sha256 != record.source_sha256
    user_touched = not _fingerprint_matches(fingerprint, record)
    if (
        fingerprint is not None
        and template_fp is not None
        and fingerprint.kind == KIND_SYMLINK
        and template_fp.kind == KIND_FILE
    ):
        # A symlink standing where the template ships a regular file is drift,
        # never a customization: it holds no content of the user's to lose, and
        # it is the pre-#253 shape that a Windows checkout without symlink
        # support materializes as a file containing the literal target path.
        # Without this, a tree reverted to the symlink after its baseline had
        # already migrated reads as `local_only` -- template unchanged, file
        # "edited" -- and every future upgrade leaves it alone (#261).
        #
        # Deliberately one-directional. The mirror case, a regular file where
        # the template ships a symlink, can hold real content, so it keeps the
        # existing merge path rather than being overwritten here.
        return "will_upgrade"
    if not template_changed:
        # Raven's template is unchanged since the baseline. If the file still
        # matches the recorded baseline (e.g. an accepted manual merge) there is
        # nothing to do. A later local edit has nothing upstream to merge against,
        # so it is "local_only": upgrade leaves it untouched without manufacturing
        # a guided merge, and doctor reports it informationally.
        return "local_only" if user_touched else "identical"
    if user_touched:
        return "needs_merge"
    # Untouched since the baseline: take the new template unless the baseline is a
    # customization (installed != source) that an overwrite would destroy.
    customized = record.installed_sha256 != record.source_sha256
    return "needs_merge" if customized else "will_upgrade"


def _classify_entry(
    entry: TemplateEntry,
    manifest: dict,
    *,
    target_exists: bool,
    content_matches: bool,
    block_state: BlockState | None,
    fingerprint: Fingerprint | None,
    template_fp: Fingerprint | None,
) -> ClassifyState:
    if not target_exists:
        return "will_copy"
    if content_matches:
        return "identical"
    if block_state == "identical":
        return "identical"
    if block_state == "upgradeable":
        return "will_upgrade"
    record = parse_record(manifest.get("files", {}).get(entry.relative))
    if block_state == "modified":
        # A local edit inside the managed block normally means a guided merge.
        # But if `raven accept` already recorded this exact file as the
        # baseline and the template hasn't changed since, that acceptance
        # stands -- don't re-prompt on every upgrade (#63).
        if record is not None:
            reconciled = reconcile_state(record, fingerprint, template_fp)
            if reconciled in ("identical", "local_only"):
                return reconciled
        return "needs_merge"
    if record is None:
        # An untracked existing copy of an adoptable config file (#200, #273)
        # is a "whose file is this?" question, not a merge: Raven renders or
        # owns these wholesale, so it can take one over outright given
        # consent. Every other untracked file keeps the generic
        # unknown_existing/guided-merge path unchanged.
        if entry.relative in ADOPTABLE_CONFIG_PATHS:
            return "needs_adoption"
        return "unknown_existing"
    return reconcile_state(record, fingerprint, template_fp)


def _differs_only_by_final_newline(entry: TemplateEntry, target: Path) -> bool:
    """Whether ``target`` and the template differ only in trailing newline(s).

    A file installed by Raven that loses (or gains) its final newline -- a common
    editor/formatter artifact -- otherwise produces a guided merge with nothing
    substantive to resolve. When the content is identical apart from trailing
    newlines, upgrade can safely take the template instead of prompting.
    """
    if entry.copy_as_symlink or target.is_symlink():
        return False
    try:
        if entry.rendered_content is not None:
            src = entry.rendered_content
        else:
            src = entry.source.read_bytes()
        dst = target.read_bytes()
    except OSError:
        return False
    return src != dst and src.rstrip(b"\n") == dst.rstrip(b"\n")


def classify(
    template: Path,
    destination: Path,
    excludes: set[str],
    config: RavenConfig | None = None,
    manifest: dict | None = None,
    entries: dict[str, TemplateEntry] | None = None,
) -> Classification:
    """Bucket every template entry by what installing it at ``destination`` would do.

    Read-only: only inspects the filesystem and manifest, never writes. A path
    absent at the destination is ``will_copy``; present and matching the
    manifest baseline is ``will_upgrade`` (or ``identical`` if content is
    already current); present, locally modified, but with an unchanged
    template is ``local_only``; anything else present and untracked or
    diverged is ``needs_merge`` or ``unknown_existing``.
    """
    if manifest is None:
        manifest = load_manifest(destination)

    entry_iter = (
        entries.values()
        if entries is not None
        else iter_template_entries(template, excludes, config)
    )
    groups: dict[ClassifyState, list[str]] = {
        "will_copy": [],
        "will_upgrade": [],
        "identical": [],
        "needs_merge": [],
        "unknown_existing": [],
        "local_only": [],
        "needs_adoption": [],
    }
    # A pre-#274 install still has `.claude/skills` as a symlink, so every
    # compat copy under it resolves *through* the link onto the real
    # `.agents/skills` file and would otherwise classify `identical` -- with
    # nothing copied, `migrate_skills_compat_dir` would then unlink the
    # symlink and leave Claude Code with no skills at all. Treat the copies as
    # absent while the link stands: they genuinely do not exist yet at their
    # own paths.
    legacy_skills_link = (destination / SKILLS_COMPAT_PATH).is_symlink()
    compat_prefix = f"{SKILLS_COMPAT_PATH}/"
    for entry in entry_iter:
        target = destination / entry.relative
        target_exists = _any_exists(target) and not (
            legacy_skills_link and entry.relative.startswith(compat_prefix)
        )
        content_matches = False
        block_state = None
        fingerprint = None
        template_fp = None
        if target_exists:
            content_matches = same_content(entry, target)
            block_state = block_managed_state(entry, target)
            fingerprint = destination_fingerprint(target)
            if not content_matches and block_state in (None, "modified"):
                # The 3-way reconcile path needs the template fingerprint --
                # for a "modified" block, to check whether an accepted
                # baseline already covers the current state (#63).
                template_fp = entry_fingerprint(entry)
        state = _classify_entry(
            entry,
            manifest,
            target_exists=target_exists,
            content_matches=content_matches,
            block_state=block_state,
            fingerprint=fingerprint,
            template_fp=template_fp,
        )
        # A merge whose only difference is the final newline has nothing to
        # resolve; take the template rather than forcing a guided merge.
        if state == "needs_merge" and _differs_only_by_final_newline(entry, target):
            state = "will_upgrade"
        groups[state].append(entry.relative)

    return Classification(
        **groups,
        excluded=sorted(set(excludes) | set(config.exclude_paths if config else [])),
    )


def find_path_collisions(destination: Path, relatives: Iterable[str]) -> list[str]:
    """Existing non-directory ancestors that block creating the given targets.

    ``copy_paths`` (and the manifest/merge writes) create each target's parent
    chain with ``mkdir(parents=True)``. If an ancestor that must become a
    directory already exists as a regular file, a broken symlink, or a symlink
    to a non-directory, that ``mkdir`` raises mid-copy and leaves a partial
    install. A symlinked ancestor that resolves to a real directory is worse: it
    silently redirects every nested write outside the destination tree, so a
    repository-controlled link such as ``.claude -> /outside`` escapes
    containment. Ancestors are never final template paths, so any symlink among
    them is unsafe. Returning every blocking ancestor up front lets callers
    preflight the whole write set and fail before touching the destination.
    """
    collisions: set[str] = set()
    for relative in relatives:
        parts = Path(relative).parts
        for depth in range(1, len(parts)):
            ancestor_rel = "/".join(parts[:depth])
            ancestor = destination / ancestor_rel
            if ancestor_rel == SKILLS_COMPAT_PATH and ancestor.is_symlink():
                # The one ancestor an apply repairs instead of refusing: a
                # pre-#274 install left `.claude/skills` as a symlink, and
                # `migrate_skills_compat_dir` unlinks it before any write. Safe
                # whatever the link points at, precisely because it is removed
                # rather than written through -- but only while that migration
                # runs first, which `apply_plan` guarantees.
                continue
            # A symlink ancestor would route writes through its target (escaping
            # the destination), and any non-directory ancestor would make the
            # parent mkdir fail. Both are collisions; a real directory is fine.
            if _any_exists(ancestor) and (ancestor.is_symlink() or not ancestor.is_dir()):
                collisions.add(ancestor_rel)
    return sorted(collisions)


def migrate_skills_compat_dir(destination: Path) -> bool:
    """Remove a pre-#274 `.claude/skills` symlink so per-file copies can land.

    Returns whether a link was removed, which the caller turns into a manifest
    prune: the old symlink record describes a path that no longer exists in
    that shape. Writing the per-file copies without this would follow the link
    and scatter them through `.agents/skills` instead, recording paths the
    manifest then cannot reconcile.
    """
    target = destination / SKILLS_COMPAT_PATH
    if not target.is_symlink():
        return False
    target.unlink()
    return True


def mirror_project_skills(destination: Path) -> tuple[list[str], list[str]]:
    """Copy destination-owned skills into `.claude/skills`; report written and diverged.

    A project's own skills live beside Raven's under `.agents/skills`, and
    Claude Code reads only `.claude/skills`. While that path was a symlink
    (pre-#274), a project skill was visible there for free; per-file copying
    covers only the paths Raven ships, so without this a project would lose
    its own skills from Claude Code the moment it upgraded.

    Create-only. A copy that already exists with different content is left
    alone and returned in the second list, never overwritten: both sides
    belong to the destination, and Raven has no way to tell which one is
    newer. Rewriting from `.agents/skills` on the assumption that it is
    canonical destroyed real content in the field -- a code-intelligence tool
    installs a Claude-flavoured skill under `.claude/skills` and an older
    Codex-flavoured one under `.agents/skills`, and the mirror silently
    replaced the better copy with the worse one. An out-of-date mirror is a
    reported nuisance; a deleted one is unrecoverable unless it was
    committed.

    The copies are untracked by Raven either way: they are the destination's
    content, so no manifest record is written and no upgrade removes one. A
    copy whose source is gone is likewise left alone.

    A source skill that *git* ignores (a machine-local install, e.g. a tool
    that writes its own skills) gets its mirror gitignored too. It still
    reaches Claude Code, which is the point, but a broad `git add` cannot
    publish a skill the project deliberately kept untracked.

    A source that is merely *untracked* -- nobody ignored it, nobody added it
    -- gets a mirror on a tracked path, deliberately. `git add -A` would
    publish the untracked source anyway, so the mirror exposes nothing the
    source did not already expose, and treating "untracked" as "private"
    would have Raven make a call the project itself has not made. Only an
    explicit ignore rule is treated as intent.
    """
    source_root = destination / SKILLS_SOURCE_PATH
    compat_root = destination / SKILLS_COMPAT_PATH
    if not source_root.is_dir() or compat_root.is_symlink():
        return [], []
    mirrored: list[str] = []
    diverged: list[str] = []
    for source in sorted(source_root.rglob("*")):
        if source.is_dir() or source.is_symlink():
            continue
        relative = source.relative_to(source_root)
        copy = compat_root / relative
        if _any_exists(copy):
            if not copy.is_file() or file_sha256(copy) != file_sha256(source):
                diverged.append(f"{SKILLS_COMPAT_PATH}/{relative.as_posix()}")
            continue
        copy.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, copy)
        mirrored.append(f"{SKILLS_COMPAT_PATH}/{relative.as_posix()}")
    ignored = [
        skill
        for skill in sorted(_git_ignored_skills(destination, SKILLS_SOURCE_PATH, source_root))
        if (compat_root / skill).is_dir()
    ]
    # An entry for a mirror git already ignores is noise, and a repository
    # that ignores `.claude/` wholesale would otherwise collect one line per
    # skill it never needed. Ask about the compat paths too, and write only
    # what a rule does not already cover.
    covered = _git_ignored_skills(destination, SKILLS_COMPAT_PATH, compat_root)
    uncovered = [skill for skill in ignored if skill not in covered]
    if uncovered:
        ensure_skill_mirrors_gitignored(destination, uncovered)
    return mirrored, diverged


def _git_ignored_skills(destination: Path, prefix: str, root: Path) -> set[str]:
    """Names of ``<prefix>/<name>`` directories git ignores; empty when it cannot tell.

    One batched ``git check-ignore --stdin`` rather than a call per skill.
    Exit 0 lists the ignored paths, exit 1 means none matched, and anything
    else -- git missing, not a repository, a broken index -- is answered
    "none", because an unanswerable question must not start gitignoring a
    project's own skills.
    """
    if not root.is_dir():
        return set()
    names = sorted(path.name for path in root.iterdir() if path.is_dir())
    if not names:
        return set()
    try:
        result = subprocess.run(
            ["git", "-C", str(destination), "check-ignore", "--stdin"],
            input="\n".join(f"{prefix}/{name}" for name in names),
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return set()
    if result.returncode != 0:
        return set()
    return {Path(line).name for line in result.stdout.splitlines() if line.strip()}


def find_state_symlink_collisions(destination: Path, relatives: Iterable[str]) -> list[str]:
    """State-file targets whose final component is a symlink (broken ones too).

    Unlike ``find_path_collisions``, which inspects only ancestor directories,
    this checks each *final* path itself. A ``.raven/config.toml`` or
    ``.raven/manifest.json`` that is a symlink (while ``.raven`` is a real
    directory) would route the state read/write through the link to a file
    outside the destination tree, silently mutating it. These state files are
    always plain files Raven owns -- never a legitimate symlink -- so any symlink
    at the final path is a containment breach and is returned as a collision. A
    broken symlink is rejected the same way (``is_symlink`` is True regardless of
    whether the target resolves). This deliberately does not generalize to
    ``find_path_collisions``: managed copy targets may legitimately be symlinks
    that ``copy_paths`` unlink-replaces, and ``.claude`` symlink adoption creates
    one on purpose, so only these known state paths are checked here.
    """
    collisions: set[str] = set()
    for relative in relatives:
        if (destination / relative).is_symlink():
            collisions.add(relative)
    return sorted(collisions)


def copy_paths(
    template: Path,
    destination: Path,
    paths: list[str],
    config: RavenConfig | None = None,
    entries: dict[str, TemplateEntry] | None = None,
    update_managed_blocks: bool = False,
) -> None:
    """Write each of ``paths`` from the template to ``destination``.

    ``update_managed_blocks`` opts into rewriting just the RAVEN block in place
    (via `update_raven_block`) for a root instruction file whose block state is
    "upgradeable", instead of overwriting the whole file -- everything else is
    a plain symlink-or-copy.
    """
    if entries is None:
        entries = entries_for_destination(template, set(), config, destination)
    for relative in paths:
        entry = entries[relative]
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if update_managed_blocks and block_managed_state(entry, target) == "upgradeable":
            update_raven_block(entry, target)
        elif entry.rendered_content is not None:
            if target.is_symlink():
                target.unlink()
            target.write_bytes(entry.rendered_content)
        elif entry.copy_as_symlink:
            if _any_exists(target):
                target.unlink()
            target.symlink_to(os.readlink(entry.source))
        else:
            if target.is_symlink():
                target.unlink()
            shutil.copy2(entry.source, target)


def _write_entry(entry: TemplateEntry, target: Path) -> None:
    """Write one entry's content to ``target``, rendered or copied as the entry demands.

    The rendered branch is not optional: `.mcp.json`, `.codex/config.toml` and
    `.gemini/settings.json` are generated at install time (#271) and their
    ``source`` path need not exist on disk at all, so a plain ``copy2`` of it
    would fail outright.
    """
    if entry.rendered_content is not None:
        target.write_bytes(entry.rendered_content)
    else:
        shutil.copy2(entry.source, target)


def adoption_needed(
    destination: Path, entries: dict[str, TemplateEntry], adoptable: AdoptableFile
) -> bool:
    """Whether ``adoptable`` exists at the destination holding content Raven does not own.

    The structural check for a ``root_instructions`` adoptable: true for the
    still-symlinked shape a pre-#253 install left behind (a symlink is never
    the correct content once the template ships CLAUDE.md/GEMINI.md as a plain
    ``@AGENTS.md`` file), and for a real file whose content differs.

    A ``config`` adoptable needs no such probe -- the ``needs_adoption``
    classification bucket *is* its structural check -- so callers test bucket
    membership for those instead.
    """
    entry = entries.get(adoptable.path)
    target = destination / adoptable.path
    if entry is None or entry.copy_as_symlink or not _any_exists(target):
        return False
    return not same_content(entry, target)


def adopt_file(
    destination: Path, entries: dict[str, TemplateEntry], adoptable: AdoptableFile
) -> list[str]:
    """Replace ``adoptable`` with the template's content, backing up any real content first.

    Hand-rolled rather than delegating to ``copy_paths`` because this function
    only has ``entries``, not a template root -- ``copy_paths`` would need one
    it does not otherwise use, purely to make its override/managed-block
    parameters line up for a single-file write it already performs
    identically inline.

    Refuses (raises) rather than overwriting a pre-existing backup file, since
    that would silently discard whatever content it holds. Returns the
    destination-relative paths actually written, for the caller to report.
    """
    entry = entries.get(adoptable.path)
    if entry is None or entry.copy_as_symlink:
        raise ValueError(
            f"{adoptable.path} is not configured as a plain Raven-managed file in this template"
        )
    target = destination / adoptable.path
    backup = destination / adoptable.backup_path
    if not _any_exists(target):
        target.parent.mkdir(parents=True, exist_ok=True)
        _write_entry(entry, target)
        return [adoptable.path]
    if same_content(entry, target):
        return []
    if _any_exists(backup):
        raise FileExistsError(
            f"refusing to adopt {adoptable.path} because {adoptable.backup_path} already exists"
        )
    target.rename(backup)
    _write_entry(entry, target)
    return [adoptable.backup_path, adoptable.path]


def prompt_for_adoption(destination: Path, adoptable: AdoptableFile) -> bool:
    """Interactively ask whether to adopt one file; False in any non-interactive context.

    Checks ``stdin.isatty()`` up front so a non-interactive run (CI, a script,
    piped input) defaults to "no" instead of hanging on `input()` or consuming
    unrelated piped data as an answer.
    """
    if not sys.stdin.isatty():
        return False
    print(adoptable.summary)
    print(f"This repository already has {destination / adoptable.path}, which Raven does not own.")
    print(
        f"Choose whether to leave it untouched or move it to {adoptable.backup_path} and let "
        "Raven manage the file from here on."
    )
    while True:
        try:
            answer = input(f"Adopt {adoptable.path}? [y/N]: ").strip().lower()
        except EOFError:
            return False
        if answer in {"", "n", "no"}:
            return False
        if answer in {"y", "yes"}:
            return True
        print("  Enter y or n.")


def prompt_for_template_switch(prior_template: str, new_template: str) -> bool:
    """Interactively confirm a language-template switch; False in any non-interactive context.

    Mirrors ``prompt_for_claude_adoption``: ``stdin.isatty()`` is
    checked up front so a non-interactive run (CI, a script, piped input)
    declines instead of hanging on `input()` or reading unrelated piped data
    as an answer. Declining is safe here -- the caller refuses the run and
    nothing on disk changes.
    """
    if not sys.stdin.isatty():
        return False
    print(
        f"Raven last applied the '{prior_template}' template here, but the configuration "
        f"now selects '{new_template}'."
    )
    print(
        "Switching templates can remove Raven-managed files that the new template does not "
        "ship (starter tool configs such as pyproject.toml are always kept)."
    )
    while True:
        try:
            answer = (
                input(f"Switch from '{prior_template}' to '{new_template}'? [y/N]: ")
                .strip()
                .lower()
            )
        except EOFError:
            return False
        if answer in {"", "n", "no"}:
            return False
        if answer in {"y", "yes"}:
            return True
        print("  Enter y or n.")
