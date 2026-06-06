# Elixir Rules

## Applicability

Use these rules for Elixir applications, Phoenix projects, Mix libraries, OTP services, LiveView applications, Ecto-backed systems, and Oban-style background jobs.

Project-specific `AGENTS.md`, nested `AGENTS.md`, local docs, and existing task-runner commands override this file when they are more specific.

Use `.claude/docs/raven-elixir-quality.md` for detailed Elixir quality guidance when the task touches OTP supervision, Ecto migrations, Phoenix/LiveView behavior, security, deployment, testing strategy, or larger architecture decisions.

## Setup And Commands

- Prefer the repository's task runner, such as `mix precommit`, `mix quality`, `just`, `make`, or scripts, before inventing raw `mix` command sequences.
- Discover available aliases in `mix.exs` and documented commands before guessing.
- Use the narrowest relevant command first, then broaden after it passes.
- Common fallback commands:
  - `mix format --check-formatted`
  - `mix compile --warnings-as-errors`
  - `mix test`
  - `mix test path/to/test.exs` for a specific file
  - `mix test --failed` after a failure
  - `mix credo --strict` when Credo is configured
  - `mix sobelow --config` or the repository's Sobelow command when configured
  - `mix deps.audit` when `mix_audit` is configured
- Run `mix help <task>` before using an unfamiliar Mix task or option.
- Avoid `mix deps.clean --all` unless there is a clear dependency corruption reason.
- Use RTK for noisy Mix, test, Dialyzer, asset, or deployment output when exact raw output is not required.

## Pause And Ask

Ask before changing:

- Public APIs, context boundaries, module names, route paths, or externally visible behavior.
- Ecto schemas, migrations, indexes, constraints, repo configuration, or persisted data semantics.
- Authentication, authorization, tenant isolation, session handling, secret handling, or webhook verification.
- OTP supervision trees, GenServer state machines, process names, Registry usage, queues, or retry behavior.
- Dependencies, licenses, vendored code, generated artifacts, or lockfiles.
- CI/CD workflows, release configuration, deployment settings, observability, or production runtime config.
- Broad refactors, cross-context architecture changes, or unclear scope boundaries.

## Elixir Safety

- Prefer explicit pattern matching and typed return shapes such as `{:ok, value}` and `{:error, reason}`.
- Do not silently swallow errors. Match expected errors and preserve useful context.
- Avoid broad `rescue` blocks unless the boundary requires conversion to a controlled error.
- Do not call `String.to_atom/1` on user-controlled input. Use existing atoms, string keys, or safe mapping.
- Do not use list index access syntax; use pattern matching, `Enum.at/2`, or `List` functions.
- Do not use map access syntax on structs unless the struct implements Access. Use direct fields or domain APIs.
- For changesets, use `Ecto.Changeset.get_field/2` instead of treating the changeset like a map.
- Predicate function names should end in `?`; reserve `is_*` names for guards.
- Keep one top-level module per file unless the repository has a narrow local convention for internal helper modules.

## OTP And Concurrency

- Preserve supervision boundaries and restart semantics unless the task explicitly changes runtime architecture.
- Name OTP children, supervisors, registries, and processes intentionally; avoid accidental global names.
- Use `start_supervised!/1` in tests for supervised processes so cleanup is automatic.
- Avoid `Process.sleep/1` in tests. Prefer monitors, messages, `assert_receive`, or `_ = :sys.get_state(pid)` for synchronization.
- Use `Task.async_stream/3` for bounded concurrent enumeration when concurrency is needed.
- Do not introduce unbounded processes, queues, tasks, or retries without backpressure and failure behavior.
- Keep GenServer state explicit and small. Avoid using processes as hidden mutable global storage.

## Ecto And Persistence

