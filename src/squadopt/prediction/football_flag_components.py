"""Pure fixture scoring for a learned whole-week flag/minute law.

The full club shares close before a member squad is selected. Learned weekly
participation replaces the old captured multiplier, rather than multiplying it.
"""

from __future__ import annotations

import itertools
import math
import re
from collections.abc import Collection, Mapping, Sequence
from numbers import Real
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import nbinom

from squadopt.features.football_flag_inputs import MinuteFixture, input_digest, validate_week_input
from squadopt.prediction.football import JOINT_ROLE_FLAG_MODEL_VERSION
from squadopt.prediction.football_flag_minutes import (
    FEATURE_VERSION as FLAG_FEATURE_VERSION,
)
from squadopt.prediction.football_flag_minutes import (
    MODEL_VERSION as FLAG_HEAD_VERSION,
)
from squadopt.prediction.football_flag_minutes import (
    WeekMinutePrediction,
)

GOAL_POINTS = {"GK": 6, "DEF": 6, "MID": 5, "FWD": 4}
CS_POINTS = {"GK": 4, "DEF": 4, "MID": 1, "FWD": 0}
LIVE_FLAG_CONTRACT = "football_first_week_flags_v1"
FLAG_SCOPE_LIMITATION = (
    "Learned categorical flags replace eligibility only in the first week; "
    "later weeks retain the captured rule. Independent calibration is unverified."
)


def native_flag_supports(
    components: pd.DataFrame, players: Collection[int]
) -> dict[int, tuple[MinuteFixture, ...]]:
    """Preserve each captured player's original seven-state support, including blanks."""
    return {
        player: tuple(
            MinuteFixture(
                int(row["fixture"]),
                pd.Timestamp(row["kickoff"]).isoformat(),
                int(row["club"]),
                int(row["opponent"]),
                int(row["home"]),
                (
                    float(row["zero_probability"]),
                    *(
                        float(row[f"{role}_minute_probability_{b}"])
                        for role in ("start", "cameo")
                        for b in (1, 2, 3)
                    ),
                ),
                (
                    0.0,
                    *(
                        float(row[f"{role}_minute_value_{b}"])
                        for role in ("start", "cameo")
                        for b in (1, 2, 3)
                    ),
                ),
            )
            for row in components.loc[components.player_code.eq(player)]
            .sort_values(["kickoff", "fixture"])
            .to_dict("records")
        )
        for player in players
    }


def _finite(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value):
        raise ValueError(f"{label} requires a finite real number.")
    return float(value)


def flag_fixture_components(
    row: Mapping[str, object],
    prediction: WeekMinutePrediction,
    fixture_index: int,
    season: str,
    *,
    model_version: str,
) -> dict[str, object]:
    fixture = prediction.week.fixtures[fixture_index]
    p = np.asarray(prediction.fixture_probabilities[fixture_index], dtype=float)
    m = np.asarray(fixture.minutes, dtype=float)
    q = float(p[1:].sum())
    expected = float(p @ m)
    bins = np.array([0, 1, 2, 3, 1, 2, 3])
    p60 = float(p[bins >= 2].sum())
    cs = float(
        np.sum(
            p[bins >= 2]
            * np.exp(-_finite(row["opponent_goal_rate"], "opposing intensity") * m[bins >= 2] / 90)
        )
    )
    position = str(row["position"])
    threshold = 10 if position == "DEF" else 12
    rate = _finite(row["defcon_rate90"], "defensive count rate")
    dispersion = _finite(row["defcon_dispersion"], "defensive dispersion")
    means = rate * m[1:] / 90
    dc = (
        0.0
        if position == "GK"
        else float(
            np.sum(p[1:] * nbinom.sf(threshold - 1, dispersion, dispersion / (dispersion + means)))
        )
    )
    if not all(math.isfinite(v) for v in (q, expected, p60, cs, dc)):
        raise ValueError("Learned minute scoring exceeded finite support.")
    result: dict[str, object] = dict(row)
    result.update(
        expected_minutes=expected,
        appearance_probability=q,
        p60=p60,
        clean_sheet_probability=cs,
        defcon_probability=dc,
        zero_probability=float(p[0]),
        start_probability=float(p[1:4].sum()),
        cameo_probability=float(p[4:].sum()),
        unknown_role_probability=0.0,
        expected_minutes_if_appearance=expected / q if q else 0.0,
        model_version=model_version,
        availability_multiplier=1.0,
    )
    for role, offset in (("start", 0), ("cameo", 3)):
        for b in (1, 2, 3):
            result[f"{role}_minute_probability_{b}"] = float(p[offset + b])
            result[f"{role}_minute_value_{b}"] = float(m[offset + b])
    for b in range(4):
        mask = bins == b
        mass = float(p[mask].sum())
        representative = float(np.sum(p[mask] * m[mask]) / mass) if mass else (0, 30, 75, 90)[b]
        lower, upper = (
            (0, 0),
            (np.nextafter(0.0, 1.0), np.nextafter(60.0, 0.0)),
            (60, np.nextafter(90.0, 0.0)),
            (90, 120),
        )[b]
        result[f"minute_probability_{b}"] = mass
        result[f"minute_value_{b}"] = float(np.clip(representative, lower, upper))
    result["flag_minute_model_sha256"] = prediction.model_sha256
    result["flag_input_sha256"] = prediction.input_sha256
    result["flag_weekly_appearance"] = prediction.weekly_appearance
    result["flag_eligibility_application"] = "replaced_by_learned_whole_week_law"
    # Points are recomputed after complete-club allocation below.
    result["flag_defcon_active"] = int(season[:4]) >= 2025
    result["flag_goal_coefficient"] = (
        10 if position == "GK" and season >= "2024-25" else GOAL_POINTS[position]
    )
    return result


