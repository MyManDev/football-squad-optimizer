"""Readiness refuses wrong-week, late, missing and changed paired inputs."""

import json
import os
from pathlib import Path

import pytest
from scripts.check_football_prospective_inputs import audit
from tests.unit.test_football_prospective_prereg import _artifact
from tests.unit.test_live_recommendation import SEASON, _capture

from squadopt.data.timestamps import as_instant
from squadopt.live.football_artifact import football_artifact_path
from squadopt.live.recommendation import InSeasonProjection, read_inputs, write_projection_handoff
from squadopt.prediction.component_dataset import FEATURE_CONTRACT_VERSION
from squadopt.prediction.component_models import COMPONENT_MODEL_VERSION


def bundle(tmp_path: Path, captured: str = "2026-08-22T09:00:00Z") -> str:
    snapshot = _capture(tmp_path / "snapshots", captured_at=captured)
    inputs = read_inputs(snapshot, season=SEASON, gameweek=None)
    identifier = inputs.snapshot_id
    path = football_artifact_path(tmp_path / "artifacts", identifier)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_artifact(inputs)))
    timestamp = as_instant(captured).timestamp() + 60
    os.utime(path, (timestamp, timestamp))
    handoff = InSeasonProjection(
        SEASON,
        inputs.deadline.gameweek,
        identifier,
        "control",
        COMPONENT_MODEL_VERSION,
        FEATURE_CONTRACT_VERSION,
        {int(p): 3.0 for p in inputs.players.player_id},
    )
    retained = tmp_path / "handoffs" / "by-capture" / identifier / "forecast.json"
    retained.parent.mkdir(parents=True, exist_ok=True)
    write_projection_handoff(retained, handoff)
    return identifier


def check(tmp_path: Path, ids: list[str], week: int = 2) -> dict:
    return audit(
        tmp_path / "snapshots",
        tmp_path / "handoffs",
        tmp_path / "artifacts",
        snapshot_ids=ids,
        season=SEASON,
        gameweeks=[week],
        as_of="2026-08-29T00:00:00Z",
    )


def test_real_readers_pair_forecasts_without_outcomes(tmp_path: Path) -> None:
    identifier = bundle(tmp_path)
    result = check(tmp_path, [identifier])
    assert result["outcomes_read"] is False
    row = result["weeks"][0]
    assert row["status"] == "inputs_ready"
    assert row["paired_players"] == 24
    assert row["capture_selection_final"] is True
    assert row["own_target"] == 2


def test_previous_target_is_never_borrowed(tmp_path: Path) -> None:
    identifier = bundle(tmp_path, "2026-08-13T20:11:43Z")
    assert check(tmp_path, [identifier])["weeks"][0]["reason"] == "no_own_target_capture"


@pytest.mark.parametrize("failure", ["missing", "late", "corrupt", "current"])
def test_latest_unusable_capture_never_falls_back(tmp_path: Path, failure: str) -> None:
    older = bundle(tmp_path)
    latest = bundle(tmp_path, "2026-08-23T09:00:00Z")
    path = football_artifact_path(tmp_path / "artifacts", latest)
    if failure == "missing":
        path.unlink()
    elif failure == "late":
        timestamp = as_instant("2026-08-28T17:30:00Z").timestamp()
        os.utime(path, (timestamp, timestamp))
    elif failure == "corrupt":
        path.write_text("{}")
    else:
        (tmp_path / "handoffs" / "by-capture" / latest / "forecast.json").write_text("{}")
    row = check(tmp_path, [latest, older])["weeks"][0]
    assert row["snapshot_id"] == latest
    assert row["status"] == "missing"


def test_future_capture_and_duplicate_inventory_are_refused(tmp_path: Path) -> None:
    identifier = bundle(tmp_path)
    with pytest.raises(ValueError, match="unique"):
        check(tmp_path, [identifier, identifier])
    with pytest.raises(ValueError, match="later"):
        audit(
            tmp_path / "snapshots",
            tmp_path / "handoffs",
            tmp_path / "artifacts",
            snapshot_ids=[identifier],
            season=SEASON,
            gameweeks=[2],
            as_of="2026-08-21T00:00:00Z",
        )


def test_before_deadline_ready_is_only_provisional(tmp_path: Path) -> None:
    identifier = bundle(tmp_path)
    result = audit(
        tmp_path / "snapshots",
        tmp_path / "handoffs",
        tmp_path / "artifacts",
        snapshot_ids=[identifier],
        season=SEASON,
        gameweeks=[2],
        as_of="2026-08-24T00:00:00Z",
    )
    assert result["weeks"][0]["status"] == "inputs_ready"
    assert result["weeks"][0]["capture_selection_final"] is False


def test_naive_audit_instant_is_rejected_before_any_capture_read(tmp_path: Path) -> None:
    from squadopt.data.errors import DataSourceError

    with pytest.raises(DataSourceError, match="timezone"):
        audit(
            tmp_path,
            tmp_path,
            tmp_path,
            snapshot_ids=["unused"],
            season=SEASON,
            gameweeks=[2],
            as_of="2026-08-24T00:00:00",
        )