- Generate migrations with `mix ecto.gen.migration descriptive_name` rather than handcrafting timestamps.
- Treat migrations, constraints, indexes, and data backfills as high-risk durable changes.
- Encode invariants in constraints or transactions when correctness depends on the database.
- Do not put server-controlled fields such as `user_id`, `account_id`, tenant IDs, or role flags in user-cast parameter lists.
- Preload associations that templates or serialization code will access.
- Keep query logic in the appropriate context or repository boundary; avoid leaking raw query details through presentation code.
- In `seeds.exs`, import or alias required query modules explicitly.

## Phoenix, HEEx, And LiveView

- Follow the Phoenix version and local generator conventions in the repository.
- Prefer existing CoreComponents and layout components before adding new component patterns.
- Use HEEx (`~H` or `.html.heex`) for templates; do not introduce legacy `~E`.
- Use `Phoenix.Component.to_form/2`, `<.form>`, and `<.input>` when those are the project convention.
- Add stable DOM IDs to forms, buttons, and interactive elements that tests or LiveView updates need to target.
- Use HEEx class list syntax for conditional classes.
- Use `<%= for ... do %>` for generated template content rather than `Enum.each`.
- Use LiveView streams for large or frequently updated collections when the project uses streams.
- Avoid LiveComponents unless they remove real complexity or match local architecture.
- Do not add inline scripts to templates. Use the existing asset pipeline and bundle entry points.

## Testing

- Inspect nearby tests, fixtures, factories, and support modules before adding new patterns.
- Prefer domain tests for business rules and invariants.
- Use integration tests for routes, controllers, LiveViews, jobs, webhooks, and external boundaries.
- Add regression tests for bug fixes when the failure can be reproduced deterministically.
- For background jobs, test enqueueing, execution, retries, and idempotency when behavior changes.
- For webhooks and external integrations, use realistic fixtures and local stubs/mocks. Do not hit live services in tests.
- Avoid brittle UI copy assertions when intent-based assertions or stable selectors are available.
- Do not delete or weaken tests to make a change pass unless explicitly requested.

## Dependencies

- Prefer Elixir/Erlang standard library and existing dependencies before adding new packages.
- Use `Req` when the repository already includes it for HTTP; do not add HTTP clients for convenience.
- Add dependencies only when they remove meaningful complexity, are maintained, and fit the repository's license and security policy.
- Check Hex package maintenance, transitive dependency impact, and vulnerability/audit status when adding dependencies.
- Do not change `mix.lock` unless dependency resolution is required by the task.

## Security

- Treat authentication, authorization, tenant isolation, session/cookie handling, CSRF, CSP, webhooks, file access, and secrets as high-risk.
- Validate and normalize untrusted input at Phoenix, API, webhook, CLI, and persistence boundaries.
- Verify webhook signatures before processing payloads.
- Do not log secrets, tokens, raw webhook secrets, magic links, private keys, session data, payment details, or license material.
- Use Sobelow, Semgrep, dependency audits, and repository-specific security scripts when configured.
- Preserve `config :logger, :filter_parameters` and equivalent filtering behavior.

## Quality Gates

- Run the repository's documented final quality gate before handoff when code changed.
- If no final gate exists, run formatting, compile, focused tests, and relevant static checks.
- Fix formatter, compiler warning, Credo, Sobelow, and audit failures in touched code.
- Do not add broad Credo disables. Prefer fixing the code or using the narrowest scoped disable with a reason.
- If a required check cannot run locally, state the exact command and blocker.

## Tooling

- Use `rg` for exact modules, functions, routes, config keys, migration names, errors, and test names.
- Use Expert or another Elixir LSP for definitions, references, diagnostics, hover, and rename safety when available.
- Use repo-configured code intelligence before editing shared contexts, public APIs, supervision trees, schemas, migrations, or cross-context interfaces.
- Use ast-grep or Semgrep for structural searches and mechanical rewrites.
- Use Semble for conceptual discovery when names are unclear, then verify with deterministic tools.
- Use RTK or equivalent output compression for noisy Mix, ExUnit, Dialyzer, asset, or deployment output when exact raw output is not required.
