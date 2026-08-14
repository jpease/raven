"""Cross-checks between `common/.claude/settings.json`'s `permissions.deny`
block and the two Python hooks it backstops (issue #199).

Native `permissions.deny` is additive, host-enforced defense-in-depth
alongside `raven-pre-bash-guard.py` and `raven-pre-edit-guard.py` -- NOT a
replacement. Codex has no `permissions` equivalent; the two hooks remain its
only protection, and this file must never be read as license to weaken them.
See `common/.claude/docs/raven-guardrails.md` for the two-layer model these
tests verify, including what the native layer cannot catch.

Every check here reads its "expected" side from a real source (the edit
guard's module-level `BLOCKED`/`CAUTION` lists, or the bash guard's own
`DENIED_BASH_COMMANDS` test fixture) and its "actual" side from the real,
parsed `settings.json` -- never a second hardcoded copy of either list. The
one unavoidable exception is the bash guard's destructive-intent surface,
which is Python control flow (`_is_destructive_intent`,
`_is_destructive_rm`, `_is_destructive_git_clean`) rather than a data list
and so cannot be introspected generically; that expected-coverage side is
necessarily hardcoded test data, called out where it appears below.
"""

from __future__ import annotations

import fnmatch
import json
import re
import unittest

from helpers import REPO_ROOT, load_script_module
from test_agent_hooks import DENIED_BASH_COMMANDS, PIPE_TO_SHELL_DENIED_COMMANDS

SETTINGS_PATH = REPO_ROOT / "common" / ".claude" / "settings.json"
EDIT_GUARD_PATH = REPO_ROOT / "common" / ".claude" / "hooks" / "raven-pre-edit-guard.py"


def _load_deny_rules() -> list[str]:
    data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    return data["permissions"]["deny"]


def _rule_pattern(rule: str, tool: str) -> str | None:
    """Strip a `Tool(pattern)` deny-rule string down to its bare pattern."""
    prefix = f"{tool}("
    if rule.startswith(prefix) and rule.endswith(")"):
        return rule[len(prefix) : -1]
    return None


_ALL_DENY_RULES = _load_deny_rules()
READ_RULES = [p for r in _ALL_DENY_RULES if (p := _rule_pattern(r, "Read")) is not None]
BASH_RULES = [p for r in _ALL_DENY_RULES if (p := _rule_pattern(r, "Bash")) is not None]


def _edit_guard_module():
    # A fresh module name per call would leak into sys.modules repeatedly;
    # one fixed name is fine since load_script_module re-execs into it.
    return load_script_module("raven_pre_edit_guard_permissions_test", EDIT_GUARD_PATH)


def _read_rule_matches(pattern: str, path: str) -> bool:
    """Whether a `Read(pattern)` deny rule (gitignore-style) covers `path`.

    Implements exactly the two documented deny-rule behaviors these rules
    rely on (code.claude.com/docs/en/permissions.md, fetched 2026-08-13):
    a bare pattern with no "/" matches at any depth (any path segment, so it
    catches both a same-named file and a same-named directory), and a
    `dir/**` pattern matches a directory named `dir` at any depth, covering
    everything nested under it. This is not a general glob engine -- it is
    only as capable as the specific rule shapes shipped in settings.json.
    """
    if pattern.endswith("/**"):
        dirname = pattern[: -len("/**")]
        segments = path.split("/")
        return any(segment == dirname for segment in segments[:-1])
    if "/" in pattern:
        raise ValueError(f"matcher does not support an anchored pattern: {pattern!r}")
    return any(fnmatch.fnmatchcase(segment, pattern) for segment in path.split("/"))


def _bash_rule_matches(pattern: str, command: str) -> bool:
    """Whether a `Bash(pattern)` deny rule covers `command`.

    Implements the documented Bash wildcard semantics (same doc as above): a
    pattern with no `*` must match the command exactly; each `*` spans any
    number of characters, including across argument/space boundaries. A
    trailing " *" is naturally word-boundary-safe here because the literal
    space immediately before it must be present in `command` too -- e.g.
    "ls *" cannot match "lsof" because "lsof" has no space after "ls".
    Compound-command splitting, wrapper-stripping, and env-assignment
    handling are real parts of Claude Code's engine that this intentionally
    does not model; every case below is a single simple command, which is
    all these tests need.
    """
    regex = re.escape(pattern).replace(r"\*", ".*")
    return re.fullmatch(regex, command, re.DOTALL) is not None


