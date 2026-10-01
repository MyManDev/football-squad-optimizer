"""Validate and publish immutable capture-bound football documents without fitting a model."""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from squadopt.data.atomic import write_bytes_once
from squadopt.data.snapshots import CapturedSnapshot
from squadopt.live import RecommendationInputs
from squadopt.live.football_artifact import football_artifact_path, read_football_forecast
from squadopt.platform.football_minute_basis import _basis_from_snapshot, football_components_path


def _existing_agrees(path: Path, document: dict[str, Any]) -> None:
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return
    if json.loads(raw) != document:
        raise ValueError(f"A different football document already exists at {path.name}.")


def publish_football_artifacts(
    *,
    artifact_root: Path,
    snapshot: CapturedSnapshot,
    inputs: RecommendationInputs,
    document: dict[str, Any],
    companion: dict[str, Any] | None = None,
) -> tuple[Path, Path | None]:
    """Publish the forecast and, optionally, its verified v1 fixture companion.

    Existing documents are compared before either new public file is created. A
    per-capture marker serializes cooperating publishers; a concurrent invocation
    refuses rather than waiting or replacing a file. A process killed while holding
    the marker requires an operator to inspect it before removing it.

    Each document uses the shared atomic create-once writer. The companion is written
    first, so an interruption can leave a valid orphan companion that the next identical
    invocation completes. This is not an atomic transaction across two files. Neither
    an interrupted nor a competing writer may overwrite an existing document.
    """
    target = football_artifact_path(artifact_root, inputs.snapshot_id)
    component_target = (
        football_components_path(artifact_root, inputs.snapshot_id)
        if companion is not None
        else None
    )
    records = [(target, document)]
    if component_target is not None and companion is not None:
        records.append((component_target, companion))
    # Preserve the existing command's JSON representation and document fingerprints.
    payloads = {
        path: json.dumps(doc, sort_keys=True, allow_nan=False).encode() for path, doc in records
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    marker = target.with_name(f".{target.stem}.publication.lock")
    handle = marker.open("xb")
    try:
        with handle:
            for path, doc in records:
                _existing_agrees(path, doc)
            with TemporaryDirectory(prefix=".football-", dir=target.parent) as staging:
                staged = Path(staging) / target.name
                staged.write_bytes(payloads[target])
                football = read_football_forecast(staged, inputs)
                if companion is not None:
                    _basis_from_snapshot(document, companion, snapshot, inputs, football)
                elif (
                    document.get("source_fingerprint") != snapshot.metadata.fingerprint
                    or inputs.snapshot_id != snapshot.metadata.snapshot_id
                    or inputs.captured_at_utc != snapshot.metadata.captured_at_utc
                ):
                    raise ValueError("Football forecast does not identify its source capture.")
            # Complete the optional basis before making a new forecast visible. The
            # atomic writer checks again if a noncooperating writer wins the race.
            for path, _doc in reversed(records):
                write_bytes_once(payloads[path], path, parse=json.loads)
    finally:
        marker.unlink()
    return target, component_target
