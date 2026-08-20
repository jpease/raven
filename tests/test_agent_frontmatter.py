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

READ_ONLY_AGENTS = ("raven-codebase-cartographer", "raven-refactor-reviewer")


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
    """raven-codebase-cartographer and raven-refactor-reviewer must use a
    disallowedTools denylist, not a tools: allowlist. Both agent prompts
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
