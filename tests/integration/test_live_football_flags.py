"""Learned flags through publication, coupled weeks, minute news and live readers."""

from __future__ import annotations

import copy
import json
import math
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from tests.fixtures.backend_app import app_for_capture
from tests.fixtures.football_flag_fixtures import native_case, training_weeks
from tests.unit import test_live_transfers as source_world
from tests.unit.test_source_fpl_live import _history_payload, _picks_payload

from squadopt.application import football_live
from squadopt.application.football_participation import bind_football_participation
from squadopt.application.football_roles import fixture_role_estimates
from squadopt.data.snapshots import read_snapshot, write_snapshot
from squadopt.live import InSeasonProjection, read_inputs, write_projection_handoff
from squadopt.live.football_artifact import (
    ARTIFACT_CONTRACT,
    SHARES_BEFORE_AVAILABILITY_LIMIT,
    forecast_digest,
    read_football_forecast,
)
from squadopt.live.minute_evidence import ExplicitMinuteEvidence, apply_explicit_minute_evidence
from squadopt.live.tick import handoff_path_for
from squadopt.platform.advice_queue import run_advice_worker_once
from squadopt.platform.advice_worker import build_advice_compute
from squadopt.platform.backend_runtime import BackendConfig, build_backend
from squadopt.platform.football_bundle import seal_football_bundle
from squadopt.platform.football_minute_basis import _basis_from_snapshot
from squadopt.platform.football_publication import publish_football_artifacts
from squadopt.prediction.availability import apply_availability
from squadopt.prediction.football import (
    JOINT_ROLE_FLAG_MODEL_VERSION,
    JOINT_ROLE_RETAINED_HISTORY_MODEL_VERSION,
)
from squadopt.prediction.football_components import captured_availability, component_rows
from squadopt.prediction.football_flag_minutes import FlagMinutesModel
from squadopt.prediction.football_minutes_role import RETAINED_HISTORY_ROLE_FEATURE_VERSION


