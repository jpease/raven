import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from typing import ClassVar

from helpers import REPO_ROOT, RavenTestCase, load_script_module

HAVE_ASTGREP = shutil.which("ast-grep") is not None
HAVE_RG = shutil.which("rg") is not None


def _have_universal_ctags() -> bool:
    binary = shutil.which("ctags")
    if binary is None:
        return False
    try:
        version = subprocess.run([binary, "--version"], capture_output=True, text=True, check=False)
    except OSError:
        return False
    return "Universal Ctags" in version.stdout


HAVE_UNIVERSAL_CTAGS = _have_universal_ctags()

SKELETON_SCRIPT = REPO_ROOT / "common" / ".claude" / "scripts" / "raven-skeleton.py"


def _module():
    return load_script_module("raven_skeleton", SKELETON_SCRIPT)


class ExclusiveRangeConversionTests(RavenTestCase):
    """ast-grep emits zero-based lines with an exclusive end (tree-sitter
    convention). The generator must convert these to one-based inclusive
    line numbers that match how editors and ``Read`` count lines."""

    def test_multiline_symbol_with_nonzero_end_column(self):
        module = _module()
        # `def` on line 0, body ending mid-line on line 1, column 16.
        start = {"line": 0, "column": 0}
        end = {"line": 1, "column": 16}

        self.assertEqual(module.exclusive_range_to_lines(start, end), (1, 2))

    def test_block_ending_at_column_zero_excludes_trailing_line(self):
        module = _module()
        # Greeter class spanning source lines 5-7: end position is the start
        # of line 7 (zero-based), column 0, which must not count as line 8.
        start = {"line": 4, "column": 0}
        end = {"line": 7, "column": 0}

        self.assertEqual(module.exclusive_range_to_lines(start, end), (5, 7))

    def test_single_line_symbol(self):
        module = _module()
        start = {"line": 5, "column": 0}
        end = {"line": 5, "column": 20}

        self.assertEqual(module.exclusive_range_to_lines(start, end), (6, 6))


class LanguageDetectionTests(RavenTestCase):
    def test_detects_languages_for_shipped_stacks(self):
        module = _module()
        cases = {
            "a.py": "python",
            "a.ts": "typescript",
            "a.tsx": "tsx",
            "a.js": "javascript",
            "a.jsx": "javascript",
            "a.go": "go",
            "a.rs": "rust",
            "a.swift": "swift",
            "a.ex": "elixir",
            "a.exs": "elixir",
            "a.lua": "lua",
        }
        for filename, expected in cases.items():
            with self.subTest(filename=filename):
                self.assertEqual(module.detect_language(f"/repo/{filename}"), expected)

    def test_unsupported_extension_returns_none(self):
        module = _module()
        self.assertIsNone(module.detect_language("/repo/notes.md"))
        self.assertIsNone(module.detect_language("/repo/Makefile"))


class NodeKindTests(RavenTestCase):
    def test_python_kinds_include_functions_and_classes(self):
        module = _module()
        kinds = module.node_kinds("python")
        self.assertIn("function_definition", kinds)
        self.assertIn("class_definition", kinds)

    def test_typescript_kinds_include_declarations(self):
        module = _module()
        kinds = module.node_kinds("typescript")
        self.assertIn("function_declaration", kinds)
        self.assertIn("class_declaration", kinds)
        self.assertIn("interface_declaration", kinds)
        self.assertIn("method_definition", kinds)

    def test_node_kind_languages_are_a_subset_of_detectable_languages(self):
        module = _module()
        detectable = set(module.LANGUAGE_BY_EXTENSION.values())
        for language in module.NODE_KINDS:
            with self.subTest(language=language):
                self.assertIn(language, detectable)
                self.assertTrue(module.node_kinds(language))

    def test_elixir_uses_a_structural_rule_not_node_kinds(self):
        # Elixir def/defp/defmodule are `call` nodes that a plain --kind selector
        # cannot isolate, so they are handled by an ast-grep structural rule
        # instead of the node-kind table.
        module = _module()
        self.assertEqual(module.detect_language("/repo/a.ex"), "elixir")
        self.assertEqual(module.node_kinds("elixir"), [])
        self.assertIsNotNone(module.astgrep_rule("elixir"))
        self.assertTrue(module.astgrep_supports("elixir"))

    def test_kind_based_languages_have_no_structural_rule(self):
        module = _module()
        self.assertIsNone(module.astgrep_rule("python"))
        self.assertTrue(module.astgrep_supports("python"))

    def test_unknown_language_has_no_kinds(self):
        module = _module()
        self.assertEqual(module.node_kinds("cobol"), [])


