# Rust Rules

## Applicability

Use these rules for Rust crates, workspaces, command-line tools, services, libraries, and Rust-backed applications.

Project-specific `AGENTS.md`, nested `AGENTS.md`, local docs, and existing task-runner commands override this file when they are more specific.

Use `.claude/docs/raven-rust-quality.md` for detailed Rust quality guidance when the task touches public APIs, unsafe code, concurrency, dependency policy, security, benchmarking, or larger architecture decisions.

## Setup And Commands

- Prefer the repository's task runner, such as `just`, `make`, `cargo xtask`, or scripts, before inventing raw `cargo` command sequences.
- Discover available commands before guessing when the repo documents them.
- Use the narrowest relevant command first, then broaden after it passes.
- Common fallback commands are:
  - `cargo fmt --all -- --check`
  - `cargo clippy --workspace --all-targets --all-features -- -D warnings`
  - `cargo test --workspace --all-features`
  - `cargo audit`
  - `cargo deny check`
- Do not assume every project supports `--all-features`, `cargo audit`, `cargo deny`, `nextest`, or benchmarks. Use them when configured or clearly appropriate.

## Pause And Ask

In addition to the guardrails in AGENTS.md, ask before changing:

- `unsafe`, FFI, ABI, linking, build scripts, generated bindings, or platform-specific packaging.
- CI/release workflows, publishing settings, benchmark baselines, or golden/reference outputs.
- Serialization formats, persisted data, config schemas, or compatibility contracts.

## Rust Safety

- Prefer safe Rust. Do not add `unsafe` unless the project already permits it and the change includes a clear safety invariant.
- If a crate uses `#![forbid(unsafe_code)]`, preserve it.
- Avoid `unwrap`, `expect`, `panic`, and `todo` in production paths. Use typed errors, `?`, or carefully justified `expect` messages where the invariant is local and obvious.
- Avoid unchecked `as` casts where truncation, sign changes, precision loss, or overflow are possible. Prefer `From`, `TryFrom`, explicit bounds checks, or domain-specific conversion helpers.
- Use newtypes for domain identifiers, units, and values where plain primitives make invalid states easy to represent.
- Prefer explicit lifetimes, ownership, and borrowing over cloning to satisfy the compiler without understanding ownership.

## Error Handling

- For libraries, prefer typed errors that callers can match, commonly with `thiserror` when the project uses it.
- For binaries and tests, contextual errors are acceptable when they match local convention, commonly with `anyhow` or `eyre`.
- Preserve error sources and context. Do not replace useful errors with generic strings.
- Keep recoverable failures as `Result`; reserve panics for impossible internal invariants that are documented and tested.

## Architecture

- Preserve existing crate and module boundaries unless the task is explicitly architectural.
- Keep pure logic separate from I/O, time, randomness, process execution, network calls, and filesystem access where practical.
- Coordinate across modules through explicit interfaces, events, traits, or data types instead of hidden global coupling.
- Use traits when they create a meaningful boundary for tests or alternative implementations, not as default indirection.
- Prefer small focused functions and early returns over deeply nested control flow.
- Add `#[must_use]` to pure helpers or builder-like APIs when ignoring the result is likely a bug.

## Async And Concurrency

- Do not block async runtimes with synchronous filesystem, process, sleep, lock, or CPU-heavy work unless the project pattern permits it.
- Avoid holding locks across `.await`.
- Prefer structured cancellation, timeouts, and bounded queues for long-running async work.
- Be explicit about `Send` and `Sync` requirements when values cross thread or task boundaries.
- Keep shared mutable state narrow. Prefer message passing or ownership transfer when it simplifies correctness.

## Testing

- Inspect nearby tests and fixtures before adding new patterns.
- Prefer focused unit tests for pure helpers and integration tests for public behavior.
- Add regression tests for bug fixes when the failure can be reproduced deterministically.
- Use property tests, fuzz tests, snapshot tests, or golden/reference tests only when they fit the behavior and the project already supports or benefits from them.
- Update golden/reference outputs only when the behavior change is intentional, reviewed, and documented with the reason.
- Do not delete or weaken tests to make a change pass unless explicitly requested.

## Dependencies

- Prefer the standard library and existing dependencies before adding new crates.
- Add dependencies only when they remove meaningful complexity, are maintained, and fit the repository's license and security policy.
- Check license compatibility and maintenance status for new dependencies.
- Treat security audit findings as real risk. If a finding is accepted, document severity, exploitability, mitigation, owner, and review date according to project policy.
- For algorithmic code, derive from specifications, papers, or original reasoning. Do not copy or translate incompatible third-party implementations.

## Performance And Benchmarks

- Measure before broad optimization unless the inefficiency is obvious and local.
- Keep benchmark claims scoped to the machine, command, dataset, and conditions used.
- Run before/after comparisons under similar conditions and rerun suspicious results.
- Do not make broad performance claims from a single local run.
- If a change materially worsens latency, memory, binary size, or throughput, include the reason and mitigation.

## Clippy And Lint Handling

- Use the repository's configured Clippy command or quality gate when one exists.
- Do not weaken lint settings, add broad `allow` attributes, or silence Clippy globally without explicit approval.
- Prefer fixing the code over suppressing the lint. When suppression is justified, keep it local and document why.
- Test code should meet the repository's lint expectations; do not assume tests may ignore Clippy unless local policy says so.

## Quality Gates

- Run the repository's documented final quality gate before handoff when code changed.
- If no final gate exists, use the narrowest relevant `cargo` checks first, then broaden to workspace checks when practical.
- Fix `rustfmt`, Clippy, and warning failures in touched code.
- Do not add broad `allow` attributes to silence lints. Prefer fixing the code or adding the narrowest justified allowance with a reason.
- If a required check cannot run locally, state the exact command and blocker.

## Tooling

- Use `cargo metadata`, `cargo tree`, or dependency graph tools for workspace and dependency questions.
- Use Rust Analyzer for rename safety when available (via LSP or IDE).
