---
name: raven-tool-bootstrap
description: Use when the Raven tool check reports missing tools, or when the user asks to check, install, remember, or stop reminding about recommended tools.
---

# Tool Bootstrap

Goal: respond to Raven tool availability checks without repeated tool discovery.

## Skip When

- No tool check was requested or reported.
- The task can proceed using installed baseline tools.

## Required Constraints

- Do not install tools silently.
- Do not suppress future reminders without explicit user approval.
- Treat `.mcp.json` tools as optional local capabilities until verified.
- If the SessionStart hook reports missing tools, ask whether the user wants installation, instructions, a later reminder, or no future reminders.

## Commands

After tools are installed or verified, update Raven's local tool-check cache so SessionStart does not repeat the same prompt:

```sh
python .claude/scripts/raven-tool-check.py --write
```

If the user chooses not to be reminded:

```sh
python .claude/scripts/raven-tool-check.py --no-reminder
```

Use `python3`, `py -3`, or the active virtual environment if `python` is not the correct launcher.
