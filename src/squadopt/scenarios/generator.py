"""Hierarchical empirical bootstrap of joint player-point residuals."""

import math
from collections.abc import Mapping
from numbers import Integral

import numpy as np
import pandas as pd

from squadopt.data.schema import POSITIONS, season_rank_map
from squadopt.prediction import PredictionSnapshot
from squadopt.scenarios.decomposition import decompose_residual_components
from squadopt.scenarios.models import (
    RESIDUAL_HISTORY_COLUMNS,
    ScenarioConfig,
    ScenarioSet,
    ScenarioTarget,
    ScenarioValidationError,
    _scenario_fingerprint,
)

_SCALE_EPSILON = 1e-12


def _identifier_kind(value: object) -> str | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, Integral):
        return "integer"
    if isinstance(value, str) and value.strip():
        return "string"
    return None


def _validate_identifier_column(frame: pd.DataFrame, column: str) -> str:
    kinds = {_identifier_kind(value) for value in frame[column].tolist()}
    if None in kinds:
        raise ScenarioValidationError(
            f"Residual history {column} values must be non-empty strings or integers."
        )
    if len(kinds) != 1:
        raise ScenarioValidationError(
            f"Residual history {column} must use one consistent identifier type."
        )
    kind = kinds.pop()
    assert kind is not None
    return kind


def _numeric(frame: pd.DataFrame, column: str) -> pd.Series:
    try:
        values = pd.to_numeric(frame[column], errors="raise").astype("float64")
    except (TypeError, ValueError) as error:
        raise ScenarioValidationError(
            f"Residual history {column} must contain finite numeric values."
        ) from error
    if not bool(np.isfinite(values.to_numpy()).all()):
        raise ScenarioValidationError(
            f"Residual history {column} must contain finite numeric values."
        )
    return values


