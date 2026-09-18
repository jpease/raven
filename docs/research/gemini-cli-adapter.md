# Research: Gemini CLI adapter surfaces

Verifies every Gemini CLI behavior issue #263 lists, ahead of the template work in #262's
child issues. Follows the verification shape `raven-agent-compatibility.md` uses for Codex:
an upstream URL per claim, and a live-run note wherever the docs were silent or ambiguous.

**Gemini CLI version:** `main` branch docs and source, `package.json` reporting
`0.62.0-nightly` at research time; `npm view @google/gemini-cli version` resolves the latest
published (non-nightly) release as `0.60.0`, which is also what `npx -y
@google/gemini-cli@latest` installed for the live runs below.
**Research date:** 2026-09-17.

None of Gemini CLI's docs pages carry their own "as of version X" stamp, so every claim
below is anchored to that date and to the exact file/commit fetched, not to a release note.
Re-verify against the source if this ages past the doc-freshness window noted in
`raven-agent-compatibility.md`.

## 1. Instructions: `GEMINI.md` and `@import`

**A bare `@AGENTS.md` resolves identically to `@./AGENTS.md`.** Confirmed two ways:

- Source: the import scanner (`findImports` in
  [`packages/core/src/utils/memoryImportProcessor.ts`](https://github.com/google-gemini/gemini-cli/blob/main/packages/core/src/utils/memoryImportProcessor.ts))
  accepts an import path starting with `.`, `/`, or any letter — `AGENTS.md` passes the same
  validation as `./AGENTS.md` — and then resolves it with `path.resolve(fileBasePath,
  importPath)`. Node's `path.resolve` treats a bare relative segment and a `./`-prefixed one
  identically, so the two spellings produce the same resolved path.
- Live run: a scratch project with `GEMINI.md` containing only `@AGENTS.md` and a sibling
  `AGENTS.md` loaded without error — debug output logged
  `[MemoryDiscovery] Successfully read and processed imports: <path>/GEMINI.md`, with a
  processed length reflecting the inlined `AGENTS.md` content. No `ENOENT` or unresolved-
  import warning appeared for that import (a real `ENOENT` did appear in the same run, for an
  unrelated `@MainActor` import inside this machine's pre-existing global `~/.gemini/GEMINI.md`,
  which confirms the tool does report a failed import distinctly rather than silently
  swallowing it).

**Imports are recursive/transitive.** Per
[`docs/reference/memport.md`](https://github.com/google-gemini/gemini-cli/blob/main/docs/reference/memport.md):
imported files may themselves contain `@path` imports, processed to a default max depth of 5
(configurable), with automatic circular-import detection, and `@`-shaped text inside a code
block or inline code span is excluded from import scanning. Resolution is relative to the
*importing file's own directory* (`basePath`), not the cwd or the invocation root — so a
chain `GEMINI.md` → `docs/a.md` → `@b.md` resolves `b.md` against `docs/`, not the project
root.

Path format: `docs/reference/memport.md` and
[`docs/cli/gemini-md.md`](https://github.com/google-gemini/gemini-cli/blob/main/docs/cli/gemini-md.md)
only show `./`, `../`, and absolute-path examples; no restriction to `.md` files is stated,
though every example is Markdown.

Default context filename is `GEMINI.md`; `context.fileName` in `settings.json` accepts a
single string or a string array (`docs/reference/configuration.md`), so a Raven install could
in principle set `context.fileName: ["AGENTS.md"]` instead of shipping a `GEMINI.md` stub —
out of scope for this research task, but relevant to #264/#266.

## 2. Skills

**Gemini CLI reads `.agents/skills/` directly — no `.gemini/skills` symlink is needed.**
Per [`docs/cli/skills.md`](https://github.com/google-gemini/gemini-cli/blob/main/docs/cli/skills.md):

- Discovery precedence, lowest to highest: built-in skills → extension skills → user skills
  (`~/.gemini/skills/` or the `~/.agents/skills/` alias) → workspace skills (`.gemini/skills/`
  or `.agents/skills/`).
- Within a tier, `.agents/skills/` takes precedence over `.gemini/skills/` when both exist —
  the reverse of "check `.gemini` first."
- Required format: a `SKILL.md` file with `name` and `description` frontmatter — the same
  shape Raven already ships at `.agents/skills/raven-*/SKILL.md` for Codex.

This mirrors the Codex finding in `raven-agent-compatibility.md`: the canonical skills
directory is live for a third harness with zero adapter file needed. Unlike Codex (which the
compatibility doc says reads `.agents/skills` with no alternate path), Gemini CLI's own
directory is `.gemini/skills`, and `.agents/skills` is documented as an explicit
compatibility alias — so this is a deliberate cross-tool interop point on Gemini's side, not
an incidental scan.

## 3. Hooks

**Gemini CLI has a hooks system**, documented at
[`docs/hooks/reference.md`](https://github.com/google-gemini/gemini-cli/blob/main/docs/hooks/reference.md)
and [`docs/hooks/writing-hooks.md`](https://github.com/google-gemini/gemini-cli/blob/main/docs/hooks/writing-hooks.md).

- **Events:** `BeforeTool`, `AfterTool` (tool lifecycle); `BeforeAgent`, `AfterAgent`;
  `BeforeModel`, `BeforeToolSelection`, `AfterModel`; `SessionStart`, `SessionEnd`,
  `Notification`, `PreCompress`.
- **Stdin payload:** every event gets `{session_id, transcript_path, cwd, hook_event_name,
  timestamp}`. `BeforeTool`/`AfterTool` add `tool_name`, `tool_input`, `mcp_context`,
  `original_request_name`; `AfterTool` adds `tool_response`; `SessionStart` adds `source`
  (`"startup" | "resume" | "clear"`); `SessionEnd` adds `reason`.
- **Tool-name matcher values:** discrete built-in names, not bundled categories — e.g.
  `read_file`, `run_shell_command`; MCP tools are `mcp_<server>_<tool>`. Matchers support
  regex (`read_.*`). The exact write/edit built-in tool names weren't pinned down from the
  hooks doc alone (`docs/reference/tools.md` has the authoritative list) — treat as a small
  gap, not a blocker.
- **Output schema:** `decision` (`"allow" | "deny"`, alias `"block"`), `reason` (required to
  deny), `systemMessage`, `continue` (false ends the agent loop), `suppressOutput`,
  `stopReason`; plus `hookSpecificOutput.*` per event — `tool_input` override on `BeforeTool`,
  `additionalContext` (additive) or `tailToolCallRequest: {name, args}` (runs a replacement
  tool call) on `AfterTool`.
- **Exit codes:** `0` success (stdout parsed as JSON), `2` "System Block" (stderr text becomes
  the rejection/replacement reason), anything else is a non-fatal warning and the CLI
  continues.
- **Can `AfterTool` replace the tool's output entirely?** Yes — closer to Claude Code's
  `updatedToolOutput` than to Codex's add-feedback-or-block-only model. `decision: "deny"` +
  `reason` replaces the result text sent to the model; `tailToolCallRequest` replaces it with
  another tool call's result outright. This answers the acceptance-criteria question that
  motivated `raven-post-bash-truncate.py`'s Claude-only status: Gemini CLI has a real
  counterpart mechanism, unlike Codex.
- Live run: registering a `SessionStart` hook in a trusted scratch project produced `Hook
  registry initialized with 1 hook entries`, `Expanding hook command: ... (cwd: <project
  dir>)`, and `Hook execution for SessionStart: 1 hooks executed successfully` in debug
  output — the hook fired and its shell command ran with the project directory as its cwd.

### Hook working directory

**Gemini CLI does set a project-directory environment variable: `GEMINI_PROJECT_DIR`.**
Neither hooks doc names it in a dedicated "environment variables" section — it appears only
inside one Node.js example script in `writing-hooks.md` — so this was flagged for live
verification rather than trusted as documented. Live run confirms it's real: the same
`SessionStart` hook, run with `echo $GEMINI_PROJECT_DIR`, printed the project root exactly.
This is Gemini's equivalent of Claude Code's `$CLAUDE_PROJECT_DIR`, and unlike Codex — which
`raven-agent-compatibility.md` documents as having no such variable at all, forcing the
`hooks.json` launcher to parse stdin for the project root before any relative path resolves.
Not independently verified: whether `GEMINI_PROJECT_DIR` stays correct if Gemini CLI is
invoked with a working directory outside the project (the test above ran from inside the
project root, the common case); low priority to chase further unless a template design
depends on the answer.

### Hook trust is a separate, narrower mechanism than folder trust

Source: [`packages/core/src/hooks/trustedHooks.ts`](https://github.com/google-gemini/gemini-cli/blob/main/packages/core/src/hooks/trustedHooks.ts).
Each hook is individually tracked by a `name:command` key in a global `~/.gemini/
trusted_hooks.json` (`{[projectPath]: string[]}`), independent of workspace folder trust —
structurally the same idea as Codex's per-hook-hash review in `/hooks`, just keyed
differently. `docs/cli/trusted-folders.md`'s "what we scan for" list (shown in the trust
dialog) includes hooks, but its "what's disabled when untrusted" list does not — and reading
[`packages/cli/src/config/config.ts`](https://github.com/google-gemini/gemini-cli/blob/main/packages/cli/src/config/config.ts)
confirms why: the line wiring hooks into the runtime config carries the literal comment `//
TODO: loading of hooks based on workspace trust` immediately above `enableHooks:
settings.hooksConfig.enabled`. As of this research date, **workspace folder trust does not
yet gate whether project-level hooks load** — that gating is on the current TODO list, not
shipped. The only enforcement today is the separate per-hook trust file, and, in headless
mode specifically, the coarser all-or-nothing folder-trust refusal below.

## 4. Command approval / policy engine

**Yes — a TOML rule engine, structurally the closer analog to Codex's `.rules` file than
anything in `settings.json`.** Source:
[`docs/reference/policy-engine.md`](https://github.com/google-gemini/gemini-cli/blob/main/docs/reference/policy-engine.md).

- Files: `~/.gemini/policies/*.toml` (User tier); admin tier at OS-specific system
  directories, or via `--admin-policy`/`adminPolicyPaths`. **Workspace-tier policy
  (`.gemini/policies/*.toml` at the project level) is documented as currently non-functional**
  — see [issue #18186](https://github.com/google-gemini/gemini-cli/issues/18186) — so Raven's
  adapter cannot ship a project-scoped policy file that actually applies yet.
- Rule shape (`[[rule]]` blocks): `toolName` (string/wildcard, e.g. `*`, `mcp_*`,
  `mcp_<server>_*`), `mcpName`, `subagent`, `commandPrefix` XOR `commandRegex` (shell string
  match), `argsPattern` (regex against serialized tool args), `interactive` (bool),
  `toolAnnotations`, `decision` (`"allow" | "deny" | "ask_user"`), `priority` (0–999),
  `denyMessage`, `modes` (approval-mode filter), `allowRedirection`.
- Precedence: `final_priority = tier_base + (toml_priority / 1000)`, tiers Admin(5) >
  User(4) > Workspace(3, disabled today) > Extension(2) > Default(1); highest final priority
  wins.
- `ask_user` degrades to `deny` in non-interactive (headless) mode — relevant to #269's eval
  harness, since a policy rule that prompts interactively will simply block a headless run.
- A separate, simpler mechanism lives in `settings.json` (`docs/reference/configuration.md`):
  `tools.allowed` (array, e.g. `"run_shell_command(git)"`, bypasses confirmation),
  `tools.confirmationRequired` (always prompts, overrides `tools.allowed`), `tools.core`
  (allowlist restricting which built-in tools are even available), plus
  `tools.sandbox`/`sandboxAllowedPaths`/`sandboxNetworkAccess`. `tools.exclude` is documented
  as deprecated in favor of policy-engine `deny` rules.
- [Issue #15383](https://github.com/google-gemini/gemini-cli/issues/15383) records a past
  doc/behavior mismatch in the policy engine — worth a spot-check before Raven hard-codes
  exact semantics into a template.

## 5. Trust

- **File:** `~/.gemini/trustedFolders.json` (override via `GEMINI_CLI_TRUSTED_FOLDERS_PATH`).
  Confirmed live — a fresh scratch directory with no matching entry in this file behaved as
  untrusted by default. The folder-trust feature itself is **disabled by default**, enabled
  via `{"security": {"folderTrust": {"enabled": true}}}` in `settings.json`
  ([`docs/cli/trusted-folders.md`](https://github.com/google-gemini/gemini-cli/blob/main/docs/cli/trusted-folders.md)).
- **Schema:** the docs page only describes the three choices in prose ("Trust folder", "Trust
  parent folder", "Don't trust"); the literal enum lives in source —
  [`packages/core/src/utils/trust.ts`](https://github.com/google-gemini/gemini-cli/blob/main/packages/core/src/utils/trust.ts)
  defines `enum TrustLevel { TRUST_FOLDER = 'TRUST_FOLDER', TRUST_PARENT = 'TRUST_PARENT',
  DO_NOT_TRUST = 'DO_NOT_TRUST' }`. The exact per-entry record shape of `trustedFolders.json`
  itself (a flat `{path: TrustLevel}` map vs. something richer) wasn't pinned down from source
  in this pass — low-risk gap, since Raven doesn't need to write this file, only document its
  effect.
- **What's disabled when untrusted (interactive "Don't trust" choice), per
  `trusted-folders.md`:** workspace `.gemini/settings.json` is not loaded; `.env` files are
  not loaded; extension install/update/uninstall is restricted; tool auto-acceptance is
  disabled (always prompts); automatic memory loading is disabled; MCP servers do not
  connect; custom `.toml` commands (project and user) are not loaded.
- **Hooks are scanned for in the pre-trust discovery dialog but not named in that disabled
  list** — see the Hooks section above: source shows this is a genuine, dated gap (an open
  TODO), not settled doc silence.
- **Headless mode does not have a degraded "untrusted but running" state at all.** Live run:
  in an untrusted scratch directory, headless (`-p`) invocation refused outright — `Gemini CLI
  is not running in a trusted directory. To proceed, either use --skip-trust, set the
  GEMINI_CLI_TRUST_WORKSPACE=true environment variable, or trust this directory in
  interactive mode` — and exited before any hook, memory, or MCP loading occurred. So the
  interactive "Don't trust → restricted mode" behavior above does not apply to headless/CI
  invocation; there it's binary (trusted-and-fully-functional, or refuse to start).
  `--skip-trust` and `GEMINI_CLI_TRUST_WORKSPACE=true` both bypass this for automation.

## 6. Subagents

**Supported.** Source:
[`docs/core/subagents.md`](https://github.com/google-gemini/gemini-cli/blob/main/docs/core/subagents.md).

- Format: Markdown with YAML frontmatter; the body is the subagent's system prompt.
- Locations: project `.gemini/agents/*.md`, user `~/.gemini/agents/*.md`.
- Frontmatter: required `name` (slug), `description` (used for auto-delegation); optional
  `kind` (`local`/`remote`), `tools` (array, wildcards `*`/`mcp_*`/`mcp_<server>_*`; omitted =
  inherits all parent tools), `mcpServers` (inline, isolated to the subagent), `model`
  (default `inherit`), `temperature` (default `1`), `max_turns` (default `30`), `timeout_mins`
  (default `10`).
- Invocation: automatic (main agent matches `description`) or explicit `@subagent_name ...` at
  the start of a prompt.
- Built-ins enabled by default: `codebase_investigator`, `cli_help`, `generalist`;
  `browser_agent` is disabled by default. Subagents cannot call other subagents — no
  recursive delegation even through a `*` tool wildcard.
- Management: `/agents` (and `/agents reload`) interactively, or `agents.overrides` /
  `modelConfigs.overrides` in `settings.json`; disable globally via
  `experimental.enableAgents: false`. Policy-engine rules can scope by `subagent` name (see
  §4).
- A separate Agent2Agent (A2A) remote-subagent mechanism exists (`docs/core/remote-agents.md`,
  not read in this pass) — flag for follow-up only if a Raven template needs remote agents.

## 7. Headless / non-interactive mode

Source: [`docs/cli/headless.md`](https://github.com/google-gemini/gemini-cli/blob/main/docs/cli/headless.md),
[`docs/cli/tutorials/automation.md`](https://github.com/google-gemini/gemini-cli/blob/main/docs/cli/tutorials/automation.md).

- Invocation: `gemini -p "prompt"` (`--prompt`) forces non-interactive; also triggered
  automatically when stdin/stdout aren't a TTY. Piped stdin is appended to the `-p` prompt.
  `-i`/`--prompt-interactive` runs one prompt then drops into interactive mode (not headless).
  No separate `run` subcommand.
- Output format: `--output-format`/`-o`, values `text` (default), `json`, `stream-json`.
  `json` returns one object: `response` (final text), `stats` (token usage, API latency),
  `error` (present only on failure). `stream-json` emits JSONL events: `init` (session id,
  model), `message`, `tool_use`, `tool_result`, `error` (non-fatal), `result` (final
  aggregated stats). Not independently verified live — every live invocation in this pass hit
  `IneligibleTierError` during auth (this machine's cached Gemini credential is on a tier the
  CLI no longer serves), before reaching a JSON-formattable response. Debug logging up to that
  point matched the docs (memory discovery, hook init, MCP handshake all ran normally); the
  eval harness work in #269 should re-check the exact `json`/`stream-json` field names against
  a real authenticated run rather than trusting this doc summary verbatim.
- Approval/sandbox defaults: docs do not say headless mode changes `--approval-mode` or
  `--sandbox` defaults — both flags behave the same regardless of TTY. `ask_user` policy rules
  degrade to `deny` headless (§4), which is the practical mechanism that makes headless runs
  non-interactive rather than a separate approval default.
- Exit codes (`headless.md`): `0` success, `1` general/API error, `42` input error (invalid
  prompt/arguments), `53` turn-limit exceeded. No other codes documented.

## 8. MCP configuration

Source: [`docs/tools/mcp-server.md`](https://github.com/google-gemini/gemini-cli/blob/main/docs/tools/mcp-server.md),
[`docs/reference/configuration.md`](https://github.com/google-gemini/gemini-cli/blob/main/docs/reference/configuration.md).

- Location: `mcpServers` object in `settings.json`, at either `~/.gemini/settings.json`
  (user) or `.gemini/settings.json` (project). Full merge order across every settings tier —
  system defaults → user → project → system overrides → environment variables → CLI
  arguments, lower overridden by higher — is documented in `configuration.md`.
- Each server entry needs exactly one of `command` (stdio process), `url` (SSE), or `httpUrl`
  (streamable HTTP) to pick its transport. Fields: `command`, `args` (string[]), `env`
  (object), `cwd`, `url`, `httpUrl`, `headers` (object), `timeout` (ms), `trust` (bool —
  bypasses all confirmation for that server's tools), `description`, `includeTools` (allow-
  list), `excludeTools` (takes precedence over `includeTools`).
- This is materially richer than what `raven-agent-compatibility.md` documents for Codex's
  `.codex/config.toml` MCP block, and directly relevant to #265's per-language settings.json
  renderer.

## Open items for live-run follow-up (not blocking, ranked by relevance to the epic)

1. `--output-format json`/`stream-json` exact field names, once a working (non-legacy-tier)
   Gemini credential is available — relevant to #269.
2. Exact write/edit built-in tool names for hook matchers (`docs/reference/tools.md` should
   have them; not fetched here).
3. `trustedFolders.json`'s literal per-entry record shape.
4. `GEMINI_PROJECT_DIR` correctness when Gemini CLI is invoked from outside the project root.
5. A2A remote-subagent config, only if a template ends up needing it.

## Full source list

- <https://github.com/google-gemini/gemini-cli/blob/main/docs/cli/gemini-md.md>
- <https://github.com/google-gemini/gemini-cli/blob/main/docs/reference/memport.md>
- <https://github.com/google-gemini/gemini-cli/blob/main/packages/core/src/utils/memoryImportProcessor.ts>
- <https://github.com/google-gemini/gemini-cli/blob/main/docs/cli/skills.md>
- <https://github.com/google-gemini/gemini-cli/blob/main/docs/cli/using-agent-skills.md>
- <https://github.com/google-gemini/gemini-cli/blob/main/docs/cli/creating-skills.md>
- <https://github.com/google-gemini/gemini-cli/blob/main/docs/hooks/reference.md>
- <https://github.com/google-gemini/gemini-cli/blob/main/docs/hooks/writing-hooks.md>
- <https://github.com/google-gemini/gemini-cli/blob/main/packages/core/src/hooks/trustedHooks.ts>
- <https://github.com/google-gemini/gemini-cli/blob/main/packages/core/src/services/FolderTrustDiscoveryService.ts>
- <https://github.com/google-gemini/gemini-cli/blob/main/packages/cli/src/config/config.ts>
- <https://github.com/google-gemini/gemini-cli/blob/main/docs/reference/policy-engine.md>
- <https://github.com/google-gemini/gemini-cli/blob/main/docs/reference/configuration.md>
- <https://github.com/google-gemini/gemini-cli/blob/main/docs/cli/trusted-folders.md>
- <https://github.com/google-gemini/gemini-cli/blob/main/packages/cli/src/config/trustedFolders.ts>
- <https://github.com/google-gemini/gemini-cli/blob/main/packages/core/src/utils/trust.ts>
- <https://github.com/google-gemini/gemini-cli/blob/main/docs/core/subagents.md>
- <https://github.com/google-gemini/gemini-cli/blob/main/docs/cli/headless.md>
- <https://github.com/google-gemini/gemini-cli/blob/main/docs/cli/tutorials/automation.md>
- <https://github.com/google-gemini/gemini-cli/blob/main/docs/tools/mcp-server.md>
- <https://github.com/google-gemini/gemini-cli/issues/18186>
- <https://github.com/google-gemini/gemini-cli/issues/15383>
- <https://github.com/google-gemini/gemini-cli/issues/13125>
