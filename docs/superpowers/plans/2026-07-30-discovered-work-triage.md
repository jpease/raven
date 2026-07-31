# Discovered-Work Triage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every finding surfaced outside the current issue's scope receive an explicit, stated disposition — FOLD IN, FILE, or DROP — so out-of-scope work stops disappearing into issue and epic comments.

**Architecture:** A new tracker-agnostic skill, `raven-triage-discovery`, owns the disposition contract. Two enforcement points reference it: `raven-task-complete` gates unit completion on stating dispositions, and the four shipped reviewer sub-agents must return a `## Out Of Scope Findings` section that the parent then dispositions. The two platform-gated issue skills supply tracker-specific filing mechanics but no longer own the rule.

**Tech Stack:** Markdown skill/agent templates under `common/`, TOML agent adapters for Codex, Python 3.9+ stdlib-only tests (`unittest`), `scripts/self-check.py` budget validators.

**Spec:** `docs/superpowers/specs/2026-07-30-discovered-work-triage-design.md`

## Global Constraints

- **Edit canonical sources only.** Skills are canonical at `common/.agents/skills/`; language trees symlink `.agents/skills` as a whole directory. Never write to `python/.agents/skills/...` or to the repo-root `.agents/skills/...` — the former is a symlink, the latter is the dogfooded install that `raven upgrade` regenerates.
- **Both agent adapters, always.** `common/.claude/agents/*.md` and `common/.codex/agents/*.toml` duplicate the same prose in two formats. A change to one without the other is the defect Task 3's parity test exists to catch.
- **Python floor is 3.9, stdlib only.** No `tomllib`, no third-party test dependencies.
- **Ruff**: `line-length = 100`, `target-version = "py39"`. The commit hook runs `ruff check .` and `ruff format --check .` and will reject on failure.
- **No AI attribution in commit messages.** The repo's `commit-msg` hook strips `Claude-Session` and `Co-Authored-By` trailers. Do not add them.
- **Conventional Commits** per `raven-commit`.
- **Skill description cap:** 30 words per skill (`SKILL_DESCRIPTION_PER_SKILL_LIMIT`).
- **Do not add an entry to `PLATFORM_GATED_SKILLS`** in `scripts/raven_lib/config.py`. `raven-triage-discovery` must install at every platform, including `none`.

## File Structure

| File | Responsibility | Task |
|---|---|---|
| `common/.agents/skills/raven-triage-discovery/SKILL.md` | The disposition contract (new) | 1 |
| `scripts/self-check.py` | Skill-index word budget ceiling | 1 |
| `tests/test_config.py` | Proves the new skill is not platform-gated | 1 |
| `common/.agents/skills/raven-task-complete/SKILL.md` | Completion gate | 2 |
| `common/.claude/agents/raven-*.md` (4) | Claude sub-agent output contract | 3 |
| `common/.codex/agents/raven-*.toml` (4) | Codex sub-agent output contract | 3 |
| `common/.agents/skills/raven-delegate-or-inline/SKILL.md` | Delegating brief must demand the section | 3 |
| `common/AGENTS.md` | Always-loaded pointer in `Delegation` | 3 |
| `common/.agents/skills/raven-github-issues/SKILL.md` | GitHub filing mechanics | 4 |
| `common/.agents/skills/raven-gitlab-issues/SKILL.md` | GitLab filing mechanics | 4 |
| `tests/test_skills.py` | Guards all skill and agent prose contracts | 1–4 |

---

### Task 1: The `raven-triage-discovery` skill

**Files:**
- Create: `common/.agents/skills/raven-triage-discovery/SKILL.md`
- Modify: `scripts/self-check.py:310-323` (the `SKILL_DESCRIPTION_AGGREGATE_LIMIT` comment and constant)
- Test: `tests/test_skills.py` (new class, appended before `class AdapterNeutralScriptReferenceTests`)
- Test: `tests/test_config.py` (new method inside the existing platform-gating test class, after `test_none_platform_excludes_both_issue_skills`)

