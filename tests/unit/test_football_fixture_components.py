"""The per-fixture components the producer already computes, carried beside the served forecast.

``football_fixture_components_v1`` must describe exactly the matches the weekly document sums,
with the model's own numbers, bound to that document by its fingerprint, and must not move the
served document by a byte.
"""

import json
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from tests.unit.test_football_development import football_fixture  # noqa: F401

from squadopt.live.football_artifact import forecast_digest
from squadopt.live.football_horizon import build_football_horizon
from squadopt.prediction.availability import apply_availability
from squadopt.prediction.football import FOOTBALL_MODEL_VERSION
from squadopt.prediction.football_components import (
    COMPONENT_COLUMNS,
    FIXTURE_COMPONENTS_CONTRACT,
    IDENTITY_COLUMNS,
    component_rows,
)

#: What 8d510a03, the producer before this change, returns under the stubs below: the served
#: document's fingerprint, unasked and for GW6-8. The fingerprint covers the whole document,
#: so equal fingerprints mean the served bytes did not move.
SERVED_BEFORE = {
    "unasked": "731db999e6eb3340571b8b15861d519de2fc425a9f39454065476c049d481742",
    "gw6_8": "d3cce50c5a4aca056c5e3ed57ce2a4154199075a9484526f8fc917301c7bd912",
}


def _components(football_fixture, weeks=(17, 18)):  # noqa: F811
    model, history, roster, fixtures, _ = football_fixture
    horizon, components = build_football_horizon(
        model,
        history,
        roster,
        fixtures,
        gameweeks=weeks,
        season="2025-26",
        source_snapshot_id="synthetic",
        captured_at=model.cutoff - pd.Timedelta(hours=1),
    )
    multipliers = {int(player): 1.0 for player in roster.player_id}
    return horizon, components, multipliers


def test_the_model_returns_every_declared_column(football_fixture):  # noqa: F811
    _, components, _ = _components(football_fixture)
    missing = [name for name in (*IDENTITY_COLUMNS, *COMPONENT_COLUMNS) if name not in components]
    assert missing == []


def test_the_components_describe_exactly_the_matches_the_weekly_rows_sum(
    football_fixture,  # noqa: F811
):
    horizon, components, multipliers = _components(football_fixture)
    rows = pd.DataFrame(component_rows(components, multipliers))
    assert len(rows) == len(components)
    weekly = horizon.table.set_index(["gameweek", "player_id"])
    summed = rows.groupby(["GW", "player_code"]).agg(
        expected_points=("expected_points", "sum"),
        fixture_count=("fixture", "count"),
        home_fixture_count=("home", "sum"),
    )
    for (week, player), counted in summed.iterrows():
        row = weekly.loc[(week, player)]
        assert int(counted.fixture_count) == int(row.fixture_count)
        assert int(counted.home_fixture_count) == int(row.home_fixture_count)
        assert abs(float(counted.expected_points) - float(row.expected_points)) <= 1e-10
    blank = weekly.loc[weekly.fixture_count.eq(0)].index
    assert all(key not in summed.index for key in blank)


def test_each_row_carries_the_model_numbers_and_its_players_multiplier(
    football_fixture,  # noqa: F811
):
    _, components, multipliers = _components(football_fixture)
    first = int(components.player_code.iloc[0])
    multipliers[first] = 0.25
    rows = component_rows(components, multipliers)
    by_key = {(int(r["fixture"]), int(r["player_code"])): r for r in rows}
    for record in components.to_dict("records"):
        row = by_key[(int(record["fixture"]), int(record["player_code"]))]
        for name in COMPONENT_COLUMNS:
            assert row[name] == float(record[name])
        expected = 0.25 if int(record["player_code"]) == first else 1.0
        assert row["availability_multiplier"] == expected
    assert json.loads(json.dumps(rows)) == rows


@pytest.mark.parametrize(
    ("damage", "match"),
    [
        (lambda frame: frame.drop(columns="goals"), "declared columns"),
        (lambda frame: pd.concat([frame, frame.iloc[:1]]), "appears twice"),
        (lambda frame: frame.assign(goals=np.inf), "not finite"),
        (lambda frame: frame.assign(p60=1.5), "outside"),
    ],
)
def test_a_frame_a_consumer_would_misread_is_refused(football_fixture, damage, match):  # noqa: F811
    _, components, multipliers = _components(football_fixture)
    with pytest.raises(ValueError, match=match):
        component_rows(damage(components), multipliers)


def test_a_player_with_no_multiplier_is_refused(football_fixture):  # noqa: F811
    _, components, multipliers = _components(football_fixture)
    multipliers.pop(int(components.player_code.iloc[0]))
    with pytest.raises(ValueError, match="no availability multiplier"):
        component_rows(components, multipliers)


