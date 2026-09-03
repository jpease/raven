# Python Rules

## Applicability

Use these rules for Python applications, services, libraries, CLIs, scripts, and data pipelines.

Project-specific `AGENTS.md`, nested `AGENTS.md`, local docs, and existing task-runner commands override this file when they are more specific.

Use `.claude/docs/raven-python-quality.md` for detailed Python quality guidance when the task touches public APIs, error design, architecture, async behavior, testing strategy, security, dependency policy, or performance.

## Setup And Commands

- Prefer the repository's task runner such as `just`, `make`, `invoke`, `tox`, or `nox` before inventing raw command sequences.
- Do not assume every project uses the same toolchain; the session roster and the task runner say what this one uses.

## Additional Pause And Ask Triggers

In addition to the guardrails in AGENTS.md, ask before changing:

- Configuration schemas, environment variable contracts, or deployment behavior.
- CI/CD workflows or release automation.

## Python Safety

- Use type hints consistently with surrounding code. Do not introduce untyped signatures into typed codebases.
- Do not weaken mypy or pyright configuration to satisfy a type error. Fix the code instead. `raven assess` reports a `typecheck` gate whose config sits below the template's floor — `typeCheckingMode` at `basic` or `off`, or mypy's `ignore_errors` turned on.
- Avoid `Any` in typed codebases. Use `object` or a narrower type; parse/validate before narrowing.
- Prefer `T | None` over `Optional[T]` in codebases already using modern syntax.
- Use `TypedDict`, `dataclass`, or `pydantic`-style models for structured data rather than raw `dict[str, Any]`.
- Do not use mutable default arguments (`def f(x=[]):`).

## Error Handling

- Catch specific exception types. Avoid bare `except:` or overly broad `except Exception`.
- Do not silently swallow exceptions. Log or re-raise at minimum.
- Use context managers for cleanup; do not rely on `finally` blocks where `with` is cleaner.
- Preserve exception context when re-raising: use `raise NewError(...) from original_error`.

## Architecture

- Preserve existing module and package boundaries unless the task is explicitly architectural.
- Keep pure business logic separate from I/O, network calls, time, randomness, and framework integration.
- Prefer dependency injection over importing singletons or globals directly in business logic.
- Do not import from sibling packages in ways that create circular dependencies.

## Async And Concurrency

- Do not block an async event loop with synchronous filesystem, network, subprocess, or CPU-heavy work.
- Do not mix `asyncio` and `threading` without understanding the safety implications.

## Testing

- Inspect nearby tests and fixtures before adding new patterns.
- Use `pytest` fixtures and parametrize rather than duplicating setup across tests.
- Write behavior-focused tests; avoid over-mocking internals.
- Add regression tests for bug fixes when the failure can be reproduced deterministically.
- Do not delete or weaken tests to make a change pass unless explicitly requested. The observable form is a diff that ends with fewer test functions in a file than it started with, or an unconditional skip added to one; name the replacement, or say the coverage is gone.
- Avoid brittle sleeps, timing assumptions, and oversized snapshots unless the codebase already relies on them.

## Dependencies

- Prefer the standard library and existing dependencies before adding new packages.
- Do not add packages that create version incompatibilities without a documented resolution.

## Performance And Benchmarks

- Profile before optimizing; do not make performance claims from a single local run.
- CPU-bound threads do not parallelize due to the GIL; reach for `multiprocessing` or a C extension when needed.

## Quality Gates

- The pre-commit and pre-push hooks Raven installs run the formatter, linter, type check, and test suite. Do not run them by hand before committing; run the narrowest test for the change and let the hooks own the rest.
- Fix a gate failure the hook reports in touched code rather than suppressing it.
- Do not add broad `# noqa` or `# type: ignore` comments. Prefer fixing the code or using the narrowest scoped suppression with a reason comment. A suppression naming no rule code is blocked at commit time by `.raven/git-hooks/lib/check-gate-relaxation.py`; a rule code with no reason still commits, and only review catches it. `.claude/scripts/raven-capability-roster.py` shows the shape that passes — one code, then why.