def allocate_flag_components(native: pd.DataFrame, updated: pd.DataFrame) -> pd.DataFrame:
    output = updated.copy(deep=True)
    originals = native.set_index(["fixture", "player_code"])
    for (fixture, _), group in output.groupby(["fixture", "club"], sort=True):
        indices = group.index
        old = originals.loc[[(fixture, int(p)) for p in group.player_code]]
        old_minutes = old.expected_minutes.to_numpy(float)
        new_minutes = group.expected_minutes.to_numpy(float)
        if ((old_minutes == 0) & (new_minutes > 0)).any():
            raise ValueError("Native zero minute support cannot allocate a new positive recipient.")
        ratio = np.divide(
            new_minutes, old_minutes, out=np.zeros_like(new_minutes), where=old_minutes > 0
        )
        for count, share in (("goals", "goals_share"), ("assists", "assists_share")):
            total = math.fsum(old[count].to_numpy(float))
            old_share = old[share].to_numpy(float)
            if total > 0 and not math.isclose(
                math.fsum(old_share), 1.0, rel_tol=1e-12, abs_tol=1e-12
            ):
                raise ValueError("Native positive attacking mass lacks a full-club share basis.")
            if not np.allclose(
                old[count].to_numpy(float), total * old_share, rtol=1e-12, atol=1e-12
            ):
                raise ValueError("Native attacking counts disagree with their club share basis.")
            weights = old_share * ratio
            mass = math.fsum(weights)
            if total > 0 and mass <= 0:
                raise ValueError("A positive native club total has no learned minute support.")
            shares = weights / mass if mass > 0 else np.zeros_like(weights)
            output.loc[indices, share] = shares
            output.loc[indices, count] = total * shares
    if (
        output.goals.to_numpy(float) + output.assists.to_numpy(float)
        > output.team_goal_rate.to_numpy(float) + 1e-12
    ).any():
        raise ValueError(
            "A player cannot receive scorer and assist credit on the same physical goal."
        )
    q = output.appearance_probability.to_numpy(float)
    p60 = output.p60.to_numpy(float)
    raw = (
        q
        + p60
        + output.flag_goal_coefficient.to_numpy(float) * output.goals.to_numpy(float)
        + 3 * output.assists.to_numpy(float)
        + output.position.map(CS_POINTS).to_numpy(float)
        * output.clean_sheet_probability.to_numpy(float)
        + 2 * output.flag_defcon_active.to_numpy(float) * output.defcon_probability.to_numpy(float)
        + q * output.residual_if_appearance.to_numpy(float)
    )
    if not np.isfinite(raw).all():
        raise ValueError("Learned fixture points exceeded finite support.")
    output["raw_expected_points"] = raw
    output["expected_points"] = np.maximum(raw, 0)
    return output


