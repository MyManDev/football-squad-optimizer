"""The per-fixture components the producer already computes, carried beside the served forecast.

``football_fixture_components_v1`` must describe exactly the matches the weekly document sums,
with the model's own numbers, bound to that document by its fingerprint, must carry the
availability the reader applies without applying it, and must not move the served document by
a byte.
"""

import json
import re
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from tests.unit.test_football_development import football_fixture  # noqa: F401

from squadopt.live.football_artifact import (
    SHARES_BEFORE_AVAILABILITY_LIMIT,
    forecast_digest,
    read_football_forecast,
)
from squadopt.live.football_horizon import build_football_horizon
from squadopt.prediction.availability import AVAILABILITY_RULE_CONTRACT_VERSION
from squadopt.prediction.football import FOOTBALL_MODEL_VERSION
from squadopt.prediction.football_components import (
    AVAILABILITY_SCOPE,
    COMPONENT_COLUMNS,
    COMPONENT_LIMITATIONS,
    FIXTURE_COMPONENTS_CONTRACT,
    IDENTITY_COLUMNS,
    captured_availability,
    component_rows,
)
from squadopt.prediction.football_contextual import CONTEXTUAL_MODEL_VERSION

#: What #898's producer, before this change, returns under the stub world below: the served
#: document's fingerprint unasked, for GW6-8, and for the contextual candidate. The fingerprint
#: covers the whole document, so equal fingerprints mean the served bytes did not move.
SERVED_BEFORE = {
    "unasked": "5459fdf872f7e8822886adeae51debfdb9ecf13b7e6f88eadeba69fe738668fa",
    "gw6_8": "12d12912907f00f49beddc192d8138678ff0014e9cc938075c47a18d2e9188c7",
    "contextual": "1ab7c570f505a9861462d06a98b8ea359dc55217c58015577db7d5796755c15e",
}

ISO_UTC = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+00:00")


def _components(football_fixture, weeks=(17, 18)):  # noqa: F811
    """The real model's components over a window with a double and a blank.

    Clubs 0 and 1 play twice in GW17, and clubs 2 and 3 have no GW18 fixture.
    """

    model, history, roster, fixtures, _ = football_fixture
    double = fixtures.loc[fixtures.GW.eq(17) & fixtures.club.isin((0, 1))].assign(
        fixture=lambda d: d.fixture + 1000
    )
    blank = fixtures.GW.eq(18) & fixtures.club.isin((2, 3))
    horizon, components = build_football_horizon(
        model,
        history,
        roster,
        pd.concat([fixtures.loc[~blank], double], ignore_index=True),
        gameweeks=weeks,
        season="2025-26",
        source_snapshot_id="synthetic",
        captured_at=model.cutoff - pd.Timedelta(hours=1),
    )
    return horizon, components, {int(player) for player in roster.player_id}


def test_the_model_returns_every_declared_column(football_fixture):  # noqa: F811
    _, components, _ = _components(football_fixture)
    declared = (*IDENTITY_COLUMNS, *COMPONENT_COLUMNS, "model_version")
    assert [name for name in declared if name not in components] == []


def test_the_components_describe_exactly_the_matches_the_weekly_rows_sum(
    football_fixture,  # noqa: F811
):
    horizon, components, players = _components(football_fixture)
    rows = pd.DataFrame(
        component_rows(components, model_version=FOOTBALL_MODEL_VERSION, players=players)
    )
    assert len(rows) == len(components)
    weekly = horizon.table.set_index(["gameweek", "player_id"])
    assert set(weekly.fixture_count) == {0, 1, 2}
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
    assert len(blank) == 8
    assert all(key not in summed.index for key in blank)


