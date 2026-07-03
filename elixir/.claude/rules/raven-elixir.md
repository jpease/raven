# Elixir Rules

## Applicability

Use these rules for Elixir applications, Phoenix projects, Mix libraries, OTP services, LiveView applications, Ecto-backed systems, and Oban-style background jobs.

Project-specific `AGENTS.md`, nested `AGENTS.md`, local docs, and existing task-runner commands override this file when they are more specific.

Use `.claude/docs/raven-elixir-quality.md` for detailed Elixir quality guidance when the task touches OTP supervision, Ecto migrations and data safety, Phoenix/LiveView behavior, security, deployment, testing strategy, dependency and license hygiene, or larger architecture decisions.

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

## Pause And Ask

In addition to the guardrails in AGENTS.md, ask before changing:

- Ecto schemas, migrations, indexes, constraints, repo configuration, or persisted data semantics.
- OTP supervision trees, GenServer state machines, process names, Registry usage, queues, or retry behavior.
- CI/CD workflows, release configuration, deployment settings, observability, or production runtime config.

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
- Use `start_supervised!/1` in tests for supervised processes so cleanup is automatic.
- Avoid `Process.sleep/1` in tests; prefer monitors, messages, or `assert_receive`.
- Do not introduce unbounded processes, queues, tasks, or retries without backpressure.

## Ecto And Persistence

- Treat migrations, constraints, indexes, and data backfills as high-risk durable changes.
- Do not put server-controlled fields such as `user_id`, `account_id`, or role flags in user-cast parameter lists.
- Keep query logic in the appropriate context or repository boundary.

## Phoenix, HEEx, And LiveView

- Use HEEx (`~H` or `.html.heex`) for templates; do not introduce legacy `~E`.
- Add stable DOM IDs to forms, buttons, and interactive elements that tests or LiveView updates need.
- Do not add inline scripts to templates.

## Testing

- Inspect nearby tests, fixtures, factories, and support modules before adding new patterns.
- Prefer domain tests for business rules; integration tests for routes, jobs, webhooks, and external boundaries.
- Add regression tests for bug fixes when the failure can be reproduced deterministically.
- Do not delete or weaken tests to make a change pass unless explicitly requested.

## Dependencies

- Do not change `mix.lock` unless dependency resolution is required by the task.

## Security

- Treat authentication, authorization, tenant isolation, session handling, CSRF, webhooks, and secrets as high-risk.
- Verify webhook signatures before processing payloads.
- Do not log secrets, tokens, magic links, private keys, or payment details.
- Preserve `config :logger, :filter_parameters` and equivalent filtering behavior.

## Quality Gates

- Run the repository's documented final quality gate before handoff when code changed.
- If no final gate exists, run formatting, compile, focused tests, and relevant static checks.
- Fix formatter, compiler warning, Credo, Sobelow, and audit failures in touched code.
- Do not add broad Credo disables. Prefer fixing the code or using the narrowest scoped disable with a reason.
- If a required check cannot run locally, state the exact command and blocker.

## Tooling

- Use Expert or another Elixir LSP for definitions, references, diagnostics, hover, and rename safety when available.
- Use `mix deps.tree` for dependency graph questions.
