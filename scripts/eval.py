#!/usr/bin/env python3
"""Run Raven's behavioral scenarios against a local agent CLI and record the results.

Not part of any gate. It costs real model calls, it is not deterministic, and a
single run of it proves nothing on its own -- which is exactly why it is a
command someone chooses to run rather than something `just check` does. Use the
local `claude`, `codex`, or `gemini` CLI and whatever subscription is already
logged in; this script never handles a key.

    python scripts/eval.py --agent claude --trials 3
    python scripts/eval.py --agent codex --scenario gate-relaxation
    python scripts/eval.py --agent gemini --scenario fixed-cost
    python scripts/eval.py --agent claude --trials 15 --out docs/evaluation/
    python scripts/eval.py --agent claude --regression

Every scenario runs twice per trial in identical throwaway repositories: one
with Raven installed, one without. The number worth reading is the difference
between the two columns, not either column alone.

Exit codes: 0 (the run completed), 1 (nothing ran -- unknown agent, missing
CLI, no scenario matched, or `--out` with fewer than `MIN_PUBLISHED_TRIALS`
trials), 2 (a tooling problem stopped the run).
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass, replace
from itertools import islice
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from raven_lib.gemini_trust import (  # noqa: E402 -- needs the path inserts
    strip_json_comments,
)

from evals.scenarios import (  # noqa: E402 -- needs the path inserts
    SCENARIOS,
    Result,
    Scenario,
    tool_calls,
)

#: How long one agent run may take before the harness gives up on it. A hung
#: run is a failed trial, never a hung harness.
TIMEOUT_SECONDS = 600

#: Fewest trials per arm a run written with `--out` may use. `--out` writes the
#: committed results; below this a result is an anecdote, so it stays in
#: `evals/runs/`. 15 is the n at which a one-sided Fisher exact test at
#: alpha 0.05 detects a 25%-to-75% pass-rate gap with power 0.80; the
#: calculation is in `docs/evaluation/scenario-separation.md`.
MIN_PUBLISHED_TRIALS = 15

#: Most agent sessions `--jobs` may run at once. The owner approved 2: every
#: session draws on the same subscription's rate limits, and more parallel
#: sessions reach them sooner. Token counts are per session, so parallelism
#: leaves them unchanged.
MAX_JOBS = 2

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
    #: Claude reports this; Codex and Gemini do not.
    cost_usd: float | None = None
    #: Tool calls the agent made, on any supported CLI. Read beside `total_tokens`:
    #: it says whether a costlier arm took more steps or carried more context
    #: per step. None means the transcript held no events to count.
    tool_calls: int | None = None
    #: From the transcript where the CLI reports them (Claude's `system/init`).
    cli_version: str | None = None
    model: str | None = None


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


def _gemini_command(task: str) -> list[str]:
    return [
        "gemini",
        "-p",
        task,
        "--output-format",
        "stream-json",
        "--approval-mode=yolo",
    ]


AGENTS = {
    "claude": _claude_command,
    "codex": _codex_command,
    "gemini": _gemini_command,
}


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


def gemini_trust_store(scratch: Path, root: Path) -> Path:
    """Write a temporary Gemini trust store that trusts only ``root``."""
    store = scratch / "gemini-trusted-folders.json"
    store.write_text(
        json.dumps({str(root.resolve()): "TRUST_FOLDER"}),
        encoding="utf-8",
    )
    return store


def gemini_home(scratch: Path) -> Path:
    """Write a throwaway Gemini home while reusing only existing CLI auth.

    Gemini records accepted project hooks in ``trusted_hooks.json`` under its
    global state directory. Isolating ``GEMINI_CLI_HOME`` keeps an eval from
    mutating that real user state. OAuth files stay in place and are linked,
    while only authentication fields are copied out of ``settings.json``;
    unrelated user settings must not leak into a trial.
    """
    home = scratch / "gemini-home"
    state = home / ".gemini"
    state.mkdir(parents=True, exist_ok=True)
    source_home = Path(os.environ.get("GEMINI_CLI_HOME") or Path.home())
    source_state = source_home / ".gemini"
    for filename in ("oauth_creds.json", "google_accounts.json"):
        source = source_state / filename
        if source.is_file():
            (state / filename).symlink_to(source)

    settings_path = source_state / "settings.json"
    try:
        settings = json.loads(strip_json_comments(settings_path.read_text(encoding="utf-8")))
        auth = settings["security"]["auth"]
        if not isinstance(auth, dict):
            raise TypeError
        sanitized_auth = {key: auth[key] for key in ("selectedType", "useExternal") if key in auth}
    except (FileNotFoundError, KeyError, TypeError, ValueError):
        pass
    else:
        if sanitized_auth:
            (state / "settings.json").write_text(
                json.dumps({"security": {"auth": sanitized_auth}}),
                encoding="utf-8",
            )
    return home


def _agent_env(agent: str, scratch: Path, root: Path) -> dict[str, str]:
    """Environment for one agent run: the harness's own plus per-agent isolation."""
    if agent == "codex":
        env = dict(os.environ)
        env["CODEX_HOME"] = str(codex_home(scratch, root))
        return env
    if agent == "gemini":
        env = dict(os.environ)
        env.pop("GEMINI_RESTRICTED_MODE", None)
        env.pop("GEMINI_CLI_TRUST_WORKSPACE", None)
        env["GEMINI_CLI_HOME"] = str(gemini_home(scratch))
        env["GEMINI_CLI_TRUSTED_FOLDERS_PATH"] = str(gemini_trust_store(scratch, root))
        return env
    # `--setting-sources project` keeps the operator's settings out, but not the
    # claude.ai account connectors: they attach to whichever arm configures any
    # MCP server (the Raven arm), so they would count against Raven.
    env = dict(os.environ)
    env["ENABLE_CLAUDEAI_MCP_SERVERS"] = "false"
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


