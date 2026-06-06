# Raven CLI Redesign: Subcommand Interface

**Date:** 2026-05-21
**Status:** Approved

## Summary

Rename `scripts/apply-template.py` to `scripts/raven.py` and replace the flag-based interface (`--dry-run` / `--apply`) with an explicit subcommand interface: `init`, `install`, and `upgrade`. Add interactive language selection when language is not provided and config does not yet exist.

## Motivation

The current script requires understanding `--dry-run` vs `--apply` flags and creates `.raven/config.toml` silently as a side effect of `--apply`. The new interface makes intent explicit, separates first-time setup from ongoing upgrades, and guides new users through language selection interactively.

## CLI Structure

```
raven init [language]
raven install [language] [overrides...] [--dry-run] [--include-readme]
raven upgrade [overrides...] [--dry-run] [--include-readme]
```

### `raven init [language]`

Creates `.raven/config.toml`. Does not install any files.

1. Check if config already exists. If yes, exit with error: "config already exists at `.raven/config.toml`; run `raven upgrade` to update managed files."
2. If language is omitted, present an interactive numbered menu of available language templates (derived from language directories in the Raven repo). Wait for selection.
3. Write config with the selected or provided language.

### `raven install [language] [overrides...]`

Copies new Raven files and upgrades managed files. Entry point for first-time setup.

1. Check config existence.
   - If config is absent and a language argument was provided: run `init <language>`, then proceed.
   - If config is absent and no language argument: present interactive language selection, run `init <language>`, then proceed.
   - If config is present: use it; ignore any language argument.
2. Copy new files (`will_copy`) and upgrade unchanged managed files (`will_upgrade`).
3. Write/update `.raven/manifest.json`.

### `raven upgrade [overrides...]`

Updates an existing Raven installation after pulling new Raven changes. Mechanically identical to `install` once config exists — copies new files and upgrades managed files.

1. Require config. If absent, exit with error: "no `.raven/config.toml` found; run `raven install <language>` to set up Raven first."
2. Copy new files (`will_copy`) and upgrade unchanged managed files (`will_upgrade`).
3. Update `.raven/manifest.json`.

### Shared behavior

- `--dry-run` on `install` and `upgrade`: previews changes without writing anything. Output format unchanged from today.
- `--include-readme`: carries over from current implementation.
- Override positional args: template-relative paths to force-overwrite even if locally modified. Follow the optional language arg: `raven install .claude/scripts/raven-tool-check.py` (uses config language, overrides that path).
- All state checks (config presence, valid language) happen before any interactive prompts or file writes.

## Interactive Language Selection

When language selection is needed:

- Enumerate subdirectory names in the Raven repo root that are valid language templates (same logic as current `template.is_dir()` check).
- Present as a numbered list on stdout.
- Prompt with `input()`. No external dependencies.
- Validate the selection; re-prompt on invalid input.
- If stdin is not a TTY (non-interactive context), exit with error: "language required; pass it as an argument (e.g. `raven install python`)."

## Collateral Changes

- `scripts/apply-template.py` → `scripts/raven.py`
- `tests/test_apply_template.py` → `tests/test_raven.py`; update `importlib` load path and module alias (`apply_template` → `raven`). All test logic for internal functions (`classify`, `copy_paths`, etc.) is unchanged.
- `README.md`: update all command examples to use `raven.py` and new subcommand syntax.

## What Does Not Change

- Internal functions: `classify`, `copy_paths`, `iter_template_entries`, `load_config`, `load_manifest`, `save_manifest`, etc. are unchanged.
- The manifest format and config format are unchanged.
- Dry-run output format is unchanged.
- The `--include-readme` flag behavior is unchanged.
