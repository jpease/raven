# Decision record: should the `.claude/` subset ship as a Claude Code plugin?

**Research date:** August 13, 2026. **Decision: not now** — see [Recommendation](#recommendation-and-trigger).

Claude Code's plugin documentation is live, unversioned reference material; behavior described here reflects pages accessed on the date above and may have changed since. Re-verify against current docs before acting on this record if it has aged past a few months.

## The question

`scripts/raven_lib/` is roughly 4,900 LOC of sha256 manifest tracking, three-way reconcile, guided merge, orphan classification, deactivation, template walk, and git-hook installation. Functionally it is a package manager for Claude Code artifacts — it distributes skills, subagents, hooks, rules files, `.mcp.json`, and `.claude/settings.json` into destination repositories and keeps them updated without clobbering local edits.

Claude Code ships a native mechanism for exactly this: `claude plugin install`, `.claude-plugin/plugin.json`, and `marketplace.json`. This record asks whether Raven's `.claude/`-only subset should move to that channel, leaving the installer to handle everything else (`.codex/`, `.raven/`, `justfile`, language-template starter files).

Before this record, the mechanism had never been evaluated as a delivery channel here — the only "marketplace" mention in this repository is in `raven-security-review/SKILL.md`, warning about untrusted skills *from* marketplaces, never considered as a channel for Raven's own distribution.

## Measurement: what share is `.claude/`-only

Measured directly against two real installs (`raven install python` and `raven install go`), each into a fresh scratch git repository, not estimated.

**Method:** for each install, count every regular file under the destination (excluding `.git/`), then separately count files literally under `.claude/` (not following the `.claude/skills` symlink — `find DIR -type f` without `-L` does not descend into a symlinked subdirectory) and files under `.agents/skills/` (the real, shared location `.claude/skills` points to, and the location `.codex/` also reads from directly).

| | python template | go template |
| --- | --- | --- |
| Total files (excl. `.git/`) | 79 | 78 |
| Total bytes | 542,246 | 539,411 |
| `.claude/` literal (not incl. skills) | 28 files / 225,430 bytes | 28 files / 224,743 bytes |
| `.agents/skills/` (shared, symlinked from `.claude/skills`) | 20 files / 62,663 bytes | 20 files / 62,663 bytes |
| `.claude/` literal + skills combined | 48 files / 288,093 bytes | 48 files / 287,406 bytes |
| Share of total (files / bytes) | 60.8% / 53.1% | 61.5% / 53.3% |

The near-identical numbers across two unrelated language templates confirm the shared `common/` content dominates the measurement — only a handful of per-language starter files vary, and none of them land under `.claude/`.

**Two honest framings, both reported rather than picking one:** counting `.claude/`'s own directory alone (not the skills it symlinks to) gives 28/79 files (35.4%) and 225,430/542,246 bytes (41.6%). Counting what a Claude Code session actually consumes through `.claude/` — which includes the skills it resolves via that symlink — gives the larger 60.8%/53.1% figures above. A plugin bundling "the `.claude/` subset" would need the skills too, since skills are exactly the kind of thing plugins exist to carry; the smaller, literal-directory number understates what would actually need to move.

**Component counts, corrected against the issue's own estimate:** the issue's introduction cites "25+ skills, 4 subagents, 7 hooks, 5 rules files." Measured directly against this repository: **22** skills (`.agents/skills/*/`), **4** subagents (`common/.claude/agents/*.md`, matches), **6** hooks (`common/.claude/hooks/*.py`), and **2** rules files total across both adapters (`common/.claude/rules/raven-security.md`, `common/.codex/rules/raven.rules` — not 5). None of these corrections change the conclusion below, but "measurement, not estimation" applies to the whole record, not only the headline share number.

## Capability matrix: what a plugin can carry vs. what Raven ships

| Raven-shipped content | Plugin-carriable? | Notes |
| --- | --- | --- |
| Skills (`.agents/skills/`) | **Yes** — `skills/` | Plugin skills are namespaced (`/plugin-name:skill-name`); Raven's today are bare (`/raven-commit`). Migrating would change every invocation and every doc that names one. |
| Subagents (`.claude/agents/`) | **Yes** — `agents/` | No namespacing caveat found in the docs for agents specifically. |
| Hooks (`.claude/hooks/`) | **Yes** — `hooks/hooks.json` | Same event/matcher shape Raven already uses. |
| `.mcp.json` | **Yes** — `.mcp.json` at plugin root | Raven's `.mcp.json` is explicitly *not* proposed for plugin ownership here — issue #200 already carved it out of `.claude/settings.json`'s ownership model for lack of a "local overrides" sibling, and the same reasoning applies to a plugin split. |
| `.claude/settings.json` (incl. `permissions.deny`, #199) | **No** — plugin `settings.json` supports only the `agent` and `subagentStatusLine` keys | Hard blocker: today's plugin mechanism cannot carry what #199 just shipped, regardless of any other decision in this record. |
| `.claude/docs/*.md` (reference docs skills point to) | **Partial** | No dedicated component type; would need to travel inside a skill's own directory or be dropped. |
| `.codex/` (agents, hooks, scripts, rules, config) | **No** | No non-Claude-Code runtime appears anywhere in the plugin docs. |
| `justfile`, `.raven/git-hooks/`, language starter files (`pyproject.toml`, `go.mod`, …) | **No** | Closest primitive is `bin/` (executables added to the Bash tool's `PATH`), which is not the same thing as a project's own build/test recipe file or starter config. |
| Per-repo drift detection / guided merge over local edits | **No** | Plugin updates are a full directory replace with no merge — see [Whether the hybrid is worse](#whether-the-hybrid-is-worse-than-either-pure-option). |

## What machinery survives a split

If `.claude/` shipped as a plugin and everything else shipped through the installer, the remainder is `.codex/` (16 files / 155,165 bytes), `.raven/` (9 files / 86,084 bytes — config, manifest, git hooks), and root-level files (`AGENTS.md`, the `CLAUDE.md` symlink, `README.md`, `justfile`, `pyproject.toml`, `.mcp.json`).

Every one of those remaining files still needs exactly the machinery `scripts/raven_lib/` provides today:

- **Manifest tracking** — `.codex/` and root files still need sha256 baselines to detect drift; nothing about a `.claude/`-only plugin split removes the need to track the rest.
- **Three-way reconcile** — the same `identical`/`will_upgrade`/`needs_merge`/`local_only` logic (issue #200's own recent work made this explicit for `.claude/settings.json`) still applies to every remaining tracked file.
- **Guided merge** — `AGENTS.md`'s managed block and `.mcp.json`'s guided-merge path (explicitly *not* given plugin-style ownership by issue #200, on the grounds that no sibling "local overrides" file exists for it) are both entirely outside `.claude/` and keep needing this mechanism verbatim.
- **Orphan classification and deactivation** — both are policy-neutral over whatever the current template ships and the current config selects; they don't care whether `.claude/` is one of the things they're tracking. Disabling the `.codex` component alone already exercises this today.

**The split does not remove code, it relocates roughly half of what the installer walks.** None of the six mechanisms listed in the issue's own "what survives" question goes away; each keeps operating over a smaller, `.claude/`-shaped set of remaining files. This is the load-bearing finding for the recommendation below: the appeal of "delete ~4,900 LOC of installer" does not hold even in the most favorable split, because the installer's job was never specific to `.claude/` — it is generic manifest/reconcile/merge machinery that the non-`.claude/` remainder still requires in full.

**A second, concrete cost the split would introduce:** the `.claude/` and `.codex/` copies of byte-identical files (hooks, scripts) are unified in the *source* tree today — a real file under `common/.claude/`, a template-internal symlink under `common/.codex/`, materialized as two real, identical files at install time (this exact unification, and the drift-detection tests that guard it, is recent work from earlier issues in this epic: #195, #201). If `.claude/`'s copy moved into a separately-versioned plugin repository, Raven would face a choice with no good option: duplicate the byte-identical content in both the plugin repo and the installer's `common/` tree (reintroducing precisely the multi-copy-drift class #201 just eliminated for config parsing, this time for hook/script content), or make the installer's own `common/` tree pull from the plugin repository as its source of truth for `.claude/`'s half — a new cross-repo version-alignment dependency between the plugin and the installer that does not exist today.

**On "plugin versions pin globally, not per-project" specifically:** this counter-argument's first half is no longer accurate against current documentation, and it is worth correcting rather than repeating uncritically — plugin installation scope is `user`, `project`, `local`, or `managed`, and a project-scoped `.claude/settings.json` can pin `enabledPlugins` to a specific version independently of what any other project on the same machine has installed, exactly the way Raven's own `.raven/config.toml` scopes per repo today. The second half of the counter-argument stands regardless of that correction: version pinning is not the same capability as drift *detection*. A plugin's version pin says which version a project wants; it says nothing about whether the installed copy still matches that version, or flags it if a user hand-edited a file inside it — that is what manifest tracking and reconcile provide, and per-project plugin version scoping does not substitute for either.

## Whether the hybrid is worse than either pure option

Argued directly, not hedged: **yes, the hybrid is worse than either pure option, and pure-plugin is not viable at all**, so the honest comparison is hybrid vs. status quo.

**Pure plugin is not viable.** Confirmed against current plugin documentation (below): plugins have no mechanism for `.codex/` (no non-Claude-Code runtime is mentioned anywhere in the plugin docs — plugins are Claude Code–exclusive), no mechanism for `justfile`, `.raven/git-hooks/`, or language-template starter files (`pyproject.toml`, `go.mod`, and siblings) — the closest plugin primitive, `bin/` (executables added to the Bash tool's `PATH`), is not the same thing as a project's own `justfile` or starter config. Raven ships all of these today; a pure-plugin Raven could not.

**The hybrid is worse than the status quo for two concrete reasons, not just "two things to learn":**

1. **Different, weaker safety guarantees for exactly the files most likely to be hand-edited.** Per current plugin docs, plugin updates are a full directory replace: `/plugin update` or auto-update installs a complete new versioned copy; the previous version is marked orphaned and garbage-collected roughly 14 days later. There is no three-way merge, no conflict detection, and no preservation path for a locally edited file inside an installed plugin's directory — the documentation's own guidance is that users should not edit plugin files directly. Raven's installer, by contrast, treats a locally edited hook or skill as `local_only`/`needs_merge` and never silently overwrites it. A user who is used to Raven's edit-and-keep-your-changes behavior for `.claude/hooks/*.py` today would, under the hybrid, have those same edits silently discarded on the next plugin update — a real behavioral regression for the highest-value half of what Raven ships, introduced by the split itself, not by anything upstream changed.
2. **A hard capability gap, not just a style difference.** Plugin-bundled `settings.json` supports exactly two keys — `agent` and `subagentStatusLine` — confirmed against the current plugin reference. It cannot carry `permissions.deny`, which issue #199 (this same epic) just shipped as a defense-in-depth layer in `.claude/settings.json`. A `.claude/`-as-plugin split would have no native way to ship that content at all; it would need to stay installer-delivered regardless, undermining the premise of "the `.claude/` subset moves to plugins" from the start.

**On the trust boundary, correcting an assumption rather than confirming it as originally stated:** it is not strictly true that a plugin is always a separate, user-initiated install while a template file is always repo-committed and PR-reviewed. Current marketplace documentation describes exactly the opposite case: a repository can commit `extraKnownMarketplaces` and `enabledPlugins` entries in `.claude/settings.json`, and Claude Code registers the marketplace and enables the listed plugins for every team member "once they trust the project folder, with no separate prompt" beyond that existing trust dialog. So a repo *can* drive plugin installation without a second, plugin-specific consent step. The distinction that survives is narrower but still real: Raven's template files are the literal content a PR reviewer sees in the diff; a repo-driven plugin install is a *pointer* to content fetched separately from a marketplace source at trust-time, which a reviewer approving that one line of `.claude/settings.json` has not necessarily read byte-for-byte. Different security posture, but "the security skill's existing warning is relevant to Raven's own distribution too" is the right instinct from the issue, just via a different mechanism (fetch-at-trust vs. no-runtime-consent-at-all) than "install is always separately opted into."

## The `requires-python` floor

A related, explicitly-out-of-scope-for-code question the issue asks to be settled as a decision record here, since #201 (seven config parsers) and `data/gate_data.py` being a Python dict rather than TOML both trace to it.

**Data:**
- macOS 26.6.1 ships `/usr/bin/python3` as **3.9.6** — the binding constraint, since it is the stock interpreter on a machine nobody configured, and it is *older* than every Linux floor below.
- Ubuntu 22.04 LTS: 3.10. RHEL 9: 3.9. Debian 12: 3.11. Ubuntu 24.04: 3.12.
- `tomllib` is stdlib from 3.11 — there is no stdlib TOML reader below it.
- Vendoring `tomli` (a third-party dependency) would serve the installer (`scripts/raven_lib/`, which already runs under Raven's own controlled environment) but **not** the shipped hooks, which run in destination repos under whatever `python3` resolves there — an interpreter Raven does not control and cannot require a dependency for.
- `tomllib` is read-only. Comment-preserving config *writes* (`replace_platform_line` and similar) would still need `tomlkit`, a third-party package, regardless of the floor.

**Conclusion: the floor stays at 3.9. Do not move it now.** This matches #201's own scoping decision, which explicitly deferred this exact question here rather than answering it implicitly inside a refactor. The binding constraint is macOS's stock `/usr/bin/python3`, not any Linux distribution's floor, and macOS 26.6.1 still ships 3.9.6. Moving the floor would not even unlock `tomllib` use in the *shipped hooks* — those still cannot assume any interpreter version above whatever the destination repo's environment provides, floor or no floor. The only thing a higher `requires-python` would change today is what `scripts/raven_lib/` itself may assume, and #201 already shipped its own small parser rather than reaching for `tomllib` for exactly this reason — a higher floor would not have obviated that parser.

**Reconsideration trigger:** revisit the floor when macOS's stock `/usr/bin/python3` moves to 3.11 or later (removing the strongest reason `tomllib` isn't already usable in the installer), **and** separately, independently, revisit whether the shipped hooks can ever assume a stdlib TOML reader only if Raven's distribution model changes such that shipped hooks no longer need to run under an arbitrary destination-controlled interpreter — which is exactly the plugin question this record answers "not now" to. The two triggers are independent: the installer's own floor and the shipped hooks' floor are different constraints with different answers, as the epic's own framing already noted.

## Recommendation and trigger

**Not now.** Keep the installer as the sole distribution channel for `.claude/`, `.codex/`, and everything else Raven ships. This is a successful, deliberate outcome, not a deferral for lack of a conclusion — the measurement shows the split doesn't reduce installer code, only relocates roughly half of what it walks; the machinery inventory shows every reconcile/merge/orphan/deactivation mechanism is still needed for the remainder regardless; and two concrete, current capability gaps (`permissions.deny` unsupported in plugin settings, full-replace updates with no edit-preservation) mean the `.claude/` subset specifically could not move cleanly even if the rest of the split were free.

**Named triggers, any one of which should prompt revisiting this record:**

1. **A Codex-side plugin/extension equivalent ships**, closing the multi-runtime gap that makes pure-plugin non-viable today. Without this, splitting `.claude/` out still leaves `.codex/` on the installer, and the two adapters' shared, unified hook/script content (the concrete cost described above) becomes a standing maintenance cost for as long as only one side has a plugin channel.
2. **Plugin `settings.json` gains support for arbitrary settings content** (specifically `permissions.deny`) **and** **plugin updates gain a conflict-preserving update path** (something better than full replace with a 14-day orphan sweep) for locally edited plugin files. Either alone narrows the gap; both together would make a `.claude/`-only plugin genuinely comparable in safety to what the installer provides today.
3. **Explicitly not a trigger:** the `.claude/` share of installed files/bytes crossing some higher threshold. The share was worth measuring precisely because the issue asked for it, but the "what machinery survives a split" finding shows the share doesn't actually drive the decision — a larger `.claude/` share would mean relocating more files, not eliminating more code, since the installer's mechanisms are generic over whatever it tracks, not `.claude/`-specific.

## Sources

- [Anthropic — Create plugins](https://code.claude.com/docs/en/plugins) — live, unversioned documentation, accessed August 13, 2026. Source for the plugin directory structure table (`skills/`, `commands/`, `agents/`, `hooks/`, `.mcp.json`, `.lsp.json`, `monitors/`, `bin/`, `settings.json`), the `settings.json` two-key (`agent`, `subagentStatusLine`) limitation, and the migration-from-`.claude/`-to-plugin walkthrough (confirming plugin skills are always namespaced, e.g. `/plugin-name:skill-name`, unlike standalone `.claude/skills/`).
- [Anthropic — Plugins reference](https://code.claude.com/docs/en/plugins-reference) — live, unversioned documentation, accessed August 13, 2026. Source for the version-management/update mechanism (full directory replace per version, no merge, ~14-day orphaned-version sweep, no preservation of local edits inside an installed plugin), the installation-scope table (`user`/`project`/`local`/`managed`), and the full `plugin.json` schema (`name` is the only required field).
- [Anthropic — Create and distribute a plugin marketplace](https://code.claude.com/docs/en/plugin-marketplaces) — live, unversioned documentation, accessed August 13, 2026. Source for the `marketplace.json`/`extraKnownMarketplaces`/`enabledPlugins` repo-driven registration flow ("Claude Code adds your marketplace for team members once they trust the project folder, with no separate prompt"), and the version-resolution/release-channel mechanics.
- Measured directly against this repository: `raven install python` and `raven install go` into fresh scratch git repositories, file/byte counts taken with `find`/`wc -c` as described in [Measurement](#measurement-what-share-is-claude-only). Reproducible by re-running the same commands against a current checkout.
