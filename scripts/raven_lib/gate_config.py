"""Read a linter's own configuration and judge whether it still asks the gate's question.

The neighbouring modules already catch a gate that is unwired
(`assess._hook_is_trivial`), unreachable (`assess._recipes_reachable_from`),
unfailable (`assess._unfailable_reason`), or green over nothing
(`gate_evidence`). This module covers the last way a gate stops being a
constraint: it runs, it is reachable, it can fail, it inspects real files --
and its configuration has been edited so the rule it existed to enforce is
switched off.

Two consumers, one rule table:

* `relaxations(before, after)` compares a config's committed state against its
  staged state and names each edit that loosens it. `scripts/check-staged-
  relaxation.py` blocks a commit on the result.
* `gutted_gate_findings(destination)` judges a config's *current* state on its
  own, with no history, and is what `raven assess` reports.

`ruff`, `pyright`, `mypy`, `tsconfig.json`, and `Cargo.toml`'s `[lints]` have
rules here (#245), and only in formats a Raven-shipped template's own tool
config actually uses (`pyproject.toml`, `ruff.toml`, `pyrightconfig.json`,
`mypy.ini`, `setup.cfg`, `tsconfig.json`, `Cargo.toml`) -- close to free for
the last two, since JSON and TOML parsers already exist here for the others,
and `strict`/`noImplicitAny`/`strictNullChecks` and a lint moved to `warn` or
`allow` are the same shape as `typeCheckingMode` and a widened `ignore`. That
is the same discipline `gate_evidence` states for its detectors: a rule whose
loosening direction has been checked against the tool's documented semantics
earns a place; a guessed one warns on healthy projects and teaches people to
ignore the warning. SwiftLint (`.swiftlint.yml`), RuboCop (`.rubocop.yml`) and
golangci (`.golangci.yml`) have no rules and stay out: they are YAML, and this
stdlib-only, Python 3.9-floor runtime cannot read YAML without either a
dependency or a hand-rolled parser whose failure mode is a false accusation.
Credo (`.credo.exs`) and luacheck (`.luacheckrc`) are executable source in
their own languages; reading them means running them.

Those five languages are not unguarded, only unguarded *here*: a suppression
is comment syntax and needs no config parser, so
`common/.raven/git-hooks/lib/check-gate-relaxation.py` reports a blanket one
in each of them at commit time (#231). The standing-config half above stays
missing for exactly those five, for the reasons just given.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

# --------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------

_SECTION_RE = re.compile(r"^\[\s*([^\]]+?)\s*\]\s*$")
_KEY_RE = re.compile(r"^\s*(?P<key>(?:\"[^\"]*\"|'[^']*'|[A-Za-z0-9_.\-]+))\s*=\s*(?P<value>.*)$")


def _unquote(token: str) -> str:
    token = token.strip()
    if len(token) >= 2 and token[0] == token[-1] and token[0] in "\"'":
        return token[1:-1]
    return token


def _strip_comment(line: str) -> str:
    """Drop a trailing `#` comment, respecting quotes.

    A `#` inside a quoted string is data (`per-file-ignores` globs and mypy
    `exclude` regexes both legitimately hold one), so this walks the line
    rather than calling `str.split("#")`.
    """
    out: list[str] = []
    quote: str | None = None
    for ch in line:
        if quote is not None:
            out.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in "\"'":
            quote = ch
            out.append(ch)
            continue
        if ch == "#":
            break
        out.append(ch)
    return "".join(out)


def _split_list(body: str) -> list[str]:
    """Split an array body (no surrounding brackets) into unquoted entries."""
    entries: list[str] = []
    current: list[str] = []
    quote: str | None = None
    for ch in body:
        if quote is not None:
            current.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in "\"'":
            quote = ch
            current.append(ch)
            continue
        if ch == ",":
            entries.append("".join(current))
            current = []
            continue
        current.append(ch)
    entries.append("".join(current))
    return [_unquote(entry) for entry in entries if _unquote(entry) != ""]


def parse_toml_like(text: str) -> dict:
    """Parse the `[section]` + `key = value` subset TOML and INI configs share.

    Deliberately not a TOML implementation: Raven's runtime is stdlib-only and
    imports on Python 3.9, which has no `tomllib`. What it does read is the
    shape every linter config Raven ships actually uses -- table headers,
    scalars, and arrays written inline or across lines. Anything it cannot
    read is dropped, never guessed at: an unreadable key produces no rule
    result, which reports the config as fine, and reporting a healthy config
    as fine is the safe direction for a check that blocks commits.

    Returns `{"section.key": value}` where value is `str` for a scalar and
    `list[str]` for an array. Section is "" for a key before any header.
    """
    settings: dict = {}
    section = ""
    pending_key: str | None = None
    pending_parts: list[str] = []
    for raw in text.splitlines():
        line = _strip_comment(raw)
        if pending_key is not None:
            closed = "]" in line
            pending_parts.append(line.split("]")[0] if closed else line)
            if closed:
                settings[pending_key] = _split_list(" ".join(pending_parts))
                pending_key = None
                pending_parts = []
            continue
        stripped = line.strip()
        if not stripped:
            continue
        header = _SECTION_RE.match(stripped)
        if header:
            section = header.group(1).strip().strip("\"'")
            continue
        match = _KEY_RE.match(line)
        if not match:
            continue
        key = _unquote(match.group("key"))
        full = f"{section}.{key}" if section else key
        value = match.group("value").strip()
        if value.startswith("["):
            body = value[1:]
            if "]" in body:
                settings[full] = _split_list(body.split("]")[0])
            else:
                pending_key = full
                pending_parts = [body]
            continue
        settings[full] = _unquote(value)
    return settings


def _flatten_json(data: object, prefix: str, out: dict) -> None:
    if isinstance(data, dict):
        for key, value in data.items():
            _flatten_json(value, f"{prefix}.{key}" if prefix else str(key), out)
        return
    if isinstance(data, list):
        out[prefix] = [str(item) for item in data]
        return
    if isinstance(data, bool):
        out[prefix] = "true" if data else "false"
        return
    out[prefix] = str(data)


def parse_json_config(text: str) -> dict:
    """Parse a JSON config (`pyrightconfig.json`) into the same flat shape."""
    try:
        data = json.loads(text)
    except ValueError:
        return {}
    out: dict = {}
    _flatten_json(data, "", out)
    return out


#: Config files this module knows how to read, and the tool namespace each
#: one's keys belong to. `pyproject.toml` already namespaces its own tables
#: (`[tool.ruff.lint]`), so it needs no prefix; `ruff.toml` and `mypy.ini`
#: do not, so their bare `[lint]`/`[mypy]` keys get one added. `tsconfig.json`
#: is JSON with no self-namespacing (`compilerOptions.strict` says nothing
#: about which tool it belongs to), so it gets a `tsconfig` prefix the same
#: way `pyrightconfig.json` gets `pyright`. `Cargo.toml`'s `[lints.clippy]`
#: and `[lints.rust]` tables are already unambiguous, like `pyproject.toml`'s
#: own tables, so neither needs one.
CONFIG_FILES: tuple = (
    ("pyproject.toml", "toml", None),
    ("ruff.toml", "toml", "ruff"),
    (".ruff.toml", "toml", "ruff"),
    ("pyrightconfig.json", "json", "pyright"),
    ("mypy.ini", "toml", None),
    (".mypy.ini", "toml", None),
    ("setup.cfg", "toml", None),
    ("tsconfig.json", "json", "tsconfig"),
    ("Cargo.toml", "toml", None),
)


def normalize(settings: dict, prefix: str | None) -> dict:
    """Rewrite raw keys into the `<tool>.<path>.<key>` form the rule table matches.

    Three normalizations, each undoing a way the same setting is spelled
    differently depending on which file it lives in:

    * `tool.` is stripped, so `pyproject.toml`'s `[tool.ruff.lint]` and
      `ruff.toml`'s `[lint]` (given `prefix="ruff"`) land on one key.
    * `prefix` is prepended for a file whose own name supplies the tool.
    * mypy's per-module `[mypy-some.module]` sections collapse to `mypy.`,
      because `ignore_errors = true` under one is the same relaxation as
      under the global section, only narrower.
    """
    out: dict = {}
    for key, value in settings.items():
        norm = key[len("tool.") :] if key.startswith("tool.") else key
        if prefix and not norm.startswith(f"{prefix}."):
            norm = f"{prefix}.{norm}"
        if norm.startswith("mypy-"):
            norm = "mypy." + norm.split(".", 1)[1] if "." in norm else norm
        out[norm] = value
    return out


def read_config(path: Path, fmt: str, prefix: str | None) -> dict:
    """Parse one config file into normalized settings; unreadable files yield {}."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return {}
    raw = parse_json_config(text) if fmt == "json" else parse_toml_like(text)
    return normalize(raw, prefix)


