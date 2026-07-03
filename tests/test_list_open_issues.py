import json
import unittest
from unittest.mock import patch

from helpers import REPO_ROOT, load_script_module

LIST_OPEN_ISSUES = REPO_ROOT / "scripts" / "list_open_issues.py"


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
