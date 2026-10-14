"""Build the unserved prospective v1 arm and its create-once receipt before the deadline."""

import argparse
import hashlib
import json
import platform
import subprocess
import time
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any

from squadopt.application.football_live import produce_football_forecast
from squadopt.data.atomic import write_document_once
from squadopt.data.snapshots import list_snapshot_ids, read_snapshot
from squadopt.data.sources.fpl_live import BOOTSTRAP_PAYLOAD, FPL_LIVE_SOURCE
from squadopt.data.timestamps import as_instant
from squadopt.live import RecommendationInputs, infer_season, read_inputs
from squadopt.live.football_artifact import football_artifact_path, read_football_forecast
from squadopt.platform.football_publication import publish_football_artifacts
from squadopt.prediction.football import FOOTBALL_MODEL_VERSION

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SHADOW_ROOT = Path("artifacts/shadow/football_team_share_v1")
RECEIPT_CONTRACT = "football_shadow_receipt_v1"
# Every v1 receipt carries these keys, including the GW6 receipt written before #1069.
RECEIPT_KEYS = frozenset(
    {
        "contract_version",
        "snapshot_id",
        "captured_at_utc",
        "season",
        "gameweek",
        "deadline_utc",
        "model_version",
        "fingerprint",
        "artifact_sha256",
        "artifact_write_utc",
        "written_before_deadline",
        "repository_commit",
        "repository_tree_clean",
        "wall_seconds",
        "archive_hashes",
        "gameweek_captures",
        "newest_for_gameweek",
        "served",
    }
)
# Additive v1 keys, written from the merge of #1069 together with the stricter newest rule.
RECEIPT_ADDITIVE_KEYS = frozenset(
    {"skipped_captures", "ambiguous_latest", "python_version", "library_versions"}
)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _check_root(shadow_root: Path) -> Path:
    root = shadow_root.resolve()
    artifacts = REPOSITORY_ROOT / "artifacts"
    forbidden = {artifacts.resolve()}
    selection = artifacts / "backend-artifact-root.json"
    if selection.exists():
        document = json.loads(selection.read_text(encoding="utf-8-sig"))
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
            ["git", "--no-optional-locks", "-C", str(REPOSITORY_ROOT), *args], text=True
        ).strip()

    return git("rev-parse", "HEAD"), not git("status", "--porcelain")


def _gameweek_captures(
    snapshot_root: Path, inputs: RecommendationInputs
) -> tuple[list[dict[str, Any]], list[str]]:
    captures = []
    skipped = []
    for snapshot_id in list_snapshot_ids(snapshot_root, source=FPL_LIVE_SOURCE):
        snapshot = read_snapshot(snapshot_root, snapshot_id)
        if snapshot.metadata.source != FPL_LIVE_SOURCE:
            raise ValueError("The live inventory contains a capture from another source.")
        if BOOTSTRAP_PAYLOAD not in snapshot.payloads:
            skipped.append(snapshot_id)
            continue
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
    return (
        sorted(captures, key=lambda row: (as_instant(row["captured_at_utc"]), row["snapshot_id"])),
        sorted(skipped),
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
    captures, skipped = _gameweek_captures(snapshot_root, inputs)
    latest = max(as_instant(row["captured_at_utc"]) for row in captures)
    ambiguous_latest = sum(as_instant(row["captured_at_utc"]) == latest for row in captures) > 1
    library_versions = {
        name: version(name) for name in ("numpy", "scipy", "scikit-learn", "pandas")
    }
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
        "python_version": platform.python_version(),
        "library_versions": library_versions,
        "wall_seconds": time.perf_counter() - started,
        "archive_hashes": document["archive_hashes"],
        "gameweek_captures": captures,
        "skipped_captures": skipped,
        "ambiguous_latest": ambiguous_latest,
        "newest_for_gameweek": (
            not ambiguous_latest and as_instant(inputs.captured_at_utc) == latest
        ),
        "served": False,
    }
    write_document_once(receipt, receipt_path)
    return receipt


def read_shadow_receipt(path: Path) -> dict[str, Any]:
    """Read a v1 receipt with none or all of the additive keys, as it was written.

    A receipt without ``ambiguous_latest`` was written under the earlier newest rule,
    so its ``newest_for_gameweek`` is returned as recorded and never recomputed.
    """
    document = json.loads(path.read_bytes())
    if not isinstance(document, dict) or document.get("contract_version") != RECEIPT_CONTRACT:
        raise ValueError("The file is not a football_shadow_receipt_v1 receipt.")
    if set(document) not in (set(RECEIPT_KEYS), set(RECEIPT_KEYS | RECEIPT_ADDITIVE_KEYS)):
        raise ValueError("A v1 shadow receipt carries none or all of the additive keys.")
    return document


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
