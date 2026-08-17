"""Tests for recommending a squad from a captured snapshot.

Every capture here is hand-built and written to a temporary directory, so nothing reads the
network or the archive. The edge cases are the point: a recommendation is acted on with real
money-equivalent stakes, and the cases that break it are new signings, blank histories and
players the source has ruled out.
"""

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

import squadopt.live.report as live_report
from squadopt.data.errors import DataError, DataSourceError
from squadopt.data.snapshots import read_snapshot, write_snapshot
from squadopt.data.sources.fpl_live import BOOTSTRAP_PAYLOAD, FIXTURES_PAYLOAD
from squadopt.live import (
    CONTROL_MODEL_NAME,
    CONTROL_MODEL_VERSION,
    OPENING_FEATURE_CONTRACT_VERSION,
    REPORT_CONTRACT_VERSION,
    LiveResidualHistory,
    LiveRiskBlocker,
    LiveRiskStatus,
    LiveRiskValidationError,
    build_recommendation,
    infer_season,
    project,
    projection_fingerprint,
    read_inputs,
    render,
)
from squadopt.optimization import OptimizationConfig, SolverStatus, optimize_squad
from squadopt.scenarios import ScenarioConfig, ScenarioEvaluationConfig

SEASON = "2026-27"
HISTORY_SEASON = "2025-26"
CAPTURED_AT = "2026-08-13T20:11:43Z"

EVENTS: list[dict[str, Any]] = [
    {"id": 1, "deadline_time": "2026-08-21T17:30:00Z", "finished": False},
    {"id": 2, "deadline_time": "2026-08-28T17:30:00Z", "finished": False},
]
TEAMS: list[dict[str, Any]] = [
    {"id": index, "code": index * 3, "name": f"Club {index}", "short_name": f"C{index}"}
    for index in range(1, 7)
]

# Enough players, spread across clubs, that a fifteen-player squad is feasible under the
# three-per-club limit.
POSITIONS: dict[int, str] = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}
SHAPE: list[tuple[int, int]] = [(1, 3), (2, 8), (3, 8), (4, 5)]


def _elements() -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    code = 1000
    for element_type, count in SHAPE:
        for index in range(count):
            code += 1
            records.append(
                {
                    "code": code,
                    "id": code - 1000,
                    "first_name": "Player",
                    "second_name": f"{code}",
                    "team": (index % 6) + 1,
                    "element_type": element_type,
                    "now_cost": 45 + (index % 4) * 5,
                    "status": "a",
                    "chance_of_playing_next_round": None,
                    "news": "",
                    "news_added": None,
                }
            )
    return records


def _bootstrap(**overrides: Any) -> bytes:
    document: dict[str, Any] = {
        "events": EVENTS,
        "teams": TEAMS,
        "elements": _elements(),
    }
    document.update(overrides)
    return json.dumps(document).encode("utf-8")


def _capture(tmp_path: Path, bootstrap: bytes | None = None, captured_at: str = CAPTURED_AT) -> Any:
    metadata = write_snapshot(
        tmp_path,
        source="fpl-live",
        captured_at_utc=captured_at,
        payloads={
            BOOTSTRAP_PAYLOAD: _bootstrap() if bootstrap is None else bootstrap,
            FIXTURES_PAYLOAD: b"[]",
        },
    )
    return read_snapshot(tmp_path, metadata.snapshot_id)


def _panel(*, players: tuple[int, ...] = (), minutes: int = 90, points: int = 5) -> pd.DataFrame:
    """A completed prior season, so carry-over has something to read."""

    rows: list[dict[str, Any]] = []
    for code in players:
        for gameweek in range(1, 11):
            rows.append(
                {
                    "season": HISTORY_SEASON,
                    "gameweek": gameweek,
                    "player_id": code,
                    "name": f"Player {code}",
                    "team_id": "Club 1",
                    "position": "MID",
                    "price_tenths": 50,
                    "minutes": minutes,
                    "total_points": points,
                }
            )
    if not rows:
        rows.append(
            {
                "season": HISTORY_SEASON,
                "gameweek": 1,
                "player_id": 999_999,
                "name": "Nobody",
                "team_id": "Club 1",
                "position": "MID",
                "price_tenths": 50,
                "minutes": 0,
                "total_points": 0,
            }
        )
    return pd.DataFrame(rows)