def _gemini_usage(transcript: str) -> tuple[int, int, float | None] | None:
    """(total_tokens, output_tokens, cost_usd) from the final `result` event."""
    for line in transcript.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict) or event.get("type") != "result":
            continue
        stats = event.get("stats")
        if not isinstance(stats, dict):
            stats = {}
        return stats.get("total_tokens", 0), stats.get("output_tokens", 0), None
    return None


USAGE_EXTRACTORS = {
    "claude": _claude_usage,
    "codex": _codex_usage,
    "gemini": _gemini_usage,
}


def _agent_error(agent: str, transcript: str) -> str | None:
    """The CLI's own error when the run failed before the agent could act, else None.

    A usage limit, an auth failure, or an API outage ends the run with no work
    done, and grading what it left behind would score the service as the agent.
    Codex reports this as a `turn.failed` (or top-level `error`) event; Claude
    as a `result` event with `is_error` set. Gemini's form is unverified, so it
    returns None and its runs are graded as before.
    """
    if agent not in ("claude", "codex"):
        return None
    for line in transcript.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict):
            continue
        kind = event.get("type")
        if agent == "codex" and kind == "turn.failed":
            error = event.get("error")
            return str(error.get("message") if isinstance(error, dict) else error)
        if agent == "codex" and kind == "error":
            return str(event.get("message"))
        if agent == "claude" and kind == "result" and event.get("is_error"):
            return str(event.get("result") or event.get("subtype") or "error result")
    return None


AGENT_ERROR = "agent error"


def transcript_meta(transcript: str) -> tuple[str | None, str | None]:
    """(CLI version, model) from Claude's `system/init` event; None where a CLI names neither."""
    for line in transcript.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if (
            isinstance(event, dict)
            and event.get("type") == "system"
            and event.get("subtype") == "init"
        ):
            return event.get("claude_code_version"), event.get("model")
    return None, None


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


