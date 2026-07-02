#!/usr/bin/env python3
"""List open issues as a nested tree.

Hierarchy is assembled in priority order from three sources:
  Pass 0: GitHub's native sub-issue (`parent`) links — authoritative.
  Pass 1: a "Parent epic: #N" line in the issue body (legacy/manual).
  Pass 2: references to non-epic issues in an epic's own body/comments.
Issues with no parent from any pass surface as top-level roots. Within each
level, epics sort first, then by an explicit `[X:x/y]` title order tag if
present, otherwise by priority label then issue number.
"""

import json
import re
import subprocess
import sys
from collections import defaultdict

OWNER = "jpease"
REPO = "raven"


def run_gh_command(args):
    result = subprocess.run(["gh", *args], capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Error running gh command: {result.stderr}", file=sys.stderr)
        return None
    return result.stdout


def get_issues():
    query = f"""
    query($cursor: String) {{
      repository(owner: "{OWNER}", name: "{REPO}") {{
        issues(first: 100, after: $cursor, states: OPEN) {{
          pageInfo {{ hasNextPage endCursor }}
          nodes {{
            number
            title
            body
            labels(first: 20) {{ nodes {{ name }} }}
            parent {{ number }}
            comments(first: 100) {{ nodes {{ body }} }}
          }}
        }}
      }}
    }}
    """

    nodes = []
    cursor = None
    while True:
        args = ["api", "graphql", "-f", f"query={query}"]
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
    return 99


def is_epic(issue):
    return any(label["name"] == "type:epic" for label in issue["labels"]["nodes"])


def main():
    issues = get_issues()
    if not issues:
        return

    issue_map = {issue["number"]: issue for issue in issues}

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

    # Pass 1: task/epic bodies declare their own parent via "Parent epic: #N".
    for issue in issues:
        num = issue["number"]
        body = issue.get("body", "") or ""
        match = re.search(r"^Parent epic[^:]*: #(\d+)", body, re.MULTILINE)
        if match:
            parent = int(match.group(1))
            if parent in issue_map and num not in child_of:
                child_of[num] = parent
                children[parent].append(num)

    # Pass 2: epics list children in body/comments (catches any not already assigned).
    for issue in issues:
        num = issue["number"]
        if not is_epic(issue):
            continue
        all_text = (
            (issue.get("body", "") or "")
            + "\n"
            + "\n".join(comment["body"] for comment in issue["comments"]["nodes"])
        )
        for ref_str in re.findall(r"#(\d+)", all_text):
            ref = int(ref_str)
            if ref == num or ref not in issue_map:
                continue
            # Only pull in non-epics as children this way; epics declare their
            # own parents via "Parent epic: #N" in their body (Pass 1).
            if is_epic(issue_map[ref]):
                continue
            if ref not in child_of:
                child_of[ref] = num
                children[num].append(ref)

    # Sort children: epics first, then by explicit [X:x/y] order tag when present,
    # otherwise fall back to priority then issue number.
    def order_tag(issue):
        match = re.match(r"\s*\[[A-Za-z]+:(\d+)/\d+\]", issue.get("title", "") or "")
        return int(match.group(1)) if match else None

    def child_sort_key(n):
        issue = issue_map.get(n, {})
        epic_first = 0 if is_epic(issue) else 1
        tag = order_tag(issue)
        if tag is not None:
            return (epic_first, 0, tag, 0)
        return (epic_first, 1, get_priority(issue), n)

    for parent in children:
        children[parent].sort(key=child_sort_key)

    roots = [issue["number"] for issue in issues if issue["number"] not in child_of]
    roots.sort(key=lambda n: (0 if is_epic(issue_map[n]) else 1, get_priority(issue_map[n]), n))

    def print_tree(num, indent=0):
        issue = issue_map.get(num)
        if not issue:
            return
        priority = get_priority(issue)
        p_str = f"P{priority}" if priority < 99 else "---"
        prefix = "  " * indent
        marker = "↳ " if indent > 0 else ""
        print(f"{prefix}{marker}[{p_str}] #{num} - {issue['title']}")
        for child in children.get(num, []):
            print_tree(child, indent + 1)

    for root in roots:
        print_tree(root)
        if children.get(root):
            print()


if __name__ == "__main__":
    main()
