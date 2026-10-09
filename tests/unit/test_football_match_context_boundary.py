"""Synthetic match-context publication, identity, worker and eligibility boundaries."""

import json
from copy import deepcopy
from dataclasses import replace
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
from squadopt.platform.advice_documents import ADVICE_READ_SCHEMA_PATH, advice_read_schema
from squadopt.platform.football_minute_basis import (
    football_components_path,
    load_football_minute_basis,
)
from squadopt.platform.football_publication import publish_football_artifacts
from squadopt.prediction.football import FOOTBALL_MODEL_VERSION
from squadopt.prediction.football_match_context import (
    MATCH_CONTEXT_FEATURE_VERSION,
    MATCH_CONTEXT_MODEL_VERSION,
    match_context_metadata,
)


def _refingerprint(case):
    served, companion = case["document"], case["companion"]
    served["fingerprint"] = forecast_digest(served)
    companion["forecast_fingerprint"] = served["fingerprint"]
    companion["fingerprint"] = forecast_digest(companion)


def _context_case(case):
    case = {
        **case,
        "document": deepcopy(case["document"]),
        "companion": deepcopy(case["companion"]),
    }
    for document in (case["document"], case["companion"]):
        document.update(
            model_version=MATCH_CONTEXT_MODEL_VERSION,
            feature_contract_version=MATCH_CONTEXT_FEATURE_VERSION,
            match_context_metadata=match_context_metadata(),
        )
    _refingerprint(case)
    return case


def _paths(case):
    return (
        football_artifact_path(case["artifact_root"], case["inputs"].snapshot_id),
        football_components_path(case["artifact_root"], case["inputs"].snapshot_id),
    )


def _assert_pair_readback(case, tmp_path, *, eligibility=0.5):
    forecast_path, _ = _paths(case)
    forecast = read_football_forecast(forecast_path, case["inputs"])
    loaded = load_football_minute_basis(
        artifact_root=case["artifact_root"],
        snapshot_root=tmp_path / "snapshots",
        inputs=case["inputs"],
        football=forecast,
    )
    assert loaded.reason is None
    assert loaded.basis is not None
    assert forecast.horizon.model_version == MATCH_CONTEXT_MODEL_VERSION
    assert forecast.horizon.feature_contract_version == MATCH_CONTEXT_FEATURE_VERSION
    assert forecast.projection.diagnostics["feature_contract_version"] == (
        MATCH_CONTEXT_FEATURE_VERSION
    )
    assert loaded.basis.companion["match_context_metadata"] == match_context_metadata()
    keys = ["gameweek", "player_id"]
    for column in ("expected_points", "appearance_probability"):
        actual = forecast.horizon.table.set_index(keys)[column].sort_index()
        rebuilt = loaded.basis.weekly_rows.set_index(keys)[column].sort_index()
        raw = pd.DataFrame(case["document"]["rows"]).set_index(keys)[column].sort_index()
        assert raw.gt(0).any()
        np.testing.assert_allclose(actual, rebuilt, rtol=0, atol=1e-12)
        # Both readers apply the fabricated capture label once, including zero.
        np.testing.assert_allclose(actual, raw * eligibility, rtol=0, atol=1e-12)
    return forecast


def test_match_context_pair_replay_reader_and_basis_preserve_identity(publication_case, tmp_path):
    case = _context_case(publication_case)
    forecast_path, companion_path = _paths(case)
    forecast_path.parent.mkdir(parents=True)
    existing = json.dumps(case["document"], indent=4).encode()
    forecast_path.write_bytes(existing)
    assert publish_football_artifacts(**case) == (forecast_path, companion_path)
    companion_bytes = companion_path.read_bytes()
    publish_football_artifacts(**case)
    assert forecast_path.read_bytes() == existing
    assert companion_path.read_bytes() == companion_bytes
    _assert_pair_readback(case, tmp_path)