def read_config_text(text: str, name: str) -> dict:
    """Parse config `text` as if it were the file called `name`; {} for an unknown name."""
    for candidate, fmt, prefix in CONFIG_FILES:
        if candidate == name or name.endswith("/" + candidate):
            raw = parse_json_config(text) if fmt == "json" else parse_toml_like(text)
            return normalize(raw, prefix)
    return {}


def is_known_config(name: str) -> bool:
    """True when `name` is a config file this module can read."""
    return any(name == c or name.endswith("/" + c) for c, _, _ in CONFIG_FILES)


# --------------------------------------------------------------------------
# Rules
# --------------------------------------------------------------------------

#: Keys whose *added* entries loosen the gate: every one of them names
#: something the tool will now skip.
_LIST_LOOSENS_BY_ADDING = (
    re.compile(r"^ruff(?:\.lint)?\.(?:ignore|extend-ignore)$"),
    re.compile(r"^ruff(?:\.lint)?\.(?:exclude|extend-exclude)$"),
    re.compile(r"^ruff(?:\.lint)?\.per-file-ignores\."),
    re.compile(r"^pyright\.(?:exclude|ignore)$"),
    re.compile(r"^mypy\.(?:exclude|disable_error_code)$"),
)

#: Keys whose *removed* entries loosen the gate: each one named something the
#: tool used to check and no longer will.
_LIST_LOOSENS_BY_REMOVING = (re.compile(r"^ruff(?:\.lint)?\.(?:select|extend-select)$"),)

