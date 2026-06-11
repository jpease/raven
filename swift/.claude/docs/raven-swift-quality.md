# Swift Quality Reference

Use this reference for Swift, SwiftUI, SwiftData, and Apple-platform implementation work when the task touches architecture, security, accessibility, localization, persistence, sync, or user-facing behavior.

For language-neutral guidance such as clarity over cleverness, dependency restraint, comments, and maintainability, use `.claude/docs/raven-coding-principles.md`.

For changes that touch security-sensitive boundaries, run the `raven-security-review` skill before shipping.

## Public Contracts

- Treat public functions, types, protocols, and module interfaces as compatibility surfaces.
- Before changing a public API, identify callers, tests, docs, and downstream dependencies.
- Prefer additive changes when compatibility matters. Mark deprecated APIs with `@available(*, deprecated, renamed:)` before removal.
- Update documentation comments and examples when public behavior changes.
- Use `public` and `internal` access modifiers deliberately; default to the narrowest access that satisfies the design.

## Architecture

- Keep business logic separate from UI rendering, persistence, network calls, and platform APIs.
- Prefer value types (`struct`, `enum`) for domain data and state transfer where mutation is not required.
- Use protocols and dependency injection to keep business logic testable without real infrastructure.
- Keep SwiftUI views focused on presentation. Move persistence, sync, and service logic into dedicated service or model layers.
- Validate input at the boundary — network responses, file contents, user input, CloudKit records. Pass typed domain values internally.
- Avoid global mutable state. Prefer passing dependencies explicitly or through the SwiftUI environment.

## Error Design

- Use typed errors (`Error`-conforming enums) for library and service boundaries so callers can handle specific failure modes.
- Do not use `try!` or `try?` in contexts where silent failure or a crash would be worse than explicit handling.
- Propagate errors with `throws` rather than returning sentinel values or optional results where the failure reason matters.
- For recoverable failures, consider `Result<Success, Failure>` when the caller needs to handle the error asynchronously or pass it across boundaries without rethrowing.
- Preserve error context. Do not replace specific errors with generic strings.

## Async And Concurrency

- Prefer structured concurrency (`async`/`await`, `async let`, `TaskGroup`) over callbacks and completion handlers.
- Keep UI-bound state and view-facing work on `@MainActor`. Annotate explicitly rather than relying on implicit dispatch.
- Do not pass `@Model` objects or `ModelContext` across actor boundaries in SwiftData. Use Sendable value types or DTOs for cross-actor communication.
- Treat Swift 6 strict concurrency warnings as correctness issues, not style warnings.
- Avoid `Task.detached` unless the work must outlive the current scope and you have accounted for cancellation and ownership.
- Prefer `async`/`await` over `DispatchQueue` for new code. Only reach for `DispatchQueue` when interoperating with Objective-C APIs or existing callback-based code.

## Testing Strategy

- Prefer Swift Testing (`@Suite`, `@Test`, `#expect`, `#require`) for new test code.
- Maintain existing XCTest coverage; do not migrate it unless the project requires it.
- Test public behavior, not implementation details.
- For SwiftData tests, use isolated stores per the project convention. Prefer unique temp SQLite stores over shared in-memory state when concurrent persistence tests are flaky.
- Cover backup/import, CloudKit, and sync round-trips when changing persisted fields that participate in those flows.
- Add a regression test for every bug fix when the failure can be reproduced deterministically.
- Do not delete or weaken tests to make a change pass unless explicitly requested.

## Dependency And License Hygiene

- Prefer native Apple frameworks and the standard library before adding dependencies.
- Before adding a Swift package, check maintenance status, license compatibility, security posture, and whether the project already has an approved alternative.
- Do not copy or translate code from sources with incompatible licenses.
- Keep `Package.resolved` or `Podfile.lock` committed so dependency versions are reproducible.
- Review transitive dependencies when adding packages; surface license or security concerns before committing.

## Performance And Benchmarks

- Prefer simple code until measurement shows a problem. Use Instruments or `swift-metrics` to confirm before broad optimization.
- Keep SwiftUI views simple enough to render predictably; split large views when state, layout, or conditional logic becomes hard to scan.
- Prefer value types for data transfer and immutable state; they avoid unexpected sharing.
- Avoid unnecessary work on the main thread. Move computation off `@MainActor` where practical.
- Do not make performance claims from a single local run. Record the device, OS version, dataset, and conditions for any benchmark comparison.

## Security

- Store sensitive local secrets in Keychain Services.
- Use file protection (`NSFileProtectionComplete` or equivalent) for sensitive local files when appropriate.
- Use environment-aware configuration through `.xcconfig`, build settings, or plist values. Do not hardcode secrets.
- Use `weak` or `unowned` references in closures and delegate patterns when needed to avoid retain cycles.
- Treat compiler warnings and strict concurrency warnings as correctness issues.

## Platform Alignment

- Prefer native Apple frameworks and system controls before adding dependencies.
- Follow Apple's Human Interface Guidelines for interaction patterns and platform conventions.
- Use SF Symbols where they fit the UI.
- Support Dark Mode and Dynamic Type unless the project explicitly scopes them out.
- Account for right-to-left layout when building reusable UI or user-facing flows.

## Accessibility

- Add labels, hints, traits, and values for interactive controls where the default accessibility output is insufficient.
- Ensure color choices have adequate contrast and do not carry meaning alone.
- Check text scaling and truncation for important UI.
- Use VoiceOver or Accessibility Inspector for meaningful accessibility changes when feasible.

## Localization

- Keep user-facing strings localizable from the start when the project supports localization.
- Use locale-aware formatting for dates, times, numbers, measurements, and lists.
- Avoid layout assumptions that break with longer localized strings or right-to-left languages.

## Privacy

- Default to local-first behavior when the product has a privacy promise.
- Make export, HealthKit, analytics, telemetry, and network behavior explicit and user-controlled.
- Keep HealthKit access optional, granular, and revocable.
- Avoid logging user-derived or linkable values publicly.
