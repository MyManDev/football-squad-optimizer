"""Validate planning evidence before attaching it to a public ledger view.

The season ledger remains the only authority for the live one-week decision.  A
multi-horizon batch may publish solver evidence, never alternative actions.  Before
that evidence crosses the public boundary, its H1 child must reproduce the frozen
ledger squad, XI, captain, and transfers.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Final

from squadopt.application.horizon_batch import HORIZON_BATCH_CONTRACT_VERSION
from squadopt.application.horizon_plans import HORIZON_PLAN_ARTIFACT_CONTRACT_VERSION
from squadopt.application.views import JsonValue
from squadopt.data.errors import DataError
from squadopt.live.ledger import load_entry

HORIZON_EVIDENCE_CONTRACT_VERSION: Final = "public_horizon_evidence_v1"


@dataclass(frozen=True, slots=True)
class PublicHorizonEvidence:
    """Sanitized batch facts verified against one immutable ledger decision."""

    season: str
    gameweek: int
    payload: Mapping[str, JsonValue]

    def __post_init__(self) -> None:
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))


def _document(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise DataError(f"Could not read horizon evidence {path}: {error}.") from error
    if not isinstance(value, dict):
        raise DataError(f"Horizon evidence {path} must contain a JSON object.")
    return {str(key): item for key, item in value.items()}


def _verified_fingerprint(document: Mapping[str, object], field: str, *, path: Path) -> str:
    claimed = document.get(field)
    if not isinstance(claimed, str) or len(claimed) != 64:
        raise DataError(f"Horizon evidence {path} has no valid {field}.")
    content = {key: value for key, value in document.items() if key != field}
    encoded = json.dumps(content, sort_keys=True, separators=(",", ":")).encode("utf-8")
    actual = hashlib.sha256(encoded).hexdigest()
    if actual != claimed:
        raise DataError(f"Horizon evidence {path} does not match its {field}.")
    return claimed


def _integer(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise DataError(f"Horizon evidence {name} must be an integer.")
    return value


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DataError(f"Horizon evidence {name} must be non-empty text.")
    return value


def _player_ids(value: object, name: str) -> tuple[int, ...]:
    if not isinstance(value, list):
        raise DataError(f"Horizon evidence {name} must be a list.")
    identifiers: list[int] = []
    for item in value:
        raw_identifier = item.get("player_id") if isinstance(item, Mapping) else item
        identifiers.append(_integer(raw_identifier, f"{name}.player_id"))
    return tuple(identifiers)


def _artifact_root(manifest_path: Path, season: str, gameweek: int) -> Path:
    expected_parent = Path(season) / f"gw{gameweek:02d}" / "batches"
    resolved = manifest_path.resolve()
    try:
        relative_parent = Path(*resolved.parts[-4:-1])
    except IndexError as error:  # pragma: no cover - defensive for exotic paths
        raise DataError(f"Horizon manifest path {manifest_path} is too short.") from error
    if relative_parent != expected_parent:
        raise DataError(
            f"Horizon manifest {manifest_path} is not under {expected_parent.as_posix()}."
        )
    return resolved.parents[3]


def _child_path(root: Path, relative: object) -> Path:
    text = _text(relative, "artifact_path")
    child = (root / Path(text)).resolve()
    if not child.is_relative_to(root):
        raise DataError("Horizon artifact_path escapes its artifact root.")
    return child


def _verify_h1_against_ledger(
    child: Mapping[str, object], *, ledger_root: Path, season: str, gameweek: int
) -> None:
    entry = load_entry(ledger_root, season, gameweek)
    decision = entry.decision
    if child.get("source_snapshot_id") != decision.get("snapshot_id"):
        raise DataError("H1 horizon snapshot does not match the frozen ledger decision.")
    for field in ("model_name", "model_version", "feature_contract_version"):
        if child.get(field) != decision.get(field):
            raise DataError(f"H1 horizon {field} does not match the frozen ledger decision.")
    weeks = child.get("weeks")
    if not isinstance(weeks, list) or len(weeks) != 1 or not isinstance(weeks[0], Mapping):
        raise DataError("H1 horizon artifact must contain exactly one week object.")
    week = weeks[0]
    comparisons = (
        (
            set(_player_ids(week.get("squad"), "weeks.squad")),
            set(_player_ids(decision.get("squad_player_ids"), "decision.squad_player_ids")),
            "squad",
        ),
        (
            set(_player_ids(week.get("starting_xi"), "weeks.starting_xi")),
            set(
                _player_ids(
                    decision.get("starting_xi_player_ids"), "decision.starting_xi_player_ids"
                )
            ),
            "starting XI",
        ),
        (
            _player_ids(week.get("bench"), "weeks.bench"),
            _player_ids(decision.get("bench_player_ids"), "decision.bench_player_ids"),
            "bench order",
        ),
    )
    for actual, expected, label in comparisons:
        if actual != expected:
            raise DataError(f"H1 horizon {label} does not match the frozen ledger decision.")
    if _integer(week.get("captain_player_id"), "captain_player_id") != _integer(
        decision.get("captain_player_id"), "decision.captain_player_id"
    ):
        raise DataError("H1 horizon captain does not match the frozen ledger decision.")
    transfers = decision.get("transfers")
    ledger_transfers = transfers if isinstance(transfers, Mapping) else {}
    for field in ("transfers_in", "transfers_out"):
        if set(_player_ids(week.get(field), f"weeks.{field}")) != set(
            _player_ids(ledger_transfers.get(field, []), f"decision.{field}")
        ):
            raise DataError(f"H1 horizon {field} does not match the frozen ledger decision.")
    expected_score = float(str(decision.get("projected_score")))
    actual_score = float(str(week.get("projected_score")))
    if not math.isclose(actual_score, expected_score, rel_tol=0.0, abs_tol=1e-9):
        raise DataError("H1 horizon score does not match the frozen ledger decision.")


def load_public_horizon_evidence(
    manifest_path: Path, *, ledger_root: Path
) -> PublicHorizonEvidence:
    """Return sanitized batch evidence only after its H1 reproduces the ledger."""

    path = Path(manifest_path)
    manifest = _document(path)
    if manifest.get("contract_version") != HORIZON_BATCH_CONTRACT_VERSION:
        raise DataError("Horizon manifest uses an unsupported contract version.")
    fingerprint = _verified_fingerprint(manifest, "batch_fingerprint", path=path)
    season = _text(manifest.get("season"), "season")
    gameweek = _integer(manifest.get("first_gameweek"), "first_gameweek")
    snapshot_id = _text(manifest.get("source_snapshot_id"), "source_snapshot_id")
    if manifest.get("public_advice_policy") != "only_the_one_week_control_is_decision_eligible":
        raise DataError("Horizon manifest has an unsupported public advice policy.")
    root = _artifact_root(path, season, gameweek)
    rows = manifest.get("horizons")
    if not isinstance(rows, list) or not rows:
        raise DataError("Horizon manifest must contain horizon rows.")

    public_rows: list[JsonValue] = []
    seen: set[int] = set()
    h1_child: dict[str, object] | None = None
    for raw_row in rows:
        if not isinstance(raw_row, Mapping):
            raise DataError("Every horizon manifest row must be an object.")
        row = {str(key): value for key, value in raw_row.items()}
        horizon = _integer(row.get("horizon"), "horizon")
        if horizon in seen or horizon not in {1, 3, 5}:
            raise DataError("Horizon manifest rows must be unique H1, H3, or H5 records.")
        seen.add(horizon)
        child_path = _child_path(root, row.get("artifact_path"))
        child = _document(child_path)
        if child.get("contract_version") != HORIZON_PLAN_ARTIFACT_CONTRACT_VERSION:
            raise DataError(f"H{horizon} artifact uses an unsupported contract version.")
        child_fingerprint = _verified_fingerprint(child, "artifact_fingerprint", path=child_path)
        if child_fingerprint != row.get("artifact_fingerprint"):
            raise DataError(f"H{horizon} artifact fingerprint disagrees with the manifest.")
        if child.get("season") != season or child.get("source_snapshot_id") != snapshot_id:
            raise DataError(f"H{horizon} artifact lineage disagrees with the manifest.")
        for field in ("projection_handoff_fingerprint", "initial_state_fingerprint"):
            if child.get(field) != manifest.get(field):
                raise DataError(f"H{horizon} artifact {field} disagrees with the manifest.")
        targets = child.get("target_gameweeks")
        if not isinstance(targets, list) or targets != list(range(gameweek, gameweek + horizon)):
            raise DataError(f"H{horizon} artifact has unexpected target gameweeks.")
        expected_role = "live_control" if horizon == 1 else "research_shadow"
        expected_publication = "decision_eligible" if horizon == 1 else "shadow_only"
        if row.get("decision_role") != expected_role:
            raise DataError(f"H{horizon} has an invalid decision role.")
        if row.get("publication_status") != expected_publication:
            raise DataError(f"H{horizon} has an invalid publication status.")
        public_fields = (
            "decision_role",
            "solver_status",
            "solver_proof_status",
            "publication_status",
        )
        for field in public_fields:
            if child.get(field) != row.get(field):
                raise DataError(f"H{horizon} artifact {field} disagrees with the manifest.")
        if horizon == 1:
            if row.get("solver_status") != "OPTIMAL" or row.get("solver_proof_status") != "proven":
                raise DataError("H1 evidence must be an OPTIMAL, proven control replay.")
            h1_child = child
        gap = row.get("relative_optimality_gap")
        public_gap: float | None = None
        if gap is not None:
            public_gap = float(str(gap))
            if not math.isfinite(public_gap) or public_gap < 0.0:
                raise DataError(
                    f"H{horizon} relative optimality gap must be finite and non-negative."
                )
        public_rows.append(
            {
                "horizon": horizon,
                "decision_role": expected_role,
                "solver_status": _text(row.get("solver_status"), "solver_status"),
                "solver_proof_status": _text(row.get("solver_proof_status"), "solver_proof_status"),
                "publication_status": expected_publication,
                "relative_optimality_gap": public_gap,
                "artifact_fingerprint": child_fingerprint,
            }
        )
    if h1_child is None:
        raise DataError("Horizon evidence must include the H1 live-control replay.")
    _verify_h1_against_ledger(
        h1_child, ledger_root=Path(ledger_root), season=season, gameweek=gameweek
    )
    payload: dict[str, JsonValue] = {
        "contract_version": HORIZON_EVIDENCE_CONTRACT_VERSION,
        "batch_fingerprint": fingerprint,
        "source_snapshot_id": snapshot_id,
        "ledger_control_verified": True,
        "horizons": public_rows,
        "stated_limit": (
            "H3 and H5 are solver evidence from frozen projections, not live advice or "
            "forecast-calibration evidence."
        ),
    }
    return PublicHorizonEvidence(season=season, gameweek=gameweek, payload=payload)
