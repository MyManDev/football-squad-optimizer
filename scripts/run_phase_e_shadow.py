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
    load_phase_d_candidate,
    load_phase_d_development,
    prepare_phase_e_folds,
)

from squadopt.data import DataError
from squadopt.evaluation import EvaluationError, read_phase_c_component_handoff
from squadopt.experiments.phase_e_shadow import (
    PHASE_E_SHADOW_CONTRACT,
    PHASE_E_SHADOW_DEVELOPMENT_CONTRACT,
    PHASE_E_SHADOW_DEVELOPMENT_V2_CONTRACT,
    PhaseEShadowError,
)
from squadopt.experiments.shadow_report import _internal_destination, write_document_once
from squadopt.scenarios import ScenarioError
from squadopt.scenarios.components import ConditionalResidualConfig
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
    path: Path,
    binding_evidence: PhaseDBindingEvidence,
    *,
    conditional_residuals: ConditionalResidualConfig | None = None,
) -> PhaseERuntimeEvidence:
    """Recompute the existing E2 rule instead of trusting the artifact's frozen_k label.

    The artifact must have been probed under the same sampler the E3 run draws with: a
    foundation probe carries the binding contract, a candidate-sampler probe the development
    contract and a matching sampler block, and every scored historical draw declares it.
    """

    payload = path.read_bytes()
    document = _object(json.loads(payload), "E2 artifact")
    binding._finite_numbers(document, "E2 artifact")
    expected_sampler = probe.sampler_record(conditional_residuals)
    v2 = binding_evidence.development_contract is not None
    expected_contract = (
        probe.DEVELOPMENT_V2_PROBE_CONTRACT_VERSION
        if v2
        else probe.probe_contract_version(conditional_residuals)
    )
    if (
        document.get("contract_version") != expected_contract
        or document.get("sampler", probe.sampler_record(None)) != expected_sampler
        or document.get("development_only", False) is not (conditional_residuals is not None)
    ):
        raise PhaseEShadowError(
            "E2 must have been probed under the sampler this E3 run draws with, under that "
            "sampler's own probe contract."
        )
    expected_constants = {
        "candidate_counts": list(PHASE_E_CANDIDATE_COUNTS),
        "sensitivity_seeds": list(probe.SENSITIVITY_SEEDS),
        "budget_seconds": probe.BUDGET_SECONDS,
        "scenario_count": 1000,
        "risk_weight": 0.25,
        "tail_fraction": 0.10,
    }
    if (
        document.get("preregistration") != probe.PREREGISTRATION
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
    expected_source = (
        binding_evidence.phase_c_source
        if v2
        else {
            "table_sha256": binding.PHASE_C_TABLE_SHA256,
            "roster_sha256": binding.PHASE_C_ROSTER_SHA256,
            "manifest_sha256": binding.PHASE_C_MANIFEST_SHA256,
        }
    )
    if document.get("source") != expected_source:
        raise PhaseEShadowError("E2 source must match the binding run's frozen Phase C inputs.")
    if v2:
        population = _object(document.get("population"), "E2 v2 population")
        if (
            document.get("phase_c_contract") != "development_v2"
            or document.get("binding") is not False
            or document.get("measured_fold_ids") != list(binding_evidence.fold_ids)
            or population.get("eligibility_complete") is not True
            or population.get("eligible_fold_ids") != list(binding_evidence.fold_ids)
            or population.get("history_eligible_fold_ids")
            != list(binding_evidence.history_eligible_fold_ids)
            or population.get("history_burn_in_fold_ids")
            != list(binding_evidence.history_burn_in_fold_ids)
            or population.get("direct_control_abstentions")
            != list(binding_evidence.direct_control_fold_ids)
            or population.get("all_fold_ids")
            != sorted(
                (
                    *binding_evidence.history_burn_in_fold_ids,
                    *binding_evidence.history_eligible_fold_ids,
                )
            )
        ):
            raise PhaseEShadowError(
                "E2 v2 must cover the complete Phase D v2 population, not a pilot."
            )
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
                declared = draw.get(
                    "component_sampler_contract_version", probe.COMPONENT_SCENARIO_CONTRACT_VERSION
                )
                if declared != expected_sampler["contract_version"]:
                    raise PhaseEShadowError("An E2 draw was not made with the requested sampler.")
                if (
                    v2
                    and historical
                    and draw.get("development_contract") != binding_evidence.development_contract
                ):
                    raise PhaseEShadowError(
                        "An E2 draw does not name the Phase D v2 development scope."
                    )
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
        points,
        PHASE_E_CANDIDATE_COUNTS,
        expected_fold_ids=binding_evidence.fold_ids,
        **({"phase_c_contract": "development_v2"} if v2 else {}),
    )
    recorded = _object(document.get("candidate_count_rule"), "E2 candidate-count rule")
    if recorded != rule or document.get("frozen_k") != rule["frozen_k"]:
        raise PhaseEShadowError("E2 frozen K or rule disagrees with its measured pool records.")
    frozen = rule["frozen_k"]
    if type(frozen) is not int or frozen not in PHASE_E_CANDIDATE_COUNTS:
        raise PhaseEShadowError(f"E2 has no usable frozen K: {rule['frozen_k_reason']}")
    return PhaseERuntimeEvidence(frozen, hashlib.sha256(payload).hexdigest())


