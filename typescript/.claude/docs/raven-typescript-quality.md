# TypeScript Quality Reference

Use this reference for TypeScript implementation work when the task touches type system design, error design, architecture, React patterns, async behavior, testing strategy, security, or dependency policy.

For language-neutral guidance such as clarity over cleverness, dependency restraint, comments, and maintainability, use `.claude/docs/raven-coding-principles.md`.

For changes that touch security-sensitive boundaries, run the `raven-security-review` skill before shipping.

## Public Contracts

- Treat exported functions, types, classes, and package interfaces as compatibility surfaces.
- Before changing a public API, identify callers, tests, docs, and downstream packages.
- Prefer additive changes when compatibility matters. Use `@deprecated` JSDoc and a migration path before removal.
- Update documentation and examples when public behavior changes.
- Use explicit exports (`export { ... }`) rather than exporting everything; a clear surface is easier to evolve.

## TypeScript Configuration

Maintain strict type checking. Recommended baseline:

```json
{
  "strict": true,
  "noImplicitAny": true,
  "exactOptionalPropertyTypes": true,
  "noUncheckedIndexedAccess": true,
  "useUnknownInCatchVariables": true,
  "noPropertyAccessFromIndexSignature": true,
  "noImplicitOverride": true,
  "noFallthroughCasesInSwitch": true,
  "noEmitOnError": true
}
```

Do not weaken these settings to satisfy a type error. Fix the code instead.

## Types And Invariants

### No `any`

- `any` is forbidden in application and domain code.
- Use `unknown` for values whose type is genuinely not known. Narrow with schema validation or type guards before use.
- Avoid `as SomeType` casts in application code. If a cast is unavoidable, isolate it at a validated boundary and add a comment explaining the invariant.
- Use `satisfies` instead of type assertions for configuration objects where you want inference to be preserved.
- `// @ts-ignore` is forbidden. `// @ts-expect-error` is allowed only with a reason comment.

### Discriminated Unions

Prefer discriminated unions over boolean flags or optional fields for multi-state values.

```ts
// Prefer this
type AsyncState<T> =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'success'; data: T }
  | { status: 'error'; error: Error };

// Over this
type AsyncState<T> = {
  loading: boolean;
  data?: T;
  error?: Error;
};
```

Enforce exhaustiveness with `never` in switch statements:

```ts
function assertNever(x: never): never {
  throw new Error('Unexpected value: ' + String(x));
}
```

### Const Unions Instead Of Enums

Prefer `as const` unions over TypeScript `enum`:

```ts
export const TaskStatus = ['todo', 'in_progress', 'done'] as const;
export type TaskStatus = (typeof TaskStatus)[number];
```

### Branded Types For Domain Identifiers

Use branded types to prevent accidental mixing of domain IDs:

```ts
type Brand<T, Name extends string> = T & { readonly __brand: Name };

type UUID = Brand<string, 'uuid'>;
type WorkspaceId = Brand<UUID, 'workspaceId'>;
type TaskId = Brand<UUID, 'taskId'>;
```

Apply branding after validation at the boundary. Internal code accepts branded types, not raw strings.

### Type-Only Imports

Prefer `import type { ... }` for type-only imports to avoid accidental runtime side effects and improve tree-shaking:

```ts
import type { TaskId } from './types';
import { createTask } from './task';
```

## Boundary Validation

Validate all untrusted input at the system boundary. After validation, internal code operates on typed domain values.

Boundaries include:
- HTTP request bodies, query params, and route params
- Environment variables and config files
- Webhook payloads and external API responses
- OIDC claims and role mappings
- Imported data from external systems

Rule: parse once at the boundary, pass typed values everywhere else.

Use a consistent schema validation library (Zod or Valibot are common choices). Do not use ad-hoc casting instead of validation.

## Error Design

### Result-Like Patterns For Domain Code

Domain and application layers should return typed errors rather than throwing:

```ts
type Result<T, E> = { ok: true; value: T } | { ok: false; error: E };
```

This makes failure modes explicit and testable. Throwing is appropriate at I/O boundaries and framework adapters, but convert to typed errors before they enter domain code.

### Error Context

Preserve error context when wrapping:

```ts
// Preserve the original
throw new AppError('Failed to load workspace', { cause: err });

// Not this
throw new Error('something went wrong');
```

### HTTP Error Mapping

Map internal errors to a consistent API error envelope at the route layer:
- Validation errors → `validation_failed`
- Missing resources → `not_found`
- Auth failures → `unauthorized` / `forbidden`
- Conflicts → `conflict`
- Unexpected failures → `internal_error`

## Architecture

### Functional Core, Imperative Shell

Keep business logic pure and testable. Separate:

- **Domain/core layer**: pure functions, type definitions, business rules, state transitions — no I/O.
- **Application/service layer**: use-cases that orchestrate domain logic with persistence and external calls.
- **Infrastructure/adapter layer**: database, network, email, external APIs, time, randomness.
- **API/entry layer**: routes, request parsing, auth middleware, error mapping.

