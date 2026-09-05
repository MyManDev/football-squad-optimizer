"""Run E3 only with binding Phase D evidence and an independently frozen E2 candidate count."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts import probe_phase_e_runtime as probe
from scripts import run_component_squad_calibration as binding
from scripts._experiment_cli import DEFAULT_ARCHIVE_ROOT, artifact_metadata
from scripts._phase_e_evaluation import evaluate_phase_e_prepared_folds
from scripts._phase_e_inputs import (
    PhaseDBindingEvidence,
    load_phase_d_binding,
    prepare_phase_e_folds,
)

from squadopt.data import DataError
from squadopt.evaluation import EvaluationError, read_phase_c_component_handoff
from squadopt.experiments.phase_e_shadow import PHASE_E_SHADOW_CONTRACT, PhaseEShadowError
from squadopt.experiments.shadow_report import _internal_destination, write_document_once
from squadopt.scenarios import ScenarioError
from squadopt.scenarios.selection import PHASE_E_CANDIDATE_COUNTS


@dataclass(frozen=True, slots=True)
class PhaseERuntimeEvidence:
    """The verified probe bytes and the K derived from their measured records."""

    candidate_count: int
    sha256: str


def _object(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise PhaseEShadowError(f"{name} must be a JSON object.")
    return value


def _seconds(value: object, name: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, int | float)
        or not math.isfinite(value)
        or value < 0
    ):
        raise PhaseEShadowError(f"{name} must be a finite non-negative number.")
    return float(value)


def load_phase_e_runtime(
    path: Path, binding_evidence: PhaseDBindingEvidence
) -> PhaseERuntimeEvidence:
    """Recompute the existing E2 rule instead of trusting the artifact's frozen_k label."""

    payload = path.read_bytes()
    document = _object(json.loads(payload), "E2 artifact")
    binding._finite_numbers(document, "E2 artifact")
    expected_constants = {
        "candidate_counts": list(PHASE_E_CANDIDATE_COUNTS),
        "sensitivity_seeds": list(probe.SENSITIVITY_SEEDS),
        "budget_seconds": probe.BUDGET_SECONDS,
        "scenario_count": 1000,
        "risk_weight": 0.25,
        "tail_fraction": 0.10,
    }
    if (
        document.get("contract_version") != probe.PROBE_CONTRACT_VERSION
        or document.get("preregistration") != probe.PREREGISTRATION
        or document.get("preregistration_version") != probe.PREREGISTRATION_VERSION
        or document.get("diagnostic_only") is not True
        or document.get("promotes_anything") is not False
        or document.get("reads_realized_outcomes") is not False
        or document.get("outcome_policy") != probe.OUTCOME_POLICY
        or document.get("scoring_requested") is not True
        or document.get("constants") != expected_constants
    ):
        raise PhaseEShadowError(
            "E2 must use the frozen, outcome-free probe contract and constants."
        )
    if document.get("source") != {
        "table_sha256": binding.PHASE_C_TABLE_SHA256,
        "roster_sha256": binding.PHASE_C_ROSTER_SHA256,
        "manifest_sha256": binding.PHASE_C_MANIFEST_SHA256,
    }:
        raise PhaseEShadowError("E2 source must match the binding run's frozen Phase C inputs.")
    provenance = _object(document.get("provenance"), "E2 provenance")
    if provenance.get("working_tree_dirty") is not False or not provenance.get("repository_commit"):
        raise PhaseEShadowError("E2 must name a clean producer repository revision.")
    points = document.get("decision_points")
    if not isinstance(points, list) or len(points) != len(binding_evidence.fold_ids) + 3:
        raise PhaseEShadowError("E2 must contain the complete binding and live pool population.")
    for value in points:
        point = _object(value, "E2 decision point")
        if point.get("kind") not in ("live", "fold") or not isinstance(point.get("label"), str):
            raise PhaseEShadowError("E2 decision points need recognized kinds and labels.")
        historical = point["kind"] == "fold"
        if historical and (
            point.get("draw_available") is not True
            or point.get("draw_unavailable_reason") is not None
        ):
            raise PhaseEShadowError(
                "Every historical E2 fold needs measured scenario scoring before K can freeze."
            )
        if not isinstance(point.get("draw_available"), bool):
            raise PhaseEShadowError("E2 draw availability must be a measured boolean.")
        runs = point.get("runs")
        if not isinstance(runs, list) or len(runs) != 3:
            raise PhaseEShadowError(
                "Every E2 pool must contain exactly three candidate-count runs."
            )
        for value in runs:
            run = _object(value, "E2 run")
            if (
                type(run.get("candidate_count")) is not int
                or run["candidate_count"] not in PHASE_E_CANDIDATE_COUNTS
            ):
                raise PhaseEShadowError("E2 run candidate counts must be 4, 8 or 16.")
            for key in ("complete", "all_optimal", "generation_repeat_identical"):
                if not isinstance(run.get(key), bool):
                    raise PhaseEShadowError(f"E2 {key} must be a measured boolean.")
            generation = _seconds(run.get("generation_seconds"), "generation_seconds")
            _seconds(run.get("generation_seconds_repeat"), "generation_seconds_repeat")
            if not historical and run.get("scoring") is None:
                if (
                    not isinstance(run.get("scoring_unavailable_reason"), str)
                    or not run["scoring_unavailable_reason"]
                    or run.get("budget_seconds") is not None
                    or run.get("within_budget") is not None
                    or (not point["draw_available"] and not point.get("draw_unavailable_reason"))
                ):
                    raise PhaseEShadowError(
                        "Unscored live diagnostics need a reason and unknown scoring budget."
                    )
            else:
                if not point["draw_available"] or point.get("draw_unavailable_reason") is not None:
                    raise PhaseEShadowError("E2 scoring contradicts draw availability.")
                scoring = _object(run.get("scoring"), "E2 scoring")
                draw = _object(scoring.get("draw"), "E2 draw")
                if draw.get("scenario_count") != 1000 or draw.get("deterministic_seed") != 0:
                    raise PhaseEShadowError("E2 draws must use N=1000 and seed 0.")
                for key in ("draw_repeat_identical", "selection_repeat_identical"):
                    if not isinstance(scoring.get(key), bool):
                        raise PhaseEShadowError(f"E2 {key} must be a measured boolean.")
                total = generation + _seconds(
                    scoring.get("scoring_seconds_total"), "scoring_seconds_total"
                )
                if not math.isclose(
                    total, _seconds(run.get("budget_seconds"), "budget_seconds"), abs_tol=1e-9
                ):
                    raise PhaseEShadowError(
                        "E2 budget must equal measured generation plus scoring time."
                    )
                if not isinstance(run.get("within_budget"), bool) or run["within_budget"] != (
                    total <= probe.BUDGET_SECONDS
                ):
                    raise PhaseEShadowError(
                        "E2 within_budget contradicts the measured 120-second budget."
                    )
            candidates = run.get("candidates")
            if not historical and candidates == []:
                if (
                    run["complete"]
                    or run["all_optimal"]
                    or run.get("candidates_found") != 0
                    or run.get("termination_status") not in ("INFEASIBLE", "UNKNOWN")
                    or run.get("scoring") is not None
                ):
                    raise PhaseEShadowError(
                        "Unsolved live control needs consistent failure evidence."
                    )
                continue
            if (
                not isinstance(candidates, list)
                or not 0 < len(candidates) <= run["candidate_count"]
            ):
                raise PhaseEShadowError("E2 candidate records are missing or exceed requested K.")
            statuses = [
                _object(candidate, "E2 candidate").get("solver_status") for candidate in candidates
            ]
            complete = all(status == "OPTIMAL" for status in statuses) and (
                (
                    len(candidates) == run["candidate_count"]
                    and run.get("termination_status") == "OPTIMAL"
                )
                or (
                    len(candidates) < run["candidate_count"]
                    and run.get("termination_status") == "INFEASIBLE"
                )
            )
            if run["complete"] != complete:
                raise PhaseEShadowError("E2 completeness contradicts its count or terminal solve.")
            signatures = set()
            for rank, candidate in enumerate(candidates):
                squad, eleven = candidate.get("squad_ids"), candidate.get("eleven_ids")
                captain = candidate.get("captain_id")
                if (
                    type(candidate.get("rank")) is not int
                    or candidate["rank"] != rank
                    or not isinstance(squad, list)
                    or not isinstance(eleven, list)
                    or not all(
                        isinstance(identifier, str) and identifier for identifier in squad + eleven
                    )
                    or len(squad) != 15
                    or len(set(squad)) != 15
                    or len(eleven) != 11
                    or len(set(eleven)) != 11
                    or not set(eleven) <= set(squad)
                    or not isinstance(captain, str)
                    or captain not in eleven
                ):
                    raise PhaseEShadowError("E2 candidates need ranked, complete legal identities.")
                signature = (tuple(sorted(squad)), tuple(sorted(eleven)), captain)
                if signature in signatures:
                    raise PhaseEShadowError("E2 contains duplicate complete decisions.")
                signatures.add(signature)
            proven = run["complete"] and all(status == "OPTIMAL" for status in statuses)
            if run.get("candidates_found") != len(candidates) or run["all_optimal"] != proven:
                raise PhaseEShadowError("E2 optimality flags contradict candidate records.")
    rule = probe.candidate_count_rule(
        points, PHASE_E_CANDIDATE_COUNTS, expected_fold_ids=binding_evidence.fold_ids
    )
    recorded = _object(document.get("candidate_count_rule"), "E2 candidate-count rule")
    if recorded != rule or document.get("frozen_k") != rule["frozen_k"]:
        raise PhaseEShadowError("E2 frozen K or rule disagrees with its measured pool records.")
    frozen = rule["frozen_k"]
    if type(frozen) is not int or frozen not in PHASE_E_CANDIDATE_COUNTS:
        raise PhaseEShadowError(f"E2 has no usable frozen K: {rule['frozen_k_reason']}")
    return PhaseERuntimeEvidence(frozen, hashlib.sha256(payload).hexdigest())


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("binding", "runtime-probe", "table", "roster", "manifest", "json-output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--archive-root", type=Path, default=DEFAULT_ARCHIVE_ROOT)
    arguments = parser.parse_args(argv)
    started = datetime.now(UTC)
    try:
        # These gates precede all historical data access and cannot be bypassed by a K flag.
        evidence = load_phase_d_binding(arguments.binding)
        runtime = load_phase_e_runtime(arguments.runtime_probe, evidence)
        destination = _internal_destination(arguments.json_output, "E3 artifacts")
        if destination.exists():
            raise PhaseEShadowError(
                "E3 output already exists; an existing measurement is never replaced."
            )
        metadata = artifact_metadata(panel_rows=0, history_seasons=binding.HISTORY_SEASONS)
        initial_provenance = _object(metadata["provenance"], "repository provenance")
        if initial_provenance["working_tree_dirty"]:
            raise PhaseEShadowError("Commit working-tree changes before measuring E3.")
        handoff = read_phase_c_component_handoff(
            arguments.table, arguments.roster, arguments.manifest
        )
        folds, panel_rows = prepare_phase_e_folds(handoff, evidence, arguments.archive_root)
        measured = evaluate_phase_e_prepared_folds(
            handoff, folds, evidence, frozen_candidate_count=runtime.candidate_count
        )
        metadata = artifact_metadata(panel_rows=panel_rows, history_seasons=binding.HISTORY_SEASONS)
        final_provenance = _object(metadata["provenance"], "repository provenance")
        if (
            final_provenance["working_tree_dirty"]
            or final_provenance["repository_commit"] != initial_provenance["repository_commit"]
        ):
            raise PhaseEShadowError(
                "Repository changed during E3; measurement will not be written."
            )
        finished = datetime.now(UTC)
        document = {
            "contract_version": PHASE_E_SHADOW_CONTRACT,
            "prereg_document": probe.PREREGISTRATION,
            "preregistration_version": probe.PREREGISTRATION_VERSION,
            "internal_only": True,
            "operational_control_changed": False,
            "member_facing_probability_published": False,
            "locked_holdout_accessed": False,
            "runtime_probe_sha256": runtime.sha256,
            "source": {
                "table_sha256": handoff.table_sha256,
                "roster_sha256": handoff.roster_sha256,
                "manifest_sha256": handoff.manifest_sha256,
            },
            "execution": {
                "started_at_utc": started.isoformat(),
                "completed_at_utc": finished.isoformat(),
                "elapsed_seconds": (finished - started).total_seconds(),
            },
            **metadata,
            **measured,
        }
        outcome = write_document_once(document, destination)
    except (DataError, EvaluationError, ScenarioError, ValueError, OSError) as error:
        print(f"E3 refused: {error}", file=sys.stderr)
        return 1
    print(f"Wrote {arguments.json_output} ({outcome})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
