"""The Free Hit rules that more than one path has to obey.

Two of them, both from the official Fantasy Premier League rules for 2026-27:

- "The Free Hit chip cannot be played in consecutive Gameweeks." The season grants one
  Free Hit per half (``chips`` in bootstrap-static lists it for events 2 to 19 and again
  for 20 to 38), so the only pair the rule can forbid is gameweeks 19 and 20, and it does
  forbid it. ``played_free_hit_last_week`` is that rule, read before a deadline.
- A Free Hit squad lasts its own gameweek. At the next deadline the member holds the
  fifteen, and the bank, from *before* the chip, which is the previous gameweek's squad
  unless that week was a Free Hit too. ``free_hit_basis_gameweek`` walks that back.

Both the member path (a captured entry's picks) and our own path (the season ledger) ask
the second question, of different records; ``was_free_hit`` is where each says how to read
its own. Keeping one loop here is the point: two implementations of one rule disagreed,
and the ledger's resolved to a squad that never existed.
"""

from collections.abc import Callable, Iterable
from typing import Final

from squadopt.data.sources.fpl_live import FREE_HIT_CHIP

__all__ = [
    "FIRST_GAMEWEEK",
    "FREE_HIT_CHIP",
    "free_hit_basis_gameweek",
    "played_free_hit_last_week",
]

FIRST_GAMEWEEK: Final = 1
"""No squad is held before it, so a walk-back that reaches it has nowhere left to go."""


def played_free_hit_last_week(gameweek: int, weeks_played: Iterable[int]) -> bool:
    """Whether a Free Hit in the week before ``gameweek`` bars one in ``gameweek``.

    ``weeks_played`` is every week the member played the chip in, across both halves: the
    forbidden pair straddles the halves, so a check inside one window would never see it.
    """

    return int(gameweek) - 1 in {int(week) for week in weeks_played}


def free_hit_basis_gameweek(
    chip_gameweek: int, *, was_free_hit: Callable[[int], bool]
) -> int | None:
    """The gameweek whose squad is held after a Free Hit played in ``chip_gameweek``.

    Steps back while the week it lands on was also a Free Hit, and returns None when the
    walk falls below gameweek 1. The caller names that refusal in its own vocabulary,
    because a capture that lacks a document and a ledger that lacks an entry are different
    failures with different remedies. ``was_free_hit`` may raise its own error for a week
    it cannot read at all; nothing here swallows it.
    """

    week = int(chip_gameweek)
    while True:
        week -= 1
        if week < FIRST_GAMEWEEK:
            return None
        if not was_free_hit(week):
            return week