def _parse_arguments(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("runtime-probe", "table", "roster", "manifest", "json-output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--binding", type=Path, help="binding Phase D artifact (foundation)")
    parser.add_argument(
        "--phase-d-candidate",
        type=Path,
        help="candidate Phase D artifact (binding: false) for a development sampler run",
    )
    parser.add_argument("--archive-root", type=Path, default=DEFAULT_ARCHIVE_ROOT)
    parser.add_argument("--phase-c-contract", choices=binding.PHASE_C_CONTRACTS, default="v1")
    parser.add_argument(
        "--phase-d-development", type=Path, help="complete Phase D v2 development evidence"
    )
    for name in ("expected-table-sha256", "expected-roster-sha256", "expected-manifest-sha256"):
        parser.add_argument(f"--{name}")
    parser.add_argument(
        "--sampler",
        choices=probe.SAMPLER_CHOICES,
        default="foundation",
        help="the component sampler every E3 draw uses; conditional is development only",
    )
    parser.add_argument("--conditional-residual-fraction", type=float, default=None)
    parser.add_argument("--conditional-residual-minimum-rows", type=int, default=None)
    return parser.parse_args(argv)


def _evidence(
    arguments: argparse.Namespace, conditional_residuals: ConditionalResidualConfig | None
) -> PhaseDBindingEvidence:
    """Binding evidence for the foundation sampler; candidate evidence for a candidate one."""

    if arguments.phase_c_contract == "development_v2":
        if (
            conditional_residuals is None
            or arguments.phase_d_development is None
            or arguments.binding is not None
            or arguments.phase_d_candidate is not None
        ):
            raise PhaseEShadowError(
                "E3 v2 requires --phase-d-development and the conditional sampler only."
            )
        development = binding._development_from_arguments(arguments)
        assert development is not None
        return load_phase_d_development(
            arguments.phase_d_development,
            development=development,
            conditional_residuals=conditional_residuals,
        )
    if arguments.phase_d_development is not None or any(
        getattr(arguments, name) is not None
        for name in ("expected_table_sha256", "expected_roster_sha256", "expected_manifest_sha256")
    ):
        raise PhaseEShadowError(
            "V2 evidence and input digest flags require --phase-c-contract development_v2."
        )
    if conditional_residuals is None:
        if arguments.binding is None or arguments.phase_d_candidate is not None:
            raise PhaseEShadowError(
                "A foundation E3 run reads --binding and never a --phase-d-candidate artifact."
            )
        return load_phase_d_binding(arguments.binding)
    if arguments.phase_d_candidate is None or arguments.binding is not None:
        raise PhaseEShadowError(
            "A development E3 run reads --phase-d-candidate and never the --binding artifact."
        )
    return load_phase_d_candidate(
        arguments.phase_d_candidate, conditional_residuals=conditional_residuals
    )


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parse_arguments(argv)
    started = datetime.now(UTC)
    try:
        conditional_residuals = probe.conditional_from_arguments(
            arguments.sampler,
            arguments.conditional_residual_fraction,
            arguments.conditional_residual_minimum_rows,
        )
        # These gates precede all historical data access and cannot be bypassed by a K flag.
        evidence = _evidence(arguments, conditional_residuals)
        if evidence.development_contract is not None and evidence.status != "calibrated_internal":
            raise PhaseEShadowError("Phase D v2 did not pass its development calibration gates.")
        runtime = load_phase_e_runtime(
            arguments.runtime_probe, evidence, conditional_residuals=conditional_residuals
        )
        destination = _internal_destination(arguments.json_output, "E3 artifacts")
        if destination.exists():
            raise PhaseEShadowError(
                "E3 output already exists; an existing measurement is never replaced."
            )
        history_seasons = evidence.history_seasons or binding.HISTORY_SEASONS
        metadata = artifact_metadata(panel_rows=0, history_seasons=history_seasons)
        initial_provenance = _object(metadata["provenance"], "repository provenance")
        if initial_provenance["working_tree_dirty"]:
            raise PhaseEShadowError("Commit working-tree changes before measuring E3.")
        handoff = (
            binding._read_handoff(arguments, binding._development_from_arguments(arguments))
            if evidence.development_contract is not None
            else read_phase_c_component_handoff(
                arguments.table, arguments.roster, arguments.manifest
            )
        )
        folds, panel_rows = prepare_phase_e_folds(handoff, evidence, arguments.archive_root)
        measured = evaluate_phase_e_prepared_folds(
            handoff,
            folds,
            evidence,
            frozen_candidate_count=runtime.candidate_count,
            conditional_residuals=conditional_residuals,
        )
        metadata = artifact_metadata(panel_rows=panel_rows, history_seasons=history_seasons)
        final_provenance = _object(metadata["provenance"], "repository provenance")
        if (
            final_provenance["working_tree_dirty"]
            or final_provenance["repository_commit"] != initial_provenance["repository_commit"]
        ):
            raise PhaseEShadowError(
                "Repository changed during E3; measurement will not be written."
            )
        finished = datetime.now(UTC)
        development = conditional_residuals is not None
        v2 = evidence.development_contract is not None
        document = {
            "contract_version": (
                PHASE_E_SHADOW_DEVELOPMENT_V2_CONTRACT
                if v2
                else PHASE_E_SHADOW_DEVELOPMENT_CONTRACT
                if development
                else PHASE_E_SHADOW_CONTRACT
            ),
            "prereg_document": probe.PREREGISTRATION,
            "preregistration_version": probe.PREREGISTRATION_VERSION,
            "internal_only": True,
            "binding": not development,
            "development_only": development,
            "e4_permitted": False if development else None,
            "sampler": probe.sampler_record(conditional_residuals),
            "phase_d_evidence": {
                "contract_version": (
                    binding.DEVELOPMENT_REPORT_VERSION
                    if v2
                    else binding.CANDIDATE_REPORT_VERSION
                    if development
                    else binding.REPORT_VERSION
                ),
                "binding": evidence.binding,
                "status": evidence.status,
                "sha256": evidence.sha256,
                "sampler_contract_version": evidence.sampler_contract_version,
            },
            "operational_control_changed": False,
            "member_facing_probability_published": False,
            "locked_holdout_accessed": v2 and "2025-26" in history_seasons,
            "runtime_probe_sha256": runtime.sha256,
            "source": evidence.phase_c_source
            if v2
            else {
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
