"""Tests for the multi-gameweek projection horizon builder.

The capture helpers are imported from the live recommendation tests rather than rebuilt,
because one of the claims here is that a single-gameweek horizon reproduces the existing
live projection exactly — a claim that is only meaningful if both are fed the same
capture.

What the tests spend their effort on is the calendar. The captured 2026-27 calendar is
uniform (every club has exactly one fixture in all 38 gameweeks at capture time, measured
against the real snapshot), so blanks and doubles only appear later in a season as
fixtures are rescheduled. Real data therefore cannot exercise the cases that matter most,
and a synthetic calendar has to.
"""

import json
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from tests.unit.test_live_recommendation import (
    CAPTURED_AT,
    HISTORY_SEASON,
    SEASON,
    _bootstrap,
    _elements,
    _panel,
)

from squadopt.data.errors import DataSourceError
from squadopt.data.snapshots import read_snapshot, write_snapshot
from squadopt.data.sources.fpl_live import BOOTSTRAP_PAYLOAD, FIXTURES_PAYLOAD
from squadopt.live.horizon import (
    HORIZON_POST_PROCESSING_CONTRACT_VERSION,
    build_projection_horizon,
    gameweek_fixture_fingerprints,
    make_projection_horizon_builder,
)
from squadopt.live.recommendation import InSeasonProjection, project, read_inputs
from squadopt.planning.horizon import PROJECTION_HORIZON_COLUMNS, to_planning_horizon
from squadopt.prediction.in_season import (
    IN_SEASON_FEATURE_CONTRACT_VERSION,
    IN_SEASON_MODEL_VERSION,
)

CLUBS = tuple(range(1, 7))
PLAYER_CODES = tuple(record["code"] for record in _elements())


def _fixture(identifier: int, gameweek: int, home: int, away: int) -> dict[str, Any]:
    return {
        "id": identifier,
        "event": gameweek,
        "team_h": home,
        "team_a": away,
        "team_h_difficulty": 2,
        "team_a_difficulty": 3,
        "kickoff_time": "2026-08-22T14:00:00Z",
        "finished": False,
        "provisional_start_time": False,
    }


def _calendar(
    *,
    blank_club: int | None = None,
    double_club: int | None = None,
    gameweeks: tuple[int, ...] = (1, 2),
) -> bytes:
    """Two gameweeks of fixtures, with an optional blank and an optional double in GW2.

    GW1 pairs every club once. GW2 does the same, then drops the blank club's fixture and
    adds a second one for the double club, which is exactly how a rescheduled match makes
    a calendar uneven.
    """

    records: list[dict[str, Any]] = []
    identifier = 0
    for gameweek in gameweeks:
        for home, away in ((1, 2), (3, 4), (5, 6)):
            if gameweek == 2 and blank_club in (home, away):
                continue
            identifier += 1
            records.append(_fixture(identifier, gameweek, home, away))
    if double_club is not None:
        identifier += 1
        opponent = 6 if double_club != 6 else 5
        records.append(_fixture(identifier, 2, double_club, opponent))
    return json.dumps(records).encode("utf-8")


def _capture(
    tmp_path: Path,
    *,
    fixtures: bytes | None = None,
    bootstrap: bytes | None = None,
    captured_at: str = CAPTURED_AT,
) -> Any:
    metadata = write_snapshot(
        tmp_path,
        source="fpl-live",
        captured_at_utc=captured_at,
        payloads={
            BOOTSTRAP_PAYLOAD: _bootstrap() if bootstrap is None else bootstrap,
            FIXTURES_PAYLOAD: _calendar() if fixtures is None else fixtures,
        },
    )
    return read_snapshot(tmp_path, metadata.snapshot_id)


def _history() -> pd.DataFrame:
    return _panel(players=PLAYER_CODES)


def _in_season_handoff(capture: Any, *, gameweek: int = 2) -> InSeasonProjection:
    return InSeasonProjection(
        season=SEASON,
        gameweek=gameweek,
        source_snapshot_id=capture.metadata.snapshot_id,
        model_name="squadopt-deterministic-baseline",
        model_version=IN_SEASON_MODEL_VERSION,
        feature_contract_version=IN_SEASON_FEATURE_CONTRACT_VERSION,
        expected_points={
            int(player): 1.0 + index / 100.0 for index, player in enumerate(PLAYER_CODES)
        },
    )


