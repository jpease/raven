#!/usr/bin/env python3
"""Run Raven's behavioral scenarios against a local agent CLI and record the results.

Not part of any gate. It costs real model calls, it is not deterministic, and a
single run of it proves nothing on its own -- which is exactly why it is a
command someone chooses to run rather than something `just check` does. Use the
local `claude` or `codex` CLI and whatever subscription is already logged in;
this script never handles a key.

    python scripts/eval.py --agent claude --trials 3
    python scripts/eval.py --agent codex --scenario gate-relaxation
    python scripts/eval.py --agent claude --trials 5 --out docs/evaluation/

Every scenario runs twice per trial in identical throwaway repositories: one
with Raven installed, one without. The number worth reading is the difference
between the two columns, not either column alone.

Exit codes: 0 (the run completed), 1 (nothing ran -- unknown agent, missing
CLI, or no scenario matched), 2 (a tooling problem stopped the run).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from evals.scenarios import (  # noqa: E402 -- needs the path inserts
    SCENARIOS,
    Result,
    Scenario,
    tool_calls,
)

#: How long one agent run may take before the harness gives up on it. A hung
#: run is a failed trial, never a hung harness.
TIMEOUT_SECONDS = 600

#: Written into every fixture that does not ship its own. Any real Python
#: repository ignores these; a fixture that did not handed the Raven arm
#: extra work of its own making -- the installed pre-commit hook runs ruff,
#: which leaves `.ruff_cache/` untracked, and a gate run leaves
#: `__pycache__/`, and transcripts (2026-09-02) show agents spending steps
#: on both. Identical in both arms, so it changes nothing about the comparison.
FIXTURE_GITIGNORE = ".ruff_cache/\n__pycache__/\n"


@dataclass
class TrialOutcome:
    """One scenario, one arm, one trial."""

    scenario: str
    arm: str
    trial: int
    passed: bool
    evidence: str
    error: str | None = None
    #: Every token the model processed this trial (fresh + cached input, plus
    #: output), summed across turns. None means the harness found no usage
    #: event to read, never that zero tokens were used.
    total_tokens: int | None = None
    output_tokens: int | None = None
    #: Only `claude` reports this; always None for `codex`.
    cost_usd: float | None = None
    #: Tool calls the agent made, on either CLI. Read beside `total_tokens`:
    #: it says whether a costlier arm took more steps or carried more context
    #: per step. None means the transcript held no events to count.
    tool_calls: int | None = None


# ---------------------------------------------------------------------------
# Agents
# ---------------------------------------------------------------------------


def _claude_command(task: str) -> list[str]:
    return [
        "claude",
        "-p",
        task,
        "--output-format",
        "stream-json",
        "--verbose",
        "--permission-mode",
        "bypassPermissions",
        # Without this, the operator's own ~/.claude config -- personal plugins,
        # global MCP servers -- leaks into every trial, in both arms alike. That
        # inflates every number here with content that has nothing to do with
        # Raven and won't reproduce on a different machine or in CI.
        "--setting-sources",
        "project",
    ]


def _codex_command(task: str) -> list[str]:
    return [
        "codex",
        "exec",
        "--dangerously-bypass-approvals-and-sandbox",
        "--skip-git-repo-check",
        "--json",
        # Codex runs a project's hooks only after each one has been reviewed
        # and trusted by hash in `/hooks`. Nothing can do that review in a
        # throwaway fixture, so without this the Raven arm's `.codex/hooks.json`
        # is parsed and then skipped -- confirmed live, 2026-09-02, with a
        # SessionStart hook that touches a file and never did. The operator's
        # own config is kept out by `codex_home` below, not by
        # `--ignore-user-config`, which did not stop `~/.codex/rules/` from
        # loading either.
        "--dangerously-bypass-hook-trust",
        task,
    ]


AGENTS = {"claude": _claude_command, "codex": _codex_command}


def codex_home(scratch: Path, root: Path) -> Path:
    """Write a throwaway `$CODEX_HOME` that trusts ``root`` and nothing else.

    Codex loads a project's `.codex/` layer -- config, hooks, rules, agents --
    only when the project is trusted, and the only thing that grants trust is
    a `[projects."<path>"] trust_level = "trusted"` table in the config file
    `$CODEX_HOME` points at. A `-c projects.<path>.trust_level=trusted`
    override on the command line does not (tried live, 2026-09-02: the hook
    stayed silent), and a fresh temporary directory is trusted by nobody, so
    every Codex trial before this ran the Raven arm with its adapter files
    inert and reported a number for guidance the agent never received.

    A private home also replaces `--ignore-user-config`: the operator's
    config, rules, and skills are absent by construction instead of by flag.
    Auth is the one thing carried over -- as a symlink to the real
    `auth.json`, never a copy, so no credential is written anywhere new and
    the link dies with the fixture. Skipped when there is no `auth.json`,
    which is the API-key case, where the environment carries the credential.
    """
    home = scratch / "codex-home"
    home.mkdir(parents=True, exist_ok=True)
    real = root.resolve()
    (home / "config.toml").write_text(
        f"[projects.'{real}']\ntrust_level = 'trusted'\n", encoding="utf-8"
    )
    source_home = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
    auth = source_home / "auth.json"
    if auth.is_file():
        (home / "auth.json").symlink_to(auth)
    return home


def _agent_env(agent: str, scratch: Path, root: Path) -> dict[str, str] | None:
    """Environment for one agent run, or None to inherit the harness's own."""
    if agent != "codex":
        return None
    env = dict(os.environ)
    env["CODEX_HOME"] = str(codex_home(scratch, root))
    return env


