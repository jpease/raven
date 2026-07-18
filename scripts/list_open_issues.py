#!/usr/bin/env python3
"""List open issues as a nested epic/task tree, sorted by priority.

Portable across repos: owner/repo are auto-detected via `gh repo view`
(override with two positional args: `list_open_issues.py OWNER REPO`).

Hierarchy is assembled in priority order from three sources:
  Pass 0: GitHub's native sub-issue (`parent`) link — authoritative.
  Pass 1: a declared parent in the issue's own body — either
          "Parent epic: #N" or "Part of Epic #N" (different repos use
          different conventions; both are recognized).
  Pass 2: `#N` references inside an epic's own body/comments, for repos
          that track children via an "Ordered Checklist" instead of a
          native sub-issue link or a declared-parent line.
Issues whose parent is closed (or otherwise not in the open set) surface
as top-level roots.

Sibling ordering, applied uniformly at every depth:
  1. Epics first — detected by a `type:epic` label OR an `Epic:`/`Sub-epic:`
     title prefix (optionally preceded by a bracket tag), since repos vary
     on which convention they use.
  2. An issue's own `[X:x/y]` execution-order title tag (X = recommended
     model letter, x = order, y = total) sorts ahead of untagged siblings.
  3. An untagged *non-epic* container inherits the smallest order tag among
     its descendants, so it slots in where its first child step does
     rather than sinking to the bottom.
  4. A top-level epic's own bare `[x/y]` tag (no model letter) orders it
     among other epics; an epic without one sinks to the bottom of the
     epic group.
  5. Otherwise: priority label, then issue number.
"""

import json
import re
import subprocess
import sys
from collections import defaultdict


