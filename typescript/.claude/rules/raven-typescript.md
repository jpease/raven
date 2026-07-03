# TypeScript Rules

## Applicability

Use these rules for TypeScript projects, monorepos, Node.js services, React applications, CLI tools, and libraries.

Project-specific `AGENTS.md`, nested `AGENTS.md`, local docs, and existing task-runner commands override this file when they are more specific.

Use `.claude/docs/raven-typescript-quality.md` for detailed TypeScript quality guidance when the task touches type system design, error handling patterns, React architecture, module structure, async and concurrency, testing strategy, dependency policy, or performance.

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
- In monorepos and project-reference layouts, editor-injected `cannot find module` diagnostics are often false positives (one root `tsserver` over a solution-style `tsconfig`); the build/typecheck gate wins on disagreement.

## Pause And Ask

In addition to the guardrails in AGENTS.md, ask before changing:

- Serialization formats, persisted data, or API contracts.

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
- Preserve error context when wrapping; do not replace useful errors with generic strings.

## Architecture

- Preserve existing module and package boundaries unless the task is explicitly architectural.
- Keep pure domain logic separate from I/O, network calls, time, and randomness.
- Prefer `import type` boundaries between packages when only types cross the boundary.

## Async And Concurrency

- Always handle Promise rejections. Unhandled rejections are errors, not warnings.
- Do not spawn unbounded parallel async work in server contexts; batch or queue concurrent operations.

## Testing

- Inspect nearby tests and fixtures before adding new patterns.
- Prefer the narrowest useful test command first, such as one file or one test case.
- Unit-test pure functions and domain logic at high volume.
- Use integration tests for API routes, repositories, and service layers.
- Do not delete or weaken tests to make a change pass unless explicitly requested.
- Add regression tests for bug fixes when the failure can be reproduced deterministically.

## Dependencies

- Resolve peer dependency warnings; track accepted exceptions explicitly.
- Use `--frozen-lockfile` (or equivalent) in CI to prevent drift.

## Performance And Benchmarks

- Profile before broad optimization; do not make performance claims from a single local run.

## Quality Gates

- Run the repository's documented final quality gate before handoff when code changed.
- If no final gate exists, run typecheck, lint, and tests at minimum.
- Fix typecheck, lint, and formatter failures in touched code.
- Do not add broad `eslint-disable` comments. Prefer fixing the code or using the narrowest scoped disable with a reason comment.