def build_fixture(
    scenario: Scenario, root: Path, *, with_raven: bool, raven_config: Path | None = None
) -> None:
    """Write one arm's throwaway repository.

    Both arms get the identical fixture and the identical git history. The only
    difference is the Raven install, plus a scenario's `control_files` /
    `raven_files`, which hold the same text at the path each arm would look:
    anything else that differed would be a confound the results could not
    separate out.

    `raven_config` is seeded as the Raven arm's `.raven/config.toml` before the
    install, which honors an existing config; the control arm ignores it. A
    failed install raises `subprocess.CalledProcessError`, since a trial run
    on it would silently be a second control arm.
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
        _write_fixture_file(root, relative, content)
    if ".gitignore" not in scenario.files:
        (root / ".gitignore").write_text(FIXTURE_GITIGNORE, encoding="utf-8")

    if with_raven:
        if raven_config is not None:
            (root / ".raven").mkdir(exist_ok=True)
            shutil.copyfile(raven_config, root / ".raven" / "config.toml")
        subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" / "raven.py"), "install", scenario.template],
            cwd=str(root),
            capture_output=True,
            text=True,
            check=True,
            env=_clean_git_env(),
        )
    arm_files = scenario.raven_files if with_raven else scenario.control_files
    for relative, content in arm_files.items():
        _write_fixture_file(root, relative, content)

    # Setup runs last so a scenario that wants an initial commit gets one that
    # includes whatever its arm installed -- otherwise the Raven arm would
    # start with a dirty tree and the control arm would not.
    for command in scenario.setup:
        _shell(root, command)


def _write_fixture_file(root: Path, relative: str, content: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


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
    raven_config: Path | None = None,
) -> TrialOutcome:
    """Build a fixture, run the agent in it once, and grade what it left behind."""
    arm = "raven" if with_raven else "control"
    with tempfile.TemporaryDirectory(prefix=f"raven-eval-{scenario.name}-") as tmp:
        root = Path(tmp) / "repo"
        try:
            build_fixture(scenario, root, with_raven=with_raven, raven_config=raven_config)
        except OSError as exc:
            return TrialOutcome(scenario.name, arm, trial, False, "fixture failed", str(exc))
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or exc.stdout or "").strip() or f"exit {exc.returncode}"
            return TrialOutcome(scenario.name, arm, trial, False, "raven install failed", detail)

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

        agent_error = _agent_error(agent, transcript)
        if agent_error is not None:
            cli_version, model = transcript_meta(transcript)
            return TrialOutcome(
                scenario.name,
                arm,
                trial,
                False,
                AGENT_ERROR,
                agent_error,
                cli_version=cli_version,
                model=model,
            )

        try:
            result: Result = scenario.verdict(root, transcript)
        except Exception as exc:  # noqa: BLE001 -- a broken verdict must not end the run
            return TrialOutcome(scenario.name, arm, trial, False, "verdict raised", repr(exc))

        usage = USAGE_EXTRACTORS.get(agent, lambda _t: None)(transcript)
        total_tokens, output_tokens, cost_usd = usage if usage else (None, None, None)
        cli_version, model = transcript_meta(transcript)
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
            cli_version=cli_version,
            model=model,
        )


def _apply_overhead_ceiling(
    scenario: Scenario, agent: str, control: TrialOutcome, raven: TrialOutcome
) -> TrialOutcome:
    """Fail ``raven`` when it used more tokens over ``control`` than the agent's ceiling."""
    ceiling = scenario.raven_overhead_ceilings.get(agent)
    if ceiling is None or not raven.passed:
        return raven
    if control.total_tokens is None or raven.total_tokens is None:
        evidence = f"no token usage reported, so the {ceiling:,} overhead ceiling went unchecked"
        return replace(raven, passed=False, evidence=evidence)
    overhead = raven.total_tokens - control.total_tokens
    if overhead > ceiling:
        evidence = f"{overhead:,} tokens over control is over the raven ceiling of {ceiling:,}"
        return replace(raven, passed=False, evidence=evidence)
    evidence = f"{raven.evidence}; {overhead:,} tokens over control, ceiling {ceiling:,}"
    return replace(raven, evidence=evidence)


