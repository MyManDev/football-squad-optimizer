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

import contextlib
import json
import math
import os
import re
import secrets
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

SHADOW_CALIBRATION_CONTRACT_VERSION = "shadow_calibration_report_v1"
LOCKED_HOLDOUT_SEASON = "2025-26"
SHADOW_STATUSES: tuple[str, ...] = ("calibrated_internal", "failed", "abstained")

#: The pre-registered gate families of the Phase 2 protocol. This lives in the contract
#: rather than in a runner, because a report that may declare its own gate set can
#: declare a subset of the protocol and pass it — which is the failure the completeness
#: rule exists to prevent.
PREREG_GATE_FAMILIES: tuple[str, ...] = (
    "P1_player_coverage",
    "S1_squad_pit_location",
    "S2_squad_lower_tail",
)

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_FOLD_ID = re.compile(r"^\d{4}-\d{2}-gw\d{2}$")


class ShadowReportError(ValueError):
    """Raised when a shadow report violates its own contract."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ShadowReportError(message)


def _matches_family(gate: str, family: str) -> bool:
    """Does one measured gate id belong to a declared pre-registered family?

    A family may be answered by one entry of its own name, or by several sub-gates
    named ``<family>_<cell>`` — gate P1 is measured pooled and per fixture group. The
    rule is exact-or-underscore-prefix so that a typo drops a gate loudly rather than
    matching by accident.
    """

    return gate == family or gate.startswith(f"{family}_")


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
    #: The pre-registered gate families this report claims to answer. Empty means the
    #: report makes no completeness claim, which is what every report written before
    #: this field existed does; such a report can never be ``calibrated_internal``.
    declared_gates: tuple[str, ...] = field(default=())
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
        _require(
            not isinstance(self.declared_gates, str),
            "declared_gates must be a sequence of names, not a single string.",
        )
        for family in self.declared_gates:
            _require(
                isinstance(family, str) and bool(family.strip()),
                "a declared gate family must be a non-empty name.",
            )
        _require(
            len(set(self.declared_gates)) == len(self.declared_gates),
            f"declared_gates repeats a family: {self.declared_gates!r}.",
        )
        if self.shadow_status == "calibrated_internal":
            _require(bool(self.gate_results), "calibrated_internal requires gate results.")
            _require(
                all(gate.passes for gate in self.gate_results),
                "calibrated_internal requires every pre-registered gate to pass; a "
                "failed gate is a failed report, not a caveat.",
            )
            # A subset of the protocol is not a verdict. This lives in the contract
            # rather than in one runner's prose, so a second runner inherits it
            # instead of having to remember it.
            _require(
                bool(self.declared_gates),
                "calibrated_internal requires declared_gates: a report that does not "
                "say which gates the protocol required cannot claim to have passed it.",
            )
            missing = [
                family for family in PREREG_GATE_FAMILIES if family not in set(self.declared_gates)
            ]
            _require(
                not missing,
                f"declared_gates omits pre-registered families {missing!r}. A report may "
                "not declare a subset of the protocol and then pass its own subset.",
            )
            for family in self.declared_gates:
                _require(
                    any(_matches_family(gate.gate, family) for gate in self.gate_results),
                    f"declared gate {family!r} has no entry in gate_results; a partial "
                    "gate set cannot produce a complete pass verdict.",
                )
            for gate in self.gate_results:
                _require(
                    any(_matches_family(gate.gate, family) for family in self.declared_gates),
                    f"gate {gate.gate!r} matches no declared family {self.declared_gates!r}; "
                    "a measured gate outside the pre-registered set cannot count toward it.",
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
    document: dict[str, object] = {
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
    if report.declared_gates:
        # Omitted when empty so that a report written before this field existed
        # serializes to the same bytes and still replays. A report that declares
        # nothing makes no completeness claim, and says so by saying nothing.
        document["declared_gates"] = list(report.declared_gates)
    return document


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


def write_shadow_report_once(report: ShadowCalibrationReport, path: Path) -> str:
    """Publish a report atomically, exactly once, and say which of three happened.

    The corrective amendment requires a writer that is crash-safe and safe under
    concurrent writers: the bytes are completed and fsynced in a sibling temporary
    file, published with a no-overwrite hard link, and the temporary removed on every
    path. A losing writer compares its own bytes with the winner's and reports a
    replay when they agree.

    Returns ``"written"``, ``"replay"`` or raises. ``replay_identity_of`` decides what
    a replay may differ by — only the wall clock.
    """

    resolved = path.resolve()
    _require(
        "web/public" not in resolved.as_posix(),
        f"{resolved} sits inside a published site tree; shadow reports are internal.",
    )
    document = report_to_dict(report)
    serialized = json.dumps(document, indent=2, sort_keys=True, allow_nan=False)
    payload = (serialized + "\n").encode("utf-8")
    resolved.parent.mkdir(parents=True, exist_ok=True)
    temporary = resolved.with_name(f".{resolved.name}.tmp-{os.getpid()}-{secrets.token_hex(8)}")
    try:
        with temporary.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, resolved)
            return "written"
        except FileExistsError:
            existing_bytes = resolved.read_bytes()
            if existing_bytes == payload:
                return "replay"
            try:
                existing = json.loads(existing_bytes)
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise ShadowReportError(
                    f"{resolved} already exists but is not the recorded JSON contract."
                ) from error
            if replay_identity_of(existing) == replay_identity_of(document):
                return "replay"
            raise ShadowReportError(
                f"{resolved} already holds a different measurement. A recorded result is "
                "not overwritten; move or delete it deliberately if it is superseded."
            ) from None
    finally:
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()


def replay_identity_of(document: Mapping[str, object]) -> dict[str, object]:
    """The part of a report two runs of the same measurement must agree on, byte for byte.

    Only the wall clock is excluded — the top-level stamp and the three timing fields
    inside ``execution``. Nothing else is exempt: a differing number is a differing
    measurement, and a differing seed or warning is a differing run.
    """

    identity = {key: value for key, value in document.items() if key != "generated_at_utc"}
    execution = identity.get("execution")
    if isinstance(execution, Mapping):
        identity["execution"] = {
            key: value
            for key, value in execution.items()
            if key not in {"started_at_utc", "completed_at_utc", "elapsed_seconds"}
        }
    return identity
