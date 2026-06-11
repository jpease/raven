# Elixir Quality Reference

Use this reference for Elixir implementation work when the task touches public APIs, architecture, OTP, Ecto, Phoenix/LiveView behavior, security, testing strategy, dependencies, or production operations.

For language-neutral guidance such as clarity over cleverness, dependency restraint, comments, and maintainability, use `.claude/docs/raven-coding-principles.md`.

For changes that touch security-sensitive boundaries, run the `raven-security-review` skill before shipping.

## Public Contracts

- Treat public modules, context functions, routes, API payloads, event names, job args, database schemas, migrations, config keys, and release behavior as compatibility surfaces.
- Before changing a compatibility surface, identify callers, tests, docs, data migration needs, and deployment order.
- Prefer additive changes when compatibility matters.
- Update docs, examples, and tests when public behavior changes.

## Contexts And Architecture

- Keep domain logic in contexts or domain modules, not controllers, LiveViews, templates, or jobs.
- Keep Phoenix web modules focused on request handling, presentation, and interaction flow.
- Keep external integrations behind explicit boundaries so tests can stub them without network access.
- Avoid generic `Utils`, `Manager`, and `Handler` modules when a domain-specific name is clearer.
- Use small composable functions and pattern matching rather than broad conditional control flow.
- Do not introduce cross-context calls that create cycles or hidden coupling without checking local architecture.

## Return Values And Errors

- Prefer explicit `{:ok, value}` and `{:error, reason}` tuples for expected domain failures.
- Preserve failure reasons that callers can act on.
- Convert low-level errors at boundaries where a user-facing or API-facing error shape is needed.
- Reserve exceptions for truly exceptional failures or framework-required behavior.
- Do not silently swallow errors; log or return them according to the boundary's convention.

## Types, Specs, And Docs

- Add `@spec` for public functions when the project uses specs or the function participates in a boundary.
- Keep specs honest; do not widen to `term()` to silence Dialyzer or LSP feedback.
- Public modules should have useful `@moduledoc` unless the project explicitly suppresses docs for that layer.
- Docs should explain why a boundary or invariant exists, not repeat the function name.
- Inline comments should be rare and reserved for non-obvious decisions.

## OTP Design

- Supervision trees are runtime contracts. Preserve restart strategy, child order, process names, and shutdown behavior unless intentionally changing them.
- Use supervised processes for long-lived work; avoid orphaned processes.
- Keep GenServer APIs explicit and small.
- Avoid using Agent or GenServer as a substitute for clear data flow.
- Add tests around process lifecycle, failure handling, and message ordering when those behaviors matter.

## Ecto And Data Safety

- Treat migrations and schema changes as durable compatibility changes.
- Use database constraints and transactions for invariants that must hold under concurrency.
- Keep changesets responsible for validation and casting; keep server-controlled fields out of user-controlled casts.
- Prefer `Ecto.Multi` or repository transactions when multiple writes must succeed or fail together.
- Test idempotency and duplicate delivery behavior for webhook and job processing.
- Use realistic fixtures for external payloads and keep them sanitized.
- Never run destructive data changes without clear migration and rollback reasoning.

## Phoenix And LiveView

- Follow local Phoenix version conventions, especially generated layout, component, and auth patterns.
- Keep assign names clear and avoid storing derived data that can be computed cheaply.
- Use streams for large or frequently updated LiveView collections when appropriate.
- Keep LiveView event handlers thin; move domain work to context functions.
- Prefer stable DOM IDs and intent-based assertions for tests.
- Avoid inline JavaScript and one-off asset paths; use existing JS/CSS entry points.
- Respect CSP and security-header policy when adding scripts, styles, images, or external origins.

## Testing Strategy

- Put most coverage at the domain and integration levels.
- Domain tests should cover invariants, validation, authorization, and pure calculations.
- Integration tests should cover controllers, LiveViews, jobs, webhooks, email boundaries, persistence behavior, and external integration seams.
- Background jobs should be tested for enqueueing, execution, retry behavior, and idempotency.
- Webhook tests should cover valid signatures, invalid signatures, duplicate delivery, and partial-failure safety.
- Use `start_supervised!/1` for processes in tests.
- Avoid `Process.sleep/1`; synchronize with monitors, messages, or process state calls.
- Use fixed time or time helpers when ordering or expiry matters.
- Do not use live network services in tests. Use local stubs, mocks, fixtures, and test adapters.

## Security

- Treat auth, tenant isolation, IDOR risk, webhook verification, file access, command execution, secret handling, CSP, and rate limiting as high-risk areas.
- Validate authorization in both domain and web tests when data ownership matters.
- Never log secrets, tokens, private keys, magic links, payment data, signed license payloads, or raw credential material.
- Prefer workload identity or platform secret stores over long-lived static cloud keys when available.
- Keep sensitive runtime configuration out of committed plain-text files.
- Run Sobelow, Semgrep, dependency audits, and project-specific secret checks when configured.

## Dependencies And Supply Chain

- Prefer the standard library, OTP, Phoenix/Ecto primitives, and existing dependencies.
- Do not add dependencies for small convenience wrappers.
- Before adding a Hex dependency, check maintenance, license compatibility, security posture, transitive dependencies, and whether the project already has a preferred alternative.
- Keep dependency updates scoped. Explain lockfile changes.
- Do not bypass audit findings without documenting severity, exploitability, mitigation, owner, and review date according to project policy.

## Performance And Operations

- Prefer correctness and reliability before optimization.
- Measure before optimizing unless the inefficiency is local and obvious.
- Avoid premature caching and premature concurrency.
- For production-facing changes, consider observability: logs, metrics, traces, alerts, and operational runbooks.
- Log at boundaries with stable IDs and enough context to debug, but never with sensitive material.
- For performance claims, state the command, dataset, runtime versions, and conditions used.

## Quality Gates

- Use the repository's quality alias or task runner when present.
- Common final checks include format check, compile with warnings as errors, tests, Credo, Sobelow, dependency audit, and asset checks.
- Start narrow while developing, then run the documented final gate before handoff.
- If a check fails outside touched code, report it clearly and avoid hiding it.
- If a check cannot run, state the command, missing dependency, and residual risk.
