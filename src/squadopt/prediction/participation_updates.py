"""Apply explicit participation evidence to a fresh, identified projection basis.

This is an evidence adapter, not a news probability model. A captured percentage is
an eligibility multiplier, an assumption is labelled as such, and an external
calibration is usable only with its supplied provenance. No statement, LLM confidence,
or categorical rotation/minutes warning supplies a numerical probability here.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from numbers import Real
from typing import Literal

import pandas as pd

from squadopt.prediction.config import PredictionConfigurationError

EvidenceKind = Literal[
    "captured_source_percentage", "scenario_assumption", "external_calibration", "source_statement"
]
ProbabilityTarget = Literal["eligibility", "appearance"]
PARTICIPATION_UPDATE_CONTRACT = "participation_evidence_v1"
_BASIS_MARKER = "squadopt_participation_update"
_UNINFORMATIVE = frozenset(("no_statement", "not_addressed", "ambiguous"))


@dataclass(frozen=True, slots=True)
class ParticipationEvidence:
    """One source or explicit assumption, bound to one decision week and deadline.

    ``source_percentage`` is the value actually captured from the source (0..100).
    ``probability`` is reserved for an explicit scenario assumption (0..1). External
    calibration values live in a separately identified table, never in LLM output.
    ``valid_until`` is explicit: this adapter does not invent a recovery date or carry
    a week-six statement into weeks seven to ten.
    """

    evidence_id: str
    player_id: int
    season: str
    gameweek: int
    deadline: pd.Timestamp
    published_at: pd.Timestamp
    captured_at: pd.Timestamp
    valid_until: pd.Timestamp
    source_id: str
    kind: EvidenceKind
    source_url: str | None = None
    disposition: str = "no_statement"
    source_percentage: float | None = None
    probability: float | None = None
    target: ProbabilityTarget = "eligibility"
    assumption: str | None = None
    calibration_id: str | None = None


@dataclass(frozen=True, slots=True)
class DispositionCalibration:
    """An externally supplied mapping, whose accuracy this adapter does not certify.

    The caller must identify the evidence behind the table and when its observations
    ended. Positive sample count is metadata validation, not proof of calibration.
    No training observations are loaded or fitted by this module.
    """

    calibration_id: str
    reference: str
    published_at: pd.Timestamp
    observations_through: pd.Timestamp
    sample_count: int
    target: ProbabilityTarget
    probabilities: Mapping[str, float]


@dataclass(frozen=True, slots=True)
class ParticipationUpdate:
    table: pd.DataFrame
    diagnostics: tuple[dict[str, object], ...]
    base_revision: str


def _aware(value: object) -> bool:
    return isinstance(value, pd.Timestamp) and not pd.isna(value) and value.tzinfo is not None


def _number(value: object, upper: float = 1.0) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, Real)
        and math.isfinite(float(value))
        and 0.0 <= float(value) <= upper
    )


def _timing_reason(
    item: ParticipationEvidence,
    *,
    season: str,
    as_of: pd.Timestamp,
    deadlines: Mapping[int, pd.Timestamp],
) -> str | None:
    if not item.evidence_id.strip() or not item.source_id.strip():
        return "missing_source_identity"
    if item.season != season:
        return "season_mismatch"
    if item.gameweek not in deadlines or item.deadline != deadlines[item.gameweek]:
        return "deadline_mismatch"
    times = (item.deadline, item.published_at, item.captured_at, item.valid_until)
    if not all(_aware(value) for value in times):
        return "invalid_source_timing"
    if item.published_at > item.captured_at:
        return "invalid_source_timing"
    if item.captured_at > as_of:
        return "future_evidence"
    if as_of >= item.deadline or item.captured_at >= item.deadline:
        return "deadline_passed"
    if item.valid_until < as_of or as_of - item.published_at > pd.Timedelta(days=7):
        return "expired_evidence"
    if item.kind != "scenario_assumption" and not (item.source_url or "").strip():
        return "missing_source_citation"
    return None


def _calibration_reason(table: DispositionCalibration, as_of: pd.Timestamp) -> str | None:
    if not table.calibration_id.strip() or not table.reference.strip():
        return "missing_calibration_provenance"
    if (
        isinstance(table.sample_count, bool)
        or not isinstance(table.sample_count, int)
        or table.sample_count <= 0
    ):
        return "invalid_calibration_sample_count"
    if (
        not _aware(table.published_at)
        or not _aware(table.observations_through)
        or not table.observations_through <= table.published_at <= as_of
    ):
        return "ineligible_calibration_timing"
    if table.target not in ("eligibility", "appearance") or not table.probabilities:
        return "invalid_calibration_table"
    if any(not _number(value) for value in table.probabilities.values()):
        return "invalid_calibration_probability"
    return None


def _stated_probability(
    item: ParticipationEvidence,
    calibrations: Mapping[str, DispositionCalibration],
    as_of: pd.Timestamp,
) -> tuple[float | None, str, str | None]:
    if item.target not in ("eligibility", "appearance"):
        return None, item.target, "unsupported_probability_target"
    if item.kind == "captured_source_percentage":
        if item.target != "eligibility" or item.probability is not None:
            return None, item.target, "source_percentage_is_eligibility"
        if item.calibration_id is not None or item.assumption is not None:
            return None, item.target, "mixed_evidence_kinds"
        if not _number(item.source_percentage, 100.0):
            return None, item.target, "invalid_source_percentage"
        assert item.source_percentage is not None
        return float(item.source_percentage) / 100.0, "eligibility", None
    if item.source_percentage is not None:
        return None, item.target, "mixed_evidence_kinds"
    if item.kind == "scenario_assumption":
        if not (item.assumption or "").strip() or item.calibration_id is not None:
            return None, item.target, "missing_or_mixed_scenario_assumption"
        if not _number(item.probability):
            return None, item.target, "invalid_scenario_probability"
        assert item.probability is not None
        return float(item.probability), item.target, None
    if item.probability is not None or item.assumption is not None:
        return None, item.target, "mixed_evidence_kinds"
    if item.disposition in _UNINFORMATIVE:
        return None, item.target, item.disposition
    if item.kind == "source_statement":
        if item.calibration_id is not None:
            return None, item.target, "mixed_evidence_kinds"
        if item.disposition == "stated_expected_absent":
            return 0.0, "appearance", None
        return None, item.target, "categorical_statement_has_no_probability"
    if item.kind == "external_calibration":
        table = calibrations.get(item.calibration_id or "")
        if table is None or table.calibration_id != item.calibration_id:
            return None, item.target, "calibration_not_supplied"
        reason = _calibration_reason(table, as_of)
        if reason:
            return None, item.target, reason
        if item.target != table.target:
            return None, item.target, "calibration_target_mismatch"
        value = table.probabilities.get(item.disposition)
        if value is None:
            return None, item.target, "disposition_not_calibrated"
        return float(value), table.target, None
    return None, item.target, "unsupported_evidence_kind"


def _appearance(
    row: pd.Series[float], value: float, target: str
) -> tuple[float | None, str | None]:
    if target == "appearance":
        return value, None
    if "availability_multiplier" not in row or not _number(row["availability_multiplier"]):
        return None, "eligibility_basis_missing"
    prior_eligibility = float(row["availability_multiplier"])
    prior_q = float(row["appearance_probability"])
    if prior_eligibility == 0:
        if prior_q != 0:
            return None, "inconsistent_eligibility_basis"
        return (0.0, None) if value == 0 else (None, "zero_eligibility_basis")
    conditional_appearance = prior_q / prior_eligibility
    if conditional_appearance > 1.0 + 1e-12:
        return None, "inconsistent_eligibility_basis"
    return min(conditional_appearance, 1.0) * value, None


def apply_participation_updates(
    base: pd.DataFrame,
    evidence: Sequence[ParticipationEvidence],
    *,
    season: str,
    as_of: pd.Timestamp,
    deadlines: Mapping[int, pd.Timestamp],
    base_revision: str,
    calibrations: Mapping[str, DispositionCalibration] | None = None,
) -> ParticipationUpdate:
    """Replace participation once while preserving the base conditional point mean.

    The input carries ``player_id``, ``gameweek``, ``expected_points`` and
    ``appearance_probability``. A captured percentage additionally needs the actual
    base ``availability_multiplier``; it cannot be interpreted as a start probability.
    From a zero-q basis an explicit ``points_if_appearance`` is needed to revive q.

    Supply a fresh projection for ``base_revision`` every time. An output frame has a
    provenance marker and is refused as a new basis, preventing accidental compounding.
    Repeating an identical call on the same pristine basis gives an identical result.
    This adapter does not refit starts, minutes, or event distributions: use its narrow
    projection output at the planning boundary, or regenerate richer model outputs.
    """
    required = {"player_id", "gameweek", "expected_points", "appearance_probability"}
    if base.columns.has_duplicates:
        raise PredictionConfigurationError("Participation basis columns must be unique.")
    if not required.issubset(base.columns):
        raise PredictionConfigurationError("Participation basis lacks projection columns.")
    if not base_revision.strip() or not season.strip():
        raise PredictionConfigurationError("An identified season and base revision are required.")
    if _BASIS_MARKER in base.attrs:
        raise PredictionConfigurationError("Participation updates require a fresh base revision.")
    if not _aware(as_of) or not deadlines or not all(_aware(v) for v in deadlines.values()):
        raise PredictionConfigurationError("As-of and deadlines must be timezone-aware.")
    if base.duplicated(["player_id", "gameweek"]).any():
        raise PredictionConfigurationError("Participation basis repeats a player and gameweek.")
    if not set(base.gameweek).issubset(deadlines):
        raise PredictionConfigurationError("Every projected gameweek needs its exact deadline.")
    for q, points in zip(base.appearance_probability, base.expected_points, strict=True):
        if not _number(q) or isinstance(points, bool) or not isinstance(points, Real):
            raise PredictionConfigurationError(
                "Invalid participation basis probabilities or points."
            )
        if not math.isfinite(float(points)) or (q == 0 and points != 0):
            raise PredictionConfigurationError(
                "Participation basis has inconsistent expected points."
            )

    table = base.copy(deep=True)
    audit: list[dict[str, object]] = []
    by_row: dict[tuple[int, int], list[ParticipationEvidence]] = defaultdict(list)
    counts = Counter(item.evidence_id for item in evidence)
    for item in evidence:
        by_row[(item.player_id, item.gameweek)].append(item)
    present = set(zip(base.player_id, base.gameweek, strict=True))
    for item in evidence:
        if (item.player_id, item.gameweek) not in present:
            audit.append(
                {
                    "player_id": item.player_id,
                    "gameweek": item.gameweek,
                    "base_revision": base_revision,
                    "evidence_id": item.evidence_id,
                    "source_id": item.source_id,
                    "status": "unchanged",
                    "reason": "outside_projection",
                }
            )

    for position, (_, row) in enumerate(base.iterrows()):
        player_id, gameweek = int(row.player_id), int(row.gameweek)
        items = by_row.get((player_id, gameweek), [])
        diagnostic: dict[str, object] = {
            "player_id": player_id,
            "gameweek": gameweek,
            "base_revision": base_revision,
            "status": "unchanged",
            "reason": "no_evidence",
            "prior_appearance_probability": float(row.appearance_probability),
            "appearance_probability": float(row.appearance_probability),
            "evidence": [],
            "start_and_minutes_reestimated": False,
        }
        audit.append(diagnostic)
        if not items:
            continue
        candidates: list[tuple[float, float, str]] = []
        provenance: list[dict[str, object]] = []
        duplicate = any(counts[item.evidence_id] > 1 for item in items)
        source_counts = Counter(item.source_id for item in items)
        duplicate = duplicate or any(count > 1 for count in source_counts.values())
        for item in items:
            reason = _timing_reason(item, season=season, as_of=as_of, deadlines=deadlines)
            value, target = None, str(item.target)
            if reason is None:
                value, target, reason = _stated_probability(item, calibrations or {}, as_of)
            q = None
            if reason is None and value is not None:
                q, reason = _appearance(row, value, target)
            if reason is None and q is not None and value is not None:
                candidates.append((q, value, target))
            calibration = (calibrations or {}).get(item.calibration_id or "")
            provenance.append(
                {
                    "evidence_id": item.evidence_id,
                    "source_id": item.source_id,
                    "source_url": item.source_url,
                    "kind": item.kind,
                    "disposition": item.disposition,
                    "target": target,
                    "published_at": str(item.published_at),
                    "captured_at": str(item.captured_at),
                    "deadline": str(item.deadline),
                    "valid_until": str(item.valid_until),
                    "source_percentage": (
                        item.source_percentage if _number(item.source_percentage, 100.0) else None
                    ),
                    "assumption": item.assumption,
                    "stated_probability": value,
                    "calibration_id": item.calibration_id,
                    "calibration_reference": calibration.reference if calibration else None,
                    "calibration_sample_count": calibration.sample_count if calibration else None,
                    "calibration_observations_through": (
                        str(calibration.observations_through) if calibration else None
                    ),
                    "calibration_published_at": (
                        str(calibration.published_at) if calibration else None
                    ),
                    "calibration_verified_here": False,
                    "reason": reason or "eligible",
                }
            )
        diagnostic["evidence"] = provenance
        if duplicate:
            diagnostic["reason"] = "duplicate_evidence_or_source"
            continue
        # A claim that somebody will start or play limited minutes contradicts a
        # same-week absence, even though it cannot supply a numerical probability.
        # Only source-timed, cited statements reaching the semantic stage count.
        absent = any(
            record["kind"] == "source_statement"
            and record["disposition"] == "stated_expected_absent"
            and record["reason"] == "eligible"
            for record in provenance
        )
        expected_to_play = any(
            record["kind"] == "source_statement"
            and record["disposition"] in ("stated_expected_to_start", "stated_minutes_limited")
            and record["reason"] == "categorical_statement_has_no_probability"
            for record in provenance
        )
        if absent and expected_to_play:
            diagnostic["reason"] = "conflicting_sources"
            continue
        if not candidates:
            diagnostic["reason"] = provenance[0]["reason"]
            continue
        q, value, target = candidates[0]
        if any(not math.isclose(q, other[0], rel_tol=0.0, abs_tol=1e-12) for other in candidates):
            diagnostic["reason"] = "conflicting_sources"
            continue
        prior_q = float(row.appearance_probability)
        conditional_mean = float(row.expected_points) / prior_q if prior_q else 0.0
        if prior_q == 0 and q > 0:
            conditional = row.get("points_if_appearance")
            if (
                isinstance(conditional, bool)
                or not isinstance(conditional, Real)
                or not math.isfinite(float(conditional))
            ):
                diagnostic["reason"] = "zero_prior_without_conditional_mean"
                continue
            conditional_mean = float(conditional)
        table.iat[
            position, int(table.columns.get_indexer(pd.Index(["appearance_probability"]))[0])
        ] = q
        table.iat[position, int(table.columns.get_indexer(pd.Index(["expected_points"]))[0])] = (
            q * conditional_mean
        )
        if all(candidate[2] == "eligibility" for candidate in candidates):
            table.iat[
                position, int(table.columns.get_indexer(pd.Index(["availability_multiplier"]))[0])
            ] = value
        diagnostic.update(
            status="applied",
            reason="explicit_evidence",
            appearance_probability=q,
            conditional_points_if_appearance=conditional_mean,
        )
    table.attrs[_BASIS_MARKER] = {
        "contract": PARTICIPATION_UPDATE_CONTRACT,
        "base_revision": base_revision,
        "as_of": str(as_of),
        "evidence_ids": tuple(item.evidence_id for item in evidence),
    }
    return ParticipationUpdate(table, tuple(audit), base_revision)