# One ast-grep `--json=stream` match per line (JSON Lines), shaped like the real
# ast-grep 0.43.0 output: zero-based start, exclusive end, full matched text.
_ASTGREP_STREAM = (
    '{"text":"def top_function(x: int) -> int:\\n    return x + 1",'
    '"range":{"start":{"line":0,"column":0},"end":{"line":1,"column":16}},'
    '"file":"sample.py","language":"Python"}\n'
    '{"text":"class Greeter:\\n    def greet(self):\\n        return 1",'
    '"range":{"start":{"line":4,"column":0},"end":{"line":7,"column":0}},'
    '"file":"sample.py","language":"Python"}\n'
)


class ParseAstgrepStreamTests(RavenTestCase):
    def test_parses_rows_with_inclusive_lines_and_header(self):
        module = _module()
        rows = module.parse_astgrep_stream(_ASTGREP_STREAM)

        self.assertEqual(
            rows,
            [
                {"start_line": 1, "end_line": 2, "header": "def top_function(x: int) -> int:"},
                {"start_line": 5, "end_line": 7, "header": "class Greeter:"},
            ],
        )

    def test_tolerates_blank_lines_and_empty_input(self):
        module = _module()
        self.assertEqual(module.parse_astgrep_stream(""), [])
        self.assertEqual(module.parse_astgrep_stream("\n\n"), [])


class SortRowsTests(RavenTestCase):
    def test_sorts_by_start_then_container_before_members_and_dedupes(self):
        module = _module()
        rows = [
            {"start_line": 6, "end_line": 7, "header": "def greet(self):"},
            {"start_line": 5, "end_line": 7, "header": "class Greeter:"},
            {"start_line": 1, "end_line": 3, "header": "def top_function():"},
            {"start_line": 5, "end_line": 7, "header": "class Greeter:"},  # duplicate
        ]

        self.assertEqual(
            module.sort_rows(rows),
            [
                {"start_line": 1, "end_line": 3, "header": "def top_function():"},
                {"start_line": 5, "end_line": 7, "header": "class Greeter:"},
                {"start_line": 6, "end_line": 7, "header": "def greet(self):"},
            ],
        )


class FormatSkeletonTests(RavenTestCase):
    def test_formats_rows_as_range_and_header(self):
        module = _module()
        rows = [
            {"start_line": 1, "end_line": 2, "header": "def f():"},
            {"start_line": 5, "end_line": 7, "header": "class C:"},
        ]
        self.assertEqual(module.format_skeleton(rows), "1-2\tdef f():\n5-7\tclass C:")

    def test_caps_output_and_notes_truncation(self):
        module = _module()
        rows = [{"start_line": i, "end_line": i, "header": f"def f{i}():"} for i in range(1, 6)]
        out = module.format_skeleton(rows, max_symbols=3)
        lines = out.splitlines()
        self.assertEqual(len(lines), 4)  # 3 rows + 1 truncation note
        self.assertIn("2 more", lines[-1])


class AstgrepSkeletonTests(RavenTestCase):
    """End-to-end golden tests against the real ast-grep binary. Values were
    captured from ast-grep 0.43.0; a grammar/version change that shifts node
    kinds or ranges fails these loudly rather than silently emitting a bad
    skeleton."""

    def _write(self, name: str, body: str) -> Path:
        path = self.destination / name
        path.write_text(body, encoding="utf-8")
        return path

    def test_returns_none_for_unsupported_language_without_running_astgrep(self):
        module = _module()
        path = self._write("notes.md", "# hello\n")
        self.assertIsNone(module.astgrep_skeleton(str(path)))

    @unittest.skipUnless(HAVE_ASTGREP, "ast-grep not installed")
    def test_python_golden(self):
        module = _module()
        path = self._write(
            "golden.py",
            "def top_function(x):\n    return x + 1\n\n\n"
            'class Greeter:\n    def greet(self):\n        return "hi"\n',
        )

        self.assertEqual(
            module.astgrep_skeleton(str(path)),
            [
                {"start_line": 1, "end_line": 2, "header": "def top_function(x):"},
                {"start_line": 5, "end_line": 7, "header": "class Greeter:"},
                {"start_line": 6, "end_line": 7, "header": "def greet(self):"},
            ],
        )

    @unittest.skipUnless(HAVE_ASTGREP, "ast-grep not installed")
    def test_typescript_golden(self):
        module = _module()
        path = self._write(
            "golden.ts",
            "export function formatUser(u: User): string { return u.name }\n\n"
            "class UserService {\n  constructor() {}\n  load(): void {}\n}\n\n"
            "interface User { name: string }\n",
        )

        self.assertEqual(
            module.astgrep_skeleton(str(path)),
            [
                {
                    "start_line": 1,
                    "end_line": 1,
                    "header": "function formatUser(u: User): string { return u.name }",
                },
                {"start_line": 3, "end_line": 6, "header": "class UserService {"},
                {"start_line": 4, "end_line": 4, "header": "constructor() {}"},
                {"start_line": 5, "end_line": 5, "header": "load(): void {}"},
                {"start_line": 8, "end_line": 8, "header": "interface User { name: string }"},
            ],
        )

    @unittest.skipUnless(HAVE_ASTGREP, "ast-grep not installed")
    def test_elixir_golden_via_structural_rule(self):
        module = _module()
        path = self._write(
            "golden.ex",
            "defmodule M do\n  def alpha(x) do\n    x\n  end\n\n"
            "  defp beta do\n    1\n  end\nend\n",
        )

        self.assertEqual(
            module.astgrep_skeleton(str(path)),
            [
                {"start_line": 1, "end_line": 9, "header": "defmodule M do"},
                {"start_line": 2, "end_line": 4, "header": "def alpha(x) do"},
                {"start_line": 6, "end_line": 8, "header": "defp beta do"},
            ],
        )


