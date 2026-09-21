"""What the live projection got wrong, read from one table a gameweek.

The protocol is ``docs/live_projection_audit_prereg.md``. This module is the arithmetic and
holds no file access: it is handed, for one settled gameweek, the forecasts made before the
deadline and the outcome read after it, all keyed on the persistent player code, and returns
plain numbers. The runner that finds the captures and writes the record is
``scripts/measure_live_projection_audit.py``.

Three forecasts are made comparable:

``ours_decided``
    our projection times the availability multiplier of the same capture: what the solver read.
``ours_unconditional``
    our projection before availability, so the part of the error that is "did he appear" can
    be told from the rest.
``game``
    the game's own ``ep_next`` from the same capture. A yardstick, never an input.

Nothing here is a test. There is no gate and no interval: players inside one gameweek share
fixtures, so an interval over them would be too narrow, and the pooled reading that uses
gameweeks as its unit waits until there are enough of them. Absent is not zero throughout: a
player a forecast does not name is left out of that forecast's numbers, never scored as a
forecast of nothing.
"""

from collections.abc import Mapping, Sequence
from typing import Final

import pandas as pd

LIVE_PROJECTION_AUDIT_CONTRACT_VERSION: Final = "live_projection_audit_v1"

#: Where the solver buys: each position's most highly forecast players.
TOP_PER_POSITION: Final = 40
#: Price bands in tenths: under 5.0, 5.0 to 7.5, above 7.5.
PRICE_BANDS: Final[tuple[tuple[str, int, int], ...]] = (
    ("under_5.0", 0, 49),
    ("5.0_to_7.5", 50, 75),
    ("above_7.5", 76, 10_000),
)
MINUTES_BUCKETS: Final[tuple[tuple[str, int, int], ...]] = (
    ("did_not_appear", 0, 0),
    ("1_to_59", 1, 59),
    ("60_and_above", 60, 10_000),
)
#: How large the forecast was for a player who then did not appear: squad filler, a
#: rotation option, or somebody the forecast expected to start.
FORECAST_SIZES: Final[tuple[tuple[str, float, float], ...]] = (
    ("under_1.0", 0.0, 1.0),
    ("1.0_to_2.5", 1.0, 2.5),
    ("2.5_and_above", 2.5, float("inf")),
)
#: Minutes a gameweek the player had played this season before the deadline. Sixty is the
#: game's own line for a full appearance; none is a player the season has not yet seen.
PRIOR_MINUTES_BUCKETS: Final[tuple[tuple[str, float, float], ...]] = (
    ("none", 0.0, 0.0),
    ("under_30", 0.0, 30.0),
    ("30_to_60", 30.0, 60.0),
    ("60_and_above", 60.0, float("inf")),
)
#: How many of the largest absent forecasts a reading lists by player.
LARGEST_ABSENT: Final = 10
FORECASTS: Final[tuple[str, ...]] = ("ours_decided", "ours_unconditional", "game")
POSITIONS: Final[tuple[str, ...]] = ("GK", "DEF", "MID", "FWD")

FRAME_COLUMNS: Final[tuple[str, ...]] = (
    "player_id",
    "position",
    "price_tenths",
    "ours_unconditional",
    "ours_decided",
    "game",
    "realized_points",
    "minutes",
    "prior_minutes_per_week",
)


class LiveProjectionAuditError(ValueError):
    """The audit was handed tables it cannot pair."""


