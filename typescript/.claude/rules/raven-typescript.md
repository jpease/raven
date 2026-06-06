# TypeScript Rules

## Applicability

Use these rules for TypeScript projects, monorepos, Node.js services, React applications, CLI tools, and libraries.

Project-specific `AGENTS.md`, nested `AGENTS.md`, local docs, and existing task-runner commands override this file when they are more specific.

Use `.claude/docs/raven-typescript-quality.md` for detailed TypeScript quality guidance when the task touches type system design, error handling patterns, React architecture, module structure, testing strategy, or dependency policy.

## Setup And Commands

- Prefer the repository's task runner such as `turbo`, `just`, `make`, or `nx` before inventing raw `tsc` or package-manager command sequences.
- Discover available commands before guessing when the repo documents them.
- Use the narrowest relevant command first, then broaden after it passes.
- Common fallback commands:
  - `pnpm typecheck` or `tsc --noEmit`
  - `pnpm lint` or `eslint .`
  - `pnpm test` or `vitest run`
  - `pnpm build`
  - `pnpm format --check` or `prettier --check .`
- Do not assume every project uses pnpm, turbo, vitest, or ESLint. Confirm before using.
- Use RTK for noisy test, build, or package manager output when exact raw output is not required.

## Pause And Ask

Ask before changing:

- Public APIs, package boundaries, module paths, or exported types.
- Serialization formats, persisted data, config schemas, migrations, or API contracts.
- Authentication, authorization, secret handling, or security-sensitive behavior.
- Dependencies, license-sensitive code, vendored code, or generated artifacts.
- Broad refactors, cross-package architecture changes, or unclear scope boundaries.
- Database queries, schema definitions, or migration files.
- CI/CD workflows, deployment config, or release behavior.

## TypeScript Safety

- Maintain `strict: true` and do not weaken TypeScript configuration.
- `any` is forbidden in application and domain code. Use `unknown` and validate/narrow.
- Avoid `as SomeType` casts except at validated boundaries. Prefer `satisfies` for configuration objects.
- Do not use `// @ts-ignore`. Use `// @ts-expect-error` only with a reason comment.
- Prefer `import type { ... }` for type-only imports.
- Use discriminated unions over boolean flags for multi-state values.
- Use branded types for domain identifiers where mixing raw primitives would create bugs.

## Error Handling

- Prefer typed errors or `Result`-like patterns in domain and application code.
- Reserve `throw` for true boundary failures; catch and convert to typed errors at entry points.
- Preserve error context when wrapping errors; do not replace useful errors with generic strings.

## Architecture

- Preserve existing module and package boundaries unless the task is explicitly architectural.
- Keep pure domain logic separate from I/O, network calls, time, and randomness.
- Validate untrusted input at the boundary — HTTP requests, env config, webhooks, external data. Pass typed domain values internally.
- Prefer `import type` boundaries between packages when only types cross the boundary.

## Async And Concurrency

- Prefer `async`/`await` over raw Promise chains for readability and error propagation.
- Always handle Promise rejections. Unhandled rejections are errors, not warnings.
- Avoid `async void` except for top-level event handlers; return the Promise so callers can await or catch.
- In Node.js, do not block the event loop with synchronous CPU-heavy or filesystem work; use `fs/promises`, worker threads, or a process pool.
- Do not spawn unbounded parallel async work in server contexts; batch or queue concurrent operations.
- In React, handle stale async results in effects: cancel with `AbortController` or check a mounted flag before applying results.

## Testing

- Inspect nearby tests and fixtures before adding new patterns.
- Prefer the narrowest useful test command first, such as one file or one test case.
- Unit-test pure functions and domain logic at high volume.
- Use integration tests for API routes, repositories, and service layers.
- Use Playwright for E2E selectively; prefer `data-testid` selectors over text selectors.
- Do not delete or weaken tests to make a change pass unless explicitly requested.
- Add regression tests for bug fixes when the failure can be reproduced deterministically.

## Dependencies

- Prefer existing dependencies before adding new packages.
- Add packages only when they remove meaningful complexity and are actively maintained.
- Resolve peer dependency warnings; track accepted exceptions explicitly.
- Use `--frozen-lockfile` (or equivalent) in CI to prevent drift.

## Performance And Benchmarks

- For web targets, bundle size is as important as runtime speed; measure with a bundle analyzer before and after changes that affect dependencies or code splitting.
- Use `performance.now()` or `console.time` for microbenchmarks, but account for JIT warmup in V8 — run iterations before measuring.
- For Node.js services, use `clinic`, `0x`, or `autocannon` for profiling; do not optimize from `console.time` alone.
- Profile React render performance with React DevTools Profiler before adding memoization.
- State runtime (Node.js version or browser and version), build mode (`development` vs `production`), and dataset when reporting performance results.

## Quality Gates

- Run the repository's documented final quality gate before handoff when code changed.
- If no final gate exists, run typecheck, lint, and tests at minimum.
- Fix typecheck, lint, and formatter failures in touched code.
- Do not add broad `eslint-disable` comments. Prefer fixing the code or using the narrowest scoped disable with a reason comment.

## Tooling

- Use `rg` for exact symbols, imports, config keys, and error messages.
- Use LSP (TypeScript Language Server) for definitions, references, type information, diagnostics, and rename safety.
- Use ast-grep or Semgrep for structural searches and mechanical rewrites.
- Use GitNexus before editing shared public APIs or cross-package interfaces.
- Use Semble for conceptual discovery when names are unclear, then verify with deterministic tools.
- Use RTK or equivalent output compression for noisy builds, test logs, and package manager output when exact raw output is not required.