class ParseCtagsJsonTests(RavenTestCase):
    """The Universal Ctags fallback is the *exact* tier: a tag counts only when
    it carries both ``line`` and ``end``. The header is read from the source so
    it matches the ast-grep tier's "first line of the declaration" convention."""

    SOURCE_LINES: ClassVar[list[str]] = [
        "def top_function(x):",  # 1
        "    y = 1",  # 2
        "    return y",  # 3
        "",  # 4
        "class Greeter:",  # 5
        "    def greet(self):",  # 6
        "        return 1",  # 7
        "",  # 8
        "def no_end():",  # 9
    ]

    def test_keeps_tags_with_end_and_discards_tags_without_end(self):
        module = _module()
        text = (
            '{"_type":"tag","name":"top_function","line":1,"kind":"function","end":3}\n'
            '{"_type":"tag","name":"Greeter","line":5,"kind":"class","end":7}\n'
            '{"_type":"tag","name":"greet","line":6,"kind":"method","scope":"Greeter","end":7}\n'
            '{"_type":"tag","name":"no_end","line":9,"kind":"function"}\n'
        )
        self.assertEqual(
            module.parse_ctags_json(text, self.SOURCE_LINES),
            [
                {"start_line": 1, "end_line": 3, "header": "def top_function(x):"},
                {"start_line": 5, "end_line": 7, "header": "class Greeter:"},
                {"start_line": 6, "end_line": 7, "header": "def greet(self):"},
            ],
        )

    def test_tolerates_blank_lines_and_non_tag_json(self):
        module = _module()
        text = '\n{"_type":"ptag","name":"!_TAG_PROGRAM"}\n'
        self.assertEqual(module.parse_ctags_json(text, self.SOURCE_LINES), [])


class RgDeclarationPatternTests(RavenTestCase):
    def test_has_pattern_for_shipped_languages(self):
        module = _module()
        for language in ["python", "typescript", "javascript", "go", "rust", "swift", "lua"]:
            with self.subTest(language=language):
                self.assertTrue(module.rg_declaration_pattern(language))

    def test_none_for_unknown_language(self):
        module = _module()
        self.assertIsNone(module.rg_declaration_pattern("cobol"))


class ParseRgMatchesTests(RavenTestCase):
    """The rg tier is start-only: it locates declaration starts and infers each
    end as the line before the next declaration (EOF for the last). Ranges are
    approximate by construction."""

    def test_infers_ranges_from_declaration_starts(self):
        module = _module()
        # rg --line-number --no-heading emits "<lineno>:<text>" for a single file.
        text = "1:def alpha():\n5:class Beta:\n"
        self.assertEqual(
            module.parse_rg_matches(text, total_lines=8),
            [
                {"start_line": 1, "end_line": 4, "header": "def alpha():"},
                {"start_line": 5, "end_line": 8, "header": "class Beta:"},
            ],
        )

    def test_tolerates_blank_and_malformed_lines(self):
        module = _module()
        self.assertEqual(module.parse_rg_matches("", total_lines=3), [])
        self.assertEqual(module.parse_rg_matches("not-a-match\n", total_lines=3), [])