def audit_frame(
    players: pd.DataFrame,
    outcomes: pd.DataFrame,
    *,
    expected_points: Mapping[int, float] | None,
    multipliers: Mapping[int, float] | None,
    decided: Mapping[int, float] | None = None,
    game: Mapping[int, float] | None,
    prior_minutes_per_week: Mapping[int, float] | None = None,
) -> pd.DataFrame:
    """Pair one gameweek's forecasts with its outcome, one row per player of the capture.

    ``players`` is the pre-deadline capture's roster (``player_id``, ``position``,
    ``price_tenths``); ``outcomes`` the settled gameweek (``player_id``, ``minutes``,
    ``total_points``). A player of the roster the outcome does not name did not feature in
    the gameweek's payload and is dropped with everybody else the outcome lacks; a player
    the outcome names and the roster does not was not available to buy at the deadline.

    ``decided`` overrides the product of ``expected_points`` and ``multipliers`` for the one
    case where only the decided numbers survive (gameweek 1, whose capture was lost).
    ``prior_minutes_per_week`` is what the same capture said each player had played so
    far this season, a gameweek; a player it does not name has no prior, which is not
    a prior of nothing.
    """

    for name, frame, columns in (
        ("players", players, ("player_id", "position", "price_tenths")),
        ("outcomes", outcomes, ("player_id", "minutes", "total_points")),
    ):
        missing = [column for column in columns if column not in frame.columns]
        if missing:
            raise LiveProjectionAuditError(f"The {name} table lacks {missing!r}.")
    if players["player_id"].duplicated().any() or outcomes["player_id"].duplicated().any():
        raise LiveProjectionAuditError("A player appears twice; the tables cannot be paired.")

    frame = players.loc[:, ["player_id", "position", "price_tenths"]].merge(
        outcomes.loc[:, ["player_id", "minutes", "total_points"]], on="player_id", how="inner"
    )
    frame = frame.rename(columns={"total_points": "realized_points"})
    ids = frame["player_id"].astype("int64")
    frame["ours_unconditional"] = (
        ids.map(dict(expected_points)) if expected_points is not None else float("nan")
    )
    if decided is not None:
        frame["ours_decided"] = ids.map(dict(decided))
    elif expected_points is not None and multipliers is not None:
        # A player the availability rule does not name is scored as the rule scores him
        # everywhere else: unchanged.
        frame["ours_decided"] = frame["ours_unconditional"] * ids.map(dict(multipliers)).fillna(1.0)
    else:
        frame["ours_decided"] = float("nan")
    frame["game"] = ids.map(dict(game)) if game is not None else float("nan")
    frame["prior_minutes_per_week"] = (
        ids.map(dict(prior_minutes_per_week))
        if prior_minutes_per_week is not None
        else float("nan")
    )
    ordered = frame.loc[:, list(FRAME_COLUMNS)].sort_values("player_id").reset_index(drop=True)
    return ordered.astype({"realized_points": "float64", "minutes": "int64"})


def _error_block(frame: pd.DataFrame, forecast: str) -> dict[str, object]:
    rows = frame.loc[frame[forecast].notna()]
    if rows.empty:
        return {"players": 0}
    error = rows["realized_points"] - rows[forecast]
    return {
        "players": len(rows),
        "mean_absolute_error": float(error.abs().mean()),
        "bias": float(error.mean()),
        "mean_forecast": float(rows[forecast].mean()),
        "mean_realized": float(rows["realized_points"].mean()),
    }


def _rank_agreement(frame: pd.DataFrame, forecast: str, by: Sequence[str]) -> dict[str, object]:
    """Spearman agreement inside each group, and their mean weighted by group size."""

    groups: dict[str, dict[str, object]] = {}
    total = 0
    weighted = 0.0
    # Pooled gameweeks are never ranked against each other: order is a within-week question.
    keys = [*(["gameweek"] if "gameweek" in frame.columns else []), *by]
    for key, rows in frame.loc[frame[forecast].notna()].groupby(keys, sort=True):
        if len(rows) < 3 or rows[forecast].nunique() < 2 or rows["realized_points"].nunique() < 2:
            continue
        value = float(rows[forecast].corr(rows["realized_points"], method="spearman"))
        label = "|".join(str(part) for part in (key if isinstance(key, tuple) else (key,)))
        groups[label] = {"players": len(rows), "spearman": value}
        total += len(rows)
        weighted += value * len(rows)
    return {
        "weighted_mean": weighted / total if total else None,
        "players": total,
        "groups": groups,
    }


def _band(price_tenths: int) -> str:
    for label, low, high in PRICE_BANDS:
        if low <= price_tenths <= high:
            return label
    raise LiveProjectionAuditError(f"No price band holds {price_tenths}.")


