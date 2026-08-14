#!/usr/bin/env python3
"""Block AI attribution mentions from leaking into staged/outbound content.

The commit-msg hook strips attribution *trailers* at commit time -- but an
AI-authorship credit left in a source file or README (an AI tool named as the
generator) would still reach history untouched. Unlike commit-msg, this fails
the commit/push rather than silently editing tracked file content: there is no
safe way to auto-rewrite an arbitrary line inside a source file.

The `outbound --push-plan` path additionally scans commit *messages*, which
commit-msg cannot vouch for. Stripping only happens when that hook ran, and it
routinely does not: `git commit --no-verify`, `git cherry-pick` and `git
rebase` reapplying pre-hook commits (neither runs commit-msg), and any clone
made before the hooks were installed all land a trailer in history that
strip-time never saw. Pre-push is where that is discoverable.

Modes:

    staged                    scan the staged diff (pre-commit)
    outbound                  scan HEAD against its upstream (direct/manual use)
    outbound --push-plan      scan the refs Git is actually pushing, read from
                              stdin in Git's own pre-push format:
                              "<local-ref> <local-sha> <remote-ref> <remote-sha>"
                              per line. Add --remote <name> (Git's first
                              pre-push argument) to bound the scan by that
                              remote's tracking refs.

Ref updates arrive on stdin rather than argv so an arbitrarily large push
(`git push --all` on a many-branch repo) cannot overflow the argument list, and
so the hook can forward Git's plan byte-for-byte without re-quoting it in POSIX
sh. Reading stdin is opt-in via --push-plan, which keeps the bare `outbound`
invocation (used by hand and by this repo's tests) from blocking on a terminal.

Fail-open by design: this gate gates pushes, so anything it cannot evaluate
(unresolvable object, absent plan, failing git invocation) is skipped rather
than treated as a finding. A hook that blocks every push on an internal error
is worse than the leak it is meant to catch.
"""

from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path

_CONTENT_PATTERN = re.compile(
    r"(?:generated|written|authored|implemented|drafted)\s+(?:by|with)\s+.*"
    r"(?:claude|copilot|codex|chatgpt|gpt-[0-9]+|gemini|llama|mistral"
    r"|@anthropic\.com|@openai\.com)",
    re.IGNORECASE,
)

# Commit-message trailers, matched per line. Deliberately a copy of the
# commit-msg hook's `_AI_TRAILER` rather than an import: that hook is a
# standalone script with no dependency on this lib/ directory, and a partial
# install must not be able to break it. `test_message_pattern_matches_the_
# commit_msg_hook_pattern` pins the two together so they cannot drift.
_MESSAGE_PATTERN = re.compile(
    r"^(?:co-authored-by|generated-by):\s+.*"
    r"(?:(?:claude|copilot|codex|chatgpt|gpt-[0-9]+|gemini|llama|mistral"
    r"|@anthropic\.com|@openai\.com)"
    r"|<noreply@[^>]+>)"
    r"|^claude-session:\s+\S+",
    re.IGNORECASE,
)


def _raven_config_module():
    """Import the ``raven_config.py`` sibling shipped in this same directory.

    This file already lives at ``.raven/git-hooks/lib/``, the same directory
    ``raven_config.py`` ships in -- a fixed, flat sibling resolution, unlike
    commit-msg's own loader, which has to climb up one level from
    ``.raven/git-hooks/`` into ``lib/`` first. Same
    ``spec_from_file_location`` + ``SourceFileLoader`` mechanism used
    throughout the other rewired callers.
    """
    path = Path(__file__).resolve().parent / "raven_config.py"
    spec = importlib.util.spec_from_file_location(
        "raven_config_for_attribution_content",
        path,
        loader=SourceFileLoader("raven_config_for_attribution_content", str(path)),
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"could not load raven_config from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _read_config_bool(config_path: Path, section: str, key: str, default: bool) -> bool:
    """Read a boolean flag from ``config_path``, defaulting on anything short of a clean read.

    Was previously a byte-for-byte copy of commit-msg's own regex-based
    ``_read_config_bool`` (deliberately, per that hook's docstring, since it
    cannot depend on this lib/ directory) -- but this file already lives
    alongside the shared parser, so there is no reason for it to carry its
    own duplicate implementation too. Also fixes the same pre-existing gap as
    commit-msg's copy: an unreadable-but-present config used to propagate an
    uncaught ``OSError`` instead of falling back to ``default`` like every
    other read failure here already did.
    """
    raven_config = _raven_config_module()
    try:
        parsed = raven_config.read_config(config_path)
    except raven_config.RavenConfigError:
        return default
    if parsed is None:
        return default
    raw_value = parsed.get(section, {}).get(key)
    if raw_value is None:
        return default
    parsed_value = raven_config.parse_bool(raw_value)
    return default if parsed_value is None else parsed_value


def _repo_root() -> Path | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
        )
        return Path(result.stdout.strip())
    except subprocess.CalledProcessError:
        return None


