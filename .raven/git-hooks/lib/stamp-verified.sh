#!/usr/bin/env sh
# Records that the full verification gate passed against the current commit,
# so the pre-push hook can skip re-running it if the same commit is pushed
# again with a clean tree. Called from the pre-push hook after `just check`
# passes, and from the `check` recipe itself so a manual run earns the same
# credit -- the skip invariant (HEAD SHA + clean tree, re-checked here rather
# than assumed) is what makes a run trustworthy, not which caller triggered
# it. The stamp is an optimization: any failure below is swallowed rather
# than surfacing as an error.
head_sha=$(git rev-parse HEAD 2>/dev/null) || exit 0
[ -n "$head_sha" ] || exit 0
[ -z "$(git status --porcelain 2>/dev/null)" ] || exit 0
stamp="$(git rev-parse --git-dir)/raven-pre-push-verified"
printf '%s\n' "$head_sha" > "$stamp" 2>/dev/null || true