def apply_flag_predictions(
    native: pd.DataFrame,
    predictions: Sequence[WeekMinutePrediction],
    *,
    season: str,
    gameweek: int,
    players: Collection[int],
) -> tuple[pd.DataFrame, list[dict[str, object]]]:
    """Bind the complete first-week roster to one learned law per player."""
    if len(predictions) != len(players) or {p.week.player_code for p in predictions} != set(
        players
    ):
        raise ValueError("Learned laws must cover the exact captured roster once.")
    if not native.GW.eq(gameweek).all():
        raise ValueError("Flag replacement is scoped to the first gameweek only.")
    originals = {
        (int(row["fixture"]), int(row["player_code"])): {
            str(key): value for key, value in row.items()
        }
        for row in native.to_dict("records")
    }
    if len(originals) != len(native):
        raise ValueError("Duplicate native player-fixture.")
    updates = {}
    laws = []
    for prediction in predictions:
        week = prediction.week
        validate_week_input(week)
        if (
            week.season != season
            or week.gameweek != gameweek
            or prediction.input_sha256 != input_digest(week)
        ):
            raise ValueError("Flag law input differs from its retained target.")
        states = tuple(itertools.product(range(7), repeat=len(week.fixtures)))
        probabilities = np.asarray(prediction.probabilities, dtype=float)
        if (
            prediction.states != states
            or probabilities.shape != (len(states),)
            or not np.isfinite(probabilities).all()
            or (probabilities < 0).any()
            or not math.isclose(math.fsum(probabilities), 1.0, abs_tol=1e-12, rel_tol=0)
        ):
            raise ValueError("Invalid learned whole-week state distribution.")
        if not math.isclose(
            math.fsum(probabilities[1:]), prediction.weekly_appearance, abs_tol=1e-12, rel_tol=0
        ):
            raise ValueError("Learned weekly appearance differs from the joint state law.")
        if len(prediction.fixture_probabilities) != len(week.fixtures):
            raise ValueError("Incomplete learned fixture marginals.")
        for index, fixture in enumerate(week.fixtures):
            marginal = [
                math.fsum(
                    p
                    for state, p in zip(states, probabilities, strict=True)
                    if state[index] == cell
                )
                for cell in range(7)
            ]
            if not np.allclose(
                marginal, prediction.fixture_probabilities[index], atol=1e-12, rtol=0
            ):
                raise ValueError("Fixture marginal differs from the learned whole-week law.")
            key = fixture.fixture, week.player_code
            if key not in originals:
                raise ValueError("Flag law names an unknown native player-fixture.")
            row = originals[key]
            original_p = (
                row["zero_probability"],
                *(
                    row[f"{role}_minute_probability_{b}"]
                    for role in ("start", "cameo")
                    for b in (1, 2, 3)
                ),
            )
            original_m = (
                0.0,
                *(
                    row[f"{role}_minute_value_{b}"]
                    for role in ("start", "cameo")
                    for b in (1, 2, 3)
                ),
            )
            if (
                original_p != fixture.probabilities
                or original_m != fixture.minutes
                or row["minute_role_status"] != "fitted_known_start_labels"
            ):
                raise ValueError("Flag law changed its original native minute support.")
            updates[key] = flag_fixture_components(
                row, prediction, index, season, model_version=JOINT_ROLE_FLAG_MODEL_VERSION
            )
        laws.append(
            {
                "player_code": week.player_code,
                "fixture_ids": [fixture.fixture for fixture in week.fixtures],
                "probabilities": [float(value) for value in prediction.probabilities],
                "appearance_probability": float(prediction.weekly_appearance),
                "model_sha256": prediction.model_sha256,
                "input_sha256": prediction.input_sha256,
            }
        )
    if set(updates) != set(originals):
        raise ValueError("Flag laws lack complete native fixture coverage.")
    if native.empty:
        return native.copy(deep=True), laws
    updated = pd.DataFrame(
        [updates[key] for key in originals],
        index=native.index,
    )
    return allocate_flag_components(native, updated), laws


def flag_weekly_chances(
    document: Mapping[str, Any], *, components: pd.DataFrame | None = None
) -> dict[int, float] | None:
    """Validate serialized first-week laws and, when supplied, all role marginals."""
    try:
        return _flag_weekly_chances(document, components=components)
    except (KeyError, TypeError, AttributeError, IndexError) as error:
        raise ValueError("Malformed retained flag metadata or weekly law.") from error


