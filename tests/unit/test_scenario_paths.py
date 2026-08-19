"""Multi-week scenario paths: the block rule, the fallbacks, and the horizon-one equivalence.

The equivalence test is the load-bearing one. If a path of length one is not bit-for-bit the
existing generator, every calibration result recorded against that generator would have to be
re-validated before paths could be used anywhere.
"""

import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal
from tests.fixtures.synthetic_gameweeks import SEASON, make_canonical_gameweeks

from squadopt.backtest import DecisionPoint, baseline_projection_builder, rows_through
from squadopt.prediction import (
    PredictionProvenance,
    PredictionSnapshot,
    prepare_optimizer_projection,
)
from squadopt.scenarios import ScenarioConfig, ScenarioTarget, generate_scenarios
from squadopt.scenarios.models import ScenarioValidationError
from squadopt.scenarios.paths import (
    SCENARIO_PATH_CONTRACT_VERSION,
    ScenarioPathTarget,
    contiguous_starts,
    generate_scenario_paths,
)

FIRST_GAMEWEEK = 8
CONFIG = ScenarioConfig(
    scenario_count=200,
    deterministic_seed=19,
    min_history_folds=5,
    min_player_observations=3,
    player_scale_shrinkage=4.0,
)


def _snapshot(
    gameweek: int = FIRST_GAMEWEEK, *, drop_first_player: bool = False
) -> PredictionSnapshot:
    panel = make_canonical_gameweeks()
    decision = DecisionPoint(SEASON, FIRST_GAMEWEEK)
    projection = baseline_projection_builder(rows_through(panel, decision), decision)
    if drop_first_player:
        projection = projection.iloc[1:].reset_index(drop=True)
    provenance = PredictionProvenance(
        model_name="synthetic-path-model",
        model_version="1.0.0",
        feature_contract_version="synthetic-path-features-v1",
        training_cutoff=f"{SEASON}:GW{FIRST_GAMEWEEK - 1:02d}",
        training_data_fingerprint="b" * 64,
    )
    if gameweek != FIRST_GAMEWEEK:
        # A later week of the same window: the same pool, a slightly different expectation.
        projection = projection.copy(deep=True)
        projection["expected_points"] = projection["expected_points"] * (
            1.0 + 0.05 * (gameweek - FIRST_GAMEWEEK)
        )
    return prepare_optimizer_projection(
        projection.drop(columns="expected_points"),
        projection.loc[:, ["player_id", "expected_points"]],
        provenance,
    )


def _residual_history(
    *,
    gameweeks: tuple[int, ...] = (2, 3, 4, 5, 6, 7),
    trending: bool = True,
    alternating: bool = False,
) -> pd.DataFrame:
    """A history with a team effect, a player effect, and optionally a league-wide trend.

    The trend is what makes the block edge effect visible; ``trending=False`` gives the
    stationary pool the edge effect is claimed to cost nothing on.
    """

    projection = _snapshot()
    position_effect = {"GK": -0.3, "DEF": -0.1, "MID": 0.1, "FWD": 0.3}
    records: list[dict[str, object]] = []
    for gameweek in gameweeks:
        if alternating:
            # Negatively autocorrelated: a good week is followed by a bad one, which is the
            # shape the control's real residuals turn out to have.
            common = 3.0 if gameweek % 2 == 0 else -3.0
        else:
            common = (float(gameweek) - 4.0) if trending else 0.0
        for row in projection.table.itertuples(index=False):
            team_effect = ((int(row.team_id) * 3 + gameweek) % 7 - 3) * 0.7
            player_effect = ((int(row.player_id) + gameweek * 2) % 5 - 2) * 0.2
            residual = common + team_effect + position_effect[str(row.position)] + player_effect
            predicted = float(row.expected_points)
            records.append(
                {
                    "fold_id": f"{SEASON}-gw{gameweek:02d}",
                    "season": SEASON,
                    "gameweek": gameweek,
                    "player_id": row.player_id,
                    "team_id": row.team_id,
                    "position": row.position,
                    "predicted_points": predicted,
                    "realized_points": predicted + residual,
                    "residual": residual,
                }
            )
    return pd.DataFrame.from_records(records)


# --- the equivalence that lets this be adopted ---------------------------------


