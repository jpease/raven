#!/usr/bin/env sh
#
# Skip a heavy verification command when the current commit already passed it
# against a clean working tree, so back-to-back runs (a manual `just check`
# right before `git push`, or a rejected push followed by `git pull --rebase
# && git push`) don't repeat identical work.
#
# Correctness rules:
#   - The stamp is written ONLY after the command exits 0 AND the tree is
#     clean. A partial, failed, or interrupted run never writes it, so it can
#     never be mistaken for a full pass.
#   - The stamp is keyed by <label>, so independently-cached commands (e.g.
#     "check-fast" vs "check") keep separate stamps -- a partial gate can't
#     satisfy a fuller one.
#   - "Clean tree" means `git status --porcelain` is empty (untracked,
#     non-ignored files count as dirty). Any uncommitted change or new commit
#     invalidates the stamp for free.
#   - The stamp is an optimization, never a correctness dependency: a
#     missing, unreadable, or unwritable stamp simply falls through to
#     running the command.
#   - --force skips the cache *read* (the command always runs) but still
#     performs the cache *write* on success. Raven's pre-push hook uses this
#     when it cannot trust the cache: a push whose local ref differs from
#     this worktree's HEAD proves nothing about that HEAD having been
#     vetted, but if HEAD itself still passes here, that success is worth
#     recording for a later push of HEAD itself.
#
# Usage: with-verified-cache.sh [--force] <label> <command> [args...]

force=0
if [ "$1" = "--force" ]; then
    force=1
    shift
fi

if [ "$#" -lt 2 ]; then
    echo "usage: $0 [--force] <label> <command> [args...]" >&2
    exit 2
fi

label="$1"
shift

git_dir=$(git rev-parse --git-dir 2>/dev/null) || exec "$@"
[ -n "$git_dir" ] || exec "$@"

# On an unborn HEAD (no commits yet), `git rev-parse HEAD` exits non-zero but
# still echoes the literal unresolved arg "HEAD" to stdout (its fallback
# pathspec-passthrough behavior) -- checking the exit status directly, not
# just whether stdout came back non-empty, is what keeps that garbage out of
# head_sha.
head_sha=$(git rev-parse HEAD 2>/dev/null) || head_sha=""
stamp="$git_dir/verified-$label"

is_clean() {
    [ -z "$(git status --porcelain 2>/dev/null)" ]
}

if [ "$force" -eq 0 ] && [ -n "$head_sha" ] && is_clean \
    && [ "$head_sha" = "$(cat "$stamp" 2>/dev/null)" ]; then
    echo "✓ $label already passed for ${head_sha} against a clean tree -- skipping." >&2
    exit 0
fi

status=0
"$@" || status=$?

# Only a full success against a still-clean tree earns the stamp.
if [ "$status" -eq 0 ] && [ -n "$head_sha" ] && is_clean; then
    printf '%s\n' "$head_sha" >"$stamp" 2>/dev/null || true
fi

exit "$status"
