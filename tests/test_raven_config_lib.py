"""Tests for the shared config parser shipped at .raven/git-hooks/lib/raven_config.py.

This module is loaded from its shipped path (not imported as a package) the
same way every other standalone Raven script under test is -- see
`helpers.load_script_module`.
"""

from __future__ import annotations

import unittest

from helpers import REPO_ROOT, RavenTestCase, load_script_module

MODULE_PATH = REPO_ROOT / "common" / ".raven" / "git-hooks" / "lib" / "raven_config.py"


def _module():
    return load_script_module("raven_config", MODULE_PATH)


class StripCommentTests(unittest.TestCase):
    def test_no_comment_is_unchanged(self):
        self.assertEqual(_module().strip_comment("key = 1"), "key = 1")

    def test_strips_trailing_comment(self):
        self.assertEqual(_module().strip_comment("key = 1  # note"), "key = 1")

    def test_hash_inside_double_quotes_is_not_a_comment(self):
        # The parser-2/3 bug this module exists to fix: a naive
        # `line.split("#", 1)[0]` corrupts a string value containing "#".
        self.assertEqual(_module().strip_comment('key = "a#b"'), 'key = "a#b"')

    def test_hash_inside_single_quotes_is_not_a_comment(self):
        self.assertEqual(_module().strip_comment("key = 'a#b'"), "key = 'a#b'")

    def test_apostrophe_inside_double_quotes_does_not_break_comment_scan(self):
        # The parser-4 bug: a comment-stripper that only tracks `"` corrupts
        # `x = "a's #b"` by treating the apostrophe as significant.
        self.assertEqual(
            _module().strip_comment('key = "it\'s here"  # note'), 'key = "it\'s here"'
        )

    def test_escaped_double_quote_does_not_close_the_string(self):
        self.assertEqual(_module().strip_comment('key = "a\\"#b"'), 'key = "a\\"#b"')

    def test_whole_line_comment_becomes_empty(self):
        self.assertEqual(_module().strip_comment("# just a comment"), "")


class ParseConfigTextTests(unittest.TestCase):
    def test_empty_text_yields_only_the_root_section(self):
        self.assertEqual(_module().parse_config_text(""), {"": {}})

    def test_top_level_keys_live_under_the_empty_section(self):
        parsed = _module().parse_config_text('template = "python"\n')
        self.assertEqual(parsed[""], {"template": '"python"'})

    def test_keyed_values_are_returned_raw_still_quoted(self):
        parsed = _module().parse_config_text('[a]\nkey = "value"\n')
        self.assertEqual(parsed["a"]["key"], '"value"')

    def test_a_hash_inside_a_quoted_value_round_trips(self):
        # Correctness proof required by the issue: this is the parser-2/3 bug.
        parsed = _module().parse_config_text('[a]\nkey = "py#thon"\n')
        self.assertEqual(parsed["a"]["key"], '"py#thon"')

    def test_an_apostrophe_inside_a_quoted_value_round_trips(self):
        # Correctness proof required by the issue: this is the parser-4 bug.
        parsed = _module().parse_config_text("[a]\nkey = \"it's fine\"\n")
        self.assertEqual(parsed["a"]["key"], "\"it's fine\"")

    def test_section_with_no_keys_still_appears(self):
        parsed = _module().parse_config_text("[mcp_servers.semble]\n")
        self.assertIn("mcp_servers.semble", parsed)
        self.assertEqual(parsed["mcp_servers.semble"], {})

    def test_reopened_section_merges_rather_than_resets(self):
        text = "[a]\nx = 1\n[b]\ny = 2\n[a]\nz = 3\n"
        parsed = _module().parse_config_text(text)
        self.assertEqual(parsed["a"], {"x": "1", "z": "3"})

    def test_last_assignment_of_a_key_wins(self):
        parsed = _module().parse_config_text("[a]\nx = 1\nx = 2\n")
        self.assertEqual(parsed["a"]["x"], "2")

    def test_commented_out_key_has_no_effect(self):
        parsed = _module().parse_config_text("[a]\n# x = 1\n")
        self.assertNotIn("x", parsed["a"])

    def test_unrecognized_line_is_skipped_not_raised(self):
        # Deliberately lenient: no exception for a line this subset parser
        # does not understand (e.g. a bare word, or a Codex config construct
        # beyond this subset).
        parsed = _module().parse_config_text("[a]\nnot a valid line\nx = 1\n")
        self.assertEqual(parsed["a"], {"x": "1"})

    def test_array_valued_line_is_kept_as_a_raw_string_not_split(self):
        # None of the six callers need array parsing; a value that looks like
        # an array is still just stored as its raw text.
        parsed = _module().parse_config_text('[mcp_servers.lsp]\nargs = ["--workspace", "."]\n')
        self.assertEqual(parsed["mcp_servers.lsp"]["args"], '["--workspace", "."]')


class ReadConfigTests(RavenTestCase):
    def test_missing_file_returns_none(self):
        module = _module()
        self.assertIsNone(module.read_config(self.destination / "nope" / "config.toml"))

    def test_existing_file_is_parsed(self):
        module = _module()
        path = self.destination / "config.toml"
        path.write_text('template = "python"\n', encoding="utf-8")
        parsed = module.read_config(path)
        self.assertEqual(parsed[""]["template"], '"python"')

    def test_unreadable_file_raises_raven_config_error(self):
        module = _module()
        path = self.destination / "config.toml"
        path.write_text('template = "python"\n', encoding="utf-8")
        path.chmod(0o000)
        try:
            with self.assertRaises(module.RavenConfigError):
                module.read_config(path)
        finally:
            path.chmod(0o644)  # restore so tempdir cleanup can remove it


class ParseBoolTests(unittest.TestCase):
    def test_true_literal(self):
        self.assertIs(_module().parse_bool("true"), True)

    def test_false_literal(self):
        self.assertIs(_module().parse_bool("false"), False)

    def test_whitespace_is_trimmed(self):
        self.assertIs(_module().parse_bool("  true  "), True)

    def test_wrong_typed_value_returns_none(self):
        self.assertIsNone(_module().parse_bool('"maybe"'))

    def test_empty_value_returns_none(self):
        self.assertIsNone(_module().parse_bool(""))

    def test_uppercase_true_is_recognized(self):
        # commit-msg's pre-#201 _BOOL_RE matched true/false via re.IGNORECASE;
        # a config already written with an uppercase value must keep working.
        self.assertIs(_module().parse_bool("TRUE"), True)

    def test_mixed_case_false_is_recognized(self):
        self.assertIs(_module().parse_bool("False"), False)


class ModuleShipsAtItsDocumentedPathTests(unittest.TestCase):
    def test_lives_under_the_hooks_component_lib_directory(self):
        # No new COMPONENT_PATHS entry is needed: `.raven/git-hooks` (the
        # whole directory, including lib/) already ships under the "hooks"
        # component. This test pins the file to that existing path so a
        # future move would fail loudly here instead of silently breaking
        # every caller's relative import.
        self.assertTrue(MODULE_PATH.is_file())
        self.assertEqual(MODULE_PATH.parent.name, "lib")
        self.assertEqual(MODULE_PATH.parent.parent.name, "git-hooks")


if __name__ == "__main__":
    unittest.main()
