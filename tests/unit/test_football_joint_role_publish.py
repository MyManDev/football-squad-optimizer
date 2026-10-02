"""Offline producer/read/public-role wiring of the opt-in joint minute model."""

import json
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal
from tests.unit.test_football_fixture_components import CLUBS, PLAYERS, _producer_world
from tests.unit.test_football_minute_integration import bind, world
from tests.unit.test_joint_role_minute_evidence import joint_documents
from tests.unit.test_minute_evidence import basis_from, documents

from squadopt.application.football_roles import (
    bind_role_absences,
    fixture_role_estimates,
    role_forecast_summary,
)
from squadopt.live.football_artifact import forecast_digest, read_football_forecast
from squadopt.live.minute_evidence import FixtureComponentBasis
from squadopt.planning.horizon import APPEARANCE_HORIZON_CONTRACT_VERSION
from squadopt.prediction.football import JOINT_ROLE_MODEL_VERSION
from squadopt.prediction.football_components import IDENTITY_COLUMNS

SELECTION = ("2022-23", "2023-24", "2024-25")


def producer(monkeypatch, tmp_path):
    module, snapshot, inputs = _producer_world(monkeypatch)
    _, template, _, _ = joint_documents()
    templates = pd.DataFrame(template["rows"]).drop_duplicates("position").set_index("position")
    old_build = module.build_football_horizon
    calls = {"fits": 0, "archives": [], "priors": []}
    captured_calendar = []
    history = pd.DataFrame(
        {
            "season": SELECTION,
            "kickoff": pd.to_datetime(
                ["2023-05-01T15:00Z", "2024-05-01T15:00Z", "2025-05-01T15:00Z"]
            ),
        }
    )

    def archive(root, *, seasons):
        calls["archives"].append(tuple(seasons))
        assert tuple(seasons) == SELECTION
        return history.copy()

    def training(frame, *, prior_only_season):
        calls["priors"].append(prior_only_season)
        assert set(frame.season) == set(SELECTION)
        return pd.DataFrame({"season": ["2023-24"] * 48 + ["2024-25"] * 48})

    class Joint:
        def __init__(self, train, history, *, cutoff):
            calls["fits"] += 1
            assert len(train) == 96 and "2025-26" not in set(history.season)
            self.cutoff = cutoff
            self.role_metadata = deepcopy(template["role_metadata"])

    def build(model, history, roster, calendar, **kwargs):
        assert isinstance(model, Joint)
        captured_calendar.append(calendar.copy())
        horizon, old = old_build(model, history, roster, calendar, **kwargs)
        records = []
        for row in old.to_dict("records"):
            record = templates.loc[row["position"]].to_dict()
            record.update({key: row[key] for key in IDENTITY_COLUMNS})
            record["model_version"] = JOINT_ROLE_MODEL_VERSION
            record["team_goal_rate"] = row["club"] / 10
            record["opponent_goal_rate"] = row["opponent"] / 10
            records.append(record)
        frame = pd.DataFrame(records)
        count = frame.groupby(["fixture", "club"]).player_code.transform("size")
        frame["goals_share"] = 1.0 / count
        frame["assists_share"] = 1.0 / count
        frame["goals"] = 0.8 * frame.team_goal_rate / count
        frame["assists"] = 0.6 * frame.team_goal_rate / count
        frame["clean_sheet_probability"] = sum(
            frame[f"{role}_minute_probability_{b}"]
            * np.exp(-frame.opponent_goal_rate * frame[f"{role}_minute_value_{b}"] / 90)
            for role in ("start", "cameo")
            for b in (2, 3)
        )
        goal = frame.position.map({"GK": 10, "DEF": 6, "MID": 5, "FWD": 4})
        clean = frame.position.map({"GK": 4, "DEF": 4, "MID": 1, "FWD": 0})
        frame["raw_expected_points"] = (
            frame.appearance_probability
            + frame.p60
            + goal * frame.goals
            + 3 * frame.assists
            + clean * frame.clean_sheet_probability
            + 2 * frame.defcon_probability
            + frame.appearance_probability * frame.residual_if_appearance
        )
        frame["expected_points"] = frame.raw_expected_points.clip(lower=0)
        grouped = frame.groupby(["GW", "player_code"])
        points = grouped.expected_points.sum()
        probability = grouped.appearance_probability.agg(lambda q: 1 - (1 - q).prod())
        table = horizon.table.copy()
        keys = list(zip(table.gameweek, table.player_id, strict=True))
        table["expected_points"] = [float(points.get(key, 0)) for key in keys]
        table["appearance_probability"] = [float(probability.get(key, 0)) for key in keys]
        return SimpleNamespace(
            table=table, contract_version=APPEARANCE_HORIZON_CONTRACT_VERSION
        ), frame

    monkeypatch.setattr(module, "ARCHIVE_SEASONS", (*SELECTION, "2025-26"))
    monkeypatch.setattr(module, "archive_history", archive)
    monkeypatch.setattr(module, "causal_training", training)
    monkeypatch.setattr(module, "JointRoleFootballModel", Joint)
    monkeypatch.setattr(module, "build_football_horizon", build)
    monkeypatch.setattr(module, "captured_history", lambda *a, **k: pytest.fail("Not selected."))
    for season in SELECTION:
        for name in ("gws/merged_gw.csv", "players_raw.csv", "teams.csv", "fixtures.csv"):
            path = tmp_path / "archive" / "data" / season / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("synthetic archive identity", encoding="utf-8")
    return module, snapshot, inputs, calls, captured_calendar


