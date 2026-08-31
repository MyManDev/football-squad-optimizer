"""Exact score-component attribution for a fixed selected XI."""

import re
from collections.abc import Mapping, Sequence
from typing import Final, cast

import numpy as np
import pandas as pd

from squadopt.experiments.shadow_calibration import (
    BOOTSTRAP_SEED,
    CONFIDENCE_LEVEL,
    bootstrap_interval,
)
from squadopt.experiments.shadow_squad_calibration import (
    BOOTSTRAP_RESAMPLES,
    MIN_EVALUATION_FOLDS,
    _require,
)
from squadopt.experiments.tail_diagnostic import S1_PIT_BOUNDS, S2_TAIL_BOUNDS

CONTRACT_VERSION: Final = "phase2_component_attribution_v1"
COMPONENTS: Final = ("appearance", "attacking", "defensive", "bonus", "negative")
CONTROL: Final = "control"
MIN_PLAYER_HISTORY: Final = 8
IDENTITY_TOLERANCE: Final = 1e-9

SHARED_COMPONENT_FAILURE: Final = "shared_component_failure"
COMPONENT_NOT_LOCALIZED: Final = "component_not_localized"
INCONCLUSIVE: Final = "diagnostic_inconclusive"

_GOAL_WEIGHTS: Final = {"GK": 6, "DEF": 6, "MID": 5, "FWD": 4}
_CLEAN_SHEET_WEIGHTS: Final = {"GK": 4, "DEF": 4, "MID": 1, "FWD": 0}
_RAW_COLUMNS: Final = {
    "position",
    "minutes",
    "total_points",
    "goals_scored",
    "assists",
    "clean_sheets",
    "goals_conceded",
    "saves",
    "bonus",
    "yellow_cards",
    "red_cards",
    "own_goals",
    "penalties_missed",
    "penalties_saved",
}
_FOLD_PATTERN: Final = re.compile(r"^(\d{4})-\d{2}-gw(\d{2})$")


def _fold_order(fold_id: str) -> tuple[int, int]:
    match = _FOLD_PATTERN.fullmatch(fold_id)
    _require(match is not None, f"invalid chronological fold id {fold_id!r}.")
    assert match is not None
    return int(match.group(1)), int(match.group(2))


def score_fixture_components(frame: pd.DataFrame) -> pd.DataFrame:
    """Return a copy with the five exact FPL score components attached."""

    _require(isinstance(frame, pd.DataFrame), "fixture outcomes must be a DataFrame.")
    missing = sorted(_RAW_COLUMNS - set(frame.columns))
    _require(not missing, f"fixture outcomes are missing columns {missing!r}.")
    result = frame.copy(deep=True)
    result["position"] = result["position"].astype(str).str.strip().str.upper().replace("GKP", "GK")
    _require(
        bool(result["position"].isin(_GOAL_WEIGHTS).all()),
        "fixture outcomes contain an unsupported position.",
    )
    numeric = sorted(_RAW_COLUMNS - {"position"})
    for column in numeric:
        values = pd.to_numeric(result[column], errors="coerce").to_numpy(dtype="float64")
        _require(
            bool(np.isfinite(values).all()) and bool(np.equal(values, np.floor(values)).all()),
            f"fixture outcome {column!r} must contain finite integers.",
        )
        result[column] = values.astype("int64")
    non_negative = set(numeric) - {"total_points"}
    _require(
        all(bool((result[column].astype("int64") >= 0).all()) for column in non_negative),
        "fixture event counts and minutes must be non-negative.",
    )

    positions = result["position"]
    minutes = result["minutes"].astype("int64")
    result["appearance"] = (minutes > 0).astype("int64") + (minutes >= 60).astype("int64")
    result["attacking"] = positions.map(_GOAL_WEIGHTS).astype("int64") * result[
        "goals_scored"
    ].astype("int64") + 3 * result["assists"].astype("int64")
    result["defensive"] = (
        positions.map(_CLEAN_SHEET_WEIGHTS).astype("int64") * result["clean_sheets"].astype("int64")
        + result["saves"].astype("int64").floordiv(3)
        + 5 * result["penalties_saved"].astype("int64")
        - positions.isin({"GK", "DEF"}).astype("int64")
        * result["goals_conceded"].astype("int64").floordiv(2)
    )
    result["bonus"] = result["bonus"].astype("int64")
    result["negative"] = -(
        result["yellow_cards"].astype("int64")
        + 3 * result["red_cards"].astype("int64")
        + 2 * result["own_goals"].astype("int64")
        + 2 * result["penalties_missed"].astype("int64")
    )
    reconstructed = result.loc[:, list(COMPONENTS)].sum(axis=1).astype("int64")
    _require(
        bool(reconstructed.eq(result["total_points"].astype("int64")).all()),
        "fixture score components do not reconstruct total_points exactly.",
    )
    return result


