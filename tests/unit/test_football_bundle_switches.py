"""Ready bundles control optional football inputs without changing the current baseline."""

import hashlib
import json
from dataclasses import replace

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal
from tests.unit.test_football_bundle import add_quiet_news, dump, marker
from tests.unit.test_football_bundle import case as case
from tests.unit.test_football_publication import publication_case as publication_case
from tests.unit.test_joint_role_minute_evidence import joint_documents

from squadopt.data.snapshots import METADATA_FILENAME, PAYLOAD_DIRECTORY, read_snapshot
from squadopt.live import Projection, read_inputs, read_projection_handoff
from squadopt.live.football_artifact import football_artifact_path, forecast_digest
from squadopt.platform import advice_switches as switches
from squadopt.platform.advice_cache import advice_cache_key
from squadopt.platform.football_bundle import seal_football_bundle
from squadopt.platform.football_minute_basis import football_components_path
from squadopt.prediction.football import (
    FOOTBALL_MODEL_VERSION,
    JOINT_ROLE_MODEL_VERSION,
    JOINT_ROLE_MODEL_VERSIONS,
)
from squadopt.prediction.football_components import COMPONENT_COLUMNS
from squadopt.prediction.football_minutes_role import ROLE_COMPONENT_COLUMNS, ROLE_METADATA_COLUMNS


def baseline(case):
    capture = read_snapshot(case["snapshot_root"], case["snapshot_id"])
    inputs = read_inputs(capture, season="2026-27")
    frame = inputs.players.copy().assign(expected_points=2.0, appearance_probability=0.5)
    return inputs, Projection(
        frame,
        (),
        {
            "model_version": "synthetic-current",
            "projection_handoff_fingerprint": read_projection_handoff(
                case["handoff_path"]
            ).fingerprint,
        },
    )


def load(case, *, configured=None, inputs=None, projection=None):
    if inputs is None:
        inputs, projection = baseline(case)
    return switches.load_switch_inputs(
        artifact_root=case["artifact_root"],
        club_news_source=configured,
        snapshot_root=case["snapshot_root"],
        inputs=inputs,
        projection=projection,
    )


def signature(case, configured=None):
    return switches.discovery_signature(
        artifact_root=case["artifact_root"],
        club_news_source=configured,
        season="2026-27",
        gameweek=6,
        capture_snapshot_id=case["snapshot_id"],
        snapshot_root=case["snapshot_root"],
    )


def cache_key(case, identity):
    return advice_cache_key(
        advice_contract_version="entry_advice_v1",
        capture_snapshot_id=case["snapshot_id"],
        season="2026-27",
        gameweek=6,
        league_id=1,
        entry_id=101,
        strategy="saf-puan",
        window=3,
        projection_handoff_fingerprint="a" * 64,
        repository_commit="b" * 40,
        configuration_fingerprint="c" * 64,
        switches=identity,
    )


def make_joint_pair(case, *, version=JOINT_ROLE_MODEL_VERSION):
    """Replace only this synthetic fixture pair with a valid joint-law pair before sealing."""
    forecast_path = football_artifact_path(case["artifact_root"], case["snapshot_id"])
    components_path = football_components_path(case["artifact_root"], case["snapshot_id"])
    served = json.loads(forecast_path.read_bytes())
    companion = json.loads(components_path.read_bytes())
    _, template, _, _ = joint_documents(dgw=True)
    examples = {row["player_code"]: row for row in template["rows"]}
    for row in companion["rows"]:
        example = examples[row["player_code"]]
        row.update(
            {
                key: example[key]
                for key in (*COMPONENT_COLUMNS, *ROLE_COMPONENT_COLUMNS, *ROLE_METADATA_COLUMNS)
            }
        )
    totals = pd.DataFrame(companion["rows"]).groupby(["GW", "player_code"]).expected_points.sum()
    for row in served["rows"]:
        row["expected_points"] = float(totals.loc[row["gameweek"], row["player_id"]])
    for document in (served, companion):
        document["model_version"] = version
        document["role_metadata"] = dict(template["role_metadata"])
        if version != JOINT_ROLE_MODEL_VERSION:
            document["role_metadata"]["role_feature_version"] = (
                "retained_player_history_indicator_v1"
            )
    served["fingerprint"] = forecast_digest(served)
    companion["forecast_fingerprint"] = served["fingerprint"]
    companion["fingerprint"] = forecast_digest(companion)
    dump(forecast_path, served)
    dump(components_path, companion)


