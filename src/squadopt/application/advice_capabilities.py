"""Computable member requests, shared by the producer and transport adapters.

Two lists, on purpose. ``advice_capabilities`` is what ``advise_entry`` itself answers and
has not moved: the pure-points plan at every window, a rival strategy at one week.
``menu_capabilities`` is the whole member menu, which ``advise_menu_entry`` answers by
dispatching to the producer each document has: a rival strategy over a window, a Top 100
setting on all of them, the manager's word on the one-week pure-points plan. A caller that
passes neither a setting nor the word and leaves ``capabilities`` alone is validated
exactly as before.
"""

from collections.abc import Mapping
from dataclasses import dataclass

from squadopt.application.entries import EntryError
from squadopt.application.strategies import STRATEGY_CATALOG
from squadopt.live.rules import CHIP_NAMES

COMPUTED_MODE = "saf-puan"
COMPUTED_WINDOW = 1
MEMBER_WINDOWS: tuple[int, ...] = (1, 3, 5)

#: The Top 100 settings a member may choose; zero is off. ``application/top100_weight.py``
#: owns the rule and re-exports this tuple, so the transport and the producer read one list.
TOP100_WEIGHTS: tuple[int, ...] = (0, 5, 10, 20, 30, 40, 50)


@dataclass(frozen=True, slots=True)
class AdviceCapability:
    windows: tuple[int, ...]
    requires_rival: bool
    #: The windows a Top 100 setting may be asked at, and the ones the manager's word may.
    #: Empty means the switch is not offered for this strategy on this path.
    top100_windows: tuple[int, ...] = ()
    managers_word_windows: tuple[int, ...] = ()
    chip_windows: tuple[int, ...] = ()


def _rival_strategies() -> tuple[str, ...]:
    return tuple(
        slug
        for slug, strategy in STRATEGY_CATALOG.items()
        if strategy.constraints.overlap_floor is not None
        or strategy.constraints.overlap_ceiling is not None
    )


def advice_capabilities() -> dict[str, AdviceCapability]:
    capabilities = {COMPUTED_MODE: AdviceCapability(MEMBER_WINDOWS, False)}
    for slug in _rival_strategies():
        capabilities[slug] = AdviceCapability((COMPUTED_WINDOW,), True)
    return capabilities


def menu_capabilities() -> dict[str, AdviceCapability]:
    """Everything the member menu offers, which is what the batch publishes.

    A switch is one more tuple of windows on the capability; a further one (a chip, say)
    is added here the same way and validated in ``validate_advice_selection``.
    """

    capabilities = {
        COMPUTED_MODE: AdviceCapability(
            MEMBER_WINDOWS,
            False,
            top100_windows=MEMBER_WINDOWS,
            managers_word_windows=(COMPUTED_WINDOW,),
            chip_windows=(COMPUTED_WINDOW,),
        )
    }
    for slug in _rival_strategies():
        capabilities[slug] = AdviceCapability(MEMBER_WINDOWS, True, top100_windows=MEMBER_WINDOWS)
    return capabilities


def validate_advice_selection(
    *,
    strategy: str,
    window: int,
    entry_id: int,
    rival_entry_id: int | None,
    capabilities: Mapping[str, AdviceCapability] | None = None,
    top100_weight: int = 0,
    managers_word: bool = False,
    chip: str | None = None,
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
    if (
        isinstance(top100_weight, bool)
        or not isinstance(top100_weight, int)
        or top100_weight not in TOP100_WEIGHTS
    ):
        raise EntryError(
            f"The Top 100 influence must be one of {list(TOP100_WEIGHTS)}; got {top100_weight!r}."
        )
    if not isinstance(managers_word, bool):
        raise EntryError("managers_word must be true or false.")
    if top100_weight and window not in capability.top100_windows:
        raise EntryError(
            f"The Top 100 influence is not computed for {strategy!r} at window {window} "
            "on this path."
        )
    if managers_word and window not in capability.managers_word_windows:
        raise EntryError("The manager's word applies to the one-week pure-points plan only.")
    if chip is not None:
        if chip not in CHIP_NAMES:
            raise EntryError("Unknown chip choice.")
        if window not in capability.chip_windows or top100_weight or managers_word:
            raise EntryError(
                "A chip requires the one-week pure-points plan with other switches off."
            )
