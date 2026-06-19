from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Severity(str, Enum):
    OK = "ok"
    WARN = "warn"
    ERROR = "error"


@dataclass(frozen=True)
class Finding:
    id: str
    severity: Severity
    category: str
    title: str
    detail: str
    fix: str | None = None


def exit_code(findings: list[Finding]) -> int:
    return 1 if any(f.severity is Severity.ERROR for f in findings) else 0


def summarize(findings: list[Finding]) -> dict[str, int]:
    return {
        "errors": sum(1 for f in findings if f.severity is Severity.ERROR),
        "warnings": sum(1 for f in findings if f.severity is Severity.WARN),
        "ok": sum(1 for f in findings if f.severity is Severity.OK),
    }
