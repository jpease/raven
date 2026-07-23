#!/usr/bin/env python3

from __future__ import annotations

import datetime
import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RAVEN_SCRIPT = REPO_ROOT / "scripts" / "raven.py"


def run(label: str, args: list[str]) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    result = subprocess.run(
        args,
        cwd=REPO_ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if result.returncode != 0:
        # Surface full output only on failure, so a real error is not buried
        # under routine success chatter from upgrades, linters, and tests.
        print(f"==> {label}")
        print(result.stdout, end="")
        raise SystemExit(result.returncode)
    print(f"==> {label} ok")
    return result


def load_raven_module():
    scripts_dir = str(RAVEN_SCRIPT.parent)
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    import raven_lib

    return raven_lib


def validate_shared_docs_sync() -> None:
    print("==> validate shared docs are in sync with common/")
    non_template_dirs = load_raven_module().NON_TEMPLATE_DIRS
    common_docs = REPO_ROOT / "common" / ".claude" / "docs"
    language_dirs = [
        d
        for d in REPO_ROOT.iterdir()
        if d.is_dir() and not d.name.startswith(".") and d.name not in non_template_dirs
    ]
    mismatches: list[str] = []
    for lang_dir in sorted(language_dirs):
        lang_docs = lang_dir / ".claude" / "docs"
        if not lang_docs.is_dir():
            continue
        for doc in lang_docs.iterdir():
            common_copy = common_docs / doc.name
            if not common_copy.exists():
                continue
            if doc.read_bytes() != common_copy.read_bytes():
                mismatches.append(
                    f"{doc.relative_to(REPO_ROOT)} differs from common/.claude/docs/{doc.name}"
                )
    if mismatches:
        for m in mismatches:
            print(f"  MISMATCH: {m}")
        raise SystemExit("Shared docs are out of sync with common/. Update both copies.")
    print("shared docs sync ok")


# Shared paths every language tree symlinks back to common/ rather than
# copying (see .claude/docs/raven-namespace.md). Update this list by hand when
# a new shared path is added to the trees -- mirrors the THRESHOLDS/PROFILES
# dicts below, which take the same "add it here" maintenance.
_TREE_SYMLINKS_TO_COMMON = [
    ".agents/skills",
    ".claude/agents/raven-codebase-cartographer.md",
    ".claude/agents/raven-refactor-reviewer.md",
    ".claude/agents/raven-security-reviewer.md",
    ".claude/agents/raven-test-debugger.md",
    ".claude/docs/raven-agent-compatibility.md",
    ".claude/docs/raven-authority-map.md",
    ".claude/docs/raven-coding-principles.md",
    ".claude/docs/raven-guardrails.md",
    ".claude/docs/raven-lsp-mcp.md",
    ".claude/docs/raven-namespace.md",
    ".claude/docs/raven-semgrep.md",
    ".claude/docs/raven-tool-assessment.md",
    ".claude/hooks",
    ".claude/rules/raven-security.md",
    ".claude/scripts",
    ".claude/settings.json",
    ".codex/agents",
    ".codex/hooks",
    ".codex/hooks.json",
    ".codex/rules",
    ".codex/scripts",
    ".raven/git-hooks",
    "AGENTS.md",
]
# Shared paths that symlink within their own tree rather than into common/.
_TREE_SYMLINKS_WITHIN_TREE = {
    "CLAUDE.md": "AGENTS.md",
    ".claude/skills": "../.agents/skills",
}


def _language_dirs() -> list[Path]:
    non_template_dirs = load_raven_module().NON_TEMPLATE_DIRS
    return sorted(
        d
        for d in REPO_ROOT.iterdir()
        if d.is_dir() and not d.name.startswith(".") and d.name not in non_template_dirs
    )


def validate_symlink_canonicality() -> None:
    """Each language tree symlinks its shared paths to common/ (or, for
    CLAUDE.md/.claude/skills, to the in-tree canonical file) instead of
    carrying its own copy. A stray `cp` during a manual edit or guided merge
    can silently replace a symlink with a real file, which then drifts from
    common/ unnoticed -- catch that here instead of relying on `ls -l`.
    """
    print("==> validate language-tree symlink canonicality")
    problems: list[str] = []
    for lang_dir in _language_dirs():
        for rel in _TREE_SYMLINKS_TO_COMMON:
            expected = REPO_ROOT / "common" / rel
            problems.extend(_check_tree_symlink(lang_dir / rel, expected))
        for rel, relative_target in _TREE_SYMLINKS_WITHIN_TREE.items():
            target = lang_dir / rel
            expected = (target.parent / relative_target).resolve()
            problems.extend(_check_tree_symlink(target, expected))

    if problems:
        for p in problems:
            print(f"  {p}")
        raise SystemExit(
            "Language-tree symlink canonicality broken. Restore the symlink "
            "instead of copying content -- see .claude/docs/raven-namespace.md."
        )
    print("symlink canonicality ok")


def _check_tree_symlink(target: Path, expected: Path) -> list[str]:
    label = str(target.relative_to(REPO_ROOT))
    if not target.exists() and not target.is_symlink():
        return [f"MISSING: {label}"]
    if not target.is_symlink():
        return [f"NOT A SYMLINK: {label} (real file/dir where a symlink is expected)"]
    if target.resolve() != expected.resolve():
        return [
            f"MISDIRECTED: {label} -> {os.readlink(target)} (expected to resolve to {expected})"
        ]
    return []


def _template_rules_files() -> dict[str, Path]:
    """Map template dir name -> its always-loaded raven-<name>.md rules file, if any."""
    non_template_dirs = load_raven_module().NON_TEMPLATE_DIRS
    found: dict[str, Path] = {}
    for d in sorted(REPO_ROOT.iterdir()):
        if not d.is_dir() or d.name.startswith(".") or d.name in non_template_dirs:
            continue
        rules_file = d / ".claude" / "rules" / f"raven-{d.name}.md"
        if rules_file.exists():
            found[d.name] = rules_file
    return found


def validate_context_budget() -> None:
    # always-loaded tier — raise thresholds only with deliberate justification
    THRESHOLDS: dict[str, int] = {
        "common/AGENTS.md": 1110,
        # language-specific rules files
        "python/.claude/rules/raven-python.md": 760,
        "elixir/.claude/rules/raven-elixir.md": 890,
        "rust/.claude/rules/raven-rust.md": 820,
        "swift/.claude/rules/raven-swift.md": 640,
        "typescript/.claude/rules/raven-typescript.md": 660,
        "go/.claude/rules/raven-go.md": 840,
        "lua/.claude/rules/raven-lua.md": 680,
        "dotfiles/.claude/rules/raven-dotfiles.md": 530,
        # shared rules files (symlinked from language dirs)
        "common/.claude/rules/raven-security.md": 45,
    }
    print("==> validate context budget for always-loaded guidance")

    unbudgeted = [
        str(path.relative_to(REPO_ROOT))
        for path in _template_rules_files().values()
        if str(path.relative_to(REPO_ROOT)) not in THRESHOLDS
    ]
    if unbudgeted:
        raise SystemExit(
            "Always-loaded rules file(s) with no context budget threshold: "
            f"{', '.join(sorted(unbudgeted))}. Add them to THRESHOLDS in "
            "validate_context_budget()."
        )

    offenders: list[str] = []
    for rel, limit in THRESHOLDS.items():
        path = REPO_ROOT / rel
        if not path.exists():
            print(f"  WARNING: {rel} not found, skipping budget check")
            continue
        text = path.read_text(encoding="utf-8")
        count = len(text.split())
        if count > limit:
            offenders.append(f"  {rel}: {count} words (limit {limit})")
    if offenders:
        for line in offenders:
            print(line)
        raise SystemExit(
            "Context budget exceeded. Trim always-loaded guidance or raise thresholds with justification."
        )
    print("context budget ok")


def validate_aggregate_budget() -> None:
    # Per-language always-loaded tier = AGENTS.md + that language's rules file +
    # the shared security rules (symlinked into each language dir).
    # Per-file thresholds cap each file alone; this caps the SUM, which they do
    # not. Without it, every file could spend its individual headroom at once and
    # silently bloat the context window. Keep each budget below the sum of the
    # corresponding per-file thresholds so it stays a real, tighter constraint.
    SHARED = [
        "common/AGENTS.md",
        "common/.claude/rules/raven-security.md",
    ]
    PROFILES: dict[str, tuple[int, str]] = {
        # language: (aggregate word budget, language rules file)
        "python": (1918, "python/.claude/rules/raven-python.md"),
        "elixir": (2048, "elixir/.claude/rules/raven-elixir.md"),
        "rust": (1978, "rust/.claude/rules/raven-rust.md"),
        "swift": (1818, "swift/.claude/rules/raven-swift.md"),
        "typescript": (1838, "typescript/.claude/rules/raven-typescript.md"),
        "go": (1998, "go/.claude/rules/raven-go.md"),
        "lua": (1838, "lua/.claude/rules/raven-lua.md"),
        "dotfiles": (1672, "dotfiles/.claude/rules/raven-dotfiles.md"),
    }
    print("==> validate aggregate context budget per language profile")

    unprofiled = [name for name in _template_rules_files() if name not in PROFILES]
    if unprofiled:
        raise SystemExit(
            "Template(s) with always-loaded rules but no aggregate context budget "
            f"profile: {', '.join(sorted(unprofiled))}. Add them to PROFILES in "
            "validate_aggregate_budget()."
        )

    offenders: list[str] = []
    for lang, (limit, rules_rel) in PROFILES.items():
        total = 0
        missing = False
        for rel in [*SHARED, rules_rel]:
            path = REPO_ROOT / rel
            if not path.exists():
                print(f"  WARNING: {rel} not found, skipping {lang} aggregate check")
                missing = True
                break
            total += len(path.read_text(encoding="utf-8").split())
        if missing:
            continue
        if total > limit:
            offenders.append(f"  {lang}: {total} words (limit {limit})")
    if offenders:
        for line in offenders:
            print(line)
        raise SystemExit(
            "Aggregate context budget exceeded. Trim always-loaded guidance "
            "or raise the profile budget with justification."
        )
    print("aggregate context budget ok")


def _parse_frontmatter_description(text: str) -> str | None:
    """Return the `description:` value from a SKILL.md's leading `---` block.

    Stdlib-only, Python 3.9+: a simple line-prefix parse over the frontmatter
    (the block between the first two `---` lines), not a YAML dependency. Raven
    skill descriptions are single-line, which this assumes.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if line.startswith("description:"):
            return line[len("description:") :].strip()
    return None


def validate_skill_description_budget() -> None:
    # Each skill's `description:` frontmatter is injected into every session's
    # skill index whether or not the skill is invoked, so it is an always-loaded
    # surface like AGENTS.md and the rules files — but the per-file and aggregate
    # rules budgets above never see it. Cap the SUM so the index cannot bloat
    # unnoticed, and cap each single description so one skill cannot eat the pool.
    # Skills are canonical in common/.agents/skills (language trees symlink to
    # it), so counting common/ once matches what a session actually loads.
    AGGREGATE_LIMIT = 362  # ~329 words in-tree + ~10% margin
    PER_SKILL_LIMIT = 30
    print("==> validate context budget for skill-index descriptions")

    skills_dir = REPO_ROOT / "common" / ".agents" / "skills"
    skill_files = sorted(skills_dir.glob("*/SKILL.md"))
    if not skill_files:
        raise SystemExit(
            f"No SKILL.md files under {skills_dir.relative_to(REPO_ROOT)}; "
            "skill-description budget cannot be validated."
        )

    total = 0
    unparseable: list[str] = []
    over_cap: list[str] = []
    for path in skill_files:
        description = _parse_frontmatter_description(path.read_text(encoding="utf-8"))
        if description is None:
            unparseable.append(str(path.relative_to(REPO_ROOT)))
            continue
        count = len(description.split())
        total += count
        if count > PER_SKILL_LIMIT:
            over_cap.append(
                f"  {path.parent.name}: {count} words (per-skill limit {PER_SKILL_LIMIT})"
            )

    if unparseable:
        raise SystemExit(
            "SKILL.md file(s) with no parseable description frontmatter: "
            f"{', '.join(sorted(unparseable))}."
        )
    if over_cap:
        for line in over_cap:
            print(line)
        raise SystemExit(
            f"Skill description exceeds the per-skill cap. Trim it to {PER_SKILL_LIMIT} "
            "words or fewer so one skill cannot dominate the skill-index budget."
        )
    if total > AGGREGATE_LIMIT:
        raise SystemExit(
            f"Skill-index description budget exceeded: {total} words "
            f"(limit {AGGREGATE_LIMIT}). Trim skill descriptions or raise the "
            "threshold with justification."
        )
    print(f"skill description budget ok ({total} words)")


def validate_installed_shape() -> None:
    print("==> validate installed RAVEN shape")
    raven = load_raven_module()
    agents = REPO_ROOT / "AGENTS.md"
    claude = REPO_ROOT / "CLAUDE.md"
    claude_skills = REPO_ROOT / ".claude" / "skills"

    if not agents.is_file():
        raise SystemExit("AGENTS.md is missing")
    block = raven.find_raven_block(agents.read_text(encoding="utf-8"))
    if block is None:
        raise SystemExit("AGENTS.md is missing a RAVEN-managed block")
    if not raven.raven_block_is_unchanged(block):
        raise SystemExit("AGENTS.md RAVEN-managed block was edited directly")
    if not claude.is_symlink() or os.readlink(claude) != "AGENTS.md":
        raise SystemExit("CLAUDE.md must be a symlink to AGENTS.md")
    if not claude_skills.is_symlink() or os.readlink(claude_skills) != "../.agents/skills":
        raise SystemExit(".claude/skills must be a symlink to ../.agents/skills")
    print("installed shape ok")


_LAST_VERIFIED_RE = re.compile(r"Last verified:\s*(\d{4}-\d{2}-\d{2})")
_FRESHNESS_MAX_DAYS = 180
_FRESHNESS_REQUIRED = {
    "raven-lsp-mcp.md",
    "raven-semgrep.md",
    "raven-tool-assessment.md",
}


def warn_stale_docs() -> None:
    """Warn if third-party setup docs are missing or stale freshness markers.

    Fatal when RAVEN_SELF_CHECK_STRICT_FRESHNESS=1 (set by the scheduled CI
    run), so the weekly cron actually fails instead of logging a warning
    inside an otherwise-green run nobody watches.
    """
    docs_dir = REPO_ROOT / "common" / ".claude" / "docs"
    today = datetime.date.today()
    warnings: list[str] = []

    for doc in sorted(docs_dir.glob("*.md")):
        text = doc.read_text(encoding="utf-8")
        m = _LAST_VERIFIED_RE.search(text)
        if m:
            try:
                verified = datetime.date.fromisoformat(m.group(1))
                age = (today - verified).days
                if age > _FRESHNESS_MAX_DAYS:
                    warnings.append(
                        f"  STALE: {doc.name} — last verified {m.group(1)} ({age} days ago)"
                    )
            except ValueError:
                warnings.append(
                    f"  WARN: {doc.name} — unparseable Last verified date: {m.group(1)!r}"
                )
        elif doc.name in _FRESHNESS_REQUIRED:
            warnings.append(f"  MISSING: {doc.name} — no 'Last verified:' marker found")

    if not warnings:
        print("==> freshness check ok")
        return

    strict = os.environ.get("RAVEN_SELF_CHECK_STRICT_FRESHNESS") == "1"
    print(f"==> freshness warnings ({'fatal' if strict else 'non-fatal'})")
    for w in warnings:
        print(w)
    if strict:
        raise SystemExit(
            "Stale or missing freshness markers in common/.claude/docs "
            "(RAVEN_SELF_CHECK_STRICT_FRESHNESS=1)."
        )


def main() -> int:
    validate_shared_docs_sync()
    validate_symlink_canonicality()
    validate_context_budget()
    validate_aggregate_budget()
    validate_skill_description_budget()
    warn_stale_docs()
    validate_installed_shape()
    run(
        "RAVEN self-upgrade dry run",
        [sys.executable, str(RAVEN_SCRIPT), "--destination", ".", "upgrade", "--dry-run"],
    )
    run(
        "RAVEN self-upgrade apply",
        [sys.executable, str(RAVEN_SCRIPT), "--destination", ".", "upgrade"],
    )
    validate_installed_shape()
    run("ruff format check", [sys.executable, "-m", "ruff", "format", "--check", "."])
    run("ruff lint", [sys.executable, "-m", "ruff", "check", "."])
    run("unit tests", [sys.executable, "-m", "pytest", "tests"])
    print("RAVEN self-check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
