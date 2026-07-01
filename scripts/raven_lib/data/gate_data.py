"""Per-language gate expectations consumed by ``raven assess``.

Each entry in ``GATE_DATA`` declares the justfile recipes, gate tool ids,
tool-config signals, language-detection signals, and non-just fallback commands
for one template. Keep recipe names in sync with ``<template>/justfile``.

This is plain Python data on purpose: Raven's runtime is stdlib-only and must
import on Python 3.9+, so it cannot use ``tomllib`` (3.11+) to read a TOML file.
A literal dict needs no parser, keeps these explanatory comments, and works on
every supported interpreter.

Field shapes (consumed by ``raven_lib.gates._build_spec``):
  recipes:         list[str]
  tools:           list[str]
  detect_signals:  list[str]
  config_signals:  list[[file, required_substring]]; substring "" means
                   "file must merely exist"
  fallback_commands: dict[recipe, list[str]] -- the non-just command to run
"""

from __future__ import annotations

GATE_DATA: dict[str, dict[str, object]] = {
    "python": {
        "recipes": ["lint", "format", "typecheck", "test"],
        "tools": ["ruff", "pyright"],
        "detect_signals": ["pyproject.toml", "setup.py", "setup.cfg"],
        "config_signals": [["pyproject.toml", "[tool.ruff]"]],
        "fallback_commands": {
            "lint": ["ruff", "check", "."],
            "format": ["ruff", "format", "--check", "."],
            "typecheck": ["pyright"],
            "test": ["python", "-m", "pytest"],
        },
    },
    "go": {
        "recipes": ["fmt-check", "vet", "lint", "test"],
        "tools": ["golangci-lint", "gofmt"],
        "detect_signals": ["go.mod", "go.sum"],
        "config_signals": [["go.mod", ""]],
        "fallback_commands": {
            "fmt-check": ["gofmt", "-l", "."],
            "vet": ["go", "vet", "./..."],
            "lint": ["golangci-lint", "run"],
            "test": ["go", "test", "./..."],
        },
    },
    "rust": {
        "recipes": ["lint", "typecheck", "test"],
        "tools": ["cargo"],
        "detect_signals": ["Cargo.toml", "Cargo.lock"],
        "config_signals": [["Cargo.toml", ""]],
        "fallback_commands": {
            "lint": ["cargo", "clippy", "--", "-D", "warnings"],
            "typecheck": ["cargo", "check"],
            "test": ["cargo", "test"],
        },
    },
    "typescript": {
        "recipes": ["lint", "typecheck", "test"],
        "tools": ["npx"],
        "detect_signals": ["package.json", "tsconfig.json"],
        "config_signals": [["tsconfig.json", ""]],
        "fallback_commands": {
            "lint": ["npx", "eslint", "."],
            "typecheck": ["npx", "tsc", "--noEmit"],
            "test": ["npx", "vitest", "run"],
        },
    },
    "swift": {
        # `check-fast` runs `lint-format` then `lint`; `check` adds `build`/`test`.
        # `lint-format` (Apple swift-format in lint mode) is part of standard
        # verification, so assess must require it like any other gate recipe.
        "recipes": ["lint-format", "lint", "build", "test"],
        # swift-format ships inside the Xcode toolchain and is invoked as
        # `xcrun swift-format`, not a standalone PATH binary, so the probeable
        # executable for the format gate is `xcrun` rather than `swift-format`.
        "tools": ["swift", "swiftlint", "xcrun"],
        # SwiftPM packages have Package.swift; Xcode app targets (xcodegen) have
        # project.yml. The justfile dispatches build/test between the two.
        "detect_signals": ["Package.swift", "project.yml"],
        # The tool config is the linter config the template installs -- present in
        # both SwiftPM and Xcode-app repos -- not Package.swift (absent in apps).
        "config_signals": [[".swiftlint.yml", ""]],
        "fallback_commands": {
            # No-pipe equivalent of the justfile's `git ls-files | xargs ... lint`:
            # the runner has no shell, so lint the tree recursively instead.
            "lint-format": ["xcrun", "swift-format", "lint", "--recursive", "--strict", "."],
            "lint": ["swiftlint", "lint"],
            "build": ["swift", "build"],
            "test": ["swift", "test"],
        },
    },
    "elixir": {
        "recipes": ["lint", "typecheck", "test"],
        "tools": ["mix"],
        "detect_signals": ["mix.exs"],
        "config_signals": [["mix.exs", ""]],
        "fallback_commands": {
            "lint": ["mix", "credo"],
            "typecheck": ["mix", "dialyzer"],
            "test": ["mix", "test"],
        },
    },
    "lua": {
        "recipes": ["fmt-check", "lint", "test"],
        "tools": ["luacheck", "stylua", "busted"],
        "detect_signals": [".luacheckrc", ".busted"],
        "config_signals": [[".luacheckrc", ""]],
        "fallback_commands": {
            "fmt-check": ["stylua", "--check", "."],
            "lint": ["luacheck", "."],
            "test": ["busted"],
        },
    },
}
