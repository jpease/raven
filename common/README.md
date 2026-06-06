# Common Raven Template

This directory contains shared configuration for token-efficient agentic coding.

`AGENTS.md` is authoritative. Agent-specific files should be thin pointers or symlinks to `AGENTS.md`.
`.agents/skills/` is the canonical skill location. Claude and Codex files are compatibility adapters.

The template favors:

- short always-loaded instructions
- task-specific skills
- subagents for broad or noisy investigations
- deterministic hooks for safety checks
- structured tool use through MCP
- compressed output for noisy shell commands
- local user memory for verified tool availability and reminder preferences

Language templates should link to these files and add only language-specific rules.

See `.claude/docs/raven-tool-assessment.md` for platform notes and recommended tool roles.
See `.claude/docs/raven-authority-map.md` for canonical versus non-canonical context rules.
See `.claude/docs/raven-guardrails.md` for guardrail levels and verification expectations.
See `.claude/docs/raven-coding-principles.md` for shared coding-quality principles.
See `.claude/docs/raven-namespace.md` for Raven-owned paths.

## Tool Bootstrap

To check recommended tools and record availability outside the repository:

```sh
python .claude/scripts/raven-tool-check.py --write
```

To suppress future reminders about missing recommended tools:

```sh
python .claude/scripts/raven-tool-check.py --no-reminder
```

If `python` is not the correct launcher for the machine, use the repository's configured Python command, such as `python3`, `py -3`, or the active virtual environment.