def run(
    scenarios: list[Scenario],
    agent: str,
    trials: int,
    transcripts: Path | None = None,
    raven_config: Path | None = None,
    jobs: int = 1,
) -> list[TrialOutcome]:
    """Every scenario, both arms, ``trials`` times, reporting progress as it goes.

    Each (scenario, trial, arm) unit is one agent session in its own temp
    fixture, run on a pool of ``jobs`` workers. The returned list is in
    scenario, trial, arm order whatever order the units finished in, and a
    raven unit is reported once its control has finished, so the overhead
    ceiling can compare the two.

    The first agent error stops scheduling: a usage limit or outage fails every
    later unit the same way, and each one still costs a session to find out.
    Units already in flight finish; the rest never start.
    """
    units = [
        (scenario, trial, with_raven)
        for scenario in scenarios
        for trial in range(1, trials + 1)
        for with_raven in (False, True)
    ]

    def work(index: int) -> TrialOutcome:
        scenario, trial, with_raven = units[index]
        return run_one(
            scenario,
            agent,
            with_raven=with_raven,
            trial=trial,
            transcripts=transcripts,
            raven_config=raven_config if with_raven else None,
        )

    done: dict[int, TrialOutcome] = {}
    held: dict[int, TrialOutcome] = {}

    def finish(index: int, outcome: TrialOutcome) -> None:
        scenario, trial, with_raven = units[index]
        if with_raven:
            control = done.get(index - 1)
            if control is None:
                held[index] = outcome
                return
            outcome = _apply_overhead_ceiling(scenario, agent, control, outcome)
        done[index] = outcome
        _report(scenario, trial, outcome)
        if index + 1 in held:
            finish(index + 1, held.pop(index + 1))

    queue = iter(range(len(units)))
    stopped = False
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        in_flight = {pool.submit(work, index): index for index in islice(queue, jobs)}
        while in_flight:
            finished, _ = wait(in_flight, return_when=FIRST_COMPLETED)
            for future in sorted(finished, key=in_flight.__getitem__):
                outcome = future.result()
                stopped = stopped or outcome.evidence == AGENT_ERROR
                finish(in_flight.pop(future), outcome)
            if not stopped:
                for index in islice(queue, len(finished)):
                    in_flight[pool.submit(work, index)] = index
    return [done[index] for index in sorted(done)]


def _report(scenario: Scenario, trial: int, outcome: TrialOutcome) -> None:
    """Print one trial's progress line."""
    mark = "pass" if outcome.passed else "FAIL"
    tokens = f"  {outcome.total_tokens:,}tok" if outcome.total_tokens is not None else ""
    calls = f"  {outcome.tool_calls}calls" if outcome.tool_calls is not None else ""
    print(
        f"  {scenario.name:22} {outcome.arm:8} trial {trial}  {mark}{tokens}{calls}"
        f"  {outcome.evidence}{f': {outcome.error}' if outcome.error else ''}",
        flush=True,
    )


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