def validate_residual_history(
    residual_history: object,
    projections: PredictionSnapshot,
    target: ScenarioTarget,
    config: ScenarioConfig,
) -> pd.DataFrame:
    """Return an independent, chronological residual history before the target."""

    if not isinstance(residual_history, pd.DataFrame):
        raise ScenarioValidationError("residual_history must be a pandas DataFrame.")
    duplicates = residual_history.columns[residual_history.columns.duplicated()].tolist()
    if duplicates:
        raise ScenarioValidationError(
            f"Residual history contains duplicate columns: {duplicates!r}."
        )
    missing = [column for column in RESIDUAL_HISTORY_COLUMNS if column not in residual_history]
    if missing:
        raise ScenarioValidationError(f"Residual history is missing columns: {missing!r}.")
    frame = residual_history.loc[:, list(RESIDUAL_HISTORY_COLUMNS)].copy(deep=True)
    if frame.empty:
        raise ScenarioValidationError("Residual history must contain at least one row.")
    missing_values = [column for column in frame if bool(frame[column].isna().any())]
    if missing_values:
        raise ScenarioValidationError(
            f"Residual history contains missing values in: {missing_values!r}."
        )
    if bool(frame.duplicated(subset=["fold_id", "player_id"]).any()):
        raise ScenarioValidationError(
            "Residual history must contain at most one row per fold_id and player_id."
        )
    player_kind = _validate_identifier_column(frame, "player_id")
    team_kind = _validate_identifier_column(frame, "team_id")
    projection_player_kind = _identifier_kind(projections.table.iloc[0]["player_id"])
    projection_team_kind = _identifier_kind(projections.table.iloc[0]["team_id"])
    if player_kind != projection_player_kind or team_kind != projection_team_kind:
        raise ScenarioValidationError(
            "Residual-history player_id and team_id types must match the projections."
        )
    invalid_positions = sorted(
        {str(value) for value in frame["position"] if value not in POSITIONS}
    )
    if invalid_positions:
        raise ScenarioValidationError(
            f"Residual history positions must be in {list(POSITIONS)!r}; "
            f"invalid={invalid_positions!r}."
        )
    invalid_seasons = [
        value for value in frame["season"] if not isinstance(value, str) or not value.strip()
    ]
    invalid_fold_ids = [
        value for value in frame["fold_id"] if not isinstance(value, str) or not value.strip()
    ]
    if invalid_seasons or invalid_fold_ids:
        raise ScenarioValidationError(
            "Residual history season and fold_id must be non-empty strings."
        )
    gameweeks: list[int] = []
    for value in frame["gameweek"]:
        if isinstance(value, bool) or not isinstance(value, Integral) or int(value) < 1:
            raise ScenarioValidationError(
                "Residual history gameweek must contain positive integers."
            )
        gameweeks.append(int(value))
    frame["gameweek"] = pd.Series(gameweeks, index=frame.index, dtype="int64")
    expected_fold_ids = [
        f"{str(season).strip()}-gw{gameweek:02d}"
        for season, gameweek in zip(frame["season"], frame["gameweek"], strict=True)
    ]
    if expected_fold_ids != frame["fold_id"].tolist():
        raise ScenarioValidationError(
            "Residual history fold_id must match its season and gameweek."
        )
    for column in ("predicted_points", "realized_points", "residual"):
        frame[column] = _numeric(frame, column)
    if bool((frame["predicted_points"] < 0.0).any()):
        raise ScenarioValidationError("Residual-history predicted_points must be non-negative.")
    calculated = frame["realized_points"] - frame["predicted_points"]
    if not bool(
        np.allclose(
            calculated.to_numpy(),
            frame["residual"].to_numpy(),
            rtol=1e-10,
            atol=1e-10,
        )
    ):
        raise ScenarioValidationError(
            "Residual history residual must equal realized_points minus predicted_points."
        )
    ranks = season_rank_map([*frame["season"].tolist(), target.season])
    target_key = (ranks[target.season], target.gameweek)
    future_or_target = [
        (str(season), int(gameweek))
        for season, gameweek in zip(frame["season"], frame["gameweek"], strict=True)
        if (ranks[str(season)], int(gameweek)) >= target_key
    ]
    if future_or_target:
        raise ScenarioValidationError(
            "Residual history must be strictly before the scenario target; "
            f"invalid examples: {future_or_target[:10]!r}."
        )
    fold_count = frame["fold_id"].nunique()
    if fold_count < config.min_history_folds:
        raise ScenarioValidationError(
            f"Scenario generation needs at least {config.min_history_folds} historical folds; "
            f"got {fold_count}."
        )
    return frame.sort_values(["season", "gameweek", "player_id"], kind="stable").reset_index(
        drop=True
    )


def _centered(values: np.ndarray) -> np.ndarray:
    return values - values.mean() if values.size else values


def _standardized(values: np.ndarray) -> tuple[np.ndarray, float]:
    centered = _centered(values.astype("float64", copy=True))
    scale = float(centered.std(ddof=0)) if centered.size else 0.0
    if scale <= _SCALE_EPSILON:
        return np.zeros(max(1, centered.size), dtype="float64"), 0.0
    return centered / scale, scale


def _decompose(
    frame: pd.DataFrame,
) -> tuple[pd.DataFrame, tuple[str, ...], np.ndarray, dict[str, np.ndarray]]:
    decomposed = decompose_residual_components(frame)
    fold_ids = tuple(decomposed["fold_id"].drop_duplicates().tolist())
    common = np.asarray(
        [
            decomposed.loc[decomposed["fold_id"] == fold_id, "common_component"].iloc[0]
            for fold_id in fold_ids
        ],
        dtype="float64",
    )
    common = _centered(common)
    teams_by_fold: dict[str, np.ndarray] = {}
    for fold_id in fold_ids:
        values = (
            decomposed.loc[decomposed["fold_id"] == fold_id]
            .groupby("team_id", sort=True)["team_component"]
            .first()
            .to_numpy(dtype="float64")
        )
        teams_by_fold[fold_id] = _centered(values)
    return decomposed, fold_ids, common, teams_by_fold


