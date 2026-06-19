# Research: file-read interception via hooks in Claude Code and Codex CLI

**Research date:** June 18, 2026.

Both documentation sites are live, unversioned references. Anthropic’s page includes behavior introduced through Claude Code v2.1.139; OpenAI explicitly says its hooks page is the release-behavior authority and that `main`-branch schemas may contain unreleased fields.

## Capability matrix

| Capability                             | Claude Code                                                                            | OpenAI Codex CLI                                                                                                                                                       |
| -------------------------------------- | -------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Discrete file-read tool                | **Yes — `Read`**. Input includes `file_path`, optional `offset`, and optional `limit`. | **No general `Read` hook tool.** Hook coverage is currently Bash, `apply_patch`, and MCP calls.                                                                        |
| Match file reads directly              | **Yes — `matcher: "Read"`**                                                            | **No**, unless the read is an MCP tool such as `mcp__filesystem__read_file`. Shell reads appear as `Bash`, not `Read`.                                                 |
| PreToolUse deny/block                  | **Yes.** `hookSpecificOutput.permissionDecision: "deny"` or exit 2.                    | **Yes for supported calls.** Same `permissionDecision: "deny"` shape, legacy `decision: "block"`, or exit 2.                                                           |
| PreToolUse modify input                | **Yes.** `hookSpecificOutput.updatedInput` replaces the entire tool-input object.      | **Yes, but only for supported calls.** `permissionDecision: "allow"` plus `updatedInput`; Bash/`apply_patch` require a replacement `command` string.                   |
| PreToolUse replace eventual result     | **No.** It can rewrite the operation, not synthesize its returned result directly.     | **No documented direct result injection.** It can rewrite the Bash/MCP call so that the rewritten operation produces the skeleton.                                     |
| PostToolUse sees original result       | **Yes.** Receives `tool_response`.                                                     | **Yes for supported calls.** Receives `tool_response`.                                                                                                                 |
| PostToolUse replace tool output        | **Yes.** `hookSpecificOutput.updatedToolOutput` replaces what Claude sees.             | **Partially.** `decision: "block"` or `continue: false` suppresses/replaces the original result with hook feedback, but there is no general `updatedToolOutput` field. |
| PostToolUse arbitrary skeleton payload | **Yes**, provided the replacement matches the built-in tool’s output schema.           | **Not cleanly/documentedly.** You can replace the result with feedback/context, but not supply a schema-preserving arbitrary replacement result.                       |
| PostToolUse observe-only               | **No.** It can inject context, block continuation, and replace output.                 | **No**, but its transformation controls are much narrower than Claude’s.                                                                                               |
| Coverage of all shell executions       | N/A for direct `Read`; Bash is also hookable.                                          | **No.** Official docs say interception of the newer `unified_exec` path is incomplete.                                                                                 |
| MCP read interception                  | **Yes**, by MCP tool-name matcher.                                                     | **Yes**, by canonical MCP matcher such as `mcp__filesystem__read_file`.                                                                                                |
| Default hook timeout                   | Usually **600 seconds**; event-specific exceptions exist.                              | **600 seconds** unless overridden.                                                                                                                                     |
| Command hook input                     | One JSON object on stdin.                                                              | One JSON object on stdin.                                                                                                                                              |
| Async hooks                            | **Supported**, but async hooks cannot affect the triggering action.                    | `async` is parsed but **not supported**; such handlers are skipped.                                                                                                    |
| Handler types                          | Command, HTTP, MCP tool, prompt, and agent, depending on event.                        | Only `type: "command"` executes currently; prompt/agent are parsed but skipped.                                                                                        |
| Windows support                        | Supported; exec-form commands are preferred for portability.                           | Supported through `commandWindows`/`command_windows`; managed directories differ by OS.                                                                                |
| Repo-hook trust                        | Project hooks follow normal Claude configuration policy.                               | Repo/plugin hooks require explicit review and trust unless managed or bypassed.                                                                                        |

The key asymmetry is that Claude Code exposes a matchable `Read` tool and a true post-result replacement field. Codex currently exposes neither a universal discrete read operation nor an equivalent `updatedToolOutput`.

## Q1. Hook events and matcher syntax

### Claude Code

Current documented events:

- `SessionStart`
- `Setup`
- `InstructionsLoaded`
- `UserPromptSubmit`
- `UserPromptExpansion`
- `MessageDisplay`
- `PreToolUse`
- `PermissionRequest`
- `PermissionDenied`
- `PostToolUse`
- `PostToolUseFailure`
- `PostToolBatch`
- `Notification`
- `SubagentStart`
- `SubagentStop`
- `TaskCreated`
- `TaskCompleted`
- `Stop`
- `StopFailure`
- `TeammateIdle`
- `ConfigChange`
- `CwdChanged`
- `FileChanged`
- `WorktreeCreate`
- `WorktreeRemove`
- `PreCompact`
- `PostCompact`
- `Elicitation`
- `ElicitationResult`
- `SessionEnd`

Matcher interpretation is documented as follows:

- `"*"`, `""`, or omitted: match all.
- Only letters, digits, `_`, and `|`: exact name or pipe-separated exact names.
- Any other character: JavaScript regular expression.

Thus `Read` is exact, `Edit|Write` is an exact-name union, and `mcp__memory__.*` is a regex. Tool events match against the tool name.

Claude-only or presently Claude-exclusive events include `Setup`, `InstructionsLoaded`, `UserPromptExpansion`, `MessageDisplay`, `PermissionDenied`, `PostToolUseFailure`, `PostToolBatch`, `Notification`, task/team events, configuration/filesystem-change events, worktree events, elicitation events, `StopFailure`, and `SessionEnd`.

### Codex CLI

Current documented events:

- `SessionStart`
- `SubagentStart`
- `PreToolUse`
- `PermissionRequest`
- `PostToolUse`
- `PreCompact`
- `PostCompact`
- `UserPromptSubmit`
- `SubagentStop`
- `Stop`

Codex always treats `matcher` as a regex string:

- `"*"`, `""`, or omitted: match all.
- Tool events match tool name and supported aliases.
- `apply_patch` additionally matches `Edit` and `Write`.
- `UserPromptSubmit` and `Stop` ignore configured matchers.

Examples include `^apply_patch$`, `Edit|Write`, and `mcp__filesystem__.*`.

## Q2. PreToolUse capabilities

### Claude Code

#### Deny/block: documented yes

```json
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": "Fetch the file skeleton first."
  }
}
```

Exit code 2 with the reason on stderr also blocks the call. Exit 1 is generally non-blocking.

#### Modify input: documented yes

```json
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "allow",
    "updatedInput": {
      "file_path": "/repo/large.py",
      "offset": 1,
      "limit": 100
    }
  }
}
```

`updatedInput` replaces the **entire** input object, so unchanged fields must also be returned.

For a `Read`, this can narrow the read using `offset` and `limit`, but it cannot change the built-in `Read` operation into an unrelated tree-sitter index operation unless the rewritten input itself remains valid for `Read`.

#### Inject or replace result before execution: no direct field

PreToolUse supports `additionalContext`, but no documented field lets it directly provide a synthetic tool result and skip execution while treating the hook payload as the result. To produce a skeleton instead of file contents, use either:

1. `PostToolUse.updatedToolOutput`; or
2. deny the `Read` and direct the agent to a skeleton tool.

### Codex CLI

#### Deny/block: documented yes, but only on supported paths

```json
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": "Large direct reads require an index first."
  }
}
```

Legacy `{"decision":"block","reason":"..."}` and exit code 2 plus stderr are also accepted.

#### Modify input: documented yes

```json
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "allow",
    "updatedInput": {
      "command": "maki index src/large.py"
    }
  }
}
```

For Bash and `apply_patch`, the replacement must contain string field `command`. For MCP calls, `updatedInput` is the replacement arguments object. It is valid only with `permissionDecision: "allow"`.

This gives Codex a plausible **pre-execution transformation** strategy: recognize a shell read command and rewrite it into a skeleton command. However, robustly parsing arbitrary shell syntax is Raven’s responsibility, and Codex’s incomplete `unified_exec` interception means this is not a complete enforcement boundary.

#### Inject or replace result before execution: undocumented/no direct mechanism

There is no documented PreToolUse field equivalent to “return this value as the tool result.” The hook can add `additionalContext` or rewrite the operation, but not directly synthesize a completed result.

## Q3. Can PostToolUse modify or replace output?

### Claude Code: yes, explicitly

`PostToolUse` receives the original `tool_input` and `tool_response`. Its documented output includes:

```json
{
  "hookSpecificOutput": {
    "hookEventName": "PostToolUse",
    "updatedToolOutput": "replacement matching the tool output schema",
    "additionalContext": "Optional extra context"
  }
}
```

`updatedToolOutput` replaces the result **before it is sent to Claude**. For built-in tools, the replacement must match that tool’s output schema; otherwise Claude Code ignores it and uses the original. MCP output is not subjected to the same built-in schema validation.