def _claude_usage(transcript: str) -> tuple[int, int, float | None] | None:
    """(total_tokens, output_tokens, cost_usd) from the final `result` event.

    `total_tokens` sums every token the model processed -- fresh input, cache
    writes, cache reads, and output -- because a cache hit is cheaper but
    still consumed context; the token-discipline question this exists to
    answer is about total footprint, not just what was billed. None means no
    `result` event was seen, never that zero tokens were used.
    """
    for line in transcript.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if event.get("type") != "result":
            continue
        usage = event.get("usage") or {}
        total = (
            usage.get("input_tokens", 0)
            + usage.get("cache_creation_input_tokens", 0)
            + usage.get("cache_read_input_tokens", 0)
            + usage.get("output_tokens", 0)
        )
        return total, usage.get("output_tokens", 0), event.get("total_cost_usd")
    return None


def _codex_usage(transcript: str) -> tuple[int, int, float | None] | None:
    """(total_tokens, output_tokens, cost_usd), summed across `turn.completed` events.

    A single `exec` call can run several turns; each carries its own usage, so
    this totals them rather than keeping only the last.

    Codex follows the OpenAI usage shape, where `cached_input_tokens` is a
    subset of `input_tokens`, not an addition to it -- unlike claude, whose
    `cache_read_input_tokens` sits beside an uncached `input_tokens`. The
    tell is a first-turn session reporting 19,701 input and 11,136 cached
    (observed 2026-09-02): no fresh session carries a 30K prompt when its
    instructions total 20K. Adding the cached figure, as this did until then,
    double-counted every cache hit, so every Codex total recorded before that
    date is inflated by however much of its context was cached at the time.
    `cache_write_input_tokens` is kept: it is zero on OpenAI models, and on
    a provider that reports it the write is not part of `input_tokens`.
    """
    total = 0
    output = 0
    seen = False
    for line in transcript.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if event.get("type") != "turn.completed":
            continue
        usage = event.get("usage") or {}
        total += (
            usage.get("input_tokens", 0)
            + usage.get("cache_write_input_tokens", 0)
            + usage.get("output_tokens", 0)
        )
        output += usage.get("output_tokens", 0)
        seen = True
    return (total, output, None) if seen else None


USAGE_EXTRACTORS = {"claude": _claude_usage, "codex": _codex_usage}


# ---------------------------------------------------------------------------
# Fixture construction
# ---------------------------------------------------------------------------


def _clean_git_env() -> dict:
    """The current environment with every ``GIT_*`` variable removed.

    A fixture is a throwaway repository built with `git init`, and an inherited
    `GIT_DIR`, `GIT_WORK_TREE`, or `GIT_INDEX_FILE` silently redirects those
    commands at whatever repository set them -- the fixture then looks
    committed when nothing was, or worse, the caller's repository takes the
    commit. Nothing here needs anything from git's environment, so all of it
    goes.
    """
    return {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}


def _shell(cwd: Path, command: str) -> None:
    """Run one fixture-setup command.

    `shell=True` is deliberate and safe here: every command it ever receives is
    a literal authored in `evals/scenarios.py`, never anything the agent, the
    environment, or a caller supplies. Scenario setup wants shell semantics
    (`&&`, `>>`), so the alternative would be re-implementing them.
    """
    subprocess.run(
        command,
        cwd=str(cwd),
        shell=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
        env=_clean_git_env(),
    )