def test_each_row_carries_the_model_numbers_and_the_match_it_describes(
    football_fixture,  # noqa: F811
):
    _, components, players = _components(football_fixture)
    rows = component_rows(components, model_version=FOOTBALL_MODEL_VERSION, players=players)
    by_key = {(int(r["fixture"]), int(r["player_code"])): r for r in rows}
    positions = set()
    for record in components.to_dict("records"):
        row = by_key[(int(record["fixture"]), int(record["player_code"]))]
        assert row["GW"] == int(record["GW"])
        assert row["club"] == int(record["club"])
        assert row["opponent"] == int(record["opponent"])
        assert row["home"] == round(float(record["home"]))
        assert row["position"] == record["position"]
        assert row["kickoff"] == pd.Timestamp(record["kickoff"]).isoformat()
        assert ISO_UTC.fullmatch(str(row["kickoff"]))
        for name in COMPONENT_COLUMNS:
            assert row[name] == float(record[name])
        positions.add(row["position"])
    assert positions == {"GK", "DEF", "MID", "FWD"}
    assert json.loads(json.dumps(rows)) == rows


def _other_side(frame):
    """Every row of one fixture's home side, so that fixture has one side only."""

    first = frame.fixture.iloc[0]
    return frame.loc[~(frame.fixture.eq(first) & frame.home.eq(1.0))]


def _one_rate_moved(frame):
    """One row's own goal rate differs from the rest of its side."""

    return frame.assign(
        team_goal_rate=frame.team_goal_rate.where(frame.index != frame.index[0], 9.0)
    )


@pytest.mark.parametrize(
    ("damage", "match"),
    [
        (lambda frame: frame.drop(columns="goals"), "declared columns"),
        (lambda frame: frame.drop(columns="model_version"), "declared columns"),
        (lambda frame: pd.concat([frame, frame.iloc[:1]]), "appears twice"),
        (lambda frame: frame.assign(model_version="football_role_v2"), "another model"),
        (lambda frame: frame.assign(position="ST"), "unknown position"),
        (lambda frame: frame.assign(goals=np.inf), "not finite"),
        (lambda frame: frame.assign(team_goal_rate=-0.1), "negative"),
        (lambda frame: frame.assign(defcon_dispersion=0.0), "negative"),
        (lambda frame: frame.assign(p60=1.5), "outside"),
        (lambda frame: frame.assign(minute_value_3=130.0), "minute value"),
        (lambda frame: frame.assign(expected_points=frame.expected_points + 1), "clipped raw"),
        (lambda frame: frame.assign(home=0.5), "home flag"),
        (_other_side, "one home and one away"),
        (lambda frame: frame.assign(opponent=frame.club), "inconsistent opponents"),
        (
            lambda frame: frame.assign(opponent_goal_rate=frame.opponent_goal_rate + 0.5),
            "goal rates",
        ),
        (_one_rate_moved, "goal rates"),
    ],
)
def test_a_frame_a_consumer_would_misread_is_refused(football_fixture, damage, match):  # noqa: F811
    _, components, players = _components(football_fixture)
    with pytest.raises(ValueError, match=match):
        component_rows(damage(components), model_version=FOOTBALL_MODEL_VERSION, players=players)


def test_minute_probabilities_that_do_not_sum_to_one_are_refused(football_fixture):  # noqa: F811
    _, components, players = _components(football_fixture)
    damaged = components.assign(minute_probability_0=components.minute_probability_0 / 2)
    with pytest.raises(ValueError, match="sum to one"):
        component_rows(damaged, model_version=FOOTBALL_MODEL_VERSION, players=players)


def test_a_player_without_captured_availability_is_refused(football_fixture):  # noqa: F811
    _, components, players = _components(football_fixture)
    players.discard(int(components.player_code.iloc[0]))
    with pytest.raises(ValueError, match="no captured availability"):
        component_rows(components, model_version=FOOTBALL_MODEL_VERSION, players=players)


@pytest.mark.parametrize("value", [-0.1, 1.5, float("nan")])
def test_an_availability_multiplier_outside_the_unit_interval_is_refused(value):
    rule = {
        "availability_contract_version": AVAILABILITY_RULE_CONTRACT_VERSION,
        "availability_unknown_is_available": True,
        "availability_multiplier_floor": 0.0,
    }
    with pytest.raises(ValueError, match="outside"):
        captured_availability({101: value}, rule)


