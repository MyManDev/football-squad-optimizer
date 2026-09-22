"""Read FPL's published taker priorities without treating ranks as probabilities."""

from __future__ import annotations

import json
from numbers import Integral

import pandas as pd

TAKER_FIELDS = (
    "penalties_order",
    "direct_freekicks_order",
    "corners_and_indirect_freekicks_order",
)


def captured_taker_priorities(bootstrap: bytes) -> pd.DataFrame:
    """Use stable player codes; a missing rank means unknown, never zero ability.

    The caller owns the immutable capture identity and timestamp. Do not fetch current
    priorities inside a historical forecast, or infer event rates from these ranks.
    """
    rows = []
    for player in json.loads(bootstrap)["elements"]:
        code = player["code"]
        if isinstance(code, bool) or not isinstance(code, Integral) or code <= 0:
            raise ValueError("FPL taker priorities require a positive stable player code.")
        row: dict[str, object] = {"player_id": int(code)}
        for field in TAKER_FIELDS:
            rank = player.get(field)
            if rank is not None and (
                isinstance(rank, bool) or not isinstance(rank, Integral) or rank <= 0
            ):
                raise ValueError("FPL taker priorities must be positive integer ranks or null.")
            row[field] = rank
        rows.append(row)
    table = pd.DataFrame(rows, columns=("player_id", *TAKER_FIELDS))
    if table.empty or table.player_id.duplicated().any():
        raise ValueError("FPL taker priorities require a unique nonempty player roster.")
    for field in TAKER_FIELDS:
        table[field] = table[field].astype("Int64")
    return table