def test_synthetic_source_producer_reader_and_basis_are_connected(
    publication_case, monkeypatch, tmp_path
):
    from squadopt.application import football_live

    case = publication_case
    inputs = case["inputs"]
    history = pd.DataFrame(
        {
            "season": ["2024-25", "2026-27"],
            "kickoff": pd.to_datetime(["2024-09-01T15:00:00Z", "2026-09-01T15:00:00Z"]),
        }
    )
    accesses, fits = [], []
    archive_root = tmp_path / "synthetic-archive-must-not-be-opened"

    def archive(root, *, seasons):
        assert root == archive_root
        assert seasons == ("2024-25",)
        accesses.append("selected_archive_stub")
        return history.loc[history.season.eq("2024-25")].copy()

    def captured(snapshot, *, season, gameweek):
        assert snapshot is case["snapshot"]
        assert (season, gameweek) == (inputs.season, inputs.deadline.gameweek)
        accesses.append("selected_capture_stub")
        return history.loc[history.season.eq("2026-27")].copy()

    def training(frame, *, prior_only_season, match_context):
        assert prior_only_season == "2024-25"
        assert match_context is True
        return frame.loc[frame.season.eq("2026-27")].copy()

    class Model:
        def __init__(self, training, supplied_history, *, cutoff):
            assert training.season.tolist() == ["2026-27"]
            assert supplied_history.season.tolist() == ["2024-25", "2026-27"]
            assert cutoff == pd.Timestamp(inputs.captured_at_utc)
            fits.append(self)

    def build(model, supplied_history, roster, calendar, **kwargs):
        assert model is fits[0]
        assert kwargs["source_snapshot_id"] == inputs.snapshot_id
        assert set(roster.player_id) == set(inputs.players.player_id)
        components = pd.DataFrame(case["companion"]["rows"])
        columns = ["GW", "fixture", "club", "opponent", "home"]
        expected = set(components[columns].drop_duplicates().itertuples(index=False, name=None))
        assert set(calendar[columns].itertuples(index=False, name=None)) == expected
        components["model_version"] = MATCH_CONTEXT_MODEL_VERSION
        return (
            SimpleNamespace(table=pd.DataFrame(case["document"]["rows"])),
            components,
        )

    original_read_bytes = Path.read_bytes

    def read_bytes(path):
        if path.is_relative_to(archive_root):
            assert "2024-25" in path.parts
            accesses.append("synthetic_hash")
            return path.as_posix().encode()
        return original_read_bytes(path)

    monkeypatch.setattr(football_live, "infer_season", lambda snapshot: inputs.season)
    monkeypatch.setattr(football_live, "read_inputs", lambda snapshot, *, season: inputs)
    monkeypatch.setattr(football_live, "archive_history", archive)
    monkeypatch.setattr(football_live, "captured_history", captured)
    monkeypatch.setattr(football_live, "causal_training", training)
    monkeypatch.setattr(football_live, "MatchContextFootballModel", Model)
    monkeypatch.setattr(football_live, "build_football_horizon", build)
    monkeypatch.setattr(Path, "read_bytes", read_bytes)
    served, companion = football_live.produce_football_components(
        case["snapshot"],
        archive_root,
        training_seasons=("2024-25", "2026-27"),
        match_context=True,
    )
    assert accesses == ["selected_archive_stub", "selected_capture_stub", *["synthetic_hash"] * 4]
    assert len(fits) == 1
    for document in (served, companion):
        assert document["model_version"] == MATCH_CONTEXT_MODEL_VERSION
        assert document["feature_contract_version"] == MATCH_CONTEXT_FEATURE_VERSION
        assert document["match_context_metadata"] == match_context_metadata()
        assert document["training_selection"]["prior_only_seasons"] == ["2024-25"]
    assert served["match_context_metadata"] is not companion["match_context_metadata"]
    case = {**case, "document": served, "companion": companion}
    publish_football_artifacts(**case)
    _assert_pair_readback(case, tmp_path)


