import argparse
import importlib.util
import sys
import tempfile
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path
from typing import Any, cast

REPO_ROOT = Path(__file__).resolve().parents[1]
RAVEN_PATH = REPO_ROOT / "scripts" / "raven.py"

sys.path.insert(0, str(REPO_ROOT / "scripts"))
import raven_lib as raven  # noqa: E402,F401


def load_script_module(name: str, path: Path) -> Any:
    """Load a standalone Raven script as a module for testing.

    Returns the module typed as ``Any`` on purpose: a script loaded from a
    file path has no importable static type, and these tests intentionally
    read and monkeypatch its attributes. Centralizing the import keeps the
    ``spec``/``loader`` None-checks in one Pyright-friendly place.
    """
    # The loader is passed explicitly so extensionless scripts load too: Raven's
    # git hooks are named `commit-msg`/`pre-push`, and spec_from_file_location
    # infers no loader for a path whose suffix it does not recognize.
    spec = importlib.util.spec_from_file_location(
        name, path, loader=SourceFileLoader(name, str(path))
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"could not load module {name!r} from {path}")
    module = importlib.util.module_from_spec(spec)
    # Register before exec so the module can resolve its own namespace -- e.g.
    # @dataclass under ``from __future__ import annotations`` looks the module up
    # in sys.modules to evaluate string annotations. This mirrors the import
    # system's own loading order.
    sys.modules[name] = module
    # spec_from_file_location yields a SourceFileLoader; cast past the
    # importlib.abc.Loader base, whose typeshed stub omits exec_module.
    cast(SourceFileLoader, spec.loader).exec_module(module)
    return module


def attribution_line(tool: str = "Claude", verb: str = "Generated", prep: str = "by") -> str:
    """Build an AI-attribution line that the scanners under test must reject.

    Assembled at runtime rather than written as one literal, so no test file's
    own source contains the exact phrase -- the AI-attribution content scan runs
    on this repository too (see pre-commit/pre-push), and a literal here would
    fail Raven's own gate. That constraint is the reason this lives in one
    place: it was previously duplicated, where a well-meaning "simplify it to a
    string" edit in either copy would break the repo's own commit path.
    """
    return f"# {verb} {prep} {tool}\n"


def trailer_line(
    tool: str = "Claude",
    key: str = "Co-Authored-By",
    email: str = "dev@example.com",
) -> str:
    """Build an AI-attribution commit *message* trailer the scanners must reject.

    Assembled at runtime for the same reason as ``attribution_line``: Raven's
    own hooks run on this repository, and the commit-msg hook would strip a
    literal trailer out of any commit that touched a file containing one.
    """
    return f"{key}: {tool} <{email}>\n"


def push_plan_line(ref: str, local_sha: str, remote_sha: str) -> str:
    """Build one line of the ref plan Git feeds a pre-push hook on stdin.

    The format is ``<local-ref> <local-sha> <remote-ref> <remote-sha>``. Issue
    #126 was a scan that read the checked-out branch instead of this plan, so
    tests that drive a pre-push hook must supply the real thing.
    """
    return f"{ref} {local_sha} {ref} {remote_sha}\n"


# The single source of truth for each language template's default LSP server.
# Everything else that names one -- both `.mcp.json` files, `.codex/config.toml`,
# the README table, and `.claude/docs/raven-lsp-mcp.md` -- is checked against
# this rather than restating it. Previously the same server names were spelled
# out in eight shipped files, two doc tables, and two near-identical dicts in
# test_template.py, so a server change had ten places to miss.
#
# Deliberately pinned by hand, not derived from the shipped files: changing a
# template's language server should be an explicit edit here that fails every
# consistency check until the templates and docs are updated to match. Validate
# a new default against upstream maintainer docs first (see CLAUDE.md).
#
# language -> (server command, whether mcp-language-server forwards `-- --stdio`)
LSP_DEFAULTS = {
    "python": ("pyright-langserver", True),
    "typescript": ("typescript-language-server", True),
    "go": ("gopls", False),
    "rust": ("rust-analyzer", False),
    "swift": ("sourcekit-lsp", False),
    "elixir": ("expert", True),
    "lua": ("lua-language-server", False),
    "ruby": ("ruby-lsp", False),
}


def lsp_mcp_args(language: str) -> list[str]:
    """The `mcp-language-server` argv a template's MCP config must declare."""
    server, forwards_stdio = LSP_DEFAULTS[language]
    args = ["--workspace", ".", "--lsp", server]
    if forwards_stdio:
        args += ["--", "--stdio"]
    return args


def lsp_doc_command(language: str) -> str:
    """How a doc table spells the server, e.g. `pyright-langserver --stdio`."""
    server, forwards_stdio = LSP_DEFAULTS[language]
    return f"{server} --stdio" if forwards_stdio else server


def install_ns(destination: Path, language: str = "python", *, dry_run: bool = False):
    """The argparse namespace `cmd_install` expects, with test-friendly defaults."""
    return argparse.Namespace(
        destination=str(destination),
        language=language,
        args=None,
        overrides=[],
        dry_run=dry_run,
        include_readme=False,
        adopt_claude_symlink=False,
        platform=None,
    )


def upgrade_ns(destination: Path, *, dry_run: bool = False):
    """The argparse namespace `cmd_upgrade` expects, with test-friendly defaults."""
    return argparse.Namespace(
        destination=str(destination),
        overrides=[],
        dry_run=dry_run,
        include_readme=False,
        adopt_claude_symlink=False,
    )


class RavenTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.destination = Path(self.tmp.name)
        self.template = REPO_ROOT / "python"
        self.excludes = {"README.md"}