# --- Part 1: edit-guard BLOCKED paths vs Read(...) deny rules --------------
#
# Representative normalized paths each BLOCKED regex in the edit guard
# denies. `test_samples_actually_match_the_real_regex` proves each sample
# really is a member of the regex's match space (using the hook's own real
# pattern, not a restatement of it); `test_every_sample_is_covered_by_a_
# native_read_deny_rule` then checks settings.json's real Read(...) rules
# against those same samples.
BLOCKED_PATTERN_SAMPLES: dict[str, list[str]] = {
    r"\.pem$": ["server.pem", "certs/server.pem"],
    r"\.key$": ["id.key", "certs/id.key"],
    r"\.p12$": ["bundle.p12", "certs/bundle.p12"],
    r"\.pfx$": ["bundle.pfx", "certs/bundle.pfx"],
    r"\.crt$": ["server.crt", "certs/server.crt"],
    r"\.cer$": ["server.cer", "certs/server.cer"],
    r"(^|/)\.env(\.[^/]*)?$": [
        ".env",
        "config/.env",
        # The spellings that actually hold values: the committed template is
        # `.env.example` and the secrets live beside it (issue #213).
        ".env.local",
        ".env.production",
        ".env.development",
        "packages/api/.env.local",
    ],
    r"(^|/)\.envrc$": [".envrc", "config/.envrc"],
    r"(^|/)secrets?(\.|/|$)": [
        "secret",
        "secrets",
        "secret.yaml",
        "secrets.json",
        "secrets/prod.json",
        "a/secret/prod.json",
    ],
    r"(^|/)credentials?(\.|/|$)": [
        "credential",
        "credentials",
        "credential.yml",
        "credentials.yml",
        "credentials/prod.json",
        "a/credential/prod.json",
    ],
}


class EditGuardBlockedPathsHaveNativeCoverageTests(unittest.TestCase):
    def test_every_blocked_pattern_has_a_documented_sample(self):
        """Fails loudly if the hook grows a BLOCKED entry with no sample
        here, instead of the coverage check below silently iterating zero
        paths for it and passing vacuously.
        """
        hook = _edit_guard_module()
        for pattern in hook.BLOCKED:
            with self.subTest(pattern=pattern):
                self.assertIn(
                    pattern,
                    BLOCKED_PATTERN_SAMPLES,
                    "add a sample path for this new BLOCKED pattern",
                )

    def test_no_stale_sample_entries_remain(self):
        """The reverse direction: a sample dict key for a pattern the hook
        no longer ships would otherwise validate nothing forever.
        """
        hook = _edit_guard_module()
        for pattern in BLOCKED_PATTERN_SAMPLES:
            with self.subTest(pattern=pattern):
                self.assertIn(pattern, hook.BLOCKED)

    def test_samples_actually_match_the_real_regex(self):
        for pattern, samples in BLOCKED_PATTERN_SAMPLES.items():
            for sample in samples:
                with self.subTest(pattern=pattern, sample=sample):
                    self.assertTrue(re.search(pattern, sample, re.IGNORECASE))

    def test_every_sample_is_covered_by_a_native_read_deny_rule(self):
        for pattern, samples in BLOCKED_PATTERN_SAMPLES.items():
            for sample in samples:
                with self.subTest(pattern=pattern, sample=sample):
                    covered = any(_read_rule_matches(p, sample) for p in READ_RULES)
                    self.assertTrue(
                        covered,
                        f"no Read(...) deny rule in settings.json covers {sample!r} "
                        f"(from edit-guard BLOCKED pattern {pattern!r})",
                    )


# --- Part 2: caution-tier paths must NEVER appear in permissions.deny ------
#
# The caution list is warn-only in the hook -- a deny is not a warning.
CAUTION_PATTERN_SAMPLES: dict[str, list[str]] = {
    r"/migrations/": ["db/migrations/0001_init.sql"],
    r"/generated/": ["src/generated/schema.ts"],
    r"package-lock\.json$": ["package-lock.json"],
    r"Cargo\.lock$": ["Cargo.lock"],
    r"pnpm-lock\.yaml$": ["pnpm-lock.yaml"],
}


class NoCautionTierPatternInDenyTests(unittest.TestCase):
    def test_every_caution_pattern_has_a_documented_sample(self):
        hook = _edit_guard_module()
        for pattern in hook.CAUTION:
            with self.subTest(pattern=pattern):
                self.assertIn(pattern, CAUTION_PATTERN_SAMPLES)

    def test_no_stale_sample_entries_remain(self):
        hook = _edit_guard_module()
        for pattern in CAUTION_PATTERN_SAMPLES:
            with self.subTest(pattern=pattern):
                self.assertIn(pattern, hook.CAUTION)

    def test_samples_actually_match_the_real_regex(self):
        for pattern, samples in CAUTION_PATTERN_SAMPLES.items():
            for sample in samples:
                with self.subTest(pattern=pattern, sample=sample):
                    self.assertTrue(re.search(pattern, sample, re.IGNORECASE))

    def test_no_caution_sample_is_covered_by_a_native_deny_rule(self):
        for pattern, samples in CAUTION_PATTERN_SAMPLES.items():
            for sample in samples:
                with self.subTest(pattern=pattern, sample=sample):
                    covered = any(_read_rule_matches(p, sample) for p in READ_RULES)
                    self.assertFalse(
                        covered,
                        f"caution-tier path {sample!r} (pattern {pattern!r}) must NOT "
                        "appear in permissions.deny -- caution is warn-only in the "
                        "hook, a deny is not a warning",
                    )


