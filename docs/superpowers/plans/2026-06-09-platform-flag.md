# --platform Flag for raven init and raven install

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `--platform github|gitlab|none` to `raven init` and `raven install` so the issue-tracker platform is set at install time without manual config editing.

**Architecture:** `default_config_text` grows a `platform` parameter; `cmd_init` reads `args.platform`; `cmd_install` passes it through to `cmd_init` for new configs or calls `_update_config_platform` for existing configs. Validation is done by argparse `choices`.

**Tech Stack:** Python 3.9+, argparse, pathlib — no new dependencies.

---

## File Map

| File | Change |
|------|--------|
| `scripts/raven.py` | Add constant, update `default_config_text`, add `_update_config_platform`, update `cmd_init`, update `cmd_install`, add `--platform` to both subparsers |
| `tests/test_raven.py` | Add 5 new tests for `--platform` behavior |

---

### Task 1: Fail-first tests for `default_config_text` platform param

**Files:**
- Modify: `tests/test_raven.py` (append to `RavenTests`)

- [ ] **Write the failing tests**

Add these three methods to `RavenTests`:

```python
def test_default_config_embeds_github_platform(self):
    config = raven.default_config_text("python", False, "github")
    self.assertIn('platform = "github"', config)

def test_default_config_embeds_gitlab_platform(self):
    config = raven.default_config_text("python", False, "gitlab")
    self.assertIn('platform = "gitlab"', config)

def test_default_config_platform_defaults_to_none(self):
    config = raven.default_config_text("python", False)
    self.assertIn('platform = "none"', config)
```

- [ ] **Run to confirm they fail**

```
PYENV_VERSION=3.9.24 python -m pytest tests/test_raven.py -k "embeds_github_platform or embeds_gitlab_platform or platform_defaults" -v
```
Expected: 2 fail (wrong signature), 1 pass (already defaults to none).

---

### Task 2: Add `platform` param to `default_config_text`

**Files:**
- Modify: `scripts/raven.py:309`

- [ ] **Update the function signature and `[issue_tracker]` block**

Current signature at line 309:
```python
def default_config_text(template_name: str, include_readme: bool) -> str:
```

New signature:
```python
def default_config_text(template_name: str, include_readme: bool, platform: str = "none") -> str:
```

Replace the `[issue_tracker]` block in the f-string (currently lines 415–422) with:

```python
        [issue_tracker]
        # External issue tracker for this project. Controls which issue-tracker
        # workflow skill is active and which CLI raven-tool-bootstrap checks for.
        # This is independent of local session tracking (governed by [lifecycle]).
        #
        # platform = "github"   # use raven-github-issues + gh CLI
        # platform = "gitlab"   # use raven-gitlab-issues + glab CLI
        # platform = "none"     # no external issue tracker
        platform = "{platform}"
```

- [ ] **Run the three new tests — all should pass**

```
PYENV_VERSION=3.9.24 python -m pytest tests/test_raven.py -k "embeds_github_platform or embeds_gitlab_platform or platform_defaults" -v
```
Expected: 3 pass.

- [ ] **Run the existing issue_tracker test to confirm it still passes**

```
PYENV_VERSION=3.9.24 python -m pytest tests/test_raven.py -k "issue_tracker" -v
```
Expected: pass (still emits `platform = "none"` by default).

---

### Task 3: Add `_update_config_platform` for existing configs

**Files:**
- Modify: `scripts/raven.py` (insert before `_run`)

- [ ] **Write the failing test**

Add to `RavenTests`:

```python
def test_update_config_platform_replaces_platform_value(self):
    config_path = self.destination / ".raven" / "config.toml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        raven.default_config_text("python", False, "none"), encoding="utf-8"
    )

    raven._update_config_platform(config_path, "github")

    config = raven.load_config(self.destination)
    # load_config doesn't expose platform yet; check raw text
    self.assertIn('platform = "github"', config_path.read_text(encoding="utf-8"))
    self.assertNotIn('platform = "none"', config_path.read_text(encoding="utf-8"))
```

- [ ] **Run to confirm it fails**

```
PYENV_VERSION=3.9.24 python -m pytest tests/test_raven.py -k "update_config_platform" -v
```
Expected: AttributeError — `_update_config_platform` not found.

- [ ] **Add `_update_config_platform` to `scripts/raven.py`** (insert just before `_git_hooks_dir`):

```python
_ISSUE_TRACKER_SECTION_RE = re.compile(r"^\s*\[([^\]]+)\]")
_PLATFORM_LINE_RE = re.compile(r"^\s*platform\s*=")


def _update_config_platform(config_path: Path, platform: str) -> None:
    """Replace the platform value in [issue_tracker] section of config."""
    lines = config_path.read_text(encoding="utf-8").splitlines(keepends=True)
    in_section = False
    new_lines = []
    updated = False
    for line in lines:
        m = _ISSUE_TRACKER_SECTION_RE.match(line)
        if m:
            in_section = m.group(1).strip() == "issue_tracker"
        if in_section and not updated and _PLATFORM_LINE_RE.match(line) and not line.lstrip().startswith("#"):
            new_lines.append(f'platform = "{platform}"\n')
            updated = True
            continue
        new_lines.append(line)
    config_path.write_text("".join(new_lines), encoding="utf-8")
```

