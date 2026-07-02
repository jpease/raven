from __future__ import annotations

import os
import re
from pathlib import Path

from .config import config_excluded
from .constants import EXCLUDED_NAMES, STARTER_TOOL_CONFIG_PATHS, _any_exists
from .models import RavenConfig, TemplateEntry


def is_excluded(
    path: Path, relative: str, explicit_excludes: set[str], config: RavenConfig | None = None
) -> bool:
    if relative in explicit_excludes:
        return True
    if config and config_excluded(relative, config):
        return True
    return any(part in EXCLUDED_NAMES for part in path.parts)


def should_preserve_symlink(path: Path) -> bool:
    if not path.is_symlink():
        return False
    target = os.readlink(path).replace("\\", "/")
    return not re.match(r"(\.\./)+common/", target)


def iter_template_entries(
    template: Path, excludes: set[str], config: RavenConfig | None = None
) -> list[TemplateEntry]:
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
    entries = {entry.relative: entry for entry in iter_template_entries(template, excludes, config)}
    for relative in STARTER_TOOL_CONFIG_PATHS:
        if relative in entries and _any_exists(destination / relative):
            entries.pop(relative)

    skills_entry = entries.get(".claude/skills")
    target = destination / ".claude" / "skills"
    if (
        skills_entry
        and skills_entry.copy_as_symlink
        and target.exists()
        and target.is_dir()
        and not target.is_symlink()
    ):
        entries.pop(".claude/skills")
        for relative, entry in list(entries.items()):
            if relative.startswith(".agents/skills/") and not entry.copy_as_symlink:
                suffix = relative.removeprefix(".agents/skills/")
                new_relative = f".claude/skills/{suffix}"
                if is_excluded(entry.source, new_relative, excludes, config):
                    continue
                entries[new_relative] = TemplateEntry(
                    relative=new_relative,
                    source=entry.source,
                    copy_as_symlink=False,
                )
    return {key: entries[key] for key in sorted(entries)}
