"""Synthetic pre-cutoff club form and opt-in prediction tests."""

import json
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal
from tests.unit.test_football_fixture_components import _producer_world

from squadopt.application.football_live import causal_training
from squadopt.live.football_artifact import forecast_digest, read_football_forecast
from squadopt.live.football_horizon import build_football_horizon
from squadopt.prediction.football import FixtureFootballModel, _matrix
from squadopt.prediction.football_features import FEATURES, TEAM_FEATURES, football_features
from squadopt.prediction.football_team_form import (
    FORM_FEATURES,
    FORM_HEAD_FEATURES,
    TEAM_FORM_FEATURE_VERSION,
    TEAM_FORM_MODEL_VERSION,
    TeamFormFootballModel,
    football_team_form_features,
    team_form_features,
    team_form_metadata,
)


@pytest.fixture(scope="module")
def form_world():
    rows = []
    for week in range(1, 17):
        for club in range(4):
            pair = club // 2
            home_goals, away_goals = (week + pair) % 4, (week // 3 + pair) % 3
            gf, ga = (home_goals, away_goals) if club % 2 == 0 else (away_goals, home_goals)
            for offset, position in enumerate(("GK", "DEF", "MID", "FWD")):
                minutes = (0, 30, 75, 90)[(week + club + offset) % 4]
                rows.append(
                    dict(
                        season="2026-27",
                        GW=week,
                        fixture=week * 10 + pair,
                        player_code=club * 4 + offset + 1,
                        club=club,
                        opponent=club ^ 1,
                        home=float(club % 2 == 0),
                        position=position,
                        kickoff=pd.Timestamp("2026-08-01", tz="UTC") + pd.Timedelta(days=week * 7),
                        minutes=minutes,
                        appeared=float(minutes > 0),
                        long=float(minutes >= 60),
                        m_bin=0
                        if minutes == 0
                        else 1
                        if minutes < 60
                        else 2
                        if minutes < 90
                        else 3,
                        starts=float(minutes >= 60),
                        goals_scored=int(offset == 3 and gf > 0),
                        assists=int(offset == 2 and gf > 0),
                        expected_goals=gf / 4 + (offset + 1) / 20,
                        expected_assists=(offset + 1) / 30,
                        clean_sheets=int(minutes >= 60 and ga == 0),
                        defensive_contribution=float(minutes / 90 * (offset + 7)),
                        dc_event=float(minutes >= 60 and offset == 3),
                        total_points=float((minutes > 0) + (minutes >= 60) + offset),
                        team_goals=gf,
                        team_conceded=ga,
                    )
                )
    history = pd.DataFrame(rows)
    target = (
        history.loc[history.GW.eq(16)]
        .copy()
        .assign(
            GW=17,
            fixture=lambda f: f.fixture + 10,
            kickoff=lambda f: f.kickoff + pd.Timedelta(days=7),
        )
    )
    cutoff = history.kickoff.max() + pd.Timedelta(days=1)
    return history, target, cutoff


def test_exact_season_and_recent_form_counts_club_matches_not_players(form_world):
    history, target, cutoff = form_world
    features = team_form_features(history, target, cutoff)
    own = features.iloc[0]
    matches = history.loc[history.club.eq(0)].drop_duplicates("fixture").sort_values("kickoff")
    wins = matches.team_goals.gt(matches.team_conceded)
    draws = matches.team_goals.eq(matches.team_conceded)
    assert own.own_form_season_matches == 16
    assert own.own_form_season_wins == wins.sum()
    assert own.own_form_season_draws == draws.sum()
    assert own.own_form_season_losses == 16 - wins.sum() - draws.sum()
    assert own.own_form_season_points_per_match == pytest.approx((3 * wins + draws).mean())
    assert own.own_form_season_ga == pytest.approx(matches.team_conceded.mean())
    assert own.own_form_season_clean_sheet_rate == pytest.approx(matches.team_conceded.eq(0).mean())
    for window in (3, 5):
        last = matches.tail(window)
        prefix = f"own_form_recent{window}_"
        assert own[prefix + "matches"] == window
        assert own[prefix + "ga"] == pytest.approx(last.team_conceded.mean())
        assert own[prefix + "clean_sheet_rate"] == pytest.approx(last.team_conceded.eq(0).mean())
        # Four player xG rows per opponent fixture, summed once.
        expected_against = (
            history.loc[history.club.eq(1) & history.fixture.isin(last.fixture)]
            .groupby("fixture")
            .expected_goals.sum()
            .mean()
        )
        assert own[prefix + "xga"] == pytest.approx(expected_against)
    assert_frame_equal(
        features, team_form_features(history.sample(frac=1, random_state=42), target, cutoff)
    )


def test_different_players_do_not_duplicate_club_results(form_world):
    history, target, cutoff = form_world
    extra = history.assign(player_code=lambda f: f.player_code + 1000, expected_goals=0.0)
    assert_frame_equal(
        team_form_features(history, target, cutoff),
        team_form_features(pd.concat([history, extra]), target, cutoff),
    )
    with pytest.raises(ValueError, match="Duplicate"):
        team_form_features(pd.concat([history, history.iloc[:1]]), target, cutoff)


def test_current_season_is_separate_and_cold_starts_have_zero_count(form_world):
    history, target, cutoff = form_world
    earlier = history.assign(
        season="2024-25",
        fixture=lambda f: f.fixture + 1000,
        kickoff=lambda f: f.kickoff - pd.Timedelta(days=730),
    )
    assert_frame_equal(
        team_form_features(history, target, cutoff),
        team_form_features(pd.concat([earlier, history]), target, cutoff),
    )
    assert team_form_features(history, target.assign(season="2027-28"), cutoff).eq(0).all().all()
    assert team_form_features(history.iloc[:0], target, cutoff).eq(0).all().all()


@pytest.mark.parametrize(
    "damage, message",
    [
        (lambda h: h.assign(kickoff=pd.Timestamp("2027-01-01", tz="UTC")), "unavailable"),
        (lambda h: h.assign(kickoff=pd.Timestamp("2026-01-01")), "timezone-aware"),
        (lambda h: h.assign(team_goals=0.5), "nonnegative integers"),
        (lambda h: h.assign(expected_goals=-1), "finite and nonnegative"),
        (lambda h: h.loc[h.club.ne(0)], "opposing"),
        (lambda h: h.assign(opponent=h.club), "opposing"),
        (lambda h: h.assign(team_conceded=99), "scores disagree"),
    ],
)
def test_invalid_or_unavailable_history_is_refused(form_world, damage, message):
    history, target, cutoff = form_world
    with pytest.raises(ValueError, match=message):
        team_form_features(damage(history), target, cutoff)


def test_boundary_same_week_and_target_outcome_poisoning(form_world):
    history, target, cutoff = form_world
    before = football_team_form_features(history, target, cutoff)
    poison = target.assign(team_goals=999, team_conceded=999, total_points=-999, expected_goals=999)
    assert_frame_equal(before, football_team_form_features(history, poison, cutoff))
    with pytest.raises(ValueError, match="unavailable"):
        team_form_features(history, target, history.kickoff.max() + pd.Timedelta(hours=3))
    assert not team_form_features(
        history, target, history.kickoff.max() + pd.Timedelta(hours=3, microseconds=1)
    ).empty
    with pytest.raises(ValueError, match="target gameweek"):
        team_form_features(history, target.assign(GW=16), cutoff)
    with pytest.raises(ValueError, match="timezone-aware"):
        team_form_features(history, target, cutoff.tz_localize(None))


@pytest.mark.parametrize("side", ["history", "target"])
@pytest.mark.parametrize("value", [None, 0, 39, 1.5, np.inf, True])
def test_gameweek_identity_is_complete_and_valid(form_world, side, value):
    history, target, cutoff = form_world
    damaged = (history if side == "history" else target).assign(GW=value)
    with pytest.raises(ValueError):
        team_form_features(
            damaged if side == "history" else history,
            damaged if side == "target" else target,
            cutoff,
        )


@pytest.mark.parametrize("side", ["history", "target"])
def test_missing_gameweek_cannot_bypass_the_causal_contract(form_world, side):
    history, target, cutoff = form_world
    with pytest.raises(ValueError):
        team_form_features(
            history.drop(columns="GW") if side == "history" else history,
            target.drop(columns="GW") if side == "target" else target,
            cutoff,
        )


@pytest.mark.parametrize("scope", ["within_side", "across_sides"])
def test_paired_fixture_gameweek_identity_must_agree(form_world, scope):
    history, target, cutoff = form_world
    history = history.copy()
    first_fixture = history.fixture.iloc[0]
    if scope == "within_side":
        history.loc[history.fixture.eq(first_fixture) & history.player_code.eq(4), "GW"] = 2
    else:
        history.loc[history.fixture.eq(first_fixture) & history.club.eq(1), "GW"] = 2
    with pytest.raises(ValueError, match=r"consistent.*fixture sides"):
        team_form_features(history, target, cutoff)


def test_causal_training_uses_same_form_builder_and_excludes_target_week(form_world):
    history, _, _ = form_world
    training = causal_training(history, prior_only_season="2024-25", team_form=True)
    row = training.loc[training.GW.eq(7) & training.player_code.eq(1)].iloc[0]
    assert row.own_form_season_matches == 6
    assert row.own_form_recent5_matches == 5
    poisoned = history.copy()
    poisoned.loc[
        poisoned.GW.ge(7), ["team_goals", "team_conceded", "total_points", "expected_goals"]
    ] = 99
    other = causal_training(poisoned, prior_only_season="2024-25", team_form=True)
    assert_frame_equal(
        training.loc[training.GW.eq(7), list(FORM_FEATURES)],
        other.loc[other.GW.eq(7), list(FORM_FEATURES)],
    )
    legacy = causal_training(history, prior_only_season="2024-25")
    explicit_legacy = causal_training(history, prior_only_season="2024-25", team_form=False)
    assert_frame_equal(legacy, explicit_legacy)
    assert not any(name in legacy for name in FORM_FEATURES)


def test_single_selected_season_is_prior_only_and_cannot_supply_supervised_rows(form_world):
    history, _, _ = form_world
    with pytest.raises(ValueError, match="No causal football training rows"):
        causal_training(history, prior_only_season="2026-27", team_form=True)


@pytest.fixture(scope="module")
def fitted_form(form_world):
    history, target, cutoff = form_world
    training = causal_training(history, prior_only_season="2024-25", team_form=True)
    model = TeamFormFootballModel(training, history, cutoff=cutoff)
    return model, football_team_form_features(history, target, cutoff)


def test_optional_fit_uses_form_and_reverses_all_opponent_features(fitted_form):
    model, features = fitted_form
    features = features.assign(
        player_code=range(1, 17),
        position=["GK", "DEF", "MID", "FWD"] * 4,
        season="2026-27",
        fixture=[170] * 8 + [171] * 8,
        club=np.repeat(range(4), 4),
    )
    original = model.predict(features)
    changed = features.copy()
    changed["own_form_recent5_points_per_match"] += 10
    different = model.predict(changed)
    assert not np.allclose(original.team_goal_rate, different.team_goal_rate)
    assert not np.allclose(original.expected_points, different.expected_points)
    assert not np.allclose(original.clean_sheet_probability, different.clean_sheet_probability)
    assert np.array_equal(original.appearance_probability, different.appearance_probability)
    assert np.array_equal(original.expected_minutes, different.expected_minutes)
    other = features.loc[:, list(FORM_HEAD_FEATURES)].copy()
    for own in FORM_HEAD_FEATURES:
        if own.startswith("own_"):
            opp = "opp_" + own[4:]
            other[own], other[opp] = features[opp].to_numpy(), features[own].to_numpy()
    other["home"] = 1 - features.home.to_numpy()
    assert np.array_equal(
        original.opponent_goal_rate, model.team.predict(_matrix(other, FORM_HEAD_FEATURES))
    )
    assert original.model_version.eq(TEAM_FORM_MODEL_VERSION).all()
    assert original.availability_multiplier.eq(1).all()
    with pytest.raises(ValueError, match="role-transition"):
        model.predict(features, role_steps=1)


def test_live_horizon_inference_and_legacy_team_columns(form_world, fitted_form):
    history, target, cutoff = form_world
    model, _ = fitted_form
    roster = (
        target[["player_code", "position", "club"]]
        .rename(columns={"player_code": "player_id"})
        .assign(name="synthetic", team_id=lambda f: f.club.astype(str), price_tenths=50)
    )
    calendar = target[["fixture", "club", "opponent", "home", "GW", "kickoff"]].drop_duplicates()
    horizon, components = build_football_horizon(
        model,
        history,
        roster,
        calendar,
        gameweeks=(17,),
        season="2026-27",
        source_snapshot_id="synthetic",
        captured_at=cutoff,
    )
    assert horizon.feature_contract_version == TEAM_FORM_FEATURE_VERSION
    assert horizon.model_version == TEAM_FORM_MODEL_VERSION
    assert components.own_form_season_matches.eq(16).all()
    assert horizon.table.appearance_probability.between(0, 1).all()
    assert FixtureFootballModel.team_features == TEAM_FEATURES
    assert len(TEAM_FEATURES) == 9
    assert tuple(football_features(history, target, cutoff).columns) == FEATURES
    with pytest.raises(ValueError, match="role-transition"):
        build_football_horizon(
            model,
            history,
            roster,
            calendar,
            gameweeks=(17,),
            season="2026-27",
            source_snapshot_id="synthetic",
            captured_at=cutoff,
            role_transitions=True,
        )


def _form_producer(monkeypatch):
    producer, snapshot, inputs = _producer_world(monkeypatch)
    calls = []
    history = pd.DataFrame(
        {
            "season": ["2026-27", "2026-27"],
            "kickoff": pd.to_datetime(["2026-08-01T14:00:00Z", "2026-08-08T14:00:00Z"]),
        }
    )
    monkeypatch.setattr(producer, "captured_history", lambda *a, **kw: history)
    monkeypatch.setattr(producer, "ARCHIVE_SEASONS", ("2024-25",))

    def archive(root, *, seasons):
        assert seasons == ("2024-25",)
        return history.assign(
            season="2024-25", kickoff=lambda frame: frame.kickoff - pd.Timedelta(days=730)
        )

    monkeypatch.setattr(producer, "archive_history", archive)

    def train(h, **kwargs):
        calls.append(("train", kwargs))
        return h.loc[h.season.ne(kwargs["prior_only_season"])].copy()

    class Model:
        def __init__(self, train, history, *, cutoff):
            self.cutoff = cutoff
            calls.append(("fit", len(train)))

    build = producer.build_football_horizon

    def form_build(*args, **kwargs):
        horizon, components = build(*args, **kwargs)
        return horizon, components.assign(model_version=TEAM_FORM_MODEL_VERSION)

    monkeypatch.setattr(producer, "causal_training", train)
    monkeypatch.setattr(producer, "TeamFormFootballModel", Model)
    monkeypatch.setattr(producer, "build_football_horizon", form_build)
    return producer, snapshot, inputs, calls


def test_producer_and_reader_bind_explicit_form_identity(monkeypatch, tmp_path):
    producer, snapshot, inputs, calls = _form_producer(monkeypatch)
    # Fabricated archive bytes exercise hashing without opening a real source.
    for filename in ("gws/merged_gw.csv", "players_raw.csv", "teams.csv", "fixtures.csv"):
        path = tmp_path / "data" / "2024-25" / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("synthetic selected archive", encoding="utf-8")
    document, companion = producer.produce_football_components(
        snapshot, tmp_path, training_seasons=("2024-25", "2026-27"), team_form=True
    )
    assert calls == [("train", {"prior_only_season": "2024-25", "team_form": True}), ("fit", 2)]
    assert document["training_selection"]["allowed_seasons"] == ["2024-25", "2026-27"]
    assert document["training_selection"]["prior_only_seasons"] == ["2024-25"]
    assert document["training_selection"]["supervised_rows_by_season"] == {"2026-27": 2}
    assert document["model_version"] == TEAM_FORM_MODEL_VERSION
    assert document["team_form_metadata"] == team_form_metadata()
    assert companion["team_form_metadata"] == document["team_form_metadata"]
    assert companion["team_form_metadata"] is not document["team_form_metadata"]
    path = tmp_path / "form.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    read = read_football_forecast(path, inputs)
    assert read.projection.diagnostics["feature_contract_version"] == TEAM_FORM_FEATURE_VERSION
    assert read.horizon.feature_contract_version == TEAM_FORM_FEATURE_VERSION
    # Player 103's 75 source label scales the accepted q once.
    row = read.projection.table.loc[read.projection.table.player_id.eq(103)].iloc[0]
    raw = next(r for r in document["rows"] if r["gameweek"] == 6 and r["player_id"] == 103)
    assert row.appearance_probability == pytest.approx(raw["appearance_probability"] * 0.75)
    for damage in ("metadata", "feature", "windows"):
        broken = json.loads(json.dumps(document))
        if damage == "metadata":
            broken.pop("team_form_metadata")
        elif damage == "feature":
            broken["feature_contract_version"] = "causal_football_fixture_features_v1"
        else:
            broken["team_form_metadata"]["windows"] = [2, 8]
        broken["fingerprint"] = forecast_digest(broken)
        path.write_text(json.dumps(broken), encoding="utf-8")
        with pytest.raises(ValueError, match="feature identity"):
            read_football_forecast(path, inputs)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"team_form": True},
        {"team_form": 1},
        {"team_form": True, "contextual": True, "training_seasons": ("2024-25",)},
        {"team_form": True, "role_minutes": True, "training_seasons": ("2024-25",)},
    ],
)
def test_invalid_opt_in_fails_before_any_source_read(tmp_path, kwargs):
    from squadopt.application.football_live import produce_football_forecast

    with pytest.raises(ValueError, match=r"team_form|Team form"):
        produce_football_forecast(SimpleNamespace(), tmp_path, **kwargs)


@pytest.mark.parametrize(
    "extra",
    [
        [],
        ["--contextual", "--training-season", "2024-25"],
        ["--role-minutes", "--training-season", "2024-25"],
    ],
)
def test_cli_team_form_guard_precedes_snapshot_read(monkeypatch, extra):
    import scripts.build_football_forecast as command

    monkeypatch.setattr(
        command, "read_snapshot", lambda *a: pytest.fail("snapshot read before preflight")
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "build_football_forecast",
            "--snapshot-root",
            "synthetic",
            "--snapshot-id",
            "synthetic",
            "--archive-root",
            "synthetic",
            "--artifact-root",
            "synthetic",
            "--team-form",
            *extra,
        ],
    )
    with pytest.raises(SystemExit) as error:
        command.main()
    assert error.value.code == 2