#: Ordered strictest-to-loosest scales. A move rightward is a relaxation; a
#: value absent from the scale is unranked and never reported. Cargo's lint
#: levels (https://doc.rust-lang.org/cargo/reference/manifest.html#the-lints-section)
#: apply to any key under `[lints.clippy]` or `[lints.rust]` -- matched by
#: prefix, since a lint's own name is an open set this module cannot enumerate.
_LEVELS = (
    (re.compile(r"^pyright\.typeCheckingMode$"), ("strict", "standard", "basic", "off")),
    (re.compile(r"^pyright\.report"), ("error", "warning", "information", "none")),
    (re.compile(r"^mypy\.follow_imports$"), ("normal", "silent", "skip")),
    (re.compile(r"^lints\.(?:clippy|rust)\."), ("forbid", "deny", "warn", "allow")),
)

#: Boolean settings whose `true` is the strict state, matched by prefix or
#: exact name. mypy spells strictness both ways round, so both lists exist.
#: tsconfig's three each independently narrow type-checking when true --
#: `strict` turns the whole family on, `noImplicitAny`/`strictNullChecks` can
#: still be flipped off individually even with `strict: true` set, since
#: TypeScript lets an explicit flag override the umbrella setting
#: (https://www.typescriptlang.org/tsconfig/#strict).
_TRUE_IS_STRICT = (
    re.compile(r"^mypy\.(?:strict|strict_equality|no_implicit_optional)$"),
    re.compile(r"^mypy\.(?:warn_|disallow_|check_)"),
    re.compile(r"^pyright\.strict"),
    re.compile(r"^tsconfig\.compilerOptions\.(?:strict|noImplicitAny|strictNullChecks)$"),
)
_TRUE_IS_LOOSE = (
    re.compile(r"^mypy\.(?:ignore_errors|ignore_missing_imports)$"),
    re.compile(r"^mypy\.allow_"),
)

_BOOL_TRUE = frozenset({"true", "True", "yes", "1", "on"})
_BOOL_FALSE = frozenset({"false", "False", "no", "0", "off"})


def _as_level(value: object, scale: tuple) -> int | None:
    """Position of `value` on `scale`, mapping booleans onto its ends."""
    if not isinstance(value, str):
        return None
    if value in _BOOL_TRUE:
        return 0
    if value in _BOOL_FALSE:
        return len(scale) - 1
    lowered = value.lower()
    for index, level in enumerate(scale):
        if lowered == level.lower():
            return index
    return None


def _matches(key: str, patterns: tuple) -> bool:
    return any(pattern.search(key) for pattern in patterns)


def _as_list(value: object) -> list:
    if isinstance(value, list):
        return value
    if isinstance(value, str) and value:
        return [part for part in re.split(r"[,\s]+", value) if part]
    return []


