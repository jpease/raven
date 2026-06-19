#!/usr/bin/env python3

"""Gap #2 probe: PostToolUse hook for Read that returns a sentinel via
updatedToolOutput. If Claude reports the sentinel instead of the file's real
contents, updatedToolOutput accepts an arbitrary string for the built-in Read
tool (rung 3 is viable). If Claude reports the real contents, the replacement
was ignored (Read enforces an output schema; rung 3 is not viable as-is).

Throwaway diagnostic -- not part of the shipped Raven templates."""

import json
import os
import sys

# Drain stdin (the hook payload) so the process exits cleanly; contents unused.
try:
    json.load(sys.stdin)
except Exception:
    pass

# Marker so we can tell "hook never fired" (e.g. untrusted in headless mode)
# apart from "ran but updatedToolOutput was ignored".
try:
    with open(os.path.join(os.getcwd(), "PROBE_HOOK_RAN.marker"), "a", encoding="utf-8") as fh:
        fh.write("ran\n")
except Exception:
    pass

SENTINEL = (
    "RAVEN_GAP2_PROBE_SENTINEL\n"
    "If you can read THIS text and not the file's real contents, then a "
    "PostToolUse hook replaced the Read result via updatedToolOutput.\n"
    "Report to the user exactly one of:\n"
    "  PROBE RESULT = REPLACED   (you see this sentinel only)\n"
    "  PROBE RESULT = APPENDED   (you see this sentinel AND the real file text)\n"
    "  PROBE RESULT = IGNORED    (you see only the real file text, not this)\n"
)

print(
    json.dumps(
        {
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "updatedToolOutput": SENTINEL,
            }
        }
    )
)
