# Swift template: support Xcode app targets, not just SwiftPM (#60)

**Date:** 2026-07-01
**Status:** Approved (design)
**Issue:** #60 — swift template assumes SwiftPM; breaks iOS/xcodebuild app projects
**Scope:** `swift/justfile`, `swift/README.md`, `scripts/raven_lib/data/gate_data.py`, tests

## Problem

The `swift` template's `build`/`test` recipes are SwiftPM-only (`swift build`, `swift test`) and its `check` gate runs `swift build`/`swift test`. Neither works for an Xcode **app** target, which builds with `xcodebuild -scheme <S> -destination <D>`. All three real iOS repos dogfooded (regularity, fieldjoy, and the #60 reporter) had to hand-rewrite these recipes. Additionally `gate_data`'s `detect_signals: ["Package.swift"]` makes `raven assess` warn "no language signal" for iOS apps (no `Package.swift`), even though they are valid Swift projects.

## Decision

Keep a **single** `swift` template and make it serve both SwiftPM packages and Xcode app targets by **auto-dispatching** on `Package.swift` presence. Rejected a separate `swift-app` template because raven only resolves `common/`-pointing symlinks on install (`template.py:should_preserve_symlink`), so a variant would have to duplicate ~6 swift-specific real files (`raven-swift.md`, `raven-swift-quality.md`, `.swiftlint.yml`, `.swift-format`, `.codex/config.toml`, `.mcp.json`) and keep them in sync forever.

## Design

### `swift/justfile`

Add two placeholder variables and dispatch `build`/`test`:

```just
# Xcode app targets only (ignored for SwiftPM packages). Set SCHEME to your
# Xcode scheme — for xcodegen projects this is the `name:` in project.yml.
SCHEME := "YourScheme"
DESTINATION := "platform=iOS Simulator,name=iPhone 16"

# Build: SwiftPM package -> swift build; Xcode app -> xcodebuild.
build:
    #!/usr/bin/env sh
    if [ -f Package.swift ]; then
        swift build
    else
        xcodebuild -scheme "{{SCHEME}}" build -destination "{{DESTINATION}}"
    fi

# Test: SwiftPM package -> swift test; Xcode app -> xcodebuild test.
test:
    #!/usr/bin/env sh
    if [ -f Package.swift ]; then
        swift test
    else
        xcodebuild -scheme "{{SCHEME}}" test -destination "{{DESTINATION}}"
    fi

check-fast: lint-format lint
check: check-fast build     # build verifies compile; test is on-demand / CI
```

- `lint-format`, `lint`, `format`, `install-hooks` are unchanged.
- **`check` drops `test`** (was `check-fast build test`). Rationale: for an app, `xcodebuild test` boots a simulator and runs the full XCUITest suite — too heavy for every push (both iOS repos removed it). `build` still catches compile breaks. A comment notes SwiftPM projects can add `test` back if they want push-time tests.
- The `Package.swift` check routes **every** non-package project (xcodegen or plain `.xcodeproj`) to xcodebuild — more robust than detecting `project.yml`.

### `gate_data.py` (swift entry)

Only change: `detect_signals: ["Package.swift", "project.yml"]` (add `project.yml`). This makes xcodegen app projects register as a template fit, so `assess` stops the false "no language signal" warning. `recipes`, `tools`, and `fallback_commands` are unchanged — the `swift build`/`swift test` fallbacks remain the best-effort for a SwiftPM repo without `just`; app projects rely on `just` (the dispatch).

### `swift/README.md`

Update the gate description: `check` now runs `lint-format`, `lint`, and build (not test); note the SwiftPM-vs-Xcode-app dispatch and the `SCHEME`/`DESTINATION` vars.

## Behavior changes / compatibility

- **SwiftPM adopters:** `just check` no longer runs `swift test` at pre-push (build still runs). Documented; re-adding `test` to `check` is a one-word edit. This is the only behavior change for existing swift users.
- **Xcode app adopters:** `build`/`test` now work after setting `SCHEME` (previously silently broken). `assess` recognizes the project via `project.yml`.
- SwiftPM users see two inert, commented `SCHEME`/`DESTINATION` vars.

## Testing

- `swift/justfile`: `build` and `test` each contain the `Package.swift` guard plus both `swift build`/`swift test` and `xcodebuild` branches; `check` recipe is `check-fast build` (asserts `test` is not in `check`).
- `gate_data`: `gate_spec_for("swift").detect_signals` contains both `Package.swift` and `project.yml`.
- `assess` fit: a repo with `project.yml` (no `Package.swift`) configured as `swift` yields an OK `assess.fit.signal` finding (not the WARN "no language signal").
- Existing swift gate/assess/template tests continue to pass.

## Out of scope

- Auto-deriving `SCHEME` from `project.yml` (placeholder chosen; no yq dependency).
- The broader "assess only recognizes canonical `just check`" gap (#59).