def _flag_weekly_chances(
    document: Mapping[str, Any], *, components: pd.DataFrame | None = None
) -> dict[int, float] | None:
    if document.get("model_version") != JOINT_ROLE_FLAG_MODEL_VERSION:
        return None
    metadata = document.get("flag_metadata")
    if (
        not isinstance(metadata, dict)
        or metadata.get("contract_version") != LIVE_FLAG_CONTRACT
        or metadata.get("gameweek") != document.get("gameweek")
        or metadata.get("head_version") != FLAG_HEAD_VERSION
        or metadata.get("feature_version") != FLAG_FEATURE_VERSION
    ):
        raise ValueError("Learned flag forecast requires its exact scope and metadata.")
    for field in (
        "model_sha256",
        "native_forecast_fingerprint",
        "native_components_fingerprint",
        "training_receipts_sha256",
    ):
        if (
            not isinstance(metadata.get(field), str)
            or re.fullmatch(r"[0-9a-f]{64}", metadata[field]) is None
        ):
            raise ValueError("Learned flag metadata lacks a valid fitted/native fingerprint.")
    cutoff = pd.Timestamp(document["captured_at_utc"])
    decision, deadline = (
        pd.Timestamp(metadata["decision_at"]),
        pd.Timestamp(metadata["deadline_at"]),
    )
    if (
        any(pd.isna(clock) or clock.tzinfo is None for clock in (cutoff, decision, deadline))
        or not cutoff < decision < deadline
        or metadata.get("fit_cutoff") != document["captured_at_utc"]
    ):
        raise ValueError("Learned flag information and decision clocks differ.")
    if (
        type(metadata.get("training_rows")) is not int
        or metadata["training_rows"] <= 0
        or metadata.get("later_weeks") != "legacy_captured_rule"
    ):
        raise ValueError("Learned flag forecast lacks its fitted population and horizon policy.")
    seasons = metadata.get("training_seasons")
    native_seasons = metadata.get("native_training_seasons")
    permitted = ["2022-23", "2023-24", "2024-25", document["season"]]
    if native_seasons not in (
        permitted,
        sorted([*permitted, "2025-26"]),
    ) or native_seasons != document.get("training_selection", {}).get("allowed_seasons"):
        raise ValueError(
            "Learned flag native training population differs from its explicit selection."
        )
    weeks = metadata.get("training_gameweeks")
    if (
        not isinstance(seasons, list)
        or not seasons
        or any(
            not isinstance(season, str) or season == "2025-26" or season > document["season"]
            for season in seasons
        )
    ):
        raise ValueError("Learned flag training seasons include protected or future information.")
    if (
        not isinstance(weeks, list)
        or any(type(week) is not int or not 1 <= week < document["gameweek"] for week in weeks)
        or weeks != sorted(set(weeks))
    ):
        raise ValueError("Learned flag training gameweeks include target or future information.")
    first = {
        row["player_id"]: row for row in document["rows"] if row["gameweek"] == document["gameweek"]
    }
    chances = {}
    laws = metadata.get("weekly_laws")
    if not isinstance(laws, list) or len(laws) != len(first):
        raise ValueError("Learned weekly laws must cover the full captured first-week roster.")
    for law in laws:
        player = law["player_code"]
        fixtures, probabilities = law["fixture_ids"], law["probabilities"]
        if (
            type(player) is not int
            or player in chances
            or player not in first
            or not isinstance(fixtures, list)
            or len(fixtures) > 3
            or len(set(fixtures)) != len(fixtures)
            or any(type(f) is not int or f <= 0 for f in fixtures)
        ):
            raise ValueError("Duplicate or unknown learned law identity.")
        if (
            first[player]["fixture_count"] != len(fixtures)
            or law.get("model_sha256") != metadata["model_sha256"]
            or re.fullmatch(r"[0-9a-f]{64}", str(law.get("input_sha256"))) is None
        ):
            raise ValueError("Learned law differs from its forecast scope or fitted model.")
        if (
            not isinstance(probabilities, list)
            or len(probabilities) != 7 ** len(fixtures)
            or any(
                type(p) not in (int, float) or not math.isfinite(p) or p < 0 for p in probabilities
            )
            or not math.isclose(math.fsum(probabilities), 1.0, abs_tol=1e-12, rel_tol=0)
        ):
            raise ValueError("Malformed learned joint week law.")
        chance = math.fsum(probabilities[1:])
        if not math.isclose(
            chance, float(law["appearance_probability"]), abs_tol=1e-12, rel_tol=0
        ) or not math.isclose(
            chance, float(first[player]["appearance_probability"]), abs_tol=1e-12, rel_tol=0
        ):
            raise ValueError("Served appearance differs from the learned joint law.")
        if components is not None:
            rows = components.loc[
                components.GW.eq(document["gameweek"]) & components.player_code.eq(player)
            ].sort_values(["kickoff", "fixture"])
            if rows.fixture.tolist() != fixtures:
                raise ValueError("Learned law lacks the original complete player-fixture scope.")
            states = tuple(itertools.product(range(7), repeat=len(fixtures)))
            for index, row in enumerate(rows.to_dict("records")):
                marginal = [
                    math.fsum(
                        p
                        for state, p in zip(states, probabilities, strict=True)
                        if state[index] == cell
                    )
                    for cell in range(7)
                ]
                actual = [
                    row["zero_probability"],
                    *(
                        row[f"{role}_minute_probability_{b}"]
                        for role in ("start", "cameo")
                        for b in (1, 2, 3)
                    ),
                ]
                if not np.allclose(actual, marginal, atol=1e-12, rtol=0):
                    raise ValueError("Fixture minute marginals differ from the learned joint law.")
        chances[player] = chance
    return chances