def _git(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], capture_output=True, text=True)


def _added_lines(diff_text: str) -> list[str]:
    # Unified diff: "+++ " is the new-file header, not an added line; every
    # other "+"-prefixed line is content actually entering the tree.
    return [
        line
        for line in diff_text.splitlines()
        if line.startswith("+") and not line.startswith("+++")
    ]


def _scan(added_lines: list[str], label: str) -> int:
    hits = [line for line in added_lines if _CONTENT_PATTERN.search(line)]
    if not hits:
        return 0
    print(f"Forbidden AI attribution content found in {label}:", file=sys.stderr)
    for hit in hits:
        print(hit, file=sys.stderr)
    print(
        "remove generated-attribution mentions from newly added repository text",
        file=sys.stderr,
    )
    return 1


def _scan_messages(message_text: str, label: str) -> int:
    hits = [line for line in message_text.splitlines() if _MESSAGE_PATTERN.match(line)]
    if not hits:
        return 0
    print(f"Forbidden AI attribution trailer found in a commit message ({label}):", file=sys.stderr)
    for hit in hits:
        print(hit, file=sys.stderr)
    print(
        "amend or rebase the commit to drop the attribution trailer "
        "(commit-msg strips these, but only when it runs)",
        file=sys.stderr,
    )
    return 1


def _scan_staged() -> int:
    diff = _git(["diff", "--cached", "--no-color", "--unified=0", "--", "."])
    return _scan(_added_lines(diff.stdout), "staged diff")


#: Conventional default-branch names, tried in order when the clone has no
#: `origin/HEAD` to ask. Raven is a template: it cannot know which name a
#: consumer picked, and assuming one turns the whole outbound scan into a
#: silent pass for every repository that picked another.
FALLBACK_DEFAULT_BRANCHES = ("main", "master", "develop", "trunk")


def _default_remote_branch() -> str | None:
    """Remote-tracking ref a no-upstream scan should compare against, or None.

    Asks git for `origin/HEAD` first, which is what the remote actually says
    its default branch is, so this needs no configuration and keeps working if
    that default ever moves. Only when the clone has no `origin/HEAD` -- it is
    not created by `git clone --single-branch`, among others -- does it guess
    from `FALLBACK_DEFAULT_BRANCHES`.

    This previously hardcoded a single conventional name. That is correct in
    Raven's own repository and wrong in any consumer that chose differently,
    which is the worst shape for a template defect: the tests pass upstream and
    the scan quietly does nothing downstream.
    """
    head = _git(["symbolic-ref", "--short", "refs/remotes/origin/HEAD"])
    if head.returncode == 0 and head.stdout.strip():
        return head.stdout.strip()
    for name in FALLBACK_DEFAULT_BRANCHES:
        ref = f"origin/{name}"
        if _git(["show-ref", "--verify", "--quiet", f"refs/remotes/{ref}"]).returncode == 0:
            return ref
    return None


def _outbound_range() -> str | None:
    upstream = _git(["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"])
    if upstream.returncode == 0 and upstream.stdout.strip():
        return f"{upstream.stdout.strip()}..HEAD"
    base = _default_remote_branch()
    return f"{base}..HEAD" if base else None