def _idiosyncratic_draws(
    decomposed: pd.DataFrame,
    projections: pd.DataFrame,
    config: ScenarioConfig,
    rng: np.random.Generator,
) -> tuple[np.ndarray, dict[str, int], dict[str, float]]:
    values = decomposed["idiosyncratic_component"].to_numpy(dtype="float64")
    pooled_standardized, pooled_scale = _standardized(values)
    position_state: dict[str, tuple[np.ndarray, float]] = {}
    for position in POSITIONS:
        position_values = decomposed.loc[
            decomposed["position"] == position, "idiosyncratic_component"
        ].to_numpy(dtype="float64")
        standardized, scale = _standardized(position_values)
        if scale <= _SCALE_EPSILON:
            standardized, scale = pooled_standardized, pooled_scale
        position_state[position] = standardized, scale

    draws = np.zeros((config.scenario_count, len(projections)), dtype="float64")
    source_counts = {"player": 0, "position": 0, "pooled": 0}
    scales: dict[str, float] = {}
    for column, row in enumerate(projections.itertuples(index=False)):
        player_id = row.player_id
        target_position = str(row.position)
        player_values = decomposed.loc[
            decomposed["player_id"] == player_id, "idiosyncratic_component"
        ].to_numpy(dtype="float64")
        position_pool, position_scale = position_state[target_position]
        if player_values.size >= config.min_player_observations:
            player_pool, player_scale = _standardized(player_values)
            if player_scale <= _SCALE_EPSILON and position_scale > _SCALE_EPSILON:
                player_pool = position_pool
            strength = config.player_scale_shrinkage
            effective_variance = (
                player_values.size * player_scale**2 + strength * position_scale**2
            ) / (player_values.size + strength)
            effective_scale = math.sqrt(max(0.0, effective_variance))
            pool = player_pool
            source = "player"
        elif position_scale > _SCALE_EPSILON:
            pool = position_pool
            effective_scale = position_scale
            source = "position"
        else:
            pool = pooled_standardized
            effective_scale = pooled_scale
            source = "pooled"
        indices = rng.integers(0, len(pool), size=config.scenario_count)
        draws[:, column] = pool[indices] * effective_scale
        source_counts[source] += 1
        scales[str(player_id)] = effective_scale
    return draws, source_counts, scales


def _player_locations(
    history: pd.DataFrame,
    projections: pd.DataFrame,
    shrinkage: float,
) -> tuple[np.ndarray, int]:
    """Return each projected player's shrunk historical mean residual.

    The hierarchical shocks are zero-mean by construction, so without this component
    the scenarios are centered exactly on the projections and carry no memory of a
    player's systematic optimism or pessimism. The shrunk location restores that
    memory; a player with no history contributes zero rather than a borrowed value.
    """

    grouped = history.groupby("player_id", sort=False)["residual"]
    means = grouped.mean()
    counts = grouped.size()
    locations = np.zeros(len(projections), dtype="float64")
    players_with_history = 0
    for column, player_id in enumerate(projections["player_id"].tolist()):
        if player_id in means.index:
            count = float(counts.loc[player_id])
            weight = count / (count + shrinkage) if (count + shrinkage) > 0.0 else 0.0
            locations[column] = weight * float(means.loc[player_id])
            players_with_history += 1
    return locations, players_with_history