def make_live_case(tmp_path_factory, *, fit_cutoff=None):
    case = native_case(double=True)
    frames = []
    for week in range(6, 11):
        frame = case.components.copy(deep=True)
        if week > 7:
            frame = frame.loc[frame.fixture.ne(69)].copy()
        frame["GW"] = week
        frame["fixture"] += 1000 * (week - 6)
        frame["kickoff"] = pd.to_datetime(frame.kickoff, utc=True) + pd.Timedelta(
            days=7 * (week - 6)
        )
        frames.append(frame)
    components = pd.concat(frames, ignore_index=True)
    components["model_version"] = JOINT_ROLE_RETAINED_HISTORY_MODEL_VERSION
    roster = case.roster[["player_id", "name", "team_id", "position"]].copy()
    roster["price_tenths"] = case.roster.buy_price_tenths
    rows = []
    for week in range(6, 11):
        for player in roster.to_dict("records"):
            group = components.loc[
                components.GW.eq(week) & components.player_code.eq(player["player_id"])
            ]
            rows.append(
                player
                | {
                    "gameweek": week,
                    "expected_points": float(group.expected_points.sum()),
                    "appearance_probability": 1
                    - math.prod(1 - float(q) for q in group.appearance_probability),
                    "fixture_count": len(group),
                    "home_fixture_count": int(group.home.sum()),
                }
            )
    captured, decision, deadline = (
        "2026-09-22T11:00:00+00:00",
        "2026-09-22T12:00:00+00:00",
        "2026-09-22T18:00:00+00:00",
    )
    boot = {
        "events": [
            {"id": 1, "deadline_time": "2026-08-01T12:00:00Z", "is_next": False, "finished": True},
            {"id": 6, "deadline_time": deadline, "is_next": True, "finished": False},
        ],
        "teams": [{"id": club, "code": club, "name": f"Club {club}"} for club in range(1, 7)],
        "elements": [
            {
                "id": int(row.player_id),
                "code": int(row.player_id),
                "team": int(row.team_id),
                "element_type": ("GK", "DEF", "MID", "FWD").index(row.position) + 1,
                "first_name": "Synthetic",
                "second_name": str(row.player_id),
                "web_name": row.name,
                "now_cost": int(row.price_tenths),
                "status": "d",
                "chance_of_playing_next_round": int(
                    100 * case.captured_availability[int(row.player_id)]
                ),
                "news": "Synthetic flag",
                "news_added": "2026-09-22T10:00:00Z",
            }
            for row in roster.itertuples()
        ],
    }
    rules_source = json.loads(source_world._bootstrap())
    boot.update({key: rules_source[key] for key in ("game_config", "chips")})
    for row in rows:
        row["team_id"] = f"Club {row['team_id']}"
    roster["team_id"] = roster.team_id.map(lambda club: f"Club {club}")
    calendar = components[
        ["GW", "fixture", "club", "opponent", "home", "kickoff"]
    ].drop_duplicates()
    fixtures = [
        {
            "id": int(row.fixture),
            "event": int(row.GW),
            "team_h": int(row.club),
            "team_a": int(row.opponent),
            "kickoff_time": row.kickoff.isoformat(),
            "team_h_difficulty": 3,
            "team_a_difficulty": 3,
            "finished": False,
            "provisional_start_time": False,
        }
        for row in calendar.loc[calendar.home.eq(1)].itertuples()
    ]
    root = tmp_path_factory.mktemp("learned-flags")
    metadata = write_snapshot(
        root / "snapshots",
        source="fpl-live",
        captured_at_utc=captured,
        payloads={
            "bootstrap-static.json": json.dumps(boot).encode(),
            "fixtures.json": json.dumps(fixtures).encode(),
            "entry-101-picks-gw05.json": _picks_payload(
                squad=[1, 3, 4, 5, 6, 8, 9, 10, 11, 13, 14, 2, 7, 12, 15]
            ),
            "entry-101-history.json": _history_payload(
                current=[
                    {
                        "event": week,
                        "event_transfers": 0,
                        "event_transfers_cost": 0,
                        "points": 40,
                        "total_points": 40 * week,
                        "points_on_bench": 0,
                        "bank": 5,
                    }
                    for week in range(1, 6)
                ]
            ),
        },
    )
    snapshot = read_snapshot(root / "snapshots", metadata.snapshot_id)
    captured = metadata.captured_at_utc
    availability = pd.DataFrame(
        {
            "player_id": roster.player_id,
            "status": "d",
            "chance_of_playing": [
                int(100 * case.captured_availability[int(p)]) for p in roster.player_id
            ],
        }
    )
    inputs = read_inputs(snapshot, season="2026-27")
    original = {
        "contract_version": ARTIFACT_CONTRACT,
        "model_version": JOINT_ROLE_RETAINED_HISTORY_MODEL_VERSION,
        "season": inputs.season,
        "gameweek": 6,
        "source_snapshot_id": metadata.snapshot_id,
        "captured_at_utc": captured,
        "source_fingerprint": metadata.fingerprint,
        "training_rows": 100,
        "training_latest_kickoff": "2026-09-01T15:00:00+00:00",
        "archive_hashes": {},
        "training_selection": {"allowed_seasons": ["2022-23", "2023-24", "2024-25", "2026-27"]},
        "role_metadata": {"role_feature_version": RETAINED_HISTORY_ROLE_FEATURE_VERSION},
        "limitations": [],
        "rows": rows,
    }
    original["fingerprint"] = forecast_digest(original)
    companion = {
        key: copy.deepcopy(original[key])
        for key in (
            "model_version",
            "season",
            "gameweek",
            "source_snapshot_id",
            "captured_at_utc",
            "source_fingerprint",
            "training_rows",
            "training_latest_kickoff",
            "archive_hashes",
            "training_selection",
            "role_metadata",
        )
    }
    companion.update(
        contract_version="football_fixture_components_v1",
        gameweeks=list(range(6, 11)),
        forecast_fingerprint=original["fingerprint"],
        captured_availability=captured_availability(
            case.captured_availability,
            apply_availability(roster.assign(expected_points=1.0), availability).diagnostics,
        ),
        limitations=[],
        rows=component_rows(
            components,
            model_version=JOINT_ROLE_RETAINED_HISTORY_MODEL_VERSION,
            players=roster.player_id,
        ),
    )
    companion["fingerprint"] = forecast_digest(companion)
    patch = pytest.MonkeyPatch()
    patch.setattr(football_live, "infer_season", lambda snapshot: "2026-27")
    patch.setattr(football_live, "read_inputs", lambda *a, **kw: inputs)
    patch.setattr(
        football_live,
        "produce_football_components",
        lambda *a, **kw: (copy.deepcopy(original), copy.deepcopy(companion)),
    )
    if fit_cutoff is not None:
        retained = FlagMinutesModel(
            training_weeks(), fit_cutoff=fit_cutoff, target_season="2026-27", target_gameweeks=(6,)
        )
        patch.setattr(football_live, "FlagMinutesModel", lambda *a, **kw: retained)
    try:
        document, result = football_live.produce_flagged_football_components(
            snapshot,
            Path("unused-synthetic-archive"),
            training=training_weeks(),
            decision_at=decision,
        )
    finally:
        patch.undo()
    return root, snapshot, inputs, document, result, original, calendar, case