def aggregate_player_gameweeks(frame: pd.DataFrame) -> pd.DataFrame:
    """Aggregate already-scored fixture rows to player-gameweek grain."""

    keys = ["season", "gameweek", "fold_id", "player_id"]
    required = {*keys, "fixture_id", "position", "minutes", "total_points", *COMPONENTS}
    missing = sorted(required - set(frame.columns))
    _require(not missing, f"scored fixtures are missing columns {missing!r}.")
    _require(
        not bool(frame.duplicated(["season", "gameweek", "fixture_id", "player_id"]).any()),
        "scored fixtures repeat a player-fixture identity.",
    )
    position_counts = frame.groupby(keys, sort=False)["position"].nunique(dropna=False)
    _require(bool(position_counts.eq(1).all()), "a player changes position within a gameweek.")
    grouped = frame.groupby(keys, sort=True, as_index=False)
    totals = grouped[["minutes", "total_points", *COMPONENTS]].sum()
    positions = grouped["position"].first()
    fixture_counts = grouped.size().rename(columns={"size": "fixture_count"})
    result = totals.merge(positions, on=keys, validate="one_to_one").merge(
        fixture_counts, on=keys, validate="one_to_one"
    )
    _require(
        bool(result.loc[:, list(COMPONENTS)].sum(axis=1).eq(result["total_points"]).all()),
        "player-gameweek components do not reconstruct total_points exactly.",
    )
    return result.sort_values(["season", "gameweek", "player_id"], kind="stable").reset_index(
        drop=True
    )


def _history_pool(
    history: pd.DataFrame, *, player_id: object, position: str
) -> tuple[pd.DataFrame, str]:
    player = history.loc[
        (history["player_id"] == player_id) & history["position"].astype(str).eq(position)
    ]
    if len(player) >= MIN_PLAYER_HISTORY:
        return player, "player_position"
    position_rows = history.loc[history["position"].astype(str).eq(position)]
    if not position_rows.empty:
        return position_rows, "position"
    _require(not history.empty, "component history is empty.")
    return history, "pooled"


