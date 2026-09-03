# Ruby Rules

## Applicability

Use these rules for Ruby scripts, libraries, gems, and general applications (CLI tools, Sinatra-style services, background workers). Rails-specific guidance (ActiveRecord, ActionController, asset pipeline) is out of scope for this template; layer Rails-specific project conventions on top when present.

Project-specific `AGENTS.md`, nested `AGENTS.md`, local docs, and existing task-runner commands override this file when they are more specific.

Use `.claude/docs/raven-ruby-quality.md` for detailed Ruby quality guidance when the task touches error design, gem architecture, metaprogramming, performance, security, or dependency policy.

## Setup And Commands

- Prefer the repository's task runner, such as `just`, `rake`, or project scripts, before inventing raw commands.
- Use `bundle exec` to run gem executables against the project's locked versions; do not assume a bare binary on PATH matches `Gemfile.lock`.
- Do not assume every project uses RuboCop, Minitest, or Bundler. Use them when configured or clearly appropriate; RSpec is a common alternative to Minitest.

## Additional Pause And Ask Triggers

In addition to the guardrails in AGENTS.md, ask before changing:

- Ruby version targets or compatibility. Ruby 3.2 reached end-of-life on 2026-03-31 (no further security patches) and 3.3 is now security-only maintenance -- flag it if a task assumes 3.2 as a supported floor.
- Monkey-patching or reopening core classes (`String`, `Array`, `Object`, etc.) and other metaprogramming that changes behavior repo-wide.
- Native C extensions or FFI bindings, where behavior depends on the compiled extension rather than the Ruby source alone.

## Ruby Safety

- Never call `eval`, `instance_eval`, `class_eval`, `send`, `public_send`, or `const_get` with untrusted or user-controlled input.
- Avoid string-built shell commands with backticks, `system`, `exec`, or `Kernel#open` with unsanitized input; prefer `Process.spawn`/`Open3` with an argv array over shell interpolation.
- Add `# frozen_string_literal: true` to new files in codebases that already use it; do not mutate frozen strings.
- Avoid reopening or monkey-patching core classes; prefer refinements or explicit wrapper objects when extension is genuinely needed.
- Treat `nil` deliberately: use `&.`, `Array#compact`, or explicit checks rather than relying on `NoMethodError` as control flow.

## Error Handling

- Rescue specific `StandardError` subclasses; avoid bare `rescue` and never rescue `Exception` except at a process-level top boundary.
- Do not swallow exceptions silently. Log or re-raise at minimum.
- Preserve exception context when re-raising: `raise NewError, message, cause: original_error` (or a plain `raise NewError` inside a `rescue` block, which sets `cause` automatically).
- Use `ensure` for cleanup that must run regardless of success or failure; prefer block-based resource APIs (`File.open(...) { |f| ... }`) over manual `ensure`-based closing.

## Architecture

- Keep pure business logic separate from I/O, network calls, time, randomness, and framework integration (service objects/POROs over fat models).
- Preserve existing module and gem boundaries unless the task is explicitly architectural.
- Prefer dependency injection (constructor arguments) over reaching for singletons or global state in business logic.
- Do not create circular `require`/`require_relative` dependencies between sibling files.

## Testing

- Inspect nearby tests and fixtures before adding new patterns.
- Prefer `Minitest::Test` (or the project's existing framework, e.g. RSpec) -- do not introduce a second test framework into a project that already picked one.
- Add regression tests for bug fixes when the failure can be reproduced deterministically.
- Do not delete or weaken tests to make a change pass unless explicitly requested.
- Avoid brittle sleeps, timing assumptions, and oversized fixtures unless the codebase already relies on them.

## Dependencies

- Check license compatibility and maintenance status for new gems before adding them to the `Gemfile`.
- Do not change `Gemfile.lock` unless dependency resolution is required by the task.
- Run `just audit` (osv-scanner) before shipping dependency changes to check for known-vulnerable gem versions.

## Quality Gates

- The pre-commit and pre-push hooks Raven installs run the formatter, linter, type check, and test suite. Do not run them by hand before committing; run the narrowest test for the change and let the hooks own the rest.
- Fix a gate failure the hook reports in touched code rather than suppressing it.
- Do not add broad `# rubocop:disable` comments spanning a whole file. Prefer fixing the code or the narrowest scoped inline disable with a reason.
