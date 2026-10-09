"""Synthetic production provenance checks; no fit and no archive access."""

import json
from dataclasses import replace

import pytest
from tests.unit.test_football_bundle import case as case
from tests.unit.test_football_bundle import dump
from tests.unit.test_football_publication import publication_case as publication_case
from tests.unit.test_joint_role_minute_evidence import joint_documents
from tests.unit.test_minute_evidence import basis_from

from squadopt.live import read_projection_handoff, write_projection_handoff
from squadopt.live.football_artifact import forecast_digest
from squadopt.platform import football_bundle as bundle


@pytest.mark.parametrize(
    "field",
    [
        "model_version",
        "source_fingerprint",
        "training_rows",
        "training_latest_kickoff",
        "archive_hashes",
        "training_selection",
        "role_metadata",
    ],
)
def test_normal_seal_refuses_different_production_identity(case, field):
    path = bundle.football_components_path(case["artifact_root"], case["snapshot_id"])
    document = json.loads(path.read_bytes())
    document[field] = (
        {"different": True}
        if field in {"archive_hashes", "training_selection", "role_metadata"}
        else "different"
    )
    document["fingerprint"] = forecast_digest(document)
    dump(path, document)
    message = {
        "model_version": "fixture component contract",
        "training_selection": "training selection",
        "role_metadata": "role-minute metadata",
    }.get(field, "source, cutoff or training binding")
    with pytest.raises(ValueError, match=message):
        bundle.seal_football_bundle(**case)
    marker = bundle.football_bundle_path(case["artifact_root"], case["snapshot_id"])
    assert not marker.exists()
    assert not marker.with_suffix(".production.json").exists()


def test_normal_seal_records_each_models_own_training_provenance(case):
    handoff = read_projection_handoff(case["handoff_path"])
    archives = ["2021-22", "2022-23", "2023-24", "2024-25"]
    handoff = replace(
        handoff,
        diagnostics={
            "component_training_seasons": archives,
            "projection_selection": "not training",
        },
    )
    write_projection_handoff(case["handoff_path"], handoff)
    ready = bundle.seal_football_bundle(**case)
    path = ready.marker_path.with_suffix(".production.json")
    record = json.loads(path.read_bytes())
    assert record["current_handoff"]["training_provenance"] == {
        "component_training_seasons": archives
    }
    assert "archive_hashes" in record["football"]
    assert record["football"]["archive_hashes"] == {"test": "b" * 64}
    assert "component_training_seasons" not in record["football"]
    assert (
        bundle.read_football_bundle(
            artifact_root=case["artifact_root"],
            snapshot_root=case["snapshot_root"],
            snapshot_id=case["snapshot_id"],
        ).fingerprint
        == ready.fingerprint
    )


def test_joint_record_keeps_three_archive_seasons_and_causal_history_apart(case):
    # Already built synthetic fixture documents, not a call to any training producer.
    forecast, companion, calendar, clubs = joint_documents()
    selection = {
        "contract_version": "football_training_selection_v1",
        "allowed_seasons": ["2022-23", "2023-24", "2024-25", "2026-27"],
        "archive_seasons_read": ["2022-23", "2023-24", "2024-25"],
        "captured_history_included": True,
        "captured_history_season": "2026-27",
        "prior_only_seasons": ["2022-23"],
        "prior_policy": "first_selected_usable_season_prior_only",
        "history_rows_by_season": {"2022-23": 20, "2023-24": 40, "2024-25": 40, "2026-27": 5},
        "supervised_rows_by_season": {"2023-24": 40, "2024-25": 40, "2026-27": 5},
    }
    for document in (forecast, companion):
        document["training_selection"] = selection
    forecast["fingerprint"] = forecast_digest(forecast)
    companion["forecast_fingerprint"] = forecast["fingerprint"]
    companion["fingerprint"] = forecast_digest(companion)
    forecast_path = case["artifact_root"] / "joint-forecast.json"
    companion_path = case["artifact_root"] / "joint-components.json"
    dump(forecast_path, forecast)
    dump(companion_path, companion)
    handoff = replace(
        read_projection_handoff(case["handoff_path"]),
        source_snapshot_id=forecast["source_snapshot_id"],
        diagnostics={
            "component_training_seasons": ["2021-22", "2022-23", "2023-24", "2024-25"],
        },
    )
    write_projection_handoff(case["handoff_path"], handoff)
    record = bundle._production_record(
        {
            "forecast": forecast_path.read_bytes(),
            "components": companion_path.read_bytes(),
            "handoff": case["handoff_path"].read_bytes(),
        },
        forecast["source_snapshot_id"],
        handoff_fingerprint=handoff.fingerprint,
    )
    assert (
        basis_from((forecast, companion, calendar, clubs)).served["training_selection"] == selection
    )
    assert record["current_handoff"]["source_snapshot_id"] == forecast["source_snapshot_id"]
    assert record["football"]["model_version"] == "football_joint_role_minutes_v1"
    assert "training_selection" in record["football"]
    assert record["football"]["training_selection"] == selection
    assert record["football"]["training_latest_kickoff"] < forecast["captured_at_utc"]
    assert record["current_handoff"]["training_provenance"]["component_training_seasons"] == [
        "2021-22",
        "2022-23",
        "2023-24",
        "2024-25",
    ]


def test_preflight_refusal_leaves_no_production_record(case):
    marker = bundle.football_bundle_path(case["artifact_root"], case["snapshot_id"])
    target = marker.parent / (case["snapshot_id"] + ".bundle") / "handoff.json"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"stale copied bytes")
    with pytest.raises(ValueError, match="different immutable bundle artifact"):
        bundle.seal_football_bundle(**case)
    assert not marker.exists()
    assert not marker.with_suffix(".production.json").exists()
    target.write_bytes(case["handoff_path"].read_bytes())
    assert bundle.seal_football_bundle(**case).snapshot_id == case["snapshot_id"]


def test_record_uses_sealed_handoff_bytes_even_if_source_diagnostics_change(case, monkeypatch):
    original = bundle._production_record
    source = case["handoff_path"]

    def altered_source(payloads, snapshot_id, **kwargs):
        doc = json.loads(source.read_bytes())
        doc["diagnostics"]["component_training_seasons"] = ["1999-00"]
        dump(source, doc)
        return original(payloads, snapshot_id, **kwargs)

    monkeypatch.setattr(bundle, "_production_record", altered_source)
    ready = bundle.seal_football_bundle(**case)
    record = json.loads(ready.marker_path.with_suffix(".production.json").read_bytes())
    sealed = ready.files["handoff"].read_bytes()
    assert "component_training_seasons" not in json.loads(sealed)["diagnostics"]
    assert record["current_handoff"]["training_provenance"] == {}
    assert record["current_handoff"]["sha256"] == bundle._digest(sealed)
    marker_doc = json.loads(ready.marker_path.read_bytes())
    assert record["current_handoff"]["sha256"] == marker_doc["files"]["handoff"]["sha256"]


def test_production_record_refuses_different_capture_pair(case):
    files = {
        "forecast": bundle.football_artifact_path(case["artifact_root"], case["snapshot_id"]),
        "handoff": case["handoff_path"],
    }
    payloads = {role: path.read_bytes() for role, path in files.items()}
    handoff = json.loads(payloads["handoff"])
    handoff["source_snapshot_id"] = "other-capture"
    payloads["handoff"] = json.dumps(handoff).encode()
    with pytest.raises(ValueError, match="capture identities differ"):
        bundle._production_record(payloads, case["snapshot_id"], handoff_fingerprint="synthetic")