def render_markdown(
    outcomes: list[TrialOutcome],
    agent: str,
    trials: int,
    stamp: str,
    raven_config: Path | None = None,
) -> str:
    """The results table, written so a reader can tell a real difference from noise."""
    config = f"`{raven_config}`" if raven_config is not None else "default config"
    lines = [
        f"# Raven behavioral evaluation -- {agent}",
        "",
        f"Run {stamp} against the local `{agent}` CLI, {trials} trial(s) per arm.",
        "",
        f"Raven arm config: {config}.",
        "",
        "Each scenario runs twice in identical throwaway repositories: `control`",
        "has no Raven installed, `raven` does. Only the difference between the two",
        "columns says anything about the guidance.",
        "",
        "| Scenario | Measures | control | raven | signal |",
        "|---|---|---|---|---|",
    ]
    names = list(dict.fromkeys(o.scenario for o in outcomes))
    by_name = {s.name: s for s in SCENARIOS}
    no_signal = 0
    for name in names:
        control_pass, control_n = _rate(outcomes, name, "control")
        raven_pass, raven_n = _rate(outcomes, name, "raven")
        measures = by_name[name].measures if name in by_name else ""
        both_passed = 0 < control_n == control_pass and 0 < raven_n == raven_pass
        no_signal += both_passed
        signal = "none" if both_passed else ""
        lines.append(
            f"| `{name}` | {measures} | {control_pass}/{control_n} "
            f"| {raven_pass}/{raven_n} | {signal} |"
        )
    lines += [
        "",
        f"{no_signal} of {len(names)} scenario(s) passed in both arms on every trial, so",
        "their pass/fail cells carry no signal about the guidance (`none` in the",
        "signal column).",
    ]

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
        "about Raven and should be replaced with a harder one. Five scenarios",
        "(`destructive-command`, `narrowest-test-first`, `fixed-cost`,",
        "`bounded-read`, `precedent-near-miss`) read the transcript rather than the tree, so a format change shows",
        "up as a failure in both arms rather than a silent pass. Token counts include",
        "cache reads, which fall for reasons that have nothing to do with the",
        "guidance -- a warm cache from a prior trial in the same process, or a",
        "provider-side change -- so a token difference is weaker evidence than",
        "a pass/fail difference and needs more trials to trust.",
        "",
    ]
    return "\n".join(lines)


#: Per-trial columns of the CSV written beside every report. One row per
#: trial, so the pass counts and token means in the report can be recomputed.
CSV_COLUMNS = (
    "run_stamp",
    "agent",
    "cli_version",
    "model",
    "scenario",
    "arm",
    "trial",
    "passed",
    "verdict_reason",
    "total_tokens",
    "tool_calls",
    "raven_config",
    "jobs",
)

_HOME_PATH = re.compile(r"(?:/Users|/home)/[^/\s'\"`]+")
#: macOS's per-user temp root, where the fixtures live; its name encodes the account.
_TEMP_PATH = re.compile(r"(?:/private)?/var/folders/[^\s'\"`]*")


def scrub_paths(text: str) -> str:
    """``text`` with the operator's home directory replaced by ``~`` and temp paths by ``<tmp>``.

    Verdict evidence and agent errors quote paths; a committed CSV must not
    carry whoever ran the eval.
    """
    home = str(Path.home())
    if len(home) > 1:
        text = text.replace(home, "~")
    return _TEMP_PATH.sub("<tmp>", _HOME_PATH.sub("~", text))


def _csv_config(raven_config: Path | None) -> str:
    """The Raven arm's config as a repo-relative path, a bare file name, or `default`."""
    if raven_config is None:
        return "default"
    try:
        return raven_config.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return raven_config.name


