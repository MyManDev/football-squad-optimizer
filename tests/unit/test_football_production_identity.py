"""Synthetic production provenance checks; no fit and no archive access."""

import json
from dataclasses import replace

import pytest
from tests.unit.test_football_bundle import case as case
from tests.unit.test_football_bundle import dump
from tests.unit.test_football_publication import publication_case as publication_case
from tests.unit.test_joint_role_minute_evidence import joint_documents

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
    with pytest.raises(ValueError, match=f"production identity differs for {field}"):
        bundle.seal_football_bundle(**case)
    marker = bundle.football_bundle_path(case["artifact_root"], case["snapshot_id"])
    assert not marker.exists()
    assert not marker.with_suffix(".production.json").exists()


def test_normal_seal_records_each_models_own_training_provenance(case):
    handoff = read_projection_handoff(case["handoff_path"])
    archives = ["2021-22", "2022-23", "2023-24", "2024-25"]
    handoff = replace(handoff, diagnostics={"component_training_seasons": archives})
    write_projection_handoff(case["handoff_path"], handoff)
    ready = bundle.seal_football_bundle(**case)
    path = ready.marker_path.with_suffix(".production.json")
    record = json.loads(path.read_bytes())
    assert record["current_handoff"]["training_provenance"] == {
        "component_training_seasons": archives
    }
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
    forecast, companion, _, _ = joint_documents()
    selection = {
        "allowed_seasons": ["2022-23", "2023-24", "2024-25", "2026-27"],
        "archive_seasons_read": ["2022-23", "2023-24", "2024-25"],
        "captured_history_included": True,
        "captured_history_season": "2026-27",
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
        diagnostics={
            "component_training_seasons": ["2021-22", "2022-23", "2023-24", "2024-25"],
        },
    )
    write_projection_handoff(case["handoff_path"], handoff)
    record = bundle._production_record(
        {
            "forecast": forecast_path,
            "components": companion_path,
            "handoff": case["handoff_path"],
        },
        forecast["source_snapshot_id"],
    )
    assert record["football"]["model_version"] == "football_joint_role_minutes_v1"
    assert record["football"]["training_selection"] == selection
    assert record["football"]["training_latest_kickoff"] < forecast["captured_at_utc"]
    assert record["current_handoff"]["training_provenance"]["component_training_seasons"] == [
        "2021-22",
        "2022-23",
        "2023-24",
        "2024-25",
    ]
