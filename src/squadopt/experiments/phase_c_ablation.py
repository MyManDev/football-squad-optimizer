"""Descriptive, exact-key Phase C evidence ablations."""

import hashlib
import json
import math
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from numbers import Integral, Real
from typing import Final

import pandas as pd

from squadopt.evaluation import (
    PHASE_C_OOF_KEY,
    PHASE_C_OOF_REQUIRED_COLUMNS,
    PhaseCComponentEvaluation,
    evaluate_component_oof,
)
from squadopt.experiments.config import ExperimentExecutionError

PHASE_C_ABLATION_CONTRACT_VERSION: Final = "phase_c_evidence_ablation_v1"
COMPONENT_BASE_ARM: Final = "component_base"
PHASE_C_EVIDENCE_FAMILIES: Final = ("none", "availability", "ownership_transfer", "elite")
_PAIR_COLUMNS: Final = (
    "fold_id",
    "position",
    "fixture_count",
    "composition_route",
    "appearance_target",
    "start_target",
    "minutes_target",
    "points_target",
)
_PREDICTION_COLUMNS: Final = (
    "appearance_probability",
    "q_start_given_appearance",
    "start_probability",
    "expected_minutes_if_appearance",
    "expected_minutes",
    "expected_points_if_appearance",
    "fallback_expected_points",
    "expected_points",
)
_DIGEST_CHARACTERS: Final = frozenset("0123456789abcdef")


def _label(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ExperimentExecutionError(f"{name} must be non-empty text.")
    return value.strip()


def _digest(value: object, name: str) -> str:
    normalized = _label(value, name)
    if len(normalized) != 64 or any(
        character not in _DIGEST_CHARACTERS for character in normalized
    ):
        raise ExperimentExecutionError(f"{name} must be a lowercase SHA-256 digest.")
    return normalized


@dataclass(frozen=True, slots=True)
class PhaseCArmDeclaration:
    """Identity of one already-produced Phase C component table."""

    arm_id: str
    evidence_family: str
    model_version: str
    feature_contract_version: str
    target_contract_version: str
    evaluation_rows_sha256: str

    def __post_init__(self) -> None:
        for name in (
            "arm_id",
            "model_version",
            "feature_contract_version",
            "target_contract_version",
        ):
            object.__setattr__(self, name, _label(getattr(self, name), name))
        family = _label(self.evidence_family, "evidence_family")
        if family not in PHASE_C_EVIDENCE_FAMILIES:
            raise ExperimentExecutionError(
                f"evidence_family must be one of {list(PHASE_C_EVIDENCE_FAMILIES)!r}."
            )
        object.__setattr__(self, "evidence_family", family)
        object.__setattr__(
            self,
            "evaluation_rows_sha256",
            _digest(self.evaluation_rows_sha256, "evaluation_rows_sha256"),
        )


@dataclass(frozen=True, slots=True)
class PhaseCArmEvaluation:
    """One arm's metrics after table and pairing validation."""

    declaration: PhaseCArmDeclaration
    metrics: PhaseCComponentEvaluation


@dataclass(frozen=True, slots=True)
class PhaseCAblationEvaluation:
    """Descriptive scores for exact-key component-base and evidence arms."""

    base: PhaseCArmEvaluation
    candidates: tuple[PhaseCArmEvaluation, ...]
    paired_rows: int
    comparison_fingerprint: str
    contract_version: str = PHASE_C_ABLATION_CONTRACT_VERSION


def _canonical_value(value: object) -> object:
    if value is None or value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, Real) and not isinstance(value, bool):
        number = float(value)
        if math.isnan(number):
            return None
        if isinstance(value, Integral):
            return int(value)
        return number
    return value


def _canonical_rows(rows: pd.DataFrame) -> list[dict[str, object]]:
    canonical = rows.loc[:, list(PHASE_C_OOF_REQUIRED_COLUMNS)].sort_values(
        list(PHASE_C_OOF_KEY), kind="stable"
    )
    return [
        {str(column): _canonical_value(value) for column, value in record.items()}
        for record in canonical.to_dict("records")
    ]


