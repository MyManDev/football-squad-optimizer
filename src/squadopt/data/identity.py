"""Reconcile a live capture's player identities against known history.

The live source and the historical archive are supposed to identify a player the
same way, through the platform's persistent player code. Everything downstream
depends on that: cross-season carry-over, the residual history and every paired
comparison join on it. If the two ever drift into different identifier spaces, the
join does not fail loudly — it silently matches nothing, and a season's worth of
history quietly becomes unavailable for every player at once.

This module is the check that turns that silent failure into a stated one. It lives
above both source adapters because each of those is meant to know exactly one source,
and a reconciliation by definition knows two.

A new player is not an error. At the opening gameweek of a season a large minority of
the roster has no record anywhere, and the projection layer has an explicit fallback
for exactly that. What is an error is *nobody* matching, because a whole roster of
debutants is not a thing that happens.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from numbers import Integral

import pandas as pd

from squadopt.data.errors import InvalidValueError, format_examples


@dataclass(frozen=True, slots=True)
class IdentityReconciliation:
    """How a captured roster lines up with the identities already on record.

    ``new_player_ids`` is reported in full rather than sampled. These are the players
    a projection has to cold-start, so the count and the identities are both operator
    information rather than a diagnostic detail.
    """

    captured_players: int
    known_players: int
    new_players: int
    new_player_ids: tuple[int, ...]

    @property
    def known_fraction(self) -> float:
        """Share of the captured roster that has history to draw on."""

        return self.known_players / self.captured_players


def _known_identifiers(values: Iterable[object]) -> set[int]:
    known: set[int] = set()
    invalid: list[object] = []
    for value in values:
        if isinstance(value, bool) or not isinstance(value, Integral):
            invalid.append(value)
            continue
        known.add(int(value))
    if invalid:
        raise InvalidValueError(
            "Known player identifiers must be integers matching the canonical "
            f"player_id space: {format_examples(invalid)}."
        )
    if not known:
        raise InvalidValueError(
            "No known player identifiers were supplied, so nothing can be reconciled. "
            "Pass the player_id values of the historical panel."
        )
    return known


def reconcile_player_identity(
    captured: pd.DataFrame, known_player_ids: Iterable[object]
) -> IdentityReconciliation:
    """Compare a captured roster's identities with those already on record.

    ``known_player_ids`` is passed in rather than read from the archive here, so this
    stays independent of which history is being reconciled against and can be tested
    without one.
    """

    if not isinstance(captured, pd.DataFrame):
        raise InvalidValueError("Captured roster must be a pandas DataFrame.")
    if "player_id" not in captured.columns:
        raise InvalidValueError(
            f"Captured roster is missing column 'player_id'; it carries "
            f"{sorted(map(str, captured.columns))!r}."
        )
    if captured.empty:
        raise InvalidValueError("Captured roster has no rows to reconcile.")

    known = _known_identifiers(known_player_ids)
    captured_ids = _known_identifiers(captured["player_id"].tolist())

    new_ids = tuple(sorted(captured_ids - known))
    matched = len(captured_ids) - len(new_ids)
    if matched == 0:
        raise InvalidValueError(
            f"None of the {len(captured_ids)} captured players appear in the "
            f"{len(known)} identities on record. A roster of complete unknowns is not "
            "plausible, so the two sides are keyed on different identifier spaces — "
            "most likely a per-season element id on one side and the persistent player "
            f"code on the other. Captured examples: {format_examples(sorted(captured_ids)[:5])}; "
            f"known examples: {format_examples(sorted(known)[:5])}."
        )

    return IdentityReconciliation(
        captured_players=len(captured_ids),
        known_players=matched,
        new_players=len(new_ids),
        new_player_ids=new_ids,
    )