@pytest.fixture(scope="module")
def live_case(tmp_path_factory):
    return make_live_case(tmp_path_factory)


def loaded(live_case, *, document=None, companion=None):
    root, snapshot, inputs, original_doc, original_companion, _, _, _ = live_case
    document = copy.deepcopy(original_doc if document is None else document)
    companion = copy.deepcopy(original_companion if companion is None else companion)
    path = root / "read-only-forecast.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    football = read_football_forecast(path, inputs)
    basis = _basis_from_snapshot(document, companion, snapshot, inputs, football)
    return football, basis


def test_actual_fitted_head_round_trips_without_another_fit_or_flag_multiplier(
    live_case, monkeypatch
):
    root, snapshot, inputs, document, companion, _, _, _ = live_case
    assert document["model_version"] == "football_joint_role_retained_flags_v2"
    assert document["flag_metadata"]["contract_version"] == "football_first_week_flags_v2"
    assert (
        document["flag_metadata"]["feature_version"]
        == "causal_categorical_flag_minutes_features_v2"
    )
    assert document["flag_metadata"]["fit_cutoff"] == document["captured_at_utc"]
    monkeypatch.setattr(
        FlagMinutesModel, "fit", lambda *a, **kw: pytest.fail("Reading must never fit")
    )
    publish_football_artifacts(
        artifact_root=root / "artifacts",
        snapshot=snapshot,
        inputs=inputs,
        document=document,
        companion=companion,
    )
    football, basis = loaded(live_case)
    assert football.horizon.model_version == JOINT_ROLE_FLAG_MODEL_VERSION
    first = football.horizon.table.loc[football.horizon.table.gameweek.eq(6)].set_index("player_id")
    assert 0 < first.loc[7, "appearance_probability"] < 1  # Original categorical zero.
    assert (
        basis.weekly_rows.loc[lambda f: f.gameweek.eq(6)]
        .set_index("player_id")
        .appearance_probability.equals(first.appearance_probability)
    )
    law = next(row for row in document["flag_metadata"]["weekly_laws"] if row["player_code"] == 3)
    assert first.loc[3, "appearance_probability"] == pytest.approx(sum(law["probabilities"][1:]))
    fixture_q = basis.fixture_rows.loc[
        lambda f: f.GW.eq(6) & f.player_code.eq(3)
    ].appearance_probability
    assert not math.isclose(
        float(first.loc[3, "appearance_probability"]),
        1 - math.prod(1 - float(q) for q in fixture_q),
        abs_tol=1e-9,
    )


def test_reused_older_fitted_head_preserves_original_cutoff_and_round_trips(tmp_path_factory):
    cutoff = "2026-09-22T10:30:00+00:00"
    case = make_live_case(tmp_path_factory, fit_cutoff=cutoff)
    _, _, _, document, companion, _, _, _ = case
    assert document["flag_metadata"]["fit_cutoff"] == cutoff
    assert companion["flag_metadata"]["fit_cutoff"] == cutoff
    football, basis = loaded(case)
    assert football.horizon.model_version == JOINT_ROLE_FLAG_MODEL_VERSION
    assert basis is not None


def test_missing_fitted_flag_cutoff_is_refused(live_case):
    _, _, _, original, original_companion, _, _, _ = live_case
    document, companion = copy.deepcopy(original), copy.deepcopy(original_companion)
    del document["flag_metadata"]["fit_cutoff"]
    reseal(document, companion)
    with pytest.raises(ValueError, match="clocks"):
        loaded(live_case, document=document, companion=companion)


@pytest.mark.parametrize("window", [1, 3, 5])
def test_future_horizons_keep_the_exact_native_legacy_rule(live_case, window):
    _, _, _, _, _, native, _, case = live_case
    football, _ = loaded(live_case)
    horizon = football.build_horizon(tuple(range(6, 6 + window)))
    assert len(horizon.table) == 66 * window
    originals = pd.DataFrame(native["rows"]).set_index(["gameweek", "player_id"])
    for row in horizon.table.loc[horizon.table.gameweek.ne(6)].itertuples():
        old = originals.loc[row.gameweek, row.player_id]
        a = case.captured_availability[row.player_id]
        assert row.expected_points == old.expected_points * a
        assert row.appearance_probability == old.appearance_probability * a


