"""The internal shadow calibration report — versioned, never member-facing.

Phase 2's shadow measurements need one artifact shape whose honesty is structural
rather than editorial. This contract (``shadow_calibration_report_v1``) is that
shape, and it is deliberately unreachable from the published site: nothing under
``ui_view_v1`` references it, the writer refuses any destination inside a
``web/public`` tree, and serialization refuses NaN so an unmeasured number can
never ride out looking measured. Missing and zero stay distinct throughout —
an absent diagnostic is ``None`` (serialized ``null``), never ``0``.

The three terminal statuses mirror ``docs/phase2_shadow_calibration_prereg.md``:
``calibrated_internal`` (every gate passed; unlocks nothing member-facing),
``failed`` (a recorded negative; thresholds do not move), and ``abstained``
(insufficient sample or unprovable inputs — distinct from failure, and it must
say why).
"""

import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

SHADOW_CALIBRATION_CONTRACT_VERSION = "shadow_calibration_report_v1"
LOCKED_HOLDOUT_SEASON = "2025-26"
SHADOW_STATUSES: tuple[str, ...] = ("calibrated_internal", "failed", "abstained")

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_FOLD_ID = re.compile(r"^\d{4}-\d{2}-gw\d{2}$")


class ShadowReportError(ValueError):
    """Raised when a shadow report violates its own contract."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ShadowReportError(message)


def _finite_or_none(label: str, values: Mapping[str, float | None]) -> None:
    for key, value in values.items():
        if value is None:
            continue
        _require(
            isinstance(value, float) and math.isfinite(value),
            f"{label}[{key!r}] must be a finite float or None (missing), got {value!r}; "
            "an unmeasured number must stay None, never NaN and never zero.",
        )


@dataclass(frozen=True, slots=True)
class ShadowResidualSource:
    """The one residual export a shadow calibration wraps, named and pinned."""

    export_label: str
    model_name: str
    model_version: str
    feature_contract_version: str
    table_sha256: str
    seasons: tuple[str, ...]
    cutoff_fold_id: str

    def __post_init__(self) -> None:
        for name in ("export_label", "model_name", "model_version", "feature_contract_version"):
            _require(bool(getattr(self, name)), f"{name} must be non-empty.")
        _require(
            _SHA256.fullmatch(self.table_sha256) is not None,
            "table_sha256 must be a 64-hex-character SHA-256; a shadow calibration "
            "without a committed manifest fingerprint may not run.",
        )
        _require(bool(self.seasons), "At least one residual season is required.")
        _require(
            LOCKED_HOLDOUT_SEASON not in self.seasons,
            f"{LOCKED_HOLDOUT_SEASON} is the locked holdout and may not appear in a "
            "shadow calibration's residual provenance.",
        )
        _require(
            _FOLD_ID.fullmatch(self.cutoff_fold_id) is not None,
            "cutoff_fold_id must name the last fold visible to the fit, e.g. '2023-24-gw38'.",
        )


@dataclass(frozen=True, slots=True)
class ShadowGateResult:
    """One pre-registered gate, exactly as measured."""

    gate: str
    passes: bool
    observed: float | None
    threshold: str

    def __post_init__(self) -> None:
        _require(bool(self.gate), "gate must be non-empty.")
        _require(bool(self.threshold), "threshold must state the pre-registered bound.")
        if self.observed is not None:
            _require(
                math.isfinite(self.observed),
                f"gate {self.gate!r}: observed must be finite or None (not evaluable).",
            )
        if self.observed is None:
            _require(
                not self.passes,
                f"gate {self.gate!r}: a gate with no observed value cannot pass.",
            )


@dataclass(frozen=True, slots=True)
class ShadowExecutionMetadata:
    """The reproducibility facts for one concrete shadow execution."""

    started_at_utc: str
    completed_at_utc: str
    elapsed_seconds: float
    deterministic_seed: int
    warnings: tuple[str, ...]

    def __post_init__(self) -> None:
        def instant(label: str, value: str) -> datetime:
            try:
                parsed = datetime.fromisoformat(value)
            except ValueError as error:
                raise ShadowReportError(f"{label} must be an ISO-8601 timestamp.") from error
            _require(
                parsed.tzinfo is not None and parsed.utcoffset() == UTC.utcoffset(parsed),
                f"{label} must describe a UTC instant.",
            )
            return parsed

        started = instant("started_at_utc", self.started_at_utc)
        completed = instant("completed_at_utc", self.completed_at_utc)
        _require(completed >= started, "completed_at_utc cannot precede started_at_utc.")
        _require(
            isinstance(self.elapsed_seconds, float)
            and math.isfinite(self.elapsed_seconds)
            and self.elapsed_seconds >= 0.0,
            "elapsed_seconds must be a finite non-negative float.",
        )
        _require(
            isinstance(self.deterministic_seed, int)
            and not isinstance(self.deterministic_seed, bool)
            and self.deterministic_seed >= 0,
            "deterministic_seed must be a non-negative integer.",
        )
        _require(
            all(isinstance(item, str) and bool(item.strip()) for item in self.warnings),
            "warnings must contain only non-empty strings; no warnings is an empty tuple.",
        )


@dataclass(frozen=True, slots=True)
class ShadowCalibrationReport:
    """One shadow measurement's complete, internal-only record."""

    generated_at_utc: str
    execution: ShadowExecutionMetadata
    horizon: int
    residual_source: ShadowResidualSource
    sample_size: int
    point_estimate: float | None
    calibration_diagnostics: Mapping[str, float | None]
    interval_diagnostics: Mapping[str, float | None]
    gate_results: tuple[ShadowGateResult, ...]
    shadow_status: str
    reasons: tuple[str, ...]
    provenance_fingerprints: Mapping[str, str]
    contract_version: str = field(default=SHADOW_CALIBRATION_CONTRACT_VERSION)

    def __post_init__(self) -> None:
        _require(
            self.contract_version == SHADOW_CALIBRATION_CONTRACT_VERSION,
            f"contract_version must be {SHADOW_CALIBRATION_CONTRACT_VERSION!r}.",
        )
        _require(bool(self.generated_at_utc), "generated_at_utc must be non-empty.")
        _require(
            self.horizon == 1,
            "shadow_calibration_report_v1 is single-gameweek: h=1 only. Multi-week "
            "aggregation requires its own pre-registration before a contract admits it.",
        )
        _require(self.sample_size >= 0, "sample_size cannot be negative.")
        if self.point_estimate is not None:
            _require(math.isfinite(self.point_estimate), "point_estimate must be finite or None.")
        _finite_or_none("calibration_diagnostics", self.calibration_diagnostics)
        _finite_or_none("interval_diagnostics", self.interval_diagnostics)
        _require(
            self.shadow_status in SHADOW_STATUSES,
            f"shadow_status must be one of {SHADOW_STATUSES!r}, got {self.shadow_status!r}.",
        )
        if self.shadow_status == "calibrated_internal":
            _require(bool(self.gate_results), "calibrated_internal requires gate results.")
            _require(
                all(gate.passes for gate in self.gate_results),
                "calibrated_internal requires every pre-registered gate to pass; a "
                "failed gate is a failed report, not a caveat.",
            )
        else:
            _require(
                bool(self.reasons),
                f"{self.shadow_status} must state its reasons; an unexplained "
                "non-result is not a record.",
            )
        for key, value in self.provenance_fingerprints.items():
            _require(
                bool(key) and bool(value),
                "provenance_fingerprints entries must be non-empty strings.",
            )


