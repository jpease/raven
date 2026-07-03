# Orphaned-Managed-File Removal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `raven upgrade` remove a managed file that the template no longer ships — but only when it is provably unmodified — and report (never delete) modified orphans, with matching visibility in `raven doctor`.

**Architecture:** A new pure module `orphans.py` computes the orphan set (`manifest.files − currently-shipped relatives`) and buckets each entry using the same baseline-trust check `reconcile_state` already uses for overwrites. The upgrade path acts on the buckets (delete clean, keep+report modified, prune records); `doctor` calls the same computation read-only. Orphan detection is scoped to genuine template drops — never to destination/config policy exclusions — which is the single safety-critical decision.

**Tech Stack:** Python 3.9+ stdlib only, `unittest` (the repo's existing test framework under `tests/`).

## Global Constraints

- **Runtime floor:** Python 3.9+, stdlib only. Keep `from __future__ import annotations` in every module; no `tomllib`, no 3.10+-only syntax. (`[[project_runtime-python-39-floor]]`)
- **`common/` is canonical:** edit `common/` only; language-tree shared paths are symlinks into it — never `cp` a real file into a language tree. (`[[project_template-common-symlinks]]`)
- **Never delete a user-modified file:** a managed file is auto-removed only when its on-disk content still matches the recorded `installedSha256` baseline **and** that baseline is not a customization (`installedSha256 == sourceSha256`). Anything else is reported and left in place.
- **Orphan = template drop, not policy opt-out:** the "currently shipped" reference set is computed policy-neutral (no config exclusions, no starter-config existence pop), so a user's starter config or an opted-out language file is never a deletion candidate.
- **Strict hashing:** do NOT apply the trailing-newline tolerance (`_differs_only_by_final_newline`) to orphans — a newline-only diff routes to report, not delete.
- **Test command:** `python -m pytest tests/ -q` (repo standard). Run the narrowest test first per step. Do not use `--no-verify` or weaken any gate to make things pass (`[[feedback_fix-preexisting-no-bypass]]`).
- **Commit style:** Conventional Commits; no AI attribution / `Co-Authored-By` footers (`[[feedback_no-ai-attribution]]`).

---

### Task 1: Orphan classification (pure core)

Compute the orphan set and bucket each entry. No file mutation — this task only reads the destination to fingerprint files.

**Files:**
- Create: `scripts/raven_lib/orphans.py`
- Modify: `scripts/raven_lib/models.py` (add `OrphanClassification` dataclass after `Classification`)
- Test: `tests/test_orphans.py`

**Interfaces:**
- Consumes: `entries_for_destination`, `iter_template_entries` (`template.py`); `destination_fingerprint` (`hashing.py`); `parse_record` (`manifest.py`); `ManifestRecord`, `Fingerprint` (`models.py`); `STARTER_TOOL_CONFIG_PATHS`, `KIND_SYMLINK` (`constants.py`).
- Produces:
  - `OrphanClassification(will_remove: list[str], orphan_modified: list[str], already_gone: list[str])` — frozen dataclass.
  - `shipped_relatives(template: Path, destination: Path) -> set[str]` — policy-neutral set of destination-relative paths the current template could install here.
  - `classify_orphans(template: Path, destination: Path, manifest: dict) -> OrphanClassification`.

- [ ] **Step 1: Add the `OrphanClassification` dataclass**

In `scripts/raven_lib/models.py`, add after the `Classification` dataclass (after line 65):

```python
@dataclass(frozen=True)
class OrphanClassification:
    """Manifest-tracked files the current template no longer ships.

    ``will_remove``: destination still matches the recorded baseline and the
    baseline is not a customization, so upgrade can safely delete it.
    ``orphan_modified``: destination differs from the baseline or the baseline
    is a customization; upgrade reports and keeps it. ``already_gone``: the file
    is absent on disk, so only the stale manifest record needs pruning.
    """

    will_remove: list[str]
    orphan_modified: list[str]
    already_gone: list[str]
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_orphans.py`:

```python
from __future__ import annotations

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from raven_lib.orphans import classify_orphans, shipped_relatives


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class ShippedRelativesTests(unittest.TestCase):
    def test_includes_starter_config_even_when_present_on_disk(self) -> None:
        # entries_for_destination pops an existing starter config; shipped_relatives
        # must still count it as shipped so it is never treated as an orphan.
        with TemporaryDirectory() as tmp:
            template = Path(tmp) / "template"
            dest = Path(tmp) / "dest"
            # A real starter-config path shipped by every template.
            from raven_lib.constants import STARTER_TOOL_CONFIG_PATHS

            starter = sorted(STARTER_TOOL_CONFIG_PATHS)[0]
            _write(template / starter, "shipped\n")
            _write(dest / starter, "user copy\n")
            self.assertIn(starter, shipped_relatives(template, dest))


class ClassifyOrphansTests(unittest.TestCase):
    def _setup(self) -> tuple[Path, Path]:
        tmp = self.enterContext(TemporaryDirectory())
        template = Path(tmp) / "template"
        dest = Path(tmp) / "dest"
        template.mkdir()
        dest.mkdir()
        return template, dest

    def test_clean_orphan_is_will_remove(self) -> None:
        template, dest = self._setup()
        from raven_lib.hashing import file_sha256

        target = dest / "docs" / "dropped.md"
        _write(target, "content\n")
        sha = file_sha256(target)
        manifest = {
            "schema": 1,
            "files": {
                "docs/dropped.md": {
                    "kind": "file",
                    "installedSha256": sha,
                    "sourceSha256": sha,
                }
            },
        }
        result = classify_orphans(template, dest, manifest)
        self.assertEqual(result.will_remove, ["docs/dropped.md"])
        self.assertEqual(result.orphan_modified, [])

    def test_locally_modified_orphan_is_reported_not_removed(self) -> None:
        template, dest = self._setup()
        target = dest / "docs" / "dropped.md"
        _write(target, "user edited this\n")
        manifest = {
            "schema": 1,
            "files": {
                "docs/dropped.md": {
                    "kind": "file",
                    "installedSha256": "a" * 64,  # baseline the user diverged from
                    "sourceSha256": "a" * 64,
                }
            },
        }
        result = classify_orphans(template, dest, manifest)
        self.assertEqual(result.orphan_modified, ["docs/dropped.md"])
        self.assertEqual(result.will_remove, [])

    def test_customized_baseline_is_reported_not_removed(self) -> None:
        template, dest = self._setup()
        from raven_lib.hashing import file_sha256

        target = dest / "docs" / "dropped.md"
        _write(target, "accepted merge\n")
        sha = file_sha256(target)
        manifest = {
            "schema": 1,
            "files": {
                "docs/dropped.md": {
                    "kind": "file",
                    "installedSha256": sha,
                    "sourceSha256": "b" * 64,  # installed != source: a customization
                }
            },
        }
        result = classify_orphans(template, dest, manifest)
        self.assertEqual(result.orphan_modified, ["docs/dropped.md"])
        self.assertEqual(result.will_remove, [])

    def test_missing_on_disk_is_already_gone(self) -> None:
        template, dest = self._setup()
        manifest = {
            "schema": 1,
            "files": {
                "docs/dropped.md": {
                    "kind": "file",
                    "installedSha256": "a" * 64,
                    "sourceSha256": "a" * 64,
                }
            },
        }
        result = classify_orphans(template, dest, manifest)
        self.assertEqual(result.already_gone, ["docs/dropped.md"])
        self.assertEqual(result.will_remove, [])

    def test_still_shipped_file_is_not_an_orphan(self) -> None:
        template, dest = self._setup()
        from raven_lib.hashing import file_sha256

        _write(template / "docs" / "kept.md", "content\n")
        target = dest / "docs" / "kept.md"
        _write(target, "content\n")
        sha = file_sha256(target)
        manifest = {
            "schema": 1,
            "files": {
                "docs/kept.md": {
                    "kind": "file",
                    "installedSha256": sha,
                    "sourceSha256": sha,
                }
            },
        }
        result = classify_orphans(template, dest, manifest)
        self.assertEqual(result.will_remove, [])
        self.assertEqual(result.orphan_modified, [])
        self.assertEqual(result.already_gone, [])

    def test_legacy_record_without_source_sha_is_not_removed(self) -> None:
        template, dest = self._setup()
        from raven_lib.hashing import file_sha256

        target = dest / "docs" / "dropped.md"
        _write(target, "content\n")
        sha = file_sha256(target)
        manifest = {
            "schema": 1,
            "files": {
                "docs/dropped.md": {"kind": "file", "installedSha256": sha}
            },
        }
        result = classify_orphans(template, dest, manifest)
        self.assertEqual(result.orphan_modified, ["docs/dropped.md"])
        self.assertEqual(result.will_remove, [])


if __name__ == "__main__":
    unittest.main()
```

> Note: `enterContext` requires Python 3.11+. This repo's floor is 3.9, so replace `self.enterContext(TemporaryDirectory())` with the `addCleanup` form if the test runner is on 3.9/3.10:
> ```python
> tmp = TemporaryDirectory()
> self.addCleanup(tmp.cleanup)
> tmp = tmp.name
> ```
> Check the interpreter first: `python --version`. Use `addCleanup` unless it prints 3.11+.

- [ ] **Step 3: Run the tests to verify they fail**

Run: `python -m pytest tests/test_orphans.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'raven_lib.orphans'`.

- [ ] **Step 4: Implement `orphans.py`**

Create `scripts/raven_lib/orphans.py`:

```python
from __future__ import annotations

from pathlib import Path

from .constants import KIND_SYMLINK, STARTER_TOOL_CONFIG_PATHS
from .hashing import destination_fingerprint
from .manifest import parse_record
from .models import Fingerprint, ManifestRecord, OrphanClassification
from .template import entries_for_destination, iter_template_entries


def shipped_relatives(template: Path, destination: Path) -> set[str]:
    """Destination-relative paths the current template could install here.

    Computed policy-neutral (empty excludes, no config) so a file the template
    still ships is never treated as an orphan just because config gating or a
    starter-config existence check would skip re-copying it. ``entries_for_
    destination`` still pops existing starter configs, so add those back from the
    raw shipped set: their presence on disk must not make them deletion targets.
    """
    resolved = set(entries_for_destination(template, set(), None, destination))
    raw = {entry.relative for entry in iter_template_entries(template, set(), None)}
    resolved |= raw & set(STARTER_TOOL_CONFIG_PATHS)
    return resolved


def _unmodified_baseline(record: ManifestRecord, fingerprint: Fingerprint) -> bool:
    """Whether the on-disk file still matches its recorded, non-customized baseline."""
    if record.source_sha256 is None:
        # Legacy record predating sourceSha256: no baseline to trust, never delete.
        return False
    if record.installed_sha256 != record.source_sha256:
        # A customization (e.g. accepted manual merge) that removal would destroy.
        return False
    if fingerprint.kind != record.kind:
        return False
    if fingerprint.kind == KIND_SYMLINK and fingerprint.target != record.target:
        return False
    return fingerprint.sha256 == record.installed_sha256


def classify_orphans(
    template: Path, destination: Path, manifest: dict
) -> OrphanClassification:
    """Bucket manifest files the current template no longer ships.

    Non-orphans (still shipped) are ignored. Each orphan is classified strictly:
    an exact, non-customized baseline match is removable; anything else is
    reported and kept; an absent file only needs its record pruned.
    """
    tracked = manifest.get("files", {})
    if not isinstance(tracked, dict):
        return OrphanClassification([], [], [])
    shipped = shipped_relatives(template, destination)
    orphans = sorted(set(tracked) - shipped)

    will_remove: list[str] = []
    orphan_modified: list[str] = []
    already_gone: list[str] = []
    for relative in orphans:
        record = parse_record(tracked.get(relative))
        fingerprint = destination_fingerprint(destination / relative)
        if fingerprint is None:
            already_gone.append(relative)
        elif record is not None and _unmodified_baseline(record, fingerprint):
            will_remove.append(relative)
        else:
            orphan_modified.append(relative)
    return OrphanClassification(will_remove, orphan_modified, already_gone)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/test_orphans.py -q`
Expected: PASS (all tests).

- [ ] **Step 6: Commit**

```bash
git add scripts/raven_lib/orphans.py scripts/raven_lib/models.py tests/test_orphans.py
git commit -m "feat(upgrade): classify manifest orphans the template no longer ships"
```

---

### Task 2: Orphan removal + manifest pruning (side effects)

Execute deletions safely and prune records. Isolated from Task 1 so the destructive step has its own tests.

**Files:**
- Modify: `scripts/raven_lib/orphans.py` (add `remove_orphans`)
- Modify: `scripts/raven_lib/manifest.py` (`update_manifest` gains a `remove` parameter)
- Test: `tests/test_orphans.py` (append), `tests/test_manifest.py` (append if it exists; else add to `tests/test_orphans.py`)

**Interfaces:**
- Consumes: `OrphanClassification` from Task 1.
- Produces:
  - `remove_orphans(destination: Path, relatives: list[str]) -> list[str]` — unlinks each `destination/relative` (file or symlink), removes now-empty parent dirs up to (but not including) `destination`, returns the relatives actually removed.
  - `update_manifest(..., remove: list[str] | None = None)` — pops the given keys from `manifest["files"]` before saving.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_orphans.py`:

```python
class RemoveOrphansTests(unittest.TestCase):
    def test_removes_file_and_prunes_empty_parent(self) -> None:
        with TemporaryDirectory() as tmp:
            dest = Path(tmp)
            target = dest / "docs" / "sub" / "dropped.md"
            _write(target, "x\n")
            from raven_lib.orphans import remove_orphans

            removed = remove_orphans(dest, ["docs/sub/dropped.md"])
            self.assertEqual(removed, ["docs/sub/dropped.md"])
            self.assertFalse(target.exists())
            # Now-empty parents are pruned...
            self.assertFalse((dest / "docs" / "sub").exists())
            self.assertFalse((dest / "docs").exists())
            # ...but the destination root is never removed.
            self.assertTrue(dest.exists())

    def test_keeps_parent_with_other_files(self) -> None:
        with TemporaryDirectory() as tmp:
            dest = Path(tmp)
            _write(dest / "docs" / "dropped.md", "x\n")
            _write(dest / "docs" / "kept.md", "y\n")
            from raven_lib.orphans import remove_orphans

            remove_orphans(dest, ["docs/dropped.md"])
            self.assertTrue((dest / "docs" / "kept.md").exists())
            self.assertTrue((dest / "docs").exists())

    def test_removes_symlink_orphan(self) -> None:
        with TemporaryDirectory() as tmp:
            dest = Path(tmp)
            (dest / "docs").mkdir()
            link = dest / "docs" / "link.md"
            link.symlink_to("../common/real.md")
            from raven_lib.orphans import remove_orphans

            removed = remove_orphans(dest, ["docs/link.md"])
            self.assertEqual(removed, ["docs/link.md"])
            self.assertFalse(link.is_symlink())
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_orphans.py::RemoveOrphansTests -q`
Expected: FAIL — `ImportError: cannot import name 'remove_orphans'`.

- [ ] **Step 3: Implement `remove_orphans`**

Append to `scripts/raven_lib/orphans.py` (and add `import os` at the top):

```python
def remove_orphans(destination: Path, relatives: list[str]) -> list[str]:
    """Delete each managed orphan file/symlink and prune now-empty parents.

    Only the exact paths passed in are removed; parent directories are removed
    only when they become empty, and the destination root is never touched.
    """
    removed: list[str] = []
    for relative in relatives:
        target = destination / relative
        if target.is_symlink():
            target.unlink()
        elif target.exists():
            target.unlink()
        else:
            continue
        removed.append(relative)
        # Prune empty parents, stopping before the destination root.
        parent = target.parent
        while parent != destination and parent.is_dir():
            try:
                parent.rmdir()
            except OSError:
                break  # not empty (or race) -- leave it and everything above.
            parent = parent.parent
    return removed
```

> `os` is imported for parity with the rest of the package's file ops even if unused here; if a linter flags it as unused, omit the import. Verify with the lint step below.

- [ ] **Step 4: Add the `remove` parameter to `update_manifest`**

In `scripts/raven_lib/manifest.py`, modify `update_manifest` (lines 129-157). Change the signature and add pruning before `save_manifest`:

```python
def update_manifest(
    destination: Path,
    template_name: str,
    template: Path,
    excludes: set[str],
    config: RavenConfig,
    paths: list[str],
    manifest: dict | None = None,
    entries: dict[str, TemplateEntry] | None = None,
    remove: list[str] | None = None,
) -> None:
    if manifest is None:
        manifest = load_manifest(destination)
    manifest["schema"] = 1
    manifest["template"] = template_name
    manifest["ravenVersion"] = git_ref()
    manifest["updatedAt"] = datetime.now(timezone.utc).isoformat()
    manifest.setdefault("files", {})

    if entries is None:
        entries = entries_for_destination(template, excludes, config, destination)
    new_records = {
        relative: record
        for relative in sorted(set(paths))
        if (entry := entries.get(relative)) is not None
        if (record := _make_manifest_record(entry, destination / relative)) is not None
    }
    manifest["files"].update(new_records)
    for relative in remove or []:
        manifest["files"].pop(relative, None)

    save_manifest(destination, manifest)
```

- [ ] **Step 5: Write and run the manifest-prune test**

Append to `tests/test_orphans.py`:

```python
class UpdateManifestRemoveTests(unittest.TestCase):
    def test_remove_pops_records_before_save(self) -> None:
        with TemporaryDirectory() as tmp:
            dest = Path(tmp)
            (dest / ".raven").mkdir()
            import json

            (dest / ".raven" / "manifest.json").write_text(
                json.dumps(
                    {
                        "schema": 1,
                        "files": {
                            "docs/gone.md": {"kind": "file", "installedSha256": "a" * 64},
                            "docs/kept.md": {"kind": "file", "installedSha256": "b" * 64},
                        },
                    }
                ),
                encoding="utf-8",
            )
            from raven_lib.manifest import load_manifest, update_manifest
            from raven_lib.models import RavenConfig

            config = RavenConfig(None, False, {}, {}, {}, [])
            template = dest / "template"
            template.mkdir()
            update_manifest(
                dest, "python", template, set(), config, [], remove=["docs/gone.md"]
            )
            files = load_manifest(dest)["files"]
            self.assertNotIn("docs/gone.md", files)
            self.assertIn("docs/kept.md", files)
```

Run: `python -m pytest tests/test_orphans.py -q`
Expected: PASS.

- [ ] **Step 6: Lint and commit**

```bash
ruff check scripts/raven_lib/orphans.py scripts/raven_lib/manifest.py
git add scripts/raven_lib/orphans.py scripts/raven_lib/manifest.py tests/test_orphans.py
git commit -m "feat(upgrade): remove clean orphans and prune stale manifest records"
```

---

### Task 3: Wire orphan handling into `upgrade`

Surface orphans in the dry-run plan and apply summary, and perform removal on a live run.

**Files:**
- Modify: `scripts/raven_lib/plan.py` (`apply_plan` performs removal; `print_dry_run_plan` shows orphan sections; `print_apply_summary` reports)
- Modify: `scripts/raven_lib/cli.py` (`_run` computes orphans, threads them into dry-run + apply)
- Test: `tests/test_upgrade_orphans.py`

**Interfaces:**
- Consumes: `classify_orphans`, `remove_orphans` (Task 1-2); `OrphanClassification`.
- Produces: `apply_plan(...)` gains an `orphans: OrphanClassification` argument and, on a live run, calls `remove_orphans` for `will_remove` and passes `will_remove + already_gone` as `update_manifest(remove=...)`. New printed sections keyed off the orphan buckets.

- [ ] **Step 1: Write the failing end-to-end test**

Create `tests/test_upgrade_orphans.py`. This installs a shape, drops a template file, upgrades, and asserts behavior. Follow the existing install/upgrade test harness — inspect `tests/test_cli.py` (or the file that already drives `_run`/`cmd_upgrade` against a temp template) and reuse its fixture helpers rather than reinventing them.

```python
from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

# Reuse the repo's existing upgrade harness. Locate it first:
#   rg -l "def .*install|_run\(|cmd_upgrade" tests/
# and import the same helper the other upgrade tests use to build a temp
# template + destination and run an upgrade. The assertions below are the
# contract; adapt the setup calls to the existing helper's signature.


class UpgradeOrphanTests(unittest.TestCase):
    def test_clean_orphan_removed_and_reported(self) -> None:
        # 1. Install a template that ships docs/dropped.md.
        # 2. Drop docs/dropped.md from the template.
        # 3. Run upgrade (live).
        # 4. Assert the destination file is gone and its manifest record pruned.
        raise NotImplementedError  # replace with harness-driven steps

    def test_modified_orphan_kept_and_reported(self) -> None:
        # Same as above but edit the destination file before upgrade;
        # assert it survives and appears in the "left in place" report.
        raise NotImplementedError

    def test_existing_starter_config_never_removed(self) -> None:
        # Install, ensure a STARTER_TOOL_CONFIG_PATHS file exists on disk,
        # upgrade against the full template; assert it is untouched.
        raise NotImplementedError
```

> This is a genuine harness-integration test — the exact fixture calls depend on helpers already in `tests/`. Before writing implementation, replace each `raise NotImplementedError` with concrete setup using the discovered helper. If no reusable helper exists, build the temp template by copying a minimal subtree of `REPO_ROOT / "python"` into a tmp dir, run `raven_lib.cli._run(...)` to install, delete one file from the tmp template, and run `_run(...)` again to upgrade.

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_upgrade_orphans.py -q`
Expected: FAIL (NotImplementedError / assertion failures once harness is wired).

- [ ] **Step 3: Thread orphans through `apply_plan`**

In `scripts/raven_lib/plan.py`, modify `apply_plan` (lines 207-263). Add the `orphans` parameter and act on it. Add `from .models import ... OrphanClassification` to the existing models import and `from .orphans import remove_orphans`:

```python
def apply_plan(
    destination: Path,
    template_name: str,
    template: Path,
    excludes: set[str],
    config: RavenConfig,
    manifest: dict,
    entries: dict[str, TemplateEntry],
    plan: ApplyPlan,
    orphans: OrphanClassification,
) -> tuple[int, list[str], list[str], list[str]]:
    adopted_claude: list[str] = []
    if plan.adopt_claude_symlink:
        try:
            adopted_claude = adopt_claude_symlink(destination, entries)
        except FileExistsError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2, [], [], []

    try:
        if plan.requested_overrides:
            copy_paths(template, destination, plan.requested_overrides, config, entries=entries)
        if plan.will_copy:
            copy_paths(template, destination, plan.will_copy, config, entries=entries)
        if plan.will_upgrade:
            copy_paths(
                template,
                destination,
                plan.will_upgrade,
                config,
                entries=entries,
                update_managed_blocks=True,
            )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2, adopted_claude, [], []

    removed_orphans = remove_orphans(destination, orphans.will_remove)

    managed_paths = (
        plan.copied
        + plan.will_upgrade
        + plan.overwritten
        + plan.identical
        + ([CLAUDE_PATH] if adopted_claude else [])
    )
    if managed_paths or removed_orphans or orphans.already_gone:
        update_manifest(
            destination,
            template_name,
            template,
            excludes,
            config,
            managed_paths,
            manifest=manifest,
            entries=entries,
            remove=removed_orphans + orphans.already_gone,
        )

    merge_artifacts = write_guided_merge_artifacts(destination, entries, plan.guided_merge_paths)
    return 0, adopted_claude, merge_artifacts, removed_orphans
```

> The return tuple grows from 3 to 4 elements (adds `removed_orphans`). Update the caller in Step 5 accordingly.

- [ ] **Step 4: Add dry-run and apply-summary sections**

In `scripts/raven_lib/plan.py`, add orphan reporting. Extend `print_dry_run_plan` (before the `return 0`, after the guided-merge section, lines ~197-204) to accept and print orphans:

```python
def print_dry_run_plan(
    destination: Path,
    classification: Classification,
    entries: dict[str, TemplateEntry],
    plan: ApplyPlan,
    orphans: OrphanClassification,
) -> int:
    # ... existing body unchanged up to the guided-merge block ...
    if orphans.will_remove:
        print()
        print_section(
            "Will remove orphaned Raven files (template no longer ships them; "
            "destination still matches the recorded baseline):",
            orphans.will_remove,
        )
    if orphans.orphan_modified:
        print()
        print_section(
            "Orphaned but locally modified; left in place (template no longer "
            "ships them, but you changed them — delete manually if unwanted):",
            orphans.orphan_modified,
        )
    return 0
```

Extend `print_apply_summary` to take and report the removed/kept orphans. Add two parameters at the end and two report blocks:

```python
def print_apply_summary(
    copied: list[str],
    upgraded: list[str],
    overwritten: list[str],
    adopted_claude: list[str],
    identical: list[str],
    needs_merge: list[str],
    unknown_existing: list[str],
    removed_orphans: list[str],
    orphan_modified: list[str],
) -> None:
    # ... existing body unchanged ...
    if removed_orphans:
        print()
        print_section(
            f"Removed {len(removed_orphans)} orphaned file(s) the template no longer ships:",
            removed_orphans,
        )
    if orphan_modified:
        print()
        print_section(
            "Orphaned but left in place because you modified them "
            "(template no longer ships these; remove manually if unwanted):",
            orphan_modified,
        )
```

- [ ] **Step 5: Compute and thread orphans in `cli._run`**

In `scripts/raven_lib/cli.py`, add `from .orphans import classify_orphans` near the other imports. In `_run`, after `classification = classify(...)` (line 176-178) and before/near `build_apply_plan`, compute:

```python
    orphans = classify_orphans(template, destination, manifest)
```

Update the dry-run call (line 220):

```python
    if dry_run:
        return print_dry_run_plan(destination, classification, entries, plan, orphans)
```

Update the `apply_plan` call (lines 238-247) and its unpacking:

```python
    rc, adopted_claude, merge_artifacts, removed_orphans = apply_plan(
        destination,
        template_name,
        template,
        excludes,
        config,
        manifest,
        entries,
        plan,
        orphans,
    )
    if rc != 0:
        return rc
```

Update the `print_apply_summary` call (lines 253-261):

```python
    print_apply_summary(
        plan.copied,
        plan.will_upgrade,
        plan.overwritten,
        adopted_claude,
        plan.identical,
        plan.needs_merge,
        plan.unknown_existing,
        removed_orphans,
        orphans.orphan_modified,
    )
```

- [ ] **Step 6: Finish the harness test and run it**

Replace the `raise NotImplementedError` bodies from Step 1 with the discovered-harness setup, then:

Run: `python -m pytest tests/test_upgrade_orphans.py -q`
Expected: PASS.

- [ ] **Step 7: Run the full suite (nothing else broke)**

Run: `python -m pytest tests/ -q`
Expected: PASS. If any existing test constructs `apply_plan`, `print_apply_summary`, or `print_dry_run_plan` directly, update those call sites to the new signatures (search: `rg -n "apply_plan\(|print_apply_summary\(|print_dry_run_plan\(" tests/ scripts/`).

- [ ] **Step 8: Commit**

```bash
git add scripts/raven_lib/plan.py scripts/raven_lib/cli.py tests/test_upgrade_orphans.py
git commit -m "feat(upgrade): report and remove orphaned managed files during upgrade"
```

---

### Task 4: Surface orphans in `doctor`

Read-only visibility so orphans are seen without running an upgrade.

**Files:**
- Modify: `scripts/raven_lib/doctor.py` (`drift_findings` adds orphan findings)
- Test: `tests/test_doctor.py` (append; confirm the filename with `rg -l "drift_findings" tests/`)

**Interfaces:**
- Consumes: `classify_orphans` (Task 1); `validate_manifest` (already imported in `doctor.py`).
- Produces: up to two new `Finding`s with ids `doctor.orphan.removable` (WARN) and `doctor.orphan.modified` (WARN), disjoint from existing drift findings.

- [ ] **Step 1: Write the failing test**

Append to the doctor test file (e.g. `tests/test_doctor.py`), matching its existing setup style for building a destination with a manifest:

```python
def test_doctor_reports_removable_orphan(self) -> None:
    # Build a destination whose manifest tracks a file the template no longer
    # ships, with the on-disk file matching its recorded baseline.
    # Assert a finding with id "doctor.orphan.removable" is present.
    ...

def test_doctor_reports_modified_orphan(self) -> None:
    # Same, but the on-disk file diverges from the baseline.
    # Assert a finding with id "doctor.orphan.modified" is present.
    ...
```

> Fill the `...` using the doctor test file's existing destination-builder helper. The contract is the finding ids; the setup mirrors the neighbouring tests.

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_doctor.py -q -k orphan`
Expected: FAIL (findings not present).

- [ ] **Step 3: Add orphan findings to `drift_findings`**

In `scripts/raven_lib/doctor.py`, add `from .orphans import classify_orphans` to the imports. Inside `drift_findings`, after `manifest = manifest_status.manifest` and the `classify(...)` call (around line 234-236), compute and append findings before the `return findings`:

```python
    orphans = classify_orphans(template, destination, manifest)
    if orphans.will_remove:
        findings.append(
            Finding(
                id="doctor.orphan.removable",
                severity=Severity.WARN,
                category=_DRIFT,
                title=f"{len(orphans.will_remove)} orphaned Raven file(s) the template no longer ships",
                detail=", ".join(orphans.will_remove),
                fix="run `raven upgrade` to remove them",
            )
        )
    if orphans.orphan_modified:
        findings.append(
            Finding(
                id="doctor.orphan.modified",
                severity=Severity.WARN,
                category=_DRIFT,
                title=f"{len(orphans.orphan_modified)} orphaned + locally modified Raven file(s)",
                detail=", ".join(orphans.orphan_modified),
                fix="template no longer ships these; review and delete manually if unwanted",
            )
        )
```

> Note the existing "No Raven-owned drift detected" OK finding (lines 277-286) is gated on `not missing/modified/pending/local_only`. Orphans are a distinct axis; leaving the OK finding as-is is acceptable (it describes template-vs-installed drift, not orphans). Do NOT expand its guard unless a test requires it — keep this change minimal.

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_doctor.py -q -k orphan`
Expected: PASS.

- [ ] **Step 5: Full suite + commit**

Run: `python -m pytest tests/ -q`
Expected: PASS.

```bash
git add scripts/raven_lib/doctor.py tests/test_doctor.py
git commit -m "feat(doctor): report orphaned managed files without requiring upgrade"
```

---

### Task 5: Execute #91 Part A — delete `raven-tests.md`, fold bullet (b) into each language

Now the mechanism exists, drop the shared test-rules file and fold its unique bullet into each language rules file. The dogfood proof: this repo's own install must upgrade cleanly (the orphaned `.claude/rules/raven-tests.md` at the repo root is removed, not left behind).

**Files:**
- Delete: `common/.claude/rules/raven-tests.md` and the 8 per-tree symlinks (`{dotfiles,elixir,go,lua,python,rust,swift,typescript}/.claude/rules/raven-tests.md`)
- Modify: each `<lang>/.claude/rules/raven-<lang>.md` `## Testing` section (8 files) — fold in bullet (b)
- Modify: `scripts/self-check.py` (`THRESHOLDS`, `SHARED`, `PROFILES`)
- Modify: `tests/test_self_check.py` (`SHARED` mirror line 20, `PYTHON_BUDGET` line 27)

**Global note for this task:** `common/` is canonical and the per-tree files are symlinks into it (`[[project_template-common-symlinks]]`). Delete the real file in `common/` AND the 8 symlinks. The bullet (b) text to fold is verbatim:

```
- Avoid brittle sleeps, timing assumptions, and oversized snapshots unless the codebase already relies on them.
```

(16 whitespace tokens by `str.split()`. `raven-tests.md` contributes 48 tokens to each aggregate today.)

- [ ] **Step 1: Confirm bullet (a) coverage, fold bullet (b) into each language rules file**

Bullet (a) ("Add tests near existing coverage / local naming and fixture patterns") is claimed already-covered per file — verify before folding only (b). For each of the 8 languages:

```bash
rg -n "existing coverage|local naming|fixture" <lang>/.claude/rules/raven-<lang>.md   # bullet (a) present?
rg -n "brittle|oversized snapshot|timing assumption" <lang>/.claude/rules/raven-<lang>.md  # bullet (b) absent (confirmed 0 for all)
```

In each `<lang>/.claude/rules/raven-<lang>.md`, locate the `## Testing` section (`rg -n "## Testing" <lang>/.claude/rules/raven-<lang>.md`) and add the bullet (b) line as the last bullet of that section's list. If bullet (a) is genuinely missing in a given file, add it too (verify per file — do not assume).

- [ ] **Step 2: Delete the shared file and its symlinks**

```bash
git rm common/.claude/rules/raven-tests.md \
       dotfiles/.claude/rules/raven-tests.md \
       elixir/.claude/rules/raven-tests.md \
       go/.claude/rules/raven-tests.md \
       lua/.claude/rules/raven-tests.md \
       python/.claude/rules/raven-tests.md \
       rust/.claude/rules/raven-tests.md \
       swift/.claude/rules/raven-tests.md \
       typescript/.claude/rules/raven-tests.md
```

- [ ] **Step 3: Update `scripts/self-check.py`**

In `validate_context_budget`, remove the `raven-tests.md` line from `THRESHOLDS` (line 103). If any language rules file's new word count (with bullet (b) added, +16 tokens) now exceeds its individual threshold (lines 93-100), do NOT silently raise it — pause and report to the maintainer; the intent of #97/#91 is trimming, and a per-file overflow is a signal to trim elsewhere.

In `validate_aggregate_budget`, remove `"common/.claude/rules/raven-tests.md"` from `SHARED` (line 148). For each language in `PROFILES` (lines 152-159), lower the budget by `48 - 16 = 32` tokens (remove the 48-token shared file, add the 16-token bullet to that language's own file). Example: python `1950 → 1918`. Apply `-32` to all 8 profiles. Budgets move **downward only** — never up (`[[issue #97]]`).

- [ ] **Step 4: Update `tests/test_self_check.py`**

Remove `"common/.claude/rules/raven-tests.md"` from the `SHARED` mirror (line 20). Update `PYTHON_BUDGET` (line 27) to match the new python profile budget from Step 3 (`1918`). Check line 59's invariant (`500 * len(PYTHON_PROFILE_FILES) > PYTHON_BUDGET`) still holds and that `PYTHON_PROFILE_FILES` no longer references the deleted file.

- [ ] **Step 5: Run self-check and the suite**

```bash
python -m pytest tests/ -q
python scripts/self-check.py
```

Expected: both PASS. `self-check.py` applies `upgrade` to this repo's own install — confirm the summary shows `.claude/rules/raven-tests.md` **removed** (via the new mechanism), not orphaned or listed as needing a merge.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "refactor(rules): drop shared raven-tests.md, fold its bullet into each language"
```

---

## Self-Review

**Spec coverage:**
- "Detect files in manifest but not shipped; bucket by baseline trust" → Task 1. ✔
- "Remove clean, report modified, prune already-gone" → Task 2 (`remove_orphans`, `update_manifest(remove=...)`). ✔
- Guard #1 (orphan = template drop, not policy exclusion) → Task 1 `shipped_relatives` (policy-neutral + starter add-back) with a dedicated test. ✔
- Guard #2 (skills remap: match source-relative, delete installed path) → manifest keys are already destination-relative; `destination / relative` is the installed path. ✔
- Guard #3 (strict hashing, empty-parent pruning) → Task 1 (no newline tolerance), Task 2 (`rmdir` only when empty, never the root). ✔
- Dry-run + apply summary surfacing → Task 3. ✔
- Doctor finding → Task 4. ✔
- Upgrade-path regression test → Task 3 (`tests/test_upgrade_orphans.py`). ✔
- #91 Part A (delete file, fold bullet, adjust budgets downward, update tests) → Task 5. ✔
- Dogfood: repo's own install upgrades cleanly → Task 5 Step 5. ✔

**Placeholder scan:** Task 3 Step 1 and Task 4 Step 1 intentionally defer exact fixture wiring to the discovered test harness — flagged explicitly, not silent TODOs, because the fixture helper's signature must be read from `tests/` rather than guessed. Every other step carries complete code.

**Type consistency:** `OrphanClassification(will_remove, orphan_modified, already_gone)` is defined once (Task 1) and consumed with those exact field names in Tasks 3-4. `apply_plan` returns a 4-tuple after Task 3; its sole caller (`cli._run`) is updated in the same task. `update_manifest`'s `remove` param is added in Task 2 and used in Task 3.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-02-orphaned-file-removal.md`.
