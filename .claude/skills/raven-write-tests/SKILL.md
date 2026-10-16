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
- Keep tests behavior-focused: protect observable contracts so refactors can change internals without needless rewrites.
- Test names should describe the scenario and expected outcome, not the implementation.
- Tests should fail when observable behavior breaks; do not couple them to safe-refactor internals.
- Mock only true external boundaries: time, randomness, network, filesystem, process state, expensive services, unavailable platform APIs, or hard-to-trigger failure modes. Do not use mocks that merely restate implementation.
- Separate behavior changes from refactors: existing tests must be green before starting a refactor; add or update tests for behavior changes before changing the implementation.
- Run the new or changed test before the implementation lands and confirm it fails for the behavior it asserts — not from a compile, import, collection, or fixture error. A test never run red may have passed anyway.
- When a change adds or changes a required member on a shared interface, protocol, or abstract base, search the repo for all implementers. The break can surface outside your test target — as a compile error, an import-time failure, or another package's suite.
- If a shared test double's fidelity gap blocks an assertion, prefer asserting on the observable call sequence over widening the double, which changes behavior for every test that uses it.
- A test that stands up a fixture must assert the fixture held. A spawned server, thread, or process that dies mid-test makes the assertion blame the code under test. Record what the fixture did and assert that premise before the conclusion.
- Run only the new or changed tests first.
- Broaden test scope only after narrow tests pass.
- Do not delete, weaken, or over-mock tests just to make a change pass. Deletion and weakening each have an observable form: a diff ending with fewer test functions in a file than it started with, and an unconditional skip (`@pytest.mark.skip`, `@unittest.skip`, `self.skipTest`). A conditional `skipif`/`skipUnless` is different in kind — it states the environment in which the test does not apply.

## Rationalization Check

| Thought | Reality |
|---|---|
| "This is a small change, existing tests are enough" | `Skip When` already covers no-behavior-change cases. A real change needs new or updated coverage. |
| "It obviously fails without the implementation, no need to run it" | Obvious is not observed. An unrun test can pass already, or fail from a typo'd fixture that would mask a bogus assertion once the code lands. |
| "The test broke, I'll update it to match" | Classify the failure first. Updating a stale assertion without classifying it can mask a regression. |
| "Coverage looks thin but the main path works" | Missing edge cases and regressions are the gap this skill exists to close. |
| "This guard has been green for months, it must work" | Green-forever is exactly the invisible failure mode. Write the negative control before trusting it. |

## When Existing Tests Fail

Classify the failure before acting:

- **Regression** — the change broke real behavior; fix the code.
- **Stale assertion** — the test was tied to a contract that was intentionally changed; update the test.
- **Test bug** — the test was wrong before the change; fix the test and document why.
- **Environment issue** — flaky, timing-dependent, or platform-specific; fix or isolate the condition.
- **Pre-existing failure** — was already failing before the change; note it separately, do not fix as part of this change.

## Guards

A guard — a check script, lint rule, CI gate, schema validator, or invariant assertion — needs a different check from a test. A test is written alongside the behavior it protects, so red-first applies naturally. A guard usually predates the change it should catch and passes on every commit, so its failure is invisible: it keeps passing on input it should reject, and nothing runs it against such input.

- Write a negative control: temporarily construct the condition the guard exists to catch, confirm the guard fails, then restore. A guard never observed failing is unverified, however long it has been green.
- Also run it against a real past failure, such as a checkout from before the bug was fixed. Synthetic fixtures contain only the condition you thought of; real input carries the confounds that hide a gap.
- Assert that the discovered set is non-empty. A guard looping over a glob or parametrized case list passes every per-file assertion when the walk returns nothing. Assert the count against the floor you expect: `len(justfiles) >= 8` catches a walk that found one of eight, where `> 0` waves it through.
- Diff the guard's stated scope against its implementation. If a comment or name names a bounded set ("the legacy fixtures"), enumerate that set rather than glob an unbounded one; the first new item that legitimately matches the glob will be rejected.
- Assert on effect. Grepping a script for `unset FOO` proves the line was written, not that the tool reads the environment rather than a config file. Assert against the rendered output or observable behavior instead of the command string.
- When the guard proves something is absent — a secret scrubbed from an error report — assert over the whole serialized object; a field-by-field check misses the password riding in a nested `extra` dict. In the same test, assert a harmless value of the same shape still appears, or a scrubber that redacts everything passes.
- When a reader substitutes a default for a missing field, test the mapping end to end through the real reader, and assert that a populated field arrives populated. A unit test that constructs the domain object directly skips the mapping layer where the wiring gap lives.
- For a permission/authorization boundary, run the negative control under the SAME credential level production traffic uses, never a privileged one kept for test convenience. A row-level-security policy, capability check, or tenant-scoping middleware run through a superuser/admin/service credential never evaluates the policy: the suite is green and the boundary is inert. Also watch the positive assertion (access denied / row excluded) fail once under an elevated credential, to prove the boundary is reachable through this test setup.

## Process

1. Use `rg` for similar test names and fixtures.
2. Use a configured code-intelligence index, if any, if the relevant behavior is conceptually described but not obvious.
3. Add focused coverage for the behavior or regression.
4. Use RTK for noisy test output when exact raw output is not required.

## Avoid

- Do not chase line coverage; prefer meaningful scenarios, edge cases, regressions, and integration boundaries.
- Do not snapshot large irrelevant output.
- Do not add brittle timing or sleep-based tests unless unavoidable.