def _top(frame: pd.DataFrame, forecast: str) -> pd.DataFrame:
    rows = frame.loc[frame[forecast].notna()]
    ranked = rows.sort_values([forecast, "player_id"], ascending=[False, True])
    keys = [*(["gameweek"] if "gameweek" in rows.columns else []), "position"]
    return ranked.groupby(keys, sort=True).head(TOP_PER_POSITION)


def _appearance_split(frame: pd.DataFrame, forecast: str) -> dict[str, object]:
    """How much of a forecast sat on players who did not appear, and the error over the rest."""

    rows = frame.loc[frame[forecast].notna()]
    if rows.empty:
        return {"players": 0}
    buckets: dict[str, object] = {}
    for label, low, high in MINUTES_BUCKETS:
        held = rows.loc[rows["minutes"].between(low, high)]
        buckets[label] = {
            **_error_block(held, forecast),
            "forecast_points": float(held[forecast].sum()),
        }
    absent = rows.loc[rows["minutes"] == 0]
    total = float(rows[forecast].sum())
    return {
        "forecast_points": total,
        "forecast_points_on_players_who_did_not_appear": float(absent[forecast].sum()),
        "share_on_players_who_did_not_appear": (
            float(absent[forecast].sum()) / total if total > 0 else None
        ),
        "by_minutes": buckets,
    }


def _by_prior_minutes(frame: pd.DataFrame, forecast: str) -> dict[str, object]:
    """The error by how much the player had been playing before the deadline.

    It asks where a forecast's level is off: on the players the season has not yet
    seen, on the rotation, or on the regulars. Totals sit beside the means because the
    buckets are of very different sizes and a small mean over many players is a large
    number of points.
    """

    rows = frame.loc[frame[forecast].notna() & frame["prior_minutes_per_week"].notna()]
    if rows.empty:
        return {"players": 0}
    buckets: dict[str, object] = {}
    prior = rows["prior_minutes_per_week"]
    for label, low, high in PRIOR_MINUTES_BUCKETS:
        held = rows.loc[
            (prior == 0) if high == 0 else (prior > 0) & (prior >= low) & (prior < high)
        ]
        buckets[label] = {
            **_error_block(held, forecast),
            "forecast_points": float(held[forecast].sum()),
            "realized_points": float(held["realized_points"].sum()),
            "appeared": int((held["minutes"] > 0).sum()),
        }
    return {"players": len(rows), "buckets": buckets}


def _mass(rows: pd.DataFrame, forecast: str, total: float) -> dict[str, object]:
    points = float(rows[forecast].sum())
    return {
        "players": len(rows),
        "forecast_points": points,
        "share_of_absent_forecast": points / total if total > 0 else None,
    }


def absent_forecast(frame: pd.DataFrame, forecast: str) -> dict[str, object]:
    """Where the forecast points of players who did not appear were sitting.

    The appearance split says how much of a forecast sat on players who did not appear.
    This says on whom: by position, by price band, by how large the forecast was, and
    by whether our own availability rule had named the player before the deadline
    (``ours_decided`` below ``ours_unconditional``). The last split separates two
    different faults. Points on players the rule named are "the rule discounts too
    little"; points on players nobody named are "the projection expected somebody to
    play who was never going to", which no availability flag can repair. It is asked
    of every forecast with the same naming, so the game's own forecast is read against
    our rule's flags and the two are comparable.
    """

    rows = frame.loc[frame[forecast].notna() & (frame["minutes"] == 0)]
    total = float(rows[forecast].sum())
    banded = rows.assign(price_band=rows["price_tenths"].map(_band))
    # Absent on either side is not a flag: a player the rule never scored was not named.
    named = rows["ours_decided"] < rows["ours_unconditional"] - 1e-9
    largest = rows.sort_values([forecast, "player_id"], ascending=[False, True]).head(
        LARGEST_ABSENT
    )
    return {
        "players": len(rows),
        "forecast_points": total,
        "by_position": {
            position: _mass(rows.loc[rows["position"] == position], forecast, total)
            for position in POSITIONS
        },
        "by_price_band": {
            label: _mass(banded.loc[banded["price_band"] == label], forecast, total)
            for label, _, _ in PRICE_BANDS
        },
        "by_forecast_size": {
            label: _mass(
                rows.loc[(rows[forecast] >= low) & (rows[forecast] < high)], forecast, total
            )
            for label, low, high in FORECAST_SIZES
        },
        "by_our_availability_rule": {
            "named": _mass(rows.loc[named], forecast, total),
            "not_named": _mass(rows.loc[~named], forecast, total),
        },
        "largest": [
            {
                "player_id": int(player_id),
                "position": str(position),
                "price_tenths": int(price_tenths),
                "forecast_points": float(points),
                "named_by_our_availability_rule": bool(flag),
            }
            for player_id, position, price_tenths, points, flag in zip(
                largest["player_id"],
                largest["position"],
                largest["price_tenths"],
                largest[forecast],
                named.loc[largest.index],
                strict=True,
            )
        ],
    }