def _producer_world(monkeypatch):
    """The producer with its archive, model and forecaster stubbed at the module boundary.

    The forecaster returns one fixture per player per week with every declared column, so
    what stays real is the producer's own wiring: the served document it builds, and the
    components document it binds to it.
    """

    from squadopt.application import football_live

    history = pd.DataFrame(
        {
            "season": ["2025-26", "2025-26"],
            "kickoff": pd.to_datetime(["2026-05-01T14:00:00Z", "2026-05-08T14:00:00Z"]),
        }
    )

    class Model:
        def __init__(self, training, history, *, cutoff):
            self.cutoff = cutoff

    def build(
        model, history, roster, calendar, *, gameweeks, season, source_snapshot_id, captured_at
    ):
        weekly, parts = [], []
        for week in gameweeks:
            for side, player in enumerate((101, 102)):
                weekly.append(
                    dict(
                        gameweek=week,
                        player_id=player,
                        name=str(player),
                        team_id="t",
                        position="MID",
                        price_tenths=50,
                        expected_points=2.0 + week / 100,
                        fixture_count=1,
                        home_fixture_count=1 - side,
                    )
                )
                parts.append(
                    {
                        "GW": week,
                        "fixture": week * 10,
                        "kickoff": pd.Timestamp(f"2026-10-{week + 4:02d}T14:00:00Z"),
                        "club": 10 if side == 0 else 20,
                        "opponent": 20 if side == 0 else 10,
                        "home": float(1 - side),
                        "player_code": player,
                        "position": "MID",
                        **{name: 0.5 for name in COMPONENT_COLUMNS},
                        "expected_points": 2.0 + week / 100,
                    }
                )
        return SimpleNamespace(table=pd.DataFrame(weekly)), pd.DataFrame(parts)

    inputs = SimpleNamespace(
        captured_at_utc="2026-09-22T20:55:33Z",
        deadline=SimpleNamespace(gameweek=6),
        players=pd.DataFrame({"player_id": [101, 102]}),
        snapshot_id="synthetic",
        availability=pd.DataFrame(
            {"player_id": [101, 102], "status": ["d", "a"], "chance_of_playing": [50, None]}
        ),
    )
    fixtures = [
        dict(id=w * 10, team_h=1, team_a=2, event=w, kickoff_time=f"2026-10-{w + 4:02d}T14:00:00Z")
        for w in range(6, 14)
    ]
    snapshot = SimpleNamespace(
        payloads={
            "bootstrap-static.json": json.dumps(
                {
                    "teams": [{"id": 1, "code": 10}, {"id": 2, "code": 20}],
                    "elements": [{"code": 101, "team": 1}, {"code": 102, "team": 2}],
                }
            ),
            "fixtures.json": json.dumps(fixtures),
        },
        metadata=SimpleNamespace(fingerprint="fingerprint"),
    )
    monkeypatch.setattr(football_live, "infer_season", lambda snapshot: "2026-27")
    monkeypatch.setattr(football_live, "read_inputs", lambda snapshot, *, season: inputs)
    monkeypatch.setattr(football_live, "archive_history", lambda root: history)
    monkeypatch.setattr(football_live, "captured_history", lambda *a, **k: pd.DataFrame())
    monkeypatch.setattr(football_live, "causal_training", lambda history: pd.DataFrame({"x": [1]}))
    monkeypatch.setattr(football_live, "FixtureFootballModel", Model)
    monkeypatch.setattr(football_live, "build_football_horizon", build)
    monkeypatch.setattr(football_live, "ARCHIVE_SEASONS", ())
    return football_live, snapshot, inputs


def test_the_served_document_is_unchanged_by_the_components_beside_it(monkeypatch, tmp_path):
    football_live, snapshot, _ = _producer_world(monkeypatch)
    alone = football_live.produce_football_forecast(snapshot, tmp_path)
    assert alone["fingerprint"] == SERVED_BEFORE["unasked"]
    served, _ = football_live.produce_football_components(snapshot, tmp_path)
    assert json.dumps(served, sort_keys=True, default=str) == json.dumps(
        alone, sort_keys=True, default=str
    )
    longer = football_live.produce_football_forecast(snapshot, tmp_path, gameweeks=range(6, 9))
    served_longer, _ = football_live.produce_football_components(
        snapshot, tmp_path, gameweeks=range(6, 9)
    )
    assert served_longer["fingerprint"] == longer["fingerprint"] == SERVED_BEFORE["gw6_8"]


def test_the_components_bind_to_the_served_document_and_carry_the_readers_rule(
    monkeypatch, tmp_path
):
    football_live, snapshot, inputs = _producer_world(monkeypatch)
    served, components = football_live.produce_football_components(snapshot, tmp_path)
    assert components["contract_version"] == FIXTURE_COMPONENTS_CONTRACT
    assert components["model_version"] == FOOTBALL_MODEL_VERSION == served["model_version"]
    assert components["forecast_fingerprint"] == served["fingerprint"]
    assert components["fingerprint"] == forecast_digest(components)
    assert components["availability_application"] == "not_applied"
    assert components["gameweeks"] == [6, 7, 8, 9, 10]
    for key in ("source_snapshot_id", "captured_at_utc", "source_fingerprint", "archive_hashes"):
        assert components[key] == served[key]
    unit = pd.DataFrame({"player_id": [101, 102], "expected_points": [1.0, 1.0]})
    rule = dict(
        zip([101, 102], apply_availability(unit, inputs.availability).multiplier, strict=True)
    )
    assert rule[101] < 1.0 == rule[102]
    assert {r["player_code"]: r["availability_multiplier"] for r in components["rows"]} == rule
    assert {r["GW"] for r in components["rows"]} == set(range(6, 11))