Therefore PostToolUse is not observe-only. It is the cleanest Claude mechanism for skeletonizing a `Read` result while ensuring the model never receives the original body.

One caveat: the file has already been read locally before PostToolUse. This saves model context and enforces model visibility, but it does not avoid disk I/O or prevent telemetry from seeing the original output.

### Codex CLI: result suppression/replacement with feedback, not general output transformation

Codex PostToolUse receives `tool_response`. It supports:

- `hookSpecificOutput.additionalContext`
- `decision: "block"` plus `reason`
- exit code 2 plus stderr feedback
- `continue: false` plus `stopReason`

The docs state that `decision: "block"` replaces the completed tool result with the hook feedback and continues the model from that message. `continue: false` also stops normal processing of the original result and replaces it with feedback or stop text.

What Codex does **not** document is an `updatedToolOutput`-style field that accepts an arbitrary replacement value preserving the original tool’s result schema. Therefore:

- **Redact or suppress and explain:** documented.
- **Inject a complete structural skeleton as the replacement tool result:** not cleanly documented.
- **Add the skeleton as `additionalContext` while suppressing the original:** possibly workable, but this is context injection plus result suppression, not a documented general-purpose output rewrite API.

## Q4. File-read paths

### Claude Code

Claude Code exposes a first-class `Read` tool. It is directly matchable in `PreToolUse` and `PostToolUse`, with this documented input:

```json
{
  "file_path": "/path/to/file",
  "offset": 10,
  "limit": 50
}
```

The docs explicitly list `Read` among tool names recognized by PreToolUse.

A shell command such as `cat file.py` remains a `Bash` tool call rather than a `Read` call, so full enforcement should cover both `Read` and shell commands capable of reading files.

### Codex CLI

Codex’s current hook docs do **not** expose a general first-class `Read` tool. PreToolUse and PostToolUse currently intercept:

- `Bash`
- `apply_patch`
- MCP tools

The docs explicitly say they do not intercept WebSearch or other non-shell/non-MCP tools, and that interception of the newer `unified_exec` shell mechanism is incomplete.

Consequently, ordinary source inspection is generally visible to hooks only as a shell operation, such as:

- `cat`
- `sed`
- `head`/`tail`
- `rg` with context/output
- language-specific commands
- a rewritten index command

An MCP filesystem server can expose a distinct read name such as `mcp__filesystem__read_file`, which is matchable and receives structured arguments. That is the only currently documented Codex path that gives Raven a reliably discrete, semantic read operation.

Upstream issue evidence also reports that built-in filesystem-adjacent handlers such as `list_dir` and `view_image` lacked Pre/PostToolUse payload implementations in Codex 0.125.0. This issue is useful corroboration, but it is an open issue rather than normative documentation.

**Conclusion on the key unknown:** Codex does not currently provide Raven with a universal matchable `Read` tool comparable to Claude Code’s `Read`.

## Q5. Practical limits and process semantics

### Claude Code

#### Input

Command hooks receive event JSON on stdin. Common fields include:

- `session_id`
- `transcript_path`
- `cwd`
- `permission_mode` where applicable
- `hook_event_name`
- event-specific fields such as `tool_name`, `tool_input`, `tool_use_id`, and `tool_response`

#### Output and exit codes

- Exit 0: stdout may be parsed as structured JSON.
- Exit 2: blocking error; JSON is ignored, and stderr becomes model-visible feedback according to event semantics.
- Other non-zero codes: normally non-blocking errors.
- Structured JSON must be the only stdout content.
- Output strings are capped at 10,000 characters; oversized content is moved to a file and replaced with a preview/path.

#### Timeouts

Most command, HTTP, and MCP-tool hooks default to 600 seconds. Exceptions include:

- `UserPromptSubmit`: 30 seconds.
- `MessageDisplay`: 10 seconds.
- `SessionEnd`: 1.5 seconds by default, adjustable subject to its overall budget.
- Agent hooks: 60 seconds.

#### Platforms

As of Claude Code v2.1.139, macOS/Linux command hooks run without a controlling terminal; they and their children cannot open `/dev/tty`. Windows has no `/dev/tty`. Use `systemMessage` or `terminalSequence` rather than terminal writes. Exec-form commands plus explicit `args` are the most portable option.

#### Content returned to model

Yes, through event-specific `additionalContext`, plain stdout on selected events, stderr on blocking exit 2, or `updatedToolOutput` on PostToolUse.

### Codex CLI

