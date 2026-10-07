"""Build the unserved prospective v1 arm and its create-once receipt before the deadline."""

import argparse
import hashlib
import json
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from squadopt.application.football_live import produce_football_forecast
from squadopt.data.atomic import write_document_once
from squadopt.data.snapshots import list_snapshot_ids, read_snapshot
from squadopt.data.sources.fpl_live import FPL_LIVE_SOURCE
from squadopt.data.timestamps import as_instant
from squadopt.live import RecommendationInputs, infer_season, read_inputs
from squadopt.live.football_artifact import football_artifact_path, read_football_forecast
from squadopt.platform.football_publication import publish_football_artifacts
from squadopt.prediction.football import FOOTBALL_MODEL_VERSION

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SHADOW_ROOT = Path("artifacts/shadow/football_team_share_v1")
RECEIPT_CONTRACT = "football_shadow_receipt_v1"


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _check_root(shadow_root: Path) -> Path:
    root = shadow_root.resolve()
    artifacts = REPOSITORY_ROOT / "artifacts"
    forbidden = {artifacts.resolve()}
    selection = artifacts / "backend-artifact-root.json"
    if selection.exists():
        document = json.loads(selection.read_text(encoding="utf-8"))
        if (
            not isinstance(document, dict)
            or set(document) != {"artifact_root"}
            or not isinstance(document["artifact_root"], str)
            or not document["artifact_root"].strip()
        ):
            raise ValueError("Invalid backend artifact root selection; cannot isolate the shadow.")
        selected = Path(document["artifact_root"])
        forbidden.add((REPOSITORY_ROOT / selected).resolve())
    if root in forbidden:
        raise ValueError("The shadow root must not be a backend artifact root.")
    return root


def _repository_state() -> tuple[str, bool]:
    def git(*args: str) -> str:
        return subprocess.check_output(
            ["git", "-C", str(REPOSITORY_ROOT), *args], text=True
        ).strip()

    return git("rev-parse", "HEAD"), not git("status", "--porcelain")


def _gameweek_captures(snapshot_root: Path, inputs: RecommendationInputs) -> list[dict[str, Any]]:
    captures = []
    for snapshot_id in list_snapshot_ids(snapshot_root, source=FPL_LIVE_SOURCE):
        snapshot = read_snapshot(snapshot_root, snapshot_id)
        if snapshot.metadata.source != FPL_LIVE_SOURCE:
            raise ValueError("The live inventory contains a capture from another source.")
        season = infer_season(snapshot)
        if season != inputs.season:
            continue
        own_inputs = read_inputs(snapshot, season=season)
        if own_inputs.deadline.gameweek == inputs.deadline.gameweek:
            captures.append(
                {"snapshot_id": snapshot_id, "captured_at_utc": snapshot.metadata.captured_at_utc}
            )
    if inputs.snapshot_id not in {row["snapshot_id"] for row in captures}:
        raise ValueError("The decision capture is absent from the live inventory.")
    return sorted(
        captures, key=lambda row: (as_instant(row["captured_at_utc"]), row["snapshot_id"])
    )


def build_shadow(
    *,
    snapshot_root: Path,
    snapshot_id: str,
    archive_root: Path,
    shadow_root: Path = DEFAULT_SHADOW_ROOT,
) -> dict[str, Any]:
    started = time.perf_counter()
    run_instant = _utc_now()
    root = _check_root(shadow_root)
    artifact = football_artifact_path(root, snapshot_id)
    receipt_path = root / "receipts" / artifact.name
    if receipt_path.exists():
        raise ValueError("A shadow receipt already exists for this capture.")
    snapshot = read_snapshot(snapshot_root, snapshot_id)
    if snapshot.metadata.source != FPL_LIVE_SOURCE:
        raise ValueError("The shadow command requires an fpl-live capture.")
    inputs = read_inputs(snapshot, season=infer_season(snapshot))
    deadline = as_instant(inputs.deadline.deadline_utc)
    if run_instant >= deadline:
        raise ValueError("The capture's own deadline has closed; a shadow cannot be backfilled.")
    commit, clean = _repository_state()
    document = produce_football_forecast(
        snapshot,
        archive_root,
        contextual=False,
        manager_words=None,
        training_seasons=None,
    )
    if document.get("model_version") != FOOTBALL_MODEL_VERSION:
        raise ValueError("The shadow producer must return football_team_share_v1.")
    captures = _gameweek_captures(snapshot_root, inputs)
    if _utc_now() >= deadline:
        raise ValueError("The deadline closed during fitting; no shadow will be published.")
    publish_football_artifacts(
        artifact_root=root,
        snapshot=snapshot,
        inputs=inputs,
        document=document,
        companion=None,
    )
    forecast = read_football_forecast(artifact, inputs)
    if forecast.horizon.model_version != FOOTBALL_MODEL_VERSION:
        raise ValueError("The shadow reader must return football_team_share_v1.")
    raw = artifact.read_bytes()
    written = datetime.fromtimestamp(artifact.stat().st_mtime, UTC)
    receipt = {
        "contract_version": RECEIPT_CONTRACT,
        "snapshot_id": snapshot_id,
        "captured_at_utc": inputs.captured_at_utc,
        "season": inputs.season,
        "gameweek": inputs.deadline.gameweek,
        "deadline_utc": inputs.deadline.deadline_utc,
        "model_version": forecast.horizon.model_version,
        "fingerprint": forecast.fingerprint,
        "artifact_sha256": hashlib.sha256(raw).hexdigest(),
        "artifact_write_utc": written.isoformat().replace("+00:00", "Z"),
        "written_before_deadline": written < deadline,
        "repository_commit": commit,
        "repository_tree_clean": clean,
        "wall_seconds": time.perf_counter() - started,
        "archive_hashes": document["archive_hashes"],
        "gameweek_captures": captures,
        "newest_for_gameweek": captures[-1]["snapshot_id"] == snapshot_id,
        "served": False,
    }
    write_document_once(receipt, receipt_path)
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-root", type=Path, required=True)
    parser.add_argument("--snapshot-id", required=True)
    parser.add_argument("--archive-root", type=Path, required=True)
    parser.add_argument("--shadow-root", type=Path, default=DEFAULT_SHADOW_ROOT)
    args = parser.parse_args()
    print(json.dumps(build_shadow(**vars(args)), indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
