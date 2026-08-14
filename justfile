# Interpreter launcher for `test` (and other dev-only commands that need
# pytest). Defaults to a uv-managed, reproducible dev environment -- see
# [dependency-groups].dev in pyproject.toml and the committed uv.lock.
# Override for contributors not using uv, either per-invocation:
#   just PYTHON='python' test
# or for the session:
#   RAVEN_PYTHON=python just test
# An override interpreter must have the dev group installed itself, e.g.
# `python -m pip install --group dev`.
#
# PYTHON is passed to `_test` as a positional argument ($1), never
# interpolated into the recipe body's shell text (#182): `just`'s {{...}}
# substitution happens before the shell parses the script, so a value
# containing shell metacharacters (`;`, an embedded `"`, ...) would
# otherwise become live shell syntax instead of opaque data --
# `RAVEN_PYTHON='x ; touch INJECTED ; true' just test` used to run the
# injected command. `set positional-arguments` (below) makes the value
# available as $1 in `_test`; unquoted `$1` expansion still splits the
# multi-word default into separate argv words (word-splitting, not
# shell-metacharacter re-parsing), so both are preserved: an attacker's
# `;`/`"` land as inert literal argv text, and the legitimate multi-word
# default still execs correctly.
PYTHON := env_var_or_default("RAVEN_PYTHON", "uv run --group dev python")

set positional-arguments

# Run the test suite
test: (_test PYTHON)

_test python:
    #!/usr/bin/env sh
    if ! $1 -c 'import pytest' >/dev/null 2>&1; then
        echo "error: no pytest available via '$1'." >&2
        if command -v uv >/dev/null 2>&1; then
            echo "Bootstrap the default dev environment and rerun: uv sync --group dev && just test" >&2
        else
            # The fresh-clone case: naming `uv sync` here would just hand the
            # contributor a second `command not found`.
            echo "uv is not installed; install it, then rerun 'just test':" >&2
            echo "  https://docs.astral.sh/uv/getting-started/installation/" >&2
        fi
        echo "Using a different interpreter? Install the dev group into it first:" >&2
        echo "  python -m pip install --group dev" >&2
        echo "  then: just PYTHON='python' test   (or RAVEN_PYTHON=python just test)" >&2
        exit 1
    fi
    $1 -m pytest

# Run lint checks
lint:
    ruff check .

# Format the codebase
format:
    ruff format .

# Check formatting without modifying files
fmt-check:
    ruff format --check .

# Run type checks
typecheck:
    pyright

# Scan staged content for home-directory absolute paths and (if a local
# denylist is configured) private repository names. Repo-only: this is
# Raven's own public-repo hygiene gate (see AGENTS.md's "Public Repository
# Hygiene" section), not part of the shipped python/justfile template, so it
# lives here rather than in a recipe common templates inherit.
hygiene:
    ./scripts/check-staged-hygiene.py

# Fast static checks for the pre-commit hook (no type check, no tests)
check-fast: lint fmt-check hygiene

# Run the standard local verification set (also runs in the pre-push hook).
# A successful run credits the pre-push stamp too, so a manual `just check`
# right before pushing skips a redundant rerun in the hook.
check: check-fast typecheck test
    [ -f .raven/git-hooks/lib/with-verified-cache.sh ] && sh .raven/git-hooks/lib/with-verified-cache.sh check true || true

# Report known advisories in this project's dependency manifests.
#
# Deliberately NOT a dependency of `check`. Every other recipe here is a
# function of the working tree; an audit is a function of the tree AND of what
# the world published overnight, so as a gate it would turn an unchanged commit
# red for reasons no one can fix in that commit. A gate is also binary, while an
# advisory has to be classified first -- see the Advisory Triage section of the
# `raven-dependency-update` skill. Report-only: never fails the shell.
audit:
    #!/usr/bin/env sh
    if ! command -v osv-scanner >/dev/null 2>&1; then
        echo "osv-scanner is not installed; skipping the dependency audit."
        echo "Install: https://google.github.io/osv-scanner/installation/"
        exit 0
    fi
    osv-scanner scan source -r .
    status=$?
    # Documented exit codes: 0 clean, 1-126 result-related (findings),
    # 127 general error, 128 nothing scannable, 129-255 other errors.
    if [ "$status" -eq 0 ]; then
        echo "No known advisories in the scanned manifests."
    elif [ "$status" -ge 1 ] && [ "$status" -le 126 ]; then
        echo "Advisories reported above. Classify each one before remediating"
        echo "(see the raven-dependency-update skill); this is not a gate."
    elif [ "$status" -eq 128 ]; then
        echo "No supported dependency manifest found; nothing to audit."
    else
        echo "osv-scanner exited $status without completing the scan." >&2
    fi
    exit 0

# Install pre-commit (fast checks) and pre-push (full check) git hooks
install-hooks:
    #!/usr/bin/env sh
    # Resolve Git's effective hooks dir (honors core.hooksPath and linked
    # worktrees) so hooks land where Git will run them, not a hard-coded
    # .git/hooks that a custom hooksPath would ignore.
    hooks_dir=$(git rev-parse --git-path hooks) || exit 1
    install_hook() {
        name="$1"
        cmd="$2"
        path="$hooks_dir/$name"
        if [ -f "$path" ]; then
            echo "A $name hook already exists at $path."
            echo "To use RAVEN's gate, add this line to it:"
            printf "  %s\n" "$cmd"
        else
            mkdir -p "$hooks_dir"
            printf '#!/bin/sh\n%s\n' "$cmd" > "$path"
            chmod +x "$path"
            echo "Installed $path to run '$cmd'."
        fi
    }
    install_hook pre-commit "just check-fast"
    install_hook pre-push "just check"