def test_a_horizon_of_one_reproduces_the_existing_generator_exactly() -> None:
    history = _residual_history()
    snapshot = _snapshot()
    single = generate_scenarios(snapshot, history, ScenarioTarget(SEASON, FIRST_GAMEWEEK), CONFIG)
    path = generate_scenario_paths(
        {FIRST_GAMEWEEK: snapshot},
        history,
        ScenarioPathTarget(SEASON, FIRST_GAMEWEEK, 1),
        CONFIG,
    )
    assert_frame_equal(path.week(FIRST_GAMEWEEK), single.scenario_points)
    assert path.scenario_ids == single.scenario_ids
    assert tuple(block[0] for block in path.source_fold_blocks) == single.source_fold_ids


def test_a_horizon_of_one_reproduces_the_existing_fingerprint() -> None:
    history = _residual_history()
    snapshot = _snapshot()
    single = generate_scenarios(snapshot, history, ScenarioTarget(SEASON, FIRST_GAMEWEEK), CONFIG)
    path = generate_scenario_paths(
        {FIRST_GAMEWEEK: snapshot},
        history,
        ScenarioPathTarget(SEASON, FIRST_GAMEWEEK, 1),
        CONFIG,
    )
    rebuilt = path.as_scenario_set(FIRST_GAMEWEEK)
    assert rebuilt.scenario_fingerprint == single.scenario_fingerprint
    assert_frame_equal(rebuilt.scenario_points, single.scenario_points)


# --- the block rule ------------------------------------------------------------


def test_blocks_never_cross_a_season_boundary_or_skip_a_gameweek() -> None:
    seasons = np.array(["A", "A", "A", "B", "B", "B"], dtype=object)
    gameweeks = np.array([1, 2, 4, 1, 2, 3], dtype="int64")
    assert list(contiguous_starts(seasons, gameweeks, 1)) == [0, 1, 2, 3, 4, 5]
    # 0-1 is contiguous; 1-2 skips gameweek three; 2-3 crosses into season B.
    assert list(contiguous_starts(seasons, gameweeks, 2)) == [0, 3, 4]
    assert list(contiguous_starts(seasons, gameweeks, 3)) == [3]
    assert contiguous_starts(seasons, gameweeks, 4).size == 0


def test_a_history_with_no_run_of_the_requested_length_is_refused() -> None:
    history = _residual_history(gameweeks=(2, 4, 6))
    with pytest.raises(ScenarioValidationError, match="no run of 2 consecutive"):
        generate_scenario_paths(
            {FIRST_GAMEWEEK: _snapshot(), FIRST_GAMEWEEK + 1: _snapshot(FIRST_GAMEWEEK + 1)},
            history,
            ScenarioPathTarget(SEASON, FIRST_GAMEWEEK, 2),
            ScenarioConfig(
                scenario_count=50,
                deterministic_seed=19,
                min_history_folds=3,
                min_player_observations=3,
                player_scale_shrinkage=4.0,
            ),
        )


def test_every_scenario_draws_one_contiguous_run_of_folds() -> None:
    path = _three_week_path()
    for block in path.source_fold_blocks:
        weeks = [int(fold.rsplit("gw", 1)[1]) for fold in block]
        assert weeks == list(range(weeks[0], weeks[0] + 3))
        assert len({fold.rsplit("-gw", 1)[0] for fold in block}) == 1


def _three_week_path(*, trending: bool = True, alternating: bool = False):
    history = _residual_history(trending=trending, alternating=alternating)
    target = ScenarioPathTarget(SEASON, FIRST_GAMEWEEK, 3)
    return generate_scenario_paths(
        {gameweek: _snapshot(gameweek) for gameweek in target.gameweeks},
        history,
        target,
        CONFIG,
    )


# --- what a path is, and what it is for ----------------------------------------


def test_a_path_covers_every_week_of_its_window() -> None:
    path = _three_week_path()
    assert path.horizon == 3
    assert set(path.weekly_points) == {FIRST_GAMEWEEK, FIRST_GAMEWEEK + 1, FIRST_GAMEWEEK + 2}
    assert path.contract_version == SCENARIO_PATH_CONTRACT_VERSION
    assert path.target.window_id.endswith("gw08-gw10")
    for gameweek in path.target.gameweeks:
        assert path.week(gameweek).shape == (
            CONFIG.scenario_count,
            len(path.projections[gameweek].table),
        )