def _scan_outbound() -> int:
    range_spec = _outbound_range()
    if range_spec is None:
        # No upstream and no remote default branch to diff against; nothing to
        # compare, so skip rather than block a push this cannot evaluate.
        return 0
    diff = _git(["diff", "--no-color", "--unified=0", range_spec, "--", "."])
    return _scan(_added_lines(diff.stdout), f"git diff ({range_spec})")


def _is_zero_sha(sha: str) -> bool:
    return sha != "" and set(sha) == {"0"}


def _parse_push_plan(text: str) -> list[tuple[str, str, str, str]]:
    """Parse Git's pre-push stdin plan; ignore anything not shaped like a ref update."""
    updates = []
    for line in text.splitlines():
        fields = line.split()
        if len(fields) < 4:
            continue
        updates.append((fields[0], fields[1], fields[2], fields[3]))
    return updates


def _resolve_commit(rev: str) -> str | None:
    result = _git(["rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}"])
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _remote_tracking_shas(remote: str) -> list[str]:
    """Commits the remote is known to already have, as exclusion tips.

    Prefer the named remote's tracking refs: content already published to
    `origin` is not necessarily published on the `fork` being pushed to, so
    scoping matters. Fall back to every remote only when the named one has no
    tracking refs at all (an unfetched or URL-only remote), which at worst
    widens the exclusion set to commits that have provably left the machine.
    Resolved to SHAs rather than passed as a `--remotes=<glob>` so a remote
    "name" that is really a URL (Git passes the URL for both arguments on
    `git push <url> <ref>`) cannot produce an invalid refname pattern.
    """
    if remote:
        scoped = _git(["rev-parse", f"--remotes={remote}"])
        scoped_shas = scoped.stdout.split() if scoped.returncode == 0 else []
        if scoped_shas:
            return scoped_shas
    every = _git(["rev-parse", "--remotes"])
    if every.returncode != 0:
        return []
    return every.stdout.split()


_UNBOUNDED_NOTICE = (
    "note: no remote baseline -- this remote has no tracking refs in this clone, "
    "so nothing is known to be already published and the scan covered the full "
    "history rather than only new commits. The findings above may predate this "
    "branch and may not be fixable without rewriting history. To publish anyway, "
    "set block_ai_attribution_content = false under [git_hooks] in "
    ".raven/config.toml."
)


