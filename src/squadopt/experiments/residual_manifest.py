"""Binding one shadow calibration to one exact model's residual export.

Phase 2A's pre-registration says a shadow calibration is conditional on the model it
wraps: it must name one ``oos_residual_export_v1`` export by label, model identity and
``table_sha256``, and calibrating one model's spread on another's residuals is refused
(the #45 rule that ``live/risk.py``'s ``MODEL_MISMATCH`` already enforces at decision
time). This module is that binding, made explicit and testable *before* any measurement
consumes an export.

It deliberately does not re-validate what ``squadopt.preflight`` already validates —
column order, manifest field presence, table/manifest agreement, position vocabulary.
It calls that preflight and refuses on any failed finding, then adds the four things a
shadow calibration needs on top of a preflighted artifact:

* **The bytes on disk are the bytes the manifest describes** — the digest is recomputed
  from the file, never trusted from the document.
* **The model the caller asked for is the model the export describes** — an exact
  (name, version, feature contract) match, so an export cannot be silently substituted.
* **The locked holdout is absent**, declared rather than assumed, and time ordering is
  real: the fit cutoff precedes every evaluated fold.
* **The serialization contract is stated** — the decimal rounding the digest depends
  on, so a cross-platform digest difference reads as a contract fact rather than a
  mystery.

The result serializes to deterministic LF JSON: the same export produces the same
bytes on every platform, and it converts to Phase 2A's ``ShadowResidualSource`` rather
than restating those fields in a second schema.
"""

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import pandas as pd

from squadopt.experiments.shadow_report import (
    LOCKED_HOLDOUT_SEASON,
    ShadowResidualSource,
)
from squadopt.preflight import (
    RESIDUAL_EXPORT_COLUMNS,
    RESIDUAL_EXPORT_CONTRACT_VERSION,
    run_residual_export_preflight,
)

RESIDUAL_SOURCE_MANIFEST_CONTRACT_VERSION: Final = "residual_source_manifest_v1"

#: The rounding the recorded digest depends on. ``docs/export_precision.md`` measured
#: nine decimals as the point where a cross-machine BLAS last-bit difference stops
#: changing the bytes; an export written without it is byte-stable only on the machine
#: that produced it, and this contract records which of the two it is holding.
DECLARED_PREDICTED_POINTS_DECIMALS: Final = 9

#: Missing is never zero. A residual row must carry a proven projection and a proven
#: outcome; a row missing either is refused, never imputed and never filled with 0.
MISSING_DATA_POLICY: Final = "refuse_row_never_impute"