def attribute_fold(
    starters: pd.DataFrame,
    target_components: pd.DataFrame,
    history_components: pd.DataFrame,
    history_fold_ids: Sequence[str],
    scenario_scores: Sequence[float],
    *,
    shift_points: float,
    lower_quantile: float,
) -> tuple[pd.DataFrame, dict[str, object]]:
    """Read control and five component-normalized arms for one fixed XI."""

    starter_required = {"fold_id", "season", "player_id", "position", "expected_points", "weight"}
    component_required = {
        "fold_id",
        "player_id",
        "position",
        "minutes",
        "total_points",
        *COMPONENTS,
    }
    _require(starter_required.issubset(starters.columns), "starter rows are incomplete.")
    _require(
        component_required.issubset(target_components.columns), "target components are incomplete."
    )
    _require(
        component_required.issubset(history_components.columns), "component history is incomplete."
    )
    _require(
        len(starters) == 11 and starters["player_id"].is_unique, "a fold needs 11 unique starters."
    )
    weights = pd.to_numeric(starters["weight"], errors="coerce")
    _require(
        int(weights.eq(2).sum()) == 1 and int(weights.eq(1).sum()) == 10,
        "starter weights must name one captain and ten other starters.",
    )
    target_folds = {str(value) for value in starters["fold_id"]}
    _require(len(target_folds) == 1, "starter rows must belong to one fold.")
    target_fold = next(iter(target_folds))
    target_season = str(starters["season"].iloc[0])
    _require(
        bool(starters["season"].astype(str).eq(target_season).all()),
        "starter rows must belong to one season.",
    )
    allowed = tuple(str(value) for value in history_fold_ids)
    _require(
        len(allowed) == len(set(allowed)) and bool(allowed),
        "history fold ids must be unique and non-empty.",
    )
    _require(target_folds.isdisjoint(allowed), "the target fold cannot enter component history.")
    _require(
        all(_fold_order(fold_id) < _fold_order(target_fold) for fold_id in allowed),
        "component history contains a target or future fold.",
    )
    history = history_components.loc[history_components["fold_id"].astype(str).isin(set(allowed))]
    _require(
        {str(value) for value in history["fold_id"]} == set(allowed),
        "component history is missing a declared fold.",
    )
    _require(
        set(target_components["fold_id"].astype(str)) == {target_fold}
        and set(target_components["season"].astype(str)) == {target_season},
        "target components do not belong to the starter fold and season.",
    )
    targets = target_components.loc[target_components["player_id"].isin(set(starters["player_id"]))]
    _require(
        targets["player_id"].is_unique and set(targets["player_id"]) == set(starters["player_id"]),
        "target components must cover every starter exactly once.",
    )
    joined = starters.merge(
        targets.loc[:, ["player_id", "position", "minutes", "total_points", *COMPONENTS]],
        on="player_id",
        how="left",
        suffixes=("", "_outcome"),
        validate="one_to_one",
    )
    _require(
        bool(joined["position"].astype(str).eq(joined["position_outcome"].astype(str)).all()),
        "starter and component positions disagree.",
    )
    scores = np.asarray(tuple(scenario_scores), dtype="float64")
    _require(
        bool(len(scores)) and bool(np.isfinite(scores).all()),
        "scenario scores must be finite and non-empty.",
    )
    _require(np.isfinite(shift_points), "shift_points must be finite.")
    _require(0.0 < lower_quantile < 1.0, "lower_quantile must be strictly between zero and one.")

    surprises = {component: 0.0 for component in COMPONENTS}
    baseline_total = 0.0
    projection_total = 0.0
    source_counts: dict[str, int] = {}
    player_rows = 0
    for row in joined.itertuples(index=False):
        pool, source = _history_pool(history, player_id=row.player_id, position=str(row.position))
        source_counts[source] = source_counts.get(source, 0) + 1
        player_rows += int(source == "player_position")
        weight = float(cast(float, row.weight))
        projection_total += weight * float(cast(float, row.expected_points))
        for component in COMPONENTS:
            baseline = float(pool[component].astype("float64").mean())
            baseline_total += weight * baseline
            surprises[component] += weight * (float(getattr(row, component)) - baseline)

    realized_score = float((joined["weight"] * joined["total_points"]).sum())
    component_score = float(
        sum((joined["weight"] * joined[component]).sum() for component in COMPONENTS)
    )
    raw_mean = float(scores.mean() - shift_points)
    location_gap = baseline_total - projection_total
    scenario_gap = projection_total - raw_mean
    identity_right = sum(surprises.values()) + location_gap + scenario_gap - shift_points
    identity_left = realized_score - float(scores.mean())
    _require(
        abs(component_score - realized_score) <= IDENTITY_TOLERANCE,
        "weighted components do not reproduce realized score.",
    )
    _require(
        abs(identity_left - identity_right) <= IDENTITY_TOLERANCE,
        "component attribution identity does not close.",
    )

    lower = float(np.quantile(scores, lower_quantile, method="linear"))
    rows: list[dict[str, object]] = []
    for arm in (CONTROL, *COMPONENTS):
        arm_realized = realized_score if arm == CONTROL else realized_score - surprises[arm]
        rows.append(
            {
                "fold_id": str(joined["fold_id"].iloc[0]),
                "season": str(joined["season"].iloc[0]),
                "arm": arm,
                "realized_score": arm_realized,
                "scenario_mean_score": float(scores.mean()),
                "lower_quantile_score": lower,
                "probability_integral_transform": float((scores <= arm_realized).mean()),
                "below_lower_quantile": bool(arm_realized < lower),
            }
        )
    minutes = joined["minutes"].astype("float64")
    diagnostics: dict[str, object] = {
        "component_surprises": surprises,
        "historical_baseline_total": baseline_total,
        "projection_total": projection_total,
        "raw_scenario_mean": raw_mean,
        "location_gap": location_gap,
        "scenario_gap": scenario_gap,
        "identity_error": identity_left - identity_right,
        "component_score_error": component_score - realized_score,
        "source_counts": source_counts,
        "player_source_coverage": player_rows / len(joined),
        "weighted_minutes": float((joined["weight"] * minutes).sum()),
        "zero_minute_starters": int(minutes.eq(0).sum()),
        "partial_appearance_starters": int(minutes.between(1, 59).sum()),
        "completed_appearance_starters": int(minutes.ge(60).sum()),
    }
    return pd.DataFrame(rows), diagnostics