#: FPL team id to team code, as the bootstrap gives them.
CLUBS = {1: 10, 2: 20, 3: 30}

#: Player code to team id and position.
PLAYERS = {
    101: (1, "GK"),
    102: (1, "DEF"),
    103: (1, "MID"),
    104: (2, "FWD"),
    105: (2, "GK"),
    106: (2, "DEF"),
    107: (3, "MID"),
    108: (3, "FWD"),
}

#: Status and stated chance per player, chosen so each of the reader's rules gives a different
#: multiplier than its neighbours would: a stated chance over a status, a doubtful player with
#: and without one, the unavailable statuses, and player 108 with no row at all.
AVAILABILITY = {
    101: ("d", 50),
    102: ("a", None),
    103: ("a", 75),
    104: ("i", None),
    105: ("d", None),
    106: ("d", 0),
    107: ("s", None),
}


def _fixtures_payload():
    """Club 10 hosts club 20 every week; in GW7 club 30 also hosts club 10.

    Club 10 so plays a double in GW7, and club 30 plays only then: every other week is a blank
    for its two players.
    """

    fixtures = [
        dict(id=w * 10, team_h=1, team_a=2, event=w, kickoff_time=f"2026-10-{w + 4:02d}T14:00:00Z")
        for w in range(6, 14)
    ]
    fixtures.append(dict(id=71, team_h=3, team_a=1, event=7, kickoff_time="2026-10-14T19:00:00Z"))
    return fixtures


def _numbers(player, club, opponent):
    """One player-fixture's outputs, distinct per player and consistent between the two sides."""

    share = (player % 7 + 1) / 100
    return {
        "expected_minutes": 60.0 + player % 7,
        "appearance_probability": 0.80 + (player % 5) / 100,
        "p60": 0.60 + (player % 3) / 100,
        "team_goal_rate": club / 10,
        "opponent_goal_rate": opponent / 10,
        "goals": club / 10 * share,
        "goals_share": share,
        "assists": club / 10 * share / 2,
        "assists_share": share / 2,
        "clean_sheet_probability": 0.30 + (player % 4) / 100,
        "defcon_probability": 0.20 + (player % 6) / 100,
        "defcon_rate90": 5.0 + player % 3,
        "defcon_dispersion": 2.0,
        "residual_if_appearance": 0.40 + (player % 9) / 100,
        "minute_probability_0": 0.10,
        "minute_probability_1": 0.20,
        "minute_probability_2": 0.30,
        "minute_probability_3": 0.40,
        "minute_value_0": 0.0,
        "minute_value_1": 30.0,
        "minute_value_2": 75.0,
        "minute_value_3": 90.0,
    }