_FOLD_ID = re.compile(r"^(\d{4}-\d{2})-gw(\d{2})$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class ResidualSourceError(ValueError):
    """Raised when an export cannot be bound as a shadow calibration's source."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ResidualSourceError(message)


def _fold_sort_key(fold_id: str) -> tuple[str, int]:
    match = _FOLD_ID.fullmatch(fold_id)
    _require(
        match is not None,
        f"fold_id {fold_id!r} does not match the contract's '<season>-gwNN' shape.",
    )
    assert match is not None  # narrowed by the check above
    return match.group(1), int(match.group(2))


@dataclass(frozen=True, slots=True)
class ResidualSourceManifest:
    """One exact model's residual export, bound and pinned for a shadow calibration."""

    contract_version: str
    export_contract_version: str
    export_label: str
    model_name: str
    model_version: str
    feature_contract_version: str
    training_contract_version: str
    evaluation_objective: str
    source_seasons: tuple[str, ...]
    decision_gameweek_min: int
    decision_gameweek_max: int
    first_fold_id: str
    last_fold_id: str
    fold_count: int
    row_count: int
    opening_gameweeks_included: bool
    missing_data_policy: str
    walk_forward_provenance: str
    generation_commit: str
    dataset_snapshot_id: str
    table_sha256: str
    predicted_points_decimals: int
    locked_holdout_excluded: bool
    created_at_utc: str | None

    def to_shadow_source(self, *, cutoff_fold_id: str) -> ShadowResidualSource:
        """The Phase 2A source record this export supports, with its fit cutoff.

        ``cutoff_fold_id`` is the last fold a fit may see. It must belong to this
        export and leave at least one later fold to evaluate, so a "walk-forward"
        split that secretly consumes everything cannot be declared.
        """

        cutoff = _fold_sort_key(cutoff_fold_id)
        first, last = _fold_sort_key(self.first_fold_id), _fold_sort_key(self.last_fold_id)
        _require(
            first <= cutoff,
            f"cutoff {cutoff_fold_id!r} precedes the export's first fold {self.first_fold_id!r}.",
        )
        _require(
            cutoff < last,
            f"cutoff {cutoff_fold_id!r} leaves no fold after it to evaluate "
            f"(the export ends at {self.last_fold_id!r}); a split must hold something out.",
        )
        return ShadowResidualSource(
            export_label=self.export_label,
            model_name=self.model_name,
            model_version=self.model_version,
            feature_contract_version=self.feature_contract_version,
            table_sha256=self.table_sha256,
            seasons=self.source_seasons,
            cutoff_fold_id=cutoff_fold_id,
        )


def manifest_to_dict(manifest: ResidualSourceManifest) -> dict[str, object]:
    """The manifest as one JSON-ready mapping; unknown values stay ``None``."""

    return {
        "contract_version": manifest.contract_version,
        "export_contract_version": manifest.export_contract_version,
        "export_label": manifest.export_label,
        "model_name": manifest.model_name,
        "model_version": manifest.model_version,
        "feature_contract_version": manifest.feature_contract_version,
        "training_contract_version": manifest.training_contract_version,
        "evaluation_objective": manifest.evaluation_objective,
        "source_seasons": list(manifest.source_seasons),
        "decision_gameweek_min": manifest.decision_gameweek_min,
        "decision_gameweek_max": manifest.decision_gameweek_max,
        "first_fold_id": manifest.first_fold_id,
        "last_fold_id": manifest.last_fold_id,
        "fold_count": manifest.fold_count,
        "row_count": manifest.row_count,
        "opening_gameweeks_included": manifest.opening_gameweeks_included,
        "missing_data_policy": manifest.missing_data_policy,
        "walk_forward_provenance": manifest.walk_forward_provenance,
        "generation_commit": manifest.generation_commit,
        "dataset_snapshot_id": manifest.dataset_snapshot_id,
        "table_sha256": manifest.table_sha256,
        "predicted_points_decimals": manifest.predicted_points_decimals,
        "locked_holdout_excluded": manifest.locked_holdout_excluded,
        "created_at_utc": manifest.created_at_utc,
    }


def write_residual_source_manifest(manifest: ResidualSourceManifest, path: Path) -> None:
    """Write the bound manifest as stable LF JSON — same input, same bytes."""

    payload = json.dumps(manifest_to_dict(manifest), indent=2, sort_keys=True, allow_nan=False)
    resolved = path.resolve()
    _require(
        "web/public" not in resolved.as_posix(),
        f"{resolved} sits inside a published site tree; a residual source manifest is "
        "an internal record and may never be written under web/public.",
    )
    resolved.parent.mkdir(parents=True, exist_ok=True)
    with resolved.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(payload + "\n")


def _check_table_health(table: pd.DataFrame) -> None:
    """The row-level facts a calibration would otherwise inherit silently."""

    _require(not table.empty, "The residual table is empty.")
    duplicated = int(table.duplicated(subset=["fold_id", "player_id"]).sum())
    _require(
        duplicated == 0,
        f"{duplicated} rows repeat a (fold_id, player_id) pair; the contract is one row each.",
    )
    for column in ("predicted_points", "realized_points", "residual"):
        values = pd.to_numeric(table[column], errors="coerce")
        missing = int(values.isna().sum())
        _require(
            missing == 0,
            f"{missing} rows carry a missing or non-numeric {column}; a missing value is "
            f"refused ({MISSING_DATA_POLICY}), never read as zero.",
        )
        non_finite = int((~values.map(math.isfinite)).sum())
        _require(
            non_finite == 0,
            f"{non_finite} rows carry a non-finite {column} (NaN or infinity); a shadow "
            "calibration cannot describe a spread built on one.",
        )
    residual_error = (
        table["residual"] - (table["realized_points"] - table["predicted_points"])
    ).abs()
    _require(
        float(residual_error.max()) <= 1e-9,
        "residual must equal realized minus predicted on the bytes a reader sees.",
    )


def load_residual_source_manifest(
    table_path: Path,
    manifest_path: Path,
    *,
    expect_model_name: str,
    expect_model_version: str,
    expect_feature_contract_version: str | None = None,
    forbidden_seasons: Sequence[str] = (LOCKED_HOLDOUT_SEASON,),
) -> ResidualSourceManifest:
    """Bind one export to one exact model, or refuse and say which check failed.

    The caller states the model it intends to calibrate. That statement is the point:
    an export whose identity differs is refused rather than adapted, so a shadow
    calibration cannot quietly describe the spread of a model that is not deciding.
    """

    _require(table_path.is_file(), f"Residual table not found at {table_path}.")
    _require(manifest_path.is_file(), f"Residual manifest not found at {manifest_path}.")

    raw = manifest_path.read_text(encoding="utf-8")
    try:
        document = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ResidualSourceError(f"{manifest_path} is not readable JSON: {error}") from error
    _require(isinstance(document, Mapping), f"{manifest_path} must hold a JSON object.")

    digest = hashlib.sha256(table_path.read_bytes()).hexdigest()
    recorded = str(document.get("table_sha256", ""))
    _require(
        _SHA256.fullmatch(recorded) is not None,
        f"table_sha256 {recorded!r} is not a 64-hex-character SHA-256.",
    )
    _require(
        digest == recorded,
        f"{table_path.name} hashes to {digest} but its manifest records {recorded}; the "
        "export changed after it was described, so nothing may be calibrated on it.",
    )

    table = pd.read_csv(table_path)
    report = run_residual_export_preflight(
        table, document, table_sha256=digest, artifact_label=str(table_path.name)
    )
    failed = [finding for finding in report.findings if not finding.passed]
    _require(
        not failed,
        "The export fails its own preflight and may not be bound: "
        + "; ".join(f"{finding.check}: {finding.detail}" for finding in failed[:5]),
    )

    columns = tuple(str(column) for column in table.columns)
    _require(
        columns == RESIDUAL_EXPORT_COLUMNS,
        f"Column order {columns} is not the contract's {RESIDUAL_EXPORT_COLUMNS}.",
    )
    _check_table_health(table)

    model_name = str(document["model_name"])
    model_version = str(document["model_version"])
    feature_contract = str(document["feature_contract_version"])
    _require(
        model_name == expect_model_name and model_version == expect_model_version,
        f"This export describes {model_name}/{model_version}, but the caller asked to "
        f"calibrate {expect_model_name}/{expect_model_version}. One model's residuals "
        "may not describe another's spread.",
    )
    if expect_feature_contract_version is not None:
        _require(
            feature_contract == expect_feature_contract_version,
            f"This export was built under feature contract {feature_contract!r}, not the "
            f"requested {expect_feature_contract_version!r}.",
        )

    seasons = tuple(sorted({str(season) for season in table["season"]}))
    present = [season for season in forbidden_seasons if season in seasons]
    _require(
        not present,
        f"Seasons {present!r} are forbidden for this calibration and are present in the "
        "export; the locked holdout may not be read, in an input or anywhere else.",
    )
    declared = tuple(sorted(str(season) for season in document["development_seasons"]))
    _require(
        declared == seasons,
        f"The manifest declares seasons {declared} but the table carries {seasons}.",
    )

    fold_ids = sorted({str(fold) for fold in table["fold_id"]}, key=_fold_sort_key)
    gameweeks = pd.to_numeric(table["gameweek"], errors="raise").astype(int)
    opening_present = bool((gameweeks <= 1).any())
    _require(
        opening_present == bool(document["opening_gameweeks_included"]),
        f"The manifest says opening_gameweeks_included="
        f"{bool(document['opening_gameweeks_included'])} but the table "
        f"{'carries' if opening_present else 'carries no'} opening gameweek.",
    )

    commit = str(document.get("repository_commit", ""))
    _require(
        bool(commit),
        "repository_commit is empty; an export with no generation provenance cannot be "
        "bound as evidence for anything.",
    )

    decimals_value = document.get("predicted_points_decimals")
    _require(
        decimals_value is not None,
        "predicted_points_decimals is missing; a byte-addressed residual export must "
        f"declare the measured {DECLARED_PREDICTED_POINTS_DECIMALS}-decimal rule.",
    )
    try:
        decimals = int(str(decimals_value))
    except ValueError as error:
        raise ResidualSourceError(
            "predicted_points_decimals must be an integer declaration."
        ) from error
    _require(
        decimals == DECLARED_PREDICTED_POINTS_DECIMALS,
        f"predicted_points_decimals is {decimals}, not the measured "
        f"{DECLARED_PREDICTED_POINTS_DECIMALS} the byte rule fixes.",
    )

    created = document.get("created_at_utc")
    return ResidualSourceManifest(
        contract_version=RESIDUAL_SOURCE_MANIFEST_CONTRACT_VERSION,
        export_contract_version=RESIDUAL_EXPORT_CONTRACT_VERSION,
        export_label=str(document["candidate_label"]),
        model_name=model_name,
        model_version=model_version,
        feature_contract_version=feature_contract,
        training_contract_version=str(document["training_contract_version"]),
        evaluation_objective=str(document["evaluation_objective"]),
        source_seasons=seasons,
        decision_gameweek_min=int(gameweeks.min()),
        decision_gameweek_max=int(gameweeks.max()),
        first_fold_id=fold_ids[0],
        last_fold_id=fold_ids[-1],
        fold_count=len(fold_ids),
        row_count=len(table),
        opening_gameweeks_included=opening_present,
        missing_data_policy=MISSING_DATA_POLICY,
        # Stated, not inferred: the export's own decision points are walk-forward by
        # construction (outcomes read only after each decision), and the preflight above
        # is what checks the table honours it.
        walk_forward_provenance="oos_walk_forward_decision_points_v1",
        generation_commit=commit,
        dataset_snapshot_id=str(document["dataset_snapshot_id"]),
        table_sha256=digest,
        predicted_points_decimals=decimals,
        locked_holdout_excluded=True,
        created_at_utc=None if created is None else str(created),
    )