@pytest.mark.parametrize("part", ["document", "companion"])
@pytest.mark.parametrize(
    "damage", ["missing_metadata", "scope", "head", "feature", "extra_key", "numeric_type"]
)
def test_new_identity_rejects_invalid_metadata_before_publishing_either_half(
    publication_case, part, damage
):
    case = _context_case(publication_case)
    document = case[part]
    if damage == "missing_metadata":
        document.pop("match_context_metadata")
    elif damage == "scope":
        document["match_context_metadata"]["context_features"]["all_competition_coverage"] = True
    elif damage == "head":
        document["match_context_metadata"]["minute_features"] = []
    elif damage == "feature":
        document["feature_contract_version"] = "causal_football_fixture_features_v1"
    elif damage == "numeric_type":
        document["match_context_metadata"]["context_features"]["all_competition_coverage"] = 0
    else:
        document["match_context_metadata"]["another_head"] = "unsupported"
    _refingerprint(case)
    with pytest.raises(ValueError, match="exact feature and head metadata"):
        publish_football_artifacts(**case)
    assert not any(path.exists() for path in _paths(case))


def test_new_identity_cannot_replace_existing_default_pair(publication_case):
    paths = publish_football_artifacts(**publication_case)
    previous = tuple(path.read_bytes() for path in paths)
    with pytest.raises(ValueError, match="different football document"):
        publish_football_artifacts(**_context_case(publication_case))
    assert tuple(path.read_bytes() for path in paths) == previous
    default = read_football_forecast(paths[0], publication_case["inputs"])
    assert default.horizon.model_version == FOOTBALL_MODEL_VERSION
    assert default.horizon.feature_contract_version == "causal_football_fixture_features_v1"


@pytest.mark.parametrize("chance", [0, 25, 50, 75, None])
def test_reader_and_basis_apply_each_capture_label_once(publication_case, tmp_path, chance):
    case = _context_case(publication_case)
    inputs = case["inputs"]
    availability = inputs.availability.assign(status="a", chance_of_playing=chance)
    case["inputs"] = replace(inputs, availability=availability)
    eligibility = 1.0 if chance is None else chance / 100
    for entry in case["companion"]["captured_availability"]["multipliers"]:
        entry["multiplier"] = eligibility
    _refingerprint(case)
    publish_football_artifacts(**case)
    forecast = _assert_pair_readback(case, tmp_path, eligibility=eligibility)
    if chance == 0:
        assert set(forecast.projection.unavailable_players) == set(inputs.players.player_id)


def test_match_context_artifact_survives_real_worker_and_document_schema(
    publication_case, monkeypatch
):
    import squadopt.platform.advice_worker as worker
    from squadopt.platform.advice_documents import validate_advice_document
    from squadopt.platform.advice_job_spec import AdviceJobSpec
    from squadopt.platform.advice_read import AdviceRequestContext
    from squadopt.platform.advice_switches import AdviceSwitchInputs, switch_identity
    from squadopt.platform.jobs_contract import AdviceJob

    case = _context_case(publication_case)
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
    fabricated = json.loads(_valid_advice_document(spec.entry_id))["payload"]
    fabricated.update(season=inputs.season, gameweek=inputs.deadline.gameweek)
    calls = []

    def plan(request, **kwargs):
        assert kwargs["projection"] is football.projection
        assert kwargs["horizon_builder"].__self__ is football
        calls.append(request)
        return deepcopy(fabricated)

    monkeypatch.setattr(worker, "advise_menu_entry", plan)
    job = AdviceJob(
        job_id="synthetic-match-context",
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
    assert result["payload"]["prediction_model"] == {
        "id": "football",
        "version": MATCH_CONTEXT_MODEL_VERSION,
        "experimental": True,
        "fingerprint": football.fingerprint,
    }
    assert result["payload"]["decision_information"] == switches.decision_information(
        inputs.snapshot_id
    )
    assert json.loads(ADVICE_READ_SCHEMA_PATH.read_text(encoding="utf-8")) == advice_read_schema()


@pytest.mark.parametrize(
    "options",
    [
        {"match_context": "yes"},
        {"match_context": True},
        {"match_context": True, "training_seasons": ("2025-26",)},
        {"match_context": True, "training_seasons": ("2024-25",), "contextual": True},
        {"match_context": True, "training_seasons": ("2024-25",), "role_minutes": True},
        {"match_context": True, "training_seasons": ("2024-25",), "retained_role_history": True},
    ],
)
def test_invalid_option_combinations_refuse_before_source_reads(monkeypatch, tmp_path, options):
    from squadopt.application import football_live

    def forbidden(*args, **kwargs):
        pytest.fail("Invalid options must fail before reading or fitting")

    for name in ("infer_season", "read_inputs", "archive_history", "captured_history"):
        monkeypatch.setattr(football_live, name, forbidden)
    with pytest.raises(ValueError):
        football_live.produce_football_forecast(object(), tmp_path, **options)


@pytest.mark.parametrize("with_components", [False, True])
def test_cli_forwards_explicit_candidate_and_selected_sources(
    publication_case, monkeypatch, capsys, with_components
):
    import scripts.build_football_forecast as command

    case = _context_case(publication_case)
    calls = []
    selected = ["2024-25", "2026-27"]

    def ordinary(snapshot, archive_root, **kwargs):
        assert snapshot is case["snapshot"]
        assert archive_root == Path("synthetic-archive-never-read")
        assert kwargs == {
            "contextual": False,
            "manager_words": None,
            "training_seasons": selected,
            "match_context": True,
        }
        calls.append("ordinary")
        return case["document"]

    def paired(snapshot, archive_root, **kwargs):
        assert snapshot is case["snapshot"]
        assert archive_root == Path("synthetic-archive-never-read")
        assert kwargs == {"training_seasons": selected, "match_context": True}
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
        "synthetic-snapshot-never-read",
        "--snapshot-id",
        case["inputs"].snapshot_id,
        "--archive-root",
        "synthetic-archive-never-read",
        "--artifact-root",
        str(case["artifact_root"]),
        "--match-context",
    ]
    for season in selected:
        argv.extend(["--training-season", season])
    if with_components:
        argv.append("--with-components")
    monkeypatch.setattr("sys.argv", argv)
    command.main()
    assert calls == ["paired" if with_components else "ordinary"]
    output = json.loads(capsys.readouterr().out)
    assert output["model_version"] == MATCH_CONTEXT_MODEL_VERSION
    assert output["fingerprint"] == case["document"]["fingerprint"]
    assert ("components_fingerprint" in output) is with_components
    assert _paths(case)[1].exists() is with_components