def _interval(values: Sequence[float]) -> dict[str, float]:
    _require(bool(values), "a component contrast has no folds.")
    low, high = bootstrap_interval(
        values,
        resamples=BOOTSTRAP_RESAMPLES,
        seed=BOOTSTRAP_SEED,
        confidence_level=CONFIDENCE_LEVEL,
    )
    return {"mean": float(np.mean(values)), "bootstrap_low": low, "bootstrap_high": high}


def _contrast_interval(values: pd.Series, tail: pd.Series) -> dict[str, float]:
    """Bootstrap the difference between tail and non-tail fold means."""

    numbers = values.to_numpy(dtype="float64")
    groups = tail.to_numpy(dtype="bool")
    _require(bool(groups.any()) and bool((~groups).any()), "a contrast needs both groups.")
    generator = np.random.default_rng(BOOTSTRAP_SEED)
    draws = generator.integers(0, len(numbers), size=(BOOTSTRAP_RESAMPLES, len(numbers)))
    contrasts: list[float] = []
    for draw in draws:
        sampled_groups = groups[draw]
        if bool(sampled_groups.any()) and bool((~sampled_groups).any()):
            sampled = numbers[draw]
            contrasts.append(
                float(sampled[sampled_groups].mean() - sampled[~sampled_groups].mean())
            )
    _require(bool(contrasts), "the component contrast bootstrap produced no valid draws.")
    alpha = (1.0 - CONFIDENCE_LEVEL) / 2.0
    low, high = np.quantile(np.asarray(contrasts), [alpha, 1.0 - alpha])
    return {
        "mean": float(numbers[groups].mean() - numbers[~groups].mean()),
        "bootstrap_low": float(low),
        "bootstrap_high": float(high),
    }


def summarise(readings: pd.DataFrame, diagnostics: pd.DataFrame) -> dict[str, object]:
    """Summarise one declared season without selecting a best point estimate."""

    _require(not readings.empty and not diagnostics.empty, "component attribution has no rows.")
    arms: dict[str, object] = {}
    for arm_name in (CONTROL, *COMPONENTS):
        selected = readings.loc[readings["arm"].eq(arm_name)]
        _require(not selected.empty, f"component arm {arm_name!r} is absent.")
        arms[arm_name] = {
            "fold_count": int(selected["fold_id"].nunique()),
            "mean_probability_integral_transform": float(
                selected["probability_integral_transform"].mean()
            ),
            "below_lower_quantile_folds": int(selected["below_lower_quantile"].sum()),
            "below_lower_quantile_rate": float(selected["below_lower_quantile"].mean()),
            "mean_realized_score": float(selected["realized_score"].mean()),
            "mean_scenario_score": float(selected["scenario_mean_score"].mean()),
        }
    control = readings.loc[readings["arm"].eq(CONTROL)].set_index("fold_id").sort_index()
    components: dict[str, object] = {}
    for component in COMPONENTS:
        arm_rows = readings.loc[readings["arm"].eq(component)].set_index("fold_id").sort_index()
        diag = diagnostics.set_index("fold_id").sort_index()
        _require(
            control.index.equals(arm_rows.index) and control.index.equals(diag.index),
            "component folds are not paired.",
        )
        surprise = diag[f"surprise_{component}"].astype("float64")
        tail = control["below_lower_quantile"].astype(bool)
        reduction = control["below_lower_quantile"].astype("float64") - arm_rows[
            "below_lower_quantile"
        ].astype("float64")
        components[component] = {
            "mean_surprise": float(surprise.mean()),
            "tail_minus_other_surprise": _contrast_interval(surprise, tail),
            "q10_failure_reduction": _interval([float(value) for value in reduction]),
        }
    source_counts = {"player_position": 0, "position": 0, "pooled": 0}
    for value in diagnostics["source_counts"]:
        _require(isinstance(value, Mapping), "source counts must be mappings.")
        for source in source_counts:
            source_counts[source] += int(cast(Mapping[str, int], value).get(source, 0))
    return {
        "arms": arms,
        "components": components,
        "source_counts": source_counts,
        "mean_player_source_coverage": float(diagnostics["player_source_coverage"].mean()),
        "maximum_absolute_identity_error": float(diagnostics["identity_error"].abs().max()),
        "maximum_absolute_component_score_error": float(
            diagnostics["component_score_error"].abs().max()
        ),
        "minutes": {
            "mean_weighted_minutes": float(diagnostics["weighted_minutes"].mean()),
            "zero_minute_starters": int(diagnostics["zero_minute_starters"].sum()),
            "partial_appearance_starters": int(diagnostics["partial_appearance_starters"].sum()),
            "completed_appearance_starters": int(
                diagnostics["completed_appearance_starters"].sum()
            ),
        },
    }