def test_one_joint_fit_produces_bound_pair_that_both_readers_agree_on(monkeypatch, tmp_path):
    module, snapshot, inputs, calls, calendars = producer(monkeypatch, tmp_path)
    served, companion = module.produce_football_components(
        snapshot, tmp_path / "archive", role_minutes=True, training_seasons=SELECTION
    )
    assert calls == {"fits": 1, "archives": [SELECTION], "priors": [SELECTION[0]]}
    assert served["model_version"] == companion["model_version"] == JOINT_ROLE_MODEL_VERSION
    assert served["role_metadata"] == companion["role_metadata"]
    assert served["role_metadata"] is not companion["role_metadata"]
    assert served["training_selection"] == companion["training_selection"]
    assert served["training_selection"]["archive_seasons_read"] == list(SELECTION)
    assert not served["training_selection"]["captured_history_included"]
    assert companion["captured_availability"]["application"] == "not_applied"
    assert served["fingerprint"] == forecast_digest(served)
    assert companion["forecast_fingerprint"] == served["fingerprint"]
    assert companion["fingerprint"] == forecast_digest(companion)
    path = tmp_path / "served.json"
    path.write_text(json.dumps(served, allow_nan=False), encoding="utf-8")
    forecast = read_football_forecast(path, inputs)
    basis = FixtureComponentBasis.from_documents(
        served,
        companion,
        fixture_calendar=calendars[0],
        roster_clubs={player: CLUBS[team] for player, (team, _) in PLAYERS.items()},
    )
    columns = ["gameweek", "player_id", "expected_points", "appearance_probability"]
    assert_frame_equal(
        forecast.horizon.table[columns].set_index(columns[:2]).sort_index(),
        basis.weekly_rows[columns].set_index(columns[:2]).sort_index(),
    )
    raw = pd.DataFrame(served["rows"]).query("player_id == 101 and gameweek == 6").iloc[0]
    loaded = forecast.projection.table.query("player_id == 101").iloc[0]
    assert loaded.appearance_probability == pytest.approx(raw.appearance_probability * 0.5)
    assert loaded.expected_points == pytest.approx(raw.expected_points * 0.5)
    public = fixture_role_estimates(basis, inputs)
    first = next(row for row in public if row["player_id"] == 101)
    assert first["start_probability"] + first["cameo_probability"] == pytest.approx(
        loaded.appearance_probability
    )
    double_raw = pd.DataFrame(companion["rows"]).query("player_code == 101 and GW == 7")
    double = forecast.horizon.table.query("player_id == 101 and gameweek == 7").iloc[0]
    assert double.appearance_probability == pytest.approx(
        0.5 * (1 - (1 - double_raw.appearance_probability).prod())
    )
    assert not np.isclose(
        double.appearance_probability, 1 - (1 - 0.5 * double_raw.appearance_probability).prod()
    )


def test_joint_opt_in_requires_explicit_selection_before_opening_archive(monkeypatch, tmp_path):
    module, snapshot, _ = _producer_world(monkeypatch)
    monkeypatch.setattr(
        module, "archive_history", lambda *a, **k: pytest.fail("Must refuse first.")
    )
    with pytest.raises(ValueError, match="explicit training-season"):
        module.produce_football_components(snapshot, tmp_path, role_minutes=True)
    with pytest.raises(ValueError, match="cannot be combined"):
        module.produce_football_forecast(
            snapshot, tmp_path, contextual=True, role_minutes=True, training_seasons=SELECTION
        )