def _producer_world(monkeypatch):
    """The producer with its archive, models, context and forecaster stubbed at the boundary.

    The forecaster reads the producer's own calendar, so a double gives two rows and a blank
    none, and returns every declared column. What stays real is the producer's wiring: the
    served document it builds, and the components document it binds to it.
    """

    from squadopt.application import football_live
    from squadopt.data.sources.fpl_set_pieces import TAKER_FIELDS

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
        for player in roster.itertuples():
            for week in gameweeks:
                games = calendar.loc[calendar.GW.eq(week) & calendar.club.eq(player.club)]
                points = []
                for game in games.itertuples():
                    raw = round(2.0 + week / 100 + player.player_id / 1000 + game.home / 10, 6)
                    parts.append(
                        {
                            "GW": week,
                            "fixture": game.fixture,
                            "kickoff": game.kickoff,
                            "club": game.club,
                            "opponent": game.opponent,
                            "home": game.home,
                            "player_code": player.player_id,
                            "position": player.position,
                            "model_version": FOOTBALL_MODEL_VERSION,
                            **_numbers(player.player_id, game.club, game.opponent),
                            "raw_expected_points": raw,
                            "expected_points": raw,
                        }
                    )
                    points.append(raw)
                weekly.append(
                    dict(
                        gameweek=week,
                        player_id=player.player_id,
                        name=player.name,
                        team_id=player.team_id,
                        position=player.position,
                        price_tenths=player.price_tenths,
                        expected_points=float(sum(points)),
                        fixture_count=len(points),
                        home_fixture_count=int(games.home.sum()),
                    )
                )
        table = pd.DataFrame(weekly)
        return SimpleNamespace(table=table, contract_version="stub"), pd.DataFrame(parts)

    codes = sorted(PLAYERS)
    inputs = SimpleNamespace(
        season="2026-27",
        captured_at_utc="2026-09-22T20:55:33Z",
        deadline=SimpleNamespace(gameweek=6),
        players=pd.DataFrame(
            {
                "player_id": codes,
                "name": [str(code) for code in codes],
                "team_id": [f"club {PLAYERS[code][0]}" for code in codes],
                "position": [PLAYERS[code][1] for code in codes],
                "price_tenths": [40 + code % 10 for code in codes],
            }
        ),
        snapshot_id="synthetic",
        availability=pd.DataFrame(
            {
                "player_id": list(AVAILABILITY),
                "status": [status for status, _ in AVAILABILITY.values()],
                "chance_of_playing": [chance for _, chance in AVAILABILITY.values()],
            }
        ),
    )
    snapshot = SimpleNamespace(
        payloads={
            "bootstrap-static.json": json.dumps(
                {
                    "teams": [{"id": team, "code": code} for team, code in CLUBS.items()],
                    "elements": [{"code": code, "team": PLAYERS[code][0]} for code in codes],
                }
            ),
            "fixtures.json": json.dumps(_fixtures_payload()),
        },
        metadata=SimpleNamespace(fingerprint="fingerprint"),
    )
    takers = pd.DataFrame({"player_id": codes, **{field: None for field in TAKER_FIELDS}})
    monkeypatch.setattr(football_live, "infer_season", lambda snapshot: "2026-27")
    monkeypatch.setattr(football_live, "read_inputs", lambda snapshot, *, season: inputs)
    monkeypatch.setattr(football_live, "archive_history", lambda root: history)
    monkeypatch.setattr(football_live, "captured_history", lambda *a, **k: pd.DataFrame())
    monkeypatch.setattr(football_live, "causal_training", lambda history: pd.DataFrame({"x": [1]}))
    monkeypatch.setattr(football_live, "FixtureFootballModel", Model)
    monkeypatch.setattr(football_live, "ContextualFootballModel", Model)
    monkeypatch.setattr(football_live, "captured_taker_priorities", lambda payload: takers)
    monkeypatch.setattr(
        football_live, "bind_football_context", lambda roster, availability, **_: (roster, [])
    )
    monkeypatch.setattr(football_live, "build_football_horizon", build)
    monkeypatch.setattr(football_live, "ARCHIVE_SEASONS", ())
    return football_live, snapshot, inputs


def test_the_served_document_is_unchanged_by_the_components_beside_it(monkeypatch, tmp_path):
    football_live, snapshot, _ = _producer_world(monkeypatch)
    alone = football_live.produce_football_forecast(snapshot, tmp_path)
    assert alone["fingerprint"] == SERVED_BEFORE["unasked"]
    served, _ = football_live.produce_football_components(snapshot, tmp_path)
    assert served == alone
    longer = football_live.produce_football_forecast(snapshot, tmp_path, gameweeks=range(6, 9))
    served_longer, _ = football_live.produce_football_components(
        snapshot, tmp_path, gameweeks=range(6, 9)
    )
    assert served_longer["fingerprint"] == longer["fingerprint"] == SERVED_BEFORE["gw6_8"]


def test_the_contextual_candidate_still_reaches_its_own_model(monkeypatch, tmp_path):
    football_live, snapshot, _ = _producer_world(monkeypatch)
    document = football_live.produce_football_forecast(snapshot, tmp_path, contextual=True)
    assert document["model_version"] == CONTEXTUAL_MODEL_VERSION
    assert document["fingerprint"] == SERVED_BEFORE["contextual"]


