---
name: raven-write-tests
description: Use when adding, fixing, or reviewing tests.
---

# Write Tests

## Skip When

- The task does not add or change behavior and no test gap is being addressed — run existing tests as an oracle instead.
- The user explicitly asks not to touch tests.

## Required Constraints

- Inspect nearby tests before adding a new pattern.
- Keep tests behavior-focused: tests should protect observable contracts so refactors can change internals without needless rewrites.
- Test names should describe the scenario and expected outcome, not the implementation.
- Tests should fail when observable behavior breaks; do not couple them to safe-refactor internals.
- Mock only true external boundaries: time, randomness, network, filesystem, process state, expensive services, unavailable platform APIs, or hard-to-trigger failure modes. Do not use mocks that merely restate implementation.
- Separate behavior changes from refactors: existing tests must be green before starting a refactor; add or update tests for behavior changes before changing the implementation.
- Run the new or changed test before the implementation lands and confirm it fails for the behavior it asserts — not from a compile, import, collection, or fixture error. A test written first but never run red can be one that would have passed anyway.
- When a change adds or changes a required member on a shared interface, protocol, or abstract base, search for all implementers across the repo before treating the change as scoped to the file you're editing. The break can surface outside your test target entirely — as a compile error, an import-time failure, or a different package's test suite — not as a failing test where you made the change.
- If a shared test double's fidelity gap blocks an assertion, prefer asserting on the observable call sequence over widening the double. Widening changes behavior for every other test that depends on it; a narrow assertion doesn't.
- Run only the new or changed tests first.
- Broaden test scope only after narrow tests pass.
- Do not delete, weaken, or over-mock tests just to make a change pass. Deletion and weakening each have an observable form: a diff ending with fewer test functions in a file than it started with, and an unconditional skip (`@pytest.mark.skip`, `@unittest.skip`, `self.skipTest`). A conditional `skipif`/`skipUnless` is different in kind — it states the environment in which the test does not apply.

## Rationalization Check

| Thought | Reality |
|---|---|
| "This is a small change, existing tests are enough" | `Skip When` already covers no-behavior-change cases. A real change needs new or updated coverage. |
| "I'll mock this to make the test simpler" | Mock only true external boundaries. Mocking internals just restates the implementation. |
| "It obviously fails without the implementation, no need to run it" | Obvious is not observed. An unrun test can pass already, or fail from a typo'd fixture that would mask a bogus assertion once the code lands. |
| "The test broke, I'll update it to match" | Classify the failure first. Updating a stale assertion without classifying it can mask a regression. |
| "Coverage looks thin but the main path works" | Missing edge cases and regressions are the gap this skill exists to close, not something to wave off. |
| "This failure is in a different file, that's unrelated" | A required-member change on a shared interface breaks every implementer at once. Sweep repo-wide before deciding it's unrelated. |
| "This guard has been green for months, it must work" | Green-forever is exactly the invisible failure mode. Write the negative control before trusting it. |
| "The loop covers every file it finds, so new files are covered automatically" | And zero files, silently. A discovery-driven guard needs an assertion on the count before its per-file assertions mean anything. |

## When Existing Tests Fail

Classify the failure before acting:

- **Regression** — the change broke real behavior; fix the code.
- **Stale assertion** — the test was tied to a contract that was intentionally changed; update the test.
- **Test bug** — the test was wrong before the change; fix the test and document why.
- **Environment issue** — flaky, timing-dependent, or platform-specific; fix or isolate the condition.
- **Pre-existing failure** — was already failing before the change; note it separately, do not fix as part of this change.

## Guards

A guard — a check script, lint rule, CI gate, schema validator, or invariant assertion — is not a test and needs a different check. A test is written alongside the behavior it protects, so red-first applies naturally. A guard usually predates the change it's meant to catch and is expected to pass on every commit, so its failure mode is invisible: it keeps passing on input it should reject, and nothing ever runs it against such input.

- Write a negative control: temporarily construct the condition the guard exists to catch and confirm the guard fails on it, then restore. A guard that has never been observed failing is unverified, no matter how long it's been green.
- Assert that the discovered set is non-empty. A guard that loops over what it finds — a glob or a parametrized case list — passes every per-file assertion when the walk returns nothing, so a moved directory or a renamed extension turns it into a green no-op. Assert the count against the floor you expect: `len(justfiles) >= 8` catches a walk that found one of eight, where `> 0` waves it through.
- Diff the guard's stated scope against its implementation. If a comment or name names a bounded set ("the legacy fixtures", "the deprecated endpoints"), the code should enumerate that set rather than glob an unbounded one and rely on the two coinciding by coincidence — the first new item that legitimately matches the glob will be rejected as a violation of the very state it was built to produce.
- Assert on effect, not intent. A guard that greps for `unset FOO` in a script proves the line was written, not that the tool being invoked actually reads the environment rather than a config file. Assert against the rendered output or observable behavior the guard is meant to guarantee, not the command string that was supposed to produce it.
- When the guard proves something is absent — a secret scrubbed from an error report, a customer identifier stripped from a log line — assert over the whole serialized object rather than field by field. A field-by-field check passes while the same password rides along in a breadcrumb or a nested `extra` dict. Assert the surviving direction in the same test: a harmless value of the same shape must still appear, or a scrubber that redacts everything passes and leaves the report useless.
- When a reader tolerates a missing field by substituting a default, test the mapping end to end over a fixture that goes through the real reader, and assert that a populated field arrives populated — not only that an absent one degrades cleanly. A unit test that constructs the domain object directly skips the mapping layer where the wiring gap actually lives.
- For a permission/authorization boundary specifically, run the negative control under the SAME credential level production traffic uses, not a privileged one kept around for test convenience. A row-level-security policy, capability check, or tenant-scoping middleware exercised through a superuser/admin/service credential that legitimately bypasses the boundary never evaluates the policy at all — every assertion is a real assertion on real results, the suite is green, and the boundary is completely inert in production. Also observe the positive assertion (access denied / row excluded / capability refused) fail once, deliberately, under an elevated credential — that verifies the boundary is even reachable through this test setup, rather than assumed.

## Process

1. Use `rg` for similar test names and fixtures.
2. Use `mcp__gitnexus__query` if the relevant behavior is conceptually described but not obvious.
3. Add focused coverage for the behavior or regression.
4. Use RTK for noisy test output when exact raw output is not required.

## Avoid

- Do not chase line coverage; prefer meaningful scenarios, edge cases, regressions, and integration boundaries.
- Do not snapshot large irrelevant output.
- Do not add brittle timing or sleep-based tests unless unavoidable.
