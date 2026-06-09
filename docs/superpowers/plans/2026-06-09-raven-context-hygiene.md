# Raven Context Hygiene Skill — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `raven-context-hygiene` skill that prompts users to `/clear` or `/compact` at natural task boundaries.

**Architecture:** One new skill file in `common/.agents/skills/`; one edit to `raven-project-lifecycle`; run `raven.py upgrade --destination .` to self-install both into the repo root and update the manifest. No code changes — all files are markdown.

**Tech Stack:** Markdown, `raven.py` installer, `self-check.py`

---

### Task 1: Create the new skill source file

**Files:**
- Create: `common/.agents/skills/raven-context-hygiene/SKILL.md`

- [ ] **Step 1: Create the skill file**

Create `common/.agents/skills/raven-context-hygiene/SKILL.md` with this exact content:

```markdown
---
name: raven-context-hygiene
description: Use at unit completion and when the user signals a new unrelated task is beginning.
---

# Context Hygiene

## Skip When

- The session just started and there is no prior work in context.
- The new request is a direct follow-up to what was just discussed.

## Process

1. Identify the trigger:
   - Unit completion: invoked after `raven-session.py --complete`
   - New-session language: user says something like "now let's work on X" or "next up is Y"
2. Ask: "Looks like we're starting something new — would you like to `/clear` context, `/compact`, or continue as-is?"
3. Wait for response, then proceed accordingly.
```

- [ ] **Step 2: Verify file exists**

```bash
cat common/.agents/skills/raven-context-hygiene/SKILL.md
```

Expected: full file content printed with no errors.

---

### Task 2: Update raven-project-lifecycle to invoke the skill

**Files:**
- Modify: `common/.agents/skills/raven-project-lifecycle/SKILL.md:54-57`

- [ ] **Step 1: Insert the context hygiene step**

In `common/.agents/skills/raven-project-lifecycle/SKILL.md`, replace the Phase 3 steps 4–6:

```
4. Run `python .claude/scripts/raven-session.py --complete <unit-name>`
   - The checkpoint hook validates this before allowing it to succeed
5. If the context block in `session.md` grows large, the script will warn — run `--archive` after user confirmation
6. Advance to the next unit
```

With:

```
4. Run `python .claude/scripts/raven-session.py --complete <unit-name>`
   - The checkpoint hook validates this before allowing it to succeed
5. Invoke `raven-context-hygiene`.
6. If the context block in `session.md` grows large, the script will warn — run `--archive` after user confirmation
7. Advance to the next unit
```

- [ ] **Step 2: Verify the edit**

```bash
grep -A 10 "## Phase 3" common/.agents/skills/raven-project-lifecycle/SKILL.md
```

Expected: steps 1–7 visible, step 5 reads "Invoke `raven-context-hygiene`."

---

### Task 3: Self-install via upgrade and validate

**Files:**
- Modified by upgrade: `.agents/skills/raven-context-hygiene/SKILL.md` (new)
- Modified by upgrade: `.agents/skills/raven-project-lifecycle/SKILL.md`
- Modified by upgrade: `.raven/manifest.json`

- [ ] **Step 1: Run dry-run to confirm expected changes**

```bash
python scripts/raven.py --destination . upgrade --dry-run
```

Expected output includes:
- `add  .agents/skills/raven-context-hygiene/SKILL.md`
- `upgrade  .agents/skills/raven-project-lifecycle/SKILL.md`

- [ ] **Step 2: Apply the upgrade**

```bash
python scripts/raven.py --destination . upgrade
```

Expected: same files listed without errors.

- [ ] **Step 3: Verify installed skill file exists**

```bash
cat .agents/skills/raven-context-hygiene/SKILL.md
```

Expected: full skill content.

- [ ] **Step 4: Verify manifest was updated**

```bash
python3 -c "
import json
d = json.load(open('.raven/manifest.json'))
key = '.agents/skills/raven-context-hygiene/SKILL.md'
print('FOUND' if key in d['files'] else 'MISSING')
print(d['files'].get(key, {}))
"
```

Expected: `FOUND` followed by a dict with `installedSha256`, `kind`, and `sourceSha256`.

- [ ] **Step 5: Run self-check**

```bash
python scripts/self-check.py
```

Expected: `RAVEN self-check passed`

---

### Task 4: Commit

- [ ] **Step 1: Stage and commit**

```bash
git add \
  common/.agents/skills/raven-context-hygiene/SKILL.md \
  .agents/skills/raven-context-hygiene/SKILL.md \
  common/.agents/skills/raven-project-lifecycle/SKILL.md \
  .agents/skills/raven-project-lifecycle/SKILL.md \
  .raven/manifest.json
git commit -m "feat(skills): add raven-context-hygiene skill

Prompts users to /clear or /compact at unit completion and when
explicit new-session language is detected. Integrated into
raven-project-lifecycle Phase 3 as step 5 after --complete."
```

Expected: commit created successfully.