def summarise_forecast(frame: pd.DataFrame, forecast: str) -> dict[str, object]:
    """Everything the protocol reads about one forecast in one gameweek."""

    if forecast not in FORECASTS:
        raise LiveProjectionAuditError(f"Unknown forecast {forecast!r}.")
    banded = frame.assign(price_band=frame["price_tenths"].map(_band))
    top = _top(banded, forecast)
    return {
        "all_players": _error_block(banded, forecast),
        "top_per_position": {"per_position": TOP_PER_POSITION, **_error_block(top, forecast)},
        "rank_agreement_within_position": _rank_agreement(banded, forecast, ("position",)),
        "rank_agreement_within_position_and_price_band": _rank_agreement(
            banded, forecast, ("position", "price_band")
        ),
        "by_position": {
            position: _error_block(banded.loc[banded["position"] == position], forecast)
            for position in POSITIONS
        },
        "by_price_band": {
            label: _error_block(banded.loc[banded["price_band"] == label], forecast)
            for label, _, _ in PRICE_BANDS
        },
        "appearance_split": _appearance_split(banded, forecast),
        "absent_forecast": absent_forecast(banded, forecast),
        "by_prior_minutes": _by_prior_minutes(banded, forecast),
    }


def paired_difference(frame: pd.DataFrame, first: str, second: str) -> dict[str, object]:
    """Mean difference in absolute error, ``first`` minus ``second``, over players both name.

    Negative favours ``first``. No interval: one gameweek's players share fixtures, and the
    protocol says so.
    """

    rows = frame.loc[frame[first].notna() & frame[second].notna()]
    if rows.empty:
        return {"players": 0}
    one = (rows["realized_points"] - rows[first]).abs()
    two = (rows["realized_points"] - rows[second]).abs()
    top = _top(rows, second)
    top_one = (top["realized_points"] - top[first]).abs()
    top_two = (top["realized_points"] - top[second]).abs()
    return {
        "players": len(rows),
        "mean_absolute_error_difference": float((one - two).mean()),
        "top_per_position_players": len(top),
        "top_per_position_difference": float((top_one - top_two).mean()),
        "top_per_position_ranked_by": second,
    }


def summarise_gameweek(frame: pd.DataFrame) -> dict[str, object]:
    """The record of one gameweek: each forecast present, and ours against the game's."""

    present = [name for name in FORECASTS if frame[name].notna().any()]
    record: dict[str, object] = {
        "players": len(frame),
        "forecasts": {name: summarise_forecast(frame, name) for name in present},
    }
    if "ours_decided" in present and "game" in present:
        record["ours_decided_minus_game"] = paired_difference(frame, "ours_decided", "game")
    return record


def pool(frames: Mapping[int, pd.DataFrame]) -> dict[str, object]:
    """The same reading over every audited gameweek together, with the count beside it."""

    if not frames:
        return {"gameweeks": []}
    stacked = pd.concat(
        [frame.assign(gameweek=gameweek) for gameweek, frame in sorted(frames.items())],
        ignore_index=True,
    )
    record = summarise_gameweek(stacked)
    return {"gameweeks": sorted(frames), "rests_on_gameweeks": len(frames), **record}