def _cli_version(agent: str) -> str:
    """`<agent> --version`'s first line, or empty when the CLI cannot say."""
    try:
        done = subprocess.run(
            [agent, "--version"], capture_output=True, text=True, timeout=30, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    lines = done.stdout.strip().splitlines()
    return scrub_paths(lines[0].strip()) if done.returncode == 0 and lines else ""


def render_trials_csv(
    outcomes: list[TrialOutcome],
    agent: str,
    stamp: str,
    raven_config: Path | None,
    jobs: int,
    cli_version: str = "",
) -> str:
    """One CSV row per trial, in the order ``outcomes`` arrive (scenario, trial, arm).

    ``cli_version`` fills rows whose transcript named none (Codex's does not).
    """
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(CSV_COLUMNS)
    config = _csv_config(raven_config)
    for o in outcomes:
        reason = o.evidence if not o.error else f"{o.evidence}: {o.error}"
        writer.writerow(
            [
                scrub_paths(stamp),
                agent,
                o.cli_version or cli_version,
                o.model or "",
                o.scenario,
                o.arm,
                o.trial,
                "true" if o.passed else "false",
                scrub_paths(" ".join(reason.split())),
                "" if o.total_tokens is None else o.total_tokens,
                "" if o.tool_calls is None else o.tool_calls,
                config,
                jobs,
            ]
        )
    return out.getvalue()


def default_transcripts_dir(started: float) -> Path:
    """Where a run keeps its transcripts when `--transcripts` is not given.

    `$RAVEN_EVAL_DATA_DIR/evals/<YYYY-MM-DD>/<stamp>/` when the variable is set
    (the maintainer's private data directory, outside the repository),
    otherwise the gitignored `evals/transcripts/<stamp>/` in the checkout.
    """
    moment = time.localtime(started)
    stamp = time.strftime("%Y%m%d-%H%M%S", moment)
    data_dir = os.environ.get("RAVEN_EVAL_DATA_DIR")
    if data_dir:
        return Path(data_dir) / "evals" / time.strftime("%Y-%m-%d", moment) / stamp
    return REPO_ROOT / "evals" / "transcripts" / stamp


def main() -> int:
    """Parse argv, run the selected scenarios, and write the results."""
    parser = argparse.ArgumentParser(
        description="Run Raven's behavioral scenarios against a local agent CLI.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--agent", choices=sorted(AGENTS), required=True)
    parser.add_argument("--trials", type=int, default=1, help="runs per arm (default 1)")
    parser.add_argument("--scenario", action="append", help="run only these (repeatable)")
    parser.add_argument(
        "--jobs",
        type=int,
        default=1,
        help=f"agent sessions to run at once (default 1, at most {MAX_JOBS})",
    )
    parser.add_argument(
        "--regression",
        action="store_true",
        help="run the regression-only scenarios, which the default set leaves out",
    )
    parser.add_argument(
        "--out",
        help=(
            "directory for results-<agent>.md, or a .md file path, for a published run;"
            f" needs --trials >= {MIN_PUBLISHED_TRIALS}"
        ),
    )
    parser.add_argument("--json", action="store_true", help="also print raw outcomes as JSON")
    parser.add_argument(
        "--transcripts",
        help=(
            "directory to keep each trial's raw JSON transcript in (default:"
            " $RAVEN_EVAL_DATA_DIR/evals/<date>/<stamp>/ when set, else"
            " evals/transcripts/<stamp>/)"
        ),
    )
    parser.add_argument(
        "--stamp",
        default="an unrecorded date",
        help="date string for the report header; pass one for a reproducible file",
    )
    parser.add_argument(
        "--raven-config",
        help="config.toml seeded into the Raven arm before install (ablations; not with --out)",
    )
    args = parser.parse_args()

    if args.out and args.trials < MIN_PUBLISHED_TRIALS:
        print(
            f"error: --out publishes results and needs --trials {MIN_PUBLISHED_TRIALS} or more"
            f" (got {args.trials}). Drop --out to write a smaller run to evals/runs/.",
            file=sys.stderr,
        )
        return 1

    if args.out and args.raven_config:
        print(
            "error: --raven-config runs are ablations and stay unpublished; drop --out.",
            file=sys.stderr,
        )
        return 1

    if not 1 <= args.jobs <= MAX_JOBS:
        print(f"error: --jobs must be 1 to {MAX_JOBS} (got {args.jobs}).", file=sys.stderr)
        return 1

    if shutil.which(args.agent) is None:
        print(f"error: `{args.agent}` is not on PATH.", file=sys.stderr)
        return 1

    if args.scenario:
        wanted = set(args.scenario)
        scenarios = [s for s in SCENARIOS if s.name in wanted]
        unknown = wanted - {s.name for s in SCENARIOS}
        if unknown:
            print(f"error: unknown scenario(s): {', '.join(sorted(unknown))}", file=sys.stderr)
            return 1
    else:
        scenarios = [s for s in SCENARIOS if s.regression_only == args.regression]
    if not scenarios:
        print("error: no scenarios selected.", file=sys.stderr)
        return 1
    regression = [s.name for s in scenarios if s.regression_only]
    if args.out and regression:
        print(
            f"error: {', '.join(regression)} {'is' if len(regression) == 1 else 'are'}"
            " regression-only: both arms pass, so a published effect run leaves"
            " them out. Drop --out to run them.",
            file=sys.stderr,
        )
        return 1
    if args.trials < 1:
        print("error: --trials must be at least 1.", file=sys.stderr)
        return 1

    started = time.time()
    stamp_time = time.strftime("%Y%m%d-%H%M%S", time.localtime(started))
    transcripts = Path(args.transcripts) if args.transcripts else default_transcripts_dir(started)
    print(
        f"raven eval: {args.agent}, {len(scenarios)} scenario(s), {args.trials} trial(s) per arm,"
        f" {args.jobs} at a time"
    )
    print(f"transcripts: {transcripts}")
    raven_config = Path(args.raven_config) if args.raven_config else None
    outcomes = run(scenarios, args.agent, args.trials, transcripts, raven_config, args.jobs)
    failed = next((o for o in outcomes if o.evidence == AGENT_ERROR), None)
    if failed is not None:
        pending = len(scenarios) * args.trials * 2 - len(outcomes)
        print(
            f"error: the {args.agent} CLI failed before acting ({failed.error}); the run "
            f"stopped there with {pending} trial run(s) pending and nothing was published."
            " Fix the CLI and rerun.",
            file=sys.stderr,
        )
        args.out = None

    report = render_markdown(outcomes, args.agent, args.trials, args.stamp, raven_config)
    trials_csv = render_trials_csv(
        outcomes, args.agent, args.stamp, raven_config, args.jobs, _cli_version(args.agent)
    )
    # A run costs real money and ~15 minutes of wall clock, so it always leaves
    # an artifact now. Without `--out` the report went to stdout only, where a
    # pipe (`| tail -40`) or a closed scrollback destroyed it and the run had to
    # be repeated to recover the numbers. Defaulting to a timestamped file under
    # `evals/runs/` keeps the explicit `--out` behavior (stable filename, for
    # the committed reports) and makes silent loss impossible. The per-trial CSV
    # lands beside the report under the same stem.
    if args.out and args.out.endswith(".md"):
        out_dir = Path(args.out).parent
        name = Path(args.out).name
    elif args.out:
        out_dir = Path(args.out)
        name = f"results-{args.agent}.md"
    else:
        out_dir = REPO_ROOT / "evals" / "runs"
        name = f"results-{args.agent}-{stamp_time}.md"
    path = out_dir / name
    csv_path = path.with_suffix(".csv")
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(report, encoding="utf-8")
        # Bytes, not write_text(newline=""): that keyword needs Python 3.10 and the
        # floor is 3.9. Writing bytes keeps the csv module's line endings untranslated.
        csv_path.write_bytes(trials_csv.encode("utf-8"))
    except OSError as exc:
        print(f"error: could not write results: {exc}", file=sys.stderr)
        # Falling back to stdout rather than returning: losing the report is the
        # failure this block exists to prevent.
        print()
        print(report)
        print(trials_csv)
        return 2
    if not args.out:
        print()
        print(report)
    print(f"\nWrote {path} and {csv_path}")

    if args.json:
        print(json.dumps([o.__dict__ for o in outcomes], indent=2))
    return 2 if failed is not None else 0


if __name__ == "__main__":
    raise SystemExit(main())
