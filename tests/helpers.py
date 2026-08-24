import argparse
import importlib.util
import shutil
import sys
import tempfile
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path
from typing import Any, Optional, cast

REPO_ROOT = Path(__file__).resolve().parents[1]
RAVEN_PATH = REPO_ROOT / "scripts" / "raven.py"

# The shared config-parsing module every rewired hook/script under
# common/.claude and common/.raven/git-hooks loads as a sibling file (see
# common/.raven/git-hooks/lib/raven_config.py). It ships under the "hooks"
# component alongside .raven/git-hooks itself, so any test fixture that
# fabricates an installed-project layout (rather than loading a caller
# straight from common/) needs a copy of it at the matching relative path for
# that caller's own __file__-relative or root-relative resolution to find it.
RAVEN_CONFIG_LIB = REPO_ROOT / "common" / ".raven" / "git-hooks" / "lib" / "raven_config.py"

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


def install_raven_config_lib(destination: Path) -> Path:
    """Copy raven_config.py into a fabricated project's ``.raven/git-hooks/lib/``.

    Mirrors what a real ``raven install``/``upgrade`` places there, for a test
    fixture that builds a synthetic installed-project tree from scratch
    (rather than loading a caller module straight out of ``common/``, where
    the real file already sits at the matching relative offset). Returns the
    destination path written.
    """
    lib_dir = destination / ".raven" / "git-hooks" / "lib"
    lib_dir.mkdir(parents=True, exist_ok=True)
    target = lib_dir / "raven_config.py"
    shutil.copy2(RAVEN_CONFIG_LIB, target)
    return target


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
# language -> (server command, whether mcp-language-server forwards `-- --stdio`,
#              official Claude Code LSP plugin shipping the same server, or None)
#
# The third field decides which harness gets the `mcp-language-server` bridge.
# Claude Code's official marketplace LSP plugins launch the language server
# themselves, and a language server started twice is two full instances: two
# indexes, two resident processes. `sourcekit-lsp` makes the cost impossible to
# ignore -- each client gets its own `SourceKitService`, measured here between
# 0.3 GB and 6.5 GB, on top of the one Xcode already runs. So a language with a
# plugin ships no `lsp` server in `.mcp.json`. Codex has no LSP integration of
# its own (verified against codex-cli 0.149.1), so `.codex/config.toml` keeps
# the bridge for every language.
LSP_DEFAULTS = {
    "python": ("pyright-langserver", True, "pyright-lsp"),
    "typescript": ("typescript-language-server", True, "typescript-lsp"),
    "go": ("gopls", False, "gopls-lsp"),
    "rust": ("rust-analyzer", False, "rust-analyzer-lsp"),
    "swift": ("sourcekit-lsp", False, "swift-lsp"),
    "elixir": ("expert", True, None),
    "lua": ("lua-language-server", False, "lua-lsp"),
    "ruby": ("ruby-lsp", False, "ruby-lsp"),
}


def claude_lsp_plugin(language: str) -> Optional[str]:
    """The official Claude Code LSP plugin for `language`, or None if there is none."""
    return LSP_DEFAULTS[language][2]


def lsp_mcp_args(language: str) -> list[str]:
    """The `mcp-language-server` argv a template's MCP config must declare."""
    server, forwards_stdio, _ = LSP_DEFAULTS[language]
    args = ["--workspace", ".", "--lsp", server]
    if forwards_stdio:
        args += ["--", "--stdio"]
    return args


def lsp_doc_command(language: str) -> str:
    """How a doc table spells the server, e.g. `pyright-langserver --stdio`."""
    server, forwards_stdio, _ = LSP_DEFAULTS[language]
    return f"{server} --stdio" if forwards_stdio else server


# Adapter files that are byte-identical between the two harnesses and are
# therefore stored once, under `common/.claude/<subdir>/`, with the Codex copies
# as template-internal symlinks. See `.claude/docs/raven-agent-compatibility.md`
# ("Adapter File Classification") for the per-file classification, including the
# files deliberately *not* unified.
#
# Deliberately pinned by hand rather than globbed: adding a file to
# `.codex/<subdir>/` without either unifying it or classifying it as
# path-transformed or intentionally asymmetric should fail a test, not pass by
# omission.
UNIFIED_ADAPTER_SCRIPTS = (
    "raven-capability-roster.py",
    "raven-session.py",
    "raven-skeleton.py",
    "raven-tool-check.py",
)
UNIFIED_ADAPTER_HOOKS = (
    "raven-post-bash-summarize.py",
    "raven-post-edit-format.py",
    "raven-pre-bash-guard.py",
    "raven-pre-edit-guard.py",
    "raven-session-checkpoint.py",
)


def codex_symlink_target(subdir: str, name: str) -> str:
    """The exact symlink target each unified `.codex/<subdir>/` entry must use.

    The spelling is load-bearing, not cosmetic. `should_preserve_symlink` in
    `scripts/raven_lib/template.py` dereferences a symlink -- copying real
    content to the destination -- only when its target climbs back in through
    `common/`; anything else is preserved *as a symlink* at the destination.

    The paired components are independently toggleable
    (`[components.claude] scripts = false`), so a destination-level symlink from
    one adapter into the other dangles whenever only one is installed. Spelling
    the target as a climb through `common/` is what keeps these links inside the
    template. The shorter `../../.claude/<subdir>/<name>` resolves to the same
    file but would ship dangling symlinks -- do not "simplify" it.

    Three levels up works from both `common/.codex/<subdir>/` and a language
    tree's `<lang>/.codex/<subdir>/`, because the two sit at the same depth.
    """
    return f"../../../common/.claude/{subdir}/{name}"


def codex_script_symlink_target(name: str) -> str:
    """The symlink target for a unified `.codex/scripts/` entry."""
    return codex_symlink_target("scripts", name)


def codex_hook_symlink_target(name: str) -> str:
    """The symlink target for a unified `.codex/hooks/` entry."""
    return codex_symlink_target("hooks", name)


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