def relaxations(before: dict, after: dict) -> list:
    """Name every edit from `before` to `after` that loosens a gate.

    Returns a list of `(key, description)` pairs, one per loosened setting,
    in sorted key order so a report is stable across runs. A key that is only
    tightened, reordered, or reformatted produces nothing -- adding a rule to
    `select` and removing one from `ignore` are both invisible here, which is
    what keeps the check from arguing with someone raising the bar.
    """
    found: list = []
    for key in sorted(set(before) | set(after)):
        old = before.get(key)
        new = after.get(key)
        if old == new:
            continue
        if _matches(key, _LIST_LOOSENS_BY_ADDING):
            added = [item for item in _as_list(new) if item not in _as_list(old)]
            if added:
                found.append((key, f"adds {', '.join(repr(a) for a in added)} to `{key}`"))
            continue
        if _matches(key, _LIST_LOOSENS_BY_REMOVING):
            gone = [item for item in _as_list(old) if item not in _as_list(new)]
            if gone:
                found.append((key, f"drops {', '.join(repr(g) for g in gone)} from `{key}`"))
            continue
        level_scale = next((scale for pattern, scale in _LEVELS if pattern.search(key)), None)
        if level_scale is not None:
            old_index = _as_level(old, level_scale)
            new_index = _as_level(new, level_scale)
            if new_index is None:
                continue
            if old_index is None:
                # A key that was not set before. Only the loosest value on the
                # scale reports: `reportMissingImports = false`,
                # `typeCheckingMode = "off"`, `follow_imports = "skip"` all
                # pin the setting off no matter what the mode's default was,
                # while a newly written middle value (a fresh config declaring
                # `typeCheckingMode = "standard"`) is an ordinary declaration.
                if new_index == len(level_scale) - 1:
                    found.append((key, f"sets `{key}` to its loosest value, {new!r}"))
                continue
            if new_index <= old_index:
                continue
            shown = new if new is not None else "(unset)"
            found.append((key, f"lowers `{key}` from {old!r} to {shown!r}"))
            continue
        if _matches(key, _TRUE_IS_STRICT) and old in _BOOL_TRUE and new in _BOOL_FALSE:
            found.append((key, f"turns off `{key}`"))
            continue
        if _matches(key, _TRUE_IS_LOOSE) and new in _BOOL_TRUE and old not in _BOOL_TRUE:
            found.append((key, f"turns on `{key}`"))
    return found


# --------------------------------------------------------------------------
# Absolute judgment: does this config still ask the gate's question?
# --------------------------------------------------------------------------

#: Path patterns that, as a lint `exclude` entry, cover the whole project.
_WHOLE_TREE = frozenset({".", "./", "*", "**", "**/*", "./*", "src", "/"})


def _ruff_scope(settings: dict, suffix: str) -> list:
    """Every entry of `ruff.<suffix>` and `ruff.lint.<suffix>`, in one list."""
    out: list = []
    for key in (f"ruff.{suffix}", f"ruff.lint.{suffix}"):
        out.extend(_as_list(settings.get(key)))
    return out


