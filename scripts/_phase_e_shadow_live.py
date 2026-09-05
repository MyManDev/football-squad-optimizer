"""Artifact-gated prospective E4 diagnostics, using the existing E2 measurement path."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from time import perf_counter
from typing import Any

import pandas as pd
from scripts import probe_phase_e_runtime as probe
from scripts import run_component_squad_calibration as calibration
from scripts._phase_e_inputs import PhaseDBindingEvidence, load_phase_d_binding
from scripts._phase_e_live import live_component_decision
from scripts.run_phase_e_shadow import PhaseERuntimeEvidence, load_phase_e_runtime

from squadopt.data.snapshots import CapturedSnapshot
from squadopt.evaluation import read_phase_c_component_handoff
from squadopt.experiments.phase_e_shadow import (
    PHASE_E_SHADOW_CONTRACT,
    PhaseEShadowCandidate,
    PhaseEShadowError,
    PhaseEShadowFold,
    evaluate_phase_e_shadow,
)
from squadopt.live import Projection, read_projection_handoff


def load_shadow_eligibility(
    path: Path, binding: PhaseDBindingEvidence, runtime: PhaseERuntimeEvidence
) -> str:
    """Recompute the E3 verdict from every recorded fold, including fallbacks."""
    payload = path.read_bytes()
    try:
        document = json.loads(payload)
        if (
            binding.status != "calibrated_internal"
            or document["contract_version"] != PHASE_E_SHADOW_CONTRACT
            or document["preregistration_version"] != probe.PREREGISTRATION_VERSION
            or document["prereg_document"] != probe.PREREGISTRATION
            or document["binding_artifact_sha256"] != binding.sha256
            or document["runtime_probe_sha256"] != runtime.sha256
            or document["frozen_candidate_count"] != runtime.candidate_count
            or document["internal_only"] is not True
            or document["operational_control_changed"] is not False
            or document["locked_holdout_accessed"] is not False
            or document["provenance"]["working_tree_dirty"] is not False
            or not document["provenance"]["repository_commit"]
            or document["source"]
            != {
                "table_sha256": calibration.PHASE_C_TABLE_SHA256,
                "roster_sha256": calibration.PHASE_C_ROSTER_SHA256,
                "manifest_sha256": calibration.PHASE_C_MANIFEST_SHA256,
            }
        ):
            raise PhaseEShadowError(
                "E4 requires clean E3 evidence bound to these Phase D/E2 artifacts."
            )
        folds = []
        for record in document["folds"]:
            if (
                any(
                    type(record[name]) is not bool
                    for name in (
                        "candidate_set_complete",
                        "squad_changed",
                        "eleven_changed",
                        "captain_changed",
                        "formation_changed",
                    )
                )
                or type(record["selected_rank"]) is not int
            ):
                raise PhaseEShadowError(
                    "E3 fold flags and ranks must retain their measured JSON types."
                )
            candidates = tuple(
                PhaseEShadowCandidate(
                    **{
                        **candidate,
                        "squad_ids": tuple(candidate["squad_ids"]),
                        "starting_ids": tuple(candidate["starting_ids"]),
                    }
                )
                for candidate in record["candidates"]
            )
            folds.append(PhaseEShadowFold(**{**record, "candidates": candidates}))
        verdict = evaluate_phase_e_shadow(
            folds, expected_fold_ids=binding.fold_ids, phase_d_status=binding.status
        )
        # JSON serializes interval tuples as lists; compare the actual serialized contract.
        if (
            verdict["status"] != "shadow_eligible"
            or json.loads(json.dumps(verdict, allow_nan=False)) != document["verdict"]
        ):
            raise PhaseEShadowError("E3 records do not prove the recorded shadow_eligible verdict.")
    except (KeyError, TypeError, AttributeError) as error:
        raise PhaseEShadowError("Malformed E3 eligibility evidence.") from error
    return hashlib.sha256(payload).hexdigest()


def prospective_readiness(run: dict[str, Any], candidate_count: int) -> bool:
    """Historical K alone never proves readiness on the prospective capture."""
    scoring = run.get("scoring")
    if not isinstance(scoring, dict):
        return False
    return (
        run.get("candidate_count") == candidate_count
        and run.get("complete") is True
        and run.get("all_optimal") is True
        and run.get("generation_repeat_identical") is True
        and run.get("within_budget") is True
        and scoring.get("draw_repeat_identical") is True
        and scoring.get("selection_repeat_identical") is True
        and scoring.get("control_covered") is True
        and scoring.get("candidates_covered", 0) >= 2
        and scoring.get("selector_probe_pin", {}).get("status") == "SELECTED"
    )


def make_live_shadow_hook(
    *,
    binding_path: Path,
    runtime_path: Path,
    shadow_path: Path,
    table_path: Path,
    roster_path: Path,
    manifest_path: Path,
    projection_path: Path,
    archive_root: Path,
) -> Callable[[CapturedSnapshot, Projection], dict[str, object]]:
    """Prepare an explicitly requested hook; nothing installs it in the default live path."""
    binding = load_phase_d_binding(binding_path)
    runtime = load_phase_e_runtime(runtime_path, binding)
    shadow_sha = load_shadow_eligibility(shadow_path, binding, runtime)
    handoff = read_phase_c_component_handoff(table_path, roster_path, manifest_path)
    frozen_projection = read_projection_handoff(projection_path)
    if frozen_projection.season != "2026-27" or frozen_projection.gameweek < 4:
        raise PhaseEShadowError(
            "Prospective E4 starts after the three original diagnostic gameweeks."
        )

    def measure(capture: CapturedSnapshot, projection: Projection) -> dict[str, object]:
        started = perf_counter()
        point = live_component_decision(
            capture, frozen_projection, handoff, archive_root, binding_evidence=binding
        )
        pd.testing.assert_frame_equal(
            point.pool.reset_index(drop=True),
            projection.table.loc[:, list(probe.POOL_COLUMNS)].reset_index(drop=True),
        )
        record = probe.probe_decision_point(
            point, candidate_counts=(runtime.candidate_count,), sensitivity_seeds=(), scoring=True
        )
        run = record["runs"][0]
        ready = prospective_readiness(run, runtime.candidate_count)
        selected = (
            run["scoring"]["selector_probe_pin"]["selected_candidate_rank"] if ready else None
        )
        return {
            "contract_version": "phase_e_live_shadow_v1",
            "status": "SHADOW_RECORDED" if ready else "NOT_READY",
            "internal_only": True,
            "published_decision_changed": False,
            "comparison_scope": "full_pool_squad_diagnostic",
            "is_transfer_alternative": False,
            "binding_artifact_sha256": binding.sha256,
            "runtime_probe_sha256": runtime.sha256,
            "shadow_evaluation_sha256": shadow_sha,
            "frozen_candidate_count": runtime.candidate_count,
            "prospective_ready": ready,
            "selected_candidate_rank": selected,
            "prospective_probe": record,
            "wall_clock_seconds": perf_counter() - started,
        }

    return measure
