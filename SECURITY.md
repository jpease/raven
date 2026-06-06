# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in Raven, please report it privately rather than opening a public issue.

**Email:** 536+jpease@users.noreply.github.com

Please include:
- A description of the vulnerability and its potential impact
- Steps to reproduce
- Any suggested mitigations

You can expect an initial response within 5 business days. If the vulnerability is confirmed, a fix will be prioritized and a patched release made available before public disclosure.

## Scope

Raven is a template installer and guidance library. Security-relevant areas include:

- `scripts/raven.py` — file copy, managed block upgrade, and symlink operations
- `.claude/hooks/raven-pre-bash-guard.py` — shell command interception
- `.claude/hooks/raven-pre-edit-guard.py` — file edit interception

## Out of Scope

- Vulnerabilities in third-party tools that Raven templates reference (language servers, MCP bridges, etc.)
- Issues arising from user-modified template content
