"""Explicit retained-history admission over synthetic pairs; no archive or provider access."""

import json
from copy import deepcopy

import pandas as pd
import pytest
from jsonschema import Draft202012Validator
from pandas.testing import assert_frame_equal
from scripts import build_football_forecast as command
from tests.unit.test_football_fixture_components import CLUBS, PLAYERS
from tests.unit.test_football_joint_role_publish import SELECTION, producer
from tests.unit.test_football_minute_integration import bind, world
from tests.unit.test_joint_role_minute_evidence import joint_documents
from tests.unit.test_minute_evidence import basis_from, claim

from squadopt.application.football_roles import role_forecast_summary
from squadopt.contracts.football_explanations import role_forecast_schema
from squadopt.live.football_artifact import forecast_digest, read_football_forecast
from squadopt.live.minute_evidence import FixtureComponentBasis, apply_explicit_minute_evidence
from squadopt.prediction.football import (
    JOINT_ROLE_MODEL_VERSION,
    JOINT_ROLE_MODEL_VERSIONS,
    JOINT_ROLE_RETAINED_HISTORY_MODEL_VERSION,
)
from squadopt.prediction.football_components import component_rows


def selected_documents(version, *, unknown=False, dgw=False):
    parts = joint_documents(unknown=unknown, dgw=dgw)
    for document in parts[:2]:
        document["model_version"] = version
        if version == JOINT_ROLE_RETAINED_HISTORY_MODEL_VERSION:
            document["role_metadata"]["role_feature_version"] = (
                "retained_player_history_indicator_v1"
            )
    parts[0]["fingerprint"] = forecast_digest(parts[0])
    parts[1]["forecast_fingerprint"] = parts[0]["fingerprint"]
    parts[1]["fingerprint"] = forecast_digest(parts[1])
    return parts


@pytest.mark.parametrize("retained", [False, True])
def test_explicit_producer_selects_one_fit_and_preserves_pair_identity(
    monkeypatch, tmp_path, retained
):
    module, snapshot, inputs, calls, calendars = producer(monkeypatch, tmp_path)
    old_joint = module.JointRoleFootballModel
    build = module.build_football_horizon
    version = JOINT_ROLE_RETAINED_HISTORY_MODEL_VERSION if retained else JOINT_ROLE_MODEL_VERSION
    selected_models = []

    class Retained(old_joint):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.role_metadata["role_feature_version"] = "retained_player_history_indicator_v1"

    def capture(model, *args, **kwargs):
        selected_models.append(type(model))
        horizon, frame = build(model, *args, **kwargs)
        return horizon, frame.assign(model_version=version)

    monkeypatch.setattr(module, "RetainedHistoryRoleFootballModel", Retained)
    monkeypatch.setattr(module, "build_football_horizon", capture)
    options = {"retained_role_history": True} if retained else {}
    served, companion = module.produce_football_components(
        snapshot, tmp_path / "archive", role_minutes=True, training_seasons=SELECTION, **options
    )
    assert selected_models == [Retained if retained else old_joint]
    assert calls["fits"] == 1 and calls["archives"] == [SELECTION[:3]]
    assert served["model_version"] == companion["model_version"] == version
    assert served["role_metadata"] == companion["role_metadata"]
    assert companion["captured_availability"]["application"] == "not_applied"
    assert all("start_probability" in row for row in companion["rows"])
    path = tmp_path / "forecast.json"
    path.write_text(json.dumps(served, allow_nan=False), encoding="utf-8")
    forecast = read_football_forecast(path, inputs)
    basis = FixtureComponentBasis.from_documents(
        served,
        companion,
        fixture_calendar=calendars[0],
        roster_clubs={player: CLUBS[team] for player, (team, _) in PLAYERS.items()},
    )
    for column in ("expected_points", "appearance_probability"):
        left = forecast.horizon.table.sort_values(["gameweek", "player_id"])[column].to_numpy()
        right = basis.weekly_rows.sort_values(["gameweek", "player_id"])[column].to_numpy()
        assert left == pytest.approx(right)
    assert forecast.horizon.model_version == version
    assert forecast.horizon.model_name == "fixture_football_candidate"


@pytest.mark.parametrize("version", JOINT_ROLE_MODEL_VERSIONS)
@pytest.mark.parametrize("unknown", [False, True])
def test_roles_keep_actual_version_and_once_only_eligibility_without_public_probabilities(
    version, unknown
):
    football, inputs, _words, basis = world(selected_documents(version, unknown=unknown, dgw=True))
    result = bind(football, inputs, None, basis)
    assert_frame_equal(result.horizon.table, football.horizon.table)
    internal = result.projection.diagnostics["fixture_role_estimates"]
    public = role_forecast_summary(result.projection.diagnostics, {3}, model_version=version)
    assert public is not None and public["model_version"] == version
    Draft202012Validator(role_forecast_schema()).validate(public)
    source = basis.fixture_rows.loc[lambda f: f.player_code.eq(3) & f.GW.eq(6)]
    rows = [row for row in internal if row["player_id"] == 3]
    assert len(rows) == len(source) == 2
    assert sum(row["expected_minutes"] for row in rows) == pytest.approx(
        0.5 * float(source.expected_minutes.sum())
    )
    assert sum(row["point_components"]["total"] for row in rows) == pytest.approx(
        float(result.projection.table.set_index("player_id").loc[3, "expected_points"])
    )
    if unknown:
        assert all(row["start_probability"] is None for row in rows)
    assert all("start_probability" not in row for row in public["rows"])
    assert all(not row["news_applied"] for row in public["rows"])
    assert (
        role_forecast_summary(result.projection.diagnostics, {3}, model_version="unknown") is None
    )