def phase_c_evaluation_rows_sha256(rows: pd.DataFrame) -> str:
    """Digest the canonical scorer columns; this is not a source-file checksum."""

    evaluate_component_oof(rows)
    payload = json.dumps(
        _canonical_rows(rows),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _validate_declared_table(
    declaration: PhaseCArmDeclaration, rows: pd.DataFrame
) -> PhaseCComponentEvaluation:
    metrics = evaluate_component_oof(rows)
    actual = phase_c_evaluation_rows_sha256(rows)
    if actual != declaration.evaluation_rows_sha256:
        raise ExperimentExecutionError(
            f"Phase C arm {declaration.arm_id!r} evaluation_rows_sha256 does not match "
            "its exact scorer rows."
        )
    return metrics


def _comparable_rows(rows: pd.DataFrame) -> pd.DataFrame:
    return (
        rows.loc[
            :,
            [*PHASE_C_OOF_KEY, *_PAIR_COLUMNS, "evidence_status", *_PREDICTION_COLUMNS],
        ]
        .sort_values(list(PHASE_C_OOF_KEY), kind="stable")
        .reset_index(drop=True)
    )


def _pair_exactly(base: pd.DataFrame, candidate: pd.DataFrame, arm_id: str) -> None:
    for column in (*PHASE_C_OOF_KEY, *_PAIR_COLUMNS):
        left = [_canonical_value(value) for value in base[column].tolist()]
        right = [_canonical_value(value) for value in candidate[column].tolist()]
        if left != right:
            raise ExperimentExecutionError(
                f"Phase C arm {arm_id!r} changes paired {column!r} values."
            )
    for column in _PREDICTION_COLUMNS:
        if base[column].notna().tolist() != candidate[column].notna().tolist():
            raise ExperimentExecutionError(
                f"Phase C arm {arm_id!r} changes the {column!r} eligibility mask."
            )
    missing_evidence = candidate["evidence_status"].eq("missing")
    for column in ("composition_route", *_PREDICTION_COLUMNS):
        left = [_canonical_value(value) for value in base.loc[missing_evidence, column].tolist()]
        right = [
            _canonical_value(value) for value in candidate.loc[missing_evidence, column].tolist()
        ]
        if left != right:
            raise ExperimentExecutionError(
                f"Phase C arm {arm_id!r} must reproduce component_base for missing evidence."
            )


def evaluate_phase_c_ablations(
    base_declaration: PhaseCArmDeclaration,
    base_rows: pd.DataFrame,
    candidate_arms: Iterable[tuple[PhaseCArmDeclaration, pd.DataFrame]],
) -> PhaseCAblationEvaluation:
    """Score exact-key evidence arms descriptively without applying promotion gates."""

    if not isinstance(base_declaration, PhaseCArmDeclaration):
        raise ExperimentExecutionError("base_declaration must be a PhaseCArmDeclaration.")
    if base_declaration.arm_id != COMPONENT_BASE_ARM or base_declaration.evidence_family != "none":
        raise ExperimentExecutionError("The base arm must be component_base with no evidence.")
    try:
        candidates = tuple(candidate_arms)
    except TypeError as error:
        raise ExperimentExecutionError("candidate_arms must be iterable.") from error
    if not candidates:
        raise ExperimentExecutionError("At least one evidence candidate arm is required.")

    base_metrics = _validate_declared_table(base_declaration, base_rows)
    paired_base = _comparable_rows(base_rows)
    if set(paired_base["evidence_status"].tolist()) != {"not_requested"}:
        raise ExperimentExecutionError("component_base evidence must be not_requested.")
    seen_arm_ids = {base_declaration.arm_id}
    seen_families: set[str] = set()
    evaluated: list[PhaseCArmEvaluation] = []
    for item in candidates:
        if not isinstance(item, tuple) or len(item) != 2:
            raise ExperimentExecutionError(
                "Each candidate arm must be a (PhaseCArmDeclaration, DataFrame) pair."
            )
        declaration, rows = item
        if not isinstance(declaration, PhaseCArmDeclaration):
            raise ExperimentExecutionError("Every candidate needs a PhaseCArmDeclaration.")
        if declaration.arm_id in seen_arm_ids:
            raise ExperimentExecutionError(f"Repeated Phase C arm_id: {declaration.arm_id!r}.")
        if declaration.evidence_family == "none":
            raise ExperimentExecutionError("A candidate arm must declare one evidence family.")
        if declaration.evidence_family in seen_families:
            raise ExperimentExecutionError(
                "Only one candidate per evidence family is allowed: "
                f"{declaration.evidence_family!r}."
            )
        if declaration.target_contract_version != base_declaration.target_contract_version:
            raise ExperimentExecutionError("All arms must share one target_contract_version.")
        metrics = _validate_declared_table(declaration, rows)
        paired_candidate = _comparable_rows(rows)
        if "not_requested" in set(paired_candidate["evidence_status"].tolist()):
            raise ExperimentExecutionError(
                "Evidence candidate rows must declare available or missing evidence."
            )
        _pair_exactly(paired_base, paired_candidate, declaration.arm_id)
        evaluated.append(PhaseCArmEvaluation(declaration, metrics))
        seen_arm_ids.add(declaration.arm_id)
        seen_families.add(declaration.evidence_family)

    ordered = tuple(sorted(evaluated, key=lambda item: item.declaration.arm_id))
    fingerprint_payload = {
        "contract_version": PHASE_C_ABLATION_CONTRACT_VERSION,
        "base": asdict(base_declaration),
        "candidates": [asdict(item.declaration) for item in ordered],
    }
    fingerprint = hashlib.sha256(
        json.dumps(fingerprint_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return PhaseCAblationEvaluation(
        base=PhaseCArmEvaluation(base_declaration, base_metrics),
        candidates=ordered,
        paired_rows=len(paired_base),
        comparison_fingerprint=fingerprint,
    )


__all__ = [
    "COMPONENT_BASE_ARM",
    "PHASE_C_ABLATION_CONTRACT_VERSION",
    "PHASE_C_EVIDENCE_FAMILIES",
    "PhaseCAblationEvaluation",
    "PhaseCArmDeclaration",
    "PhaseCArmEvaluation",
    "evaluate_phase_c_ablations",
    "phase_c_evaluation_rows_sha256",
]
