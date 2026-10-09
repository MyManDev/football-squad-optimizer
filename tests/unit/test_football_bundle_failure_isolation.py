"""Failed new publication cannot select loose v1 inputs or damage a previous bundle."""

import json
from dataclasses import replace
from datetime import datetime, timedelta

import pytest
from pandas.testing import assert_frame_equal
from tests.unit.test_football_bundle import case as case
from tests.unit.test_football_bundle import dump
from tests.unit.test_football_bundle import publication_case as publication_case
from tests.unit.test_football_bundle_switches import baseline, load, signature

from squadopt.data.snapshots import read_snapshot, write_snapshot
from squadopt.live import read_inputs, read_projection_handoff, write_projection_handoff
from squadopt.live.football_artifact import football_artifact_path, forecast_digest
from squadopt.platform import football_bundle as bundle
from squadopt.platform.advice_switches import SwitchInputUnavailable, switch_identity
from squadopt.platform.football_minute_basis import football_components_path
from squadopt.platform.football_publication import publish_football_artifacts


def newer_case(case, tmp_path):
    prior = read_snapshot(case["snapshot_root"], case["snapshot_id"])
    at = (
        (
            datetime.fromisoformat(prior.metadata.captured_at_utc.replace("Z", "+00:00"))
            + timedelta(minutes=1)
        )
        .isoformat()
        .replace("+00:00", "Z")
    )
    metadata = write_snapshot(
        case["snapshot_root"], source="fpl-live", captured_at_utc=at, payloads=dict(prior.payloads)
    )
    snapshot = read_snapshot(case["snapshot_root"], metadata.snapshot_id)
    served = json.loads(
        football_artifact_path(case["artifact_root"], case["snapshot_id"]).read_bytes()
    )
    companion = json.loads(
        football_components_path(case["artifact_root"], case["snapshot_id"]).read_bytes()
    )
    for document in (served, companion):
        document.update(
            source_snapshot_id=metadata.snapshot_id,
            source_fingerprint=metadata.fingerprint,
            captured_at_utc=metadata.captured_at_utc,
        )
    served["fingerprint"] = forecast_digest(served)
    companion["forecast_fingerprint"] = served["fingerprint"]
    companion["fingerprint"] = forecast_digest(companion)
    publish_football_artifacts(
        artifact_root=case["artifact_root"],
        snapshot=snapshot,
        inputs=read_inputs(snapshot, season="2026-27"),
        document=served,
        companion=companion,
    )
    handoff = tmp_path / "new-handoff.json"
    write_projection_handoff(
        handoff,
        replace(
            read_projection_handoff(case["handoff_path"]), source_snapshot_id=metadata.snapshot_id
        ),
    )
    site = tmp_path / "new-site"
    for name in ("members.json", "entries/101.json", "entries/202.json"):
        document = json.loads((case["site_data_root"] / "league" / name).read_bytes())
        if name != "members.json":
            document["payload"]["source_snapshot_id"] = metadata.snapshot_id
        dump(site / "league" / name, document)
    return {
        **case,
        "snapshot_id": metadata.snapshot_id,
        "handoff_path": handoff,
        "site_data_root": site,
    }