def test_the_window_total_is_the_sum_of_its_weeks() -> None:
    path = _three_week_path()
    total = path.window_points()
    expected = sum(
        (path.week(gameweek) for gameweek in path.target.gameweeks[1:]),
        start=path.week(path.target.first_gameweek),
    )
    assert_frame_equal(total, expected)


def test_each_week_carries_its_own_projection() -> None:
    """A later week is projected differently, and the path must move with it.

    Levels are not compared directly: with a horizon of three the first week can only be
    drawn from folds that have two weeks after them, so a history with a trend shifts every
    week of the window. The difference between two weeks is free of that shift, because both
    weeks of one path move together.
    """

    path = _three_week_path(trending=False)
    first = path.target.first_gameweek
    base_projection = path.projections[first].table["expected_points"].to_numpy(dtype="float64")
    base_mean = path.week(first).to_numpy(dtype="float64").mean(axis=0)
    for gameweek in path.target.gameweeks[1:]:
        projected = path.projections[gameweek].table["expected_points"].to_numpy(dtype="float64")
        realized_mean = path.week(gameweek).to_numpy(dtype="float64").mean(axis=0)
        expected_step = projected - base_projection
        observed_step = realized_mean - base_mean
        assert float(np.abs(observed_step - expected_step).mean()) < 0.5
        assert float(expected_step.mean()) > 0.0


def test_the_diagnostics_expose_the_block_edge_effect() -> None:
    """A trending history shifts each week of a block; the numbers must say so."""

    trending = list(_three_week_path().diagnostics["common_block_week_means"])
    assert len(trending) == 3
    assert trending[0] < trending[-1]
    # And the claim the docstring makes: on a stationary pool the shift all but disappears.
    # It does not vanish exactly, because a fold's residual mean is not exactly zero even
    # when nothing generated a trend; what matters is the order of magnitude.
    stationary = list(_three_week_path(trending=False).diagnostics["common_block_week_means"])
    trending_spread = max(trending) - min(trending)
    stationary_spread = max(stationary) - min(stationary)
    assert trending_spread > 1.0
    assert stationary_spread < trending_spread / 5.0


def _window_spread_against_independence(path) -> float:
    """The window's own spread over the spread its weeks would have if independent."""

    total = path.window_points().to_numpy(dtype="float64")
    weekly = [path.week(gameweek).to_numpy(dtype="float64") for gameweek in path.target.gameweeks]
    independent = float(np.sqrt(sum(week.std(axis=0) ** 2 for week in weekly)).mean())
    return float(total.std(axis=0).mean()) / independent


def test_a_path_transmits_the_dependence_its_history_actually_has() -> None:
    """Both directions, because the real data runs the opposite way to the intuition.

    A trending history is positively autocorrelated and a path over it is wider than
    independent weeks; an alternating history is negatively autocorrelated and a path over it
    is narrower. On the control's real residuals the measured ratio is 0.983 — see
    `docs/scenario_path_dependence.md` — so a test that only asserted "wider" would have been
    encoding an assumption rather than the machinery.
    """

    assert _window_spread_against_independence(_three_week_path()) > 1.0
    assert _window_spread_against_independence(_three_week_path(alternating=True)) < 1.0


def test_a_week_reads_back_as_an_ordinary_scenario_set() -> None:
    path = _three_week_path()
    middle = path.as_scenario_set(FIRST_GAMEWEEK + 1)
    assert middle.target.gameweek == FIRST_GAMEWEEK + 1
    assert middle.config is path.config
    assert_frame_equal(middle.scenario_points, path.week(FIRST_GAMEWEEK + 1))
    assert middle.diagnostics["path_horizon"] == 3
    assert middle.diagnostics["drawn_as_path_week"] == 1


def test_generation_is_deterministic() -> None:
    first = _three_week_path()
    second = _three_week_path()
    assert first.path_fingerprint == second.path_fingerprint
    for gameweek in first.target.gameweeks:
        assert_frame_equal(first.week(gameweek), second.week(gameweek))