def build_fixture(scenario: Scenario, root: Path, *, with_raven: bool) -> None:
    """Write one arm's throwaway repository.

    Both arms get the identical fixture and the identical git history. The only
    difference is the Raven install, which is the whole point: anything else
    that differed would be a confound the results could not separate out.
    """
    root.mkdir(parents=True, exist_ok=True)
    _shell(root, "git init -q")
    _shell(root, "git config user.email eval@example.invalid")
    _shell(root, "git config user.name 'Raven Eval'")
    # `git commit` forks `gc --auto`, which keeps writing into
    # `.git/objects/pack` after the commit returns. The fixture is deleted the
    # moment the trial ends, so that background write races the delete and
    # surfaces as `OSError: Directory not empty: 'pack'` -- a traceback from a
    # trial that otherwise went fine. A throwaway repository has nothing worth
    # packing.
    _shell(root, "git config gc.auto 0")
    _shell(root, "git config maintenance.auto false")
    for relative, content in scenario.files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    if ".gitignore" not in scenario.files:
        (root / ".gitignore").write_text(FIXTURE_GITIGNORE, encoding="utf-8")

    if with_raven:
        subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" / "raven.py"), "install", scenario.template],
            cwd=str(root),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            env=_clean_git_env(),
        )

    # Setup runs last so a scenario that wants an initial commit gets one that
    # includes whatever its arm installed -- otherwise the Raven arm would
    # start with a dirty tree and the control arm would not.
    for command in scenario.setup:
        _shell(root, command)


# ---------------------------------------------------------------------------
# Running
# ---------------------------------------------------------------------------


def save_transcript(directory: Path, scenario: str, arm: str, trial: int, transcript: str) -> None:
    """Keep one trial's raw JSON transcript, named so trials never collide.

    The token and call columns say *that* one arm took more steps; only the
    transcript says *which* steps, and the fixture is deleted the moment the
    trial ends. Best effort: a transcript that cannot be written is a lost
    diagnostic, not a failed trial.
    """
    try:
        directory.mkdir(parents=True, exist_ok=True)
        (directory / f"{scenario}-{arm}-{trial}.jsonl").write_text(transcript, encoding="utf-8")
    except OSError as exc:
        print(f"warning: could not save transcript: {exc}", file=sys.stderr)


def run_one(
    scenario: Scenario,
    agent: str,
    *,
    with_raven: bool,
    trial: int,
    transcripts: Path | None = None,
) -> TrialOutcome:
    """Build a fixture, run the agent in it once, and grade what it left behind."""
    arm = "raven" if with_raven else "control"
    with tempfile.TemporaryDirectory(prefix=f"raven-eval-{scenario.name}-") as tmp:
        root = Path(tmp) / "repo"
        try:
            build_fixture(scenario, root, with_raven=with_raven)
        except OSError as exc:
            return TrialOutcome(scenario.name, arm, trial, False, "fixture failed", str(exc))

        try:
            completed = subprocess.run(
                AGENTS[agent](scenario.task),
                cwd=str(root),
                capture_output=True,
                text=True,
                timeout=TIMEOUT_SECONDS,
                check=False,
                env=_agent_env(agent, Path(tmp), root),
            )
            transcript = completed.stdout
        except subprocess.TimeoutExpired:
            return TrialOutcome(
                scenario.name, arm, trial, False, "agent timed out", f"> {TIMEOUT_SECONDS}s"
            )
        except OSError as exc:
            return TrialOutcome(scenario.name, arm, trial, False, "agent failed to start", str(exc))

        if transcripts is not None:
            save_transcript(transcripts, scenario.name, arm, trial, transcript)

        try:
            result: Result = scenario.verdict(root, transcript)
        except Exception as exc:  # noqa: BLE001 -- a broken verdict must not end the run
            return TrialOutcome(scenario.name, arm, trial, False, "verdict raised", repr(exc))

        usage = USAGE_EXTRACTORS.get(agent, lambda _t: None)(transcript)
        total_tokens, output_tokens, cost_usd = usage if usage else (None, None, None)
        return TrialOutcome(
            scenario.name,
            arm,
            trial,
            result.passed,
            result.evidence,
            total_tokens=total_tokens,
            output_tokens=output_tokens,
            cost_usd=cost_usd,
            tool_calls=tool_calls(transcript),
        )