#### Input

Each command hook receives one JSON object on stdin. Shared fields include:

- `session_id`
- `transcript_path`
- `cwd`
- `hook_event_name`
- `model`
- `turn_id` on turn-scoped events
- `permission_mode` on relevant events

Tool events additionally receive `tool_name`, `tool_use_id`, `tool_input`, and for PostToolUse, `tool_response`.

The transcript format is explicitly not a stable hook interface.

#### Output and exit codes

- Exit 0 with no output: success.
- JSON stdout: interpreted according to the event.
- Plain stdout is ignored for PreToolUse and PostToolUse.
- Exit 2 plus stderr: blocking/feedback behavior.
- `systemMessage` is UI/event-stream output.
- `suppressOutput` is parsed but not implemented.
- Unsupported output fields cause the hook run to be marked failed, after which Codex may continue the tool call.

#### Timeouts and handlers

- Default timeout: 600 seconds.
- `timeout` is expressed in seconds.
- Only `type: "command"` handlers execute.
- `prompt` and `agent` are parsed but skipped.
- `async: true` is parsed but unsupported and causes the handler to be skipped.
- Matching handlers run concurrently.

#### Platforms and trust

- `commandWindows`/`command_windows` supplies a Windows override.
- Managed hook directories differ between Windows and macOS/Linux.
- Project and plugin hooks must be reviewed and trusted by the user; modifications change their trust hash.
- Managed hooks can be enforced by policy and cannot be disabled through the user hook browser.

#### Content returned to model

Yes, through supported `additionalContext`, blocking feedback, user-prompt/session context, and PostToolUse feedback replacement. There is no documented general arbitrary tool-output replacement field.

## Q6. Feasibility verdict by mechanism

| Harness     | Deny-based gating of large reads                                                                                                                                                                                                      | Transform-based skeleton injection                                                                                                                                                                                                                                                |
| ----------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Claude Code | **Feasible and deterministic for `Read`.** Match `Read`, inspect `file_path` and optionally file size, then deny with instructions. Also guard Bash if bypass matters.                                                                | **Feasible.** Best implementation: `PostToolUse` on `Read` returning schema-valid `updatedToolOutput`. Alternatively redirect/limit input in PreToolUse.                                                                                                                          |
| Codex CLI   | **Partially feasible, not a complete boundary.** Match `Bash`, parse likely read commands, and deny. Also match configured MCP read tools. Incomplete `unified_exec` and absent universal `Read` coverage prevent a strong guarantee. | **Feasible only through rewriting supported input**, such as changing `cat large.py` to `maki index large.py`, or rewriting MCP arguments. PostToolUse lacks a documented general replacement-output field; feedback replacement is too limited for a clean transparent skeleton. |

## Final verdict

Claude Code can support a shippable skeleton-first read hook: use `PreToolUse` on `Read` for strict gate-first enforcement, or `PostToolUse.updatedToolOutput` for transparent skeleton substitution. Codex can support a useful but weaker hook by inspecting and rewriting or denying `Bash` read commands, with stronger behavior available when reads are deliberately routed through an MCP filesystem/index tool. Codex’s lack of a universal `Read` tool, incomplete shell interception, and lack of a general `updatedToolOutput` equivalent mean Raven should not describe Codex enforcement as deterministic across all read paths. The portable cross-harness baseline is therefore **advisory guidance plus deny/rewrite hooks where observable**; full transparent transformation should be offered as a Claude-specific capability and, for Codex, as an MCP-mediated capability.

## Open questions for implementation

This research settled the hook *plumbing* (can a hook intercept a read, and how the
two harnesses differ). It did not settle the *payload* — what actually flows through
that hook. The following must be answered before committing to a design.

### 1. The skeleton generator — resolved

The best default generator is **ast-grep**, invoked as a directly installed native
binary. It produces exact tree-sitter start/end ranges as JSON, embeds parsers for
Raven's major target languages, tolerates partial syntax, and works as a stateless
one-shot process. A local benchmark with ast-grep 0.43.0 on an 802-line synthetic
Python file measured roughly 120–140 ms per direct invocation; invoking through
`npm exec` took roughly 2.4–2.6 seconds and is unsuitable for a read hook.

The best opportunistic fallback is **Universal Ctags**, provided Raven verifies that
it is Universal Ctags, that JSON support is compiled in, and that each emitted tag
actually includes an `end` field. LSP `textDocument/documentSymbol` offers exact,
semantically rich ranges when a compatible server is already running, but cold-starting
and initializing a language server for each read is too expensive and operationally
complex. The final degraded mode is `rg`, which can locate declaration starts but can
only infer approximate ending lines.

