"""The internal shadow calibration report — versioned, never member-facing.

Phase 2's shadow measurements need one artifact shape whose honesty is structural
rather than editorial. This contract is that shape, and it is deliberately
unreachable from the published site: nothing under
``ui_view_v1`` references it, the writer refuses any destination inside a
``web/public`` tree, and serialization refuses NaN so an unmeasured number can
never ride out looking measured. Missing and zero stay distinct throughout —
an absent diagnostic is ``None`` (serialized ``null``), never ``0``.

The three terminal statuses mirror ``docs/phase2_shadow_calibration_prereg.md``:
``calibrated_internal`` (every gate passed; unlocks nothing member-facing),
``failed`` (a recorded negative; thresholds do not move), and ``abstained``
(insufficient sample or unprovable inputs — distinct from failure, and it must
say why).

**Two versions, and why the older one was not rewritten.** ``v1`` is what the
player-level runner recorded, and it means exactly what it meant on the day those
artifacts were written: a report answers whichever gates its runner could reach, and
``calibrated_internal`` asks only that each one passed. That is too weak for a
protocol measured by two instruments — a report that answers one family of three and
passes it reads as a pass — but the answer is a new version, not a quiet redefinition
of the recorded one. ``v2`` adds two rules on top of v1:

* **Completeness.** A v2 report must declare the pre-registered gate families it
  answers, must declare all of them, and may not carry a measured gate outside what it
  declared. ``calibrated_internal`` then additionally requires every declared family to
  carry an entry, so a partial gate set cannot produce a complete verdict.
* **Status consistency.** ``failed`` and a gate that failed *as measured* imply each
  other. A measured negative may not be filed as an abstention, and an abstention may
  not be dressed up as a failure it did not measure. A gate with no observation is
  missing evidence rather than a negative, so it abstains instead.

Both versions load. Only v2 may be written by a full-protocol runner, and the two
recorded v1 documents still round-trip byte for byte.
"""

import contextlib
import hashlib
import json
import math
import os
import re
import secrets
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

SHADOW_CALIBRATION_CONTRACT_V1 = "shadow_calibration_report_v1"
SHADOW_CALIBRATION_CONTRACT_V2 = "shadow_calibration_report_v2"
SHADOW_CONTRACT_VERSIONS: tuple[str, ...] = (
    SHADOW_CALIBRATION_CONTRACT_V1,
    SHADOW_CALIBRATION_CONTRACT_V2,
)

#: What a report is written under when nothing says otherwise. It stays at v1 so that
#: the player-level runner keeps producing the bytes its recorded artifacts already
#: hold; a runner that answers the whole protocol asks for v2 explicitly.
SHADOW_CALIBRATION_CONTRACT_VERSION = SHADOW_CALIBRATION_CONTRACT_V1

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