def _horizon(tmp_path: Path, gameweeks: tuple[int, ...] = (1, 2), **kwargs: Any) -> Any:
    return build_projection_horizon(
        _capture(tmp_path, fixtures=kwargs.pop("fixtures", None)),
        gameweeks,
        panel=_history(),
        season=SEASON,
        **kwargs,
    )


# --- the contract the planner accepts ---------------------------------------


def test_the_horizon_satisfies_the_planner_s_contract(tmp_path: Path) -> None:
    horizon = _horizon(tmp_path)

    assert tuple(horizon.table.columns) == PROJECTION_HORIZON_COLUMNS
    assert horizon.target_gameweeks == (1, 2)
    assert horizon.season == SEASON
    assert len(horizon.horizon_fingerprint) == 64


def test_the_provenance_names_the_operational_control(tmp_path: Path) -> None:
    """An unpromoted candidate reaching a plan would be the same defect as in a squad."""

    horizon = _horizon(tmp_path)

    assert horizon.model_name == "squadopt-deterministic-baseline"
    assert horizon.post_processing_contract_version == HORIZON_POST_PROCESSING_CONTRACT_VERSION


def test_the_post_processing_contract_names_the_scaling_rule(tmp_path: Path) -> None:
    """The calendar rule sits outside a calendar-blind model and must say so."""

    horizon = _horizon(tmp_path)

    assert "captured_availability_rule_v1" in horizon.post_processing_contract_version
    assert (
        "first_week_control_future_fixture_scaling_v2" in horizon.post_processing_contract_version
    )


def test_the_horizon_converts_to_a_planning_horizon(tmp_path: Path) -> None:
    horizon = _horizon(tmp_path)

    planning = to_planning_horizon(horizon)

    assert len(planning.table) == len(horizon.table)
    assert (planning.table["buy_price_tenths"] == planning.table["sell_price_tenths"]).all()


# --- one information state --------------------------------------------------


def test_one_gameweek_reproduces_the_live_projection_exactly(tmp_path: Path) -> None:
    """The central check. If these disagree on a shared gameweek, the horizon is wrong."""

    capture = _capture(tmp_path)
    panel = _history()
    live = project(read_inputs(capture, season=SEASON, gameweek=1), panel).table
    horizon = build_projection_horizon(capture, (1,), panel=panel, season=SEASON)

    merged = horizon.table.merge(
        live.loc[:, ["player_id", "expected_points"]],
        on="player_id",
        suffixes=("_horizon", "_live"),
    )

    assert len(merged) == len(live)
    difference = (merged["expected_points_horizon"] - merged["expected_points_live"]).abs()
    assert float(difference.max()) == 0.0


def test_a_uniform_calendar_projects_every_gameweek_identically(tmp_path: Path) -> None:
    """Not a defect: at capture time a season's published calendar has no blanks."""

    horizon = _horizon(tmp_path)

    totals = horizon.table.groupby("gameweek")["expected_points"].sum()
    assert float(totals.max() - totals.min()) == pytest.approx(0.0)


# --- the calendar -----------------------------------------------------------


def test_a_blank_gameweek_projects_exactly_zero(tmp_path: Path) -> None:
    horizon = _horizon(tmp_path, fixtures=_calendar(blank_club=1))

    blank = horizon.table.loc[
        (horizon.table["gameweek"] == 2) & (horizon.table["fixture_count"] == 0)
    ]

    assert not blank.empty
    assert float(blank["expected_points"].abs().max()) == 0.0


def test_a_blank_club_keeps_its_players_in_the_table(tmp_path: Path) -> None:
    """Dropping them would turn 'cannot score' into 'does not exist'."""

    horizon = _horizon(tmp_path, fixtures=_calendar(blank_club=1))

    first = set(horizon.table.loc[horizon.table["gameweek"] == 1, "player_id"])
    second = set(horizon.table.loc[horizon.table["gameweek"] == 2, "player_id"])

    assert first == second


def test_a_double_gameweek_scales_the_projection(tmp_path: Path) -> None:
    horizon = _horizon(tmp_path, fixtures=_calendar(double_club=1))

    table = horizon.table
    doubled = table.loc[(table["gameweek"] == 2) & (table["fixture_count"] == 2)]
    assert not doubled.empty

    single = table.loc[(table["gameweek"] == 1) & table["player_id"].isin(doubled["player_id"])]
    pairs = doubled.merge(single, on="player_id", suffixes=("_double", "_single"))
    ratio = pairs["expected_points_double"] / pairs["expected_points_single"].where(
        pairs["expected_points_single"] > 0.0
    )

    assert float(ratio.dropna().min()) == pytest.approx(2.0)