Detailed generator research appears below under **Source-code skeleton generators**.

### 2. Claude's exact `Read` output schema — RESOLVED (empirically)

Tested with a live headless probe (Claude Code 2.1.183): a `PostToolUse` hook on
`Read` returned a valid, correctly-shaped `hookSpecificOutput.updatedToolOutput`
(a plain string sentinel). A marker file confirmed the hook fired, yet Claude
received the **original file contents**, not the sentinel.

**Conclusion: `updatedToolOutput` does not replace the built-in `Read` tool's
result.** A plain-string replacement is silently ignored. The public docs never
document a `Read` output schema, so a "schema-matching" replacement cannot be
constructed reliably either. Therefore the rung-3 transparent transform is **not
viable** for `Read`; rung 2 (the gate) is the correct mechanism. Probe preserved
under `docs/research/gap2-probe/` for re-verification against future versions.

### 3. Codex read *behavior*, not just tool surface

The only clean Codex read path is an MCP filesystem tool. Confirm empirically whether
Codex actually routes reads through a configured MCP fs server, or still defaults to
`cat`/`sed`/`rg` shell reads even when one is present. If the model won't choose the
MCP read on its own, that path is theoretical and Codex collapses to brittle
Bash-command parsing. Likely needs a test, not docs.

### 4. Empirical token savings

The justification currently imports Maki's measured numbers for Maki's setup. A small
benchmark on representative files/languages should confirm skeleton-first nets a real
saving (and does not just trade a read for a deny-loop) before shipping.

### Lower-priority behavioral checks (design/test, not doc research)

- Deny-loop risk: does the agent re-issue the same read after a deny instead of
  fetching the skeleton?
- Whether the local file read still happens (only model-visibility is saved, not disk
  I/O or telemetry).

## Source-code skeleton generators

**Research date:** June 18, 2026.

### Recommendation

Use **ast-grep as Raven's default generator** when a directly installed `ast-grep`
binary is available. It ships as a native executable with parsers embedded for Raven's
major target languages, runs statelessly on one file, recovers reasonably from syntax
errors, and emits exact byte, line, and column ranges as JSON. The main implementation
cost is maintaining a small, tested per-language table of tree-sitter node kinds and a
few structural rules for declarations such as arrow functions.

Use **Universal Ctags as the fallback**, but request the `end` field and accept an
entry as exact only when both `line` and `end` are present. Use an already-running LSP
bridge as a future enhanced backend, but do not cold-start a language server from a
per-read hook. When neither structural tool is available, use `rg` to provide
start-only declaration hints and label any inferred ending lines as approximate.

### Comparison

| Candidate | Exact end-line support | Language coverage | Approximate per-call cost for ~1,000 lines | Install burden | Stateless? | Failure behavior |
| --- | --- | --- | --- | --- | --- | --- |
| **ast-grep 0.43.0** | **Yes.** JSON includes `range.start` and exclusive `range.end`, both with line and column. | Built-in parsers for major languages including Python, JavaScript, TypeScript/TSX, Rust, Go, Java, Kotlin, Swift, C/C++, C#, Ruby, PHP, Elixir, HTML/CSS, JSON, YAML, HCL, Lua, Nix, Scala, Solidity, and Haskell. | **Measured locally: 120–140 ms** for a direct native executable on an 802-line Python file. `npm exec` took 2.4–2.6 s and is unsuitable. | One native executable; built-in languages need no grammar downloads. Custom languages require a compiled tree-sitter grammar. | **Yes.** | Tree-sitter error recovery usually preserves unaffected declarations. Unsupported languages or invalid node kinds fail nonzero or return no matches. |
| **Tree-sitter CLI 0.26.9 plus queries/wrapper** | **Yes.** Parse-tree nodes carry exact start/end positions. | Potentially any tree-sitter grammar. Each language needs a compatible grammar and symbol query. | Parser work is fast, but process startup and grammar loading remain. Not benchmarked here. | CLI plus compiled grammars, query files, and often Node plus a C/C++ compiler to build parsers. | Technically yes, but cumbersome. | Strong syntax-error recovery; missing or incompatible grammars fail before useful output. Raw parse output is too verbose without queries or a wrapper. |
| **Universal Ctags 6.2-series/current Universal Ctags** | **Conditional.** Modern Universal Ctags has an `end` field, but individual parsers and tag kinds may omit it. | Very broad language and file-format coverage; exact capabilities vary by build and parser. | Generally expected to be low, often tens of milliseconds, but not benchmarked here. | One native executable. Must reject Exuberant/BSD ctags and verify JSON support through `--list-features`. | **Yes.** No tags database is needed for one-file output. | Tolerates many incomplete files, but may silently omit symbols or `end`; output fields must be validated per tag. |
| **LSP `textDocument/documentSymbol`** | **Yes by protocol.** `DocumentSymbol.range` covers the declaration and `selectionRange` identifies its name. | Potentially excellent, but every language needs its own server and toolchain. | Warm requests are suitable for editor use; cold launch, `initialize`, workspace loading, and indexing can take hundreds of milliseconds to seconds. | LSP client/bridge plus one language server per language, often plus the project's runtime or SDK. | **No, practically.** Designed for a persistent initialized process. | Servers may require a workspace, return partial/no symbols while indexing, or differ in which declarations they expose. |
| **`rg` declaration patterns** | **No.** It emits declaration start lines only. End lines must be approximated. | Only languages for which Raven maintains regular expressions. | Usually a few milliseconds. | `rg` only. | **Yes.** | Predictable but structurally inaccurate around multiline declarations, decorators, macros, nesting, and unusual syntax. |