class GenerateSkeletonLadderTests(RavenTestCase):
    """The ladder is ast-grep -> ctags -> rg. The runtime sanity check treats an
    empty result (a backend that ran but found nothing) the same as an
    unavailable backend, so a bad/empty skeleton degrades to the next tier
    instead of being emitted."""

    def _patched(self, *, astgrep, ctags, rg):
        module = _module()
        module.astgrep_skeleton = lambda *_a, **_k: astgrep
        module.ctags_skeleton = lambda *_a, **_k: ctags
        module.rg_skeleton = lambda *_a, **_k: rg
        return module

    def test_prefers_astgrep_when_it_returns_rows(self):
        rows = [{"start_line": 1, "end_line": 2, "header": "def f():"}]
        module = self._patched(astgrep=rows, ctags=None, rg=None)
        result = module.generate_skeleton("/repo/a.py")
        self.assertEqual(result.rows, rows)
        self.assertEqual(result.backend, "ast-grep")
        self.assertFalse(result.approximate)

    def test_empty_astgrep_degrades_to_ctags(self):
        rows = [{"start_line": 1, "end_line": 2, "header": "def f():"}]
        module = self._patched(astgrep=[], ctags=rows, rg=None)
        result = module.generate_skeleton("/repo/a.py")
        self.assertEqual(result.backend, "ctags")
        self.assertFalse(result.approximate)

    def test_degrades_to_rg_and_marks_approximate(self):
        rows = [{"start_line": 1, "end_line": 3, "header": "def f():"}]
        module = self._patched(astgrep=None, ctags=[], rg=rows)
        result = module.generate_skeleton("/repo/a.py")
        self.assertEqual(result.backend, "rg")
        self.assertTrue(result.approximate)

    def test_returns_none_when_every_backend_is_empty(self):
        module = self._patched(astgrep=[], ctags=None, rg=[])
        self.assertIsNone(module.generate_skeleton("/repo/a.py"))

    def test_returns_none_for_unsupported_language_without_calling_backends(self):
        module = _module()

        def _boom(path, language=None):
            raise AssertionError("backend should not run for an unsupported language")

        module.astgrep_skeleton = _boom
        module.ctags_skeleton = _boom
        module.rg_skeleton = _boom
        self.assertIsNone(module.generate_skeleton("/repo/notes.md"))


@unittest.skipUnless(HAVE_RG, "rg not installed")
class RgSkeletonEndToEndTests(RavenTestCase):
    def test_python_declaration_starts(self):
        module = _module()
        path = self.destination / "deg.py"
        path.write_text("def alpha():\n    return 1\n\n\nclass Beta:\n    pass\n", encoding="utf-8")
        self.assertEqual(
            module.rg_skeleton(str(path)),
            [
                {"start_line": 1, "end_line": 4, "header": "def alpha():"},
                {"start_line": 5, "end_line": 6, "header": "class Beta:"},
            ],
        )


@unittest.skipUnless(HAVE_UNIVERSAL_CTAGS, "Universal Ctags not installed")
class CtagsSkeletonEndToEndTests(RavenTestCase):
    def test_python_exact_ranges(self):
        module = _module()
        path = self.destination / "ct.py"
        path.write_text(
            "def alpha(x):\n    return x\n\n\nclass Beta:\n    def m(self):\n        return 1\n",
            encoding="utf-8",
        )
        rows = module.ctags_skeleton(str(path))
        self.assertIsNotNone(rows)
        headers = {r["header"] for r in rows}
        self.assertIn("def alpha(x):", headers)
        self.assertIn("class Beta:", headers)


class CliTests(RavenTestCase):
    def _run(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(SKELETON_SCRIPT), *args],
            capture_output=True,
            text=True,
            check=False,
        )

    def test_missing_file_exits_nonzero(self):
        result = self._run(str(self.destination / "does-not-exist.py"))
        self.assertNotEqual(result.returncode, 0)

    def test_unsupported_file_reports_no_skeleton_and_exits_zero(self):
        path = self.destination / "notes.md"
        path.write_text("# hi\n", encoding="utf-8")
        result = self._run(str(path))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("no skeleton", (result.stdout + result.stderr).lower())

    @unittest.skipUnless(HAVE_ASTGREP, "ast-grep not installed")
    def test_python_file_prints_skeleton(self):
        path = self.destination / "m.py"
        path.write_text("def alpha():\n    return 1\n\n\nclass Beta:\n    pass\n", encoding="utf-8")
        result = self._run(str(path))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("1-2\tdef alpha():", result.stdout)
        self.assertIn("class Beta:", result.stdout)


if __name__ == "__main__":
    unittest.main()