Domain code must not import infrastructure modules. Violations make the domain untestable without real infrastructure.

### Frontend Layering (React)

For React applications, enforce module boundaries:

```
src/
  ui/          # low-level, reusable primitives (no feature imports)
  components/  # composed widgets
  features/    # feature-level orchestration and state
  pages/       # route shells only — composition, no business logic
  lib/         # small shared utilities
```

Rules:
- `ui/` must not import from `features/` or `pages/`.
- `pages/` must remain thin; compose feature components, no business logic.
- Domain rules live server-side; the UI is not an authority layer.

Enforce these boundaries via ESLint (e.g., `eslint-plugin-boundaries`).

### State: Server State vs UI State

Separate server state (durable domain data) from UI state (ephemeral interaction state):

- Server state comes from a single client data abstraction, not ad-hoc fetches.
- Shared UI state (selection, filters, open dialogs) uses a small explicit store with stable selectors.
- `useEffect` is for integration glue (subscriptions, event listeners, DOM measurement) — not data fetching or state derivation.

## Async And Concurrency

- Prefer `async`/`await` over raw Promise chains. Use `Promise.all`, `Promise.allSettled`, and `Promise.race` for parallel work.
- Always handle rejections explicitly. Unhandled rejections are errors.
- `async void` is acceptable for event handlers but must not propagate to callers that expect a thenable.
- In Node.js, do not block the event loop with synchronous CPU-heavy work. Use `node:worker_threads` or child processes for CPU-bound tasks.
- Do not spawn unbounded parallel async work. Batch or queue concurrent operations in server contexts.
- In React effects, handle stale results: cancel with `AbortController` or check a cleanup flag before applying async results to state. Prefer data-fetching abstractions over raw `useEffect` + `fetch` patterns.
- For shared mutable state across async boundaries, prefer immutable updates or message queues over ad-hoc mutation.

## Performance And Benchmarks

- Prefer simple code until measurement shows a problem.
- Profile or benchmark before broad optimization; do not make performance claims from a single local run.
- Record command, dataset, environment, and relevant configuration when reporting performance results.
- Avoid N+1 query patterns in API routes; satisfy data requirements in a fixed number of queries.
- Use virtualization for large lists in UI; avoid unbounded renders.
- Avoid blocking the render path with expensive synchronous computations; precompute via selectors or memoization.

## Testing Strategy

### Test Pyramid

| Layer | Focus | Tooling |
|---|---|---|
| Unit | Pure functions, domain logic | Vitest or Jest |
| Service | Use-cases, repositories, routes | Vitest or Jest |
| Integration | Real DB, real external services | Vitest or Jest |
| E2E | Full user journeys | Playwright |

### Unit And Service Tests

- Test behavior, not implementation. Avoid over-mocking internals.
- Domain code should have high branch coverage; it is pure and fast to test.
- API route handlers should be tested via app injection or equivalent.
- Error codes returned by API should match the documented error taxonomy.

### E2E Tests (Playwright)

- Use `data-testid` selectors exclusively. Do not use text-based or CSS selectors.
- Avoid arbitrary sleeps. Use Playwright's waiting mechanisms or application sync signals.
- Use a deterministic test environment — disable animations, stabilize the clock.
- Keep E2E coverage narrow and targeted; unit tests cover the bulk of correctness.
- Emit enough replay metadata for failing generated tests to be reproduced locally.

### Invariant And Regression Tests

- Add a regression test for every bug fix when the failure can be reproduced deterministically.
- Test authorization rules, status transitions, and deduplication constraints where they are critical.
- Cross-workspace isolation must be verified in integration and E2E suites.

## Security

- Validate all input before it reaches the filesystem, shell, network, parser, or persistence layer.
- Secrets must not be logged or returned after creation.
- All mutations require server-side authorization checks. Claims from OIDC must be validated and mapped server-side, not trusted from the client.
- Do not use `eval`, `Function()`, or dynamic `require()` with untrusted input.
- Use parameterized queries; do not interpolate user values into SQL or shell strings.

## Dependency And License Hygiene

- Prefer existing dependencies and the standard library.
- Add a new package only when it removes meaningful complexity, is actively maintained, and fits the project's license policy.
- Resolve peer dependency warnings. Track accepted exceptions with a documented rationale and review date.
- Do not copy or translate code from sources with incompatible licenses.
- In CI, use `--frozen-lockfile` (or equivalent) to ensure reproducible installs.
- Treat high/critical vulnerability audit findings as real risk. Accepted findings should have documented rationale.

## Workspace And Monorepo Hygiene

- Use workspace-level commands when a change crosses package boundaries.
- Keep `package.json`, lockfile, and tsconfig paths aligned with the repository's dependency policy.
- Do not reformat unrelated files.
- Do not introduce committed generated files unless the repository expects them.
- Keep docs and examples synchronized with public behavior.