#: The family set each version answers, pinned to the version rather than read from
#: the constant above at load time. Otherwise a v2 document's meaning would depend on
#: what this module happens to say when someone reads it: adding a fourth family would
#: retroactively make every recorded v2 artifact unloadable, which is the same failure
#: the v1 freeze exists to prevent, one level up. A new family is a new version.
_PREREG_BY_VERSION: dict[str, tuple[str, ...]] = {
    SHADOW_CALIBRATION_CONTRACT_V2: PREREG_GATE_FAMILIES,
}

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
    matching by accident, and the cell name must be a real name: ``P1_player_coverage_``
    and ``P1_player_coverage_\u200b`` would otherwise answer a family with a cell that
    reads as nothing at all.
    """

    if gate == family:
        return True
    if not gate.startswith(f"{family}_"):
        return False
    cell = gate[len(family) + 1 :]
    # A real name: at least one alphanumeric character, and no whitespace. Otherwise
    # a family is answered by a cell called nothing at all, including the invisible
    # kinds -- an empty suffix, a space, or a zero-width character.
    return any(character.isalnum() for character in cell) and not any(
        character.isspace() for character in cell
    )


def _instant(label: str, value: str) -> datetime:
    """One UTC timestamp, or a refusal naming the field that is not one."""

    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError) as error:
        raise ShadowReportError(f"{label} must be an ISO-8601 timestamp.") from error
    _require(
        parsed.tzinfo is not None and parsed.utcoffset() == UTC.utcoffset(parsed),
        f"{label} must describe a UTC instant.",
    )
    return parsed


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
        _require(
            isinstance(self.passes, bool),
            f"gate {self.gate!r}: passes must be a boolean, got {self.passes!r}.",
        )
        if self.observed is not None:
            _require(
                isinstance(self.observed, float) and math.isfinite(self.observed),
                f"gate {self.gate!r}: observed must be a finite float or None.",
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
        started = _instant("started_at_utc", self.started_at_utc)
        completed = _instant("completed_at_utc", self.completed_at_utc)
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
    #: The pre-registered gate families this report claims to answer. A v2 report must
    #: declare all of them; a v1 report may not declare any, because the field did not
    #: exist when v1's meaning was fixed and a v1 document that carried one would be
    #: making a claim its own contract never checked.
    declared_gates: tuple[str, ...] = field(default=())
    contract_version: str = field(default=SHADOW_CALIBRATION_CONTRACT_VERSION)

    def __post_init__(self) -> None:
        # Normalize the sequences first. They are annotated as tuples but a caller can
        # pass any sequence, and a list the caller keeps a reference to can grow after
        # every rule here has run — the writer would then publish gates this contract
        # never saw. A set is refused rather than frozen because its iteration order
        # varies per process, which turns one measurement into a conflict with itself.
        for name in ("gate_results", "declared_gates", "reasons"):
            value = getattr(self, name)
            _require(
                not isinstance(value, set | frozenset),
                f"{name} must be an ordered sequence; a set's iteration order varies "
                "between processes, so two runs of one measurement would disagree.",
            )
            _require(
                not isinstance(value, str),
                f"{name} must be a sequence of items, not a single string.",
            )
            object.__setattr__(self, name, tuple(value))

        _require(
            self.contract_version in SHADOW_CONTRACT_VERSIONS,
            f"contract_version must be one of {SHADOW_CONTRACT_VERSIONS!r}, got "
            f"{self.contract_version!r}.",
        )
        _require(bool(self.generated_at_utc), "generated_at_utc must be non-empty.")
        _instant("generated_at_utc", self.generated_at_utc)
        _require(
            isinstance(self.horizon, int) and not isinstance(self.horizon, bool),
            f"horizon must be an integer, got {self.horizon!r}.",
        )
        _require(
            isinstance(self.sample_size, int) and not isinstance(self.sample_size, bool),
            f"sample_size must be an integer, got {self.sample_size!r}.",
        )
        _require(
            self.horizon == 1,
            "every version of this contract is single-gameweek: h=1 only. Multi-week "
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
        self._check_declaration()
        if self.shadow_status == "calibrated_internal":
            _require(bool(self.gate_results), "calibrated_internal requires gate results.")
            _require(
                self.sample_size > 0 or self.contract_version != SHADOW_CALIBRATION_CONTRACT_V2,
                "calibrated_internal over a sample of zero is a pass of nothing; the "
                "gate entries would carry numbers no population produced.",
            )
            _require(
                all(gate.passes for gate in self.gate_results),
                "calibrated_internal requires every pre-registered gate to pass; a "
                "failed gate is a failed report, not a caveat.",
            )
            for family in self.declared_gates:
                _require(
                    any(_matches_family(gate.gate, family) for gate in self.gate_results),
                    f"declared gate {family!r} has no entry in gate_results; a partial "
                    "gate set cannot produce a complete pass verdict.",
                )
        else:
            _require(
                bool(self.reasons),
                f"{self.shadow_status} must state its reasons; an unexplained "
                "non-result is not a record.",
            )
            _require(
                all(isinstance(reason, str) and bool(reason.strip()) for reason in self.reasons),
                f"{self.shadow_status} must state its reasons in words; a blank reason "
                "is an unexplained non-result wearing a list.",
            )
        for key, value in self.provenance_fingerprints.items():
            _require(
                bool(key) and bool(value),
                "provenance_fingerprints entries must be non-empty strings.",
            )

    def _check_declaration(self) -> None:
        """The v2 completeness and status-consistency rules, and v1's freeze.

        Everything here is keyed on the version. v1 keeps the meaning its recorded
        artifacts were written under — the alternative is to change what a document
        already on disk claims, which is the one thing a version number exists to
        prevent.
        """

        for family in self.declared_gates:
            _require(
                isinstance(family, str) and bool(family.strip()),
                "a declared gate family must be a non-empty name.",
            )
        _require(
            len(set(self.declared_gates)) == len(self.declared_gates),
            f"declared_gates repeats a family: {self.declared_gates!r}.",
        )

        if self.contract_version != SHADOW_CALIBRATION_CONTRACT_V2:
            _require(
                not self.declared_gates,
                f"declared_gates is a {SHADOW_CALIBRATION_CONTRACT_V2} field; "
                f"{self.contract_version} was recorded without it and its meaning is "
                "frozen at what its artifacts were written under.",
            )
            return

        _require(
            bool(self.declared_gates),
            f"a {SHADOW_CALIBRATION_CONTRACT_V2} report must declare which "
            "pre-registered gate families it answers; a report that does not say what "
            "the protocol required cannot be read as having answered it.",
        )
        families = _PREREG_BY_VERSION[self.contract_version]
        missing = [family for family in families if family not in set(self.declared_gates)]
        _require(
            not missing,
            f"declared_gates omits pre-registered families {missing!r}. A report may "
            "not declare a subset of the protocol and then pass its own subset.",
        )
        extra = sorted(set(self.declared_gates) - set(families))
        _require(
            not extra,
            f"declared_gates names families {extra!r} that {self.contract_version} does "
            "not pre-register. Declaring an extra family would let a gate outside the "
            "protocol ride in as though it belonged to it.",
        )
        # Exactly the pre-registered tuple, in its pre-registered order. Order is not
        # cosmetic here: it is serialized, so two runs of one measurement that listed
        # the same families differently would write different bytes and read as a
        # conflict rather than as a replay.
        _require(
            tuple(self.declared_gates) == tuple(families),
            f"declared_gates must be exactly {list(families)!r}; "
            f"{list(self.declared_gates)!r} lists the same protocol in another order, "
            "which serializes differently and would read as a different measurement.",
        )
        identifiers = [gate.gate for gate in self.gate_results]
        repeated = sorted({name for name in identifiers if identifiers.count(name) > 1})
        _require(
            not repeated,
            f"gate_results repeats {repeated!r}. One gate is one answer; two entries "
            "under one id can carry two different observations.",
        )
        for gate in self.gate_results:
            _require(
                any(_matches_family(gate.gate, family) for family in self.declared_gates),
                f"gate {gate.gate!r} matches no declared family {self.declared_gates!r}; "
                "a measured gate outside the pre-registered set cannot count toward it.",
            )

        # A gate with no observation is missing evidence, not a negative result, so it
        # is deliberately not a failure here: the prereg files those under abstention.
        measured_failures = tuple(
            gate.gate for gate in self.gate_results if not gate.passes and gate.observed is not None
        )
        if measured_failures:
            _require(
                self.shadow_status == "failed",
                f"gates {list(measured_failures)!r} failed as measured, so this report "
                f"is 'failed'; {self.shadow_status!r} would file a recorded negative as "
                "something else.",
            )
        else:
            _require(
                self.shadow_status != "failed",
                "'failed' names at least one gate that failed as measured. A report "
                "with none is an abstention, and must say what was missing.",
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
        # Only v2 can carry these, and a v2 report always does. Writing the key only
        # when it is non-empty is what keeps a v1 document's bytes exactly as recorded.
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
    payload = _validated_payload(report)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    with resolved.open("wb") as handle:
        handle.write(payload)


def write_shadow_report_once(report: ShadowCalibrationReport, path: Path) -> str:
    """Publish a report atomically, exactly once, and say which of two happened.

    The corrective amendment requires a writer that is crash-safe and safe under
    concurrent writers: the bytes are completed and fsynced in a sibling temporary
    file, published with a no-overwrite hard link, and the temporary removed on every
    path. A losing writer compares its own bytes with the winner's and reports a
    replay when they agree.

    Returns ``"written"`` or ``"replay"``, and raises when the path already holds a
    different measurement. ``replay_identity_of`` decides what a replay may differ
    by — only the wall clock.
    """

    resolved = path.resolve()
    _require(
        "web/public" not in resolved.as_posix(),
        f"{resolved} sits inside a published site tree; shadow reports are internal.",
    )
    payload = _validated_payload(report)
    document = json.loads(payload)
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
            try:
                existing_bytes = resolved.read_bytes()
            except OSError as error:
                raise ShadowReportError(
                    f"{resolved} is occupied by something this contract cannot read: {error}"
                ) from error
            if existing_bytes == payload:
                return "replay"
            # The occupant is compared through the reader, so a document this contract
            # would refuse cannot certify as a replay of one it accepts.
            existing = report_to_dict(load_shadow_bytes(existing_bytes, label=str(resolved)))
            if replay_identity_of(existing) == replay_identity_of(document):
                return "replay"
            raise ShadowReportError(
                f"{resolved} already holds a different measurement. A recorded result is "
                "not overwritten; move or delete it deliberately if it is superseded."
            ) from None
        except OSError as error:
            raise ShadowReportError(f"{resolved} could not be published: {error}") from error
    finally:
        with contextlib.suppress(OSError):
            temporary.unlink()


def _validated_payload(report: ShadowCalibrationReport) -> bytes:
    """The bytes to publish, proved readable before anything is written.

    Every rule of this contract runs in ``__post_init__``, once, against containers the
    caller still owns — a list handed in as ``gate_results`` can grow afterwards, and
    the writer would then publish gates no rule ever saw. Round-tripping the payload
    through the reader closes that: what reaches disk is exactly what a reader will
    accept, or nothing reaches disk at all.
    """

    payload = (
        json.dumps(report_to_dict(report), indent=2, sort_keys=True, allow_nan=False) + "\n"
    ).encode("utf-8")
    replayed = load_shadow_bytes(payload, label="the report being written")
    _require(
        report_to_dict(replayed) == json.loads(payload),
        "the report does not survive its own serialization; it would be written as a "
        "document this contract refuses to read.",
    )
    return payload


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


_REQUIRED_DOCUMENT_KEYS: frozenset[str] = frozenset(
    {
        "contract_version",
        "generated_at_utc",
        "execution",
        "horizon",
        "residual_source",
        "sample_size",
        "point_estimate",
        "calibration_diagnostics",
        "interval_diagnostics",
        "gate_results",
        "shadow_status",
        "reasons",
        "provenance_fingerprints",
    }
)
_OPTIONAL_DOCUMENT_KEYS: frozenset[str] = frozenset({"declared_gates"})

#: The nested shapes get the same allow-list as the top level. Checking only the top
#: level would let a rule a later contract expresses inside ``execution`` or
#: ``residual_source`` — which is where a provenance rule naturally goes — ride through
#: this reader as though it had been checked.
_EXECUTION_KEYS: frozenset[str] = frozenset(
    {"started_at_utc", "completed_at_utc", "elapsed_seconds", "deterministic_seed", "warnings"}
)
_SOURCE_KEYS: frozenset[str] = frozenset(
    {
        "export_label",
        "model_name",
        "model_version",
        "feature_contract_version",
        "table_sha256",
        "seasons",
        "cutoff_fold_id",
    }
)
_GATE_KEYS: frozenset[str] = frozenset({"gate", "passes", "observed", "threshold"})


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """JSON allows a repeated key; a record may not resolve one silently.

    Python keeps the last value, so a file that literally contains
    ``"shadow_status": "failed"`` followed by ``"shadow_status": "calibrated_internal"``
    would load as a pass — and the digest recorded beside it would attest exactly those
    bytes, so the provenance chain would endorse the ambiguity.
    """

    seen: dict[str, object] = {}
    for key, value in pairs:
        if key in seen:
            raise ShadowReportError(
                f"the document repeats the key {key!r}; which value it means is not "
                "decidable, and a record may not be ambiguous."
            )
        seen[key] = value
    return seen


def _field(document: Mapping[str, object], key: str) -> object:
    if key not in document:
        raise ShadowReportError(f"the report is missing required field {key!r}.")
    return document[key]


def _text(document: Mapping[str, object], key: str) -> str:
    value = _field(document, key)
    if not isinstance(value, str):
        raise ShadowReportError(f"{key} must be a string, got {type(value).__name__}.")
    return value


def _whole(document: Mapping[str, object], key: str) -> int:
    value = _field(document, key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ShadowReportError(f"{key} must be an integer, got {value!r}.")
    return value


def _number_or_none(value: object, label: str) -> float | None:
    """JSON has one number type; a missing value is null and stays None."""

    if value is None:
        return None
    if not isinstance(value, float):
        # Deliberately strict about int as well as bool. Every writer of this contract
        # emits floats here, so an integer is a document this contract could not have
        # produced — and one that would re-serialize as ``4.0`` where it read ``4``,
        # which is a document that loads and does not round-trip.
        raise ShadowReportError(f"{label} must be a floating-point number or null, got {value!r}.")
    number = float(value)
    if not math.isfinite(number):
        raise ShadowReportError(f"{label} must be finite; {number!r} is not measurable.")
    return number


def _text_tuple(value: object, label: str) -> tuple[str, ...]:
    if isinstance(value, str) or not isinstance(value, list | tuple):
        raise ShadowReportError(f"{label} must be a list of strings, got {type(value).__name__}.")
    for item in value:
        if not isinstance(item, str):
            raise ShadowReportError(f"{label} must contain only strings, got {item!r}.")
    return tuple(str(item) for item in value)


def _mapping(
    value: object, label: str, *, allowed: frozenset[str] | None = None
) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ShadowReportError(f"{label} must be a mapping, got {type(value).__name__}.")
    for key in value:
        if not isinstance(key, str) or not key:
            raise ShadowReportError(f"{label} keys must be non-empty strings, got {key!r}.")
    if allowed is not None:
        unknown = sorted(set(map(str, value)) - allowed)
        if unknown:
            raise ShadowReportError(
                f"{label} carries unrecognised fields {unknown!r}. It was probably "
                "written under a newer contract, whose extra rules this reader cannot "
                "check."
            )
    return {str(key): item for key, item in value.items()}


def _diagnostics(document: Mapping[str, object], key: str) -> dict[str, float | None]:
    entries = _mapping(_field(document, key), key)
    return {name: _number_or_none(item, f"{key}[{name!r}]") for name, item in entries.items()}


def load_shadow_report(document: Mapping[str, object]) -> ShadowCalibrationReport:
    """Rebuild one report from a parsed document, refusing anything unrecognised.

    Strict on purpose, and in both directions: a missing field is an error, and so is
    an unknown one. A document written under a later contract than this module knows
    would otherwise load as though its extra rules had been checked, which is exactly
    the silent-compatibility failure a version number exists to prevent. Every rule
    the dataclass enforces is then enforced again by construction.
    """

    if not isinstance(document, Mapping):
        raise ShadowReportError("a shadow report must be a JSON object.")
    unknown = sorted(set(document) - _REQUIRED_DOCUMENT_KEYS - _OPTIONAL_DOCUMENT_KEYS)
    if unknown:
        raise ShadowReportError(
            f"the report carries unrecognised fields {unknown!r}. It was probably "
            "written under a newer contract, whose extra rules this reader cannot check."
        )
    if "execution" not in document:
        raise ShadowReportError(
            "the report carries no execution block. The earliest v1 artifact was "
            "written before the corrective amendment required one, and it cannot be "
            "loaded without inventing the reproducibility facts it never recorded."
        )

    execution = _mapping(document["execution"], "execution", allowed=_EXECUTION_KEYS)
    elapsed = _number_or_none(_field(execution, "elapsed_seconds"), "execution.elapsed_seconds")
    if elapsed is None:
        raise ShadowReportError("execution.elapsed_seconds is required.")
    metadata = ShadowExecutionMetadata(
        started_at_utc=_text(execution, "started_at_utc"),
        completed_at_utc=_text(execution, "completed_at_utc"),
        elapsed_seconds=elapsed,
        deterministic_seed=_whole(execution, "deterministic_seed"),
        warnings=_text_tuple(_field(execution, "warnings"), "execution.warnings"),
    )

    source = _mapping(_field(document, "residual_source"), "residual_source", allowed=_SOURCE_KEYS)
    residual_source = ShadowResidualSource(
        export_label=_text(source, "export_label"),
        model_name=_text(source, "model_name"),
        model_version=_text(source, "model_version"),
        feature_contract_version=_text(source, "feature_contract_version"),
        table_sha256=_text(source, "table_sha256"),
        seasons=_text_tuple(_field(source, "seasons"), "residual_source.seasons"),
        cutoff_fold_id=_text(source, "cutoff_fold_id"),
    )

    entries = _field(document, "gate_results")
    if not isinstance(entries, list):
        raise ShadowReportError("gate_results must be a list.")
    gates: list[ShadowGateResult] = []
    for index, entry in enumerate(entries):
        gate = _mapping(entry, f"gate_results[{index}]", allowed=_GATE_KEYS)
        passes = _field(gate, "passes")
        if not isinstance(passes, bool):
            raise ShadowReportError(f"gate_results[{index}].passes must be a boolean.")
        gates.append(
            ShadowGateResult(
                gate=_text(gate, "gate"),
                passes=passes,
                observed=_number_or_none(_field(gate, "observed"), f"gate_results[{index}]"),
                threshold=_text(gate, "threshold"),
            )
        )

    fingerprints = _mapping(_field(document, "provenance_fingerprints"), "provenance_fingerprints")
    for name, item in fingerprints.items():
        if not isinstance(item, str):
            raise ShadowReportError(f"provenance_fingerprints[{name!r}] must be a string.")

    declared = document.get("declared_gates")
    if declared is not None or "declared_gates" in document:
        _require(
            _text(document, "contract_version") == SHADOW_CALIBRATION_CONTRACT_V2,
            "declared_gates is a v2 field; a v1 document that carries the key — even "
            "empty or null — is not a document this contract could have written, and "
            "would not re-serialize to its own bytes.",
        )
    return ShadowCalibrationReport(
        generated_at_utc=_text(document, "generated_at_utc"),
        execution=metadata,
        horizon=_whole(document, "horizon"),
        residual_source=residual_source,
        sample_size=_whole(document, "sample_size"),
        point_estimate=_number_or_none(_field(document, "point_estimate"), "point_estimate"),
        calibration_diagnostics=_diagnostics(document, "calibration_diagnostics"),
        interval_diagnostics=_diagnostics(document, "interval_diagnostics"),
        gate_results=tuple(gates),
        shadow_status=_text(document, "shadow_status"),
        reasons=_text_tuple(_field(document, "reasons"), "reasons"),
        provenance_fingerprints={name: str(item) for name, item in fingerprints.items()},
        declared_gates=(() if declared is None else _text_tuple(declared, "declared_gates")),
        contract_version=_text(document, "contract_version"),
    )


def read_shadow_report(path: Path) -> tuple[ShadowCalibrationReport, str]:
    """Load a recorded report and the SHA-256 of the exact bytes that produced it.

    The digest is returned beside the report rather than recomputed later, because a
    reader that hashes the file a second time is hashing whatever is there then, not
    what it read.
    """

    try:
        raw = path.read_bytes()
    except OSError as error:
        raise ShadowReportError(f"{path} could not be read: {error}") from error
    return load_shadow_bytes(raw, label=str(path)), hashlib.sha256(raw).hexdigest()


def load_shadow_bytes(raw: bytes, *, label: str) -> ShadowCalibrationReport:
    """Parse and validate one document's exact bytes, duplicates and all."""

    try:
        document = json.loads(raw, object_pairs_hook=_reject_duplicate_keys)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ShadowReportError(f"{label} is not a readable shadow report: {error}") from error
    if not isinstance(document, dict):
        raise ShadowReportError(f"{label} does not hold a JSON object.")
    return load_shadow_report(document)