def test_old_v1_without_marker_remains_available_and_leaves_current_baseline_exact(case):
    inputs, projection = baseline(case)
    saved = projection.table.copy(deep=True)
    selected = load(case, inputs=inputs, projection=projection)
    assert selected.football is not None
    assert selected.football.horizon.model_version == FOOTBALL_MODEL_VERSION
    assert selected.football_components_bound
    assert selected.football_bundle_sha256 is None and not marker(case).exists()
    assert switches.switch_identity(selected, model="current") == {}
    assert_frame_equal(projection.table, saved, check_exact=True)


@pytest.mark.parametrize("version", JOINT_ROLE_MODEL_VERSIONS)
def test_new_joint_pair_cannot_be_served_until_real_ready_marker_is_complete(case, version):
    make_joint_pair(case, version=version)
    before = signature(case)
    waiting = load(case)
    assert waiting.football is None and not waiting.football_components_bound
    assert any("requires a complete ready bundle" in note for note in waiting.notes)
    with pytest.raises(switches.SwitchInputUnavailable):
        switches.switch_identity(waiting, model="football")
    assert switches.switch_identity(waiting, model="current") == {}
    ready = seal_football_bundle(**case)
    assert signature(case) != before
    active = load(case)
    assert active.football is not None and active.football_components_bound
    assert active.football.horizon.model_version == version
    assert active.football_bundle_sha256 == ready.fingerprint
    assert active.football.projection.diagnostics["fixture_role_estimates"]


@pytest.mark.parametrize("changed_handoff", [False, True])
def test_ready_bundle_must_bind_the_handoff_actually_served(case, tmp_path, changed_handoff):
    add_quiet_news(case, tmp_path)
    ready = seal_football_bundle(**case)
    inputs, projection = baseline(case)
    diagnostics = dict(projection.diagnostics)
    assert diagnostics.pop("projection_handoff_fingerprint") == ready.handoff_fingerprint
    if changed_handoff:
        # A legal newly issued handoff for the same capture is not the sealed one.
        held = read_projection_handoff(case["handoff_path"])
        points = dict(held.expected_points)
        first = next(iter(points))
        points[first] += 0.5
        other = replace(held, expected_points=points)
        assert other.source_snapshot_id == case["snapshot_id"]
        diagnostics["projection_handoff_fingerprint"] = other.fingerprint
    changed = replace(projection, diagnostics=diagnostics)
    saved = changed.table.copy(deep=True)
    selected = load(case, inputs=inputs, projection=changed)
    assert selected.football is None and not selected.football_components_bound
    assert selected.football_bundle_sha256 is None and selected.manager_words is None
    assert any("differs from the served baseline handoff" in note for note in selected.notes)
    assert switches.switch_identity(selected, model="current") == {}
    with pytest.raises(switches.SwitchInputUnavailable):
        switches.switch_identity(selected, model="football")
    assert_frame_equal(changed.table, saved, check_exact=True)


def test_sealed_news_and_copied_rotation_override_stale_config_and_later_unsealed_edits(
    case, tmp_path, monkeypatch
):
    add_quiet_news(case, tmp_path)
    ready = seal_football_bundle(**case)
    # The current mutable export path is no longer the selected source after sealing.
    case["rotation_table_path"].write_text("broken unsealed table", encoding="utf-8")
    monkeypatch.setattr(
        switches,
        "_rotation_candidates",
        lambda *a, **k: pytest.fail("A ready bundle must select its exact sealed pair."),
    )
    selected = load(case, configured=tmp_path / "unrelated-stale-source.json")
    assert selected.football is not None and selected.football_components_bound
    assert selected.manager_words is not None
    assert selected.manager_words.source_label == case["news_capture_id"]
    assert selected.manager_words.clubs_covered == ("Club 1",)
    assert selected.manager_words.words == ()  # Source coverage is not an applied statement.
    sealed_manifest = json.loads(ready.files["rotation_manifest"].read_bytes())
    assert selected.rotation_table_sha256 == sealed_manifest["table_sha256"]
    assert selected.football_bundle_sha256 == ready.fingerprint
    outcomes = selected.football.projection.diagnostics["participation_evidence"][
        "statement_outcomes"
    ]
    assert outcomes == []


