# Test Rules

- Run the narrowest relevant test first.
- Use RTK for noisy test output when available.
- Inspect only failing output before broadening investigation.
- Add tests near existing coverage and follow local naming and fixture patterns.
- Avoid brittle sleeps, timing assumptions, and oversized snapshots unless the codebase already relies on them.
