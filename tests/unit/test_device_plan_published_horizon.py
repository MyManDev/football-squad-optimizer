"""Public calendar replay preserves the server's raw and integer horizon numbers."""

import copy
import json
from pathlib import Path

import pytest
from tests.unit.device_horizon_replay import (
    PublishedHorizonReplayError,
    benchmark_problem,
    replay_published_weeks,
)
from tests.unit.test_device_plan_horizon import FIXTURE, SEASON, horizon_world

from squadopt.application.fixtures_view import fixtures_view
from squadopt.optimization import OptimizationConfig
from squadopt.optimization.coefficients import objective_coefficients


@pytest.mark.parametrize("scale", [False, True], ids=["parity-24", "scale-600"])
def test_public_inputs_reproduce_every_raw_point_and_integer_coefficient(
    tmp_path: Path, scale: bool
) -> None:
    world = horizon_world(tmp_path, scale=scale)
    view = fixtures_view(world["snapshot"])
    assert view is not None
    path = FIXTURE.with_name("horizons-scale.json") if scale else FIXTURE
    recorded = json.loads(path.read_text(encoding="utf-8"))["document"]
    actual = replay_published_weeks(recorded, view.to_dict(), season=SEASON, weeks=5)
    expected = recorded["horizon"]["weeks"]
    assert len(actual) == len(expected) == 5
    for rebuilt, original in zip(actual, expected, strict=True):
        assert rebuilt["gameweek"] == original["gameweek"]
        assert rebuilt["players"] == original["players"]
    problem = benchmark_problem(recorded, view.to_dict(), world["rules"])
    assert problem["document"]["horizon"]["rules"] == recorded["horizon"]["rules"]
    assert problem["document"]["horizon"]["weeks"] == recorded["horizon"]["weeks"]
    assert {member["entry"]["free_transfers"] for member in problem["members"]} == {0, 1, 5}
    assert len({tuple(member["entry"]["held"]) for member in problem["members"]}) == 3
    players = {player["id"]: player for player in recorded["players"]}
    for member in problem["members"]:
        entry = member["entry"]
        held = [players[identifier] for identifier in entry["held"]]
        assert len(held) == len(set(entry["held"])) == recorded["rules"]["squad_size"]
        assert sum(player["buy_tenths"] for player in held) + entry["bank_tenths"] == 1000
        for position, quota in recorded["rules"]["squad_position_limits"].items():
            assert sum(player["position"] == position for player in held) == quota
        for club in {player["team"] for player in held}:
            assert (
                sum(player["team"] == club for player in held)
                <= recorded["rules"]["max_players_per_team"]
            )
        assert entry["sell_tenths"] == {str(player["id"]): player["buy_tenths"] for player in held}


def test_raw_points_are_not_replaced_by_inverted_rounded_coefficients() -> None:
    settings = OptimizationConfig()
    raw = 1.23451
    coefficients = list(objective_coefficients([raw], settings)[0])
    document = {
        "season": SEASON,
        "gameweek": 12,
        "source_snapshot_id": "synthetic-live-capture",
        "rules": {"expected_points_scale": settings.expected_points_scale},
        "players": [
            {
                "id": 1,
                "name": "Synthetic player",
                "team": "A",
                "position": "GK",
                "buy_tenths": 45,
                "expected_points": raw,
                "coefficients": coefficients,
            }
        ],
    }

    def fixture(identifier: int) -> dict[str, object]:
        return {
            "fixture_id": identifier,
            "home": {"name": "A", "team_id": 1},
            "away": {"name": "B", "team_id": 2},
        }

    calendar = {
        "season": SEASON,
        "source_snapshot_id": document["source_snapshot_id"],
        "gameweeks": [
            {"gameweek": 12, "fixtures": [fixture(1)]},
            {"gameweek": 13, "fixtures": [fixture(2), fixture(3)]},
            {"gameweek": 14, "fixtures": [fixture(4)]},
        ],
    }
    actual = replay_published_weeks(document, calendar, season=SEASON, weeks=3)
    assert actual[1]["players"][0]["expected_points"] == raw * 2
    inverted = coefficients[2] / settings.expected_points_scale
    wrongly_scaled = list(objective_coefficients([inverted * 2], settings)[0])
    assert actual[1]["players"][0]["coefficients"] != wrongly_scaled
    changed = copy.deepcopy(calendar)
    changed["source_snapshot_id"] = "synthetic-other-capture"
    with pytest.raises(PublishedHorizonReplayError, match="different captures"):
        replay_published_weeks(document, changed, season=SEASON, weeks=3)
