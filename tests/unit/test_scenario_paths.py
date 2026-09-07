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


def _blanking_history() -> pd.DataFrame:
    """One club sits out each gameweek in rotation, with the shock recoverable exactly.

    Every fold fields the same *number* of clubs and a different *set* of them, which is
    what a fixture calendar around a blank looks like and what a guard comparing club
    counts cannot see. Each fold's residuals are its clubs' centred strengths, so the
    common component is zero, the idiosyncratic component is zero, and a scenario value
    minus the projection is exactly the team shock that club received.
    """

    projection = _snapshot().table
    clubs = sorted(int(value) for value in projection["team_id"].unique())
    strength = {club: 10.0 * index for index, club in enumerate(clubs)}
    records: list[dict[str, object]] = []
    for gameweek in (2, 3, 4, 5, 6, 7):
        present = [club for club in clubs if club != clubs[(gameweek - 2) % len(clubs)]]
        centre = sum(strength[club] for club in present) / len(present)
        for row in projection.itertuples(index=False):
            club = int(row.team_id)
            if club not in present:
                continue
            residual = strength[club] - centre
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


def _fold_shocks(history: pd.DataFrame) -> dict[str, dict[int, float]]:
    """Per fold, the centred shock each club that played carries."""

    shocks: dict[str, dict[int, float]] = {}
    for fold_id, fold in history.groupby("fold_id", sort=True):
        by_club = fold.groupby("team_id", sort=True)["residual"].first()
        centred = by_club.to_numpy(dtype="float64") - by_club.to_numpy(dtype="float64").mean()
        shocks[str(fold_id)] = {
            int(club): float(value) for club, value in zip(by_club.index, centred, strict=True)
        }
    return shocks


def test_a_team_shock_follows_one_club_and_the_diagnostic_counts_what_it_says() -> None:
    """The docstring's claim, asserted: a team block holds a club, not an array position.

    A fold's club set changes whenever a club blanks. Holding a position in that fold's
    sorted clubs silently hands a target club another club's shock at every later step,
    and a guard that compares only club counts never fires, so the loss goes uncounted.
    Here every step's shock must be the step-zero source club's own shock in that week,
    or zero when that club did not play — and `truncated_team_blocks` must count exactly
    the blocks that lost a week that way.
    """

    history = _blanking_history()
    target = ScenarioPathTarget(SEASON, FIRST_GAMEWEEK, 3)
    path = generate_scenario_paths(
        {gameweek: _snapshot(gameweek) for gameweek in target.gameweeks}, history, target, CONFIG
    )
    shocks = _fold_shocks(history)
    # The premise: equal club counts at every step, never the same club set.
    for block in set(path.source_fold_blocks):
        assert len({len(shocks[fold]) for fold in block}) == 1
        assert len({tuple(sorted(shocks[fold])) for fold in block}) > 1

    table = path.projections[FIRST_GAMEWEEK].table
    clubs = sorted(int(value) for value in table["team_id"].unique())
    columns = [int(list(table["team_id"]).index(club)) for club in clubs]
    recovered = [
        path.week(gameweek).to_numpy(dtype="float64")[:, columns]
        - path.projections[gameweek].table["expected_points"].to_numpy(dtype="float64")[columns]
        for gameweek in target.gameweeks
    ]

    truncated = 0
    for scenario, block in enumerate(path.source_fold_blocks):
        first = shocks[block[0]]
        for column in range(len(clubs)):
            drawn = recovered[0][scenario, column]
            source = min(first, key=lambda club: abs(first[club] - drawn))
            assert first[source] == pytest.approx(drawn, abs=1e-9)
            held = True
            for step, fold_id in enumerate(block[1:], start=1):
                expected = shocks[fold_id].get(source, 0.0)
                held &= source in shocks[fold_id]
                assert recovered[step][scenario, column] == pytest.approx(expected, abs=1e-9)
            truncated += int(not held)

    assert truncated > 0, "the fixture must exercise a club that misses a week of its block"
    assert path.diagnostics["truncated_team_blocks"] == truncated


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


# --- the window as one ScenarioSet ---------------------------------------------


def test_the_window_reads_back_as_one_scenario_set() -> None:
    from squadopt.optimization import OptimizationConfig
    from squadopt.scenarios.rank import RankObjectiveConfig, optimize_rank_probability_squad
    from squadopt.scenarios.rivals import template_rival_from_ownership

    path = _three_week_path()
    window = path.as_window_scenario_set()
    assert window.target.gameweek == FIRST_GAMEWEEK
    assert window.diagnostics["window_horizon"] == 3
    assert window.diagnostics["scenario_points_are_window_totals"] is True
    # The matrix is the window total, and the projection is the weekly sum, so the set is
    # centred the way every consumer assumes.
    np.testing.assert_allclose(
        window.scenario_points.to_numpy(dtype="float64"),
        path.window_points().to_numpy(dtype="float64"),
    )
    projected = window.projections.table["expected_points"].to_numpy(dtype="float64")
    weekly_sum = sum(
        path.projections[gameweek].table["expected_points"].to_numpy(dtype="float64")
        for gameweek in path.target.gameweeks
    )
    np.testing.assert_allclose(projected, weekly_sum)
    for block in window.source_fold_ids:
        assert block.count("+") == 2

    # And a single-week consumer runs on it unchanged: the rank objective prices a rival
    # over the whole window without knowing the window exists.
    pool = window.projections.table.loc[:, ["player_id", "position"]].copy()
    pool["ownership"] = window.projections.table["expected_points"]
    rival = template_rival_from_ownership(pool)
    result = optimize_rank_probability_squad(
        window,
        rival,
        OptimizationConfig(solver_time_limit_seconds=20.0),
        RankObjectiveConfig(),
    )
    assert result.has_solution
    assert result.probability_ahead is not None
    assert 0.0 <= result.probability_ahead <= 1.0


def test_a_window_of_one_is_exactly_the_first_week() -> None:
    history = _residual_history()
    path = generate_scenario_paths(
        {FIRST_GAMEWEEK: _snapshot()},
        history,
        ScenarioPathTarget(SEASON, FIRST_GAMEWEEK, 1),
        CONFIG,
    )
    window = path.as_window_scenario_set()
    single = path.as_scenario_set(FIRST_GAMEWEEK)
    assert window.scenario_fingerprint == single.scenario_fingerprint
    assert_frame_equal(window.scenario_points, single.scenario_points)
