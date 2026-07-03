# Go Rules

## Applicability

Use these rules for Go modules, workspaces, command-line tools, services, libraries, and Go-backed applications.

Project-specific `AGENTS.md`, nested `AGENTS.md`, local docs, and existing task-runner commands override this file when they are more specific.

Use `.claude/docs/raven-go-quality.md` for detailed Go quality guidance when the task touches public APIs, error design, unsafe/cgo, concurrency, dependency policy, security, benchmarking, or larger architecture decisions.

## Setup And Commands

- Prefer the repository's task runner, such as `just`, `make`, `go task`, or scripts, before inventing raw `go` command sequences.
- Discover available commands before guessing when the repo documents them.
- Use the narrowest relevant command first, then broaden after it passes.
- Common fallback commands are:
  - `gofmt -w .`
  - `go test ./...`
  - `go vet ./...`
  - `golangci-lint run`
- Do not assume every project supports `golangci-lint`, race tests, fuzzing, or benchmarks. Use them when configured or clearly appropriate.

## Pause And Ask

In addition to the guardrails in AGENTS.md, ask before changing:

- cgo, `unsafe`, FFI, ABI, linking, generated bindings, or platform-specific packaging.
- CI/release workflows, publishing settings, benchmark baselines, or golden/reference outputs.

## Go Safety

- Prefer simple, explicit code. Avoid clever control flow, hidden global state, and package-level mutable state unless the project already uses that pattern.
- Avoid `panic` in production paths except for impossible internal invariants or process-startup configuration failures that the project already treats as fatal.
- Check and return errors with context. Do not discard errors with `_ =` unless the operation is intentionally best-effort and that intent is clear.
- Keep interfaces small and consumer-owned. Do not add broad interfaces just to mock a concrete type.
- Avoid `unsafe` and cgo unless the project already permits them and the change includes clear safety constraints.

## Error Handling

- For libraries, expose errors callers can reason about with wrapping, sentinels, or typed errors where matching is part of the contract.
- Preserve error causes with `%w` when wrapping.
- Keep recoverable failures as returned errors; reserve panics for impossible internal invariants.

## Architecture

- Preserve existing module and package boundaries unless the task is explicitly architectural.
- Keep pure logic separate from I/O, time, randomness, process execution, and network calls.
- Keep package APIs cohesive. Avoid dumping unrelated helpers into broad utility packages.
- Use `context.Context` at API boundaries that perform I/O, blocking work, or cancellation-sensitive operations.

## Concurrency

- Pass `context.Context` through blocking, network, and process boundaries when cancellation matters.
- Avoid goroutine leaks. Make ownership, cancellation, channel closing, and shutdown behavior explicit.
- Do not hold locks while performing blocking I/O or calling into unknown code.
- Run race tests when concurrency behavior changed and the project supports it.

## Testing

- Inspect nearby tests and fixtures before adding new patterns.
- Prefer focused unit tests for pure helpers and integration tests for public behavior.
- Add regression tests for bug fixes when the failure can be reproduced deterministically.
- Do not delete or weaken tests to make a change pass unless explicitly requested.
- Avoid brittle sleeps, timing assumptions, and oversized snapshots unless the codebase already relies on them.

## Dependencies

- Check license compatibility and maintenance status for new dependencies.
- Treat security audit findings as real risk.

## Performance And Benchmarks

- Measure before broad optimization unless the inefficiency is obvious and local.
- Do not make broad performance claims from a single local run.

## Lint Handling

- Do not weaken `golangci-lint`, `go vet`, or project lint settings without explicit approval.
- Prefer fixing the code over suppressing the lint. When suppression is justified, keep it local and document why.

## Quality Gates

- Run the repository's documented final quality gate before handoff when code changed.
- If no final gate exists, use the narrowest relevant `go` checks first, then broaden to `go test ./...`, `go vet ./...`, and configured lint checks when practical.
- Fix `gofmt`, `go vet`, and lint failures in touched code.
- Do not add broad suppressions to silence lints. Prefer fixing the code or adding the narrowest justified suppression with a reason.
- If a required check cannot run locally, state the exact command and blocker.

## Tooling

- Use `go list`, `go env`, `go mod graph`, `go mod why`, and `go version -m` for module and dependency questions.
- Use gopls for rename safety, references, diagnostics, and workspace navigation when available.