def generate_scenarios(
    projections: PredictionSnapshot,
    residual_history: pd.DataFrame,
    target: ScenarioTarget,
    config: ScenarioConfig | None = None,
    *,
    fixture_counts: Mapping[object, int] | None = None,
) -> ScenarioSet:
    """Generate deterministic joint player-point scenarios from past OOS residuals.

    ``fixture_counts`` maps a projected player to the number of fixtures their team
    plays in the target gameweek; required when ``config.double_gameweek_scale`` is not
    one, ignored otherwise.
    """

    settings = ScenarioConfig() if config is None else config
    if not isinstance(settings, ScenarioConfig):
        raise ScenarioValidationError("config must be a ScenarioConfig.")
    if settings.double_gameweek_scale != 1.0 and fixture_counts is None:
        raise ScenarioValidationError(
            "double_gameweek_scale differs from one; fixture_counts (the target gameweek's "
            "calendar per player) are required to apply it."
        )
    if not isinstance(target, ScenarioTarget):
        raise ScenarioValidationError("target must be a ScenarioTarget.")
    if not isinstance(projections, PredictionSnapshot):
        raise ScenarioValidationError("projections must be a PredictionSnapshot.")
    snapshot = projections.validated_copy()
    history = validate_residual_history(residual_history, snapshot, target, settings)
    decomposed, fold_ids, common_pool, teams_by_fold = _decompose(history)
    rng = np.random.default_rng(settings.deterministic_seed)
    source_indices = rng.integers(0, len(fold_ids), size=settings.scenario_count)
    source_fold_ids = tuple(fold_ids[index] for index in source_indices)
    common_draws = common_pool[source_indices]

    projection_table = snapshot.table
    target_teams = tuple(dict.fromkeys(projection_table["team_id"].tolist()))
    team_draws = np.zeros((settings.scenario_count, len(target_teams)), dtype="float64")
    for scenario_index, source_fold in enumerate(source_fold_ids):
        pool = teams_by_fold[source_fold]
        choices = rng.integers(0, len(pool), size=len(target_teams))
        team_draws[scenario_index] = pool[choices]
    team_column = {team_id: index for index, team_id in enumerate(target_teams)}
    player_team_columns = np.asarray(
        [team_column[team_id] for team_id in projection_table["team_id"]], dtype="int64"
    )
    shared_team_draws = team_draws[:, player_team_columns]
    idiosyncratic, fallback_counts, player_scales = _idiosyncratic_draws(
        decomposed,
        projection_table,
        settings,
        rng,
    )
    double_players = 0
    if settings.double_gameweek_scale != 1.0 and fixture_counts is not None:
        counts = dict(fixture_counts)
        double_mask = np.asarray(
            [int(counts.get(player_id, 1)) >= 2 for player_id in projection_table["player_id"]],
            dtype=bool,
        )
        double_players = int(double_mask.sum())
        idiosyncratic[:, double_mask] *= settings.double_gameweek_scale
        for player_id, is_double in zip(projection_table["player_id"], double_mask, strict=True):
            if is_double:
                player_scales[str(player_id)] *= settings.double_gameweek_scale
    point_values = projection_table["expected_points"].to_numpy(dtype="float64")
    if settings.player_location_shrinkage is not None:
        locations, players_with_history = _player_locations(
            history,
            projection_table,
            settings.player_location_shrinkage,
        )
    else:
        locations = np.zeros(len(projection_table), dtype="float64")
        players_with_history = 0
    values = (
        point_values + locations[None, :] + common_draws[:, None] + shared_team_draws
    ) + idiosyncratic
    scenario_ids = tuple(f"scenario-{index:06d}" for index in range(settings.scenario_count))
    points = pd.DataFrame(
        values,
        index=pd.Index(scenario_ids, name="scenario_id"),
        columns=projection_table["player_id"].tolist(),
        dtype="float64",
    )
    fingerprint = _scenario_fingerprint(
        snapshot,
        target,
        settings,
        scenario_ids,
        source_fold_ids,
        points,
    )
    mean_deviation = np.abs(values.mean(axis=0) - point_values)
    return ScenarioSet(
        projections=snapshot,
        target=target,
        config=settings,
        scenario_ids=scenario_ids,
        source_fold_ids=source_fold_ids,
        scenario_points=points,
        scenario_fingerprint=fingerprint,
        diagnostics={
            "double_gameweek_scale": settings.double_gameweek_scale,
            "double_gameweek_players": double_players,
            "history_rows": len(history),
            "history_folds": len(fold_ids),
            "history_first_fold": fold_ids[0],
            "history_last_fold": fold_ids[-1],
            "residual_definition": "realized_points_minus_predicted_points",
            "components": ("common_gameweek", "team_gameweek", "idiosyncratic"),
            "component_centering": "empirical_zero_mean",
            "player_location_shrinkage": settings.player_location_shrinkage,
            "players_with_location_history": players_with_history,
            "mean_absolute_player_location": float(np.abs(locations).mean()),
            "team_shock_shared_within_target_team": True,
            "idiosyncratic_fallback_counts": fallback_counts,
            "player_effective_scales": player_scales,
            "negative_scenario_points_allowed": True,
            "point_projection_changed": False,
            "mean_absolute_player_scenario_bias": float(mean_deviation.mean()),
            "maximum_absolute_player_scenario_bias": float(mean_deviation.max()),
        },
    )
