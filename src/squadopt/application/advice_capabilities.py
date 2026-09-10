"""Computable member requests, shared by the producer and transport adapters."""

from collections.abc import Mapping
from dataclasses import dataclass

from squadopt.application.entries import EntryError
from squadopt.application.strategies import STRATEGY_CATALOG

COMPUTED_MODE = "saf-puan"
COMPUTED_WINDOW = 1
MEMBER_WINDOWS: tuple[int, ...] = (1, 3, 5)


@dataclass(frozen=True, slots=True)
class AdviceCapability:
    windows: tuple[int, ...]
    requires_rival: bool


def advice_capabilities() -> dict[str, AdviceCapability]:
    capabilities = {COMPUTED_MODE: AdviceCapability(MEMBER_WINDOWS, False)}
    for slug, strategy in STRATEGY_CATALOG.items():
        constraints = strategy.constraints
        if constraints.overlap_floor is not None or constraints.overlap_ceiling is not None:
            capabilities[slug] = AdviceCapability((COMPUTED_WINDOW,), True)
    return capabilities


def validate_advice_selection(
    *,
    strategy: str,
    window: int,
    entry_id: int,
    rival_entry_id: int | None,
    capabilities: Mapping[str, AdviceCapability] | None = None,
) -> None:
    available = advice_capabilities() if capabilities is None else capabilities
    capability = available.get(strategy)
    if capability is None:
        raise EntryError(f"Strategy {strategy!r} is not computed on this path yet.")
    if isinstance(window, bool) or not isinstance(window, int) or window not in capability.windows:
        raise EntryError(f"Strategy {strategy!r} supports windows {capability.windows} only.")
    if capability.requires_rival and rival_entry_id is None:
        raise EntryError(f"Strategy {strategy!r} needs a rival: pass rival_entry_id.")
    if not capability.requires_rival and rival_entry_id is not None:
        raise EntryError(f"{strategy!r} is rival-free; ask for a rival strategy to name a rival.")
    if rival_entry_id is not None and rival_entry_id == entry_id:
        raise EntryError("A member cannot be their own rival.")
