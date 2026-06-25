from __future__ import annotations

import json

from .findings import Finding, Severity, summarize

_MARK = {Severity.INFO: "ⓘ", Severity.OK: "✓", Severity.WARN: "!", Severity.ERROR: "✗"}


def render_human(command: str, os_name: str, findings: list[Finding]) -> str:
    lines: list[str] = [f"raven {command} ({os_name})", ""]
    categories = list(dict.fromkeys(f.category for f in findings))
    for category in categories:
        lines.append(category)
        for finding in [f for f in findings if f.category == category]:
            lines.append(f"  {_MARK[finding.severity]} {finding.title}")
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
