#!/usr/bin/env python3
"""PostToolUse hook: best-effort auto-format a just-edited file with its language's formatter.

Silent and always exits 0 -- a missing formatter, an unsupported extension, or a
malformed hook payload all mean "nothing to do", never a hook failure that would
block the edit or spam the transcript.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path


def _load_payload() -> dict | None:
    try:
        payload = json.load(sys.stdin)
    except (ValueError, OSError):
        return None
    # Valid JSON of the wrong shape (a list, a bare string, a number) is still
    # unusable: returning it would break the `dict` contract below and raise on
    # `.get`. That is the one parseable input that would traceback instead of
    # failing open, on every tool call.
    return payload if isinstance(payload, dict) else None


_PATCH_HEADER = re.compile(r"^\*\*\* (?:Add File|Update File|Delete File|Move to): (.+)$")


def _patch_paths(text: str) -> list[str]:
    """Every file a Codex ``apply_patch`` payload adds, updates, deletes, or moves to.

    Headers are matched on the stripped line, as Codex's own parser does. An
    add-hunk content line starts with ``+``, so it never matches. ``*** Environment
    ID:`` names a remote executor, not a file, and is not captured.
    """
    paths: list[str] = []
    for line in text.splitlines():
        match = _PATCH_HEADER.match(line.strip())
        if match is None:
            continue
        path = match.group(1).strip()
        if path and path not in paths:
            paths.append(path)
    return paths


def _extract_paths(payload: dict) -> list[str]:
    tool_input = payload.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        return []
    command = tool_input.get("command")
    if payload.get("tool_name") == "apply_patch" and isinstance(command, str):
        return _patch_paths(command)
    path = tool_input.get("file_path") or tool_input.get("path") or payload.get("file_path")
    return [path] if path and isinstance(path, str) else []


def _anchored(path: str, payload: dict) -> str:
    """``path`` joined onto the payload ``cwd`` when it is relative and ``cwd`` is absolute."""
    cwd = payload.get("cwd")
    if isinstance(cwd, str) and os.path.isabs(cwd) and not os.path.isabs(path):
        return os.path.join(cwd, path)
    return path


_PER_COMMAND_TIMEOUT_SECONDS = 10
# Under Codex's 30 s hook timeout, leaving headroom for interpreter start-up.
_TOTAL_BUDGET_SECONDS = 20
_deadline = 0.0

_EDITION = re.compile(r'^\s*edition\s*=\s*"(\d{4})"', re.M)
_PRETTIER_SUFFIXES = {
    ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".mts", ".cts", ".json", ".md",
}  # fmt: skip
_RUBY_NAMES = {"gemfile", "rakefile"}
_RUBY_SUFFIXES = {".rb", ".gemspec", ".rake"}


def run(command: list[str], cwd: Path | None = None) -> None:
    """Run a formatter, discarding output; timeouts and exec failures are silent (best-effort)."""
    remaining = _deadline - time.monotonic()
    if remaining <= 0:
        return
    try:
        subprocess.run(
            command,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=min(_PER_COMMAND_TIMEOUT_SECONDS, remaining),
        )
    except (subprocess.TimeoutExpired, OSError):
        return


def _nearest_ancestor_with(path: Path, names: tuple[str, ...]) -> Path | None:
    """First directory from ``path.parent`` upward that contains any of ``names``."""
    for directory in (path.parent, *path.parent.parents):
        if any((directory / name).exists() for name in names):
            return directory
    return None


def _project_root(path: Path) -> Path:
    return _nearest_ancestor_with(path, (".git", ".raven")) or path.parent


def _dirs_to_root(path: Path) -> list[Path]:
    """Directories from ``path.parent`` up to the project root, inclusive."""
    root = _project_root(path)
    dirs = []
    for directory in (path.parent, *path.parent.parents):
        dirs.append(directory)
        if directory == root:
            break
    return dirs


def _prettier_cmd(path: Path) -> str | None:
    """Project-local prettier from node_modules/.bin, else PATH. Never npx (it can download)."""
    for directory in _dirs_to_root(path):
        found = shutil.which("prettier", path=str(directory / "node_modules" / ".bin"))
        if found:
            return found
    return shutil.which("prettier")


def _cargo_edition(path: Path) -> str | None:
    for directory in _dirs_to_root(path):
        manifest = directory / "Cargo.toml"
        try:
            match = _EDITION.search(manifest.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError):
            continue
        if match:
            return match.group(1)
    return None


def _swift_format_cmd() -> list[str] | None:
    """Resolve Apple's swift-format: prefer a PATH binary, else the Xcode toolchain via xcrun."""
    if shutil.which("swift-format"):
        return ["swift-format"]
    if shutil.which("xcrun"):
        return ["xcrun", "swift-format"]
    return None


def _format_ruby(path: Path) -> None:
    flags = ["--fix-layout", "--force-exclusion", str(path)]
    gemfile_dir = _nearest_ancestor_with(path, ("Gemfile",))
    if gemfile_dir is not None:
        if shutil.which("bundle"):
            run(["bundle", "exec", "rubocop", *flags], cwd=gemfile_dir)
    elif shutil.which("rubocop"):
        run(["rubocop", *flags])


def _format(path: Path) -> None:
    """Format one existing file with its language's formatter, if one is available."""
    suffix = path.suffix.lower()
    if suffix == ".py" and shutil.which("ruff"):
        run(["ruff", "format", str(path)])
    elif suffix in _PRETTIER_SUFFIXES:
        prettier = _prettier_cmd(path)
        if prettier:
            run([prettier, "--write", str(path)])
    elif suffix == ".swift":
        swift_format = _swift_format_cmd()
        if swift_format:
            run([*swift_format, "format", "--in-place", str(path)])
    elif suffix == ".go":
        if shutil.which("gofmt"):
            run(["gofmt", "-w", str(path)])
    elif suffix == ".rs":
        if shutil.which("rustfmt"):
            edition = _cargo_edition(path)
            run(["rustfmt", *(["--edition", edition] if edition else []), str(path)])
    elif suffix in {".ex", ".exs"}:
        root = _nearest_ancestor_with(path, ("mix.exs",))
        if root is not None and shutil.which("mix"):
            run(["mix", "format", str(path)], cwd=root)
    elif suffix == ".lua":
        if shutil.which("stylua"):
            run(["stylua", str(path)], cwd=_project_root(path))
    elif suffix in _RUBY_SUFFIXES or path.name.lower() in _RUBY_NAMES:
        _format_ruby(path)


def _is_remote_patch(payload: dict) -> bool:
    """True for an ``apply_patch`` whose files live on a remote executor, not this host."""
    tool_input = payload.get("tool_input")
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if payload.get("tool_name") != "apply_patch" or not isinstance(command, str):
        return False
    return any(line.strip().startswith("*** Environment ID:") for line in command.splitlines())


def main() -> int:
    """Read the hook payload from stdin and format each edited file whose type is supported."""
    global _deadline
    _deadline = time.monotonic() + _TOTAL_BUDGET_SECONDS
    payload = _load_payload()
    if payload is None or _is_remote_patch(payload):
        return 0

    for raw_path in _extract_paths(payload):
        path = Path(_anchored(raw_path, payload))
        # Deleted files and the source of a `Move to` no longer exist.
        if path.is_file():
            _format(path)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
