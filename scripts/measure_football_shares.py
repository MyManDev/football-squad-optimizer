"""Size one exact retained-history forecast; read no target-week outcomes."""

import argparse
import hashlib
import json
from pathlib import Path

from scripts._provenance import REPOSITORY_ROOT, _git_revision, write_json

from squadopt.data.snapshots import (
    CapturedSnapshot,
    SnapshotMetadata,
    build_snapshot_id,
    read_snapshot,
    snapshot_fingerprint,
)
from squadopt.data.sources.fpl_live import BOOTSTRAP_PAYLOAD, FIXTURES_PAYLOAD
from squadopt.experiments.football_share_sizing import size_attacking_shares
from squadopt.live import read_inputs
from squadopt.live.football_artifact import football_artifact_path, read_football_forecast
from squadopt.platform.football_minute_basis import _basis_from_snapshot


def _forecast_source(root: Path, identifier: str) -> CapturedSnapshot:
    """Verify metadata and only the two required source payloads, not live results."""
    directory = root / identifier
    metadata = SnapshotMetadata(**json.loads((directory / "metadata.json").read_text("utf-8")))
    fingerprint = snapshot_fingerprint(
        source=metadata.source,
        captured_at_utc=metadata.captured_at_utc,
        schema_version=metadata.schema_version,
        checksums=metadata.checksums,
    )
    if (
        metadata.fingerprint != fingerprint
        or identifier
        != build_snapshot_id(
            source=metadata.source,
            captured_at_utc=metadata.captured_at_utc,
            fingerprint=fingerprint,
        )
        or metadata.snapshot_id != identifier
    ):
        raise ValueError("Source metadata identity differs.")
    payloads = {}
    for name in (BOOTSTRAP_PAYLOAD, FIXTURES_PAYLOAD):
        content = (directory / "payloads" / name).read_bytes()
        if hashlib.sha256(content).hexdigest() != metadata.checksums[name]:
            raise ValueError("Sizing source payload checksum differs.")
        payloads[name] = content
    return CapturedSnapshot(metadata=metadata, payloads=payloads)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-root", type=Path, required=True)
    parser.add_argument("--snapshot-id", required=True)
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--archive-root", type=Path)
    parser.add_argument("--evidence-root", type=Path, required=True)
    args = parser.parse_args()
    evidence_root = args.evidence_root.resolve()
    own_artifacts = (REPOSITORY_ROOT / "artifacts").resolve()
    if not evidence_root.is_relative_to(own_artifacts):
        parser.error("Evidence must be under this worktree's artifacts directory.")
    path = football_artifact_path(args.artifact_root, args.snapshot_id)
    if path.resolve().is_relative_to(evidence_root) or evidence_root.is_relative_to(
        args.artifact_root.resolve()
    ):
        parser.error("Input artifacts and sizing evidence must have separate roots.")
    served_bytes = path.read_bytes()
    served = json.loads(served_bytes)
    if served["model_version"] != "football_joint_role_retained_history_v1":
        parser.error("Sizing requires the served retained-history base.")
    if served["season"] != "2026-27":
        parser.error("Only the declared live season is supported.")
    source = _forecast_source(args.snapshot_root, args.snapshot_id)
    inputs = read_inputs(source, season=served["season"])
    companion_path = path.with_suffix(".components.json")
    rebuilt = not companion_path.exists()
    if rebuilt:
        if args.archive_root is None:
            parser.error("A missing companion requires --archive-root for the served build.")
        from squadopt.application.football_live import produce_football_components

        # Only this explicit fallback fits historical training data. It never scores outcomes.
        selection = served["training_selection"]["allowed_seasons"]
        if "2025-26" in selection:
            parser.error("The locked 2025-26 holdout cannot be a rebuild input.")
        rebuilt_forecast, companion = produce_football_components(
            read_snapshot(args.snapshot_root, args.snapshot_id),
            args.archive_root,
            gameweeks=sorted({row["gameweek"] for row in served["rows"]}),
            training_seasons=selection,
            role_minutes=True,
            retained_role_history=True,
        )
        if rebuilt_forecast["fingerprint"] != served["fingerprint"]:
            raise ValueError("Rebuilt forecast differs from the served build.")
        companion_path = evidence_root / "rebuilt.components.json"
        write_json(companion_path, companion)
    companion_bytes = companion_path.read_bytes()
    companion = json.loads(companion_bytes)
    football = read_football_forecast(path, inputs)
    basis = _basis_from_snapshot(served, companion, source, inputs, football)
    record, frame = size_attacking_shares(basis)
    commit, dirty = _git_revision()
    record.update(
        companion_rebuilt=rebuilt,
        forecast_sha256=hashlib.sha256(served_bytes).hexdigest(),
        companion_sha256=hashlib.sha256(companion_bytes).hexdigest(),
        repository_commit=commit,
        working_tree_dirty=dirty,
        target_outcomes_read=False,
    )
    evidence_root.mkdir(parents=True, exist_ok=True)
    evidence_path = evidence_root / "player-fixtures.csv"
    frame.to_csv(evidence_path, index=False)
    record["evidence_sha256"] = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
    write_json(evidence_root / "summary.json", record)
    print(json.dumps(record, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
