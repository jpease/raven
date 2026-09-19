"""Walk the template tree into the flat `TemplateEntry` list `apply`/`plan` consume.

Symlinks that point back into ``common/`` (the template's own internal cross-links)
are re-created as regular-file copies at the destination rather than preserved as
symlinks -- only symlinks pointing *outside* the template survive the walk as-is.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from .config import component_disabled, config_excluded
from .constants import (
    EXCLUDED_NAMES,
    EXPECTED_TEMPLATE_SYMLINKS,
    INTERNAL_TEMPLATE_PATHS,
    MERGE_ONLY_TEMPLATE_PATHS,
    REPO_ROOT,
    SKILLS_COMPAT_PATH,
    SKILLS_SOURCE_PATH,
    STARTER_TOOL_CONFIG_PATHS,
    _any_exists,
)
from .models import RavenConfig, TemplateEntry
from .render import (
    can_render_codex_config_toml,
    can_render_gemini_settings,
    can_render_mcp_json,
    render_codex_config_toml,
    render_gemini_settings,
    render_mcp_json,
    resolve_common_root,
)

#: A relative symlink target that climbs out of its tree and back in through
#: ``common/`` -- the shape of the template's own internal cross-links.
_COMMON_CROSS_LINK = re.compile(r"(\.\./)+common/")


def is_known_template(name: str) -> bool:
    """Whether ``name`` is a real Raven template directory, independent of whether
    it ships gate tooling. ``gate_spec_for(name) is None`` means only "no GATE_DATA
    entry" -- see cli.list_language_templates() for the actual template roster, and
    `dotfiles` for a real template that legitimately has no gate recipes at all.

    Lives here rather than in a reporting module so `doctor` and `assess` share one
    answer to "is this a known template name" instead of each deriving it from the
    gate table (issues #187, #191).
    """
    from .cli import list_language_templates  # local: cli.py imports template.py at module level

    return name in list_language_templates()


def is_excluded(
    path: Path, relative: str, explicit_excludes: set[str], config: RavenConfig | None = None
) -> bool:
    """Whether ``relative`` is skipped by explicit excludes, config gating, or its name.

    ``MERGE_ONLY_TEMPLATE_PATHS`` (currently just ``.gitattributes``, #206) is
    checked unconditionally, independent of ``explicit_excludes``/config: those
    paths ship a real template file that must never become a normal
    will_copy/will_upgrade entry, so a caller cannot accidentally re-include one
    by omitting it from its excludes set the way ``--include-readme`` re-includes
    README.md.
    """
    if relative in explicit_excludes:
        return True
    if relative in MERGE_ONLY_TEMPLATE_PATHS:
        return True
    if relative in INTERNAL_TEMPLATE_PATHS:
        return True
    if config and config_excluded(relative, config):
        return True
    return any(part in EXCLUDED_NAMES for part in path.parts)


def _resolves_within(resolved: Path, root: Path) -> bool:
    """Whether ``resolved`` is ``root`` or lives under it, both fully resolved.

    ``os.path.commonpath`` raises for inputs it cannot compare -- most notably
    two different drives on Windows. That is precisely the "not contained" case,
    so it is answered False rather than propagated.
    """
    try:
        return os.path.commonpath([str(resolved), str(root)]) == str(root)
    except ValueError:
        return False


def should_preserve_symlink(path: Path, common_root: Path | None = None) -> bool:
    """Whether ``path`` is a symlink that should be copied as a symlink, not resolved.

    False for a symlink whose relative target climbs back into ``common/`` *and*
    genuinely lands inside it: that is an internal template cross-link, not
    something the destination should depend on ``common/`` still existing to
    follow. Everything else is preserved as a symlink.

    Both halves of that test are load-bearing:

    * The ``../common/`` spelling identifies the cross-link. Links that stay
      inside their own tree -- ``CLAUDE.md -> AGENTS.md``, ``.claude/skills ->
      ../.agents/skills`` -- also resolve inside ``common/`` but are meant to be
      installed *as symlinks*, so containment alone would wrongly flatten them.
    * Resolving the target and containing it with ``os.path.commonpath``
      identifies whether the climb really lands in ``common/``. The former
      prefix-match on the target *string* accepted
      ``../../../common/../../victim/secret.txt``, which starts with a climb
      into ``common/`` but escapes it entirely -- so the installer dereferenced
      it and copied an arbitrary file from outside the template into the
      destination (#177).

    ``common_root`` defaults to this checkout's ``common/`` and exists so tests
    can point the containment check at an isolated tree; every production caller
    uses the default.
    """
    if not path.is_symlink():
        return False
    target = os.readlink(path).replace("\\", "/")
    if not _COMMON_CROSS_LINK.match(target):
        return True
    root = (common_root if common_root is not None else REPO_ROOT / "common").resolve()
    resolved = (path.parent / target).resolve()
    return not _resolves_within(resolved, root)


def broken_template_symlinks(common_root: Path) -> list[str]:
    """`EXPECTED_TEMPLATE_SYMLINKS` entries that exist under ``common_root`` but are not symlinks.

    Sorted, and empty for a healthy checkout. A path that is simply *absent* is
    not reported: that is a different condition (a partial or throwaway tree),
    whereas a path that exists as a regular file is the signature of a checkout
    that could not create symlinks and wrote the target text as content instead.
    A dangling symlink is likewise not this check's business -- it is still a
    symlink, and `test_templates_have_no_broken_symlinks` already covers it.
    """
    return sorted(
        relative
        for relative in EXPECTED_TEMPLATE_SYMLINKS
        if (path := common_root / relative).exists() and not path.is_symlink()
    )


def iter_template_entries(
    template: Path, excludes: set[str], config: RavenConfig | None = None
) -> list[TemplateEntry]:
    """Walk ``template``, honoring excludes/config, into a sorted list of entries.

    A directory recognized as a preserved symlink is recorded as one entry and not
    descended into; everything else is walked recursively via ``os.walk``.
    """
    entries: dict[str, TemplateEntry] = {}

    for root, dirnames, filenames in os.walk(template, followlinks=True):
        root_path = Path(root)
        kept_dirnames = []
        for dirname in dirnames:
            path = root_path / dirname
            relative = path.relative_to(template).as_posix()
            if is_excluded(path, relative, excludes, config):
                continue
            if should_preserve_symlink(path):
                entries[relative] = TemplateEntry(
                    relative=relative, source=path, copy_as_symlink=True
                )
                continue
            kept_dirnames.append(dirname)
        dirnames[:] = kept_dirnames

        for filename in filenames:
            path = root_path / filename
            relative = path.relative_to(template).as_posix()
            if is_excluded(path, relative, excludes, config):
                continue
            entries[relative] = TemplateEntry(
                relative=relative,
                source=path,
                copy_as_symlink=should_preserve_symlink(path),
            )

    return [entries[key] for key in sorted(entries)]


def entries_for_destination(
    template: Path,
    excludes: set[str],
    config: RavenConfig | None,
    destination: Path,
) -> dict[str, TemplateEntry]:
    """Template entries adjusted for what already exists at ``destination``.

    Two destination-aware rewrites on top of the policy-neutral `iter_template_
    entries` walk. A starter tool config (e.g. ``pyproject.toml``) is dropped
    entirely once the destination already has one, since Raven never re-copies
    over a project's own config.

    And the ``.claude/skills`` symlink entry is always replaced with individual
    file copies (#274). The template keeps the link -- it is how one skill tree
    serves both paths inside the Raven checkout -- but a destination never
    receives it: git materializes a symlink as a regular file holding the
    target text on a checkout without symlink support, which leaves Claude
    Code finding no skills at all. That is the failure #253 removed from
    CLAUDE.md, and the installed shape has to be the same everywhere, because
    whatever lands gets committed and cloned onto every other platform. This
    rewrite was already the fallback for a destination that happened to have a
    real directory there; making it unconditional is what stops installed
    shape from depending on what was on disk the first time Raven ran.
    """
    entries = {entry.relative: entry for entry in iter_template_entries(template, excludes, config)}
    for relative in STARTER_TOOL_CONFIG_PATHS:
        if relative in entries and _any_exists(destination / relative):
            entries.pop(relative)

    skills_entry = entries.get(SKILLS_COMPAT_PATH)
    if skills_entry and skills_entry.copy_as_symlink:
        entries.pop(SKILLS_COMPAT_PATH)
        source_prefix = f"{SKILLS_SOURCE_PATH}/"
        for relative, entry in list(entries.items()):
            if relative.startswith(source_prefix) and not entry.copy_as_symlink:
                suffix = relative.removeprefix(source_prefix)
                new_relative = f"{SKILLS_COMPAT_PATH}/{suffix}"
                if is_excluded(entry.source, new_relative, excludes, config):
                    continue
                entries[new_relative] = TemplateEntry(
                    relative=new_relative,
                    source=entry.source,
                    copy_as_symlink=False,
                )

    gemini_settings_rel = ".gemini/settings.json"
    common = resolve_common_root(template)
    if gemini_settings_rel in entries:
        rendered_str = render_gemini_settings(template, common_root=common)
        entries[gemini_settings_rel] = TemplateEntry(
            relative=gemini_settings_rel,
            source=entries[gemini_settings_rel].source,
            copy_as_symlink=False,
            rendered_content=rendered_str.encode("utf-8"),
        )
    elif (
        (
            config is None
            or not is_excluded(
                destination / gemini_settings_rel, gemini_settings_rel, excludes, config
            )
        )
        and can_render_gemini_settings(template, common_root=common)
        and (
            (template / gemini_settings_rel).exists()
            or (common / gemini_settings_rel).exists()
            or (config is not None and not component_disabled(gemini_settings_rel, config))
        )
    ):
        source_path = (
            template / gemini_settings_rel
            if (template / gemini_settings_rel).exists()
            else common / gemini_settings_rel
            if (common / gemini_settings_rel).exists()
            else template / gemini_settings_rel
        )
        rendered_str = render_gemini_settings(template, common_root=common)
        entries[gemini_settings_rel] = TemplateEntry(
            relative=gemini_settings_rel,
            source=source_path,
            copy_as_symlink=False,
            rendered_content=rendered_str.encode("utf-8"),
        )

    mcp_json_rel = ".mcp.json"
    if (
        config is None
        or not is_excluded(destination / mcp_json_rel, mcp_json_rel, excludes, config)
    ) and can_render_mcp_json(template, common_root=common):
        entries[mcp_json_rel] = TemplateEntry(
            relative=mcp_json_rel,
            source=template / mcp_json_rel,
            copy_as_symlink=False,
            rendered_content=render_mcp_json(template, common_root=common).encode("utf-8"),
        )

    codex_config_rel = ".codex/config.toml"
    if (
        config is None
        or not is_excluded(destination / codex_config_rel, codex_config_rel, excludes, config)
    ) and can_render_codex_config_toml(template, common_root=common):
        entries[codex_config_rel] = TemplateEntry(
            relative=codex_config_rel,
            source=template / codex_config_rel,
            copy_as_symlink=False,
            rendered_content=render_codex_config_toml(template, common_root=common).encode("utf-8"),
        )
    return {key: entries[key] for key in sorted(entries)}