def test_the_components_bind_to_the_served_document(monkeypatch, tmp_path):
    football_live, snapshot, _ = _producer_world(monkeypatch)
    served, components = football_live.produce_football_components(snapshot, tmp_path)
    assert components["contract_version"] == FIXTURE_COMPONENTS_CONTRACT
    assert components["model_version"] == FOOTBALL_MODEL_VERSION == served["model_version"]
    assert components["experimental"] is True
    assert components["forecast_fingerprint"] == served["fingerprint"]
    assert components["fingerprint"] == forecast_digest(components)
    assert components["gameweeks"] == [6, 7, 8, 9, 10]
    for key in ("source_snapshot_id", "captured_at_utc", "source_fingerprint", "archive_hashes"):
        assert components[key] == served[key]
    assert components["archive_hashes"] is not served["archive_hashes"]
    assert components["limitations"] == [
        *served["limitations"],
        SHARES_BEFORE_AVAILABILITY_LIMIT,
        *COMPONENT_LIMITATIONS,
    ]
    assert all("availability_multiplier" not in row for row in components["rows"])


def test_the_components_carry_the_availability_the_reader_applies(monkeypatch, tmp_path):
    football_live, snapshot, inputs = _producer_world(monkeypatch)
    served, components = football_live.produce_football_components(snapshot, tmp_path)
    path = tmp_path / "served.json"
    path.write_text(json.dumps(served), encoding="utf-8")
    applied = read_football_forecast(path, inputs).horizon.table
    before = pd.DataFrame(served["rows"]).set_index(["gameweek", "player_id"]).expected_points
    after = applied.set_index(["gameweek", "player_id"]).expected_points
    played = before.gt(0)
    ratio = (after[played] / before[played]).groupby(level="player_id").agg(["min", "max"])
    assert np.allclose(ratio["min"], ratio["max"], rtol=0, atol=1e-12)
    read = {int(player): float(value) for player, value in ratio["min"].items()}
    block = components["captured_availability"]
    assert block["application"] == "not_applied"
    assert block["scope"] == AVAILABILITY_SCOPE
    assert block["rule_contract_version"] == AVAILABILITY_RULE_CONTRACT_VERSION
    assert block["unknown_is_available"] is True
    assert block["multiplier_floor"] == 0.0
    carried = {entry["player_code"]: entry["multiplier"] for entry in block["multipliers"]}
    assert sorted(carried) == sorted(PLAYERS)
    assert carried == pytest.approx(read, rel=0, abs=1e-12)
    assert len({round(value, 6) for value in carried.values()}) == 4


def test_the_rows_follow_the_calendar_through_a_double_and_a_blank(monkeypatch, tmp_path):
    football_live, snapshot, _ = _producer_world(monkeypatch)
    _, components = football_live.produce_football_components(snapshot, tmp_path)
    rows = pd.DataFrame(components["rows"])
    games = rows.groupby(["GW", "player_code"]).fixture.count()
    assert games[(7, 101)] == 2
    assert (6, 107) not in games.index
    assert set(rows.loc[rows.player_code.isin((107, 108)), "GW"]) == {7}
    double = rows.loc[rows.fixture.eq(71)].set_index("player_code")
    assert set(double.index) == {101, 102, 103, 107, 108}
    assert double.loc[107, ["club", "opponent", "home"]].tolist() == [30, 10, 1]
    assert double.loc[101, ["club", "opponent", "home"]].tolist() == [10, 30, 0]
    assert double.loc[101, "position"] == "GK" and double.loc[108, "position"] == "FWD"
    assert set(double.kickoff) == {"2026-10-14T19:00:00+00:00"}


def test_a_window_with_no_fixture_components_carries_no_rows(monkeypatch, tmp_path):
    football_live, snapshot, _ = _producer_world(monkeypatch)
    real = football_live.build_football_horizon

    def empty(*args, **kwargs):
        horizon, _ = real(*args, **kwargs)
        return horizon, pd.DataFrame()

    monkeypatch.setattr(football_live, "build_football_horizon", empty)
    served, components = football_live.produce_football_components(snapshot, tmp_path)
    assert components["rows"] == []
    assert components["forecast_fingerprint"] == served["fingerprint"]
