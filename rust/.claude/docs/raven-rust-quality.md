# Rust Quality Reference

Use this reference for Rust implementation work when the task touches public APIs, architecture, concurrency, unsafe code, security, dependencies, testing strategy, or performance claims.

For language-neutral guidance such as clarity over cleverness, dependency restraint, comments, and maintainability, use `.claude/docs/raven-coding-principles.md`.

## Public Contracts

- Treat public APIs, feature flags, crate names, module paths, serialized formats, config files, and CLI behavior as compatibility surfaces.
- Before changing a compatibility surface, identify callers, tests, docs, and migration needs.
- Prefer additive changes when compatibility matters.
- Update docs and examples when public behavior changes.

## Types And Invariants

- Use the type system to encode domain rules where it improves correctness.
- Prefer newtypes for identifiers, units, and validated values when plain primitives are ambiguous.
- Keep constructors and parsers responsible for validation so invalid states are hard to create.
- Document invariants on public types and unsafe-adjacent abstractions.

## Error Design

- Libraries should expose errors callers can reason about.
- Binaries can add human-oriented context at the boundary where errors are reported.
- Preserve error chains when wrapping errors.
- Avoid panics in reusable code unless violating the invariant means the caller already broke the API contract.

## Unsafe And FFI

- Prefer no unsafe code.
- If unsafe is already part of the project, keep unsafe blocks small and document the safety requirements at the block or abstraction boundary.
- Validate pointer, lifetime, aliasing, alignment, initialization, thread-safety, and ownership assumptions.
- Add tests around the safe wrapper, not only the unsafe implementation detail.
- For FFI, keep Rust-side ownership and error translation explicit.

## Async And Concurrency

- Avoid holding mutex guards or other blocking resources across `.await`.
- Use bounded channels, cancellation, and timeouts where unbounded work could accumulate.
- Keep shared state small and intentionally synchronized.
- Make task ownership and shutdown behavior explicit.
- Do not hide blocking work inside async functions.

## Clippy And Lint Policy

- Follow the repository's configured Clippy and lint profile; do not replace it with a generic command when a project-specific command exists.
- Treat `-D warnings`, denied lints, and CI lint settings as part of the quality gate when the repository enables them.
- Fix lint causes before adding `#[allow(...)]`.
- If a lint suppression is genuinely appropriate, use the narrowest scope and include a short reason.
- Do not add broad crate-level allows, workspace-level allows, or global lint relaxations without explicit approval.
- Keep tests, examples, and benches lint-clean when they are included in the repository's configured Clippy targets.
- If a Clippy failure remains, do not call the work complete; report the exact lint, why it remains, and what decision is needed.

## Testing Strategy

- Start with nearby test patterns and fixtures.
- Test public behavior rather than private implementation details.
- Unit-test pure logic and use integration tests for crate boundaries, CLI behavior, I/O, or service behavior.
- Use doc tests for public examples when they add confidence and remain maintainable.
- For bug fixes, add a regression test that fails before the fix when feasible.
- For golden/reference outputs, review diffs and record why the output changed.

## Dependency And License Hygiene

- Prefer existing dependencies and the standard library.
- Before adding a crate, check maintenance, license compatibility, security posture, transitive dependency impact, and whether the project already has an approved alternative.
- Do not copy or translate code from sources with incompatible licenses.
- For algorithm implementations, work from specifications, papers, or independently written explanations. Record sources for constants, formulas, and expected behavior when useful.

## Security

- Treat command execution, filesystem writes/deletes, path handling, deserialization, network calls, auth/authz, cryptography, and secret handling as high-risk areas.
- Validate untrusted input before it reaches filesystem, shell, network, parser, or persistence boundaries.
- Do not log secrets, tokens, private paths, or user-derived identifiers unless the project explicitly permits it.
- Use dependency audit tooling configured by the repository. Accepted findings should have documented rationale and a review date.

## Performance And Benchmarks

- Prefer simple code until measurement shows a problem.
- Benchmark with a quiet environment, stable inputs, and sequential before/after runs when practical.
- Record command, dataset, machine context, and relevant feature flags for performance claims.
- Treat benchmark changes as evidence, not proof, unless the method is repeatable and representative.
- If performance budgets exist, do not relax them without explicit rationale.

## Workspace Hygiene

- Use workspace-level commands when the change crosses crate boundaries.
- Keep `Cargo.toml`, `Cargo.lock`, feature flags, and build scripts aligned with the repository's dependency policy.
- Do not reformat unrelated files.
- Do not introduce generated files unless the repository expects them to be committed.
- Keep docs and examples synchronized with behavior that agents are expected to treat as canonical.
