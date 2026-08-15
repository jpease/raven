# Discovered-Work Triage

## Problem

Work found mid-task that falls outside the current issue's scope reliably
ends up as a comment on the current issue or its parent epic, where nothing
schedules it and nobody sees it. Observed repeatedly, most often when a
sub-agent reports a finding the parent then absorbs into prose.

Four mechanisms produce this:

1. **The rule is one undefined line.** `raven-github-issues` step 8 (and its
   GitLab twin) says "If new durable work is discovered: create follow-up
   issues, do not expand scope silently." `durable` is never defined, so
   ambiguous findings drift to the cheapest disposition — and a comment is by
   far the cheapest, needing no title, labels, parent, or acceptance criteria.
2. **No completion gate.** `raven-task-complete` checks tests, diff scope,
   debug scaffolding, and lint. It never asks what was found that is *not* in
   the diff, so there is no forcing function at the one moment the agent still
   has full recall.
3. **Findings die at the sub-agent boundary.** `raven-security-reviewer`,
   `raven-refactor-reviewer`, `raven-test-debugger`, and
   `raven-codebase-cartographer` are told to "return concise findings." The
   parent's contract is "finish my task." Nobody owns triage of findings that
   fall outside the current issue, and the parent's own compaction eats them.
4. **`raven-delegate-or-inline`** specifies the output *shape* a sub-agent
   should return but says nothing about the disposition of out-of-scope
   findings.

A comment is not inherently wrong: a comment on the epic that *links to a filed
issue* is good practice. The failure mode is comment-**instead-of**-issue.

## Goal

Every finding outside the current issue's acceptance criteria receives an
explicit, stated disposition before the unit of work can be declared done.
Silence stops being a passing state.

## Constraints

- **The issue skills are platform-gated.** `PLATFORM_GATED_SKILLS` in
  `scripts/raven_lib/config.py` excludes `raven-github-issues` unless
  `platform = "github"`, and excludes both issue skills at `platform = "none"`.
  The rule therefore cannot live only in the issue skills.
- **`raven-task-complete` is universal but tight.** It is `model: haiku` and
  capped at `<65` lines by `tests/test_skills.py::TaskCompleteSkillTests`
  (currently 58). It is the right *gate* but the wrong *home* for a nuanced
  triage table.
- **Sub-agent contracts are duplicated and unguarded.** `common/.claude/agents/*.md`
  and `common/.codex/agents/*.toml` carry the same prose in two formats, and no
  test enforces parity between them.
- **`common/AGENTS.md` is always-loaded** and budgeted at 1110 words in
  `scripts/self-check.py::validate_context_budget`; it currently uses 942,
  leaving 168 words of headroom.
- **Adding a skill costs no symlinks.** Language trees symlink `.agents/skills`
  and `.codex/agents` as whole directories. It does cost skill-index words:
  `SKILL_DESCRIPTION_AGGREGATE_LIMIT` (`scripts/self-check.py`) must rise, which
  its own comment sanctions "only alongside a new skill."

## Design

### The disposition contract

A new tracker-agnostic skill, `raven-triage-discovery`, canonical at
`common/.agents/skills/raven-triage-discovery/SKILL.md`. It owns exactly one
thing: every finding raised during a unit of work that is not already covered
by the current issue's acceptance criteria is assigned exactly one disposition.

| Disposition | Meaning | Required action |
|---|---|---|
| **FOLD IN** | Within the current issue's stated scope | Fix in this diff; note it in the completion summary |
| **FILE** | Real work, outside current scope | Create a new issue, linked to the parent/epic as a sub-issue |
| **DROP** | Considered and rejected | State the reason to the user in the completion summary |

Three rules make the contract bite:

1. **Comment-only is not a disposition.** A comment on the current issue or its
   epic is legitimate only as a pointer *to* a filed issue, never as the
   terminal record of new work. Stated as an explicit prohibition, because it
   is the exact observed failure mode.
2. **Ambiguity resolves to FILE.** When the choice between FILE and DROP is
   unclear, file. A closable issue costs less than an invisible one.
3. **FILE means sub-issue, not orphan.** `gh issue create --parent <epic>` puts
   the issue in the epic's task list, where it is actually visible — that is
   the difference between "filed" and "seen." Where `--parent` is unavailable
   (gh < 2.49, GitLab), add a task-list checkbox to the parent body instead.

### Degraded mode at `platform = "none"`

With no tracker configured, FILE has no destination. It degrades to: record the
item in the repository's existing durable planning location (`.raven/plans/`, or
whatever convention the repo already uses) **and** state it in the completion
summary. Never a chat-only mention — chat is exactly as invisible as the epic
comment this design exists to eliminate.

`raven-triage-discovery` is therefore **not** added to `PLATFORM_GATED_SKILLS`.
It installs at every platform, because FOLD IN, DROP, and the sub-agent contract
are all tracker-independent.