def test_ready_bundle_without_news_does_not_pull_in_unrelated_configured_source(
    case, tmp_path, monkeypatch
):
    seal_football_bundle(**case)
    monkeypatch.setattr(
        switches,
        "club_news_capture_id",
        lambda *a, **k: pytest.fail("Unsealed configured news must not enter the decision."),
    )
    selected = load(case, configured=tmp_path / "stale-news.json")
    assert selected.football is not None
    assert selected.manager_words is None and selected.rotation_table_sha256 is None
    info = selected.decision_information(case["snapshot_id"])
    assert info["minute_components_bound"] and not info["coach_news_bound"]


@pytest.mark.parametrize(
    "damage", ["malformed_marker", "marker_identity", "copied_site", "components"]
)
def test_present_invalid_marker_never_falls_back_to_partial_v1_inputs(case, damage):
    ready = seal_football_bundle(**case)
    inputs, projection = baseline(case)
    before = projection.table.copy(deep=True)
    if damage == "malformed_marker":
        marker(case).write_bytes(b"{broken")
    elif damage == "marker_identity":
        value = json.loads(marker(case).read_bytes())
        value["snapshot_id"] = "wrong-capture"
        dump(marker(case), value)
    elif damage == "copied_site":
        ready.files["site_entry_101"].write_bytes(b"changed copied site")
    else:
        ready.files["components"].write_bytes(b"changed component pair")
    selected = load(case, inputs=inputs, projection=projection)
    assert selected.football is None and not selected.football_components_bound
    assert selected.football_bundle_sha256 is None
    assert selected.manager_words is None and selected.rotation_table_sha256 is None
    assert any("no partial football inputs" in note for note in selected.notes)
    with pytest.raises(switches.SwitchInputUnavailable):
        switches.switch_identity(selected, model="football")
    assert switches.switch_identity(selected, model="current") == {}
    assert_frame_equal(projection.table, before, check_exact=True)


def test_marker_digest_changes_football_identity_and_revision_but_not_current_identity(case):
    legacy = load(case)
    legacy_identity = switches.switch_identity(legacy, model="football")
    legacy_revision = legacy.decision_information(case["snapshot_id"])["revision"]
    ready = seal_football_bundle(**case)
    selected = load(case)
    identity = switches.switch_identity(selected, model="football")
    assert selected.football.fingerprint == legacy.football.fingerprint
    assert selected.football_components_sha256 == legacy.football_components_sha256
    assert identity != legacy_identity
    assert cache_key(case, identity) != cache_key(case, legacy_identity)
    assert identity["model"]["ready_bundle_sha256"] == ready.fingerprint
    assert ready.fingerprint == hashlib.sha256(marker(case).read_bytes()).hexdigest()
    assert selected.decision_information(case["snapshot_id"])["revision"] != legacy_revision
    assert (
        switches.switch_identity(selected, model="current")
        == switches.switch_identity(legacy, model="current")
        == {}
    )
    assert cache_key(case, switches.switch_identity(selected, model="current")) == cache_key(
        case, switches.switch_identity(legacy, model="current")
    )
    # Even equal forecast bytes cannot reuse a different marker's decision identity.
    changed = replace(selected, football_bundle_sha256="f" * 64)
    assert switches.switch_identity(changed, model="football") != identity
    assert (
        changed.decision_information(case["snapshot_id"])["revision"]
        != selected.decision_information(case["snapshot_id"])["revision"]
    )


@pytest.mark.parametrize("source_part", ["metadata", "payload"])
def test_sealed_news_source_changes_invalidate_discovery_even_with_stale_config(
    case, tmp_path, source_part
):
    add_quiet_news(case, tmp_path)
    seal_football_bundle(**case)
    stale = tmp_path / "stale-configured-source.json"
    before = signature(case, stale)
    source = case["snapshot_root"] / case["news_capture_id"]
    path = (
        source / METADATA_FILENAME
        if source_part == "metadata"
        else next((source / PAYLOAD_DIRECTORY).iterdir())
    )
    if source_part == "metadata":
        document = json.loads(path.read_bytes())
        document["fingerprint"] = "f" * 64
        dump(path, document)
    else:
        path.write_bytes(path.read_bytes() + b" ")
    assert signature(case, stale) != before
    assert load(case, configured=stale).football is None