def report_to_dict(report: ShadowCalibrationReport) -> dict[str, object]:
    """The report as one JSON-ready mapping, missing values kept as None."""

    source = report.residual_source
    return {
        "contract_version": report.contract_version,
        "generated_at_utc": report.generated_at_utc,
        "execution": {
            "started_at_utc": report.execution.started_at_utc,
            "completed_at_utc": report.execution.completed_at_utc,
            "elapsed_seconds": report.execution.elapsed_seconds,
            "deterministic_seed": report.execution.deterministic_seed,
            "warnings": list(report.execution.warnings),
        },
        "horizon": report.horizon,
        "residual_source": {
            "export_label": source.export_label,
            "model_name": source.model_name,
            "model_version": source.model_version,
            "feature_contract_version": source.feature_contract_version,
            "table_sha256": source.table_sha256,
            "seasons": list(source.seasons),
            "cutoff_fold_id": source.cutoff_fold_id,
        },
        "sample_size": report.sample_size,
        "point_estimate": report.point_estimate,
        "calibration_diagnostics": dict(report.calibration_diagnostics),
        "interval_diagnostics": dict(report.interval_diagnostics),
        "gate_results": [
            {
                "gate": gate.gate,
                "passes": gate.passes,
                "observed": gate.observed,
                "threshold": gate.threshold,
            }
            for gate in report.gate_results
        ],
        "shadow_status": report.shadow_status,
        "reasons": list(report.reasons),
        "provenance_fingerprints": dict(report.provenance_fingerprints),
    }


def write_shadow_report(report: ShadowCalibrationReport, path: Path) -> None:
    """Write one report as stable LF JSON — and refuse the published site tree."""

    resolved = path.resolve()
    _require(
        "web/public" not in resolved.as_posix(),
        f"{resolved} sits inside a published site tree; shadow artifacts are "
        "internal-only and may never be written under web/public.",
    )
    payload = json.dumps(report_to_dict(report), indent=2, sort_keys=True, allow_nan=False)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    with resolved.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(payload + "\n")
