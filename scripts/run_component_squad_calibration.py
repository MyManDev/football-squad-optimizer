"""Run the preregistered Phase D component-squad calibration once.

The command freezes each Phase C decision on the complete player pool before checking
scenario eligibility. It then simulates only the selected squad, scores every draw with
official autosub/captain rules, and evaluates the frozen S1/S2 gates. The result is internal
calibration evidence; it does not change the operational model or publish probabilities.

**Phase D v2 development mode.** ``--phase-c-contract development_v2`` reads the Phase C v2
development handoff (the equal-weight A reference, pinned by its three digests) instead of
the frozen v1 artifact, admits its 2025-26 decisions, and writes the distinct
``phase_d_component_squad_calibration_development_v2`` document with ``binding: false``. Its
population is computed from the handoff under the preregistered eligibility rule rather than
asserted against the frozen 137, no v2 fidelity artifact exists yet so the S1/S2 verdict
abstains by protocol while the readings are reported as development observations, and
``--folds`` restricts the measured folds for a pilot. The v1 binding path is unchanged.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
import warnings
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Final, cast

import pandas as pd
from scripts._experiment_cli import DEFAULT_ARCHIVE_ROOT, REPOSITORY_ROOT, artifact_metadata

from squadopt.backtest import (
    BacktestConfigurationError,
    build_walk_forward_folds,
    make_ridge_projection_builder,
)
from squadopt.data import DataError
from squadopt.data.sources.vaastav import build_panel
from squadopt.evaluation import (
    DEVELOPMENT_OOF_CONTRACT_VERSION,
    EvaluationConfig,
    EvaluationError,
    EvaluationFold,
    ScoringPolicy,
    evaluate_prepared_folds,
    prepare_phase_c_component_folds,
    read_phase_c_component_handoff,
)
from squadopt.evaluation.component_handoff import PhaseCComponentHandoff
from squadopt.experiments import (
    COMPONENT_SQUAD_CALIBRATION_CONTRACT_VERSION,
    ComponentCalibrationFold,
    ComponentSquadCalibrationError,
    evaluate_component_squad_calibration,
)
from squadopt.experiments.component_squad_calibration import (
    MIN_CALIBRATION_FOLDS,
    S1_PIT_BOUNDS,
    S2_LOWER_TAIL_BOUNDS,
)
from squadopt.experiments.shadow_report import ShadowReportError, write_document_once
from squadopt.features import CrossSeasonConfig
from squadopt.optimization import OptimizationConfig, OptimizationResult, decision_signature
from squadopt.prediction import (
    PredictionProvenance,
    PredictionSnapshot,
    prepare_optimizer_projection,
)
from squadopt.prediction.component_models import COMPONENT_MODEL_VERSION, EQUAL_WEIGHTING
from squadopt.prediction.components import COMPONENT_MODEL_ROUTE, DIRECT_CONTROL_ROUTE
from squadopt.scenarios import (
    ScenarioConfig,
    ScenarioError,
    ScenarioTarget,
    score_component_scenario_decision,
    summarize_component_decision_distribution,
)
from squadopt.scenarios.components import (
    ComponentScenarioInputs,
    ComponentScenarioProvenance,
    ConditionalResidualConfig,
    paired_conditional_residuals,
    sample_component_scenarios,
)

REPORT_VERSION: Final = "phase_d_component_squad_calibration_binding_v1"
FIDELITY_VERSION: Final = "phase_d_component_fidelity_v1"
HISTORY_SEASONS: Final = (
    "2020-21",
    "2021-22",
    "2022-23",
    "2023-24",
    "2024-25",
)
DECISION_SEASONS: Final = HISTORY_SEASONS[1:]
LOCKED_HOLDOUT_SEASON: Final = "2025-26"
FULL_FOLD_COUNT: Final = 147
BINDING_FOLD_COUNT: Final = 137
FIRST_BINDING_FOLD: Final = "2021-22-gw11"
LAST_BINDING_FOLD: Final = "2024-25-gw38"
HISTORY_BURN_IN_FOLDS: Final = tuple(f"2021-22-gw{gameweek:02d}" for gameweek in range(2, 11))
DIRECT_CONTROL_ABSTENTIONS: Final = ("2021-22-gw15",)
PHASE_C_TABLE_SHA256: Final = "b05f10c3fd3ab5058fe1ff720cc6ef0a4b1362a70a19dd979ad0eb0f47d12c01"
PHASE_C_ROSTER_SHA256: Final = "3ef0c5717fa63c3c4772512f019cd750d3fae6cd9a7567d20dd4bfa24003678e"
PHASE_C_MANIFEST_SHA256: Final = "1a06b69abb3d7fe98afde6983885a9a7723463d351a2432dc9e0a11082f5eba8"
FIDELITY_ARTIFACT_SHA256: Final = "cba8dd297386a1305a6a8142121dccb80c3551cb585a6ae4c4e858f89e553fa9"
DEFAULT_OUTPUT: Final = REPOSITORY_ROOT / "docs" / "phase_d_component_squad_calibration.json"
# A candidate sampler run is a development measurement on the same population and gates,
# never the binding verdict: it carries its own contract version so nothing that requires
# the binding artifact can read it as one.
CANDIDATE_REPORT_VERSION: Final = "phase_d_component_squad_calibration_candidate_v1"
# The Phase D v2 development reading of the Phase C v2 equal-weight A reference. Its own
# contract, `binding: false`, and an honest `locked_holdout_accessed: true`: 2025-26 is read
# as development data there and is never an unseen test.
DEVELOPMENT_REPORT_VERSION: Final = "phase_d_component_squad_calibration_development_v2"
PHASE_C_CONTRACTS: Final = ("v1", "development_v2")
DEVELOPMENT_HISTORY_SEASONS: Final = (*HISTORY_SEASONS, LOCKED_HOLDOUT_SEASON)
_DIGEST: Final = r"[0-9a-f]{64}"


class BindingCalibrationError(ValueError):
    """Raised when the binding population or provenance differs from the preregistration."""


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--table", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--roster", type=Path, required=True)
    # Required under the v1 binding contract, checked in `_development_from_arguments`;
    # refused under development_v2, which has no fidelity contract yet.
    parser.add_argument("--fidelity", type=Path, default=None)
    parser.add_argument("--archive-root", type=Path, default=DEFAULT_ARCHIVE_ROOT)
    parser.add_argument("--json-output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--phase-c-contract", choices=PHASE_C_CONTRACTS, default="v1")
    parser.add_argument("--expected-table-sha256", default=None)
    parser.add_argument("--expected-roster-sha256", default=None)
    parser.add_argument("--expected-manifest-sha256", default=None)
    parser.add_argument(
        "--folds",
        default=None,
        help="development_v2 only: comma-separated fold ids to measure (a pilot); eligibility "
        "is still computed for the whole handoff",
    )
    parser.add_argument(
        "--conditional-residual-fraction",
        type=float,
        default=None,
        help="candidate sampler: fraction of a source fold's rows a player may draw from",
    )
    parser.add_argument(
        "--conditional-residual-minimum-rows",
        type=int,
        default=None,
        help="candidate sampler: the smallest such window, whole fold when the fold is smaller",
    )
    return parser.parse_args()


def _candidate_from_arguments(arguments: argparse.Namespace) -> ConditionalResidualConfig | None:
    """The candidate sampler the arguments ask for, or None for the frozen binding sampler."""

    fraction = arguments.conditional_residual_fraction
    minimum_rows = arguments.conditional_residual_minimum_rows
    if fraction is None and minimum_rows is None:
        return None
    if fraction is None or minimum_rows is None:
        raise BindingCalibrationError(
            "A candidate run needs both --conditional-residual-fraction and "
            "--conditional-residual-minimum-rows."
        )
    if Path(arguments.json_output).resolve() == DEFAULT_OUTPUT.resolve():
        raise BindingCalibrationError(
            "A candidate run cannot write the binding artifact path; give --json-output."
        )
    return ConditionalResidualConfig(fraction=fraction, minimum_rows=minimum_rows)


def _report_contract_version(
    candidate: ConditionalResidualConfig | None, development: DevelopmentInputs | None = None
) -> str:
    if development is not None:
        return DEVELOPMENT_REPORT_VERSION
    return REPORT_VERSION if candidate is None else CANDIDATE_REPORT_VERSION


@dataclass(frozen=True, slots=True)
class DevelopmentInputs:
    """What one development_v2 run is pinned to: the exact A artifacts and, for a pilot, folds."""

    table_sha256: str
    roster_sha256: str
    manifest_sha256: str
    folds: tuple[str, ...] | None


def _development_from_arguments(arguments: argparse.Namespace) -> DevelopmentInputs | None:
    """The development_v2 binding the arguments ask for, or None for the v1 binding contract.

    Under v1 nothing changes: the fidelity artifact stays required. Under development_v2 the
    three A digests are required so the run cannot silently bind to another export (the
    season-weighted B arm shares the roster digest and differs only in its table), the
    fidelity artifact is refused because no v2 fidelity contract exists, and the output path
    can never be the binding artifact's.
    """

    contract = str(getattr(arguments, "phase_c_contract", "v1"))
    if contract == "v1":
        if getattr(arguments, "fidelity", None) is None:
            raise BindingCalibrationError("--fidelity is required under the v1 binding contract.")
        for name in ("expected_table_sha256", "expected_roster_sha256", "expected_manifest_sha256"):
            if getattr(arguments, name, None) is not None:
                raise BindingCalibrationError(
                    f"--{name.replace('_', '-')} applies to --phase-c-contract development_v2 only."
                )
        if getattr(arguments, "folds", None) is not None:
            raise BindingCalibrationError(
                "--folds applies to --phase-c-contract development_v2 only."
            )
        return None
    if contract != "development_v2":
        raise BindingCalibrationError(f"Unknown Phase C contract {contract!r}.")
    if getattr(arguments, "fidelity", None) is not None:
        raise BindingCalibrationError(
            "No Phase D fidelity contract exists for the v2 development handoff; the "
            "development reading abstains from a verdict by protocol. Drop --fidelity."
        )
    digests: dict[str, str] = {}
    for name in ("expected_table_sha256", "expected_roster_sha256", "expected_manifest_sha256"):
        value = getattr(arguments, name, None)
        if not isinstance(value, str) or re.fullmatch(_DIGEST, value) is None:
            raise BindingCalibrationError(
                f"--{name.replace('_', '-')} must pin the A reference with a 64-hex SHA-256 "
                "under --phase-c-contract development_v2."
            )
        digests[name] = value
    if Path(arguments.json_output).resolve() == DEFAULT_OUTPUT.resolve():
        raise BindingCalibrationError(
            "A development_v2 run cannot write the binding artifact path; give --json-output."
        )
    raw_folds = getattr(arguments, "folds", None)
    folds: tuple[str, ...] | None = None
    if raw_folds is not None:
        folds = tuple(item.strip() for item in str(raw_folds).split(",") if item.strip())
        if not folds or len(set(folds)) != len(folds):
            raise BindingCalibrationError("--folds must list distinct fold ids.")
    return DevelopmentInputs(
        table_sha256=digests["expected_table_sha256"],
        roster_sha256=digests["expected_roster_sha256"],
        manifest_sha256=digests["expected_manifest_sha256"],
        folds=folds,
    )


def _read_handoff(
    arguments: argparse.Namespace, development: DevelopmentInputs | None
) -> PhaseCComponentHandoff:
    """Read the v1 handoff, or the pinned equal-weight A reference under development_v2."""

    if development is None:
        return read_phase_c_component_handoff(arguments.table, arguments.roster, arguments.manifest)
    handoff = read_phase_c_component_handoff(
        arguments.table,
        arguments.roster,
        arguments.manifest,
        development_contract=DEVELOPMENT_OOF_CONTRACT_VERSION,
    )
    if (
        handoff.table_sha256 != development.table_sha256
        or handoff.roster_sha256 != development.roster_sha256
        or handoff.manifest_sha256 != development.manifest_sha256
    ):
        raise BindingCalibrationError(
            "Phase C development handoff digests differ from the pinned A reference "
            f"(table {handoff.table_sha256[:12]}..., roster {handoff.roster_sha256[:12]}..., "
            f"manifest {handoff.manifest_sha256[:12]}...)."
        )
    if handoff.weighting != EQUAL_WEIGHTING or handoff.model_version != COMPONENT_MODEL_VERSION:
        raise BindingCalibrationError(
            "The development_v2 reading is bound to the equal-weight A reference; got "
            f"weighting {handoff.weighting!r} and model {handoff.model_version!r}."
        )
    return handoff


def _history_fold_ids(rows: pd.DataFrame) -> tuple[str, ...]:
    """Folds that contribute an appearance-observed component residual, in id order."""

    usable = (
        rows["composition_route"].astype("string").eq(COMPONENT_MODEL_ROUTE)
        & pd.to_numeric(rows["appearance_target"], errors="coerce").eq(1)
        & pd.to_numeric(rows["minutes_target"], errors="coerce").notna()
        & pd.to_numeric(rows["points_target"], errors="coerce").notna()
        & pd.to_numeric(rows["expected_minutes_if_appearance"], errors="coerce").notna()
        & pd.to_numeric(rows["raw_expected_points_if_appearance"], errors="coerce").notna()
    )
    return tuple(sorted({str(value) for value in rows.loc[usable, "fold_id"]}))


def _development_population(
    rows: pd.DataFrame,
    fold_ids: Sequence[str],
    *,
    min_history_folds: int,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Split the handoff's folds into history burn-in and history-eligible folds.

    The rule is the preregistration's first eligibility condition, computed from the inputs
    rather than asserted: a fold is history-eligible once at least ``min_history_folds``
    earlier folds contribute an appearance-observed component residual. The direct-control
    condition is applied afterwards, per fold, from the frozen full-pool decision.
    """

    ordered = tuple(fold_ids)
    if len(set(ordered)) != len(ordered):
        raise BindingCalibrationError("Phase C fold ids repeat.")
    history = _history_fold_ids(rows)
    burn_in: list[str] = []
    eligible: list[str] = []
    for fold_id in ordered:
        earlier = sum(1 for item in history if item < fold_id)
        (eligible if earlier >= min_history_folds else burn_in).append(fold_id)
    if eligible and burn_in and max(burn_in) > min(eligible):
        raise BindingCalibrationError("History eligibility is not monotone in fold order.")
    return tuple(burn_in), tuple(eligible)


