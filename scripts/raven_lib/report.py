from __future__ import annotations

import json

from .findings import Finding, Severity, summarize

_MARK = {Severity.INFO: "ⓘ", Severity.OK: "✓", Severity.WARN: "!", Severity.ERROR: "✗"}
_MARK_ASCII = {Severity.INFO: "i", Severity.OK: "ok", Severity.WARN: "!", Severity.ERROR: "x"}


def supports_unicode_marks(encoding: str | None) -> bool:
    """Return whether the given stream encoding can represent the human-output severity marks."""
    if not encoding:
        return False
    try:
        "".join(_MARK.values()).encode(encoding)
    except (LookupError, UnicodeEncodeError):
        return False
    return True


def render_human(
    command: str, os_name: str, findings: list[Finding], *, ascii_marks: bool = False
) -> str:
    marks = _MARK_ASCII if ascii_marks else _MARK
    lines: list[str] = [f"raven {command} ({os_name})", ""]
    categories = list(dict.fromkeys(f.category for f in findings))
    for category in categories:
        lines.append(category)
        for finding in [f for f in findings if f.category == category]:
            lines.append(f"  {marks[finding.severity]} {finding.title}")
            if finding.severity is not Severity.OK:
                lines.append(f"      {finding.detail}")
                if finding.fix:
                    lines.append(f"      fix: {finding.fix}")
        lines.append("")
    counts = summarize(findings)
    lines.append(
        f"Summary: {counts['errors']} errors, {counts['warnings']} warnings, "
        f"{counts['info']} info, {counts['ok']} ok"
    )
    return "\n".join(lines)


def render_json(command: str, os_name: str, findings: list[Finding]) -> str:
    payload = {
        "command": command,
        "os": os_name,
        "findings": [
            {
                "id": f.id,
                "severity": f.severity.value,
                "category": f.category,
                "title": f.title,
                "detail": f.detail,
                "fix": f.fix,
            }
            for f in findings
        ],
        "summary": summarize(findings),
    }
    return json.dumps(payload, indent=2)
