"""Captured season rights for the opt-in chip strategy; no live state reads."""

from collections.abc import Mapping, Sequence

from squadopt.live.rules import SeasonRules
from squadopt.planning import ChipAvailability, ChipUseWindow


def strategy_chip_availability(
    rules: SeasonRules,
    gameweeks: Sequence[int],
    used: Mapping[str, Sequence[int]] | None,
    *,
    forced: Mapping[int, str] | None = None,
) -> ChipAvailability:
    """Keep each unspent period separate, including its unobserved tail dates.

    Only rights intersecting the requested horizon are included. Unknown history
    is refused, never interpreted as all rights still held. A historical Free Hit
    also removes the following week across a renewal boundary.
    """
    if used is None:
        raise ValueError("Chip strategy requires captured chip history.")
    if not gameweeks or tuple(gameweeks) != tuple(range(gameweeks[0], gameweeks[-1] + 1)):
        raise ValueError("Chip strategy requires consecutive gameweeks.")
    periods: dict[str, list[ChipUseWindow]] = {}
    for window in rules.chips:
        if window.number != 1:
            raise ValueError("Chip strategy supports one right per published window.")
        if any(window.covers(int(w)) for w in used.get(window.name, ())):
            continue
        dates = frozenset(
            w
            for w in range(max(gameweeks[0], window.start_event), window.stop_event + 1)
            if window.name != "freehit" or w - 1 not in used.get("freehit", ())
        )
        if dates.intersection(gameweeks):
            periods.setdefault(window.name, []).append(ChipUseWindow(dates))
    return ChipAvailability(
        available={
            name: frozenset().union(*(p.gameweeks for p in ps)) for name, ps in periods.items()
        },
        forced=dict(forced or {}),
        use_windows={name: tuple(ps) for name, ps in periods.items()},
    )
