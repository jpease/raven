# Ruby Quality Reference

Deeper guidance for Ruby architecture, security, and quality decisions. Load this
when the task touches error design, metaprogramming, object design, performance,
security, or dependency policy -- not for routine edits already covered by
`raven-ruby.md`.

## Version Compatibility

- Ruby 3.2 reached end-of-life on 2026-03-31 (no future security patches).
  Ruby 3.3 is in security-only maintenance; Ruby 3.4+ receives full support.
  Treat 3.3 as the practical floor for new code unless the repo has a
  documented reason to support an EOL interpreter.
- Ractor, Fiber Scheduler, and YJIT behavior can differ across 3.x minor
  versions; check `RUBY_VERSION`/`.ruby-version` before relying on a specific
  minor version's semantics.
- Pattern matching (`case/in`), endless methods (`def square(x) = x * x`), and
  Hash shorthand (`{x:, y:}`) require Ruby 3.1+; do not use them in a codebase
  that documents an earlier floor.

## Error Design

- Define a small hierarchy of custom exceptions per domain (e.g. `class
  PaymentError < StandardError`) rather than raising bare `StandardError` or
  `RuntimeError`, so callers can rescue precisely.
- Prefer returning a `Result`-like object (`[:ok, value]` / `[:error, reason]`,
  or a small value object) at internal API boundaries where "the caller
  should branch on outcome" is expected behavior, not an exceptional path.
  Reserve exceptions for genuinely exceptional conditions.
- Use `raise NewError, "context", cause: original` (or a plain `raise` inside
  `rescue`) to preserve the original backtrace and message when translating
  a lower-level error into a domain error.

## Metaprogramming And Core Classes

- Prefer `define_method`, `method_missing` + `respond_to_missing?`, and
  modules/`Comparable`/`Enumerable` mixins over ad hoc monkey-patching.
- Never reopen core classes (`String`, `Array`, `Hash`, `Object`) in library
  code -- it is a global, load-order-dependent side effect that breaks other
  code sharing the process. Use refinements (`refine`/`using`) when the
  behavior genuinely needs to be scoped, or a wrapper/decorator object
  otherwise.
- If `method_missing` is used, always implement `respond_to_missing?`
  alongside it -- omitting it breaks `respond_to?`, `method()`, and
  duck-typing checks that other code relies on.
- Never call `eval`, `instance_eval`, `class_eval`, `send`, `public_send`, or
  `const_get` with untrusted input -- each is a code-execution or
  arbitrary-object-construction primitive.

## Object Design

- Favor plain Ruby objects (POROs) and service objects over god classes;
  a class with more than one reason to change should usually split.
- Use `Struct`/`Data.define` (Ruby 3.2+) for small immutable value objects
  instead of hand-rolled attr_accessor classes with no behavior.
- Keep constructors cheap and side-effect-free; do I/O in explicit methods,
  not in `initialize`.
- Prefer keyword arguments for methods with more than one or two parameters,
  especially booleans -- `discount(order, apply_tax: true)` reads better and
  is harder to misuse than positional booleans.

## Performance

- Profile before optimizing (`ruby-prof`, `stackprof`, or `Benchmark`); do
  not make performance claims from a single local run.
- Avoid `String#+=` / repeated concatenation in loops; use `String#<<` or
  build an array and `Array#join`.
- Freeze literals and constants (`# frozen_string_literal: true`, or
  `.freeze` on constants) to avoid needless allocation and let YJIT optimize
  more aggressively.
- Reuse `Regexp` literals (they are already memoized by Ruby when written as
  literals, unlike `Regexp.new` inside a hot loop).
- CPU-bound work does not parallelize across threads due to the GVL (Global
  VM Lock); reach for `Process.fork`, external workers, or a C
  extension/Ractor when true parallelism is required.

## Security

- Never call `eval`/`send`/`system`/backtick shell execution with
  user-controlled input; prefer `Process.spawn`/`Open3.capture2` with an
  argv array over shell string interpolation.
- Use `Marshal.load` only on trusted, process-internal data -- it can
  instantiate arbitrary objects and execute code via crafted payloads on
  untrusted input. Prefer JSON for untrusted serialization.
- Avoid `YAML.load` on untrusted input; use `YAML.safe_load` (or
  `Psych.safe_load`) with an explicit `permitted_classes` list.
- Validate and allowlist file paths built from user input before passing
  them to `File`/`Dir` APIs to avoid path traversal.

## Testing

- Prefer Minitest's `assert_*` family for behavior assertions; use
  `Minitest::Mock` or a lightweight test double over heavy mocking of
  internals.
- Use `setup`/`teardown` (or RSpec's `before`/`after` if the project uses
  RSpec) for shared fixtures rather than duplicating setup per test.
- Add a regression test for every bug fix when the failure can be reproduced
  deterministically.
- Avoid `sleep`-based waits in tests; prefer polling with a timeout or
  synchronous test doubles for async code.

## Linting And Formatting

- RuboCop covers both lint and formatting in one pass (there is no separate
  mainstream Ruby formatter the way Python/Go/JS split these concerns) -- a
  single `bundle exec rubocop` run checks both.
- Use `bundle exec rubocop -A` to auto-correct safe offenses; review the diff
  before committing, since some auto-corrections change behavior (e.g.
  frozen-string-literal insertion).
- Scope `# rubocop:disable` comments to the narrowest range (a single line or
  block) with a reason; never disable a cop file-wide without justification
  in `.rubocop.yml`'s `Exclude`/`inherit_mode` sections instead.

## Dependencies

- Check license compatibility (`bundle exec license_finder` if configured)
  and maintenance status (last release date, open security advisories)
  before adding a gem to the `Gemfile`.
- Pin dependency versions in `Gemfile.lock`; do not hand-edit the lockfile.
- Run `just audit` (osv-scanner against `Gemfile.lock`) before shipping
  dependency changes; classify any findings per the `raven-dependency-update`
  skill rather than treating the audit as a blocking gate.
