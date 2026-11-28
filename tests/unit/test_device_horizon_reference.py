"""The direct numeric replay agrees with the existing application reference."""

import json
from pathlib import Path

import pytest
from tests.unit.device_horizon_reference import reference_horizon, solve_reference
from tests.unit.test_device_plan_horizon import FIXTURE, horizon_world


@pytest.mark.parametrize("window", [3, 5])
def test_numeric_reference_matches_the_certified_application_fixture(
    tmp_path: Path, window: int
) -> None:
    world = horizon_world(tmp_path)
    fixture = json.loads(FIXTURE.read_bytes())
    member = fixture["members"][0]
    document = fixture["document"]
    horizon = reference_horizon(document, member["entry"], window)
    assert len(horizon.table) == 24 * window
    for original in document["horizon"]["weeks"][:window]:
        rows = horizon.table.loc[horizon.table.gameweek.eq(original["gameweek"])]
        assert rows.expected_points.tolist() == [p["expected_points"] for p in original["players"]]
        assert rows.buy_price_tenths.tolist() == [p["buy_tenths"] for p in original["players"]]
        assert rows.sell_price_tenths.tolist() == [
            member["entry"]["sell_tenths"].get(str(p["id"]), p["buy_tenths"])
            for p in original["players"]
        ]
    actual = solve_reference(document, member["entry"], world["rules"], window)
    expected = member["reference"][str(window)]
    assert actual["status"] == "OPTIMAL"
    assert actual["diagnostics"]["relative_optimality_gap"] == 0
    assert actual["objective_scaled"] == expected["objective_scaled"]
    assert abs(actual["objective"] - expected["objective"]) <= 1e-6
    assert actual["unique_moves"] is expected["unique_moves"] is True
    assert actual["tiebreak_completed"] is expected["tiebreak_completed"] is True
    assert [w["transfers_in"] for w in actual["weeks"]] == [
        w["transfers_in"] for w in expected["weeks"]
    ]
    assert [w["transfers_out"] for w in actual["weeks"]] == [
        w["transfers_out"] for w in expected["weeks"]
    ]
    assert actual["diagnostics"]["solver_time_limit_seconds"] == 1800
    assert actual["diagnostics"]["solver_deterministic_time_limit"] == window * 20
    assert actual["diagnostics"]["linearization_level"] == 2
    assert actual["diagnostics"]["hold_protection"]["version"] == "feasible_hold_v1"
    assert all(outcome["backend"] == "highs-native" for outcome in actual["native_outcomes"])