@pytest.mark.parametrize(
    "extra",
    [
        [],
        ["--training-season", "2025-26"],
        ["--training-season", "2024-25", "--contextual"],
        ["--training-season", "2024-25", "--role-minutes"],
        ["--training-season", "2024-25", "--retained-role-history"],
        ["--training-season", "2024-25", "--rotation-evidence", "unused"],
        ["--training-season", "2024-25", "--club-news-source", "unused"],
    ],
)
def test_cli_invalid_candidate_mode_refuses_before_any_capture_read(monkeypatch, extra):
    import scripts.build_football_forecast as command

    def forbidden(*args, **kwargs):
        pytest.fail("Invalid CLI options must fail before capture reads")

    monkeypatch.setattr(command, "read_snapshot", forbidden)
    monkeypatch.setattr(
        "sys.argv",
        [
            "build_football_forecast.py",
            "--snapshot-root",
            "unused",
            "--snapshot-id",
            "unused",
            "--archive-root",
            "unused",
            "--artifact-root",
            "unused",
            "--match-context",
            *extra,
        ],
    )
    with pytest.raises(SystemExit) as failure:
        command.main()
    assert failure.value.code == 2


@pytest.mark.parametrize("chance", [25, 50, 75])
@pytest.mark.parametrize("window", [3, 5])
def test_context_observations_preserve_mean_and_conditional_appearance(chance, window):
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
    observations = availability_observations(
        horizon,
        InitialSquadState((1, 2), 0, 1),
        pd.DataFrame({"player_id": [2], "chance_of_playing": [chance]}),
        model_version=MATCH_CONTEXT_MODEL_VERSION,
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
    assert unavailable.expected_points == unavailable.appearance_probability == 0
    original = before.loc[before.gameweek.eq(7) & before.player_id.eq(2)].iloc[0]
    assert eligible.expected_points / eligible.appearance_probability == pytest.approx(
        original.expected_points / original.appearance_probability
    )
    for node in observations.nodes:
        assert_frame_equal(
            node.horizon.table.loc[node.horizon.table.gameweek.ge(8)],
            before.loc[before.gameweek.ge(8)],
        )