### Enforcement point 1: the completion gate

`raven-task-complete` gains a Process step requiring the agent to enumerate
discovered work and state each item's disposition. "No discovered work" must be
said explicitly — the skill already establishes this pattern with its
`Intent: none` escape hatch, and the same shape applies here. Silence is not
passing.

### Enforcement point 2: the sub-agent boundary

All four shipped reviewer agents gain a required output section,
`## Out Of Scope Findings`, present-but-empty when there are none.
`raven-delegate-or-inline` requires the delegating brief to demand that section
and treats a return without it as incomplete.

This closes the leak actually observed: the parent cannot silently absorb what
the sub-agent found, because the section's absence is itself a defect in the
return. The parent — not the sub-agent — remains responsible for dedupe,
titling, epic linkage, and filing. Sub-agents stay read-only with respect to the
tracker, which avoids duplicate issues from parallel agents and keeps filing
where the repository context lives.

## Change Surface

**New (1)**

- `common/.agents/skills/raven-triage-discovery/SKILL.md` — sections following
  house style: `Skip When`, `Required Constraints`, the disposition table,
  `Rationalization Check`, `Output`.

**Edited skills (4)**

- `raven-task-complete/SKILL.md` — one Process step, one Rationalization row,
  one Output line. Line ceiling moves from `<65` to `<75` with a justification
  comment in the test, matching how `raven-debloat`'s raise was documented.
- `raven-github-issues/SKILL.md` — step 8 rewritten to delegate the decision to
  `raven-triage-discovery` and supply the GitHub mechanics (`--parent`
  sub-issue; backlink comment on the epic pointing *to* the new issue).
- `raven-gitlab-issues/SKILL.md` — same shape, `glab` mechanics.
- `raven-delegate-or-inline/SKILL.md` — `How To Delegate` gains the
  `## Out Of Scope Findings` requirement.

**Edited agent contracts (8)**

- `common/.claude/agents/raven-{security-reviewer,refactor-reviewer,test-debugger,codebase-cartographer}.md`
- `common/.codex/agents/raven-{security-reviewer,refactor-reviewer,test-debugger,codebase-cartographer}.toml`

**Edited always-loaded (1)**

- `common/AGENTS.md` — one sentence in `Delegation`, within the 168-word headroom.

**Edited infra (1)**

- `scripts/self-check.py` — raise `SKILL_DESCRIPTION_AGGREGATE_LIMIT` by exactly
  the new description's word count, preserving the documented 4-word slack, and
  extend the comment to record this as the second sanctioned raise.

**Deliberately unchanged**

- `PLATFORM_GATED_SKILLS` in `scripts/raven_lib/config.py` — no entry, per
  degraded mode above.
- No new symlinks: `.agents/skills` and `.codex/agents` are directory symlinks,
  and all four `.claude/agents/*.md` per-file symlinks already exist.

## Testing

- `tests/test_skills.py` — new `TriageDiscoverySkillTests`: required sections
  present; all three disposition buckets present; the comment-only prohibition
  present; ambiguity-resolves-to-FILE present; line ceiling.
- `tests/test_skills.py` — extend `TaskCompleteSkillTests`: raised ceiling, and
  the discovered-work step exists and precedes the `Output` section.
- `tests/test_skills.py` — assert both issue skills reference
  `raven-triage-discovery`.
- `tests/test_skills.py` — **new parity test**: all four agents in *both*
  `.claude/agents/*.md` and `.codex/agents/*.toml` carry the required output
  section. This closes the pre-existing gap where nothing kept the two adapter
  formats in sync.
- `tests/test_config.py` — assert `raven-triage-discovery` installs under
  `platform = "github"`, `"gitlab"`, and `"none"`.
- `python scripts/self-check.py` per `CLAUDE.md`.

## Rejected Alternatives

- **Guidance-only, no completion gate.** Rewriting the rule more forcefully in
  the issue skills relies on the same soft-rule mechanism that already failed.
  Rejected: the gate is what converts the rule from advisory to checkable.
- **Sub-agents file issues directly.** Nothing could be lost to parent
  compaction, but parallel agents would file duplicates, titles would drift, and
  read-only audit agents would gain write authority over the tracker. Rejected
  in favor of parent-triages.
- **Split by confidence** (sub-agent files high-confidence findings, returns the
  rest). More faithful triage in principle, but the most complex contract to
  specify and the easiest to misapply. Rejected as unfavorable complexity.
- **Default-file with narrow exceptions**, and **a criteria-based bar**. Both
  leave a judgment gap — precisely where the observed failures happened — and
  neither gives the agent vocabulary for "considered and rejected." Rejected in
  favor of forced three-way disposition.
- **Putting the disposition table directly in `raven-task-complete`.** Avoids a
  new skill, but bloats an always-run `model: haiku` skill with tracker
  mechanics, and would still need a home for the tracker-independent rules at
  `platform = "none"`.
