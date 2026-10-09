"""Synthetic team-form publication, command and eligibility contract checks."""

import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal
from tests.unit.test_advice_read import _valid_advice_document
from tests.unit.test_football_publication import publication_case as publication_case

from squadopt.live.football_artifact import (
    football_artifact_path,
    forecast_digest,
    read_football_forecast,
)
from squadopt.live.football_observations import availability_observations
from squadopt.planning import InitialSquadState, PlanningHorizon
from squadopt.planning.observed import validate_observations
from squadopt.platform.football_minute_basis import (
    football_components_path,
    load_football_minute_basis,
)
from squadopt.platform.football_publication import publish_football_artifacts
from squadopt.prediction.football import FOOTBALL_MODEL_VERSION
from squadopt.prediction.football_team_form import (
    TEAM_FORM_FEATURE_VERSION,
    TEAM_FORM_MODEL_VERSION,
    team_form_metadata,
)


def _refingerprint(case):
    case["document"]["fingerprint"] = forecast_digest(case["document"])
    case["companion"]["forecast_fingerprint"] = case["document"]["fingerprint"]
    case["companion"]["fingerprint"] = forecast_digest(case["companion"])


def _form_case(case):
    case = {
        **case,
        "document": deepcopy(case["document"]),
        "companion": deepcopy(case["companion"]),
    }
    # Form retains the v1 fixture scoring algebra; these are fabricated components.
    for document in (case["document"], case["companion"]):
        document["model_version"] = TEAM_FORM_MODEL_VERSION
        document["feature_contract_version"] = TEAM_FORM_FEATURE_VERSION
        document["team_form_metadata"] = team_form_metadata()
        document["training_selection"] = {
            "contract_version": "football_training_selection_v1",
            "allowed_seasons": ["2024-25", "2026-27"],
            "prior_only_seasons": ["2024-25"],
            "prior_policy": "first_selected_usable_season_prior_only",
        }
    _refingerprint(case)
    return case


def _paths(case):
    return (
        football_artifact_path(case["artifact_root"], case["inputs"].snapshot_id),
        football_components_path(case["artifact_root"], case["inputs"].snapshot_id),
    )


def test_form_pair_publishes_reloads_and_preserves_existing_bytes(publication_case, tmp_path):
    case = _form_case(publication_case)
    forecast_path, companion_path = _paths(case)
    forecast_path.parent.mkdir(parents=True)
    existing = json.dumps(case["document"], indent=4).encode()
    forecast_path.write_bytes(existing)
    assert publish_football_artifacts(**case) == (forecast_path, companion_path)
    companion_bytes = companion_path.read_bytes()
    publish_football_artifacts(**case)
    assert forecast_path.read_bytes() == existing
    assert companion_path.read_bytes() == companion_bytes
    forecast = read_football_forecast(forecast_path, case["inputs"])
    loaded = load_football_minute_basis(
        artifact_root=case["artifact_root"],
        snapshot_root=tmp_path / "snapshots",
        inputs=case["inputs"],
        football=forecast,
    )
    assert loaded.reason is None
    assert loaded.basis is not None
    assert forecast.horizon.model_version == TEAM_FORM_MODEL_VERSION
    assert forecast.horizon.feature_contract_version == TEAM_FORM_FEATURE_VERSION
    assert loaded.basis.companion["team_form_metadata"] == team_form_metadata()
    keys = ["gameweek", "player_id"]
    for column in ("expected_points", "appearance_probability"):
        actual = forecast.horizon.table.set_index(keys)[column].sort_index()
        rebuilt = loaded.basis.weekly_rows.set_index(keys)[column].sort_index()
        raw = pd.DataFrame(case["document"]["rows"]).set_index(keys)[column].sort_index()
        assert raw.gt(0).any()
        assert np.allclose(actual, rebuilt, rtol=0, atol=1e-12)
        # Every source label in this fabricated pair is 50; eligibility enters once.
        assert np.allclose(actual, raw * 0.5, rtol=0, atol=1e-12)


@pytest.mark.parametrize("damage", ["missing_metadata", "windows", "feature", "model"])
def test_form_companion_identity_failure_publishes_neither_half(publication_case, damage):
    case = _form_case(publication_case)
    companion = case["companion"]
    if damage == "missing_metadata":
        companion.pop("team_form_metadata")
    elif damage == "windows":
        companion["team_form_metadata"]["windows"] = [2, 8]
    elif damage == "feature":
        companion["feature_contract_version"] = "causal_football_fixture_features_v1"
    else:
        companion["model_version"] = FOOTBALL_MODEL_VERSION
    _refingerprint(case)
    with pytest.raises(ValueError):
        publish_football_artifacts(**case)
    assert not any(path.exists() for path in _paths(case))


