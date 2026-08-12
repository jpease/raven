"""The shared `Finding`/`Severity` vocabulary `doctor` and `assess` report through.

Keeping this common to both means `report.render_human`/`render_json` and the exit
code convention (only ERROR fails the process) are defined once, not duplicated
per command.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Severity(str, Enum):
    """How urgently a `Finding` should be acted on; only ERROR affects `exit_code`."""

    INFO = "info"
    OK = "ok"
    WARN = "warn"
    ERROR = "error"


@dataclass(frozen=True)
class Finding:
    """One reported observation: a stable ``id``, its severity, and human-readable detail."""

    id: str
    severity: Severity
    category: str
    title: str
    detail: str
    fix: str | None = None


def exit_code(findings: list[Finding]) -> int:
    """Process exit code for a findings list: 1 if any is ERROR, else 0."""
    return 1 if any(f.severity is Severity.ERROR for f in findings) else 0


def summarize(findings: list[Finding]) -> dict[str, int]:
    """Count findings by severity, keyed by "errors"/"warnings"/"info"/"ok"."""
    return {
        "errors": sum(1 for f in findings if f.severity is Severity.ERROR),
        "warnings": sum(1 for f in findings if f.severity is Severity.WARN),
        "info": sum(1 for f in findings if f.severity is Severity.INFO),
        "ok": sum(1 for f in findings if f.severity is Severity.OK),
    }
