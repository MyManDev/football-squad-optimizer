"""Read FPL's published taker priorities without treating ranks as probabilities."""

from __future__ import annotations

import json
from numbers import Integral

import pandas as pd

from squadopt.data.errors import (
    DataValidationError,
    DuplicateRecordsError,
    InvalidValueError,
    MissingColumnsError,
    format_examples,
)

TAKER_FIELDS = (
    "penalties_order",
    "direct_freekicks_order",
    "corners_and_indirect_freekicks_order",
)


def _is_positive_integer(value: object) -> bool:
    return not isinstance(value, bool) and isinstance(value, Integral) and int(value) > 0


def captured_taker_priorities(bootstrap: bytes) -> pd.DataFrame:
    """Use stable player codes; a null rank means unknown, never zero ability.

    Every element must carry every taker field. FPL writes ``null`` for a player with no
    rank, so a null is a published "unknown" and stays missing. An *absent* key is not
    that: it is a renamed or dropped field, and reading it as null would turn every
    player's rank into unknown and remove every penalty-taker signal without an error.

    The caller owns the immutable capture identity and timestamp. Do not fetch current
    priorities inside a historical forecast, or infer event rates from these ranks.
    """
    rows = []
    missing: dict[str, list[object]] = {}
    for player in json.loads(bootstrap)["elements"]:
        if "code" not in player:
            raise MissingColumnsError(
                f"FPL taker priorities require each element's 'code'; element "
                f"{player.get('id')!r} has none."
            )
        code = player["code"]
        if not _is_positive_integer(code):
            raise InvalidValueError(
                "FPL taker priorities require a positive stable player code, got "
                f"{format_examples([code])} for element {player.get('id')!r}."
            )
        row: dict[str, object] = {"player_id": int(code)}
        for field in TAKER_FIELDS:
            if field not in player:
                missing.setdefault(field, []).append(code)
                continue
            rank = player[field]
            if rank is not None and not _is_positive_integer(rank):
                raise InvalidValueError(
                    f"FPL taker priorities must be positive integer ranks or null: {field!r} "
                    f"is {format_examples([rank])} for player code {code!r}."
                )
            row[field] = rank
        rows.append(row)
    if missing:
        raise MissingColumnsError(
            "FPL taker priorities need every taker field on every element; absent "
            + "; ".join(
                f"{field!r} for player codes {format_examples(codes)}"
                for field, codes in sorted(missing.items())
            )
            + ". A renamed field would otherwise read as every rank unknown."
        )
    table = pd.DataFrame(rows, columns=("player_id", *TAKER_FIELDS))
    if table.empty:
        raise DataValidationError("FPL taker priorities require a nonempty player roster.")
    duplicated = table.player_id[table.player_id.duplicated()]
    if not duplicated.empty:
        raise DuplicateRecordsError(
            "FPL taker priorities require a unique player roster; repeated player codes: "
            f"{format_examples(sorted(set(duplicated.tolist())))}."
        )
    for field in TAKER_FIELDS:
        table[field] = table[field].astype("Int64")
    return table