def _recommend(tmp_path: Path, **kwargs: Any) -> Any:
    snapshot = kwargs.pop("snapshot", None) or _capture(tmp_path)
    panel = kwargs.pop("panel", None)
    if panel is None:
        panel = _panel(players=(1001, 1004, 1012))
    inputs = read_inputs(snapshot, season=SEASON, gameweek=kwargs.pop("gameweek", None))
    projection = project(inputs, panel)
    return build_recommendation(inputs, projection, **kwargs)


# --- the target deadline ----------------------------------------------------


def test_the_target_is_the_earliest_deadline_still_open_at_capture_time(tmp_path: Path) -> None:
    """Resolved from the capture's instant, not from the clock now."""

    inputs = read_inputs(_capture(tmp_path), season=SEASON)

    assert inputs.deadline.gameweek == 1
    assert inputs.deadline.deadline_utc == "2026-08-21T17:30:00Z"


def test_a_capture_taken_after_the_first_deadline_targets_the_second(tmp_path: Path) -> None:
    inputs = read_inputs(_capture(tmp_path, captured_at="2026-08-22T09:00:00Z"), season=SEASON)

    assert inputs.deadline.gameweek == 2


def test_a_named_gameweek_overrides_the_resolution(tmp_path: Path) -> None:
    inputs = read_inputs(_capture(tmp_path), season=SEASON, gameweek=2)

    assert inputs.deadline.gameweek == 2


def test_a_gameweek_the_capture_does_not_publish_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(DataSourceError, match="publishes no gameweek 38"):
        read_inputs(_capture(tmp_path), season=SEASON, gameweek=38)


def test_the_season_is_derived_from_the_captures_own_deadlines(tmp_path: Path) -> None:
    """A season passed by hand can be wrong, and would join the wrong history."""

    assert infer_season(_capture(tmp_path)) == SEASON


# --- what the projection may and may not do ---------------------------------


def test_a_mid_season_gameweek_is_refused_rather_than_approximated(tmp_path: Path) -> None:
    """Carry-over alone would ignore everything that happened that season."""

    inputs = read_inputs(_capture(tmp_path), season=SEASON, gameweek=2)

    with pytest.raises(DataSourceError, match="needs the current season's played history"):
        project(inputs, _panel(players=(1001,)))


def test_the_projection_names_the_control_not_the_candidate(tmp_path: Path) -> None:
    """Recommending from an unpromoted model would make the gates decorative."""

    inputs = read_inputs(_capture(tmp_path), season=SEASON)

    projection = project(inputs, _panel(players=(1001,)))

    assert projection.diagnostics["model_name"] == CONTROL_MODEL_NAME
    assert projection.diagnostics["projection_source"] == "operational_control"


def test_every_captured_player_is_projected(tmp_path: Path) -> None:
    inputs = read_inputs(_capture(tmp_path), season=SEASON)

    projection = project(inputs, _panel(players=(1001,)))

    assert len(projection.table) == sum(count for _, count in SHAPE)
    assert projection.table["expected_points"].notna().all()
    assert (projection.table["expected_points"] >= 0).all()


def test_a_player_with_history_and_one_without_are_both_projected(tmp_path: Path) -> None:
    """A new signing has no record anywhere and still needs a number."""

    inputs = read_inputs(_capture(tmp_path), season=SEASON)

    projection = project(inputs, _panel(players=(1001,)))

    assert projection.diagnostics["players_with_prior_record"] == 1
    assert projection.diagnostics["players_priced_from_prior"] == len(projection.table) - 1


def test_a_roster_with_no_history_at_all_still_yields_a_squad(tmp_path: Path) -> None:
    """Every player is a debutant, which is a real state at a season's opening."""

    recommendation = _recommend(tmp_path, panel=_panel())

    assert len(recommendation.squad) == 15


# --- availability -----------------------------------------------------------


def test_a_player_the_source_rules_out_is_projected_at_zero(tmp_path: Path) -> None:
    elements = _elements()
    elements[0]["status"] = "i"
    elements[0]["chance_of_playing_next_round"] = 0
    inputs = read_inputs(_capture(tmp_path, _bootstrap(elements=elements)), season=SEASON)

    projection = project(inputs, _panel(players=(1001,)))

    ruled_out = projection.table.loc[projection.table["player_id"] == 1001, "expected_points"]
    assert ruled_out.tolist() == [0.0]
    assert projection.unavailable_players == (1001,)


