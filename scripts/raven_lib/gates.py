from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from types import MappingProxyType

from .data.gate_data import GATE_DATA


@dataclass(frozen=True)
class GateSpec:
    recipes: tuple[str, ...]
    tools: tuple[str, ...]
    config_signals: tuple[tuple[str, str | None], ...]
    detect_signals: tuple[str, ...]
    fallback_commands: Mapping[str, tuple[str, ...]]


def _str_tuple(value: object) -> tuple[str, ...]:
    """Coerce a list into a tuple of strings; anything else yields ()."""
    if isinstance(value, list):
        return tuple(str(item) for item in value)
    return ()


def _build_spec(raw: dict[str, object]) -> GateSpec:
    config_signals: list[tuple[str, str | None]] = []
    config_signals_raw = raw.get("config_signals")
    if isinstance(config_signals_raw, list):
        for pair in config_signals_raw:
            if isinstance(pair, list) and pair:
                file = str(pair[0])
                substring = str(pair[1]) if len(pair) > 1 and pair[1] != "" else None
                config_signals.append((file, substring))
    fallback: dict[str, tuple[str, ...]] = {}
    fallback_raw = raw.get("fallback_commands")
    if isinstance(fallback_raw, dict):
        for recipe, command in fallback_raw.items():
            if isinstance(command, list):
                fallback[str(recipe)] = tuple(str(part) for part in command)
    return GateSpec(
        recipes=_str_tuple(raw.get("recipes")),
        tools=_str_tuple(raw.get("tools")),
        config_signals=tuple(config_signals),
        detect_signals=_str_tuple(raw.get("detect_signals")),
        fallback_commands=MappingProxyType(fallback),
    )


@lru_cache(maxsize=1)
def load_gate_specs() -> dict[str, GateSpec]:
    return {name: _build_spec(raw) for name, raw in GATE_DATA.items() if isinstance(raw, dict)}


def gate_spec_for(template: str) -> GateSpec | None:
    return load_gate_specs().get(template)


def recipe_present(justfile_text: str, recipe: str) -> bool:
    """True when the justfile declares a top-level recipe with this name."""
    return any(line.rstrip().startswith(f"{recipe}:") for line in justfile_text.splitlines())
