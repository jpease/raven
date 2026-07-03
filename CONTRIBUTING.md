# Contributing to Raven

Thank you for your interest in contributing.

## Getting Started

```sh
git clone https://github.com/jpease/raven
cd raven
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt   # if present, otherwise no extra deps needed
```

Run the test suite:

```sh
python -m pytest
```

## Development Workflow

Raven uses itself as a live testbed. After changing template files or `scripts/raven.py`:

```sh
python scripts/self-check.py
```

This validates the installed shape, runs `upgrade --dry-run`, applies `upgrade`, then runs the unit tests. If you do not have Raven installed in this repo yet, run `python scripts/raven.py install python` (or your preferred language) first.

## Project Structure

| Path | Purpose |
|---|---|
| `common/` | Shared, canonical template content installed into every destination repo |
| `python/`, `go/`, `rust/`, `typescript/`, `swift/`, `elixir/`, `lua/`, `dotfiles/` | Per-language template trees |
| `scripts/raven.py` | The installer and upgrade engine |
| `scripts/self-check.py` | Self-test harness for this repo |
| `tests/` | Unit tests |
| `project-skills/` | Maintenance skills for working in this repo (not shipped to users) |

### Template composition (symlinks)

`common/` is the single source of truth for shared content. Each language tree
**symlinks** its shared paths back to `common/` rather than holding its own copy:
`.agents/skills`, `.claude/agents/*`, the shared `.claude/docs/raven-*` docs,
`.claude/hooks`, `.claude/rules/raven-security.md`, `.claude/scripts`,
`.claude/settings.json`, `.codex/*`, `.raven/git-hooks`, and `AGENTS.md`.

To change shared content, **edit the file under `common/` only** — every language
tree inherits it through the symlink. Do **not** copy into a per-language path such
as `python/.agents/skills/...`; that path is a symlink, so the write either no-ops
through to `common/` or breaks the link. Check with `ls -l <tree>/<path>` first.

Files that legitimately differ per language are real (non-symlinked) files:
`justfile`, `.mcp.json`, `.codex/config.toml`, `.claude/rules/raven-<lang>.md`, and
`.claude/docs/raven-<lang>-quality.md`.

## Making Changes

- **Shared template files** (under `common/`): update the source in `common/`, then run `self-check.py` to verify the installed shape is correct.
- **Per-language files** (`justfile`, `.mcp.json`, `raven-<lang>` rule/quality docs): update the file in each language tree that needs it.
- **`scripts/raven.py`**: add or update tests in `tests/` alongside logic changes. The self-check will also exercise upgrade behavior end-to-end.
- **Docs** (`.claude/docs/`, `common/.claude/docs/`): update both copies in sync — `self-check.py` will fail if they diverge. The `common/` copy is what gets installed.

## Pull Requests

- Open an issue first for significant changes so we can discuss the approach.
- Keep PRs focused — one concern per PR.
- Ensure `python -m pytest` passes before opening.
- Follow the existing code style (no type annotations in shell scripts; type hints required in Python).

## Reporting Bugs

Open a GitHub issue with steps to reproduce, expected behavior, and actual behavior. For security issues, see [SECURITY.md](SECURITY.md).