def _development_observation(
    readings: Sequence[ComponentCalibrationFold],
) -> dict[str, object] | None:
    """The S1/S2 point readings as development observations, never as a verdict."""

    if not readings:
        return None
    pits = [float(item.readout.probability_integral_transform or 0.0) for item in readings]
    below = [bool(item.readout.realized_below_lower_quantile) for item in readings]
    mean_pit = sum(pits) / len(pits)
    tail_rate = sum(below) / len(below)
    return {
        "fold_count": len(readings),
        "mean_probability_integral_transform": mean_pit,
        "realized_below_lower_quantile_count": sum(below),
        "realized_below_lower_quantile_rate": tail_rate,
        "s1_bounds": list(S1_PIT_BOUNDS),
        "s2_bounds": list(S2_LOWER_TAIL_BOUNDS),
        "mean_pit_within_s1_bounds": S1_PIT_BOUNDS[0] <= mean_pit <= S1_PIT_BOUNDS[1],
        "tail_rate_within_s2_bounds": S2_LOWER_TAIL_BOUNDS[0]
        <= tail_rate
        <= S2_LOWER_TAIL_BOUNDS[1],
        "minimum_folds_for_a_verdict": MIN_CALIBRATION_FOLDS,
        "note": (
            "Development observation on the folds measured in this run. It is not a "
            "calibration verdict: the verdict abstains until a v2 sampler-fidelity artifact "
            "exists, and a pilot's folds are far too few to read."
        ),
    }