def run(
    scenarios: list[Scenario], agent: str, trials: int, transcripts: Path | None = None
) -> list[TrialOutcome]:
    """Every scenario, both arms, ``trials`` times, reporting progress as it goes."""
    outcomes: list[TrialOutcome] = []
    for scenario in scenarios:
        for trial in range(1, trials + 1):
            for with_raven in (False, True):
                outcome = run_one(
                    scenario, agent, with_raven=with_raven, trial=trial, transcripts=transcripts
                )
                mark = "pass" if outcome.passed else "FAIL"
                tokens = (
                    f"  {outcome.total_tokens:,}tok" if outcome.total_tokens is not None else ""
                )
                calls = f"  {outcome.tool_calls}calls" if outcome.tool_calls is not None else ""
                print(
                    f"  {scenario.name:22} {outcome.arm:8} trial {trial}  {mark}{tokens}{calls}"
                    f"  {outcome.evidence}",
                    flush=True,
                )
                outcomes.append(outcome)
    return outcomes


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def _rate(outcomes: list[TrialOutcome], scenario: str, arm: str) -> tuple[int, int]:
    subset = [o for o in outcomes if o.scenario == scenario and o.arm == arm]
    return sum(1 for o in subset if o.passed), len(subset)


def _avg_tokens(outcomes: list[TrialOutcome], scenario: str, arm: str) -> int | None:
    """Mean `total_tokens` for trials that reported it. None if none did."""
    values = [
        o.total_tokens
        for o in outcomes
        if o.scenario == scenario and o.arm == arm and o.total_tokens is not None
    ]
    return round(sum(values) / len(values)) if values else None


def _avg_calls(outcomes: list[TrialOutcome], scenario: str, arm: str) -> float | None:
    """Mean `tool_calls` for trials that reported it. None if none did."""
    values = [
        o.tool_calls
        for o in outcomes
        if o.scenario == scenario and o.arm == arm and o.tool_calls is not None
    ]
    return round(sum(values) / len(values), 1) if values else None