def test_home_fixture_count_never_exceeds_fixture_count(tmp_path: Path) -> None:
    horizon = _horizon(tmp_path, fixtures=_calendar(double_club=1))

    table = horizon.table
    assert not bool((table["home_fixture_count"] > table["fixture_count"]).any())


def test_each_gameweek_carries_its_own_fixture_fingerprint(tmp_path: Path) -> None:
    """Two plans differing only at gameweek four should differ at gameweek four."""

    from squadopt.data.fixtures import aggregate_team_gameweek
    from squadopt.data.sources.fpl_live import fixture_snapshot

    capture = _capture(tmp_path, fixtures=_calendar(double_club=1))
    calendar = aggregate_team_gameweek(
        fixture_snapshot(
            capture.payloads[FIXTURES_PAYLOAD],
            capture.payloads[BOOTSTRAP_PAYLOAD],
            season=SEASON,
            snapshot_id=capture.metadata.snapshot_id,
            captured_at_utc=capture.metadata.captured_at_utc,
        )
    )

    fingerprints = gameweek_fixture_fingerprints(calendar, (1, 2))

    assert set(fingerprints) == {1, 2}
    assert fingerprints[1] != fingerprints[2]
    assert all(len(value) == 64 for value in fingerprints.values())


# --- the requested gameweeks ------------------------------------------------


def test_a_gap_in_the_requested_gameweeks_is_refused(tmp_path: Path) -> None:
    """A missing gameweek is ambiguous: skipped, or blank? Those are different plans."""

    with pytest.raises(DataSourceError, match="consecutive"):
        _horizon(tmp_path, (1, 3))


def test_a_repeated_gameweek_is_refused(tmp_path: Path) -> None:
    with pytest.raises(DataSourceError, match="repeat"):
        _horizon(tmp_path, (1, 1, 2))


@pytest.mark.parametrize("gameweeks", [(), (0,), (-1,)])
def test_an_invalid_gameweek_request_is_refused(tmp_path: Path, gameweeks: tuple[int, ...]) -> None:
    with pytest.raises(DataSourceError):
        _horizon(tmp_path, gameweeks)


# --- leakage ----------------------------------------------------------------


def test_a_later_capture_instant_is_a_different_horizon(tmp_path: Path) -> None:
    """The capture instant is the information state; two instants are two states."""

    early = build_projection_horizon(
        _capture(tmp_path / "a", captured_at=CAPTURED_AT), (1, 2), panel=_history(), season=SEASON
    )
    late = build_projection_horizon(
        _capture(tmp_path / "b", captured_at="2026-08-20T20:11:43Z"),
        (1, 2),
        panel=_history(),
        season=SEASON,
    )

    assert early.source_snapshot_id != late.source_snapshot_id


def test_history_after_the_decision_season_does_not_change_the_horizon(tmp_path: Path) -> None:
    """A mutation test: the panel is completed history and nothing later may reach it."""

    capture = _capture(tmp_path)
    panel = _history()
    perturbed = panel.copy(deep=True)
    perturbed.loc[perturbed["season"] == HISTORY_SEASON, "total_points"] = 99

    baseline = build_projection_horizon(capture, (1, 2), panel=panel, season=SEASON)
    changed = build_projection_horizon(capture, (1, 2), panel=perturbed, season=SEASON)

    assert baseline.horizon_fingerprint != changed.horizon_fingerprint


def test_two_builds_of_one_horizon_are_identical(tmp_path: Path) -> None:
    capture = _capture(tmp_path)
    panel = _history()

    first = build_projection_horizon(capture, (1, 2), panel=panel, season=SEASON)
    second = build_projection_horizon(capture, (1, 2), panel=panel, season=SEASON)

    assert first.horizon_fingerprint == second.horizon_fingerprint


# --- the bound builder ------------------------------------------------------


def test_the_bound_builder_satisfies_the_protocol_signature(tmp_path: Path) -> None:
    """The planner should not have to know a projection needs a historical panel."""

    capture = _capture(tmp_path)
    panel = _history()
    builder = make_projection_horizon_builder(panel, season=SEASON)

    built = builder(capture, (1, 2))

    direct = build_projection_horizon(capture, (1, 2), panel=panel, season=SEASON)
    assert built.horizon_fingerprint == direct.horizon_fingerprint