def _scan_push_plan(plan_text: str, remote: str) -> int:
    """Scan the commits Git is actually pushing, per its own push plan.

    One scan covers the whole push: every pushed tip is a positive revision and
    everything the remote already has is negative, so commits reachable from two
    pushed refs are scanned once and a hit on any ref fails the push.

    The negative side is what keeps this bounded. A new branch has an all-zero
    remote SHA and no valid `<remote>..<local>` range; walking back to the root
    commit instead would rescan the entire repository and flag every historical
    mention. Excluding the remote's tracking refs narrows it to the commits that
    are genuinely new to that remote. The same exclusion also handles a
    force-push, where the old remote SHA is not an ancestor of the new tip: the
    rewritten commits are new objects entering the remote's history, so they are
    exactly what gets scanned, while the commits behind the old tip stay
    excluded. For an ordinary fast-forward this reduces to `<remote>..<local>`.

    Commits are scanned via per-commit patches rather than a two-tree diff of
    the endpoints, so merging an already-published branch in does not re-report
    that branch's content as newly added. The trade-off is that a merge commit
    contributes no patch of its own, leaving content introduced solely by a
    conflict resolution to the staged (pre-commit) scan.

    The same revision set is scanned twice: once for file content and once for
    commit messages, which the commit-msg hook can only vouch for on commits it
    actually ran on.

    When the remote has no tracking refs at all, the negative side is empty and
    the walk does reach the root commit. That is intentional and pinned by test:
    nothing is known to be published, so every reachable commit genuinely is
    leaving the machine for the first time and scanning all of it is the correct
    answer rather than a false positive. It is not the fail-open case -- the
    scan is fully evaluable, just wide -- so findings are reported, with
    `_UNBOUNDED_NOTICE` explaining why they may reach further back than the
    push. Only unevaluable states (unresolvable object, failing git invocation)
    skip.
    """
    positives: list[str] = []
    negatives: list[str] = []
    pushed_refs: list[str] = []
    for local_ref, local_sha, _remote_ref, remote_sha in _parse_push_plan(plan_text):
        if _is_zero_sha(local_sha):
            continue  # deletion: no content is leaving the machine
        local = _resolve_commit(local_sha)
        if local is None:
            continue  # fail-open: an object this repo cannot resolve is unevaluable
        positives.append(local)
        pushed_refs.append(local_ref)
        if not _is_zero_sha(remote_sha):
            # Whatever the remote already has for this ref is published, whether
            # or not it is an ancestor of the new tip (i.e. also on a force-push).
            remote_tip = _resolve_commit(remote_sha)
            if remote_tip is not None:
                negatives.append(remote_tip)
    if not positives:
        return 0

    negatives.extend(_remote_tracking_shas(remote))
    # An exclusion tip that equals a pushed tip is kept, not dropped: it means the
    # remote already has that commit (e.g. pushing an existing tip under a new
    # branch name), and the correct outcome is an empty scan, not a full rescan.
    revs = list(dict.fromkeys(positives))
    bounds = ["--not", *dict.fromkeys(negatives)] if negatives else []
    label = f"outbound commits for {', '.join(pushed_refs)}"

    content = _git(
        ["log", "--no-color", "--format=%H", "--unified=0", "-p", *revs, *bounds, "--", "."]
    )
    if content.returncode != 0:
        # git could not walk the range (e.g. a corrupt or grafted object); skip
        # rather than block a push this hook cannot evaluate.
        return 0
    content_status = _scan(_added_lines(content.stdout), label)

    # Messages get their own invocation rather than a widened --format on the one
    # above: keeping the two streams apart means no delimiter has to survive
    # adversarial patch text, and no patch line can be read as a message (or the
    # reverse). No pathspec here -- every pushed commit's message counts,
    # including a merge's, which contributes no patch of its own.
    messages = _git(["log", "--no-color", "--no-patch", "--format=%B", *revs, *bounds])
    message_status = 0
    if messages.returncode == 0:
        message_status = _scan_messages(messages.stdout, label)

    if not (content_status or message_status):
        return 0
    if not bounds:
        print(_UNBOUNDED_NOTICE, file=sys.stderr)
    return 1


_USAGE = "usage: check-ai-attribution-content.py {staged|outbound} [--push-plan] [--remote NAME]"


def main() -> int:
    """CLI entry point: scan staged content or an outbound push for AI-attribution phrases.

    Config-gated: ``.raven/config.toml``'s ``block_ai_attribution_content`` (default
    on) can disable the check entirely for a repo that wants attribution left in.
    """
    argv = sys.argv[1:]
    mode = argv[0] if argv else ""
    if mode not in ("staged", "outbound"):
        print(_USAGE, file=sys.stderr)
        return 1

    use_push_plan = False
    remote = ""
    rest = argv[1:]
    index = 0
    while index < len(rest):
        arg = rest[index]
        if arg == "--push-plan":
            use_push_plan = True
        elif arg == "--remote":
            index += 1
            remote = rest[index] if index < len(rest) else ""
        elif arg.startswith("--remote="):
            remote = arg.split("=", 1)[1]
        else:
            # Warn but keep going: an unrecognized flag means hook and lib are
            # out of step (a partial install), and refusing to run would block
            # every push in the repo.
            print(f"warning: ignoring unrecognized argument {arg!r}", file=sys.stderr)
        index += 1

    root = _repo_root()
    if root is not None:
        config = root / ".raven" / "config.toml"
        if not _read_config_bool(config, "git_hooks", "block_ai_attribution_content", default=True):
            return 0

    if mode == "staged":
        return _scan_staged()
    if use_push_plan:
        try:
            plan_text = sys.stdin.read()
        except OSError:
            return 0
        # Deliberately no fallback to the HEAD-relative range here: when a plan
        # was supplied, HEAD may be an unrelated branch, and scanning it is the
        # bug this path exists to fix (issue #126).
        return _scan_push_plan(plan_text, remote)
    return _scan_outbound()


if __name__ == "__main__":
    sys.exit(main())