# --- Part 3: bash-guard destructive programs vs Bash(...) deny rules -------
#
# The bash guard's blocked surface is control flow, not a data list (see
# module docstring). DENIED_BASH_COMMANDS is imported from test_agent_hooks
# rather than retyped -- it is that hook's own canonical "must deny" fixture
# for the rm-catastrophic and git-clean intents.
class RmAndGitCleanFixtureCoverageTests(unittest.TestCase):
    def test_every_denied_bash_command_fixture_entry_is_natively_covered(self):
        for command in DENIED_BASH_COMMANDS:
            with self.subTest(command=command):
                covered = any(_bash_rule_matches(p, command) for p in BASH_RULES)
                self.assertTrue(
                    covered, f"no Bash(...) deny rule in settings.json covers {command!r}"
                )


# Base-form commands for the destructive programs/intents that
# DENIED_BASH_COMMANDS does not exercise (kubectl, aws, dropdb, sudo rm, git
# reset --hard, the SQL clients). Hardcoded expected-coverage test data, per
# the module docstring -- checked against the real, parsed BASH_RULES.
BASE_FORM_CASES: list[tuple[str, str]] = [
    ("dropdb", "dropdb prod_db"),
    ("kubectl delete", "kubectl delete pod web"),
    ("aws delete*", "aws s3api delete-bucket --bucket x"),
    ("sudo rm", "sudo rm -rf /var/lib/data"),
    ("git reset --hard", "git reset --hard HEAD"),
    ("psql drop database (uppercase, hook's own test case)", 'psql -c "DROP DATABASE prod"'),
    ("psql drop database (lowercase)", 'psql -c "drop database prod"'),
    ("mysql drop database (uppercase)", 'mysql -e "DROP DATABASE prod"'),
    ("mariadb drop database (uppercase)", 'mariadb -e "DROP DATABASE prod"'),
    ("sqlite3 drop database (uppercase)", 'sqlite3 prod.db "DROP DATABASE prod"'),
    ("git clean -fdx", "git clean -fdx"),
]


class ProgramBaseFormCoverageTests(unittest.TestCase):
    def test_base_form_is_natively_covered(self):
        for label, command in BASE_FORM_CASES:
            with self.subTest(label=label, command=command):
                covered = any(_bash_rule_matches(p, command) for p in BASH_RULES)
                self.assertTrue(covered, f"{label}: no Bash(...) deny rule covers {command!r}")