def test_a_capture_without_a_fixtures_payload_is_refused(tmp_path: Path) -> None:
    metadata = write_snapshot(
        tmp_path,
        source="fpl-live",
        captured_at_utc=CAPTURED_AT,
        payloads={BOOTSTRAP_PAYLOAD: _bootstrap()},
    )
    capture = read_snapshot(tmp_path, metadata.snapshot_id)

    with pytest.raises(DataSourceError, match=FIXTURES_PAYLOAD):
        build_projection_horizon(capture, (1,), panel=_history(), season=SEASON)


def test_a_horizon_starting_after_the_opening_gameweek_needs_a_handoff(tmp_path: Path) -> None:
    """Moving the decision point without current-season history remains forbidden."""

    with pytest.raises(DataSourceError, match="needs the current season's played history"):
        _horizon(tmp_path, (2,))


@pytest.mark.parametrize("fixtures", [_calendar(), _calendar(double_club=1)])
def test_a_midseason_horizon_matches_the_live_projection_at_its_first_week(
    tmp_path: Path,
    fixtures: bytes,
) -> None:
    capture = _capture(tmp_path, fixtures=fixtures)
    handoff = _in_season_handoff(capture)
    live = project(
        read_inputs(capture, season=SEASON, gameweek=2),
        in_season=handoff,
    ).table

    horizon = build_projection_horizon(
        capture,
        (2,),
        season=SEASON,
        in_season=handoff,
    )
    merged = horizon.table.merge(
        live.loc[:, ["player_id", "expected_points"]],
        on="player_id",
        suffixes=("_horizon", "_live"),
    )

    assert len(merged) == len(live)
    difference = (merged["expected_points_horizon"] - merged["expected_points_live"]).abs()
    assert float(difference.max()) == 0.0
    assert horizon.model_version == IN_SEASON_MODEL_VERSION
    assert horizon.feature_contract_version == IN_SEASON_FEATURE_CONTRACT_VERSION


def test_a_blank_first_week_abstains_if_the_control_assigns_positive_points(
    tmp_path: Path,
) -> None:
    capture = _capture(tmp_path, fixtures=_calendar(blank_club=1))

    with pytest.raises(DataSourceError, match="no fixture"):
        build_projection_horizon(
            capture,
            (2,),
            season=SEASON,
            in_season=_in_season_handoff(capture),
        )


def test_a_horizon_refuses_gameweeks_absent_from_the_captured_season(tmp_path: Path) -> None:
    with pytest.raises(DataSourceError, match="absent from the captured season"):
        _horizon(tmp_path, (1, 2, 3))


def test_a_midseason_horizon_refuses_a_handoff_for_another_capture(tmp_path: Path) -> None:
    capture = _capture(tmp_path / "decision")
    other = _capture(tmp_path / "other", captured_at="2026-08-20T20:11:43Z")

    with pytest.raises(DataSourceError, match="another capture"):
        build_projection_horizon(
            capture,
            (2,),
            season=SEASON,
            in_season=_in_season_handoff(other),
        )


def test_the_bound_builder_accepts_a_midseason_handoff(tmp_path: Path) -> None:
    capture = _capture(tmp_path)
    handoff = _in_season_handoff(capture)
    builder = make_projection_horizon_builder(season=SEASON, in_season=handoff)

    built = builder(capture, (2,))

    assert built.target_gameweeks == (2,)
    assert built.model_version == IN_SEASON_MODEL_VERSION


def test_fixture_counts_by_player_read_the_capture_calendar(tmp_path: Path) -> None:
    from squadopt.live import fixture_counts_by_player

    capture = _capture(tmp_path, fixtures=_calendar(blank_club=2, double_club=1))
    counts = fixture_counts_by_player(capture, 2, season=SEASON)
    horizon = build_projection_horizon(capture, (1, 2), panel=_history(), season=SEASON).table
    week_two = horizon.loc[horizon["gameweek"] == 2]
    for player, count in zip(
        week_two["player_id"].tolist(), week_two["fixture_count"].tolist(), strict=True
    ):
        assert counts[int(player)] == int(count)
    assert set(counts.values()) == {0, 1, 2}
    assert len(counts) == len(week_two)
