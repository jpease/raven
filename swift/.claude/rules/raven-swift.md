# Swift Rules

## Applicability

Use these rules for Swift, SwiftUI, SwiftData, WatchConnectivity, HealthKit, CloudKit, and XcodeGen-based Apple platform projects.

Project-specific `AGENTS.md`, nested `AGENTS.md`, and local docs override this file when they are more specific.

Use `.claude/docs/raven-swift-quality.md` for detailed Swift quality guidance when the task touches security, accessibility, localization, privacy, platform behavior, or larger architecture decisions.

## Setup And Commands

- If the project uses XcodeGen, treat `project.yml` as the source of truth for project structure.
- Do not edit `project.pbxproj` by hand when a generator owns it.
- Run the project generation command after changing targets, build settings, capabilities, entitlements, dependencies, deployment targets, or Swift version.
- Adding `.swift` files to existing synchronized source folders usually should not require project regeneration.
- Prefer the repository's task runner, such as `just`, `make`, or scripts, over raw `xcodebuild` when it defines the expected workflow.

## Pause And Ask

In addition to the guardrails in AGENTS.md, ask before changing:

- SwiftData schema, model fields, relationships, delete rules, or migrations.
- CloudKit, WatchConnectivity, sync, de-duplication, or conflict-resolution behavior.
- HealthKit permissions, read/write scope, export behavior, or privacy posture.
- Entitlements, signing, capabilities, bundle identifiers, or deployment targets.

## Data Safety

- Treat persistence, migrations, import/export, sync, and delete/cascade behavior as high risk.
- Before changing high-risk data behavior, answer:
  - What happens to existing user data?
  - Is a migration required?
  - Could records be corrupted, orphaned, duplicated, or lost?
- Derived data should usually be computed, not stored, unless the project explicitly documents otherwise.
- Optional capture fields should stay optional; do not block primary user workflows on secondary data.

## Privacy

- Prefer local-first and user-initiated data movement when the project has privacy constraints.
- Do not add analytics, telemetry, network calls, export surfaces, or HealthKit access without explicit project guidance.
- Do not log user-derived or linkable values as public. Treat names, UUIDs, URLs, CloudKit record names, tokens, and detailed error descriptions as private unless the project says otherwise.
- Keep HealthKit access optional, granular, and revocable unless the product contract says otherwise.

## Async And Concurrency

- Treat strict concurrency warnings as correctness issues, not style issues.
- Do not pass SwiftData `@Model` objects or `ModelContext` across actor boundaries.
- Use `Sendable` DTOs or immutable value types for cross-actor communication.
- Keep UI-bound state and view-facing behavior on `@MainActor` when appropriate.
- Avoid `try!`, unjustified force unwraps, and broad concurrency workarounds.
- Prefer fixing actor isolation and ownership boundaries over adding deferred imports or unsafe annotations.

## SwiftData

- Add, remove, rename, or change persisted fields only with migration and data-safety reasoning.
- Avoid reserved or framework-conflicting property names on `@Model` types, such as `isDeleted`, `modelContext`, `persistentModelID`, and `hasChanges`.
- Use an app-specific soft-delete field name, such as `isSoftDeleted`, when soft deletion is needed.
- Query by stable identifier fields, such as UUIDs, when relationship traversal is brittle or inefficient.
- For junction tables, prefer explicit identifier fields plus relationships where the project pattern requires both.
- Keep `ModelContext` on the actor where it was created.

## SwiftUI

- Preserve existing navigation, state, and dependency-injection patterns.
- Use `@Observable`, `@State`, `@Binding`, environment values, and actors consistently with nearby code.
- Keep view code focused on presentation. Move persistence, sync, and service logic into existing service layers.
- Verify meaningful UI behavior in a simulator when the change affects navigation, forms, gestures, watch flows, or visual state.
- Support Dark Mode, Dynamic Type, and accessibility semantics in user-facing UI unless the project explicitly scopes them out.
- Prefer native controls, SF Symbols, and Apple platform conventions before adding custom UI machinery or dependencies.

## Accessibility And Localization

- Add accessibility labels, hints, traits, and values when default semantics are insufficient.
- Do not rely on color alone to communicate state.
- Keep user-facing text localizable when the project supports localization.
- Use locale-aware formatting for dates, times, numbers, measurements, and lists.
- Avoid layout assumptions that break with longer localized strings or right-to-left languages.

## Testing

- Prefer Swift Testing for new tests: `@Suite`, `@Test`, `#expect`, and `#require`.
- Maintain existing XCTest tests, but do not add new XCTest coverage unless the project requires it.
- Use the project's test infrastructure and task runner before inventing new test setup.
- For SwiftData tests, use isolated stores according to project convention. If concurrent persistence tests are flaky, prefer unique temp SQLite stores over shared in-memory state.
- If a test creates a `@ModelActor`, disable autosave when the project test infrastructure requires it.
- Cover backup/import, CloudKit, or sync round-trips when changing persisted fields that participate in those flows.
- If simulator or device availability prevents verification, state exactly what could not be run.

## Performance And Benchmarks

- Profile with Instruments (Time Profiler, Allocations) before optimizing; do not guess from code inspection alone.
- Large value types with many fields or nested collections can have unexpected copy costs; measure before assuming they are cheap.
- Keep `@Observable` property granular in SwiftUI — unnecessarily broad invalidation increases render work.
- State device model, OS version, and build configuration (debug vs release) when reporting performance results.

## Quality Gates

- Discover commands with the repository task runner first, such as `just --list`, before guessing.
- Run the narrowest relevant test or build first.
- Run the repository's final quality gate before handoff when code changed.
- Fix SwiftLint or formatting violations in files you touch.
- For docs-only changes, run the documented lightweight docs/link check if available.
- Treat warnings-as-errors projects accordingly; do not dismiss warnings as cosmetic.