def test_a_doubtful_player_is_scaled_by_the_stated_chance(tmp_path: Path) -> None:
    """Half a chance of playing is half the projection, and exactly half."""

    panel = _panel(players=(1004,))
    available = project(
        read_inputs(_capture(tmp_path / "a"), season=SEASON), panel
    ).table.set_index("player_id")

    doubtful_elements = _elements()
    doubtful_elements[3]["status"] = "d"
    doubtful_elements[3]["chance_of_playing_next_round"] = 50
    doubtful = project(
        read_inputs(
            _capture(tmp_path / "b", _bootstrap(elements=doubtful_elements)), season=SEASON
        ),
        panel,
    )

    assert doubtful.diagnostics["availability_reduced"] == 1
    assert doubtful.table.set_index("player_id").loc[1004, "expected_points"] == pytest.approx(
        available.loc[1004, "expected_points"] * 0.5
    )
    assert doubtful.table.set_index("player_id").loc[1005, "expected_points"] == pytest.approx(
        available.loc[1005, "expected_points"]
    )


# --- the recommendation -----------------------------------------------------


def test_the_squad_has_fifteen_players_an_eleven_and_a_captain(tmp_path: Path) -> None:
    recommendation = _recommend(tmp_path)

    assert len(recommendation.squad) == 15
    assert len(recommendation.starting_xi) == 11
    assert len(recommendation.bench) == 4
    assert recommendation.captain["name"]


def test_the_squad_stays_within_budget(tmp_path: Path) -> None:
    recommendation = _recommend(tmp_path)

    assert recommendation.total_cost_tenths <= OptimizationConfig().budget_tenths


def test_the_squad_respects_the_per_club_limit(tmp_path: Path) -> None:
    recommendation = _recommend(tmp_path)

    counts = recommendation.squad.groupby("team_id").size()
    assert counts.max() <= OptimizationConfig().max_players_per_team


def test_the_recommendation_carries_its_whole_provenance_chain(tmp_path: Path) -> None:
    """A recommendation nobody can rebuild is indistinguishable from a guess."""

    recommendation = _recommend(tmp_path)

    assert recommendation.snapshot_id
    assert recommendation.captured_at_utc == CAPTURED_AT
    assert recommendation.deadline_utc == "2026-08-21T17:30:00Z"
    assert recommendation.contract_version == REPORT_CONTRACT_VERSION
    assert recommendation.model_name == CONTROL_MODEL_NAME
    assert recommendation.feature_contract_version == OPENING_FEATURE_CONTRACT_VERSION
    assert len(recommendation.prediction_fingerprint) == 64
    assert recommendation.solver_status
    assert recommendation.solver_proved_optimal


def test_an_infeasible_pool_is_refused_rather_than_reported_empty(tmp_path: Path) -> None:
    """A squad that could not be built is not a result to hand back quietly."""

    with pytest.raises(DataError, match="do not admit a solution"):
        _recommend(tmp_path, optimization=OptimizationConfig(budget_tenths=1))