### ast-grep

#### Output fidelity

ast-grep's JSON modes include the complete matched text and a structured range:

```json
{
  "text": "def top_function(x: int) -> int:\n    return x + 1",
  "range": {
    "byteOffset": {"start": 0, "end": 55},
    "start": {"line": 0, "column": 0},
    "end": {"line": 1, "column": 16}
  },
  "file": "sample.py",
  "language": "Python"
}
```

Lines and columns are zero-based. The ending position follows tree-sitter's exclusive
range convention. Convert a result to one-based inclusive lines with:

```python
start = result["range"]["start"]
end = result["range"]["end"]

start_line = start["line"] + 1
if end["column"] == 0 and end["line"] > start["line"]:
    end_line = end["line"]
else:
    end_line = end["line"] + 1
```

#### Python command

```bash
ast-grep run \
  --lang python \
  --kind 'function_definition, class_definition' \
  --json=stream \
  -- "$file"
```

For this source:

```python
def top_function(x: int) -> int:
    y = x + 1
    return y

class Greeter:
    def greet(self) -> str:
        return "Hello"
```

ast-grep 0.43.0 produced results with these ranges:

```text
function_definition  top_function  1-3
class_definition     Greeter       5-7
function_definition  greet         6-7
```

Methods appear separately because Python represents methods as nested
`function_definition` nodes.

#### TypeScript command

```bash
ast-grep run \
  --lang typescript \
  --kind 'function_declaration, class_declaration, interface_declaration, type_alias_declaration, enum_declaration, method_definition' \
  --json=stream \
  -- "$file"
```

For representative TypeScript containing an interface, class, constructor, method,
and exported function, the result ranges were:

```text
interface_declaration  User          1-4
class_declaration      UserService   6-12
method_definition      constructor   7-7
method_definition      load          9-11
function_declaration   formatUser   14-16
```

Variable-declared functions such as `const helper = () => {}` need structural rules
that constrain a `variable_declarator` or `lexical_declaration` to an `arrow_function`
or `function_expression`; a broad node-kind selector would incorrectly include ordinary
constants.

#### Invocation cost

A local benchmark used an 802-line synthetic Python file with 100 classes, 100 methods,
and 100 top-level functions. Direct native-binary runs measured:

```text
0.14 s
0.12 s
0.13 s
0.14 s
0.13 s
```

The equivalent `npm exec --package=@ast-grep/cli@0.43.0` invocation measured roughly
2.4–2.6 seconds even with the package available. Raven should therefore execute a
preinstalled `ast-grep` binary directly and never put `npx` or `npm exec` on the
read-interception path.

#### Language and installation behavior

Built-in languages require no separate grammar downloads. Custom languages require a
compiled tree-sitter dynamic library and configuration, so Raven should treat only
built-in parsers as zero-configuration support. Installation is available through
release binaries and common package managers, but Raven should detect the executable
rather than install it automatically.

Use the name `ast-grep`, not `sg`: on some Linux systems `/usr/bin/sg` is the unrelated
`setgroups` utility.

#### Production parsing

Raven should maintain a versioned map of language aliases to symbol node kinds, plus
YAML structural rules where a node-kind union is insufficient. Sort results by
`(start_line ascending, end_line descending)`, deduplicate exact
`(start, end, kind, name)` duplicates, and cap output by symbol count or byte size.

