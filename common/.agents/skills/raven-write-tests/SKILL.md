---
name: raven-write-tests
description: Use when adding, fixing, or reviewing tests.
---

# Write Tests

## Skip When

- The task does not add or change behavior and no test gap is being addressed.
- The user explicitly asks not to touch tests.

## Required Constraints

- Inspect nearby tests before adding a new pattern.
- Keep tests behavior-focused: tests should protect observable contracts so refactors can change internals without needless rewrites.
- Run only the new or changed tests first.
- Broaden test scope only after narrow tests pass.
- Do not delete, weaken, or over-mock tests just to make a change pass.

## Process

1. Use `rg` for similar test names and fixtures.
2. Use Semble if the relevant behavior is conceptually described but not obvious.
3. Add focused coverage for the behavior or regression.
4. Use RTK for noisy test output when exact raw output is not required.

## Avoid

- Do not snapshot large irrelevant output.
- Do not add brittle timing or sleep-based tests unless unavoidable.
