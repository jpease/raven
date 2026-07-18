import json
import unittest
from unittest.mock import patch

from helpers import REPO_ROOT, load_script_module

LIST_OPEN_ISSUES = REPO_ROOT / "scripts" / "list_open_issues.py"
# list_open_issues.py is a symlink to a shared copy kept outside this repo
# (a single source of truth reused across repos), so it isn't present on
# every checkout -- e.g. CI. Skip rather than fail when the target is
# unavailable, matching the HAVE_ASTGREP/HAVE_RG pattern in test_skeleton.py.
HAVE_LIST_OPEN_ISSUES = LIST_OPEN_ISSUES.exists()


def _page(nodes, has_next, cursor=None):
    return json.dumps(
        {
            "data": {
                "repository": {
                    "issues": {
                        "pageInfo": {"hasNextPage": has_next, "endCursor": cursor},
                        "nodes": nodes,
                    }
                }
            }
        }
    )


@unittest.skipUnless(HAVE_LIST_OPEN_ISSUES, "list_open_issues.py symlink target not available")
class GetIssuesPaginationTest(unittest.TestCase):
    def setUp(self):
        self.module = load_script_module("list_open_issues_under_test", LIST_OPEN_ISSUES)

    def test_failed_page_aborts_instead_of_returning_partial_results(self):
        first_page = _page([{"number": 1, "title": "one"}], has_next=True, cursor="abc")

        with (
            patch.object(self.module, "run_gh_command", side_effect=[first_page, None]),
            self.assertRaises(SystemExit) as ctx,
        ):
            self.module.get_issues("owner", "repo")

        self.assertNotEqual(ctx.exception.code, 0)

    def test_all_pages_succeed_returns_all_nodes(self):
        first_page = _page([{"number": 1, "title": "one"}], has_next=True, cursor="abc")
        second_page = _page([{"number": 2, "title": "two"}], has_next=False)

        with patch.object(self.module, "run_gh_command", side_effect=[first_page, second_page]):
            issues = self.module.get_issues("owner", "repo")

        self.assertEqual([issue["number"] for issue in issues], [1, 2])


if __name__ == "__main__":
    unittest.main()