def test_a_feasible_but_unproven_squad_is_not_a_live_recommendation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A partial solve is useful telemetry, but not a proved recommendation."""

    snapshot = _capture(tmp_path)
    inputs = read_inputs(snapshot, season=SEASON)
    projection = project(inputs, _panel(players=(1001, 1004, 1012)))
    pool = projection.table.loc[
        :, ["player_id", "name", "team_id", "position", "price_tenths", "expected_points"]
    ]
    solved = optimize_squad(pool, OptimizationConfig())
    partial = replace(solved, solver_status=SolverStatus.FEASIBLE)
    monkeypatch.setattr(live_report, "optimize_squad", lambda *_args, **_kwargs: partial)

    with pytest.raises(DataSourceError, match="did not prove the squad optimal"):
        build_recommendation(inputs, projection)


# --- replay -----------------------------------------------------------------


def test_the_same_capture_recommends_identically_twice(tmp_path: Path) -> None:
    snapshot = _capture(tmp_path)
    panel = _panel(players=(1001, 1004))

    first = _recommend(tmp_path, snapshot=snapshot, panel=panel)
    second = _recommend(tmp_path, snapshot=snapshot, panel=panel)

    assert first.prediction_fingerprint == second.prediction_fingerprint
    assert render(first) == render(second)


def test_naming_the_open_gameweek_matches_resolving_it(tmp_path: Path) -> None:
    """Replay of the gameweek a capture was taken for reproduces the live answer."""

    snapshot = _capture(tmp_path)
    panel = _panel(players=(1001,))

    live = _recommend(tmp_path, snapshot=snapshot, panel=panel)
    replayed = _recommend(tmp_path, snapshot=snapshot, panel=panel, gameweek=1)

    assert render(live) == render(replayed)


def test_a_changed_projection_changes_the_fingerprint() -> None:
    """The digest must actually depend on the numbers it claims to cover."""

    table = pd.DataFrame(
        [
            {
                "player_id": 1,
                "name": "A",
                "team_id": "Club 1",
                "position": "MID",
                "price_tenths": 50,
                "expected_points": 4.0,
            }
        ]
    )

    assert projection_fingerprint(table) != projection_fingerprint(
        table.assign(expected_points=4.5)
    )


# --- the report -------------------------------------------------------------


def test_the_report_leads_with_provenance(tmp_path: Path) -> None:
    report = render(_recommend(tmp_path))

    assert "snapshot" in report.split("Starting XI")[0]
    assert "captured at" in report.split("Starting XI")[0]
    assert "report contract" in report.split("Starting XI")[0]
    assert "feature contract" in report.split("Starting XI")[0]


def test_the_report_says_which_model_decided_the_squad(tmp_path: Path) -> None:
    report = render(_recommend(tmp_path))

    assert "operational control" in report
    assert "did not clear them" in report


def test_the_report_states_how_much_rests_on_the_prior(tmp_path: Path) -> None:
    report = render(_recommend(tmp_path))

    assert "priced from the prior" in report
    assert "projected from history" in report


# --- live risk evidence -----------------------------------------------------


def _risk_history(
    projection: Any,
    *,
    seasons: tuple[str, ...] = ("2024-25", "2025-26"),
    gameweek: int = 1,
    model_name: str = CONTROL_MODEL_NAME,
    post_processing_contract_version: str = "captured_availability_rule_v1",
) -> LiveResidualHistory:
    rows: list[dict[str, object]] = []
    for season_index, season in enumerate(seasons):
        for row in projection.table.itertuples(index=False):
            residual = float(((int(row.player_id) + season_index) % 5) - 2) / 2.0
            rows.append(
                {
                    "fold_id": f"{season}-gw{gameweek:02d}",
                    "season": season,
                    "gameweek": gameweek,
                    "player_id": row.player_id,
                    "team_id": row.team_id,
                    "position": row.position,
                    "predicted_points": float(row.expected_points),
                    "realized_points": float(row.expected_points) + residual,
                    "residual": residual,
                }
            )
    return LiveResidualHistory(
        pd.DataFrame(rows),
        model_name=model_name,
        model_version=CONTROL_MODEL_VERSION,
        feature_contract_version=OPENING_FEATURE_CONTRACT_VERSION,
        post_processing_contract_version=post_processing_contract_version,
        source_id="synthetic-control-oos-v1",
    )


def _recommend_with_risk(
    tmp_path: Path,
    *,
    history_gameweek: int = 1,
    seasons: tuple[str, ...] = ("2024-25", "2025-26"),
    model_name: str = CONTROL_MODEL_NAME,
    post_processing_contract_version: str = "captured_availability_rule_v1",
) -> Any:
    inputs = read_inputs(_capture(tmp_path), season=SEASON)
    projection = project(inputs, _panel(players=(1001, 1004, 1012)))
    history = _risk_history(
        projection,
        seasons=seasons,
        gameweek=history_gameweek,
        model_name=model_name,
        post_processing_contract_version=post_processing_contract_version,
    )
    return build_recommendation(
        inputs,
        projection,
        risk_history=history,
        risk_scenario_config=ScenarioConfig(
            scenario_count=64,
            min_history_folds=2,
            min_player_observations=2,
        ),
        risk_evaluation_config=ScenarioEvaluationConfig(points_threshold=40.0),
    )


def test_no_residual_input_returns_structured_not_requested_risk(tmp_path: Path) -> None:
    recommendation = _recommend(tmp_path)

    assert recommendation.risk.status is LiveRiskStatus.NOT_REQUESTED
    assert recommendation.risk.metrics is None
    assert "No lower-tail number is printed" in render(recommendation)


def test_midseason_residuals_do_not_support_opening_gameweek_risk(
    tmp_path: Path,
) -> None:
    recommendation = _recommend_with_risk(tmp_path, history_gameweek=2)

    assert recommendation.risk.status is LiveRiskStatus.UNAVAILABLE
    assert LiveRiskBlocker.UNSUPPORTED_OPENING_GAMEWEEK in recommendation.risk.blockers
    assert LiveRiskBlocker.INSUFFICIENT_HISTORY in recommendation.risk.blockers
    assert recommendation.risk.metrics is None
    assert "Midseason residuals do not support opening-gameweek risk" in render(recommendation)


def test_model_mismatch_is_reported_alongside_the_opening_blocker(
    tmp_path: Path,
) -> None:
    recommendation = _recommend_with_risk(
        tmp_path,
        history_gameweek=2,
        model_name="unpromoted-candidate",
    )

    assert recommendation.risk.blockers == (
        LiveRiskBlocker.MODEL_MISMATCH,
        LiveRiskBlocker.UNSUPPORTED_OPENING_GAMEWEEK,
        LiveRiskBlocker.INSUFFICIENT_HISTORY,
    )


def test_too_few_matching_opening_folds_are_reported_not_fabricated(
    tmp_path: Path,
) -> None:
    recommendation = _recommend_with_risk(tmp_path, seasons=("2025-26",))

    assert recommendation.risk.status is LiveRiskStatus.UNAVAILABLE
    assert recommendation.risk.blockers == (LiveRiskBlocker.INSUFFICIENT_HISTORY,)
    assert recommendation.risk.metrics is None


def test_availability_post_processing_must_match_the_residual_history(
    tmp_path: Path,
) -> None:
    recommendation = _recommend_with_risk(
        tmp_path,
        post_processing_contract_version="no-availability-v1",
    )

    assert recommendation.risk.status is LiveRiskStatus.UNAVAILABLE
    assert recommendation.risk.blockers == (LiveRiskBlocker.MODEL_MISMATCH,)


def test_matching_opening_residuals_produce_all_requested_risk_metrics(
    tmp_path: Path,
) -> None:
    recommendation = _recommend_with_risk(tmp_path)
    risk = recommendation.risk

    assert risk.status is LiveRiskStatus.AVAILABLE
    assert risk.blockers == ()
    assert risk.metrics is not None
    assert risk.metrics.scenario_count == 64
    assert 0.0 <= risk.metrics.probability_below_threshold <= 1.0
    report = render(recommendation)
    assert "lower 10% quantile" in report
    assert "mean worst 10%" in report
    assert "P(score < 40)" in report
    # An available lower tail states the limit of the evidence behind it: the residual
    # history is calendar-blind, so a double gameweek's tail is optimistic.
    limits = risk.diagnostics["stated_limits"]
    assert isinstance(limits, list) and any("double gameweek" in limit for limit in limits)
    assert "stated limit" in report and "calendar-blind" in report


def test_available_risk_names_and_fingerprints_its_residual_input(
    tmp_path: Path,
) -> None:
    first = _recommend_with_risk(tmp_path / "first")
    second = _recommend_with_risk(tmp_path / "second")

    assert first.risk.residual_provenance["source_id"] == "synthetic-control-oos-v1"
    assert len(str(first.risk.residual_provenance["residual_fingerprint"])) == 64
    assert first.risk.scenario_fingerprint == second.risk.scenario_fingerprint
    assert first.risk.metrics == second.risk.metrics


def test_live_residual_history_copies_input_and_rejects_missing_columns() -> None:
    table = pd.DataFrame({"fold_id": ["2025-26-gw01"]})

    with pytest.raises(LiveRiskValidationError, match="missing columns"):
        LiveResidualHistory(
            table,
            model_name=CONTROL_MODEL_NAME,
            model_version=CONTROL_MODEL_VERSION,
            feature_contract_version=OPENING_FEATURE_CONTRACT_VERSION,
            post_processing_contract_version="captured_availability_rule_v1",
            source_id="broken",
        )
