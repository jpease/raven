---
name: template-verifier
description: Use only when maintaining this Raven template repository. Verifies language templates, shared files, symlinks, generated-file exclusions, and raven.py install/upgrade behavior before handoff.
---

# Template Verifier

This is a project-local maintenance skill for the Raven repository. Do not copy it into destination repositories.

## Scope

Use this skill when changing:

- `common/`
- language template directories such as `python/`, `rust/`, `swift/`, or `typescript/`
- `scripts/raven.py`
- template tests under `tests/`
- canonical agent docs, skills, rules, hooks, or setup scripts

## Verification Process

1. Check for broken symlinks:

```sh
find -L . -path ./.git -prune -o -type l -print
```

The command should produce no output.

2. Check for generated files that should not be committed:

```sh
find . -path ./.git -prune -o \( -name .DS_Store -o -name __pycache__ \) -print
```

The command should produce no output.

3. Run the template applicator tests:

```sh
PYTHONDONTWRITEBYTECODE=1 python -m pytest tests
```

4. Preview the Python template:

```sh
PYTHONDONTWRITEBYTECODE=1 python scripts/raven.py --destination /private/tmp install python --dry-run
```

Confirm the preview includes canonical shared files, language-specific Raven rules, `.agents/skills/raven-*/SKILL.md`, `.claude/skills`, `.claude/docs/raven-authority-map.md`, `.claude/docs/raven-guardrails.md`, `.claude/docs/raven-tool-assessment.md`, and the manifest-aware categories for new files, safe upgrades, locally modified managed files, and unknown existing files.

5. If symlink behavior changed, apply to a temporary destination and verify compatibility symlinks:

```sh
rm -rf /private/tmp/agentic-template-check
mkdir -p /private/tmp/agentic-template-check
PYTHONDONTWRITEBYTECODE=1 python scripts/raven.py --destination /private/tmp/agentic-template-check install python
ls -la /private/tmp/agentic-template-check/.claude/skills /private/tmp/agentic-template-check/CLAUDE.md
test -f /private/tmp/agentic-template-check/.claude/skills/raven-tool-bootstrap/SKILL.md
test -f /private/tmp/agentic-template-check/.raven/config.toml
test -f /private/tmp/agentic-template-check/.raven/manifest.json
```

Expected symlinks:

```text
.claude/skills -> ../.agents/skills
CLAUDE.md -> AGENTS.md
```

## Shared File Exposure Audit

When adding files to `common/`, verify each language template exposes them unless intentionally omitted. For Python, the expected Raven-specific extra file should be `.claude/rules/raven-python.md`.

Use a small script or direct inspection to compare:

- shared files under `common/`
- dereferenced files exposed by `python/`

If a shared file should not be installed into destination repositories, keep it outside `common/` and language template directories.

## Handoff Checklist

- No broken symlinks.
- No `.DS_Store` or `__pycache__` artifacts.
- `python -m pytest tests` passes.
- `raven.py install --dry-run` output is understandable and complete.
- Generated `.raven/config.toml` is self-documenting and `.raven/manifest.json` is written on apply.
- Destination-facing files live only in `common/` or language templates.
- Project-maintenance-only files live outside `common/` and language templates.
