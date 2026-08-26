# Upgrading and Merges

How `raven upgrade` decides what to touch, what happens when a file already
exists, and how to settle a conflict for good. For command syntax, see
[Commands](commands.md).

## What an upgrade changes

`raven upgrade --dry-run` sorts every file into one of these buckets:

- Will copy new Raven files
- Will upgrade unchanged Raven-managed files
- Already up to date; will not copy
- Manual merge required (locally modified Raven-managed files; will be left
  untouched)
- Manual merge required (existing files Raven does not manage; template ships
  its own version)
- Locally customized; template unchanged, so left untouched (no merge needed)
- Needs consent to adopt as Raven-managed (existing file Raven does not yet
  own; left untouched, no merge artifact -- see `--adopt-settings-json`)

The last two only appear when there is something to report in them.

Raven overwrites two things and nothing else: paths you named explicitly on
the command line, and managed files whose current content still matches the
hash in `.raven/manifest.json` from the last install. Project-owned content
survives by default.

### Removing files the template dropped

An upgrade also deletes Raven-managed files the template no longer ships, but
only when the file still matches its recorded baseline exactly. Edit it and
Raven reports it and leaves it alone. Starter tool configs such as
`pyproject.toml` are never removed.

Changing `platform` in `.raven/config.toml` works the same way: skills for a
platform you turned off are removed if untouched, reported and kept if not.

### Switching templates

Changing `template` in `.raven/config.toml` swaps the entire shipped file set,
so Raven refuses the upgrade until you confirm:

```sh
raven upgrade --confirm-template-switch
```

### `.gitattributes` and line endings

`.gitattributes` is append-only, not managed as a whole file. Raven adds the
`eol=lf` lines its shipped hooks and scripts need — so a Windows checkout of a
`#!`-invoked file is not corrupted with CRLF — and adds only the lines that are
missing. It never reorders or removes anything already there. This runs on
every install and upgrade, so a line added by a later Raven release still
reaches a repository that installed earlier.

Git applies `eol=lf` at checkout time, so a working tree checked out before
Raven added those lines keeps the line endings it already has. On Windows, or
anywhere else you need the shipped hooks renormalized in an existing clone, do
it once after upgrading:

```sh
git rm --cached -r . && git reset --hard
```

Raven does not run this for you.

### `.ignore` and searchable guidance

`.ignore` is append-only on the same terms. `rg`, `fd` and `ast-grep` read it
through the same `ignore` crate, and all three skip a dot-directory unless
something un-hides it — so without this file the `.agents/`, `.claude/`,
`.codex/` and `.raven/` guidance Raven just installed is invisible to the tools
`AGENTS.md` tells an agent to reach for first, and the search comes back empty
rather than reporting that it skipped anything.

Raven appends one `!` negation per directory and nothing else. A negation can
only un-ignore, so the merge cannot hide a path you were already searching, and
a negation for a directory you do not have is inert. Git does not read
`.ignore` at all. Delete the lines if you want them gone; the only effect is
that the guidance stops turning up in a default search.

The home directory itself is the one destination Raven skips: there
`.claude/` is Claude Code's runtime state rather than shipped guidance, and
un-hiding it would pull gigabytes of transcripts and caches into every search
from `$HOME`. A repository *under* your home directory is unaffected.

## When a file already exists

Two different things can happen, depending on the file.

### Guided merge

For a locally modified Raven-managed file, or an existing file Raven does not
track yet, Raven leaves your file alone and writes review artifacts under
`.raven/merge/`:

- `<file>.raven` — the current template version
- `<file>.diff` — a review-only diff from your file to the template
- `<file>.instructions.md` — how to merge

### Adoption

Some files Raven can take over outright instead of hand-merging, so it asks
for consent rather than writing a merge artifact. See `AGENTS.md` and
`CLAUDE.md` and `.claude/settings.json` below.

## `AGENTS.md` and `CLAUDE.md`

Raven treats `AGENTS.md` as canonical and normally installs `CLAUDE.md` as a
symlink pointing at it.

When either file already exists, Raven writes merge artifacts under
`.raven/merge/`:

- `AGENTS.md.raven` or `CLAUDE.md.raven` — the suggested content, or symlink
  guidance
- `*.instructions.md` — a short merge note for the project owner
- `*.patch` — an append-only patch, when the suggestion is safe to express as
  text

For an existing `CLAUDE.md`:

- Raven leaves it alone by default.
- To take the compatibility symlink instead, answer `Y` at the prompt or run
  with `--adopt-claude-symlink`.
- Adoption moves your file to `CLAUDE.md.bak`.
- If that backup already exists, Raven fails rather than overwrite it.

The generated `AGENTS.md` patch wraps Raven's guidance in a marked block with
a content hash. Apply that block and leave it alone, and later upgrades can
update just the block and leave the rest of your `AGENTS.md` alone. Edit
inside the block and the next upgrade reports it as needing a manual merge.

## `.claude/settings.json`

Raven owns `.claude/settings.json` as managed content. It upgrades in place
like any other template file, with no merge artifact.

`.claude/settings.local.json` is Claude Code's own local-overrides layer — put
your personal preferences there. Raven never manages it, and gitignores it the
first time it installs or adopts `settings.json`.

List-type settings in `settings.json` — `permissions.allow`/`deny`, `hooks`,
`env` — merge across scopes, so Raven's copy can only add to what a developer
already approved personally, never take it away. Scalars (`model`, `theme`,
`effortLevel`) don't merge: the highest-precedence scope wins outright, and
`.claude/settings.json` outranks a developer's own `~/.claude/settings.json`.
Since Raven upgrades this file in place across every install, a scalar added
here would silently override that personal preference for everyone on the
next upgrade. Don't add one without a deliberate, explicit reason — a personal
preference belongs in `settings.local.json` or `~/.claude/settings.json`, not
the template.

- On a clean install Raven writes `.claude/settings.json` immediately, and
  later upgrades update it in place.
- If the repository already has a hand-written `.claude/settings.json` that
  Raven does not track, Raven leaves it alone and reports that it needs
  adoption consent.
- To adopt it, answer `Y` at the prompt or run with `--adopt-settings-json`.
- Adoption moves your file to `.claude/settings.json.bak` first.
- If that backup already exists, Raven fails rather than overwrite it.
- Once adopted or freshly installed, it is tracked in the manifest and
  upgrades like any other managed file.

`.mcp.json` is not part of this ownership model — it goes through the guided
merge path above.

## Finishing a merge with `raven accept`

After you merge the template's changes by hand, record the result so future
upgrades stop re-prompting:

```sh
raven accept            # everything pending under .raven/merge/
raven accept .mcp.json  # or specific paths
raven accept --dry-run  # preview
```

`accept` records your merged file as the new baseline — its current content
plus the template version it was merged against — and removes the merge
artifacts. Later upgrades report the file as up to date until Raven's template
changes again, at which point it comes back for merge instead of being
overwritten.
