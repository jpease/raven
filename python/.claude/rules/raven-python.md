# Python Rules

## Applicability

Use these rules for Python applications, services, libraries, CLIs, scripts, and data pipelines.

Project-specific `AGENTS.md`, nested `AGENTS.md`, local docs, and existing task-runner commands override this file when they are more specific.

Use `.claude/docs/raven-python-quality.md` for detailed Python quality guidance when the task touches public APIs, error design, architecture, async behavior, testing strategy, security, dependency policy, or performance.

## Setup And Commands

- Prefer the repository's task runner such as `just`, `make`, `invoke`, `tox`, or `nox` before inventing raw command sequences.
- Discover available commands before guessing when the repo documents them.
- Use the narrowest relevant command first, then broaden after it passes.
- Common fallback commands:
  - `python -m pytest` or `pytest` for tests
  - `ruff check .` or `flake8` for lint
  - `ruff format --check .` or `black --check .` for formatting
  - `mypy .` or `pyright` for type checking
- Do not assume every project uses the same toolchain. Confirm before using.

## Pause And Ask

In addition to the guardrails in AGENTS.md, ask before changing:

- CI/CD workflows or release automation.

## Python Safety

- Use type hints consistently with surrounding code. Do not introduce untyped signatures into typed codebases.
- Do not weaken mypy or pyright configuration to satisfy a type error. Fix the code instead.
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
- Prefer the narrowest useful test command first, such as one test file or one test case.
- Use `pytest` fixtures and parametrize rather than duplicating setup across tests.
- Write behavior-focused tests; avoid over-mocking internals.
- Add regression tests for bug fixes when the failure can be reproduced deterministically.
- Do not delete or weaken tests to make a change pass unless explicitly requested.
- Broaden to the repository's standard test or quality command only after targeted tests pass.

## Dependencies

- Do not add packages that create version incompatibilities without a documented resolution.

## Performance And Benchmarks

- Profile before optimizing; do not make performance claims from a single local run.
- CPU-bound threads do not parallelize due to the GIL; reach for `multiprocessing` or a C extension when needed.

## Quality Gates

- Run the repository's documented final quality gate before handoff when code changed.
- If no final gate exists, run formatter check, lint, type check, and tests at minimum.
- Fix formatter, lint, and type-checking failures in touched code.
- Do not add broad `# noqa` or `# type: ignore` comments. Prefer fixing the code or using the narrowest scoped suppression with a reason comment.

