#!/usr/bin/env python3
r"""Shared, minimal ``.raven/config.toml`` text parsing for Raven's shipped scripts.

This is deliberately a second, smaller parser alongside
``scripts/raven_lib/config.py`` ("parser 1"), not a shared dependency of it and
not a replacement for it. Parser 1 stays exactly as it is, untouched by this
module, for two reasons. First, parser 1 is the *installer's own* parser: it
runs from Raven's own checkout, is free to depend on the rest of
``raven_lib``, and already supports strictly more than this module does --
multi-line arrays, mixed-type coercion, and hard-failing ``ConfigError``s on a
type mismatch -- because real config keys (``[exclude].paths``, the
``[components.*]`` tables) already need that. Second, and the reason this
module exists at all, is that parser 1 is not available to the scripts this
module serves: they run *inside a destination repository*, shipped as
standalone files with no ``raven_lib`` package alongside them, so they cannot
import it. Six of those shipped scripts had each grown their own hand-rolled
``.raven/config.toml`` reader to cope, and two of the six had a real bug (a
naive ``line.split("#", 1)[0]`` or single-quote-blind comment strip that
corrupts a quoted value containing ``#`` or ``'``). Rather than fix six
divergent copies of the same handful of lines, this module gives all of them
one correct implementation to call instead.

That correctness bar -- comment stripping that understands single- and
double-quoted strings, including an escaped ``\\"`` inside a double-quoted
one -- is ported from parser 1's ``strip_comment`` below, since parser 1
already gets it right and there is no reason to re-derive it. What this
module deliberately leaves out is everything else parser 1 has: array
literals, nested-type coercion, and strict-mode errors on a type mismatch.
None of the six callers this module was built for parse a TOML array or need
anything more than a raw string per key, and folding that capability in here
would grow every destination repository's checkout for a capability nothing
installed there uses.

Two entry points, layered so each caller can build its own failure handling on
top:

``parse_config_text(text)`` -- a pure function from raw config text to
``{section_name: {key: raw_value_string}}``, with pre-``[section]`` keys
under ``""``. Values are returned exactly as written, still quoted if they
were quoted -- this layer does no type coercion, since every caller wants a
different one (a boolean flag, a bare template name, a set of TOML table
headers). It never raises: an unrecognized line (neither a ``[section]``
header nor a ``key = value`` assignment) is skipped rather than rejected,
matching how every one of the six callers already treats a line it doesn't
understand, and keeping this parser usable against files this module does not
fully understand -- ``.codex/config.toml`` in particular, which can contain
constructs (multi-line arrays, nested nested tables) beyond this subset.

``read_config(path)`` -- the file-reading wrapper. A missing file returns
``None``, not an exception: every current caller treats "no config" as
"nothing to read," never a hard error. A file that exists but cannot be read
(permissions, a bad encoding) raises `RavenConfigError`, so a caller that
wants to fail closed can let that propagate, and a caller that wants to fail
open (every current one) can catch it and return its own safe default. Which
behavior is correct is a per-caller decision this module does not make for
its callers.

``parse_bool(value)`` is a small typed-coercion convenience on top, since
``value == "true"`` / ``value == "false"`` string comparison was duplicated,
verbatim, across four of the six callers. Nothing else is added on top of
the raw string values: string unquoting and the section-header filtering the
Codex MCP-server-name lookup needs stay in their respective callers, since
each is a one-line operation only that caller needs.

A second, unrelated responsibility also lives here: ``resolve_repo_root(start)``,
a shared parent-directory walk to find a project root. It has nothing to do
with config parsing, but it was folded into this module rather than given a
new file for the same reason parsing was consolidated here -- seven call
sites across this shipped "hooks" component had each grown their own copy
(four duplicating a ``.git``/``.raven`` walk inline, three shelling out to
``git rev-parse --show-toplevel`` instead), and this module is already the
one place every one of those seven call sites can import a sibling from.
See ``resolve_repo_root``'s own docstring for why it is a pure filesystem
walk rather than a ``git rev-parse`` wrapper.
"""

from __future__ import annotations

from pathlib import Path


class RavenConfigError(Exception):
    """A present config file could not be read.

    Raised only by `read_config`, only when the file exists but
    ``path.read_text()`` itself fails (permissions, a bad encoding). A missing
    file is not an error -- see `read_config`'s ``None`` return -- and
    `parse_config_text` never raises, so this is never raised for malformed
    *content*, only for a file this process could not read at all.
    """


def strip_comment(line: str) -> str:
    r"""Strip a trailing ``#`` comment from one config line, respecting quotes.

    Tracks single- and double-quoted spans independently and only treats a
    ``#`` as a comment starter when it appears outside both. A ``\\"`` inside a
    double-quoted string does not close it (single-quoted strings have no
    escape processing, matching TOML). Ported from
    ``scripts/raven_lib/config.py``'s ``strip_comment`` -- see this module's
    docstring for why it is ported rather than imported.
    """
    in_double = False
    in_single = False
    escaped = False
    result = []
    for char in line:
        if escaped:
            result.append(char)
            escaped = False
            continue
        if char == "\\" and in_double:
            result.append(char)
            escaped = True
            continue
        if char == "'" and not in_double:
            in_single = not in_single
            result.append(char)
            continue
        if char == '"' and not in_single:
            in_double = not in_double
            result.append(char)
            continue
        if char == "#" and not in_double and not in_single:
            break
        result.append(char)
    return "".join(result).strip()