@pytest.mark.parametrize("failure", ["preparation", "recording", "verification"])
def test_failure_keeps_previous_ready_and_never_selects_partial(
    case, tmp_path, monkeypatch, failure
):
    previous = bundle.seal_football_bundle(**case)
    previous_bytes = previous.marker_path.read_bytes()
    candidate = newer_case(case, tmp_path)
    inputs, projection = baseline(candidate)
    baseline_bytes = projection.table.copy(deep=True)
    # Legacy v1 artifacts remain compatible until this particular publication starts.
    assert load(candidate).football is not None
    prior_signature = signature(candidate)
    real_site = bundle._site_files
    real_write = bundle.write_bytes_once
    real_validate = bundle._validate

    def fail_site(tree):
        if tree == candidate["site_data_root"] / "league":
            raise OSError("synthetic preparation failure")
        return real_site(tree)

    def fail_record(raw, target):
        if target.name == "202.json" and any(part.endswith(".bundle") for part in target.parts):
            raise OSError("synthetic recording failure")
        return real_write(raw, target)

    def fail_verify(**kwargs):
        if (
            kwargs["snapshot_id"] == candidate["snapshot_id"]
            and ".bundle" in kwargs["files"]["handoff"].parent.name
        ):
            raise OSError("synthetic verification failure")
        return real_validate(**kwargs)

    monkeypatch.setattr(bundle, "_site_files", fail_site if failure == "preparation" else real_site)
    monkeypatch.setattr(
        bundle, "write_bytes_once", fail_record if failure == "recording" else real_write
    )
    monkeypatch.setattr(
        bundle, "_validate", fail_verify if failure == "verification" else real_validate
    )
    with pytest.raises(OSError, match=f"synthetic {failure} failure"):
        bundle.seal_football_bundle(**candidate)
    assert not bundle.football_bundle_path(
        candidate["artifact_root"], candidate["snapshot_id"]
    ).exists()
    if failure == "recording":
        folder = bundle.football_bundle_stage_path(
            candidate["artifact_root"], candidate["snapshot_id"], bundle.FootballBundleStage.FOLDER
        )
        assert (folder / "handoff.json").read_bytes() == candidate["handoff_path"].read_bytes()
        assert (folder / "site/league/members.json").is_file()
        assert (folder / "site/league/entries/101.json").is_file()
        assert not (folder / "site/league/entries/202.json").exists()
        # Isolate the real partial-folder guard from the attempt guard in this test.
        bundle.football_bundle_stage_path(
            candidate["artifact_root"], candidate["snapshot_id"], bundle.FootballBundleStage.STARTED
        ).unlink()
    assert signature(candidate) != prior_signature
    selected = load(candidate, inputs=inputs, projection=projection)
    assert selected.football is None and not selected.football_components_bound
    assert selected.football_bundle_sha256 is None
    assert any("bundle incomplete" in note for note in selected.notes)
    with pytest.raises(SwitchInputUnavailable):
        switch_identity(selected, model="football")
    assert switch_identity(selected, model="current") == {}
    assert_frame_equal(projection.table, baseline_bytes, check_exact=True)
    # Read and select the exact previous capture, including its served handoff.
    assert previous.marker_path.read_bytes() == previous_bytes
    held = bundle.read_football_bundle(
        **{key: case[key] for key in ("artifact_root", "snapshot_root", "snapshot_id")}
    )
    assert held.fingerprint == previous.fingerprint
    assert load(case).football_bundle_sha256 == previous.fingerprint
    monkeypatch.setattr(bundle, "_site_files", real_site)
    monkeypatch.setattr(bundle, "write_bytes_once", real_write)
    monkeypatch.setattr(bundle, "_validate", real_validate)
    completed = bundle.seal_football_bundle(**candidate)
    assert load(candidate).football_bundle_sha256 == completed.fingerprint


@pytest.mark.parametrize(
    "stage",
    [
        bundle.FootballBundleStage.PREPARATION,
        bundle.FootballBundleStage.PRODUCTION,
        bundle.FootballBundleStage.FOLDER,
    ],
)
def test_preexisting_partial_stage_evidence_cannot_use_legacy_fallback(case, stage):
    path = bundle.football_bundle_stage_path(case["artifact_root"], case["snapshot_id"], stage)
    if stage is bundle.FootballBundleStage.FOLDER:
        path.mkdir()
    else:
        path.write_text("{}", encoding="utf-8")
    selected = load(case)
    assert selected.football is None
    assert any("bundle incomplete" in note for note in selected.notes)


def test_unresolved_league_argument_does_not_disable_legacy_inputs(case):
    from squadopt.contracts.league_tree import (
        LeagueDirectoryError,
        PublishedLeague,
        write_league_directory,
    )

    write_league_directory(
        case["site_data_root"],
        [PublishedLeague(i, f"Synthetic {i}", "2026-27", 6, f"leagues/{i}") for i in (9, 10)],
        generated_at_utc="2026-10-08T00:00:00Z",
    )
    before = signature(case)
    assert load(case).football is not None
    with pytest.raises(LeagueDirectoryError, match="say which one"):
        bundle.seal_football_bundle(**case)
    assert signature(case) == before
    assert load(case).football is not None
    assert not any(
        path.exists()
        for path in bundle.football_bundle_stage_paths(case["artifact_root"], case["snapshot_id"])
    )
