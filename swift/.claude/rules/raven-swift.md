# Swift Rules

## Applicability

Use these rules for Swift, SwiftUI, SwiftData, WatchConnectivity, HealthKit, CloudKit, and XcodeGen-based Apple platform projects.

Project-specific `AGENTS.md`, nested `AGENTS.md`, and local docs override this file when they are more specific.

Use `.claude/docs/raven-swift-quality.md` for detailed Swift quality guidance when the task touches security, accessibility, localization, privacy, platform behavior, async/actor isolation, SwiftUI patterns, performance, or larger architecture decisions.

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
- Before changing high-risk data behavior: What happens to existing user data? Is a migration required?
- Optional capture fields should stay optional; do not block primary user workflows on secondary data.

## Privacy

- Prefer local-first and user-initiated data movement when the project has privacy constraints.
- Do not add analytics, telemetry, network calls, export surfaces, or HealthKit access without explicit project guidance.
- Do not log user-derived or linkable values. Treat names, UUIDs, CloudKit record names, and tokens as private.

## Async And Concurrency

- Treat strict concurrency warnings as correctness issues, not style issues.
- Do not pass SwiftData `@Model` objects or `ModelContext` across actor boundaries.
- Avoid `try!`, unjustified force unwraps, and broad concurrency workarounds.

## SwiftData

- Add, remove, rename, or change persisted fields only with migration and data-safety reasoning.
- Avoid reserved property names on `@Model` types: `isDeleted`, `modelContext`, `persistentModelID`, `hasChanges`.
- Keep `ModelContext` on the actor where it was created.

## SwiftUI

- Preserve existing navigation, state, and dependency-injection patterns.
- Keep view code focused on presentation. Move persistence, sync, and service logic into existing service layers.
- Prefer native controls, SF Symbols, and Apple platform conventions.

## Testing

- Prefer Swift Testing for new tests: `@Suite`, `@Test`, `#expect`, and `#require`.
- Maintain existing XCTest tests; do not add new XCTest unless the project requires it.
- Add regression tests for bug fixes when the failure can be reproduced deterministically.
- Do not delete or weaken tests to make a change pass unless explicitly requested.

## Performance And Benchmarks

- Profile with Instruments before optimizing; do not make performance claims from a single local run.

## Quality Gates

- Discover commands with the repository task runner first, such as `just --list`, before guessing.
- Run the narrowest relevant test or build first.
- Run the repository's final quality gate before handoff when code changed.
- Fix SwiftLint or formatting violations in files you touch.
- For docs-only changes, run the documented lightweight docs/link check if available.
- Treat warnings-as-errors projects accordingly; do not dismiss warnings as cosmetic.