def run_gh_command(args):
    result = subprocess.run(["gh", *args], capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Error running gh command: {result.stderr}", file=sys.stderr)
        return None
    return result.stdout


def get_repo_info():
    stdout = run_gh_command(["repo", "view", "--json", "owner,name"])
    if stdout is None:
        print(
            "Error: could not detect owner/repo via `gh repo view`. "
            "Run inside a GitHub repo with `gh` authenticated, or pass "
            "`OWNER REPO` explicitly.",
            file=sys.stderr,
        )
        sys.exit(1)
    data = json.loads(stdout)
    return data["owner"]["login"], data["name"]


def get_issues(owner, repo):
    query = """
    query($cursor: String, $owner: String!, $repo: String!) {
      repository(owner: $owner, name: $repo) {
        issues(first: 100, after: $cursor, states: OPEN) {
          pageInfo { hasNextPage endCursor }
          nodes {
            number
            title
            body
            labels(first: 20) { nodes { name } }
            parent { number }
            comments(first: 100) { nodes { body } }
          }
        }
      }
    }
    """

    nodes = []
    cursor = None
    while True:
        args = [
            "api",
            "graphql",
            "-f",
            f"query={query}",
            "-f",
            f"owner={owner}",
            "-f",
            f"repo={repo}",
        ]
        if cursor:
            args += ["-f", f"cursor={cursor}"]
        stdout = run_gh_command(args)
        if stdout is None:
            print(
                "Error: gh command failed while paginating issues; "
                "aborting to avoid rendering a truncated tree.",
                file=sys.stderr,
            )
            sys.exit(1)
        page = json.loads(stdout)["data"]["repository"]["issues"]
        nodes.extend(page["nodes"])
        if not page["pageInfo"]["hasNextPage"]:
            break
        cursor = page["pageInfo"]["endCursor"]
    return nodes


def get_priority(issue):
    for label in issue["labels"]["nodes"]:
        name = label["name"]
        if name.startswith("priority:P"):
            try:
                return int(name[len("priority:P") :])
            except ValueError:
                pass
    return 99  # Default low priority


# Epics/sub-epics are containers and render first within any sibling group.
# Detected either by a `type:epic` label or an `Epic:`/`Sub-epic:` title
# prefix (itself optionally preceded by a bracket order tag, e.g. "[2/3]
# Epic: ..."). Different repos use one convention or the other.
_EPIC_PREFIX = re.compile(
    r"^\s*(?:\[[^\]]*\]\s*)?(?:sub-?epic|epic)\s*:", re.IGNORECASE
)

# Task execution-order tag, e.g. "[O:3/15]" or "[S:1/2]", at the very start
# of the title (X = model letter, x = order, y = total).
_ORDER_TAG = re.compile(r"^\s*\[[A-Za-z]+:(\d+)/\d+\]")

# Top-level epic forward-order tag: a bare "[x/y]" (no model letter).
# Disjoint from _ORDER_TAG, which requires a letter before the colon.
_EPIC_ORDER_TAG = re.compile(r"^\s*\[(\d+)/\d+\]")

# Pass 1 declared-parent conventions (both are used across repos).
_PARENT_EPIC_RE = re.compile(r"^Parent epic[^:]*:\s*#(\d+)", re.MULTILINE)
_PART_OF_EPIC_RE = re.compile(r"Part of Epic #(\d+)")


def is_epic(issue):
    if any(label["name"] == "type:epic" for label in issue["labels"]["nodes"]):
        return True
    return bool(_EPIC_PREFIX.match(issue.get("title", "") or ""))


def order_tag(issue):
    match = _ORDER_TAG.match(issue.get("title", "") or "")
    return int(match.group(1)) if match else None


def epic_order(issue):
    match = _EPIC_ORDER_TAG.match(issue.get("title", "") or "")
    return int(match.group(1)) if match else None


def declared_parent(issue):
    body = issue.get("body") or ""
    match = _PARENT_EPIC_RE.search(body) or _PART_OF_EPIC_RE.search(body)
    return int(match.group(1)) if match else None


def build_hierarchy(issues, issue_map):
    children = defaultdict(list)  # parent_num -> [child_num, ...]
    child_of = {}  # child_num -> parent_num

    # Pass 0: native sub-issue relationships take precedence over body text.
    for issue in issues:
        num = issue["number"]
        parent_obj = issue.get("parent")
        if parent_obj:
            parent = parent_obj["number"]
            if parent in issue_map and num not in child_of:
                child_of[num] = parent
                children[parent].append(num)

    # Pass 1: the issue's own body declares its parent explicitly. Applies
    # to epics and tasks alike, so sub-epics can nest under a parent epic.
    for issue in issues:
        num = issue["number"]
        parent = declared_parent(issue)
        if parent is not None and parent in issue_map and num not in child_of:
            child_of[num] = parent
            children[parent].append(num)

    # Pass 2: epics list children in their own body/comments (catches any
    # not already assigned via native links or a declared-parent line).
    for issue in issues:
        num = issue["number"]
        if not is_epic(issue):
            continue
        all_text = (
            (issue.get("body") or "")
            + "\n"
            + "\n".join(c["body"] for c in issue["comments"]["nodes"])
        )
        for ref_str in re.findall(r"#(\d+)", all_text):
            ref = int(ref_str)
            if ref == num or ref not in issue_map:
                continue
            # Only pull in non-epics this way; an epic attaches to its
            # parent via Pass 0/1, not by casual mention.
            if is_epic(issue_map[ref]):
                continue
            if ref not in child_of:
                child_of[ref] = num
                children[num].append(ref)

    return children, child_of


def main():
    if len(sys.argv) == 3:
        owner, repo = sys.argv[1], sys.argv[2]
    elif len(sys.argv) == 1:
        owner, repo = get_repo_info()
    else:
        print("Usage: list_open_issues.py [OWNER REPO]", file=sys.stderr)
        sys.exit(1)

    issues = get_issues(owner, repo)
    if not issues:
        return

    issue_map = {issue["number"]: issue for issue in issues}
    children, child_of = build_hierarchy(issues, issue_map)

    # Effective order: an issue's own [X:x/y] tag, or — for an untagged
    # *non-epic* container — the smallest effective order among its
    # descendants, so the container slots into the sequence right where its
    # first child step does (rather than after tagged siblings). Epics do
    # NOT inherit a child order this way; they sort by their own bare
    # [x/y] forward-order tag instead (see sort_key).
    effective_order = {}

    def compute_order(num):
        if num in effective_order:
            return effective_order[num]
        own = order_tag(issue_map[num])
        child_orders = [
            o for c in children.get(num, []) if (o := compute_order(c)) is not None
        ]
        if own is not None:
            result = own
        elif child_orders and not is_epic(issue_map[num]):
            result = min(child_orders)
        else:
            result = None
        effective_order[num] = result
        return result

    for num in issue_map:
        compute_order(num)

    def sort_key(n):
        issue = issue_map[n]
        if is_epic(issue):
            # Epics render first. Among them, those carrying a bare [x/y]
            # forward-order sort by it; any epic without one (e.g. a
            # backlog/holding epic) sinks to the bottom of the epic group.
            eo = epic_order(issue)
            if eo is not None:
                return (0, 0, eo, n)
            return (0, 1, get_priority(issue), n)
        # Non-epics sort after epics: by task execution order (own or
        # inherited) ahead of untagged/unordered siblings, else priority.
        order = effective_order.get(n)
        if order is not None:
            return (1, 0, order, n)
        return (1, 1, get_priority(issue), n)

    def sort_nums(nums):
        return sorted(nums, key=sort_key)

    roots = [num for num in issue_map if num not in child_of]

    def print_tree(num, depth=0):
        issue = issue_map[num]
        priority = get_priority(issue)
        p_str = f"P{priority}" if priority < 99 else "---"
        prefix = "  " * depth
        marker = "↳ " if depth > 0 else ""
        print(f"{prefix}{marker}[{p_str}] #{num} - {issue['title']}")
        for child in sort_nums(children.get(num, [])):
            print_tree(child, depth + 1)

    for root in sort_nums(roots):
        print_tree(root)
        if children.get(root):
            print()


if __name__ == "__main__":
    main()
