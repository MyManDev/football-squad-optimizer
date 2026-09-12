"""The free transfers a member holds at a deadline, derived from the season history.

The public endpoints never state the banked count, so it is modelled from the history's
per-gameweek transfers and costs under the season's rules: the cap the capture states
(``free_transfer_cap`` in ``live/rules.py``) and the hit the game charges
(``TRANSFER_HIT_POINTS`` there, the same number the member planning policy charges).
Parsing that history is the data layer's job (``entry_transfer_history``); this module
is the model, and the application provider that builds a member's picks calls it.
"""

from dataclasses import dataclass
from typing import Final

from squadopt.data.errors import format_examples
from squadopt.data.sources.fpl_live import FREE_HIT_CHIP, EntryTransferHistory
from squadopt.live.rules import TRANSFER_HIT_POINTS

# The two chips under which transfers consume no free transfer and cost nothing. Bench
# Boost and Triple Captain change no squad, so they do not enter the banking model.
TRANSFER_CHIPS: Final = ("wildcard", FREE_HIT_CHIP)


@dataclass(frozen=True, slots=True)
class BankedFreeTransfers:
    """The free transfers a member can spend at the coming deadline, and whether that is
    derived or the rule floor. ``reason`` says why a count is unknown; the picks record
    carries only the count and the flag, so a caller wanting the reason reads this."""

    count: int
    known: bool
    reason: str | None = None


def banked_free_transfers(
    history: EntryTransferHistory,
    *,
    gameweek: int,
    max_free_transfers: int | None,
    active_chip: str | None = None,
) -> BankedFreeTransfers:
    """Derive the free transfers held at the deadline after ``gameweek`` from the history.

    The model, under the rules in force since 2024-25 (``docs/transfer_planning_spec.md``,
    ``wildcard_preserves_free_transfers``; the cap from the captured settings):

    * No free transfer exists at the gameweek 1 deadline: the opening squad is built
      with unlimited changes. From gameweek 2 on, one is added before each deadline and
      the bank is capped at ``max_free_transfers``.
    * A week's transfers consume the banked ones first; each beyond them costs
      ``TRANSFER_HIT_POINTS``. So the cost the history records must equal the hit times
      the transfers above the count this model says was available: that identity is
      checked for every week, and a week that breaks it means the model is wrong, so
      the count is reported unknown rather than trusted.
    * Under a Wildcard or Free Hit the transfers consume nothing and cost nothing, and
      the bank is kept and still gains its one the week after.

    A member whose rows do not start at gameweek 1 or skip a week up to ``gameweek``
    is reported unknown: a late joiner's opening week is not modelled here. The captured
    week's own chip comes in as ``active_chip``: the history lists a chip only once its
    week is over.
    """

    if gameweek < 1:
        raise ValueError(f"gameweek must be positive, got {gameweek}.")
    week = gameweek
    if max_free_transfers is None:
        return BankedFreeTransfers(1, False, "the capture states no free-transfer cap")
    missing = [w for w in range(1, week + 1) if w not in history.weeks]
    if missing:
        return BankedFreeTransfers(
            1, False, f"the history has no row for gameweek {format_examples(missing)}"
        )
    chip_weeks = {
        event
        for name, events in history.chips_used.items()
        if name in TRANSFER_CHIPS
        for event in events
    }
    if active_chip in TRANSFER_CHIPS:
        chip_weeks.add(week)
    available = 0
    for w in range(1, week + 1):
        row = history.weeks[w]
        unlimited = w == 1 or w in chip_weeks
        consumed = 0 if unlimited else min(row.transfers, available)
        expected = 0 if unlimited else (row.transfers - consumed) * TRANSFER_HIT_POINTS
        if row.cost != expected:
            return BankedFreeTransfers(
                1,
                False,
                f"gameweek {w} recorded {row.transfers} transfers costing {row.cost} points, "
                f"but with {available} free the banking model expects {expected}",
            )
        available = min(max_free_transfers, available - consumed + 1)
    return BankedFreeTransfers(available, True)
