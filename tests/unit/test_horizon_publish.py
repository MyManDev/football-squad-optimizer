"""Public horizon evidence keeps the immutable H1 ledger as decision authority."""

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from tests.unit.test_horizon_application import _world

from squadopt.application import (
    DecideRequest,
    HorizonBatchRequest,
    build_site,
    decide,
    load_public_horizon_evidence,
    plan_horizon_batch,
)
from squadopt.data.errors import DataError


def _fingerprint(document: dict[str, object], field: str) -> str:
    content = {key: value for key, value in document.items() if key != field}
    encoded = json.dumps(content, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _published_world(tmp_path: Path) -> tuple[dict[str, Any], Path]:
    world = _world(tmp_path)
    decide(
        DecideRequest(
            snapshot_root=world["snapshot_root"],
            snapshot_id=world["gw2_id"],
            ledger_root=world["ledger_root"],
            archive_root=tmp_path / "archive",
            in_season_projection=world["handoff"],
            mode="replay",
        )
    )
    result = plan_horizon_batch(
        HorizonBatchRequest(
            snapshot_root=world["snapshot_root"],
            snapshot_id=world["gw2_id"],
            ledger_root=world["ledger_root"],
            artifact_root=tmp_path / "artifacts" / "live",
            in_season_projection=world["handoff"],
            horizons=(1, 3, 5),
            shadow_horizons=frozenset({3, 5}),
        )
    )
    return world, result.manifest_path


def test_verified_batch_adds_solver_evidence_without_replacing_the_ledger(
    tmp_path: Path,
) -> None:
    world, manifest_path = _published_world(tmp_path)

    evidence = load_public_horizon_evidence(manifest_path, ledger_root=world["ledger_root"])
    report = build_site(
        ledger_root=world["ledger_root"],
        season="2026-27",
        out_dir=tmp_path / "site",
        horizon_manifest=manifest_path,
    )

    assert evidence.gameweek == 2
    assert evidence.payload["ledger_control_verified"] is True
    public_text = json.dumps(dict(evidence.payload), ensure_ascii=False).lower()
    assert "%" not in public_text
    assert "probabilit" not in public_text
    assert "olas\u0131l\u0131k" not in public_text
    rows = evidence.payload["horizons"]
    assert isinstance(rows, list)
    assert [row["horizon"] for row in rows if isinstance(row, dict)] == [1, 3, 5]
    assert report.horizon_evidence_gameweek == 2
    recommendation = json.loads(
        (tmp_path / "site" / "data" / "2026-27" / "gw02" / "recommendation.json").read_text(
            encoding="utf-8"
        )
    )["payload"]
    assert recommendation["metadata"]["horizon_evidence"] == dict(evidence.payload)
    assert recommendation["transfers"] is not None


def test_an_internally_consistent_but_different_h1_is_refused(tmp_path: Path) -> None:
    world, manifest_path = _published_world(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    h1 = next(row for row in manifest["horizons"] if row["horizon"] == 1)
    artifact_root = manifest_path.resolve().parents[3]
    child_path = artifact_root / h1["artifact_path"]
    child = json.loads(child_path.read_text(encoding="utf-8"))
    child["weeks"][0]["captain_player_id"] = child["weeks"][0]["bench"][0]["player_id"]
    child["artifact_fingerprint"] = _fingerprint(child, "artifact_fingerprint")
    child_path.write_text(json.dumps(child, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    h1["artifact_fingerprint"] = child["artifact_fingerprint"]
    manifest["batch_fingerprint"] = _fingerprint(manifest, "batch_fingerprint")
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    with pytest.raises(DataError, match="captain does not match"):
        load_public_horizon_evidence(manifest_path, ledger_root=world["ledger_root"])