def _within(value: float, bounds: tuple[float, float]) -> bool:
    return bounds[0] - IDENTITY_TOLERANCE <= value <= bounds[1] + IDENTITY_TOLERANCE


def classify(validation: Mapping[str, object], sensitivity: Mapping[str, object]) -> str:
    """Apply the frozen component-localization gates."""

    try:
        validation_arms = cast(Mapping[str, Mapping[str, object]], validation["arms"])
        validation_components = cast(Mapping[str, Mapping[str, object]], validation["components"])
        sensitivity_components = cast(Mapping[str, Mapping[str, object]], sensitivity["components"])
        sensitivity_arms = cast(Mapping[str, Mapping[str, object]], sensitivity["arms"])
        if (
            int(cast(int, validation_arms[CONTROL]["fold_count"])) < MIN_EVALUATION_FOLDS
            or int(cast(int, sensitivity_arms[CONTROL]["fold_count"])) < MIN_EVALUATION_FOLDS
            or float(cast(float, validation["maximum_absolute_identity_error"]))
            > IDENTITY_TOLERANCE
            or float(cast(float, validation["maximum_absolute_component_score_error"]))
            > IDENTITY_TOLERANCE
            or float(cast(float, sensitivity["maximum_absolute_identity_error"]))
            > IDENTITY_TOLERANCE
            or float(cast(float, sensitivity["maximum_absolute_component_score_error"]))
            > IDENTITY_TOLERANCE
        ):
            return INCONCLUSIVE
        localized: list[str] = []
        for component in COMPONENTS:
            contrast = cast(
                Mapping[str, float], validation_components[component]["tail_minus_other_surprise"]
            )
            reduction = cast(
                Mapping[str, float], validation_components[component]["q10_failure_reduction"]
            )
            sensitivity_contrast = cast(
                Mapping[str, float], sensitivity_components[component]["tail_minus_other_surprise"]
            )
            sensitivity_reduction = cast(
                Mapping[str, float], sensitivity_components[component]["q10_failure_reduction"]
            )
            arm = validation_arms[component]
            if (
                float(contrast["bootstrap_high"]) < 0.0
                and float(reduction["bootstrap_low"]) > 0.0
                and _within(
                    float(cast(float, arm["mean_probability_integral_transform"])), S1_PIT_BOUNDS
                )
                and _within(float(cast(float, arm["below_lower_quantile_rate"])), S2_TAIL_BOUNDS)
                and float(sensitivity_contrast["mean"]) <= 0.0
                and float(sensitivity_reduction["mean"]) >= 0.0
            ):
                localized.append(component)
    except (KeyError, TypeError, ValueError):
        return INCONCLUSIVE
    if len(localized) > 1:
        return SHARED_COMPONENT_FAILURE
    if len(localized) == 1:
        return f"{localized[0]}_component_localized"
    return COMPONENT_NOT_LOCALIZED