The symbol name should preferably come from a named metavariable such as `$NAME` in an
ast-grep rule. As a fallback, parse only the declaration header or emit a compact
signature instead of trying to extract a bare name from the complete matched body.

### Raw tree-sitter CLI or thin wrapper

Tree-sitter nodes intrinsically include exact start/end points. Raw parse output resembles:

```text
(module [0, 0] - [6, 22]
  (function_definition [0, 0] - [2, 12]
    name: (identifier [0, 4] - [0, 16]))
  (class_definition [4, 0] - [6, 22]
    name: (identifier [4, 6] - [4, 13])))
```

The commands are conceptually:

```bash
tree-sitter parse sample.py
tree-sitter query queries/python-symbols.scm sample.py
```

A Python symbol query can capture declaration nodes and names:

```scheme
(function_definition
  name: (identifier) @name) @definition.function

(class_definition
  name: (identifier) @name) @definition.class
```

The raw CLI is not a complete generator for Raven. It requires a compatible compiled
grammar and query files for each language, and Raven must parse captures into symbols.
Managing grammar source or shared libraries, ABI compatibility, platform-specific
artifacts, and per-language queries recreates the wrapper/runtime that Raven is trying
to avoid. ast-grep is effectively the packaged thin wrapper Raven would otherwise need
to build.

### Universal Ctags

Modern Universal Ctags can emit JSON Lines containing `line` and, where supported by
the parser, `end`:

```bash
ctags \
  --options=NONE \
  --output-format=json \
  --fields=+{line}{end}{scope}{signature} \
  --extras=-p \
  -o - \
  -- "$file"
```

Representative Python output has this shape:

```json
{"_type":"tag","name":"top_function","path":"sample.py","language":"Python","line":1,"kind":"function","end":3,"signature":"(x: int)"}
{"_type":"tag","name":"Greeter","path":"sample.py","language":"Python","line":5,"kind":"class","end":7}
{"_type":"tag","name":"greet","path":"sample.py","language":"Python","line":6,"kind":"method","scope":"Greeter","end":7}
```

The same command applies to TypeScript, optionally adding
`--languages=TypeScript`. Representative objects contain interface, class, method, and
function tags with `line`, and may contain `end` where the TypeScript parser records the
scope boundary.

Raven must validate the installed implementation and capabilities:

```bash
ctags --version
ctags --list-features
ctags --output-format=json --list-fields
ctags --list-languages
ctags --list-kinds-full=Python
ctags --list-kinds-full=TypeScript
```

The version output must identify **Universal Ctags**, not Exuberant Ctags or a BSD
implementation. JSON output requires a build with `libjansson` support. For every tag:

```text
line and end are integers -> exact range
line only                -> start-only or approximate range
neither                   -> discard
```

Do not treat exit code 0 as proof that all symbols have exact ending lines.

### LSP `textDocument/documentSymbol`

The LSP protocol's hierarchical `DocumentSymbol` result is the most semantically direct
representation:

```json
{
  "name": "Greeter",
  "kind": 5,
  "range": {
    "start": {"line": 4, "character": 0},
    "end": {"line": 7, "character": 0}
  },
  "selectionRange": {
    "start": {"line": 4, "character": 6},
    "end": {"line": 4, "character": 13}
  },
  "children": []
}
```

`range` covers the complete declaration, including children; `selectionRange` identifies
the symbol name. Positions are zero-based and ending positions are exclusive.

A raw request is:

```json
{
  "jsonrpc": "2.0",
  "id": 4,
  "method": "textDocument/documentSymbol",
  "params": {
    "textDocument": {
      "uri": "file:///repo/sample.py"
    }
  }
}
```

The operational problem is lifecycle cost. A client must normally start the server,
perform `initialize`/`initialized`, open or synchronize the document, and then request
symbols. Each language also needs its own server, such as basedpyright/Pyright for
Python, typescript-language-server for TypeScript, gopls for Go, rust-analyzer for Rust,
clangd for C/C++, or SourceKit-LSP for Swift. Servers may require a recognized workspace
and may return partial or no results while indexing.

LSP is therefore appropriate only when Raven can positively detect and query an
already-running compatible bridge. The presence of an MCP language-server bridge does
not by itself prove that it exposes raw `documentSymbol` or that the coding harness will
route reads through it.

### Minimal `rg` degraded mode

The degraded mode is a declaration locator, not a true AST skeleton.

Python:

