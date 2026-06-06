---
name: raven-debug-failure
description: Use when tests, builds, runtime commands, or user-reported behavior fail.
---

# Debug Failure

## Skip When

- There is no failing command, error, broken behavior, or repro target.
- The task is a planned feature or refactor rather than a failure investigation.

## Required Constraints

- Capture the exact failing command or reported behavior before changing code.
- Do not propose a fix before stating the suspected root cause.
- Verify the fix with the narrowest command that previously failed.
- Do not claim the broader system is fixed unless a broader relevant check was run.
- If the narrow test still fails, inspect only the new failing signal before broadening.

## Process

1. Reproduce using the narrowest command.
2. Run build and test commands through RTK where possible.
3. Extract the failing test or command, exact error, relevant stack frame, and likely owning file or symbol.
4. Use `rg` for exact error strings.
5. Use LSP diagnostics for target files.
6. Use Semble only if ownership is unclear.
7. Patch minimally.
8. Re-run the narrowest failing test.
9. Only then run broader tests.

## Output

Summarize root cause, changed files, verification command, and remaining risk.