# Option-bearing forms: (label, command, expected_covered). `expected_covered
# = True` means this repo shipped a mid-wildcard mitigation for that
# program's option-before-subcommand spelling and the test proves it works.
# `expected_covered = False` is a *documented* gap -- native Bash rules
# cannot express it without either combinatorial rule explosion or losing
# precision the hook has -- and is asserted so a future change cannot
# silently "fix" it by over-broadening a rule without anyone noticing. See
# raven-guardrails.md for the prose version of each gap.
OPTION_BEARING_CASES: list[tuple[str, str, bool]] = [
    # kubectl: `Bash(kubectl * delete *)` mitigates an option between the
    # program and the subcommand -- the issue's own measured example.
    ("kubectl -n default delete", "kubectl -n default delete deployment api", True),
    ("kubectl --context=prod delete", "kubectl --context=prod delete pod web", True),
    # aws: `Bash(aws * delete*)` mitigates a global flag (or an intermediate
    # service subcommand like `s3api`) before the delete-* verb.
    ("aws --profile prod delete-bucket", "aws --profile prod delete-bucket --bucket x", True),
    # sudo rm: `Bash(sudo * rm *)` mitigates an option between sudo and rm.
    ("sudo -n rm", "sudo -n rm -rf /var/lib/data", True),
    # git reset --hard: the mid-wildcard forms mitigate --hard appearing
    # after another positional (reordering), not just directly after reset.
    ("git reset HEAD --hard (reordered)", "git reset HEAD --hard", True),
    # git with a global option taking a value operand: the same mid-wildcard
    # shape already shipped for kubectl/aws/sudo, applied to git (issue #207).
    ("git -c ... reset --hard", "git -c core.pager=cat reset --hard", True),
    ("git -C ... reset --hard", "git -C /tmp reset --hard", True),
    ("git --git-dir ... clean -fdx", "git --git-dir /srv/repo/.git clean -fdx", True),
    # NOT mitigated: a destructive command reached through `ssh` has no
    # anchorable shape -- the payload is one quoted argument, and a rule
    # broad enough to see inside it (`Bash(ssh * delete *)`) would deny
    # ordinary remote work. Hook-only, by the same reasoning as the entries
    # above; the hook follows the payload, the native layer cannot.
    ("ssh -p ... kubectl delete", "ssh -p 2222 host 'kubectl delete pod web'", False),
    # NOT mitigated: rm's catastrophic-target rules are exact literal
    # spellings mirroring the hook's own DENIED_BASH_COMMANDS fixture. An
    # extra/reordered flag the hook still catches via _normalize_options --
    # e.g. an unrelated -v thrown into the cluster -- breaks the native
    # exact-string match. Hook-only; documented in raven-guardrails.md.
    ("rm -v -rf / (extra unmirrored flag)", "rm -v -rf /", False),
    # NOT mitigated: git clean's three-flag combination has 6 possible
    # cluster orderings plus split/long-option spellings; only the 4
    # spellings the hook's own test fixture asserts are natively mirrored.
    ("git clean -fxd (unmirrored ordering)", "git clean -fxd", False),
    # NOT mitigated: `git checkout -f` with no pathspec. The shipped rules are
    # the flag-carrying spellings with an operand (`Bash(git checkout -f *)`),
    # and a trailing " *" needs a real space and argument in the command. The
    # hook denies it regardless of operand, because `-f` on checkout always
    # means "discard whatever is in the worktree" (issue #210).
    ("git checkout -f (no pathspec)", "git checkout -f", False),
    # NOT mitigated: the SQL "drop database" check is a raw, case-
    # insensitive substring match with no program-position/subcommand shape
    # to anchor a Bash prefix/wildcard rule on. Only the literal upper- and
    # lower-case spellings are natively mirrored; mixed case is not.
    ("psql drop database (mixed case)", 'psql -c "Drop Database prod"', False),
]


class ProgramOptionBearingCoverageTests(unittest.TestCase):
    def test_option_bearing_form_matches_documented_expectation(self):
        for label, command, expect_covered in OPTION_BEARING_CASES:
            with self.subTest(label=label, command=command, expect_covered=expect_covered):
                covered = any(_bash_rule_matches(p, command) for p in BASH_RULES)
                if expect_covered:
                    self.assertTrue(
                        covered, f"{label}: expected native coverage for {command!r}, found none"
                    )
                else:
                    self.assertFalse(
                        covered,
                        f"{label}: expected NO native coverage for {command!r} (documented "
                        "gap), but a Bash(...) rule matched -- update the gap note if this "
                        "is now intentionally covered",
                    )


class PipeToShellIsHookOnlyTests(unittest.TestCase):
    """Piping a fetched URL into a shell has no native mirror, deliberately.

    Every other entry in this file records a gap that a glob *could* close at
    some cost in precision. This one it cannot close at any cost: the rule is a
    relationship between two command segments (something fetches, something
    else interprets stdin), and a `Bash(...)` pattern matches one subcommand at
    a time. A rule broad enough to reach it -- `Bash(curl *)`, `Bash(sh)` --
    would deny ordinary work. The hook is the only layer that can hold this
    one, which is asserted here so a future audit does not read the absence of
    a `curl` entry in settings.json as an oversight (issue #212).
    """

    def test_no_native_rule_covers_the_fetch_into_interpreter_shape(self):
        for command in PIPE_TO_SHELL_DENIED_COMMANDS:
            with self.subTest(command=command):
                covered = any(_bash_rule_matches(p, command) for p in BASH_RULES)
                self.assertFalse(
                    covered,
                    f"a Bash(...) deny rule now matches {command!r} -- if that is "
                    "intentional, check it does not also deny ordinary fetches or "
                    "ordinary shell invocations, and update this note",
                )


class NoCautionOrEditRuleAdditionsSlippedIntoDenyTests(unittest.TestCase):
    """Sanity check on the deny list's shape: only Read(...) and Bash(...)
    rules are expected. An Edit(...)/Write(...) rule would be redundant --
    a Read(...) deny already blocks Edit/Write on the same path -- and
    would signal a drift from the "rely on Read blocking Edit too" decision
    this issue made (see raven-guardrails.md).
    """

    def test_every_deny_rule_is_a_read_or_bash_rule(self):
        for rule in _ALL_DENY_RULES:
            with self.subTest(rule=rule):
                self.assertTrue(
                    rule.startswith(("Read(", "Bash(")),
                    f"unexpected rule shape in permissions.deny: {rule!r}",
                )
