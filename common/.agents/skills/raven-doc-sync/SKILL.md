---
name: raven-doc-sync
description: Use after implementing a feature or behavior change, before declaring done, to keep AGENTS.md, README, CHANGELOG, and related docs synchronized.
---

# Doc Sync

Use this skill after a feature, behavior change, template change, workflow change, or user-visible tooling change lands.

## Process

1. Identify the changed behavior and its audience: users, maintainers, agents, or template consumers.
2. Check project-owned documentation that describes that behavior, such as `README.md`, `AGENTS.md`, `CHANGELOG.md`, docs pages, examples, and template-specific guidance.
3. Update only documentation that is stale or missing because of the change.
4. Keep generated or managed files aligned through the repository's documented generation path instead of editing generated output directly.
5. Verify links, commands, filenames, and examples against the implementation.
6. If documentation work is durable but out of scope, create or update a follow-up issue instead of silently leaving it in chat.

## Checklist

- Installation, upgrade, or setup instructions still match the behavior.
- Command examples and file paths still work.
- Agent guidance and skills mention new workflow expectations.
- Changelog or release notes are updated when the project expects them.
- Managed-template output is regenerated when template sources changed.
- Facts stated in prose are ones no config file, gate, or the filesystem itself can answer.

## Avoid

- Do not rewrite unrelated docs for style.
- Do not document behavior that was not implemented.
- Do not update generated files by hand when the repo provides a generator.
- Do not restate a value a config file owns. State why the value is what it is, and point at the file that pins it.

## Config-Owned Values

A value a config file owns and a gate enforces does not belong in prose too — a wrong copy fails the build on its own, so point at the pin instead of repeating it.

State the value anyway when:

- it is a fact no config knows: why the constraint exists, what external thing imposes it, or which directories are off limits and why.
- it is part of a hard-linked fact set — a host version, a platform release, and a language version that move together by design. Naming two of the three sends the reader hunting for the pin that holds the last one, even though a config file also holds it. Coinciding with a pin by intent is not the same as being derivable from it.
