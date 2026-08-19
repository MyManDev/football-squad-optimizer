"""Joint player-point scenarios over a window, not a single gameweek.

Every recommendation this system is meant to make over one, three or five weeks rests on a
distribution nothing here could produce. ``generate_scenarios`` simulates *one* deadline:
:class:`ScenarioTarget` carries a season and a gameweek and nothing else. Ask it for a
three-week statement and the only honest answer is three independent copies of one week —
and the weeks are not independent. A player who does not play in week one is unusually
likely not to play in week two, and a club in form tends to stay in form for a while.

Which way that moves a window's spread is a measurement, not an intuition, and the intuition
is wrong here. Measured on the control's own residuals over 2024-25 gameweeks 20 to 22, a
path is **0.983x** as wide as three independent weeks, not wider: a player who beats his
projection one week tends to fall back the next, and that mean reversion cancels part of what
independent draws add up. See `docs/scenario_path_dependence.md`. The effect is small, and the
point is not its size or its sign — it is that independence asserts a dependence structure the
data does not have, while a path uses the one it does.

This module keeps the same hierarchical decomposition and replaces independent draws with a
**block bootstrap over consecutive gameweeks**. One scenario is a *path*: a run of
``horizon`` consecutive folds sampled from history, with the source identity held fixed for
the length of the block at every level.

- the **common** component walks the run, so a league-wide scoring lull persists;
- a **team** shock keeps the same source club across the run, so form persists;
- a player's **idiosyncratic** draws follow one source player across the run, so his minutes
  persist — which is the piece that matters most, because not playing is sticky.

Blocks never cross a season boundary and are always gameweek-contiguous. A club or a player
whose history offers no contiguous run of the requested length borrows a run from another
player of the same position — never a splice of unrelated weeks — and the borrowing is counted
in the diagnostics rather than hidden. A run always follows *one* player: in a position pool,
which holds every player of that position in every fold, "the next row" is a different player,
so a run is the same player at the next fold or it is not a run.

One property of block bootstrapping is worth stating rather than discovering. With a horizon
of ``H`` the first week of a path can never be drawn from the last ``H-1`` folds of a season,
and the last week never from the first ``H-1``. On a stationary residual pool that costs
nothing; on a pool with a trend it shifts each week of the window slightly in the direction of
the trend. ``common_block_week_means`` reports the shift so it can be seen rather than
assumed away, and it is the price of refusing to wrap a block around a season boundary.

**At a horizon of one this is the existing generator, bit for bit.** The random draws are
made in the same order, from the same pools, with the same sizes, and a test asserts the two
produce identical matrices and identical fingerprints. That equivalence is the reason this
can be adopted without re-validating every calibration result that came before it.
"""

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Final

import numpy as np
import pandas as pd

from squadopt.data.schema import POSITIONS
from squadopt.prediction import PredictionSnapshot
from squadopt.scenarios.decomposition import decompose_residual_components
from squadopt.scenarios.generator import (
    _centered,
    _player_locations,
    _standardized,
    validate_residual_history,
)
from squadopt.scenarios.models import (
    ScenarioConfig,
    ScenarioSet,
    ScenarioTarget,
    ScenarioValidationError,
    _scenario_fingerprint,
)

SCENARIO_PATH_CONTRACT_VERSION: Final = "hierarchical_residual_scenario_paths_v1"
_SCALE_EPSILON: Final = 1e-12


