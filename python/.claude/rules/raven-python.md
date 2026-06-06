# Python Rules

## Applicability

Use these rules for Python applications, services, libraries, CLIs, scripts, and data pipelines.

Project-specific `AGENTS.md`, nested `AGENTS.md`, local docs, and existing task-runner commands override this file when they are more specific.

Use `.claude/docs/raven-python-quality.md` for detailed Python quality guidance when the task touches public APIs, error design, architecture, async behavior, testing strategy, security, or dependency policy.

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
- Use RTK for noisy `pytest`, `tox`, `nox`, or package-manager output when exact raw output is not required.

## Pause And Ask

Ask before changing:

- Public APIs, module paths, or exported interfaces.
- Database migrations, schema definitions, or persistence behavior.
- Authentication, authorization, secret handling, or security-sensitive code.
- Dependencies, license-sensitive code, vendored code, or generated artifacts.
- Broad refactors, cross-module architecture changes, or unclear scope boundaries.
- Configuration schemas, environment variable contracts, or deployment behavior.
- CI/CD workflows or release automation.

## Python Safety

- Use type hints consistently with surrounding code. Do not introduce untyped signatures into typed codebases.
- Do not weaken mypy or pyright configuration to satisfy a type error. Fix the code instead.
- Avoid `Any` in typed codebases. Use `object` or a narrower type; parse/validate before narrowing.
- Prefer `T | None` over `Optional[T]` in codebases already using modern syntax.
- Use `TypedDict`, `dataclass`, or `pydantic`-style models for structured data rather than raw `dict[str, Any]`.
- Do not use mutable default arguments (`def f(x=[]):`).

## Error Handling

- Catch specific exception types. Avoid bare `except:` or overly broad `except Exception` unless the project already uses that pattern with intentional behavior.
- Do not silently swallow exceptions. Log or re-raise at minimum.
- Define custom exception classes for library or service boundaries so callers can handle specific failure modes.
- Use context managers for cleanup; do not rely on `finally` blocks where `with` is cleaner.
- Preserve exception context when re-raising: use `raise NewError(...) from original_error`.

## Architecture

- Preserve existing module and package boundaries unless the task is explicitly architectural.
- Keep pure business logic separate from I/O, network calls, time, randomness, and framework integration.
- Prefer dependency injection over importing singletons or globals directly in business logic.
- Validate untrusted input at the boundary — HTTP requests, CLI arguments, env config, file contents, external API responses. Pass typed domain values internally.
- Do not import from sibling packages in ways that create circular dependencies.

## Async And Concurrency

- Do not block an async event loop with synchronous filesystem, network, subprocess, or CPU-heavy work unless the project pattern permits it.
- Use `asyncio.to_thread` or an executor for blocking work that must happen in an async context.
- Do not mix `asyncio` and `threading` without understanding the safety implications.
- Keep shared mutable state narrow. Prefer message passing or structured concurrency patterns.

## Testing

- Inspect nearby tests and fixtures before adding new patterns.
- Prefer the narrowest useful test command first, such as one test file or one test case.
- Use `pytest` fixtures and parametrize rather than duplicating setup across tests.
- Write behavior-focused tests; avoid over-mocking internals.
- Add regression tests for bug fixes when the failure can be reproduced deterministically.
- Do not delete or weaken tests to make a change pass unless explicitly requested.
- Broaden to the repository's standard test or quality command only after targeted tests pass.

## Dependencies

- Prefer the standard library and existing dependencies before adding new packages.
- Add packages only when they remove meaningful complexity, are actively maintained, and fit the project's license and security policy.
- Resolve dependency conflicts; do not add packages that create version incompatibilities without a documented resolution.
- Use `--frozen` or equivalent in CI to ensure reproducible installs.

## Performance And Benchmarks

- Profile with `py-spy`, `cProfile`, or `scalene` before optimizing; use `timeit` for microbenchmarks rather than wall-clock one-liners.
- CPU-bound threads do not parallelize due to the GIL; reach for `multiprocessing` or a C extension when CPU parallelism is needed.
- Prefer generators over list comprehensions in hot paths when the result is consumed once.
- If a change is expected to affect performance, state the profiler output, Python version, and dataset size — not just a before/after time.

## Quality Gates

- Run the repository's documented final quality gate before handoff when code changed.
- If no final gate exists, run formatter check, lint, type check, and tests at minimum.
- Fix formatter, lint, and type-checking failures in touched code.
- Do not add broad `# noqa` or `# type: ignore` comments. Prefer fixing the code or using the narrowest scoped suppression with a reason comment.

## Tooling

- Use `rg` for exact module names, function names, import paths, errors, and fixture names.
- Use LSP for definitions, references, hover/type information, and diagnostics once a symbol is known.
- Use ast-grep or Semgrep for structural searches and mechanical rewrites.
- Use GitNexus before changing shared interfaces, public modules, dependency injection boundaries, or persistence code.
- Use Semble for behavior-oriented discovery when the owning module is unclear, then verify with deterministic tools.
- Use RTK for noisy `pytest`, `tox`, `nox`, or package-manager output when exact raw output is not required.