def test_retained_joint_law_is_validated_and_minute_intervention_preserves_q():
    parts = selected_documents(JOINT_ROLE_RETAINED_HISTORY_MODEL_VERSION)
    basis = basis_from(parts)
    saved = deepcopy(parts[:2])
    result = apply_explicit_minute_evidence(basis, [claim()])
    before = basis.fixture_rows.loc[lambda f: f.player_code.eq(3) & f.fixture.eq(62)].iloc[0]
    after = result.fixture_rows.loc[lambda f: f.player_code.eq(3) & f.fixture.eq(62)].iloc[0]
    assert before.appearance_probability == after.appearance_probability
    assert before.start_probability == pytest.approx(after.start_probability)
    assert after.start_minute_probability_3 == after.cameo_minute_probability_3 == 0
    assert after.expected_minutes < before.expected_minutes
    assert parts[:2] == saved
    bad = deepcopy(parts)
    bad[1]["rows"][0].pop("start_probability")
    bad[1]["fingerprint"] = forecast_digest(bad[1])
    with pytest.raises(ValueError):
        basis_from(bad)
    frame = pd.DataFrame(parts[1]["rows"]).assign(model_version=parts[0]["model_version"])
    assert (
        "start_probability"
        in component_rows(frame, model_version=parts[0]["model_version"], players=parts[3])[0]
    )
    with pytest.raises(ValueError, match="minute fields"):
        component_rows(
            frame.drop(columns="start_probability"),
            model_version=parts[0]["model_version"],
            players=parts[3],
        )


def test_companion_cannot_mislabel_an_old_forecast_as_the_retained_candidate():
    parts = selected_documents(JOINT_ROLE_RETAINED_HISTORY_MODEL_VERSION)
    parts[1]["model_version"] = JOINT_ROLE_MODEL_VERSION
    parts[1]["fingerprint"] = forecast_digest(parts[1])
    with pytest.raises(ValueError, match="contract"):
        basis_from(parts)


def cli_arguments():
    args = [
        "build_football_forecast",
        "--snapshot-root",
        "synthetic",
        "--snapshot-id",
        "synthetic",
        "--archive-root",
        "unread",
        "--artifact-root",
        "unwritten",
    ]
    for season in SELECTION:
        args.extend(["--training-season", season])
    return args


@pytest.mark.parametrize("extra", [[], ["--role-minutes"], ["--with-components"]])
def test_incomplete_cli_selection_refuses_before_capture_or_fit(monkeypatch, extra):
    def forbidden(*args, **kwargs):
        pytest.fail("Invalid explicit selection must be refused before any capture read or fit.")

    monkeypatch.setattr(command, "read_snapshot", forbidden)
    monkeypatch.setattr("sys.argv", [*cli_arguments(), "--retained-role-history", *extra])
    with pytest.raises(SystemExit) as error:
        command.main()
    assert error.value.code == 2


@pytest.mark.parametrize("retained", [False, True])
def test_cli_passes_explicit_selection_only_and_keeps_existing_default(
    monkeypatch, capsys, retained
):
    calls = []

    def produce(*args, **kwargs):
        calls.append(kwargs)
        version = (
            JOINT_ROLE_RETAINED_HISTORY_MODEL_VERSION if retained else JOINT_ROLE_MODEL_VERSION
        )
        return {"fingerprint": "a" * 64, "rows": [], "model_version": version}, {
            "fingerprint": "b" * 64
        }

    monkeypatch.setattr(command, "read_snapshot", lambda *args: object())
    monkeypatch.setattr(command, "produce_football_components", produce)
    monkeypatch.setattr(command, "read_inputs", lambda *args, **kwargs: object())
    monkeypatch.setattr(command, "infer_season", lambda *args: "2026-27")
    monkeypatch.setattr(command, "publish_football_artifacts", lambda **kwargs: None)
    extra = ["--retained-role-history"] if retained else []
    monkeypatch.setattr(
        "sys.argv", [*cli_arguments(), "--role-minutes", "--with-components", *extra]
    )
    command.main()
    assert calls == [
        {
            "training_seasons": list(SELECTION),
            "role_minutes": True,
            **({"retained_role_history": True} if retained else {}),
        }
    ]
    assert json.loads(capsys.readouterr().out)["model_version"] == (
        JOINT_ROLE_RETAINED_HISTORY_MODEL_VERSION if retained else JOINT_ROLE_MODEL_VERSION
    )


@pytest.mark.parametrize("marker", [None, "unknown_feature"])
def test_new_version_refuses_unidentified_role_features_at_both_readers(tmp_path, marker):
    parts = selected_documents(JOINT_ROLE_RETAINED_HISTORY_MODEL_VERSION)
    _, inputs, _, _ = world(parts)
    for document in parts[:2]:
        if marker is None:
            document["role_metadata"].pop("role_feature_version")
        else:
            document["role_metadata"]["role_feature_version"] = marker
    parts[0]["fingerprint"] = forecast_digest(parts[0])
    parts[1]["forecast_fingerprint"] = parts[0]["fingerprint"]
    parts[1]["fingerprint"] = forecast_digest(parts[1])
    with pytest.raises(ValueError, match="role feature identity"):
        basis_from(parts)
    path = tmp_path / "unidentified.json"
    path.write_text(json.dumps(parts[0]), encoding="utf-8")
    with pytest.raises(ValueError, match="role feature identity"):
        read_football_forecast(path, inputs)