**Interfaces:**
- Consumes: `section_region(text_lower, heading)` from `tests/test_skills.py:7`; `REPO_ROOT` from `tests/helpers.py`; `self._skill_entries(platform)` from the platform test class in `tests/test_config.py:300`.
- Produces: the skill path `common/.agents/skills/raven-triage-discovery/SKILL.md` and the exact section headings `## Skip When`, `## Required Constraints`, `## Dispositions`, `## Filing`, `## Rationalization Check`, `## Output`. Tasks 2 and 4 reference the skill by the name `raven-triage-discovery`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_skills.py`, immediately **before** `class AdapterNeutralScriptReferenceTests`:

```python
class TriageDiscoverySkillTests(unittest.TestCase):
    """Guards the discovered-work disposition contract.

    Reads the canonical skill source directly (not the installed root
    copy) since `common/.agents/skills/` is where edits must land.
    """

    def setUp(self):
        path = (
            REPO_ROOT / "common" / ".agents" / "skills" / "raven-triage-discovery" / "SKILL.md"
        )
        self.content = path.read_text(encoding="utf-8")
        self.lowered = self.content.lower()

    def test_stays_under_line_ceiling(self):
        # Same basis as raven-task-complete: this is invoked mid-task, so its
        # cost is paid at the moment context is scarcest. Keep it short.
        self.assertLess(
            len(self.content.splitlines()),
            75,
            "raven-triage-discovery/SKILL.md should stay under ~75 lines",
        )

    def test_declares_the_required_sections(self):
        for heading in (
            "## skip when",
            "## required constraints",
            "## dispositions",
            "## filing",
            "## rationalization check",
            "## output",
        ):
            with self.subTest(heading=heading):
                self.assertIn(heading, self.lowered)

    def test_dispositions_table_names_all_three_buckets(self):
        region = section_region(self.lowered, "## dispositions")
        for bucket in ("fold in", "file", "drop"):
            with self.subTest(bucket=bucket):
                self.assertIn(
                    bucket,
                    region,
                    f"the disposition table must name the {bucket.upper()} bucket",
                )

    def test_comment_only_is_prohibited_as_a_disposition(self):
        # The substance of the whole skill: commenting on the issue or epic is
        # the observed failure mode, so the prohibition is load-bearing text,
        # not decorative wording.
        region = section_region(self.lowered, "## required constraints")
        self.assertIn(
            "is not a disposition",
            region,
            "expected a Required Constraint stating that a comment on the "
            "issue or its epic is not a disposition",
        )

    def test_ambiguity_resolves_to_filing(self):
        # Without a stated tiebreak, ambiguous findings drift to the cheapest
        # action -- which is exactly how they became comments.
        region = section_region(self.lowered, "## required constraints")
        self.assertIn(
            "is unclear, file",
            region,
            "expected a Required Constraint resolving FILE-vs-DROP ambiguity "
            "toward FILE",
        )
```

Append to `tests/test_config.py`, immediately **after** `test_none_platform_excludes_both_issue_skills`:

```python
    def test_triage_discovery_skill_installs_at_every_platform(self):
        # Deliberately absent from PLATFORM_GATED_SKILLS: FOLD IN, DROP, and the
        # sub-agent reporting contract are all tracker-independent, so the skill
        # must ship even where no issue tracker is configured.
        for platform in ("github", "gitlab", "none"):
            with self.subTest(platform=platform):
                entries = self._skill_entries(platform)
                self.assertTrue(
                    any("raven-triage-discovery" in e for e in entries),
                    f"raven-triage-discovery should install at platform={platform}",
                )
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
python -m pytest tests/test_skills.py::TriageDiscoverySkillTests tests/test_config.py -k triage -v
```

Expected: `TriageDiscoverySkillTests` errors in `setUp` with `FileNotFoundError`; `test_triage_discovery_skill_installs_at_every_platform` FAILs on all three subtests.

- [ ] **Step 3: Create the skill**

Create `common/.agents/skills/raven-triage-discovery/SKILL.md` with exactly this content:

```markdown
---
name: raven-triage-discovery
description: Use when work outside the current issue's scope is discovered mid-task and needs an explicit disposition.
---

# Triage Discovery

Work surfaced mid-task that falls outside the current issue's acceptance criteria needs a disposition, not a mention. This skill assigns one.