def test_form_conflict_preserves_the_previous_v1_pair(publication_case):
    legacy = publication_case
    forecast_path, companion_path = publish_football_artifacts(**legacy)
    before = (forecast_path.read_bytes(), companion_path.read_bytes())
    with pytest.raises(ValueError, match="different football document"):
        publish_football_artifacts(**_form_case(legacy))
    assert (forecast_path.read_bytes(), companion_path.read_bytes()) == before
    assert read_football_forecast(forecast_path, legacy["inputs"]).horizon.model_version == (
        FOOTBALL_MODEL_VERSION
    )


def test_form_artifact_survives_worker_document_validation(publication_case, monkeypatch):
    import squadopt.platform.advice_worker as worker
    from squadopt.platform.advice_documents import validate_advice_document
    from squadopt.platform.advice_job_spec import AdviceJobSpec
    from squadopt.platform.advice_read import AdviceRequestContext
    from squadopt.platform.advice_switches import AdviceSwitchInputs, switch_identity
    from squadopt.platform.jobs_contract import AdviceJob

    case = _form_case(publication_case)
    forecast_path, _ = publish_football_artifacts(**case)
    inputs = case["inputs"]
    football = read_football_forecast(forecast_path, inputs)
    switches = AdviceSwitchInputs(football=football)
    context = AdviceRequestContext(
        advice_contract_version="provisional_league_ui_v1",
        capture_snapshot_id=inputs.snapshot_id,
        season=inputs.season,
        gameweek=inputs.deadline.gameweek,
        projection_handoff_fingerprint="a" * 64,
        repository_commit="b" * 40,
        configuration_fingerprint="c" * 64,
    )
    spec = AdviceJobSpec(
        league_id=352490,
        entry_id=313686,
        strategy="saf-puan",
        window=1,
        context=context,
        switches=switch_identity(switches, model="football"),
    )
    # In-memory collaborators exercise the actual compute boundary without a backend
    # or another planner solve. Only the plan result is fabricated.
    capture = SimpleNamespace(
        switches=switches,
        inputs=inputs,
        provider=SimpleNamespace(holds=lambda entry, week: True),
        rules=None,
        top100_counts=None,
        manager_words=None,
    )
    contexts = SimpleNamespace(capture=lambda value: capture if value == context else None)
    specs = SimpleNamespace(get=lambda key: spec if key == "d" * 64 else None)
    produced = json.loads(_valid_advice_document(spec.entry_id))["payload"]
    produced.update(season=inputs.season, gameweek=inputs.deadline.gameweek)
    calls = []

    def plan(request, **kwargs):
        assert request.gameweek == inputs.deadline.gameweek
        assert kwargs["projection"] is football.projection
        assert kwargs["horizon_builder"].__self__ is football
        calls.append(request)
        return deepcopy(produced)

    monkeypatch.setattr(worker, "advise_menu_entry", plan)
    job = AdviceJob(
        job_id="synthetic-team-form",
        status="running",
        request_fingerprint="e" * 64,
        cache_key="d" * 64,
        created_at_utc=inputs.captured_at_utc,
        updated_at_utc=inputs.captured_at_utc,
    )
    raw = worker.build_advice_compute(contexts, specs)(job)
    validate_advice_document(raw)
    result = json.loads(raw)
    assert len(calls) == 1
    assert result["generated_at_utc"] == inputs.captured_at_utc
    assert result["payload"]["prediction_model"] == {
        "id": "football",
        "version": TEAM_FORM_MODEL_VERSION,
        "experimental": True,
        "fingerprint": football.fingerprint,
    }
    assert result["payload"]["decision_information"] == switches.decision_information(
        inputs.snapshot_id
    )