def test_the_fingerprint_moves_when_the_horizon_does() -> None:
    history = _residual_history()
    one = generate_scenario_paths(
        {FIRST_GAMEWEEK: _snapshot()},
        history,
        ScenarioPathTarget(SEASON, FIRST_GAMEWEEK, 1),
        CONFIG,
    )
    assert one.path_fingerprint != _three_week_path().path_fingerprint


# --- what it refuses -----------------------------------------------------------


def test_a_window_missing_a_projection_is_refused() -> None:
    target = ScenarioPathTarget(SEASON, FIRST_GAMEWEEK, 3)
    with pytest.raises(ScenarioValidationError, match="carry no gameweek"):
        generate_scenario_paths({FIRST_GAMEWEEK: _snapshot()}, _residual_history(), target, CONFIG)


def test_a_projection_outside_the_window_is_refused() -> None:
    target = ScenarioPathTarget(SEASON, FIRST_GAMEWEEK, 1)
    with pytest.raises(ScenarioValidationError, match="outside the window"):
        generate_scenario_paths(
            {FIRST_GAMEWEEK: _snapshot(), 99: _snapshot()},
            _residual_history(),
            target,
            CONFIG,
        )


def test_a_pool_that_changes_mid_window_is_refused() -> None:
    target = ScenarioPathTarget(SEASON, FIRST_GAMEWEEK, 2)
    shortened = _snapshot(FIRST_GAMEWEEK + 1, drop_first_player=True)
    with pytest.raises(ScenarioValidationError, match="different player pool"):
        generate_scenario_paths(
            {FIRST_GAMEWEEK: _snapshot(), FIRST_GAMEWEEK + 1: shortened},
            _residual_history(),
            target,
            CONFIG,
        )


@pytest.mark.parametrize(
    ("season", "first_gameweek", "horizon"),
    [("", 8, 1), ("  ", 8, 1), (SEASON, 0, 1), (SEASON, 8, 0)],
)
def test_a_nonsense_window_is_refused(season: str, first_gameweek: int, horizon: int) -> None:
    with pytest.raises(ScenarioValidationError):
        ScenarioPathTarget(season, first_gameweek, horizon)


def test_a_gameweek_outside_the_window_cannot_be_read() -> None:
    path = _three_week_path()
    with pytest.raises(ScenarioValidationError, match="outside this window"):
        path.week(99)
    with pytest.raises(ScenarioValidationError, match="outside this window"):
        path.target.week_target(99)


def test_the_diagnostics_say_how_the_blocks_were_sourced() -> None:
    path = _three_week_path()
    diagnostics = path.diagnostics
    assert diagnostics["horizon"] == 3
    assert diagnostics["block_rule"] == "same_season_consecutive_gameweeks_source_identity_held"
    assert diagnostics["contiguous_block_starts"] >= 1
    sources = dict(diagnostics["idiosyncratic_block_sources"])
    assert sum(sources.values()) == len(path.projections[FIRST_GAMEWEEK].table)
    assert set(sources) == {"own_history", "position_fallback", "pooled_fallback"}


def test_a_player_with_no_run_of_his_own_borrows_one_from_his_position() -> None:
    """The case real data hit first: a position pool's next row is a different player.

    A pool is not one row per week, so a run has to be the same player at the next fold.
    Before that was true, any player short of his own contiguous run made generation fail.
    """

    history = _residual_history()
    snapshot = _snapshot()
    intermittent = snapshot.table["player_id"].iloc[0]
    # He has three observations, so he clears min_player_observations and is fitted on his
    # own pool -- but they fall in weeks 2, 4 and 6, so no run of three exists for him.
    keep = (history["player_id"] != intermittent) | history["gameweek"].isin((2, 4, 6))
    history = history.loc[keep].reset_index(drop=True)

    target = ScenarioPathTarget(SEASON, FIRST_GAMEWEEK, 3)
    path = generate_scenario_paths(
        {gameweek: _snapshot(gameweek) for gameweek in target.gameweeks},
        history,
        target,
        CONFIG,
    )
    sources = dict(path.diagnostics["idiosyncratic_block_sources"])
    assert sources["position_fallback"] >= 1
    assert sources["own_history"] >= 1
    for gameweek in target.gameweeks:
        assert np.isfinite(path.week(gameweek).to_numpy(dtype="float64")).all()