def test_minute_news_preserves_the_learned_joint_week_hurdle_and_role_explanation(live_case):
    _, _, inputs, _, _, _, _, _ = live_case
    _, basis = loaded(live_case)
    evidence = ExplicitMinuteEvidence(
        "synthetic-no-full-match",
        3,
        6,
        (62,),
        "no_full_match",
        "https://example.invalid/verified",
        "a" * 64,
        0,
        10,
    )
    result = apply_explicit_minute_evidence(basis, (evidence,))
    pd.testing.assert_series_equal(
        result.weekly_rows.appearance_probability, basis.weekly_rows.appearance_probability
    )
    old = basis.fixture_rows.loc[lambda f: f.player_code.eq(3) & f.fixture.eq(62)].iloc[0]
    roles = fixture_role_estimates(
        basis, inputs, revised_rows=result.fixture_rows, applied_fixtures=frozenset({(3, 62)})
    )
    role = next(row for row in roles if row["player_id"] == 3 and row["fixture_id"] == 62)
    # This field quotes the captured input; the learned law is already scaled.
    assert role["captured_eligibility_multiplier"] == 0.75
    assert role["expected_minutes"] < old.expected_minutes
    revised = result.fixture_rows.loc[lambda f: f.player_code.eq(3) & f.fixture.eq(62)].iloc[0]
    assert role["expected_minutes"] == revised.expected_minutes


def test_participation_binding_does_not_reinterpret_the_categorical_inputs_as_probabilities(
    live_case,
):
    _, _, inputs, _, _, _, _, _ = live_case
    football, basis = loaded(live_case)
    bound = bind_football_participation(
        football, inputs, manager_words=None, rotation_table_sha256=None, minute_basis=basis
    )
    for column in ("expected_points", "appearance_probability"):
        pd.testing.assert_series_equal(bound.horizon.table[column], football.horizon.table[column])
    audit = bound.projection.diagnostics["participation_evidence"]
    assert audit["captured_percentages"] == []


@pytest.mark.parametrize("window", [1, 3, 5])
def test_sealed_learned_flags_reach_the_http_worker_and_its_cached_member_answer(
    live_case, tmp_path, monkeypatch, window
):
    root, snapshot, inputs, document, companion, _, _, _ = live_case
    artifact_root, handoffs, site = tmp_path / "artifacts", tmp_path / "handoffs", tmp_path / "site"
    publish_football_artifacts(
        artifact_root=artifact_root,
        snapshot=snapshot,
        inputs=inputs,
        document=document,
        companion=companion,
    )
    handoff = InSeasonProjection(
        inputs.season,
        6,
        inputs.snapshot_id,
        "in_season_control",
        "in-season-carry-over-v1",
        "synthetic-features",
        {int(p): 2.0 for p in inputs.players.player_id},
    )
    handoff_path = handoff_path_for(handoffs, inputs.season, 6)
    write_projection_handoff(handoff_path, handoff)
    for filename, payload in (
        (
            "members.json",
            {
                "league_id": 1,
                "league_name": "Synthetic",
                "season": inputs.season,
                "gameweek": 6,
                "members": [{"member_kind": "human", "entry_id": 101}],
            },
        ),
        (
            "entries/101.json",
            {
                "league_id": 1,
                "season": inputs.season,
                "gameweek": 6,
                "source_snapshot_id": inputs.snapshot_id,
                "entry": {"member_kind": "human", "entry_id": 101},
            },
        ),
    ):
        path = site / "league" / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "contract_version": "provisional_league_ui_v1",
                    "payload": payload,
                    "generated_at_utc": "2026-09-22T13:00:00Z",
                }
            )
        )
    sealed = seal_football_bundle(
        artifact_root=artifact_root,
        snapshot_root=root / "snapshots",
        snapshot_id=inputs.snapshot_id,
        handoff_path=handoff_path,
        site_data_root=site,
    )
    monkeypatch.setenv("SQUADOPT_REPOSITORY_COMMIT", "a" * 40)
    store = tmp_path / "store"
    store.mkdir()
    backend = build_backend(
        BackendConfig(
            store_root=store,
            site_data_root=site,
            snapshot_root=root / "snapshots",
            handoff_root=handoffs,
            artifact_root=artifact_root,
        )
    )
    client = TestClient(app_for_capture(backend, inputs.captured_at_utc))
    route = "/api/v1/leagues/1/entries/101/advice"
    body = {"strategy": "saf-puan", "window": window, "model": "football"}
    accepted = client.post(route, json=body)
    assert accepted.status_code == 202, accepted.text
    job = run_advice_worker_once(
        backend.queue,
        backend.cache,
        build_advice_compute(backend.contexts, backend.job_specs, cache=backend.cache),
        at_utc="2026-09-22T13:00:00Z",
    )
    assert job.status == "completed", job.error
    served = client.get(route, params=body)
    assert served.status_code == 200, served.text
    payload = served.json()["payload"]
    assert payload["prediction_model"]["version"] == JOINT_ROLE_FLAG_MODEL_VERSION
    assert payload["prediction_model"]["fingerprint"] == document["fingerprint"]
    assert payload["role_forecast"]["model_version"] == JOINT_ROLE_FLAG_MODEL_VERSION
    assert companion["limitations"].count(SHARES_BEFORE_AVAILABILITY_LIMIT) == 1
    assert payload["stated_limits"].count(SHARES_BEFORE_AVAILABILITY_LIMIT) == (window > 1)
    assert backend.contexts.identity().inputs.snapshot_id == inputs.snapshot_id
    capture = backend.contexts.capture(backend.contexts.current())
    assert capture.switches.football_bundle_sha256 == sealed.fingerprint
    assert client.get(route, params=body).content == served.content
    assert client.get(route, params={**body, "model": "current"}).status_code == 404