@pytest.mark.parametrize("with_components", [False, True])
def test_cli_forwards_explicit_team_form_and_training_selection(
    publication_case, monkeypatch, capsys, with_components
):
    import scripts.build_football_forecast as command

    case = _form_case(publication_case)
    calls = []
    selected = ["2024-25", "2026-27"]

    def ordinary(snapshot, archive_root, **kwargs):
        assert snapshot is case["snapshot"]
        assert archive_root == Path("must-not-be-read")
        assert kwargs == {
            "contextual": False,
            "manager_words": None,
            "training_seasons": selected,
            "team_form": True,
        }
        calls.append("ordinary")
        return case["document"]

    def paired(snapshot, archive_root, **kwargs):
        assert snapshot is case["snapshot"]
        assert archive_root == Path("must-not-be-read")
        assert kwargs == {"training_seasons": selected, "team_form": True}
        calls.append("paired")
        return case["document"], case["companion"]

    monkeypatch.setattr(command, "produce_football_forecast", ordinary)
    monkeypatch.setattr(command, "produce_football_components", paired)
    monkeypatch.setattr(command, "read_snapshot", lambda *args: case["snapshot"])
    monkeypatch.setattr(command, "read_inputs", lambda *args, **kwargs: case["inputs"])
    monkeypatch.setattr(command, "infer_season", lambda *args: case["inputs"].season)
    argv = [
        "build_football_forecast.py",
        "--snapshot-root",
        "unused-synthetic",
        "--snapshot-id",
        case["inputs"].snapshot_id,
        "--archive-root",
        "must-not-be-read",
        "--artifact-root",
        str(case["artifact_root"]),
        "--team-form",
    ]
    for season in selected:
        argv.extend(["--training-season", season])
    if with_components:
        argv.append("--with-components")
    monkeypatch.setattr("sys.argv", argv)
    command.main()
    assert calls == ["paired" if with_components else "ordinary"]
    output = json.loads(capsys.readouterr().out)
    assert output["model_version"] == TEAM_FORM_MODEL_VERSION
    assert output["fingerprint"] == case["document"]["fingerprint"]
    assert ("components_fingerprint" in output) is with_components
    assert _paths(case)[1].exists() is with_components


@pytest.mark.parametrize("chance", [25, 50, 75])
@pytest.mark.parametrize("window", [3, 5])
def test_form_observed_eligibility_preserves_mean_and_conditional_minutes(chance, window):
    rows = [
        {
            "gameweek": week,
            "player_id": player,
            "name": f"Synthetic {player}",
            "team_id": 1,
            "position": "GK" if player == 1 else "FWD",
            "buy_price_tenths": 50,
            "sell_price_tenths": 50,
            "expected_points": 3.0 if player == 1 else 6.0 * chance / 100,
            "appearance_probability": 0.8 if player == 1 else 0.8 * chance / 100,
        }
        for week in range(6, 6 + window)
        for player in (1, 2)
    ]
    horizon = PlanningHorizon(pd.DataFrame(rows))
    before = horizon.table.copy(deep=True)
    initial = InitialSquadState((1, 2), 0, 1)
    observations = availability_observations(
        horizon,
        initial,
        pd.DataFrame({"player_id": [2], "chance_of_playing": [chance]}),
        model_version=TEAM_FORM_MODEL_VERSION,
        source_snapshot_id="synthetic",
        captured_at_utc="2026-09-22T12:00:00Z",
        deadline_utc="2026-09-23T12:00:00Z",
    )
    assert observations.reason == "captured_eligibility_resolves_next_deadline"
    assert len(observations.nodes) == 2
    validate_observations(horizon, observations.nodes)
    assert_frame_equal(horizon.table, before, check_exact=True)
    yes, no = observations.nodes
    eligible = yes.horizon.table.loc[
        yes.horizon.table.gameweek.eq(7) & yes.horizon.table.player_id.eq(2)
    ].iloc[0]
    unavailable = no.horizon.table.loc[
        no.horizon.table.gameweek.eq(7) & no.horizon.table.player_id.eq(2)
    ].iloc[0]
    assert eligible.expected_points == pytest.approx(6.0)
    assert eligible.appearance_probability == pytest.approx(0.8)
    assert unavailable.expected_points == 0
    assert unavailable.appearance_probability == 0
    original = before.loc[before.gameweek.eq(7) & before.player_id.eq(2)].iloc[0]
    assert eligible.expected_points / eligible.appearance_probability == pytest.approx(
        original.expected_points / original.appearance_probability
    )
    for node in observations.nodes:
        later = node.horizon.table.gameweek.ge(8)
        assert_frame_equal(node.horizon.table.loc[later], before.loc[before.gameweek.ge(8)])
