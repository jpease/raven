# Python Quality Reference

Use this reference for Python implementation work when the task touches public APIs, architecture, error design, async behavior, testing strategy, security, dependencies, or performance.

For language-neutral guidance such as clarity over cleverness, dependency restraint, comments, and maintainability, use `.claude/docs/raven-coding-principles.md`.

For changes that touch security-sensitive boundaries, run the `raven-security-review` skill before shipping.

## Public Contracts

- Treat public functions, classes, and module interfaces as compatibility surfaces.
- Before changing a public API, identify callers, tests, docs, and downstream packages.
- Prefer additive changes when compatibility matters. Use deprecation warnings before removal.
- Update docstrings and examples when public behavior changes.
- Use `__all__` to declare the intended public surface of a module.

## Types And Invariants

- Use type hints on all new functions and classes in typed codebases.
- Do not weaken `mypy` or `pyright` configuration to satisfy a type error. Fix the code instead.
- Avoid `Any`; use `object` or a narrower type. Parse and validate before narrowing.
- Use `TypedDict`, `dataclass`, or a validation library (e.g., Pydantic, attrs) for structured data. Avoid raw `dict[str, Any]` as a domain object.
- Use `NewType` or single-field dataclasses for important domain identifiers where mixing raw primitives would create bugs.
- Use discriminated unions or tagged data structures for multi-state values rather than optional fields and booleans.
- Use `assert` to document internal invariants, not for input validation at public boundaries.

## Error Design

- Define a custom exception hierarchy for library and service boundaries so callers can handle specific failure modes without catching `Exception`.
- Catch specific exception types. Avoid bare `except:` or `except Exception` at application level unless the intent is explicit (e.g., a global handler that logs and re-raises).
- Do not silently swallow exceptions. Log or re-raise.
- Preserve exception context: `raise AppError("...") from original`.
- For domain and application code that crosses service or thread boundaries, consider returning typed result values (`Result`, `tuple`, named alternatives) when explicit error handling by the caller is more important than raising.
- Use context managers for cleanup; do not rely on `finally` blocks where `with` is cleaner.

## Architecture

### Functional Core, Imperative Shell

Keep business logic pure and testable. Separate:

- **Domain / core layer**: pure functions, domain types, business rules, state transitions — no I/O.
- **Application / service layer**: use-cases that orchestrate domain logic with persistence, messaging, and external calls.
- **Infrastructure / adapter layer**: database, network, email, external APIs, time, randomness, filesystem.
- **Entry layer**: CLI entrypoints, HTTP routes, WSGI/ASGI adapters, argument parsing.

Domain code must not import infrastructure modules. Violations make the domain untestable without real infrastructure.

### Dependency Injection

- Pass collaborators (repositories, clients, config) into functions and classes rather than importing singletons directly.
- This makes components testable without patching module globals.
- Framework-level injection (e.g., FastAPI `Depends`, Django settings) is acceptable at the entry layer.

### Module Boundaries

- Validate untrusted input at the boundary — HTTP requests, CLI arguments, env config, file contents, external API responses. Pass typed domain values internally.
- Do not create circular imports. Reorganize modules or introduce an interface layer rather than working around the cycle.

## Async And Concurrency

- Do not block an async event loop with synchronous filesystem, network, subprocess, or CPU-heavy work.
- Use `asyncio.to_thread` or a thread-pool executor for blocking work that must happen in an async context.
- Keep shared mutable state narrow. Prefer `asyncio.Queue` or structured concurrency patterns over shared variables protected by locks when practical.
- Do not mix `asyncio` and `threading` without understanding the safety implications; prefer one concurrency model per boundary.

## Testing Strategy

### Test Pyramid

| Layer       | Focus                           | Tooling             |
| ----------- | ------------------------------- | ------------------- |
| Unit        | Pure functions, domain logic    | pytest              |
| Service     | Use-cases, repositories, routes | pytest + fakes      |
| Integration | Real DB, real external services | pytest              |
| E2E         | CLI or HTTP flows end-to-end    | pytest / subprocess |

### Unit And Service Tests

- Test behavior, not implementation. Avoid over-mocking internals.
- Use `pytest` fixtures and `parametrize` rather than duplicating setup across tests.
- Domain code should have high branch coverage; it is pure and fast to test.
- For service tests, use fakes or in-memory implementations over heavy mocks of infrastructure.

### Integration Tests

- Use real database instances where feasible (e.g., Docker-based Postgres in CI).
- Isolate test data with transactions, unique prefixes, or dedicated test schemas.

### Regression Tests

- Add a regression test for every bug fix when the failure can be reproduced deterministically.
- Do not delete or weaken existing tests to make a change pass.

## Dependency And License Hygiene

- Prefer the standard library and existing dependencies.
- Before adding a package, check: maintenance status, license compatibility, security posture, and whether the project already has an approved alternative.
- Do not copy or translate code from sources with incompatible licenses.
- Use `pip-audit`, `safety`, or equivalent to surface known vulnerabilities. Treat high/critical findings as real risk.
- In CI, use `--frozen` (or equivalent) for reproducible installs.

## Security

- Validate all input before it reaches the filesystem, shell, network, parser, or persistence layer.
- Use parameterized queries for database access; never interpolate user values into SQL strings.
- Do not use `subprocess` with `shell=True` and untrusted input. Use argument lists.
- Do not deserialize untrusted data with formats that allow arbitrary code execution; prefer JSON or other safe formats for external data exchange.
- Secrets must not be hardcoded or logged. Use environment variables or a secrets manager.
- Use file permissions and safe temp-file APIs (`tempfile` module) for sensitive file operations.

## Performance And Benchmarks

- Prefer simple code until measurement shows a problem.
- Avoid loading large datasets into memory when iteration or streaming is feasible.
- Use generators and lazy evaluation for large sequences.
- Profile before broad optimization; do not make performance claims from a single local run.
- For CPU-bound work, understand the GIL's implications. Use `multiprocessing` or C extensions where needed.
- For I/O-bound work, prefer async or thread pools over busy-waiting.