@dataclass(frozen=True, slots=True)
class ScenarioPathTarget:
    """The window a path covers: a season, its first deadline, and how many weeks follow."""

    season: str
    first_gameweek: int
    horizon: int = 1

    def __post_init__(self) -> None:
        if not isinstance(self.season, str) or not self.season.strip():
            raise ScenarioValidationError("season must be a non-empty string.")
        object.__setattr__(self, "season", self.season.strip())
        for name in ("first_gameweek", "horizon"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ScenarioValidationError(f"{name} must be a positive integer.")

    @property
    def gameweeks(self) -> tuple[int, ...]:
        return tuple(self.first_gameweek + offset for offset in range(self.horizon))

    def week_target(self, gameweek: int) -> ScenarioTarget:
        """The single-gameweek target one week of this window corresponds to."""

        if gameweek not in self.gameweeks:
            raise ScenarioValidationError(f"Gameweek {gameweek} is outside this window.")
        return ScenarioTarget(season=self.season, gameweek=gameweek)

    @property
    def window_id(self) -> str:
        last = self.gameweeks[-1]
        return f"{self.season}-gw{self.first_gameweek:02d}-gw{last:02d}"


@dataclass(frozen=True, slots=True)
class ScenarioPathSet:
    """One scenario per row, one column per player, one matrix per week of the window."""

    projections: Mapping[int, PredictionSnapshot]
    target: ScenarioPathTarget
    config: ScenarioConfig
    scenario_ids: tuple[str, ...]
    source_fold_blocks: tuple[tuple[str, ...], ...]
    """Per scenario, the run of historical folds the path was drawn from."""
    weekly_points: Mapping[int, pd.DataFrame]
    path_fingerprint: str
    diagnostics: Mapping[str, object] = field(default_factory=dict)
    contract_version: str = SCENARIO_PATH_CONTRACT_VERSION

    def __post_init__(self) -> None:
        if self.contract_version != SCENARIO_PATH_CONTRACT_VERSION:
            raise ScenarioValidationError("contract_version does not match this implementation.")
        if set(self.weekly_points) != set(self.target.gameweeks):
            raise ScenarioValidationError("weekly_points must cover exactly the window.")
        if set(self.projections) != set(self.target.gameweeks):
            raise ScenarioValidationError("projections must cover exactly the window.")
        expected = tuple(f"scenario-{index:06d}" for index in range(self.config.scenario_count))
        if self.scenario_ids != expected:
            raise ScenarioValidationError(
                "scenario_ids do not match the configured deterministic IDs."
            )
        if len(self.source_fold_blocks) != self.config.scenario_count:
            raise ScenarioValidationError("source_fold_blocks must align with scenarios.")
        if any(len(block) != self.target.horizon for block in self.source_fold_blocks):
            raise ScenarioValidationError("every source block must span the whole horizon.")

    @property
    def horizon(self) -> int:
        return self.target.horizon

    def week(self, gameweek: int) -> pd.DataFrame:
        """One week of the window, in the shape every existing consumer already reads."""

        if gameweek not in self.weekly_points:
            raise ScenarioValidationError(f"Gameweek {gameweek} is outside this window.")
        return self.weekly_points[gameweek]

    def window_points(self) -> pd.DataFrame:
        """Each scenario's total per player across the window.

        This is the object a one-, three- or five-week statement is made from: the weeks
        inside a row are the *same* path, so summing them keeps whatever persistence the
        block bootstrap put there.
        """

        frames = [self.weekly_points[gameweek] for gameweek in self.target.gameweeks]
        total = frames[0].copy(deep=True)
        for frame in frames[1:]:
            total = total.add(frame, fill_value=0.0)
        return total

    def as_scenario_set(self, gameweek: int) -> ScenarioSet:
        """One week as a :class:`ScenarioSet`, so the risk and rank layers work unchanged."""

        points = self.week(gameweek)
        offset = self.target.gameweeks.index(gameweek)
        source_fold_ids = tuple(block[offset] for block in self.source_fold_blocks)
        snapshot = self.projections[gameweek]
        target = self.target.week_target(gameweek)
        return ScenarioSet(
            projections=snapshot,
            target=target,
            config=self.config,
            scenario_ids=self.scenario_ids,
            source_fold_ids=source_fold_ids,
            scenario_points=points,
            scenario_fingerprint=_scenario_fingerprint(
                snapshot.validated_copy(),
                target,
                self.config,
                self.scenario_ids,
                source_fold_ids,
                points,
            ),
            diagnostics={
                **dict(self.diagnostics),
                "drawn_as_path_week": offset,
                "path_horizon": self.target.horizon,
            },
        )


# --- block eligibility ---------------------------------------------------------


def _fold_order(history: pd.DataFrame) -> tuple[tuple[str, ...], np.ndarray, np.ndarray]:
    """Folds in chronological order, with the season and gameweek each one names."""

    ordered = (
        history.loc[:, ["fold_id", "season", "gameweek"]]
        .drop_duplicates(subset=["fold_id"])
        .reset_index(drop=True)
    )
    fold_ids = tuple(str(value) for value in ordered["fold_id"])
    seasons = ordered["season"].astype("string").to_numpy()
    gameweeks = ordered["gameweek"].astype("int64").to_numpy()
    return fold_ids, seasons, gameweeks


def contiguous_starts(seasons: np.ndarray, gameweeks: np.ndarray, horizon: int) -> np.ndarray:
    """Positions where ``horizon`` folds run consecutively inside one season.

    A block that crosses a season boundary would splice one league onto another — the clubs
    are not the same clubs and a promoted side inherits a relegated side's shock. A block
    that skips a gameweek would claim a persistence the history does not show.
    """

    total = len(gameweeks)
    if horizon < 1:
        raise ScenarioValidationError("horizon must be a positive integer.")
    if horizon == 1:
        return np.arange(total, dtype="int64")
    valid: list[int] = []
    for start in range(total - horizon + 1):
        span = range(start, start + horizon)
        same_season = all(seasons[index] == seasons[start] for index in span)
        consecutive = all(
            int(gameweeks[index + 1]) == int(gameweeks[index]) + 1
            for index in range(start, start + horizon - 1)
        )
        if same_season and consecutive:
            valid.append(start)
    return np.asarray(valid, dtype="int64")


def source_runs(
    player_ids: np.ndarray,
    fold_positions: np.ndarray,
    seasons: np.ndarray,
    gameweeks: np.ndarray,
    horizon: int,
) -> np.ndarray:
    """Every run of ``horizon`` consecutive weeks one *player* supplies inside a pool.

    A pool is a flat array of standardised residuals, and its rows are not one per week:
    a position pool holds every player of that position in every fold. A run therefore
    cannot be "this row and the next two" — it has to be *the same player* at the next
    two folds, which is the only reading under which following a run preserves anything.

    Rows are enumerated in the pool's own order, so at a horizon of one the result is
    ``[[0], [1], ...]`` and drawing a run is drawing a row. That is what keeps the
    horizon-one path bit-for-bit identical to the single-gameweek generator.
    """

    total = len(fold_positions)
    if horizon < 1:
        raise ScenarioValidationError("horizon must be a positive integer.")
    if horizon == 1:
        return np.arange(total, dtype="int64").reshape(-1, 1)
    located: dict[tuple[object, int], int] = {
        (player_ids[row], int(fold_positions[row])): row for row in range(total)
    }
    runs: list[list[int]] = []
    for row in range(total):
        origin = int(fold_positions[row])
        block = [row]
        for step in range(1, horizon):
            following = origin + step
            if following >= len(gameweeks):
                break
            if seasons[following] != seasons[origin]:
                break
            if int(gameweeks[following]) != int(gameweeks[origin]) + step:
                break
            found = located.get((player_ids[row], following))
            if found is None:
                # The player is absent that week. That absence is information, and a run
                # spliced over it would erase exactly the persistence being modelled.
                break
            block.append(found)
        if len(block) == horizon:
            runs.append(block)
    if not runs:
        return np.zeros((0, horizon), dtype="int64")
    return np.asarray(runs, dtype="int64")


# --- generation ----------------------------------------------------------------


def _validate_projections(
    projections: Mapping[int, PredictionSnapshot], target: ScenarioPathTarget
) -> dict[int, PredictionSnapshot]:
    if not isinstance(projections, Mapping) or not projections:
        raise ScenarioValidationError("projections must be a non-empty mapping.")
    missing = [gameweek for gameweek in target.gameweeks if gameweek not in projections]
    if missing:
        raise ScenarioValidationError(f"projections carry no gameweek {missing!r}.")
    extra = [gameweek for gameweek in projections if gameweek not in target.gameweeks]
    if extra:
        raise ScenarioValidationError(f"projections carry gameweeks outside the window: {extra!r}.")
    validated: dict[int, PredictionSnapshot] = {}
    reference: list[object] | None = None
    for gameweek in target.gameweeks:
        snapshot = projections[gameweek]
        if not isinstance(snapshot, PredictionSnapshot):
            raise ScenarioValidationError(f"projections[{gameweek}] must be a PredictionSnapshot.")
        copy = snapshot.validated_copy()
        players = copy.table["player_id"].tolist()
        if reference is None:
            reference = players
        elif players != reference:
            # A window is one decision over one pool. A pool that changes mid-window would
            # make the columns of two weeks mean different things in the same path.
            raise ScenarioValidationError(
                f"Gameweek {gameweek} projects a different player pool than the window's first."
            )
        validated[gameweek] = copy
    return validated


def _path_fingerprint(
    target: ScenarioPathTarget,
    config: ScenarioConfig,
    weekly_fingerprints: Mapping[int, str],
    source_fold_blocks: Sequence[Sequence[str]],
) -> str:
    document = {
        "contract_version": SCENARIO_PATH_CONTRACT_VERSION,
        "window_id": target.window_id,
        "horizon": target.horizon,
        "scenario_count": config.scenario_count,
        "deterministic_seed": config.deterministic_seed,
        "weekly_fingerprints": {
            str(key): value for key, value in sorted(weekly_fingerprints.items())
        },
        "source_fold_blocks": [list(block) for block in source_fold_blocks],
    }
    payload = json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def generate_scenario_paths(
    projections: Mapping[int, PredictionSnapshot],
    residual_history: pd.DataFrame,
    target: ScenarioPathTarget,
    config: ScenarioConfig | None = None,
    *,
    fixture_counts: Mapping[int, Mapping[object, int]] | None = None,
) -> ScenarioPathSet:
    """Generate deterministic joint player-point *paths* over a window of gameweeks.

    ``projections`` carries one snapshot per gameweek in the window, over one unchanging
    player pool. ``fixture_counts``, when the double-gameweek scale is in use, carries one
    calendar per gameweek.

    At ``horizon`` one this reproduces :func:`generate_scenarios` exactly.
    """

    settings = ScenarioConfig() if config is None else config
    if not isinstance(settings, ScenarioConfig):
        raise ScenarioValidationError("config must be a ScenarioConfig.")
    if not isinstance(target, ScenarioPathTarget):
        raise ScenarioValidationError("target must be a ScenarioPathTarget.")
    if settings.double_gameweek_scale != 1.0 and fixture_counts is None:
        raise ScenarioValidationError(
            "double_gameweek_scale differs from one; fixture_counts (one calendar per gameweek "
            "in the window) are required to apply it."
        )
    snapshots = _validate_projections(projections, target)
    first_snapshot = snapshots[target.first_gameweek]
    history = validate_residual_history(
        residual_history, first_snapshot, target.week_target(target.first_gameweek), settings
    )
    decomposed = decompose_residual_components(history)
    fold_ids, seasons, gameweeks = _fold_order(decomposed)
    fold_position = {fold_id: index for index, fold_id in enumerate(fold_ids)}

    starts = contiguous_starts(seasons, gameweeks, target.horizon)
    if starts.size == 0:
        raise ScenarioValidationError(
            f"The residual history holds no run of {target.horizon} consecutive gameweeks "
            "inside one season, so no path of that length can be drawn from it."
        )

    common = _centered(
        np.asarray(
            [
                decomposed.loc[decomposed["fold_id"] == fold_id, "common_component"].iloc[0]
                for fold_id in fold_ids
            ],
            dtype="float64",
        )
    )
    teams_by_fold = {
        fold_id: _centered(
            decomposed.loc[decomposed["fold_id"] == fold_id]
            .groupby("team_id", sort=True)["team_component"]
            .first()
            .to_numpy(dtype="float64")
        )
        for fold_id in fold_ids
    }

    rng = np.random.default_rng(settings.deterministic_seed)
    chosen = rng.integers(0, len(starts), size=settings.scenario_count)
    block_starts = starts[chosen]
    block_positions = np.asarray(
        [[start + step for step in range(target.horizon)] for start in block_starts],
        dtype="int64",
    )
    source_fold_blocks = tuple(
        tuple(fold_ids[position] for position in row) for row in block_positions
    )
    common_draws = common[block_positions]

    projection_table = first_snapshot.table
    target_teams = tuple(dict.fromkeys(projection_table["team_id"].tolist()))
    team_draws = np.zeros(
        (settings.scenario_count, target.horizon, len(target_teams)), dtype="float64"
    )
    truncated_team_blocks = 0
    for scenario_index in range(settings.scenario_count):
        block = source_fold_blocks[scenario_index]
        pool = teams_by_fold[block[0]]
        choices = rng.integers(0, len(pool), size=len(target_teams))
        for step, fold_id in enumerate(block):
            week_pool = teams_by_fold[fold_id]
            if len(week_pool) == len(pool):
                team_draws[scenario_index, step] = week_pool[choices]
            else:
                # The source week fields a different number of clubs, so the held index no
                # longer names the same club. Zero is the honest shock, not a borrowed one.
                truncated_team_blocks += 1
    team_column = {team_id: index for index, team_id in enumerate(target_teams)}
    player_team_columns = np.asarray(
        [team_column[team_id] for team_id in projection_table["team_id"]], dtype="int64"
    )
    shared_team_draws = team_draws[:, :, player_team_columns]

    idiosyncratic, fallback_counts, player_scales, block_sources = _idiosyncratic_paths(
        decomposed,
        projection_table,
        settings,
        rng,
        fold_position=fold_position,
        seasons=seasons,
        gameweeks=gameweeks,
        horizon=target.horizon,
    )

    double_players = 0
    if settings.double_gameweek_scale != 1.0 and fixture_counts is not None:
        for step, gameweek in enumerate(target.gameweeks):
            counts = dict(fixture_counts.get(gameweek, {}))
            double_mask = np.asarray(
                [int(counts.get(player_id, 1)) >= 2 for player_id in projection_table["player_id"]],
                dtype=bool,
            )
            double_players += int(double_mask.sum())
            idiosyncratic[:, step, double_mask] *= settings.double_gameweek_scale
            if step == 0:
                for player_id, is_double in zip(
                    projection_table["player_id"], double_mask, strict=True
                ):
                    if is_double:
                        player_scales[str(player_id)] *= settings.double_gameweek_scale

    if settings.player_location_shrinkage is not None:
        locations, players_with_history = _player_locations(
            history, projection_table, settings.player_location_shrinkage
        )
    else:
        locations = np.zeros(len(projection_table), dtype="float64")
        players_with_history = 0

    scenario_ids = tuple(f"scenario-{index:06d}" for index in range(settings.scenario_count))
    weekly_points: dict[int, pd.DataFrame] = {}
    weekly_fingerprints: dict[int, str] = {}
    biases: list[float] = []
    for step, gameweek in enumerate(target.gameweeks):
        snapshot = snapshots[gameweek]
        point_values = snapshot.table["expected_points"].to_numpy(dtype="float64")
        values = (
            point_values
            + locations[None, :]
            + common_draws[:, step][:, None]
            + shared_team_draws[:, step, :]
            + idiosyncratic[:, step, :]
        )
        frame = pd.DataFrame(
            values,
            index=pd.Index(scenario_ids, name="scenario_id"),
            columns=snapshot.table["player_id"].tolist(),
            dtype="float64",
        )
        weekly_points[gameweek] = frame
        week_folds = tuple(block[step] for block in source_fold_blocks)
        weekly_fingerprints[gameweek] = _scenario_fingerprint(
            snapshot,
            target.week_target(gameweek),
            settings,
            scenario_ids,
            week_folds,
            frame,
        )
        biases.append(float(np.abs(values.mean(axis=0) - point_values).mean()))

    return ScenarioPathSet(
        projections=snapshots,
        target=target,
        config=settings,
        scenario_ids=scenario_ids,
        source_fold_blocks=source_fold_blocks,
        weekly_points=weekly_points,
        path_fingerprint=_path_fingerprint(
            target, settings, weekly_fingerprints, source_fold_blocks
        ),
        diagnostics={
            "horizon": target.horizon,
            "window_id": target.window_id,
            "history_rows": len(history),
            "history_folds": len(fold_ids),
            "contiguous_block_starts": int(starts.size),
            "block_starts_available_share": float(starts.size) / float(len(fold_ids)),
            "weekly_fingerprints": {str(key): value for key, value in weekly_fingerprints.items()},
            "idiosyncratic_fallback_counts": fallback_counts,
            "idiosyncratic_block_sources": block_sources,
            "player_effective_scales": player_scales,
            "players_with_location_history": players_with_history,
            "double_gameweek_scale": settings.double_gameweek_scale,
            "double_gameweek_player_weeks": double_players,
            "truncated_team_blocks": truncated_team_blocks,
            "mean_absolute_player_scenario_bias_by_week": biases,
            "common_block_week_means": [
                float(common_draws[:, step].mean()) for step in range(target.horizon)
            ],
            "components": ("common_gameweek", "team_gameweek", "idiosyncratic"),
            "block_rule": "same_season_consecutive_gameweeks_source_identity_held",
        },
    )


def _idiosyncratic_paths(
    decomposed: pd.DataFrame,
    projections: pd.DataFrame,
    config: ScenarioConfig,
    rng: np.random.Generator,
    *,
    fold_position: Mapping[str, int],
    seasons: np.ndarray,
    gameweeks: np.ndarray,
    horizon: int,
) -> tuple[np.ndarray, dict[str, int], dict[str, float], dict[str, int]]:
    """Draw each player a run of idiosyncratic shocks, following one source player through it.

    The draw order and pool sizes match ``_idiosyncratic_draws`` exactly at horizon one, so
    the two generators agree bit for bit there.
    """

    values = decomposed["idiosyncratic_component"].to_numpy(dtype="float64")
    all_players = decomposed["player_id"].to_numpy()
    all_folds = np.asarray(
        [fold_position[str(value)] for value in decomposed["fold_id"]], dtype="int64"
    )
    pooled_standardized, pooled_scale = _standardized(values)
    pooled_runs = source_runs(all_players, all_folds, seasons, gameweeks, horizon)

    position_state: dict[str, tuple[np.ndarray, np.ndarray, float]] = {}
    for position in POSITIONS:
        mask = (decomposed["position"] == position).to_numpy()
        standardized, scale = _standardized(
            decomposed.loc[mask, "idiosyncratic_component"].to_numpy(dtype="float64")
        )
        if scale <= _SCALE_EPSILON:
            position_state[position] = (pooled_standardized, pooled_runs, pooled_scale)
            continue
        position_state[position] = (
            standardized,
            source_runs(all_players[mask], all_folds[mask], seasons, gameweeks, horizon),
            scale,
        )

    draws = np.zeros((config.scenario_count, horizon, len(projections)), dtype="float64")
    source_counts = {"player": 0, "position": 0, "pooled": 0}
    block_sources = {"own_history": 0, "position_fallback": 0, "pooled_fallback": 0}
    scales: dict[str, float] = {}
    for column, row in enumerate(projections.itertuples(index=False)):
        player_id = row.player_id
        target_position = str(row.position)
        player_mask = (decomposed["player_id"] == player_id).to_numpy()
        player_values = decomposed.loc[player_mask, "idiosyncratic_component"].to_numpy(
            dtype="float64"
        )
        position_pool, position_runs, position_scale = position_state[target_position]
        if player_values.size >= config.min_player_observations:
            player_pool, player_scale = _standardized(player_values)
            player_runs = source_runs(
                all_players[player_mask], all_folds[player_mask], seasons, gameweeks, horizon
            )
            if player_scale <= _SCALE_EPSILON and position_scale > _SCALE_EPSILON:
                player_pool, player_runs = position_pool, position_runs
            strength = config.player_scale_shrinkage
            effective_variance = (
                player_values.size * player_scale**2 + strength * position_scale**2
            ) / (player_values.size + strength)
            effective_scale = float(np.sqrt(max(0.0, effective_variance)))
            pool, runs, source = player_pool, player_runs, "player"
        elif position_scale > _SCALE_EPSILON:
            pool, runs = position_pool, position_runs
            effective_scale = position_scale
            source = "position"
        else:
            pool, runs = pooled_standardized, pooled_runs
            effective_scale = pooled_scale
            source = "pooled"

        block_kind = "own_history"
        if runs.shape[0] == 0:
            # This source never played the requested run of weeks. Borrowing a run from
            # another player of the same position keeps the persistence the block exists
            # for; splicing unrelated weeks together would not.
            pool, runs = position_pool, position_runs
            block_kind = "position_fallback"
            if runs.shape[0] == 0:
                pool, runs = pooled_standardized, pooled_runs
                block_kind = "pooled_fallback"
            if runs.shape[0] == 0:
                raise ScenarioValidationError(
                    f"No source supplies {horizon} consecutive gameweeks for any player, so "
                    f"no path of that length can be drawn for player {player_id!r}."
                )
        chosen = rng.integers(0, runs.shape[0], size=config.scenario_count)
        selected = runs[chosen]
        for step in range(horizon):
            draws[:, step, column] = pool[selected[:, step]] * effective_scale
        source_counts[source] += 1
        block_sources[block_kind] += 1
        scales[str(player_id)] = effective_scale
    return draws, source_counts, scales, block_sources


__all__ = [
    "SCENARIO_PATH_CONTRACT_VERSION",
    "ScenarioPathSet",
    "ScenarioPathTarget",
    "contiguous_starts",
    "generate_scenario_paths",
    "source_runs",
]