@pytest.mark.parametrize("unknown", [False, True])
def test_public_current_fixture_law_has_single_eligibility_and_honest_unknown_role(unknown):
    football, inputs, _, basis = world(joint_documents(unknown=unknown, dgw=True))
    estimates = fixture_role_estimates(basis, inputs)
    raw = basis.fixture_rows.set_index(["fixture", "player_code"])
    assert len(estimates) == len(basis.fixture_rows.query("GW == 6"))
    assert {row["gameweek"] for row in estimates} == {6}
    for row in estimates:
        original = raw.loc[(row["fixture_id"], row["player_id"]), :]
        assert row["expected_minutes"] == pytest.approx(original.expected_minutes * 0.5)
        assert row["sixty_minute_probability"] == pytest.approx(original.p60 * 0.5)
        assert row["zero_probability"] == pytest.approx(1 - original.appearance_probability * 0.5)
        assert row["captured_eligibility_multiplier"] == 0.5 and not row["news_applied"]
        if unknown:
            assert row["start_probability"] is row["cameo_probability"] is None
            assert row["unknown_role_probability"] == pytest.approx(
                original.appearance_probability * 0.5
            )
        else:
            assert row["start_probability"] + row["cameo_probability"] + row[
                "zero_probability"
            ] == pytest.approx(1)
    bound = bind(football, inputs, None, basis)
    assert_frame_equal(bound.horizon.table, football.horizon.table)
    summary = role_forecast_summary(bound.projection.diagnostics, {3, 8})
    assert summary["calibration"] == "not_independently_verified"
    assert {row["player_id"] for row in summary["rows"]} == {3, 8}
    assert {row["gameweek"] for row in summary["rows"]} == {6}


@pytest.mark.parametrize("unknown", [False, True])
def test_cited_absence_zeros_public_law_only_for_absent_player_without_inventing_roles(unknown):
    football, inputs, words, basis = world(joint_documents(unknown=unknown))
    words = replace(words, words=(replace(words.words[0], disposition="stated_expected_absent"),))
    before = fixture_role_estimates(basis, inputs)
    result = bind(football, inputs, words, basis)
    after = result.projection.diagnostics["fixture_role_estimates"]
    row = next(row for row in after if row["player_id"] == 3)
    assert row["zero_probability"] == 1 and row["news_applied"]
    assert (
        row["expected_minutes"]
        == row["sixty_minute_probability"]
        == row["unknown_role_probability"]
        == 0
    )
    assert row["start_probability"] is None if unknown else row["start_probability"] == 0
    assert row["cameo_probability"] is None if unknown else row["cameo_probability"] == 0
    assert [row for row in after if row["player_id"] != 3] == [
        row for row in before if row["player_id"] != 3
    ]
    assert bind_role_absences(after, result.projection.table) == after
    assert next(row for row in before if row["player_id"] == 3)["zero_probability"] < 1


def test_real_minute_intervention_updates_public_minutes_and_flags_only_cited_fixture():
    football, inputs, words, basis = world(joint_documents())
    result = bind(football, inputs, words, basis)
    before = {(r["player_id"], r["fixture_id"]): r for r in fixture_role_estimates(basis, inputs)}
    after = {
        (r["player_id"], r["fixture_id"]): r
        for r in result.projection.diagnostics["fixture_role_estimates"]
    }
    # One unambiguous upcoming league fixture is bound to the source statement.
    old, changed = before[3, 62], after[3, 62]
    assert changed["news_applied"]
    assert changed["expected_minutes"] < old["expected_minutes"]
    assert changed["sixty_minute_probability"] < old["sixty_minute_probability"]
    assert changed["start_probability"] == pytest.approx(old["start_probability"])
    assert changed["cameo_probability"] == pytest.approx(old["cameo_probability"])
    assert all(not row["news_applied"] for key, row in after.items() if key != (3, 62))


def test_ambiguous_double_week_has_no_claim_of_public_minute_intervention():
    football, inputs, words, basis = world(joint_documents(dgw=True))
    result = bind(football, inputs, words, basis)
    assert_frame_equal(result.horizon.table, football.horizon.table)
    assert result.projection.diagnostics["fixture_role_estimates"] == fixture_role_estimates(
        basis, inputs
    )
    audit = result.projection.diagnostics["participation_evidence"]
    assert audit["unapplied_statements"][0]["reason"] == "ambiguous_current_week_fixture"
    assert not any(
        row["news_applied"] for row in result.projection.diagnostics["fixture_role_estimates"]
    )


def test_no_joint_companion_does_not_publish_synthetic_roles():
    _, inputs, _, _ = world()
    assert fixture_role_estimates(None, inputs) == []
    assert fixture_role_estimates(basis_from(documents()), inputs) == []
    assert role_forecast_summary({}, {3}) is None
