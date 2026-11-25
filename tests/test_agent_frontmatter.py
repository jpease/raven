import re
import unittest

from helpers import REPO_ROOT

FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)

# The full read-only guarantee: every write/rename-capable operation an
# agent could otherwise reach, including the LSP/GitNexus MCP write paths.
REQUIRED_DISALLOWED_TOOLS = {
    "Write",
    "Edit",
    "NotebookEdit",
    "mcp__lsp__edit_file",
    "mcp__lsp__rename_symbol",
    "mcp__gitnexus__rename",
}

READ_ONLY_AGENTS = ("raven-code-reviewer", "raven-codebase-cartographer", "raven-refactor-reviewer")

GEMINI_AGENTS_DIR = REPO_ROOT / "common" / ".gemini" / "agents"

GEMINI_READ_TOOLS = ("read_file", "list_directory", "glob", "grep_search", "run_shell_command")
GEMINI_MCP_READ_TOOLS = (
    "mcp_lsp_definition",
    "mcp_lsp_references",
    "mcp_lsp_hover",
    "mcp_lsp_diagnostics",
    "mcp_gitnexus_list_repos",
    "mcp_gitnexus_query",
    "mcp_gitnexus_context",
    "mcp_gitnexus_impact",
    "mcp_gitnexus_trace",
    "mcp_gitnexus_detect_changes",
    "mcp_codegraph_codegraph_explore",
    "mcp_semgrep_*",
)
_GEMINI_REVIEW_TOOLS = (
    *GEMINI_READ_TOOLS,
    "activate_skill",
    *GEMINI_MCP_READ_TOOLS[:10],
    "mcp_codegraph_codegraph_explore",
    "mcp_semgrep_*",
    "list_mcp_resources",
    "read_mcp_resource",
)
EXPECTED_GEMINI_TOOLS = {
    "raven-prose-reviewer": ("read_file",),
    "raven-security-reviewer": GEMINI_READ_TOOLS,
    "raven-test-debugger": GEMINI_READ_TOOLS,
    "raven-code-reviewer": _GEMINI_REVIEW_TOOLS,
    "raven-codebase-cartographer": _GEMINI_REVIEW_TOOLS,
    "raven-refactor-reviewer": _GEMINI_REVIEW_TOOLS,
}
FORBIDDEN_GEMINI_TOOLS = {
    "*",
    "mcp_*",
    "write_file",
    "replace",
    "mcp_lsp_*",
    "mcp_lsp_edit_file",
    "mcp_lsp_rename_symbol",
    "mcp_gitnexus_*",
    "mcp_gitnexus_rename",
    "mcp_gitnexus_group_sync",
    "mcp_gitnexus_refresh_index",
}


def frontmatter_fields(path):
    """Return the agent frontmatter as a dict, parsed without a YAML dependency.

    Values are read as raw comma-separated strings where relevant (``tools``,
    ``disallowedTools``) rather than through a full YAML parser, since agent
    frontmatter is a flat key: value block.
    """
    text = path.read_text(encoding="utf-8")
    match = FRONTMATTER_RE.match(text)
    assert match, f"expected {path} to start with a --- frontmatter block"
    fields = {}
    for line in match.group(1).splitlines():
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip()
    return fields


class ReadOnlyAgentDisallowedToolsTests(unittest.TestCase):
    """raven-code-reviewer, raven-codebase-cartographer, and raven-refactor-reviewer
    must use a disallowedTools denylist, not a tools: allowlist. These agent prompts
    instruct the agent to use LSP and GitNexus; a tools: allowlist
    silently drops whichever of those the list omits, so the agent is told
    to call tools it cannot reach with no error surfaced (#143).
    """

    def _fields(self, agent_name):
        return frontmatter_fields(REPO_ROOT / "common" / ".claude" / "agents" / f"{agent_name}.md")

    def test_no_tools_allowlist(self):
        for agent_name in READ_ONLY_AGENTS:
            with self.subTest(agent=agent_name):
                self.assertNotIn(
                    "tools",
                    self._fields(agent_name),
                    f"{agent_name} must not carry a tools: allowlist -- it would drop "
                    "MCP servers (LSP, GitNexus) the agent prompt depends on",
                )

    def test_disallowed_tools_covers_every_write_and_rename_operation(self):
        for agent_name in READ_ONLY_AGENTS:
            with self.subTest(agent=agent_name):
                fields = self._fields(agent_name)
                self.assertIn("disallowedTools", fields)
                disallowed = {tool.strip() for tool in fields["disallowedTools"].split(",")}
                missing = REQUIRED_DISALLOWED_TOOLS - disallowed
                self.assertFalse(
                    missing,
                    f"{agent_name} disallowedTools is missing {sorted(missing)!r} -- "
                    "the read-only guarantee is incomplete",
                )


if __name__ == "__main__":
    unittest.main()


def gemini_tools(path):
    raw = frontmatter_fields(path)["tools"]
    match = re.fullmatch(r"\[(.*)\]", raw)
    assert match, f"expected a flow-style tools list in {path}, got {raw!r}"
    return [entry.strip() for entry in match.group(1).split(",")]


class GeminiAgentToolAllowlistTests(unittest.TestCase):
    """Gemini CLI gives an agent with no `tools:` list every parent tool and has
    no denylist field, so each agent pins a read-only allowlist.
    """

    def _paths(self):
        return sorted(GEMINI_AGENTS_DIR.glob("raven-*.md"))

    def test_every_gemini_agent_is_pinned(self):
        stems = {path.stem for path in self._paths()}
        self.assertEqual(stems, set(EXPECTED_GEMINI_TOOLS))

    def test_tools_match_expected_allowlist(self):
        for path in self._paths():
            with self.subTest(agent=path.stem):
                tools = gemini_tools(path)
                self.assertEqual(tools, list(EXPECTED_GEMINI_TOOLS[path.stem]))
                self.assertEqual(len(tools), len(set(tools)))

    def test_no_write_rename_or_wildcard_tool(self):
        for path in self._paths():
            with self.subTest(agent=path.stem):
                self.assertFalse(set(gemini_tools(path)) & FORBIDDEN_GEMINI_TOOLS)

    def test_mcp_agents_keep_lsp_and_code_index_reads(self):
        for agent_name in READ_ONLY_AGENTS:
            with self.subTest(agent=agent_name):
                tools = gemini_tools(GEMINI_AGENTS_DIR / f"{agent_name}.md")
                self.assertLessEqual(set(GEMINI_MCP_READ_TOOLS), set(tools))