def render_markdown(outcomes: list[TrialOutcome], agent: str, trials: int, stamp: str) -> str:
    """The results table, written so a reader can tell a real difference from noise."""
    lines = [
        f"# Raven behavioral evaluation -- {agent}",
        "",
        f"Run {stamp} against the local `{agent}` CLI, {trials} trial(s) per arm.",
        "",
        "Each scenario runs twice in identical throwaway repositories: `control`",
        "has no Raven installed, `raven` does. Only the difference between the two",
        "columns says anything about the guidance.",
        "",
        "| Scenario | Measures | control | raven |",
        "|---|---|---|---|",
    ]
    names = list(dict.fromkeys(o.scenario for o in outcomes))
    by_name = {s.name: s for s in SCENARIOS}
    for name in names:
        control_pass, control_n = _rate(outcomes, name, "control")
        raven_pass, raven_n = _rate(outcomes, name, "raven")
        measures = by_name[name].measures if name in by_name else ""
        lines.append(
            f"| `{name}` | {measures} | {control_pass}/{control_n} | {raven_pass}/{raven_n} |"
        )

    if any(o.total_tokens is not None for o in outcomes):
        lines += [
            "",
            "## Token usage",
            "",
            "Mean total tokens per trial: every token the model processed, cached",
            "or not, summed across every turn (`docs/evaluation.md` says how each",
            "CLI's cache figures are read). This is a footprint number, not a",
            "controlled efficiency comparison -- the raven arm's context differs",
            "from control's by construction, so it says how much each arm cost for",
            "this task, not how efficient either one is per unit of work.",
            "",
            "Tool calls are the number of steps the agent took. Read the two",
            "columns together: more tokens over the same number of calls means",
            "each step carried more context; more tokens over more calls means",
            "the guidance changed what the agent did. `fixed-cost` makes no",
            "calls by design, so its token count is what one session costs",
            "before any work starts.",
            "",
            "| Scenario | control avg tokens | raven avg tokens | control avg calls | raven avg calls |",
            "|---|---|---|---|---|",
        ]
        for name in names:
            control_avg = _avg_tokens(outcomes, name, "control")
            raven_avg = _avg_tokens(outcomes, name, "raven")
            control_calls = _avg_calls(outcomes, name, "control")
            raven_calls = _avg_calls(outcomes, name, "raven")
            control_cell = f"{control_avg:,}" if control_avg is not None else "n/a"
            raven_cell = f"{raven_avg:,}" if raven_avg is not None else "n/a"
            control_calls_cell = f"{control_calls}" if control_calls is not None else "n/a"
            raven_calls_cell = f"{raven_calls}" if raven_calls is not None else "n/a"
            lines.append(
                f"| `{name}` | {control_cell} | {raven_cell} "
                f"| {control_calls_cell} | {raven_calls_cell} |"
            )

    lines += [
        "",
        "## Evidence",
        "",
        "What each run actually left behind, which is what the verdicts read.",
        "",
    ]
    for name in names:
        lines.append(f"### `{name}`")
        lines.append("")
        for outcome in [o for o in outcomes if o.scenario == name]:
            mark = "pass" if outcome.passed else "**FAIL**"
            suffix = f" ({outcome.error})" if outcome.error else ""
            tokens = (
                f", {outcome.total_tokens:,} tokens" if outcome.total_tokens is not None else ""
            )
            calls = f", {outcome.tool_calls} tool calls" if outcome.tool_calls is not None else ""
            lines.append(
                f"- {outcome.arm} trial {outcome.trial}: {mark} -- "
                f"{outcome.evidence}{suffix}{tokens}{calls}"
            )
        lines.append("")
    lines += [
        "## Reading this honestly",
        "",
        f"{trials} trial(s) per arm is a sample, not a measurement. A one-run",
        "difference is an anecdote; a scenario both arms pass measures nothing",
        "about Raven and should be replaced with a harder one. Four scenarios",
        "(`destructive-command`, `narrowest-test-first`, `fixed-cost`,",
        "`bounded-read`) read the transcript rather than the tree, so a format change shows",
        "up as a failure in both arms rather than a silent pass. Token counts include",
        "cache reads, which fall for reasons that have nothing to do with the",
        "guidance -- a warm cache from a prior trial in the same process, or a",
        "provider-side change -- so a token difference is weaker evidence than",
        "a pass/fail difference and needs more trials to trust.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    """Parse argv, run the selected scenarios, and write the results."""
    parser = argparse.ArgumentParser(
        description="Run Raven's behavioral scenarios against a local agent CLI.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--agent", choices=sorted(AGENTS), required=True)
    parser.add_argument("--trials", type=int, default=1, help="runs per arm (default 1)")
    parser.add_argument("--scenario", action="append", help="run only these (repeatable)")
    parser.add_argument("--out", help="directory to write the results file into")
    parser.add_argument("--json", action="store_true", help="also print raw outcomes as JSON")
    parser.add_argument(
        "--transcripts",
        help="directory to keep each trial's raw JSON transcript in, for reading the steps",
    )
    parser.add_argument(
        "--stamp",
        default="an unrecorded date",
        help="date string for the report header; pass one for a reproducible file",
    )
    args = parser.parse_args()

    if shutil.which(args.agent) is None:
        print(f"error: `{args.agent}` is not on PATH.", file=sys.stderr)
        return 1

    scenarios = list(SCENARIOS)
    if args.scenario:
        wanted = set(args.scenario)
        scenarios = [s for s in scenarios if s.name in wanted]
        unknown = wanted - {s.name for s in SCENARIOS}
        if unknown:
            print(f"error: unknown scenario(s): {', '.join(sorted(unknown))}", file=sys.stderr)
            return 1
    if not scenarios:
        print("error: no scenarios selected.", file=sys.stderr)
        return 1
    if args.trials < 1:
        print("error: --trials must be at least 1.", file=sys.stderr)
        return 1

    print(f"raven eval: {args.agent}, {len(scenarios)} scenario(s), {args.trials} trial(s) per arm")
    transcripts = Path(args.transcripts) if args.transcripts else None
    outcomes = run(scenarios, args.agent, args.trials, transcripts)

    report = render_markdown(outcomes, args.agent, args.trials, args.stamp)
    if args.out:
        out_dir = Path(args.out)
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
            path = out_dir / f"results-{args.agent}.md"
            path.write_text(report, encoding="utf-8")
        except OSError as exc:
            print(f"error: could not write results: {exc}", file=sys.stderr)
            return 2
        print(f"\nWrote {path}")
    else:
        print()
        print(report)

    if args.json:
        print(json.dumps([o.__dict__ for o in outcomes], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