- [ ] **Run the test — should pass**

```
PYENV_VERSION=3.9.24 python -m pytest tests/test_raven.py -k "update_config_platform" -v
```
Expected: pass.

---

### Task 4: Wire `--platform` into argparse and commands

**Files:**
- Modify: `scripts/raven.py` — `cmd_init`, `cmd_install`, `init_parser`, `install_parser`

- [ ] **Write the failing CLI tests**

Add to `RavenTests`:

```python
def test_init_with_platform_github_writes_github_to_config(self):
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        rc = raven.cmd_init(
            argparse.Namespace(destination=str(self.destination), language="python", platform="github")
        )
    self.assertEqual(rc, 0)
    text = (self.destination / ".raven" / "config.toml").read_text(encoding="utf-8")
    self.assertIn('platform = "github"', text)

def test_install_platform_updates_existing_config(self):
    # Create a config with platform = "none"
    (self.destination / ".raven").mkdir(parents=True, exist_ok=True)
    config_path = self.destination / ".raven" / "config.toml"
    config_path.write_text(raven.default_config_text("python", False, "none"), encoding="utf-8")
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        rc = raven.cmd_install(
            argparse.Namespace(
                destination=str(self.destination),
                language=None,
                args=None,
                overrides=[],
                dry_run=False,
                include_readme=False,
                adopt_claude_symlink=False,
                platform="github",
            )
        )
    self.assertEqual(rc, 0)
    text = config_path.read_text(encoding="utf-8")
    self.assertIn('platform = "github"', text)
```

(Add `import argparse` at the top of test file if not present — it's already imported via `raven` module.)

- [ ] **Run to confirm they fail**

```
PYENV_VERSION=3.9.24 python -m pytest tests/test_raven.py -k "init_with_platform or install_platform_updates" -v
```
Expected: fail — `cmd_init` and `cmd_install` don't read `platform` yet.

- [ ] **Update `cmd_init` to use `args.platform`**

In `cmd_init`, change line 1479:
```python
# Before:
path.write_text(default_config_text(language, False), encoding="utf-8")

# After:
platform = getattr(args, "platform", None) or "none"
path.write_text(default_config_text(language, False, platform), encoding="utf-8")
```

- [ ] **Update `cmd_install` to pass platform to `cmd_init` and update existing config**

In `cmd_install`, the block that calls `cmd_init` (currently around line 1504):
```python
# Before:
init_args = argparse.Namespace(destination=str(destination), language=language)

# After:
platform = getattr(args, "platform", None)
init_args = argparse.Namespace(destination=str(destination), language=language, platform=platform)
```

And after loading config for the existing-config branch (insert after `config = load_config(destination)` on the `config.exists` branch, around line 1496):
```python
if config.exists:
    template_name = config.template or list_language_templates()[0]
    include_readme = args.include_readme or config.include_readme
    platform = getattr(args, "platform", None)
    if platform is not None:
        _update_config_platform(destination / CONFIG_PATH, platform)
```

- [ ] **Add `--platform` to `init_parser` and `install_parser`**

After `init_parser.add_argument("language", ...)`:
```python
init_parser.add_argument(
    "--platform",
    choices=["github", "gitlab", "none"],
    default=None,
    help="issue-tracker platform: github, gitlab, or none (default: none)",
)
```

After `install_parser.add_argument("--adopt-claude-symlink", ...)`:
```python
install_parser.add_argument(
    "--platform",
    choices=["github", "gitlab", "none"],
    default=None,
    help="issue-tracker platform: github, gitlab, or none; updates existing config if already installed",
)
```

- [ ] **Run new and existing tests**

```
PYENV_VERSION=3.9.24 python -m pytest tests/test_raven.py -k "init_with_platform or install_platform_updates or issue_tracker or platform_defaults or embeds_github or embeds_gitlab" -v
```
Expected: all pass.

- [ ] **Run full suite**

```
PYENV_VERSION=3.9.24 python -m pytest tests/test_raven.py -q
```
Expected: 78 passed (73 existing + 5 new).

---

### Task 5: Smoke-test CLI and commit

- [ ] **Verify `--help` mentions `--platform`**

```bash
python scripts/raven.py init --help | grep platform
python scripts/raven.py install --help | grep platform
```
Expected: both print `--platform {github,gitlab,none}`.

- [ ] **Smoke-test init with --platform in a temp dir**

```bash
tmp=$(mktemp -d)
python scripts/raven.py -d "$tmp" init python --platform github
grep 'platform' "$tmp/.raven/config.toml"
rm -rf "$tmp"
```
Expected: `platform = "github"`.

- [ ] **Run self-check**

```bash
python scripts/self-check.py
```
Expected: `RAVEN self-check passed`.

- [ ] **Close issue and commit**

```bash
gh issue close 2 --comment "Implemented in $(git rev-parse --short HEAD)"
git add scripts/raven.py tests/test_raven.py
git commit -m "feat(cli): add --platform flag to raven init and raven install"
```