def reseal(document, companion):
    document["fingerprint"] = forecast_digest(document)
    companion["flag_metadata"] = copy.deepcopy(document["flag_metadata"])
    companion["forecast_fingerprint"] = document["fingerprint"]
    companion["fingerprint"] = forecast_digest(companion)


def test_a_rehashed_joint_law_with_changed_role_marginals_still_refuses(live_case):
    _, _, _, original, original_companion, _, _, _ = live_case
    document, companion = copy.deepcopy(original), copy.deepcopy(original_companion)
    law = next(row for row in document["flag_metadata"]["weekly_laws"] if row["player_code"] == 3)
    delta = law["probabilities"][24] / 2
    law["probabilities"][24] -= delta
    law["probabilities"][10] += delta
    reseal(document, companion)
    with pytest.raises(ValueError, match="marginals"):
        loaded(live_case, document=document, companion=companion)


@pytest.mark.parametrize(
    "field,legacy",
    [
        ("contract_version", "football_first_week_flags_v1"),
        ("feature_version", "causal_categorical_flag_minutes_features_v1"),
    ],
)
def test_rehashed_legacy_flag_metadata_is_refused(live_case, field, legacy):
    _, _, _, original, original_companion, _, _, _ = live_case
    document, companion = copy.deepcopy(original), copy.deepcopy(original_companion)
    document["flag_metadata"][field] = legacy
    reseal(document, companion)
    with pytest.raises(ValueError, match="exact scope and metadata"):
        loaded(live_case, document=document, companion=companion)


def test_legacy_flag_model_is_refused_even_with_current_metadata(live_case):
    _, _, _, original, original_companion, _, _, _ = live_case
    document, companion = copy.deepcopy(original), copy.deepcopy(original_companion)
    document["model_version"] = companion["model_version"] = "football_joint_role_retained_flags_v1"
    reseal(document, companion)
    with pytest.raises(ValueError, match="unsupported model_version"):
        loaded(live_case, document=document, companion=companion)


@pytest.mark.parametrize(
    "field,value",
    [
        ("gameweek", 7),
        ("fit_cutoff", "2026-09-22T12:00:00Z"),
        ("fit_cutoff", "2026-09-22T11:00:01Z"),
        ("fit_cutoff", "NaT"),
        ("fit_cutoff", "2026-09-22T10:30:00"),
        ("fit_cutoff", None),
        ("later_weeks", "reuse_next_event_label"),
        ("training_seasons", ["2025-26"]),
        ("training_gameweeks", [6]),
        ("native_training_seasons", ["2025-26", "2026-27"]),
        ("weekly_laws", [None] * 66),
        ("head_version", "unfitted"),
    ],
)
def test_rehashed_metadata_cannot_hide_wrong_clocks_target_labels_or_protected_training(
    live_case, field, value
):
    _, _, _, original, original_companion, _, _, _ = live_case
    document, companion = copy.deepcopy(original), copy.deepcopy(original_companion)
    document["flag_metadata"][field] = value
    reseal(document, companion)
    with pytest.raises(ValueError):
        loaded(live_case, document=document, companion=companion)