## Skip When

- The finding is already covered by the current issue's stated acceptance criteria.
- The finding is already tracked by an existing open issue. Link to that issue and move on.

## Required Constraints

- Every finding outside current scope gets exactly one disposition: FOLD IN, FILE, or DROP.
- A comment on the current issue or its epic is not a disposition. It is legitimate only as a pointer to a filed issue, never as the terminal record of new work.
- When the choice between FILE and DROP is unclear, file. A closable issue costs less than an invisible one.
- State every disposition to the user. An unstated DROP is indistinguishable from having forgotten.

## Dispositions

| Disposition | Applies when | Required action |
|---|---|---|
| FOLD IN | The finding is inside the current issue's stated scope | Fix it in this diff; name it in the completion summary |
| FILE | The finding is real work outside current scope | Create a new issue linked to the parent or epic |
| DROP | The finding was considered and rejected | State the reason to the user in the completion summary |

## Filing

- File as a sub-issue so the parent's task list shows it: `gh issue create --parent <n>`, or `glab issue create --parent-id <n>`. An issue nobody sees is the failure this skill exists to prevent.
- Where sub-issue linkage is unavailable (gh older than 2.49, or a tracker without it), add a task-list checkbox to the parent body instead.
- With no tracker configured, record the item in the repository's durable planning location, such as `.raven/plans/`, and state it in the completion summary. Never chat-only.
- Title the issue with the problem. Body carries the evidence: file, symbol, and what you observed.
- After filing, a comment on the parent pointing at the new issue is useful. The reverse — a comment instead of an issue — is the failure mode.

## Rationalization Check

| Thought | Reality |
|---|---|
| "I'll note it in a comment so it isn't lost" | A comment is where findings go to be lost. Comment only to point at a filed issue. |
| "This is too small to file" | Small and real is FILE. Small and rejected is DROP with a reason. Neither is silence. |
| "The epic already mentions this area" | An area is not an issue. Nothing schedules an area. |
| "I'll just fix it while I'm here" | That is FOLD IN only if it is in scope. Otherwise it is silent scope expansion. |
| "I'm not sure it's a real problem" | Then file it. Deciding is the tracker's job, not something to settle by dropping. |
| "The user saw it in my summary" | A summary is chat. Chat is as invisible as the epic comment this skill replaces. |

## Output

State the disposition of every finding before declaring the unit of work done:

> Discovered work: [N] item(s). FOLD IN: [what, now in this diff]. FILED: [#num — title]. DROPPED: [what — why].

When there is none:

> Discovered work: none.
```

- [ ] **Step 4: Run the skill tests to verify they pass**

```bash
python -m pytest tests/test_skills.py::TriageDiscoverySkillTests tests/test_config.py -k triage -v
```

Expected: PASS.

- [ ] **Step 5: Run self-check to observe the budget failure**

```bash
python scripts/self-check.py
```

Expected: FAIL with `Skill-index description budget exceeded: 388 words (limit 376)`.

This is the intended signal — the aggregate limit's own comment permits a raise "only alongside a new skill," which this is.

- [ ] **Step 6: Raise the skill-index budget**

In `scripts/self-check.py`, replace the block ending at `SKILL_DESCRIPTION_AGGREGATE_LIMIT = 376`. Change the paragraph that currently begins `# 372 words in-tree + 4 words of slack.` to:

```python
# 388 words in-tree + 4 words of slack. The slack is deliberately tight: it is
# the same 4 words every previous limit left, so unplanned description growth
# still trips this. Raised from 376 for raven-triage-discovery, a deliberate
# skill addition, not drift -- a new skill needs a description, and the old
# ceiling had no room for one. This is the second such sanctioned raise (the
# first was 362 -> 376 for raven-debloat). Raise this only alongside a new
# skill, and only to the new in-tree total plus that same slack.
```

Then change the constant:

```python
SKILL_DESCRIPTION_AGGREGATE_LIMIT = 392
```

Leave `SKILL_DESCRIPTION_PER_SKILL_LIMIT = 30` unchanged.

- [ ] **Step 7: Re-run self-check**

```bash
python scripts/self-check.py
```

Expected: `skill description budget ok (388 words)` and the run proceeds past that validator.

If self-check later reports a root-install diff, leave it — Task 5 syncs the dogfooded install once all template edits have landed.

- [ ] **Step 8: Run the full suite and formatters**

```bash
ruff format . && ruff check . && python -m pytest tests/ -q
```

Expected: all pass.

- [ ] **Step 9: Commit**

```bash
git add common/.agents/skills/raven-triage-discovery/ scripts/self-check.py tests/test_skills.py tests/test_config.py
git commit -m "feat(skills): add raven-triage-discovery disposition contract

Out-of-scope findings surfaced mid-task had no defined disposition, so
they drifted to the cheapest action -- a comment on the issue or its
epic, where nothing schedules them. The skill forces one of FOLD IN,
FILE, or DROP, prohibits comment-only as a terminal record, and resolves
FILE-vs-DROP ambiguity toward FILE.

Not platform-gated: FOLD IN, DROP, and the sub-agent reporting contract
are tracker-independent, so it ships at platform=none too. Skill-index
budget raised 376 -> 392, the second sanctioned raise for a new skill."
```

---

### Task 2: Completion gate in `raven-task-complete`

**Files:**
- Modify: `common/.agents/skills/raven-task-complete/SKILL.md`
- Test: `tests/test_skills.py` (`class TaskCompleteSkillTests`, around line 533)

**Interfaces:**
- Consumes: the skill name `raven-triage-discovery` produced by Task 1.
- Produces: nothing later tasks depend on.

- [ ] **Step 1: Write the failing tests**

In `tests/test_skills.py`, inside `class TaskCompleteSkillTests`, change the existing ceiling from `65` to `75` and extend its message, then add two methods. The ceiling method becomes:

```python
    def test_stays_under_line_ceiling(self):
        # Raised from 65 when the discovered-work disposition step landed: the
        # step, its rationalization row, and its Output line cost ~7 lines and
        # 58 + 7 == 65 would have tripped the old ceiling exactly. Headroom is
        # one iteration, not a budget to spend.
        self.assertLess(
            len(self.content.splitlines()),
            75,
            "raven-task-complete/SKILL.md should stay under ~75 lines",
        )
```

Add these two methods to the same class:

```python
    def test_process_requires_dispositioning_discovered_work(self):
        # The gate: without a step here, nothing forces the agent to account for
        # findings at the one moment it still has full recall of them.
        region = section_region(self.lowered, "## process")
        self.assertIn(
            "raven-triage-discovery",
            region,
            "expected a Process step routing discovered work to "
            "raven-triage-discovery",
        )

    def test_output_requires_stating_discovered_work(self):
        region = section_region(self.lowered, "## output")
        self.assertIn(
            "discovered work",
            region,
            "expected the Output contract to require stating discovered work, "
            "so silence is not a passing state",
        )
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
python -m pytest tests/test_skills.py::TaskCompleteSkillTests -v
```

Expected: `test_process_requires_dispositioning_discovered_work` and `test_output_requires_stating_discovered_work` FAIL. The ceiling test PASSES (58 < 75) — that is expected; it is being pre-raised for the edit that follows.

- [ ] **Step 3: Add the Process step**

In `common/.agents/skills/raven-task-complete/SKILL.md`, in the `## Process` section, insert a new step between the current step 4 (`Run lint and type-check`) and current step 5 (`State the verification summary`), then renumber the final step to 6:

```markdown
5. **Disposition discovered work** — enumerate anything surfaced during this unit that falls outside the current issue's acceptance criteria, including findings returned by sub-agents, and assign each one a disposition per `raven-triage-discovery`. "None" must be stated, not implied.
6. **State the verification summary** before handing off.
```

- [ ] **Step 4: Add the rationalization row**

In the `## Rationalization Check` table, append this row after the existing `"The code explains itself"` row:

```markdown
| "I noted the other problems in a comment" | A comment is not a disposition. Each finding gets FOLD IN, FILE, or DROP per `raven-triage-discovery`. |
```

- [ ] **Step 5: Add the Output line**

In the `## Output` section, after the existing `Always:` / `> Intent: ...` block, append:

```markdown
Always:

> Discovered work: [each item's disposition per `raven-triage-discovery`]. If none: `Discovered work: none.`
```

- [ ] **Step 6: Run the tests to verify they pass**

```bash
python -m pytest tests/test_skills.py::TaskCompleteSkillTests -v
```

Expected: PASS, including the ceiling test (the file should now be ~65 lines, under 75).

- [ ] **Step 7: Run the full suite and formatters**

```bash
ruff format . && ruff check . && python -m pytest tests/ -q
```

Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add common/.agents/skills/raven-task-complete/SKILL.md tests/test_skills.py
git commit -m "feat(skills): gate task completion on dispositioning discovered work

raven-task-complete checked tests, diff scope, scaffolding, and lint but
never asked what was found outside the diff, so there was no forcing
function at the one moment the agent still had full recall. Adds a
Process step, a rationalization row, and an Output line requiring an
explicit disposition per raven-triage-discovery -- 'none' must be stated,
matching the skill's existing 'Intent: none' escape hatch.

Line ceiling raised 65 -> 75; the edit costs ~7 lines and 58 + 7 would
have tripped the old ceiling exactly."
```

---

### Task 3: Sub-agent reporting contract

**Files:**
- Modify: `common/.claude/agents/raven-security-reviewer.md`
- Modify: `common/.claude/agents/raven-refactor-reviewer.md`
- Modify: `common/.claude/agents/raven-test-debugger.md`
- Modify: `common/.claude/agents/raven-codebase-cartographer.md`
- Modify: `common/.codex/agents/raven-security-reviewer.toml`
- Modify: `common/.codex/agents/raven-refactor-reviewer.toml`
- Modify: `common/.codex/agents/raven-test-debugger.toml`
- Modify: `common/.codex/agents/raven-codebase-cartographer.toml`
- Modify: `common/.agents/skills/raven-delegate-or-inline/SKILL.md` (`## How To Delegate`)
- Modify: `common/AGENTS.md` (`## Delegation`, line 43)
- Test: `tests/test_skills.py` (new class)

**Interfaces:**
- Consumes: the skill name `raven-triage-discovery` from Task 1.
- Produces: the literal heading `## Out Of Scope Findings`, which every agent contract must contain and which `raven-delegate-or-inline` and `common/AGENTS.md` both name.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_skills.py`, immediately **before** `class AdapterNeutralScriptReferenceTests`:

```python
class SubagentOutOfScopeContractTests(unittest.TestCase):
    """Every shipped reviewer agent must return out-of-scope findings.

    Nothing else keeps `common/.claude/agents/*.md` and
    `common/.codex/agents/*.toml` in sync -- they carry the same prose in
    two formats, so a change applied to one silently diverges from the
    other. This class is the only guard on that pair.
    """

    CLAUDE_DIR = REPO_ROOT / "common" / ".claude" / "agents"
    CODEX_DIR = REPO_ROOT / "common" / ".codex" / "agents"
    REQUIRED = "## out of scope findings"

    def test_both_adapter_trees_ship_the_same_agents(self):
        claude = {p.stem for p in self.CLAUDE_DIR.glob("raven-*.md")}
        codex = {p.stem for p in self.CODEX_DIR.glob("raven-*.toml")}
        self.assertTrue(claude, "expected common/.claude/agents to ship raven-* agents")
        self.assertEqual(
            claude,
            codex,
            "adapter agent trees have diverged; one harness would ship a "
            "reviewer the other lacks",
        )

    def test_every_agent_requires_the_out_of_scope_section(self):
        paths = sorted(self.CLAUDE_DIR.glob("raven-*.md")) + sorted(
            self.CODEX_DIR.glob("raven-*.toml")
        )
        self.assertEqual(
            len(paths),
            8,
            f"expected 4 Claude + 4 Codex agent contracts, found {len(paths)}",
        )
        for path in paths:
            with self.subTest(agent=f"{path.parent.name}/{path.name}"):
                self.assertIn(
                    self.REQUIRED,
                    path.read_text(encoding="utf-8").lower(),
                    "agent contract must require an '## Out Of Scope Findings' "
                    "section; without it the parent silently absorbs whatever "
                    "the sub-agent noticed but was not asked about",
                )
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
python -m pytest tests/test_skills.py::SubagentOutOfScopeContractTests -v
```

Expected: `test_both_adapter_trees_ship_the_same_agents` PASSES (trees already match); `test_every_agent_requires_the_out_of_scope_section` FAILS on all 8 subtests.

- [ ] **Step 3: Add the contract to the four Claude agents**

In each of the four files under `common/.claude/agents/`, insert this paragraph immediately **before** the final `Do not edit...` line:

```markdown
Always end your return with an `## Out Of Scope Findings` section listing anything you noticed outside the assigned scope, each with file/line evidence. Write `none` under the heading when there is nothing. Do not omit the section — the caller treats its absence as an incomplete return.
```

For `raven-codebase-cartographer.md` the final line is `Do not edit files. Do not return large code blocks. Batch independent reads or searches when possible.`; for `raven-refactor-reviewer.md` it is `Flag only risks with concrete evidence. Do not perform the refactor.`; for `raven-security-reviewer.md` it is `Do not edit files.`; for `raven-test-debugger.md` it is `Do not edit unless explicitly asked by the main agent.`

- [ ] **Step 4: Add the contract to the four Codex agents**

In each of the four files under `common/.codex/agents/`, insert the same paragraph inside the `developer_instructions = """ ... """` block, immediately before that block's final `Do not edit...` line. Wrap the prose to match the surrounding style in each file (those blocks are hand-wrapped near 85 columns):

```
Always end your return with an "## Out Of Scope Findings" section listing anything
you noticed outside the assigned scope, each with file/line evidence. Write none
under the heading when there is nothing. Do not omit the section -- the caller
treats its absence as an incomplete return.
```

Note the double quotes around the heading rather than backticks, and `--` rather than an em dash, matching the plain-text register of the existing TOML blocks. The literal substring `## Out Of Scope Findings` must survive, since the test matches on it case-insensitively.

- [ ] **Step 5: Run the test to verify it passes**

```bash
python -m pytest tests/test_skills.py::SubagentOutOfScopeContractTests -v
```

Expected: PASS, 8 subtests.

- [ ] **Step 6: Require the section in the delegating brief**

In `common/.agents/skills/raven-delegate-or-inline/SKILL.md`, in `## How To Delegate`, append this bullet after the existing `Before delegating a symbol-editing task...` bullet:

```markdown
- Require an `## Out Of Scope Findings` section in the return, present-but-empty when there are none. A return without it is incomplete: what the sub-agent noticed but you did not ask about is exactly what gets lost. Disposition whatever comes back per `raven-triage-discovery`.
```

- [ ] **Step 7: Point at the contract from always-loaded guidance**

In `common/AGENTS.md`, in the `## Delegation` section, append this sentence to the end of the existing paragraph (currently line 43):

```markdown
Sub-agent returns must include an `## Out Of Scope Findings` section; disposition those findings per `raven-triage-discovery` rather than leaving them in chat or in an issue comment.
```

- [ ] **Step 8: Verify the always-loaded budget still passes**

```bash
python scripts/self-check.py 2>&1 | grep -A2 "validate context budget for always-loaded"
```

Expected: `context budget ok`. `common/AGENTS.md` was 942 words against a 1110 threshold, and this sentence adds roughly 30.

- [ ] **Step 9: Run the full suite and formatters**

```bash
ruff format . && ruff check . && python -m pytest tests/ -q
```

Expected: all pass.

- [ ] **Step 10: Commit**

```bash
git add common/.claude/agents/ common/.codex/agents/ common/.agents/skills/raven-delegate-or-inline/SKILL.md common/AGENTS.md tests/test_skills.py
git commit -m "feat(agents): require sub-agents to report out-of-scope findings

Reviewer agents were told to return findings; the parent's contract was
to finish its task. Nobody owned triage of findings outside the current
issue, and parent compaction ate them. All four agents now must end with
an '## Out Of Scope Findings' section, present-but-empty when there are
none, and raven-delegate-or-inline requires the brief to demand it.

Adds the first parity test over common/.claude/agents/*.md and
common/.codex/agents/*.toml. The two adapters duplicate the same prose in
two formats and nothing previously kept them in sync."
```

---

### Task 4: Issue-skill filing mechanics

**Files:**
- Modify: `common/.agents/skills/raven-github-issues/SKILL.md` (workflow step 8; `## Execution Rules`)
- Modify: `common/.agents/skills/raven-gitlab-issues/SKILL.md` (workflow step 8; `## Execution Rules`)
- Test: `tests/test_skills.py` (new class)

**Interfaces:**
- Consumes: the skill name `raven-triage-discovery` from Task 1.
- Produces: nothing later tasks depend on.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_skills.py`, immediately **before** `class AdapterNeutralScriptReferenceTests`:

```python
class IssueSkillTriageReferenceTests(unittest.TestCase):
    """Both issue skills must delegate the disposition decision.

    The rule they used to own -- 'if new durable work is discovered: create
    follow-up issues' -- left `durable` undefined, and these skills are
    platform-gated, so neither ships at platform=none. The definition lives
    in raven-triage-discovery; these skills supply only tracker mechanics.
    """

    SKILLS_DIR = REPO_ROOT / "common" / ".agents" / "skills"

    def _skill(self, name):
        return (self.SKILLS_DIR / name / "SKILL.md").read_text(encoding="utf-8").lower()

    def test_both_issue_skills_route_discovered_work_to_the_triage_skill(self):
        for name in ("raven-github-issues", "raven-gitlab-issues"):
            with self.subTest(skill=name):
                self.assertIn(
                    "raven-triage-discovery",
                    self._skill(name),
                    "issue skill must route discovered work to "
                    "raven-triage-discovery rather than restating a vague rule",
                )

    def test_neither_issue_skill_still_carries_the_undefined_durable_rule(self):
        for name in ("raven-github-issues", "raven-gitlab-issues"):
            with self.subTest(skill=name):
                self.assertNotIn(
                    "new durable work is discovered",
                    self._skill(name),
                    "the undefined 'durable work' phrasing is what let findings "
                    "drift to comments; it must not survive alongside the "
                    "replacement rule",
                )

    def test_both_issue_skills_prohibit_the_comment_as_terminal_record(self):
        for name in ("raven-github-issues", "raven-gitlab-issues"):
            with self.subTest(skill=name):
                self.assertIn(
                    "pointer to a filed issue",
                    self._skill(name),
                    "issue skills must state that a comment is legitimate only "
                    "as a pointer to a filed issue",
                )
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
python -m pytest tests/test_skills.py::IssueSkillTriageReferenceTests -v
```

Expected: `test_both_issue_skills_route_discovered_work_to_the_triage_skill` and `test_both_issue_skills_prohibit_the_comment_as_terminal_record` FAIL; `test_neither_issue_skill_still_carries_the_undefined_durable_rule` FAILS too (the phrase is still present).

- [ ] **Step 3: Rewrite step 8 in the GitHub skill**

In `common/.agents/skills/raven-github-issues/SKILL.md`, replace workflow step 8:

```markdown
8. If new durable work is discovered: create follow-up issues, do not expand scope silently
```

with:

```markdown
8. Disposition anything discovered outside this issue's acceptance criteria per `raven-triage-discovery` — FOLD IN, FILE, or DROP. Do not expand scope silently, and do not leave new work as a comment on this issue or its epic: a comment is legitimate only as a pointer to a filed issue, never the record of it
```

- [ ] **Step 4: Add the filing-order rule to the GitHub skill**

In the same file, in `## Execution Rules`, append this bullet after the existing `If using raven-project-lifecycle alongside this skill...` bullet:

```markdown
- File discovered work as a sub-issue (`gh issue create --parent <n>`) so it appears in the parent's task list, then comment on the parent pointing at it — never the reverse
```

- [ ] **Step 5: Rewrite step 8 in the GitLab skill**

In `common/.agents/skills/raven-gitlab-issues/SKILL.md`, replace workflow step 8 with the identical text used in Step 3 (the wording is tracker-neutral):

```markdown
8. Disposition anything discovered outside this issue's acceptance criteria per `raven-triage-discovery` — FOLD IN, FILE, or DROP. Do not expand scope silently, and do not leave new work as a comment on this issue or its epic: a comment is legitimate only as a pointer to a filed issue, never the record of it
```

- [ ] **Step 6: Add the filing-order rule to the GitLab skill**

In the same file, in `## Execution Rules`, append this bullet after the existing `If using raven-project-lifecycle alongside this skill...` bullet:

```markdown
- File discovered work as a sub-issue (`glab issue create --parent-id <n>`) so it appears in the parent's task list, then add a note on the parent pointing at it — never the reverse
```

- [ ] **Step 7: Run the test to verify it passes**

```bash
python -m pytest tests/test_skills.py::IssueSkillTriageReferenceTests -v
```

Expected: PASS.

- [ ] **Step 8: Run the full suite and formatters**

```bash
ruff format . && ruff check . && python -m pytest tests/ -q
```

Expected: all pass.

- [ ] **Step 9: Commit**

```bash
git add common/.agents/skills/raven-github-issues/SKILL.md common/.agents/skills/raven-gitlab-issues/SKILL.md tests/test_skills.py
git commit -m "refactor(skills): route issue-skill discovered work to triage contract

Step 8 of both issue skills said 'if new durable work is discovered:
create follow-up issues' without defining durable, so ambiguous findings
took the cheapest path and became comments. Both now delegate the
decision to raven-triage-discovery and keep only tracker mechanics:
file as a sub-issue first, then comment on the parent pointing at it.

The rule could not stay here alone -- both skills are platform-gated and
neither installs at platform=none."
```

---

### Task 5: Self-check and dogfooded install sync

**Files:**
- Modify: repo-root installed copies under `.agents/`, `.claude/`, `.codex/`, `.raven/manifest.json` (regenerated by `raven upgrade`, never hand-edited)

**Interfaces:**
- Consumes: every template edit from Tasks 1–4.
- Produces: nothing.

- [ ] **Step 1: Run the full self-check**

```bash
python scripts/self-check.py
```

Expected: all validators pass, `upgrade --dry-run` reports the new and changed managed files, `upgrade` applies them, and the unit tests pass.

Per `CLAUDE.md`, treat any *unexpected* self-upgrade output as a product issue. Expected output here: `raven-triage-discovery/SKILL.md` added, and `raven-task-complete`, `raven-delegate-or-inline`, `raven-github-issues`, `raven-gitlab-issues`, the four Claude agents, and `AGENTS.md` updated. `raven-gitlab-issues` will be absent from the root install if this repo is configured `platform = "github"` — that is correct gating, not a failure.

- [ ] **Step 2: Inspect the resulting diff**

```bash
git status --short && git diff --stat
```

Confirm only Raven-managed root install paths changed. If `.raven/manifest.json` shows *only* a `ravenVersion` or timestamp change with no content-hash changes, discard that hunk — the manifest self-chases across commits and a version-only diff is noise.

- [ ] **Step 3: Verify no template source was modified by the upgrade**

```bash
git diff --name-only -- common/ scripts/ tests/
```

Expected: empty. The upgrade writes to the install, never back to `common/`. Non-empty output means a symlink was written through and must be investigated before committing.

- [ ] **Step 4: Commit the sync**

```bash
git add -A
git commit -m "chore(self-check): sync root install after triage-discovery template changes"
```

If Step 2 found nothing to commit, skip this step and say so.

- [ ] **Step 5: Final verification**

```bash
ruff format --check . && ruff check . && python -m pytest tests/ -q && python scripts/self-check.py
```

Expected: all pass, and self-check reports no pending upgrade.

---

## Verification Summary

At completion, all of the following must hold:

- `raven-triage-discovery` ships at `platform = "github"`, `"gitlab"`, and `"none"`.
- `raven-task-complete` cannot be satisfied without stating discovered work.
- All 8 agent contracts (4 Claude, 4 Codex) require `## Out Of Scope Findings`, and the parity test guards the pair.
- Both issue skills reference `raven-triage-discovery` and no longer carry the phrase `new durable work is discovered`.
- `python scripts/self-check.py` passes with no pending upgrade.