```bash
rg --line-number --no-heading \
  '^[[:space:]]*(async[[:space:]]+def|def|class)[[:space:]]+[A-Za-z_][A-Za-z0-9_]*' \
  -- "$file"
```

TypeScript/JavaScript:

```bash
rg --line-number --no-heading \
  '^[[:space:]]*(export[[:space:]]+)?(default[[:space:]]+)?(async[[:space:]]+)?(function|class|interface|type|enum|namespace)[[:space:]]+[A-Za-z_$][A-Za-z0-9_$]*|^[[:space:]]*(export[[:space:]]+)?(const|let|var)[[:space:]]+[A-Za-z_$][A-Za-z0-9_$]*[[:space:]]*=' \
  -- "$file"
```

An inferred range can use `next_declaration_start - 1`, with EOF as the last range's
end. This is incorrect for nested methods and declarations at different nesting levels,
so Raven must label the result:

```text
Approximate declaration ranges; AST generator unavailable.
```

The degraded mode should generally omit methods rather than imply that one portable
regular expression can recover indentation or brace nesting accurately.

### Concrete Raven backend order

```text
1. Directly installed ast-grep with a supported built-in language
2. Universal Ctags with JSON support; exact only when each tag has `end`
3. Already-running LSP bridge exposing documentSymbol, when explicitly configured
4. rg declaration starts with clearly marked approximate ranges
```

For ast-grep, parse each JSON line into `(symbol, start_line, end_line)` using the
exclusive-range conversion above. Return a compact hierarchy or sorted flat list, for
example:

```text
class Greeter                       5-7
  method greet                     6-7
function top_function              1-3
```

## Sources

- [Anthropic — Claude Code Hooks reference](https://code.claude.com/docs/en/hooks) — live, unversioned documentation accessed June 18, 2026; page includes behavior through at least Claude Code v2.1.139.
- [Anthropic — Automate actions with hooks](https://code.claude.com/docs/en/hooks-guide) — live, unversioned documentation accessed June 18, 2026.
- [OpenAI — Codex Hooks](https://developers.openai.com/codex/hooks) — live, unversioned release-behavior reference accessed June 18, 2026.
- [OpenAI Codex repository — tool registry](https://github.com/openai/codex/blob/main/codex-rs/core/src/tools/registry.rs) — `main` branch accessed June 18, 2026; use cautiously because OpenAI notes `main` schemas may lead released behavior.
- [OpenAI Codex issue #20204 — inconsistent hook coverage](https://github.com/openai/codex/issues/20204) — filed April 29, 2026; tested against Codex CLI 0.125.0, non-normative corroboration.

- [ast-grep — JSON mode](https://ast-grep.github.io/guide/tools/json.html) — accessed June 18, 2026; documents structured `pretty`, `compact`, and JSON Lines `stream` output including match ranges.
- [ast-grep — `run` command reference](https://ast-grep.github.io/reference/cli/run.html) — accessed June 18, 2026; documents `--lang`, `--kind`, and JSON output options.
- [ast-grep — built-in languages](https://ast-grep.github.io/reference/languages.html) — accessed June 18, 2026; authoritative list of embedded language parsers and CLI aliases.
- [ast-grep — custom languages](https://ast-grep.github.io/advanced/custom-language.html) — accessed June 18, 2026; documents the compiled tree-sitter dynamic-library requirement for non-built-in languages.
- [Tree-sitter — `parse`](https://tree-sitter.github.io/tree-sitter/cli/parse.html) — accessed June 18, 2026; documents parsing source files with an installed parser.
- [Tree-sitter — `query`](https://tree-sitter.github.io/tree-sitter/cli/query.html) — accessed June 18, 2026; documents applying tree-sitter query files to source paths.
- [Universal Ctags — JSON output](https://docs.ctags.io/en/latest/man/ctags-json-output.5.html) — accessed June 18, 2026; documents JSON Lines output and the optional `libjansson` build dependency.
- [Universal Ctags — main manual](https://docs.ctags.io/en/latest/man/ctags.1.html) — accessed June 18, 2026; documents output formats and the Universal Ctags `end` field.
- [Universal Ctags — tags format changes](https://docs.ctags.io/en/latest/output-tags.html) — accessed June 18, 2026; documents requesting the `end` field through `--fields`.
- [Language Server Protocol 3.17 — document symbols](https://microsoft.github.io/language-server-protocol/specifications/lsp/3.17/specification/#textDocument_documentSymbol) — accessed June 18, 2026; defines `DocumentSymbol.range` and `selectionRange`.
