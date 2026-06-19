from __future__ import annotations

import tomllib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

_GATES_PATH = Path(__file__).resolve().parent / "data" / "gates.toml"


@dataclass(frozen=True)
class GateSpec:
    recipes: tuple[str, ...]
    tools: tuple[str, ...]
    config_signals: tuple[tuple[str, str | None], ...]
    detect_signals: tuple[str, ...]
    fallback_commands: dict[str, tuple[str, ...]]


def _build_spec(raw: dict[str, object]) -> GateSpec:
    recipes = tuple(str(r) for r in raw.get("recipes", []))  # type: ignore[union-attr]
    tools = tuple(str(t) for t in raw.get("tools", []))  # type: ignore[union-attr]
    detect = tuple(str(s) for s in raw.get("detect_signals", []))  # type: ignore[union-attr]
    config_signals_raw = raw.get("config_signals", [])
    config_signals: list[tuple[str, str | None]] = []
    if isinstance(config_signals_raw, list):
        for pair in config_signals_raw:
            if isinstance(pair, list) and pair:
                file = str(pair[0])
                substring = str(pair[1]) if len(pair) > 1 and pair[1] != "" else None
                config_signals.append((file, substring))
    fallback_raw = raw.get("fallback_commands", {})
    fallback: dict[str, tuple[str, ...]] = {}
    if isinstance(fallback_raw, dict):
        for recipe, command in fallback_raw.items():
            if isinstance(command, list):
                fallback[str(recipe)] = tuple(str(part) for part in command)
    return GateSpec(
        recipes=recipes,
        tools=tools,
        config_signals=tuple(config_signals),
        detect_signals=detect,
        fallback_commands=fallback,
    )


@lru_cache(maxsize=1)
def load_gate_specs() -> dict[str, GateSpec]:
    data = tomllib.loads(_GATES_PATH.read_text(encoding="utf-8"))
    return {name: _build_spec(raw) for name, raw in data.items() if isinstance(raw, dict)}


def gate_spec_for(template: str) -> GateSpec | None:
    return load_gate_specs().get(template)