def gutting_reasons(settings: dict, tools: tuple, recipes: tuple) -> list:
    """Name every way `settings` disables the substance of a gate the template declares.

    Unlike `relaxations`, this reads one state with no history: it is what a
    project inherits when the config arrived already gutted, from a template
    fork, a migration, or an edit made before this check existed.

    `tools` and `recipes` come from the template's `GateSpec`, so a template
    that declares no `lint` recipe is never told its lint config is too
    permissive. Returns `(id_suffix, title, detail, fix)` tuples.
    """
    reasons: list = []
    if "ruff" in tools and "lint" in recipes:
        selected = _ruff_scope(settings, "select") + _ruff_scope(settings, "extend-select")
        ignored = _ruff_scope(settings, "ignore") + _ruff_scope(settings, "extend-ignore")
        if "ALL" in ignored:
            reasons.append(
                (
                    "ruff.ignore-all",
                    "the `lint` gate ignores every rule",
                    "ruff `ignore` holds `ALL`, so no rule can report",
                    "remove `ALL` from ruff's `ignore` list",
                )
            )
        # A family that is selected and then wholly ignored is the shape that
        # reads as configured and checks nothing: `select` still names it, so
        # the gate looks enforced, while `ignore` covers every code under it.
        # An ignore entry *narrower* than the selection (`D401` under `D`) is
        # ordinary scoping and never reported.
        cancelled = sorted(
            {
                f"{code} (ignored by `{entry}`)"
                for entry in ignored
                for code in selected
                if entry != "ALL" and code.startswith(entry)
            }
        )
        if cancelled:
            reasons.append(
                (
                    "ruff.cancelled",
                    "the `lint` gate selects rules it then ignores",
                    "selected and wholly ignored: " + ", ".join(cancelled),
                    "drop the `ignore` entry, or narrow it to the specific codes",
                )
            )
        blanket = sorted(
            key.rsplit(".", 1)[-1]
            for key in settings
            if _matches(key, (_LIST_LOOSENS_BY_ADDING[2],))
            and key.rsplit(".", 1)[-1] in _WHOLE_TREE
        )
        if blanket:
            reasons.append(
                (
                    "ruff.per-file-ignores",
                    "the `lint` gate has a project-wide per-file ignore",
                    "`per-file-ignores` keyed on " + ", ".join(f"`{g}`" for g in blanket),
                    "scope the `per-file-ignores` glob to the files that need it",
                )
            )
        excluded = [
            entry
            for entry in _ruff_scope(settings, "exclude") + _ruff_scope(settings, "extend-exclude")
            if entry in _WHOLE_TREE
        ]
        if excluded:
            reasons.append(
                (
                    "ruff.exclude",
                    "the `lint` gate excludes the whole project",
                    "ruff `exclude` holds " + ", ".join(f"`{e}`" for e in sorted(set(excluded))),
                    "narrow ruff's `exclude` to the paths that genuinely cannot be linted",
                )
            )
    if "pyright" in tools and "typecheck" in recipes:
        mode = settings.get("pyright.typeCheckingMode")
        # `standard` is the floor the python template ships and the one
        # `raven-python-quality.md` writes the "Types And Invariants" rules
        # against; `basic` drops most of them and `off` reports nothing.
        if isinstance(mode, str) and mode.lower() in ("off", "basic"):
            reasons.append(
                (
                    "pyright.mode",
                    "the `typecheck` gate runs below the template's floor",
                    f"`typeCheckingMode` is {mode!r}; the python template ships `standard`",
                    "restore `typeCheckingMode = \"standard\"` and fix the reported types",
                )
            )
        ignored_paths = [
            entry for entry in _as_list(settings.get("pyright.ignore")) if entry in _WHOLE_TREE
        ]
        if ignored_paths:
            reasons.append(
                (
                    "pyright.ignore",
                    "the `typecheck` gate ignores the whole project",
                    "pyright `ignore` holds "
                    + ", ".join(f"`{p}`" for p in sorted(set(ignored_paths))),
                    "narrow pyright's `ignore` to the paths that genuinely cannot be typed",
                )
            )
    if "typecheck" in recipes and settings.get("mypy.ignore_errors") in _BOOL_TRUE:
        reasons.append(
            (
                "mypy.ignore-errors",
                "the `typecheck` gate suppresses every mypy error",
                "`ignore_errors = true` is set, so mypy reports nothing it finds",
                "remove `ignore_errors`, or scope it to a `[mypy-<module>]` section",
            )
        )
    if "npx" in tools and "typecheck" in recipes:
        disabled = sorted(
            key.rsplit(".", 1)[-1]
            for key in (
                "tsconfig.compilerOptions.strict",
                "tsconfig.compilerOptions.noImplicitAny",
                "tsconfig.compilerOptions.strictNullChecks",
            )
            if settings.get(key) in _BOOL_FALSE
        )
        if disabled:
            reasons.append(
                (
                    "tsconfig.strict",
                    "the `typecheck` gate runs with strict checks off",
                    "tsconfig.json sets " + ", ".join(f"`{k}: false`" for k in disabled),
                    "remove the false setting(s) and fix the reported types",
                )
            )
    if "cargo" in tools and "lint" in recipes:
        # clippy::all and the rustc "warnings" group are each a single key
        # that stands for its whole lint family -- the Cargo.toml shape of
        # ruff's `ignore = ["ALL"]` above, not an ordinary per-lint choice.
        whole_family = sorted(
            key
            for key in ("lints.clippy.all", "lints.rust.warnings")
            if isinstance(settings.get(key), str) and settings[key].lower() == "allow"
        )
        if whole_family:
            reasons.append(
                (
                    "cargo.lints-allow-all",
                    "the `lint` gate allows an entire lint family",
                    "Cargo.toml's `[lints]` sets "
                    + ", ".join(f"`{k}` to `allow`" for k in whole_family),
                    "remove the blanket `allow`, or narrow it to the specific lints",
                )
            )
    return reasons


def read_project_settings(destination: Path) -> dict:
    """Merge every config file `destination` holds into one normalized settings dict.

    Files are read in `CONFIG_FILES` order, later ones winning: a dedicated
    `ruff.toml` overrides a `[tool.ruff]` table in `pyproject.toml`, which is
    what ruff itself does.
    """
    merged: dict = {}
    for name, fmt, prefix in CONFIG_FILES:
        path = destination / name
        if path.is_file():
            merged.update(read_config(path, fmt, prefix))
    return merged
