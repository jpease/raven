"""Detect, hash, update, and guided-merge the ``RAVEN:BEGIN``/``RAVEN:END`` managed block.

Three content-normalization strengths are deliberately kept distinct --
``normalized_block_content`` (line endings/trailing whitespace only),
``identity_block_content`` (also formatter-invariant table restyling), and
``comparison_block_content`` (also whitespace-collapsed) -- each is exactly as
permissive as its caller needs and no more, since over-normalizing risks
silently treating an edit as unmodified.
"""

from __future__ import annotations

import difflib
import os
import re
from contextlib import suppress
from pathlib import Path
from typing import Literal

from .constants import (
    MERGE_DIR,
    RAVEN_BLOCK_BEGIN_RE,
    RAVEN_BLOCK_END,
    ROOT_INSTRUCTION_FILES,
    _any_exists,
)
from .hashing import sha256_bytes
from .models import RavenBlock, TemplateEntry

BlockState = Literal["identical", "upgradeable", "modified"]


def normalized_block_content(text: str) -> str:
    """Normalize line endings and trailing whitespace; the weakest of the three block normalizers."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    return "\n".join(line.rstrip() for line in lines).strip("\n")


def _is_markdown_table_separator_cell(cell: str) -> bool:
    stripped = cell.strip()
    if len(stripped) < 3:
        return False
    inner = stripped.strip(":")
    return bool(inner) and set(inner) == {"-"}


def _normalize_markdown_table_separator(line: str) -> str | None:
    stripped = line.strip()
    if not stripped.startswith("|") or not stripped.endswith("|"):
        return None
    cells = stripped.strip("|").split("|")
    if not cells or not all(_is_markdown_table_separator_cell(cell) for cell in cells):
        return None
    normalized_cells: list[str] = []
    for cell in cells:
        value = cell.strip()
        left = ":" if value.startswith(":") else ""
        right = ":" if value.endswith(":") else ""
        normalized_cells.append(f"{left}---{right}")
    return "|" + "|".join(normalized_cells) + "|"


def _normalize_markdown_table_row(line: str) -> str | None:
    """Fold a markdown table row to one-space cell padding, or None if not a row.

    "Is a table row" uses exactly the pipe-delimiter judgment
    ``_normalize_markdown_table_separator`` already makes: the stripped line
    must both begin and end with ``|``. Prose that merely *contains* a pipe --
    a shell pipeline in a code span, a regex alternation -- is not delimited
    that way and is left alone. A bare ``|`` is not a row either.

    Only whitespace adjacent to a delimiter is touched. Cell text is
    ``strip()``ed, never collapsed, so ``| a b |`` and ``| a  b |`` stay
    distinct while ``|  a  |`` and ``| a |`` converge.
    """
    stripped = line.strip()
    if len(stripped) < 2 or not stripped.startswith("|") or not stripped.endswith("|"):
        return None
    cells = stripped.strip("|").split("|")
    return "| " + " | ".join(cell.strip() for cell in cells) + " |"


def identity_block_content(text: str) -> str:
    r"""Normalize a block for *identity* hashing (issue #118).

    ``normalized_block_content`` plus per-line markdown-table folding -- both
    separator style and cell padding -- with newlines preserved. That middle
    strength is the point:

    - Table restyling (``| --- |`` vs ``|---|``, ``| Need     |`` vs
      ``| Need |``) is a downstream formatter's doing, not an edit, so it must
      not change a block's identity. Hashing ``normalized_block_content`` alone
      made every prettier-formatted block read as hand-edited, blocking commits
      and producing permanent "will upgrade" noise.
    - It is deliberately *not* ``comparison_block_content``, which additionally
      joins every line into one space-separated string. That form cannot tell
      ``"- alpha\\n- beta"`` from ``"- alpha - beta"``; hashing it would quietly
      retire issue #26's token-boundary guarantee, which today survives only
      because the declared sha in the BEGIN marker differs.
    """
    normalized_lines: list[str] = []
    for line in normalized_block_content(text).split("\n"):
        # Separator first: its canonical form is `|---|`, not the `| --- |` the
        # generic row folder would produce.
        folded = _normalize_markdown_table_separator(line)
        if folded is None:
            folded = _normalize_markdown_table_row(line)
        normalized_lines.append(folded if folded is not None else line)
    return "\n".join(normalized_lines)


def comparison_block_content(text: str) -> str:
    """Normalize a block for the more permissive "is this upgradeable?" check.

    Collapses all whitespace, newlines included -- strictly more permissive
    than ``identity_block_content``, which it is derived from so that invariant
    cannot drift. Unlike the identity hash this is always evaluated against a
    known template, so a false match cannot silently launder an edit into
    "unmodified"; the worst case is an in-place block rewrite.
    """
    return " ".join(identity_block_content(text).split())


def block_content_matches(left: str, right: str) -> bool:
    """Whether two blocks are the same under the permissive "upgradeable" comparison."""
    return comparison_block_content(left) == comparison_block_content(right)


def raven_block_sha256(text: str) -> str:
    """The current identity hash for a block's content, declared in a fresh BEGIN marker."""
    return sha256_bytes(identity_block_content(text).encode("utf-8"))


def legacy_raven_block_sha256(text: str) -> str:
    """The pre-#118 block hash, over ``normalized_block_content``.

    Every managed block already written into a destination repo declares one of
    these. Read paths accept it so those blocks keep reading as untouched;
    nothing writes it any more.
    """
    return sha256_bytes(normalized_block_content(text).encode("utf-8"))


def raven_block_begin_for(text: str) -> str:
    """The BEGIN marker line declaring ``text``'s current identity hash."""
    return f"<!-- RAVEN:BEGIN sha256={raven_block_sha256(text)} -->"


def raven_managed_block(text: str) -> str:
    """Wrap ``text`` in a fresh, hash-stamped BEGIN/END block, led by a blank separator line."""
    content = normalized_block_content(text)
    return "\n".join(["", raven_block_begin_for(content), *content.splitlines(), RAVEN_BLOCK_END])


def find_raven_block(text: str) -> RavenBlock | None:
    """Locate the first BEGIN/END managed block in ``text``, or None if there isn't one.

    A BEGIN with no matching END is treated as no block found at all, not a
    parse error -- callers fall back to their unknown/missing-block handling
    rather than raising on a hand-edited or truncated marker.
    """
    lines = text.splitlines()
    for start, line in enumerate(lines):
        match = RAVEN_BLOCK_BEGIN_RE.fullmatch(line.strip())
        if not match:
            continue
        for end in range(start + 1, len(lines)):
            if lines[end].strip() == RAVEN_BLOCK_END:
                return RavenBlock(
                    start=start,
                    end=end,
                    content="\n".join(lines[start + 1 : end]),
                    declared_sha256=match.group(1),
                )
        return None
    return None


def raven_block_sha_is_current(block: RavenBlock) -> bool:
    """True when the declared sha was produced by the current algorithm.

    Distinct from ``raven_block_is_unchanged``, which also accepts the legacy
    hash. A block that is unchanged but not current still needs one marker
    rewrite to migrate; see ``block_managed_state``.
    """
    return block.declared_sha256 == raven_block_sha256(block.content)


def raven_block_is_unchanged(block: RavenBlock) -> bool:
    """True when the declared sha still vouches for the block's own content.

    Accepts the legacy hash as well as the current one (issue #118). Without
    that, changing the identity algorithm would make every managed block
    already written downstream read as hand-edited at once.

    Known residual gap: a block that still declares a legacy sha *and* has
    since been table-restyled by a formatter matches neither hash and reads as
    tampered. It self-heals on the next ``raven upgrade``, which rewrites the
    marker with the current, restyle-invariant hash.
    """
    if block.declared_sha256 is None:
        return False
    return block.declared_sha256 in (
        raven_block_sha256(block.content),
        legacy_raven_block_sha256(block.content),
    )


def block_managed_state(entry: TemplateEntry, target: Path) -> BlockState | None:
    """Classify a root instruction file's managed block against the template, or None if not applicable.

    None covers every case where there is nothing to classify: the entry is not
    a root instruction file, it is installed as a symlink, the target is not a
    plain file, the target is unreadable, or the target has no managed block at
    all. Otherwise returns "identical" (current hash, content matches),
    "upgradeable" (safe to rewrite -- includes the legacy-hash migration case),
    or "modified" (user edits Raven must not overwrite).
    """
    if (
        entry.relative not in ROOT_INSTRUCTION_FILES
        or entry.copy_as_symlink
        or not target.is_file()
    ):
        return None
    try:
        target_text = target.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        # An unreadable or non-UTF-8 destination file has no managed block we can
        # detect. Report "no block state" rather than crash; classify() falls back
        # to its hash-based/unknown_existing path for a file like this.
        return None
    block = find_raven_block(target_text)
    if block is None:
        return None
    source_text = normalized_block_content(entry.source.read_text(encoding="utf-8"))
    block_text = normalized_block_content(block.content)
    if identity_block_content(block_text) == identity_block_content(source_text):
        # Byte-for-byte the template, or the template as a markdown formatter
        # restyled it -- the same block either way (#118). "identical" needs the
        # *current* hash, not merely a valid one, so a marker still declaring the
        # legacy hash classifies "upgradeable" exactly once; the rewrite makes it
        # current and every later run reports "identical".
        return "identical" if raven_block_sha_is_current(block) else "upgradeable"
    if block_content_matches(block_text, source_text):
        return "upgradeable"
    if not raven_block_is_unchanged(block):
        return "modified"
    return "upgradeable"


def update_raven_block(entry: TemplateEntry, target: Path) -> None:
    """Rewrite ``target``'s managed block in place with the template's current content.

    Raises rather than overwriting when the block is missing or has diverged
    from both the current and legacy identity hash *and* doesn't content-match
    the template -- callers must route a genuinely modified block through the
    guided-merge path instead of calling this directly.
    """
    text = target.read_text(encoding="utf-8")
    block = find_raven_block(text)
    source_text = normalized_block_content(entry.source.read_text(encoding="utf-8"))
    if block is None or (
        not raven_block_is_unchanged(block)
        and not block_content_matches(block.content, source_text)
    ):
        raise ValueError(f"cannot safely update modified or missing Raven block: {entry.relative}")
    lines = text.splitlines()
    replacement = raven_managed_block(entry.source.read_text(encoding="utf-8")).splitlines()[1:]
    updated = lines[: block.start] + replacement + lines[block.end + 1 :]
    trailing_newline = "\n" if text.endswith("\n") else ""
    final_content = "\n".join(updated) + trailing_newline
    if target.is_symlink():
        target.unlink()
    target.write_text(final_content, encoding="utf-8")


def template_entry_text(entry: TemplateEntry) -> str:
    """The text a merge artifact for ``entry`` should contain.

    A symlink entry has no text of its own to offer as merge material, so this
    substitutes an explanatory stub telling the user what Raven would normally
    have done, rather than dumping the symlink target's raw bytes.
    """
    if entry.copy_as_symlink:
        target = os.readlink(entry.source)
        return (
            f"# Raven suggested handling for `{entry.relative}`\n\n"
            f"Raven normally installs `{entry.relative}` as a symlink to `{target}`.\n\n"
            "Because this file already exists in the destination repository, Raven did not replace it. "
            "Review the existing file and decide whether to keep it, merge guidance from AGENTS.md, "
            "or manually convert it to the symlink/pointer your agent tooling expects.\n"
        )
    return entry.source.read_text(encoding="utf-8")


def append_patch_text(relative: str, existing_text: str, raven_text: str) -> str:
    """Build a ``patch``-appliable hunk that installs the current Raven block.

    If the file already contains a managed block, the hunk **replaces** that block
    in place; appending a second one would leave two ``RAVEN:BEGIN`` blocks (#55).
    Only a file with no block yet gets an append hunk.
    """
    existing_lines = existing_text.splitlines()
    block = find_raven_block(existing_text)
    if block is not None:
        # Replace the existing block region (BEGIN..END inclusive) in place. Drop
        # the leading blank separator that ``raven_managed_block`` prepends -- the
        # blank already precedes the existing block in the file.
        new_lines = raven_managed_block(raven_text).splitlines()[1:]
        old_lines = existing_lines[block.start : block.end + 1]
        start = block.start + 1
        patch_lines = [
            f"--- a/{relative}",
            f"+++ b/{relative}",
            f"@@ -{start},{len(old_lines)} +{start},{len(new_lines)} @@",
            *[f"-{line}" for line in old_lines],
            *[f"+{line}" for line in new_lines],
            "",
        ]
        return "\n".join(patch_lines)
    block_lines = raven_managed_block(raven_text).splitlines()
    start = len(existing_lines) + 1
    count = len(block_lines)
    patch_lines = [
        f"--- a/{relative}",
        f"+++ b/{relative}",
        f"@@ -{len(existing_lines)},0 +{start},{count} @@",
        *[f"+{line}" for line in block_lines],
        "",
    ]
    return "\n".join(patch_lines)


def unified_diff_text(relative: str, existing_text: str, template_text: str) -> str:
    """Build a review-only unified diff from the local file to the template version.

    Unlike ``append_patch_text``, this is informational: it shows how the existing
    file differs from the Raven template version. It is not meant to be applied
    with ``patch`` -- arbitrary JSON/TOML/etc. files have no managed block to
    append to, so the user merges by hand.
    """
    diff = difflib.unified_diff(
        existing_text.splitlines(keepends=True),
        template_text.splitlines(keepends=True),
        fromfile=f"{relative} (your version)",
        tofile=f"{relative} (Raven template)",
    )
    return "".join(diff)


_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_FENCE_RE = re.compile(r"^(`{3,}|~{3,})")
_HEADING_TRAILING_PUNCT_RE = re.compile(r"[\s:.]+$")


def top_level_headings(text: str, levels: tuple[str, ...] = ("#", "##")) -> list[str]:
    """Whitespace-collapsed ATX heading text for the given marker depths.

    Skips headings inside fenced code blocks (``` or ~~~): a ``## `` line shown
    as example markdown syntax is not a real section, so counting it as one
    would produce false "duplicate heading" positives. Fence detection is a
    simple open/close toggle on any line whose stripped content starts with 3+
    backticks or tildes -- it does not require the opening and closing fence
    characters or lengths to match, which is enough for well-formed markdown
    and errs toward *not* treating content as a heading when unsure.

    ``levels`` is exposed because the two call sites in this module want
    different depths for the same document shape: the Raven template's own
    guardrail sections are always written ``##``, while a hand-written
    destination file's structural sections are just as often flat ``#``.
    Depths past ``###`` are never returned regardless of ``levels`` -- deeper
    headings are far more likely to be incidental subsection titles than a
    duplicate of a whole guardrail topic, which would make overlap detection
    noisier without making it more useful.
    """
    headings: list[str] = []
    in_fence = False
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if _FENCE_RE.match(stripped):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        match = _HEADING_RE.match(stripped)
        if match and len(match.group(1)) <= 3 and match.group(1) in levels:
            headings.append(" ".join(match.group(2).split()))
    return headings


def _normalize_heading_text(text: str) -> str:
    """Fold heading text to a comparison key: casefold, trim trailing punctuation.

    Deliberately not a fuzzy or word-subset match -- see
    ``duplicated_template_headings`` for why -- so this only absorbs trivial
    formatting differences (case, a trailing colon or period), never wording
    differences.
    """
    return _HEADING_TRAILING_PUNCT_RE.sub("", text).casefold()


def duplicated_template_headings(existing_text: str, raven_text: str) -> list[str]:
    """Template ``##`` section headings the existing file already has, by name.

    Used only to warn about an append-only instruction-file merge (no managed
    block yet): if ``existing_text`` already has, in the destination's own
    words, a section titled the same as one of Raven's, appending the template
    block verbatim leaves two write-ups of that guardrail.

    Matching is exact modulo case and trailing punctuation -- not a fuzzy or
    word-subset match. That is a precision-over-recall choice: this result
    drives a *recommendation to delete* the destination's existing section, so
    a false positive is actively harmful advice, while a false negative
    (missing, say, "## Safety" as a partial match for "## Safety Rules") just
    leaves today's plain append-and-review advice in place -- no worse than
    before this change. Real heading reuse -- someone adopting a convention
    that happens to coincide with Raven's own section names -- is normally a
    near-verbatim copy, so this still catches the common case the issue is
    about.

    Only the template's ``##`` headings are checked (not its own leading ``#``
    title): the template's title line is not a guardrail topic, so matching it
    against a destination file's own, similarly-named title would be a false
    positive that has nothing to do with duplicated guidance. The destination
    side stays permissive (``#`` and ``##``) since a hand-written file's
    structural sections are just as often flat ``#``.

    Returned in the template's own heading order, using the template's
    original heading text (not the destination's) since that is the name used
    in the merge instructions and the template docs.
    """
    existing_normalized = {_normalize_heading_text(h) for h in top_level_headings(existing_text)}
    return [
        heading
        for heading in top_level_headings(raven_text, levels=("##",))
        if _normalize_heading_text(heading) in existing_normalized
    ]


def guided_merge_instructions(
    relative: str,
    suggestion: str,
    patch: str | None,
    diff: str | None = None,
    *,
    replaces_block: bool = False,
    overlapping_headings: tuple[str, ...] = (),
) -> str:
    """Build the guided-merge instructions body for an existing file.

    Pure. At most one of ``patch``/``diff`` is set:
    ``patch`` is the relative path of a managed-block patch (instruction files
    only); ``diff`` is the relative path of a review-only unified diff (all other
    files); both ``None`` means only a fully manual merge is possible.
    ``replaces_block`` is True when the file already has a managed block the patch
    replaces in place (vs appending a new one).
    ``overlapping_headings`` names template guardrail sections (see
    ``duplicated_template_headings``) that the existing file already covers
    under the same heading, in its own words. Meaningful only when
    ``replaces_block`` is False: a file that already has a managed block is
    updated in place, so there is no new duplication risk to warn about, and
    the value is ignored in that case.
    """
    header = (
        f"# Guided Raven merge for `{relative}`\n\n"
        f"Raven found an existing `{relative}` and did not modify it.\n\n"
    )
    if patch is None and diff is not None:
        return (
            header + f"- Existing file: `{relative}`\n"
            f"- Raven template version for review: `{suggestion}`\n"
            f"- What differs from the template: `{diff}`\n\n"
            "## Manual merge\n\n"
            f"`{relative}` is not a managed-block instruction file, so Raven cannot apply an "
            "automatic patch. Review the diff to see exactly what changed:\n\n"
            f"```sh\ncat {diff}\n```\n\n"
            f"Then copy whatever applies from `{suggestion}` into `{relative}` manually.\n\n"
            f"When done, run `raven accept {relative}` (or `raven accept` to accept every "
            "pending merge). This records your merged file as the new baseline and removes "
            "these artifacts, so future upgrades will not prompt again until the template "
            "changes.\n\n"
            "Do not apply the template blindly if the repository already has stronger local settings.\n"
        )
    if patch is not None:
        patch_label = "Block-update patch" if replaces_block else "Append-only patch"
        effect = (
            "This replaces the existing `RAVEN:BEGIN` / `RAVEN:END` managed block in place."
            if replaces_block
            else "This appends a `RAVEN:BEGIN` / `RAVEN:END` managed block to the existing file."
        )
        if overlapping_headings and not replaces_block:
            heading_list = ", ".join(f"`{h}`" for h in overlapping_headings)
            return (
                header + f"- Existing file: `{relative}`\n"
                f"- Raven suggestion for review: `{suggestion}`\n"
                f"- {patch_label}: `{patch}`\n"
                f"- Headings `{relative}` already has that the Raven template also covers: "
                f"{heading_list}\n\n"
                "## Heads up: likely duplicate guardrails\n\n"
                f"`{relative}` already has its own section for {heading_list}. A dry run of the "
                "patch will succeed regardless of that -- for an append-only patch it almost "
                "always does -- so it only proves the patch *applies*, not that the result is "
                "*desirable*. If those sections already say what Raven's template says, just in "
                "different words, applying the patch as-is leaves two write-ups of each "
                "guardrail.\n\n"
                "## Recommended: apply the patch, then delete the now-redundant sections\n\n"
                "Raven only owns the `RAVEN:BEGIN` / `RAVEN:END` region it manages; everything "
                "outside that region is preserved untouched by future upgrades. So you can have "
                "auto-upgrading guardrails without duplication:\n\n"
                f"```sh\npatch -p1 < {patch}\n```\n\n"
                f"Then open `{relative}`, compare your original {heading_list} sections against "
                "the new block, and delete whatever the block now covers just as well -- keeping "
                "any genuinely local guidance that does not overlap.\n\n"
                "## Other options\n\n"
                f"- Apply the patch and leave the duplication for later: `patch -p1 < {patch}`. "
                f"{effect} Future Raven upgrades can update that block automatically as long as "
                "it is not edited directly, but you will have two write-ups of the same guardrail "
                "until you deduplicate by hand.\n"
                f"- Skip the patch and merge manually instead: review `{suggestion}` and copy "
                "only the guidance that applies. Without the managed block markers, Raven will "
                "not be able to upgrade that content automatically later.\n\n"
                f"Whichever you choose, run `raven accept {relative}` (or `raven accept`) "
                "afterwards to remove these artifacts.\n"
            )
        return (
            header + f"- Existing file: `{relative}`\n"
            f"- Raven suggestion for review: `{suggestion}`\n"
            f"- {patch_label}: `{patch}`\n\n"
            "## Recommended automatic merge\n\n"
            "From the destination repository root, inspect the patch first:\n\n"
            f"```sh\npatch --dry-run -p1 < {patch}\n```\n\n"
            "If the dry run succeeds and the Raven guidance is appropriate, apply it:\n\n"
            f"```sh\npatch -p1 < {patch}\n```\n\n"
            f"{effect} "
            "Future Raven upgrades can update that block automatically as long as it is not edited directly.\n\n"
            "## Manual merge option\n\n"
            f"Review `{suggestion}` and copy only the guidance that applies. If you do this without "
            "the managed block markers, "
            "Raven will not be able to upgrade that content automatically later.\n\n"
            f"Either way, run `raven accept {relative}` (or `raven accept`) afterwards to remove "
            "these artifacts.\n\n"
            "Do not apply the suggestion blindly if the repository already has stronger local instructions.\n"
        )
    return (
        header + f"- Existing file: `{relative}`\n"
        f"- Raven suggestion for review: `{suggestion}`\n\n"
        "Raven could not generate an automatic text patch for this file. Review the suggestion "
        "and manually merge the guidance that applies.\n\n"
        "Do not apply the suggestion blindly if the repository already has stronger local instructions.\n"
    )


def _existing_ignore_patterns(text: str) -> set[str]:
    """Effective ignore patterns from .gitignore text.

    Compares by exact pattern, not substring, so a comment or a longer path
    that merely contains an entry does not count as the entry (see #43).
    """
    patterns = set()
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        patterns.add(line)
    return patterns


def _ensure_merge_dir_gitignored(destination: Path) -> None:
    """Ignore MERGE_DIR in the destination's .gitignore.

    Guided-merge scratch artifacts are transient review material, not
    something meant to be committed. Without this, a broad `git add` run
    before `raven accept` picks them up as ordinary untracked files.
    """
    entry = f"{MERGE_DIR.as_posix()}/"
    gitignore = destination / ".gitignore"
    existing = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
    if entry in _existing_ignore_patterns(existing):
        return
    prefix = "" if not existing or existing.endswith("\n") else "\n"
    block = f"{prefix}\n# Raven guided-merge scratch artifacts\n{entry}\n"
    with gitignore.open("a", encoding="utf-8") as f:
        f.write(block)


def _write_merge_artifact(path: Path, text: str) -> None:
    """Write a merge artifact, replacing a symlink in place.

    A merge-state path that is a symlink would route the write outside the
    destination. Unlinking it first keeps every guided-merge write inside
    ``.raven/merge/``.
    """
    if path.is_symlink():
        path.unlink()
    path.write_text(text, encoding="utf-8")


def write_guided_merge_artifacts(
    destination: Path, entries: dict[str, TemplateEntry], paths: list[str]
) -> list[str]:
    """Write ``.raven/merge/<path>.raven`` plus a patch/diff for every path needing a guided merge.

    Skips a path silently when its entry is missing from ``entries`` or the
    destination file doesn't exist -- both mean there is nothing meaningful to
    merge against. Returns the destination-relative paths of every artifact
    actually written, for the caller to report.
    """
    written: list[str] = []
    merge_dir = destination / MERGE_DIR
    for relative in sorted(set(paths)):
        entry = entries.get(relative)
        target = destination / relative
        if entry is None or not _any_exists(target):
            continue
        raven_path = merge_dir / f"{relative}.raven"
        raven_path.parent.mkdir(parents=True, exist_ok=True)
        raven_text = template_entry_text(entry)
        _write_merge_artifact(raven_path, raven_text)
        written.append(raven_path.relative_to(destination).as_posix())

        suggestion = raven_path.relative_to(destination).as_posix()
        patch_rel: str | None = None
        diff_rel: str | None = None
        replaces_block = False
        overlapping_headings: tuple[str, ...] = ()
        existing_text: str | None = None
        if not entry.copy_as_symlink and target.is_file():
            try:
                existing_text = target.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                # Unreadable or non-UTF-8 existing file: fall through to the
                # manual-merge-only instructions below rather than crash mid-apply.
                existing_text = None
        if existing_text is not None:
            # Instruction files use RAVEN managed blocks, so a managed-block patch
            # merges cleanly. Any other file gets a review-only diff instead --
            # appending a managed block would corrupt arbitrary JSON/TOML/etc.
            if relative in ROOT_INSTRUCTION_FILES:
                # A file that already has a block gets a replace patch, not an
                # append (which would duplicate the block, #55).
                replaces_block = find_raven_block(existing_text) is not None
                patch_path = merge_dir / f"{relative}.patch"
                _write_merge_artifact(
                    patch_path, append_patch_text(relative, existing_text, raven_text)
                )
                patch_rel = patch_path.relative_to(destination).as_posix()
                if not replaces_block:
                    # Duplication is only a risk for an append: a file that already
                    # has a block is updated in place, not doubled up (#133).
                    overlapping_headings = tuple(
                        duplicated_template_headings(existing_text, raven_text)
                    )
            else:
                diff_path = merge_dir / f"{relative}.diff"
                _write_merge_artifact(
                    diff_path, unified_diff_text(relative, existing_text, raven_text)
                )
                diff_rel = diff_path.relative_to(destination).as_posix()

        instructions_path = merge_dir / f"{relative}.instructions.md"
        body = guided_merge_instructions(
            relative,
            suggestion,
            patch_rel,
            diff_rel,
            replaces_block=replaces_block,
            overlapping_headings=overlapping_headings,
        )
        _write_merge_artifact(instructions_path, body)
        written.append(instructions_path.relative_to(destination).as_posix())
        if patch_rel:
            written.append(patch_rel)
        if diff_rel:
            written.append(diff_rel)
    if written:
        _ensure_merge_dir_gitignored(destination)
    return written


_MERGE_ARTIFACT_SUFFIXES = (".raven", ".diff", ".patch", ".instructions.md")


def pending_merge_paths(destination: Path) -> list[str]:
    """Destination-relative paths with guided-merge artifacts awaiting acceptance.

    Each merged file has exactly one ``<path>.instructions.md`` artifact, so the
    instruction files are the canonical record of what is still pending.
    """
    merge_dir = destination / MERGE_DIR
    if not merge_dir.is_dir():
        return []
    suffix = ".instructions.md"
    paths = [
        artifact.relative_to(merge_dir).as_posix()[: -len(suffix)]
        for artifact in merge_dir.rglob(f"*{suffix}")
    ]
    return sorted(paths)


def remove_merge_artifacts(destination: Path, paths: list[str]) -> list[str]:
    """Delete the guided-merge artifacts for ``paths`` and prune empty dirs."""
    merge_dir = destination / MERGE_DIR
    removed: list[str] = []
    for relative in paths:
        for suffix in _MERGE_ARTIFACT_SUFFIXES:
            artifact = merge_dir / f"{relative}{suffix}"
            if artifact.exists() or artifact.is_symlink():
                artifact.unlink()
                removed.append(artifact.relative_to(destination).as_posix())
    if merge_dir.is_dir():
        for directory in sorted((p for p in merge_dir.rglob("*") if p.is_dir()), reverse=True):
            with suppress(OSError):
                directory.rmdir()
        with suppress(OSError):
            merge_dir.rmdir()
    return sorted(removed)