def parse_config_text(text: str) -> dict[str, dict[str, str]]:
    """Parse ``text`` into ``{section_name: {key: raw_value_string}}``.

    Keys that appear before any ``[section]`` header live under the empty
    string key ``""``. A ``[section]`` header with no keys under it still
    produces an (empty) entry, so a caller that only cares whether a section
    was declared -- the Codex MCP server table-header lookup -- can see it.
    Re-opening the same section later merges into the same dict rather than
    resetting it, and a key assigned more than once (whether in one block or
    across a re-opened section) keeps the last assignment, both matching how
    a real TOML table behaves.

    Never raises: a line that is neither a section header nor a
    ``key = value`` assignment (after comment stripping) is skipped, not
    rejected. See the module docstring for why this parser is deliberately
    lenient rather than strict like parser 1.
    """
    data: dict[str, dict[str, str]] = {"": {}}
    section = ""
    for raw_line in text.splitlines():
        line = strip_comment(raw_line)
        if not line:
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip()
            data.setdefault(section, {})
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        data.setdefault(section, {})[key.strip()] = value.strip()
    return data


def read_config(path: Path) -> dict[str, dict[str, str]] | None:
    """Read and parse ``path`` as this module's TOML subset.

    Returns ``None`` when ``path`` does not exist. Raises `RavenConfigError`
    when it exists but cannot be read (permissions, a bad encoding);
    `parse_config_text` itself never raises, so this is the only way this
    function can fail once the file is confirmed to exist.
    """
    if not path.exists():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise RavenConfigError(f"{path} could not be read: {exc}") from exc
    return parse_config_text(text)


def parse_bool(value: str) -> bool | None:
    """Parse a raw config value as a boolean literal, case-insensitively.

    Returns ``True``/``False`` for ``true``/``false`` (whitespace-trimmed,
    matched case-insensitively -- ``TRUE``, ``False``, etc. all count), or
    ``None`` for anything else -- a caller decides what "not a recognized
    boolean" means for it (keep a prior value, fall back to a default, warn
    and fail safe), so this never raises and never guesses.

    Case-insensitive on purpose, even though real TOML booleans are
    lowercase-only: the commit-msg hook's own pre-existing boolean reader
    matched ``true``/``false`` via a regex with ``re.IGNORECASE`` before this
    module replaced it, so a config already written with an uppercase value
    must keep working exactly as it did. Every other caller this module
    replaced only ever emitted or matched lowercase, so widening here is
    strictly additive for them -- it accepts a strictly larger set of inputs
    than any of the five other callers previously did, never a smaller one.
    """
    stripped = value.strip().lower()
    if stripped == "true":
        return True
    if stripped == "false":
        return False
    return None


def resolve_repo_root(start: Path) -> Path:
    """Walk up from ``start`` to the nearest enclosing project root.

    A directory counts as a root when ``.git`` exists there -- as a file
    *or* a directory, so a linked worktree resolves correctly: a worktree's
    own ``.git`` is a file pointing at the shared gitdir elsewhere, and that
    file already sits at the worktree's own logical root, not the
    superproject's, so no special-casing is needed -- or when ``.raven`` is
    a directory, for a checkout that has Raven's own marker but, for
    whatever reason, no ``.git`` alongside it (e.g. a destination that
    vendors Raven's guidance without being its own git checkout).

    Returns the first of ``start`` or its ancestors that matches, or
    ``start`` itself if none do. Never raises, and never returns ``None`` --
    the most permissive of the per-site behaviors this replaces, so every
    caller's "always get *some* answer" contract keeps holding whether or
    not a marker is ever found.

    Deliberately a pure filesystem walk, not a ``git rev-parse
    --show-toplevel`` subprocess wrapper. That subprocess call trusts the
    process environment (``GIT_DIR``, ``GIT_WORK_TREE``, ``GIT_INDEX_FILE``),
    and an inherited, stale value left over from an unrelated invocation
    earlier in the same shell corrupts its answer -- exactly the failure
    class ``scripts/raven_lib/git_hooks.py``'s ``_clean_git_env()`` exists to
    strip before invoking git from the *installer*. That fix lives in the
    installer's own package and is not available here: this module ships
    into a destination repository as a standalone file, with no
    ``raven_lib`` alongside it to import. A pure walk sidesteps the
    corruption class entirely rather than needing to re-port
    ``_clean_git_env`` a second time into a shipped copy -- and loses
    nothing by doing so, since a parent walk already agrees with ``git
    rev-parse --show-toplevel``'s answer in every legitimate
    (non-corrupted-env) worktree and submodule case, as ``.git`` sits at the
    true logical root in both.

    ``start`` is taken exactly as given, not independently sourced from
    ``Path.cwd()`` and not resolved here: every caller already has its own
    opinion of what to start from (an install-layout-derived path, a hook
    payload's ``cwd``, the process cwd) and has already decided whether and
    how to resolve it -- redoing either step here would take that choice
    away and risks masking a caller's own ``OSError`` handling around
    ``Path.resolve()``.
    """
    for candidate in (start, *start.parents):
        if (candidate / ".git").exists() or (candidate / ".raven").is_dir():
            return candidate
    return start
