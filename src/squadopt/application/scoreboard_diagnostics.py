"""Score frozen decisions without inventing missing decision-time information."""

import math
from collections.abc import Mapping
from numbers import Integral, Real
from typing import Any

import pandas as pd

from squadopt.data.errors import DataError
from squadopt.evaluation.models import FrozenSquadDecision
from squadopt.evaluation.scoring import score_frozen_squad_decision
from squadopt.live.ledger import score_named_eleven

ERROR_FIELDS = (
    "zero_minute_starters",
    "minutes_shortfall",
    "captain_shortfall",
    "autosub_recovery",
)


def empty_diagnostics() -> dict[str, float | None]:
    return dict.fromkeys(ERROR_FIELDS)


def _identities(values: object, count: int, label: str) -> list[int]:
    if (
        not isinstance(values, list | tuple)
        or len(values) != count
        or any(
            isinstance(value, bool) or not isinstance(value, Integral) or value <= 0
            for value in values
        )
    ):
        raise DataError(f"{label} needs {count} positive integer player IDs.")
    result = [int(value) for value in values]
    if len(set(result)) != count:
        raise DataError(f"{label} contains duplicate player IDs.")
    return result


def score_recorded_decision(
    decision: Mapping[str, Any],
    projections: pd.DataFrame,
    outcomes: pd.DataFrame,
) -> dict[str, object]:
    """Use the existing scorer; legacy unordered benches remain explicitly unscored.

    All identities are persistent player codes, as in the ledger. Missing minutes or
    projections are not zero. The minutes residual is summed over starters who played.
    A chip's additional captain copy is outside the ordinary captain diagnostic.
    """
    for table in (outcomes, projections):
        if table.columns.duplicated().any():
            raise DataError("Scoreboard tables cannot contain duplicate columns.")
        if "player_id" not in table or any(
            isinstance(value, bool) or not isinstance(value, Integral) or value <= 0
            for value in table["player_id"]
        ):
            raise DataError("Scoreboard tables require positive integer player IDs.")
    required = {"player_id", "minutes", "total_points"}
    if not required <= set(outcomes.columns) or outcomes["player_id"].duplicated().any():
        raise DataError("Scoreboard outcomes need unique player IDs, minutes and total_points.")
    if outcomes[["minutes", "total_points"]].map(lambda value: isinstance(value, bool)).any().any():
        raise DataError("Scoreboard outcomes cannot contain boolean numbers.")
    numeric = outcomes[["minutes", "total_points"]].apply(pd.to_numeric, errors="coerce")
    if not numeric.map(lambda value: math.isfinite(value)).all().all():
        raise DataError("Scoreboard outcomes must be finite and complete.")
    if (numeric["minutes"] < 0).any():
        raise DataError("Scoreboard minutes cannot be negative.")
    if (numeric["minutes"] % 1 != 0).any():
        raise DataError("Scoreboard minutes must be whole numbers.")
    outcomes = outcomes.assign(
        minutes=numeric["minutes"].astype(int), total_points=numeric["total_points"].astype(float)
    )
    actual = outcomes.set_index("player_id")
    starters = _identities(decision.get("starting_xi_player_ids"), 11, "Starting XI")
    squad = _identities(decision.get("squad_player_ids"), 15, "Squad")
    reserves = _identities(decision.get("bench_player_ids"), 4, "Bench")
    if set(starters) & set(reserves) or set(starters) | set(reserves) != set(squad):
        raise DataError("Starting XI and bench must partition the frozen squad.")
    if set(squad) - set(actual.index):
        raise DataError("Settled capture does not cover the frozen squad.")
    if "player_id" not in projections or projections["player_id"].duplicated().any():
        raise DataError("Frozen projections need unique player IDs.")
    projected = projections.set_index("player_id")
    captain = _identities([decision.get("captain_player_id")], 1, "Captain")[0]
    if captain not in starters:
        raise DataError("Frozen captain must belong to the starting XI.")
    points = {int(str(player)): float(value) for player, value in actual["total_points"].items()}
    diagnostics = empty_diagnostics()
    diagnostics["zero_minute_starters"] = int((actual.loc[starters, "minutes"] == 0).sum())
    playing = [player for player in starters if float(str(actual.at[player, "minutes"])) > 0]
    if "expected_minutes" in projected and set(playing) <= set(projected.index):
        minutes = pd.to_numeric(projected.loc[playing, "expected_minutes"], errors="coerce")
        if minutes.map(math.isfinite).all() and (minutes >= 0).all():
            diagnostics["minutes_shortfall"] = float(
                (minutes - actual.loc[playing, "minutes"]).sum()
            )
    if (
        "expected_points" in projected
        and captain in projected.index
        and pd.notna(projected.at[captain, "expected_points"])
    ):
        expected = pd.to_numeric(projected.at[captain, "expected_points"], errors="coerce")
        if math.isfinite(expected):
            diagnostics["captain_shortfall"] = expected - points[captain]
    transfers = decision.get("transfers")
    if transfers is None:
        transfers = {}
    if not isinstance(transfers, Mapping):
        raise DataError("Frozen transfers must be a mapping.")
    hits = transfers.get("transfer_hit_points", 0.0)
    if isinstance(hits, bool) or not isinstance(hits, Real) or not math.isfinite(hits) or hits < 0:
        raise DataError("Frozen hit charges must be finite non-negative numbers.")
    chip = transfers.get("chip")
    if chip not in (None, "3xc", "bboost", "freehit", "wildcard"):
        raise DataError("Frozen decision names an unsupported chip.")
    gross = score_named_eleven(decision, points)
    basis = "named_eleven_no_autosubs"
    vice = decision.get("vice_captain_player_id")
    bench = decision.get("ordered_bench_player_ids")
    if vice is not None and bench is not None:
        bench = _identities(bench, 4, "Ordered bench")
        vice = _identities([vice], 1, "Vice captain")[0]
        if set(bench) != set(reserves) or vice not in starters or vice == captain:
            raise DataError("Frozen bench order and vice captain disagree with the lineup.")
        frozen = FrozenSquadDecision(
            squad=projections.loc[projections["player_id"].isin(squad)],
            starting_xi=tuple(starters),
            bench=tuple(bench),
            captain_id=captain,
            vice_captain_id=int(vice),
        )
        score = score_frozen_squad_decision(frozen, outcomes)
        gross = score.total_points
        diagnostics["captain_shortfall"] = (
            None
            if diagnostics["captain_shortfall"] is None
            else float(str(projected.at[captain, "expected_points"])) - score.captain_bonus_points
        )
        diagnostics["autosub_recovery"] = score.autosub_points
        if chip == "3xc":
            gross += score.captain_bonus_points
        elif chip == "bboost":
            gross = sum(points[player] for player in squad) + score.captain_bonus_points
            diagnostics["autosub_recovery"] = 0.0
        basis = "official_autosub_captain_v2"
    return {
        "net": gross - hits,
        "xi": gross,
        "scoring_basis": basis,
        "diagnostics": diagnostics,
    }