def _decision_identity(result: OptimizationResult) -> dict[str, object]:
    """The complete frozen decision, so a repeat under the fixed profile can be compared."""

    squad, starters, captain = decision_signature(result)
    bench_order = [int(value) for value in result.bench["player_id"]]
    payload = {
        "squad": list(squad),
        "starting_xi": list(starters),
        "captain": int(captain),
        "bench_order": bench_order,
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {**payload, "sha256": digest}


def _solver_profile() -> dict[str, object]:
    """The fixed optimization profile the walk-forward controls are solved under."""

    settings = OptimizationConfig()
    return {
        "solver_time_limit_seconds": settings.solver_time_limit_seconds,
        "solver_deterministic_time_limit": settings.solver_deterministic_time_limit,
        "deterministic_seed": settings.deterministic_seed,
        "num_search_workers": 1,
        "bench_weight": settings.bench_weight,
        "scoring_policy": ScoringPolicy.OFFICIAL_AUTOSUB_CAPTAIN_V2.value,
        "note": (
            "A wall-clock budget: a fold whose solve ends FEASIBLE may return a different "
            "decision on a repeat, and a repeat is expected to reproduce a fold only when "
            "its solve ends OPTIMAL. Neither is changed to pass a pilot."
        ),
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            while chunk := handle.read(1 << 20):
                digest.update(chunk)
    except OSError as error:
        raise BindingCalibrationError(f"Cannot read {path}: {error}") from error
    return digest.hexdigest()


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise BindingCalibrationError(f"{name} must be a JSON object.")
    return cast(Mapping[str, object], value)


def _string_list(value: object, name: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise BindingCalibrationError(f"{name} must be a JSON list of strings.")
    return tuple(cast(list[str], value))


def _finite_numbers(value: object, name: str = "fidelity") -> None:
    if isinstance(value, bool | str) or value is None:
        return
    if isinstance(value, int | float):
        if not math.isfinite(float(value)):
            raise BindingCalibrationError(f"{name} contains a non-finite number.")
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            _finite_numbers(item, f"{name}.{key}")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _finite_numbers(item, f"{name}[{index}]")
        return
    raise BindingCalibrationError(f"{name} contains a non-JSON value.")


def _load_verified_fidelity(path: Path, handoff: PhaseCComponentHandoff) -> str:
    """Validate the committed diagnostic structurally, without inventing a numeric gate."""

    if (
        handoff.table_sha256 != PHASE_C_TABLE_SHA256
        or handoff.roster_sha256 != PHASE_C_ROSTER_SHA256
        or handoff.manifest_sha256 != PHASE_C_MANIFEST_SHA256
    ):
        raise BindingCalibrationError("Phase C handoff is not the frozen binding artifact.")
    fidelity_digest = _sha256(path)
    if fidelity_digest != FIDELITY_ARTIFACT_SHA256:
        raise BindingCalibrationError("Fidelity artifact is not the committed binding record.")
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise BindingCalibrationError(f"Cannot read fidelity artifact {path}: {error}") from error
    fidelity = _mapping(document, "fidelity artifact")
    _finite_numbers(fidelity)
    if fidelity.get("contract_version") != FIDELITY_VERSION:
        raise BindingCalibrationError("Fidelity artifact uses an unsupported contract version.")
    if (
        fidelity.get("diagnostic_only") is not True
        or fidelity.get("promotes_anything") is not False
        or fidelity.get("registers_any_threshold") is not False
    ):
        raise BindingCalibrationError("Fidelity artifact changes its diagnostic-only meaning.")

    config = _mapping(fidelity.get("config"), "fidelity.config")
    expected_config = {
        "scenario_count": 1_000,
        "deterministic_seed": 0,
        "min_history_folds": 8,
    }
    if dict(config) != expected_config:
        raise BindingCalibrationError("Fidelity artifact does not use the frozen scenario config.")

    provenance = _mapping(fidelity.get("provenance"), "fidelity.provenance")
    if (
        provenance.get("working_tree_dirty") is not False
        or provenance.get("manifest_locked_holdout_read") is not False
        or provenance.get("manifest_table_sha256") != handoff.table_sha256
        or provenance.get("oof_table_sha256") != handoff.table_sha256
        or provenance.get("manifest_roster_sha256") != handoff.roster_sha256
        or provenance.get("roster_sha256") != handoff.roster_sha256
        or provenance.get("manifest_sha256") != handoff.manifest_sha256
        or provenance.get("model_version") != handoff.model_version
        or provenance.get("feature_contract_version") != handoff.feature_contract_version
    ):
        raise BindingCalibrationError("Fidelity artifact does not describe this Phase C handoff.")

    population = _mapping(fidelity.get("population"), "fidelity.population")
    measured_ids = _string_list(population.get("measured_fold_ids"), "measured_fold_ids")
    all_ids = tuple(str(value) for value in handoff.rows["fold_id"].drop_duplicates())
    expected_measured = all_ids[len(HISTORY_BURN_IN_FOLDS) :]
    if (
        population.get("fold_count_total") != FULL_FOLD_COUNT
        or population.get("fold_count_excluded") != len(HISTORY_BURN_IN_FOLDS)
        or population.get("fold_count_measured") != len(expected_measured)
        or population.get("locked_holdout_season") != LOCKED_HOLDOUT_SEASON
        or population.get("locked_holdout_rows_present") != 0
        or measured_ids != expected_measured
    ):
        raise BindingCalibrationError("Fidelity artifact has a different fold population.")

    exclusions = fidelity.get("excluded_folds")
    folds = fidelity.get("folds")
    if not isinstance(exclusions, list) or not isinstance(folds, list):
        raise BindingCalibrationError("Fidelity artifact fold records are missing.")
    excluded_ids = tuple(str(_mapping(item, "excluded fold").get("fold_id")) for item in exclusions)
    measured_record_ids = tuple(
        str(_mapping(item, "fidelity fold").get("fold_id")) for item in folds
    )
    if excluded_ids != HISTORY_BURN_IN_FOLDS or measured_record_ids != expected_measured:
        raise BindingCalibrationError("Fidelity artifact fold records contradict its population.")
    warnings_value = fidelity.get("warnings")
    if not isinstance(warnings_value, list) or any(
        not isinstance(item, str) for item in warnings_value
    ):
        raise BindingCalibrationError("Fidelity warnings must be a list of strings.")
    return fidelity_digest


def _load_development_panel(
    archive_root: Path, seasons: Sequence[str] = HISTORY_SEASONS
) -> pd.DataFrame:
    panel = build_panel(archive_root, seasons=tuple(seasons))
    observed = {str(value) for value in panel["season"].dropna().unique()}
    if observed != set(seasons):
        raise BindingCalibrationError(
            "Phase D panel seasons differ from the explicit development history."
        )
    return panel


def _target(fold_id: str) -> ScenarioTarget:
    season, separator, gameweek = fold_id.rpartition("-gw")
    if not separator:
        raise BindingCalibrationError(f"Invalid fold id {fold_id!r}.")
    return ScenarioTarget(season=season, gameweek=int(gameweek))


def _selected_component_inputs(
    handoff: PhaseCComponentHandoff,
    candidate: EvaluationFold,
    selected_ids: Sequence[int],
) -> tuple[ComponentScenarioInputs, PredictionSnapshot]:
    target = _target(candidate.fold_id)
    selected = set(selected_ids)
    rows = handoff.rows.loc[
        handoff.rows["fold_id"].eq(candidate.fold_id) & handoff.rows["player_id"].isin(selected)
    ].copy(deep=True)
    projections = candidate.projections.loc[candidate.projections["player_id"].isin(selected)].copy(
        deep=True
    )
    if len(rows) != 15 or len(projections) != 15 or set(rows["player_id"]) != selected:
        raise BindingCalibrationError(
            f"{candidate.fold_id} selected squad does not align to exactly 15 Phase C rows."
        )
    rows = rows.sort_values("player_id", kind="stable").reset_index(drop=True)
    projections = projections.sort_values("player_id", kind="stable").reset_index(drop=True)
    # The verified OOF rows carry position for component slices, while team identity stays in
    # the decision roster/projection. Bind it only after the full-pool decision is frozen.
    rows = rows.merge(
        projections.loc[:, ["player_id", "team_id"]],
        on="player_id",
        how="left",
        validate="one_to_one",
    )
    snapshot = prepare_optimizer_projection(
        projections.loc[:, ["player_id", "name", "team_id", "position", "price_tenths"]],
        projections.loc[:, ["player_id", "expected_points"]],
        PredictionProvenance(
            model_name=handoff.model_version,
            model_version=handoff.model_version,
            feature_contract_version=handoff.feature_contract_version,
            training_cutoff=candidate.fold_id,
            training_data_fingerprint=handoff.table_sha256,
        ),
    )
    inputs = ComponentScenarioInputs(
        table=rows.loc[
            :,
            [
                "player_id",
                "team_id",
                "position",
                "fixture_count",
                "appearance_probability",
                "expected_minutes_if_appearance",
                "raw_expected_points_if_appearance",
                "composition_route",
                "evidence_status",
            ],
        ],
        provenance=ComponentScenarioProvenance(
            phase_c_table_sha=handoff.table_sha256,
            roster_sha=handoff.roster_sha256,
            model_version=handoff.model_version,
            feature_contract_version=handoff.feature_contract_version,
            target_contract_version=handoff.target_contract_version,
            dataset_contract_version=handoff.dataset_contract_version,
            season=target.season,
            target_gameweek=target.gameweek,
            deterministic_seed=0,
            # A development handoff yields development provenance; the frozen path passes None.
            development_contract=handoff.development_contract,
        ),
    )
    return inputs, snapshot


def _binding_population(
    fold_ids: Sequence[str], direct_control_fold_ids: Sequence[str]
) -> tuple[str, ...]:
    ordered = tuple(fold_ids)
    if (
        len(ordered) != FULL_FOLD_COUNT
        or len(set(ordered)) != FULL_FOLD_COUNT
        or ordered[: len(HISTORY_BURN_IN_FOLDS)] != HISTORY_BURN_IN_FOLDS
        or ordered[-1] != LAST_BINDING_FOLD
    ):
        raise BindingCalibrationError(
            "Phase C OOF fold population differs from the preregistration."
        )
    direct = tuple(direct_control_fold_ids)
    if direct != DIRECT_CONTROL_ABSTENTIONS:
        raise BindingCalibrationError(
            "Selected direct-control abstentions differ from the preregistered fold."
        )
    eligible = tuple(
        fold_id
        for fold_id in ordered[len(HISTORY_BURN_IN_FOLDS) :]
        if fold_id not in DIRECT_CONTROL_ABSTENTIONS
    )
    if (
        len(eligible) != BINDING_FOLD_COUNT
        or eligible[0] != FIRST_BINDING_FOLD
        or eligible[-1] != LAST_BINDING_FOLD
    ):
        raise BindingCalibrationError("Binding population is not the frozen 137-fold population.")
    return eligible


def _candidate_record(
    candidate_sampler: ConditionalResidualConfig | None,
) -> dict[str, object] | None:
    """The provenance block a candidate report carries; None for the binding sampler."""

    if candidate_sampler is None:
        return None
    return {
        "sampler_contract_version": candidate_sampler.contract_version,
        "conditional_residual_fraction": candidate_sampler.fraction,
        "conditional_residual_minimum_rows": candidate_sampler.minimum_rows,
        "reference_contract_version": REPORT_VERSION,
        "development_data_only": True,
        "binding": False,
    }


def _measure_fold(
    handoff: PhaseCComponentHandoff,
    prepared: EvaluationFold,
    result: OptimizationResult,
    realized_score: float,
    selected_ids: Sequence[int],
    settings: ScenarioConfig,
    candidate_sampler: ConditionalResidualConfig | None,
    *,
    development: bool = False,
) -> tuple[ComponentCalibrationFold, dict[str, object]]:
    """Simulate one frozen squad decision on the binding sampler, or on the candidate if given.

    The sampler setting travels under its own name from the arguments to the draw, and the fold
    record reports the contract version the draw itself declares, so the report can never name
    a sampler the draw did not use. A development record additionally carries the complete
    decision identity and its own wall time; the binding record is unchanged.
    """

    started = datetime.now(UTC)
    fold_id = prepared.fold_id
    inputs, snapshot = _selected_component_inputs(handoff, prepared, selected_ids)
    if not bool(inputs.table["composition_route"].eq(COMPONENT_MODEL_ROUTE).all()):
        raise BindingCalibrationError(f"{fold_id} contains a selected non-component row.")
    target = _target(fold_id)
    history = handoff.rows.loc[handoff.rows["fold_id"].astype("string") < fold_id]
    residuals = paired_conditional_residuals(
        history,
        target=target,
        min_history_folds=settings.min_history_folds,
    )
    draw = sample_component_scenarios(
        inputs, snapshot, residuals, target, settings, conditional_residuals=candidate_sampler
    )
    scored = score_component_scenario_decision(result, draw)
    readout = summarize_component_decision_distribution(scored, realized_score=realized_score)
    record: dict[str, object] = {
        "fold_id": fold_id,
        "sampler_contract_version": str(
            draw.scenarios.diagnostics["component_sampler_contract_version"]
        ),
        "solver_status": result.solver_status.value,
        "realized_score": readout.realized_score,
        "scenario_mean_score": readout.mean_score,
        "scenario_standard_deviation": readout.score_standard_deviation,
        "q10_score": readout.lower_quantile_score,
        "probability_integral_transform": readout.probability_integral_transform,
        "realized_below_q10": readout.realized_below_lower_quantile,
        "scenario_fingerprint": readout.scenario_fingerprint,
        "component_fingerprint": readout.component_fingerprint,
    }
    if development:
        record["decision_identity"] = _decision_identity(result)
        record["residual_history_folds"] = len(residuals.history_fold_ids)
        record["residual_pool_rows"] = len(residuals.residuals)
        record["measure_seconds"] = (datetime.now(UTC) - started).total_seconds()
    return ComponentCalibrationFold(fold_id=fold_id, readout=readout), record


def _measure(arguments: argparse.Namespace) -> tuple[dict[str, object], int]:
    candidate_sampler = _candidate_from_arguments(arguments)
    development = _development_from_arguments(arguments)
    handoff = _read_handoff(arguments, development)
    if development is None:
        return _measure_binding(arguments, handoff, candidate_sampler)
    return _measure_development(arguments, handoff, candidate_sampler, development)


def _measure_development(
    arguments: argparse.Namespace,
    handoff: PhaseCComponentHandoff,
    candidate_sampler: ConditionalResidualConfig | None,
    development: DevelopmentInputs,
) -> tuple[dict[str, object], int]:
    """The development_v2 reading: computed population, pinned inputs, no binding verdict."""

    handoff_seasons = {str(value) for value in handoff.rows["season"].dropna().unique()}
    outside = sorted(handoff_seasons - set(DEVELOPMENT_HISTORY_SEASONS[1:]))
    if outside:
        raise BindingCalibrationError(
            f"The development handoff carries seasons outside the v2 scope: {outside!r}."
        )
    decision_seasons = tuple(
        season for season in DEVELOPMENT_HISTORY_SEASONS[1:] if season in handoff_seasons
    )
    history_seasons = (DEVELOPMENT_HISTORY_SEASONS[0], *decision_seasons)
    panel = _load_development_panel(arguments.archive_root, history_seasons)
    controls = build_walk_forward_folds(
        panel,
        seasons=decision_seasons,
        projection_builder=make_ridge_projection_builder(cross_season=CrossSeasonConfig()),
    )
    prepared = prepare_phase_c_component_folds(
        handoff, controls, development_contract=DEVELOPMENT_OOF_CONTRACT_VERSION
    )
    all_ids = tuple(fold.fold_id for fold in prepared)
    settings = ScenarioConfig()
    burn_in, history_eligible = _development_population(
        handoff.rows, all_ids, min_history_folds=settings.min_history_folds
    )
    requested = development.folds
    if requested is not None:
        unknown = sorted(set(requested) - set(all_ids))
        if unknown:
            raise BindingCalibrationError(f"--folds names folds outside the handoff: {unknown!r}.")
        in_burn_in = sorted(set(requested) & set(burn_in))
        if in_burn_in:
            raise BindingCalibrationError(
                f"--folds names history burn-in folds: {in_burn_in!r}; they are not eligible."
            )
        candidates = tuple(fold for fold in prepared if fold.fold_id in set(requested))
    else:
        candidates = tuple(fold for fold in prepared if fold.fold_id in set(history_eligible))
    evaluation = evaluate_prepared_folds(
        candidates,
        EvaluationConfig(
            scoring_policy=ScoringPolicy.OFFICIAL_AUTOSUB_CAPTAIN_V2,
            run_metadata={"study": DEVELOPMENT_REPORT_VERSION},
        ),
    )
    if len(evaluation.folds) != len(candidates):
        raise BindingCalibrationError("Development evaluation omitted a Phase C fold.")

    candidate_by_id = {fold.fold_id: fold for fold in candidates}
    result_by_id = {fold.fold_id: fold for fold in evaluation.folds}
    direct_control: list[str] = []
    unsolved: list[str] = []
    unscored: list[str] = []
    selected_by_id: dict[str, tuple[int, ...]] = {}
    measured_ids: list[str] = []
    for fold_id in (fold.fold_id for fold in candidates):
        evaluated = result_by_id[fold_id]
        result = evaluated.optimization_result
        if not result.has_solution:
            unsolved.append(fold_id)
            continue
        selected_ids = tuple(int(value) for value in result.selected_squad["player_id"])
        selected_rows = handoff.rows.loc[
            handoff.rows["fold_id"].eq(fold_id) & handoff.rows["player_id"].isin(selected_ids)
        ]
        if bool(selected_rows["composition_route"].eq(DIRECT_CONTROL_ROUTE).any()):
            direct_control.append(fold_id)
            continue
        if evaluated.realized_squad_points is None:
            unscored.append(fold_id)
            continue
        selected_by_id[fold_id] = selected_ids
        measured_ids.append(fold_id)

    readings: list[ComponentCalibrationFold] = []
    fold_records: list[dict[str, object]] = []
    for fold_id in measured_ids:
        evaluated = result_by_id[fold_id]
        realized = evaluated.realized_squad_points
        if realized is None:
            raise BindingCalibrationError(f"{fold_id} lost its realized score.")
        reading, record = _measure_fold(
            handoff,
            candidate_by_id[fold_id],
            evaluated.optimization_result,
            realized,
            selected_by_id[fold_id],
            settings,
            candidate_sampler,
            development=True,
        )
        readings.append(reading)
        fold_records.append(record)

    verdict: dict[str, object] | None = None
    verdict_note = (
        "No verdict: fewer than the minimum folds for a calibration reading were measured "
        "(a pilot). The S1/S2 readings are development observations only."
    )
    if len(measured_ids) >= MIN_CALIBRATION_FOLDS:
        verdict = asdict(
            evaluate_component_squad_calibration(
                readings,
                expected_fold_ids=tuple(measured_ids),
                sampler_fidelity_verified=False,
            )
        )
        verdict_note = (
            "The verdict abstains by protocol: no sampler-fidelity artifact exists for the v2 "
            "development handoff. The S1/S2 readings are reported as development observations."
        )
    return (
        {
            "source": {
                "phase_c_contract": DEVELOPMENT_OOF_CONTRACT_VERSION,
                "phase_c_weighting": handoff.weighting,
                "table_sha256": handoff.table_sha256,
                "roster_sha256": handoff.roster_sha256,
                "manifest_sha256": handoff.manifest_sha256,
                "producer_repository_commit": handoff.repository_commit,
                "model_version": handoff.model_version,
                "feature_contract_version": handoff.feature_contract_version,
                "target_contract_version": handoff.target_contract_version,
                "dataset_contract_version": handoff.dataset_contract_version,
                "fidelity_artifact_sha256": None,
                "pinned_by_arguments": True,
            },
            "config": asdict(settings),
            "solver_profile": _solver_profile(),
            "candidate": _candidate_record(candidate_sampler),
            "sampler_contract_version": (
                candidate_sampler.contract_version
                if candidate_sampler is not None
                else "component_scenario_foundation_v1"
            ),
            "population": {
                "history_seasons": list(history_seasons),
                "decision_seasons": list(decision_seasons),
                "full_fold_count": len(all_ids),
                "min_history_folds": settings.min_history_folds,
                "history_burn_in_fold_ids": list(burn_in),
                "history_eligible_fold_count": len(history_eligible),
                "requested_fold_ids": list(requested) if requested is not None else None,
                "evaluated_fold_ids": [fold.fold_id for fold in candidates],
                "direct_control_abstention_fold_ids": direct_control,
                "unsolved_fold_ids": unsolved,
                "unscored_fold_ids": unscored,
                "measured_fold_ids": measured_ids,
                "eligibility_note": (
                    "History eligibility is computed from the handoff for every fold; the "
                    "direct-control condition is known only for the folds whose full-pool "
                    "decision was solved in this run."
                ),
            },
            "folds": fold_records,
            "development_observation": _development_observation(readings),
            "verdict": verdict,
            "verdict_note": verdict_note,
        },
        len(panel),
    )


def _measure_binding(
    arguments: argparse.Namespace,
    handoff: PhaseCComponentHandoff,
    candidate_sampler: ConditionalResidualConfig | None,
) -> tuple[dict[str, object], int]:
    fidelity_sha256 = _load_verified_fidelity(arguments.fidelity, handoff)
    panel = _load_development_panel(arguments.archive_root)
    controls = build_walk_forward_folds(
        panel,
        seasons=DECISION_SEASONS,
        projection_builder=make_ridge_projection_builder(cross_season=CrossSeasonConfig()),
    )
    candidates = prepare_phase_c_component_folds(handoff, controls)
    evaluation = evaluate_prepared_folds(
        candidates,
        EvaluationConfig(
            scoring_policy=ScoringPolicy.OFFICIAL_AUTOSUB_CAPTAIN_V2,
            run_metadata={"study": REPORT_VERSION},
        ),
    )
    if len(evaluation.folds) != len(candidates):
        raise BindingCalibrationError("Candidate evaluation omitted a Phase C fold.")

    settings = ScenarioConfig()
    candidate_by_id = {fold.fold_id: fold for fold in candidates}
    result_by_id = {fold.fold_id: fold for fold in evaluation.folds}
    all_ids = tuple(fold.fold_id for fold in candidates)
    direct_control: list[str] = []
    selected_by_id: dict[str, tuple[int, ...]] = {}
    for fold_id in all_ids[len(HISTORY_BURN_IN_FOLDS) :]:
        result = result_by_id[fold_id].optimization_result
        if not result.has_solution:
            continue
        selected_ids = tuple(int(value) for value in result.selected_squad["player_id"])
        selected_by_id[fold_id] = selected_ids
        selected_rows = handoff.rows.loc[
            handoff.rows["fold_id"].eq(fold_id) & handoff.rows["player_id"].isin(selected_ids)
        ]
        if bool(selected_rows["composition_route"].eq(DIRECT_CONTROL_ROUTE).any()):
            direct_control.append(fold_id)
    expected_ids = _binding_population(all_ids, direct_control)

    readings: list[ComponentCalibrationFold] = []
    fold_records: list[dict[str, object]] = []
    for fold_id in expected_ids:
        evaluated_fold = result_by_id[fold_id]
        if (
            not evaluated_fold.optimization_result.has_solution
            or evaluated_fold.realized_squad_points is None
        ):
            continue
        reading, record = _measure_fold(
            handoff,
            candidate_by_id[fold_id],
            evaluated_fold.optimization_result,
            evaluated_fold.realized_squad_points,
            selected_by_id[fold_id],
            settings,
            candidate_sampler,
        )
        readings.append(reading)
        fold_records.append(record)

    verdict = evaluate_component_squad_calibration(
        readings,
        expected_fold_ids=expected_ids,
        sampler_fidelity_verified=True,
    )
    return (
        {
            "source": {
                "table_sha256": handoff.table_sha256,
                "roster_sha256": handoff.roster_sha256,
                "manifest_sha256": handoff.manifest_sha256,
                "producer_repository_commit": handoff.repository_commit,
                "model_version": handoff.model_version,
                "feature_contract_version": handoff.feature_contract_version,
                "target_contract_version": handoff.target_contract_version,
                "dataset_contract_version": handoff.dataset_contract_version,
                "fidelity_artifact_sha256": fidelity_sha256,
            },
            "config": asdict(settings),
            "candidate": _candidate_record(candidate_sampler),
            "population": {
                "full_fold_count": len(all_ids),
                "history_burn_in_fold_ids": list(HISTORY_BURN_IN_FOLDS),
                "direct_control_abstention_fold_ids": direct_control,
                "expected_binding_fold_ids": list(expected_ids),
            },
            "folds": fold_records,
            "verdict": asdict(verdict),
        },
        len(panel),
    )


def _recorded_warnings(caught: list[warnings.WarningMessage]) -> list[str]:
    counted = Counter(f"{type(item.message).__name__}: {item.message}" for item in caught)
    return [
        text if count == 1 else f"{text} (raised {count} times)"
        for text, count in sorted(counted.items())
    ]


def main() -> int:
    arguments = _parse_arguments()
    started = datetime.now(UTC)
    development_mode = str(arguments.phase_c_contract) == "development_v2"
    history_seasons = DEVELOPMENT_HISTORY_SEASONS if development_mode else HISTORY_SEASONS
    metadata = artifact_metadata(
        panel_rows=0,
        created_utc=started.isoformat(timespec="seconds"),
        history_seasons=history_seasons,
    )
    provenance = cast(dict[str, object], metadata["provenance"])
    if provenance["working_tree_dirty"]:
        print("Refused: commit or stash working-tree changes before measuring Phase D.")
        return 1

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            measured, panel_rows = _measure(arguments)
        except (
            BacktestConfigurationError,
            BindingCalibrationError,
            ComponentSquadCalibrationError,
            DataError,
            EvaluationError,
            OSError,
            ScenarioError,
            ShadowReportError,
            ValueError,
        ) as error:
            print(f"Refused: {error}")
            return 1

    completed = datetime.now(UTC)
    metadata = artifact_metadata(
        panel_rows=panel_rows,
        created_utc=started.isoformat(timespec="seconds"),
        history_seasons=history_seasons,
    )
    environment = dict(cast(Mapping[str, object], metadata["environment"]))
    environment.update(
        {
            "numpy": version("numpy"),
            "scipy": version("scipy"),
            "scikit_learn": version("scikit-learn"),
        }
    )
    candidate = cast(Mapping[str, object] | None, measured.get("candidate"))
    if development_mode:
        contract_version = DEVELOPMENT_REPORT_VERSION
    elif candidate is None:
        contract_version = REPORT_VERSION
    else:
        contract_version = CANDIDATE_REPORT_VERSION
    document: dict[str, object] = {
        "contract_version": contract_version,
        "binding": candidate is None and not development_mode,
        "development_only": development_mode,
        "evaluation_contract_version": COMPONENT_SQUAD_CALIBRATION_CONTRACT_VERSION,
        "generated_at_utc": metadata["created_utc"],
        "internal_only": True,
        "member_facing_probability_published": False,
        "operational_control_changed": False,
        # 2025-26 is read as development data under the v2 contract; never an unseen test.
        "locked_holdout_accessed": development_mode,
        "prereg_document": "docs/phase_d_component_squad_calibration_prereg.md",
        **(
            {"development_method": "docs/phase_d_v2_development_method.md"}
            if development_mode
            else {}
        ),
        "execution": {
            "started_at_utc": started.isoformat(timespec="seconds"),
            "completed_at_utc": completed.isoformat(timespec="seconds"),
            "elapsed_seconds": (completed - started).total_seconds(),
            "warnings": _recorded_warnings(caught),
        },
        "provenance": metadata["provenance"],
        "environment": environment,
        **measured,
    }
    try:
        outcome = write_document_once(document, arguments.json_output)
    except ShadowReportError as error:
        print(f"Refused: {error}")
        return 1
    verdict = cast(Mapping[str, object] | None, document["verdict"])
    if verdict is None:
        population = cast(Mapping[str, object], document["population"])
        measured_ids = cast(list[str], population["measured_fold_ids"])
        print(f"Folds  {len(measured_ids)} measured (development, no verdict)")
        print(f"Note   {document['verdict_note']}")
    else:
        print(f"Folds  {verdict['fold_count']}/{verdict['expected_fold_count']}")
        print(f"S1     {verdict['s1_passes']}")
        print(f"S2     {verdict['s2_passes']}")
        print(f"Status {verdict['status']}")
    print(f"Wrote  {arguments.json_output} ({outcome})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
