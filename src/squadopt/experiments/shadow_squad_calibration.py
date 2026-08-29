"""Gates S1 and S2 of the Phase 2 protocol: the deciding model's squad distribution.

The player-level runner asks whether ``in-season-carry-over-v1``'s per-player 0.90
intervals cover 0.90 of what happened. This asks the two squad-level questions the
same pre-registration names and that runner could not: does the realized squad score
land in the middle of its own scenario distribution (S1, mean PIT), and does it fall
below that distribution's tenth percentile about a tenth of the time (S2)?

Every number here is internal. No outcome publishes a probability, a percentage or a
``P(...)`` to any member-facing surface, and a pass unlocks exactly one thing — the
``calibrated_internal`` status in an internal report.

**Nothing in this module is a new formula.** The squad comes from ``optimize_squad``,
the scenarios from ``generate_scenarios``, the distribution from
``evaluate_fixed_decision``, the realized score from ``score_realized_squad_points``,
the interval from the existing fold-level bootstrap. What is new is only the protocol
the squad-gate amendment froze, and the three disciplines it turns on:

* **The shift is fitted, then frozen.** One scalar, the negated mean of
  (raw scenario mean minus realized score) over chronological out-of-sample
  development folds, applied
  unchanged to every evaluation fold. The expanding-window "online" variant is a
  different quantity and, on an evaluation population, fits on that season's own
  outcomes; this module refuses to see an evaluation-season fold during the fit.
* **The residual population is frozen at the development boundary.** During the
  evaluation season every fold faces one identical history — not even that season's
  own earlier weeks join it — so 37 folds are 37 readings of one calibration rather
  than a slowly-improving one.
* **The unfixed controls are required, not defaulted.** ``bench_weight``, the decision
  universe and ``min_history_folds`` change which squad is chosen or which folds are
  fitted, and the amendment records them as not yet fixed. They are inputs with no
  fallback: a run that cannot name them does not start.
"""

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import numpy as np
import pandas as pd

from squadopt.backtest.splits import (
    DecisionPoint,
    realized_points_at,
    walk_forward_decision_points,
)
from squadopt.data.sources.vaastav import build_panel
from squadopt.evaluation.scoring import score_realized_squad_points
from squadopt.experiments.shadow_calibration import PREREG_GATES
from squadopt.experiments.shadow_report import (
    ShadowCalibrationReport,
    ShadowExecutionMetadata,
    ShadowGateResult,
    ShadowResidualSource,
)
from squadopt.optimization import OptimizationConfig, optimize_squad
from squadopt.prediction import PredictionProvenance, prepare_optimizer_projection
from squadopt.scenarios import (
    ScenarioConfig,
    ScenarioEvaluationConfig,
    ScenarioTarget,
    evaluate_fixed_decision,
    generate_scenarios,
)

SQUAD_SHADOW_CONTRACT_VERSION: Final = "shadow_squad_calibration_v1"

#: The squad-gate amendment's own numbers. Constants, not parameters: a run cannot be
#: given a kinder threshold than the one committed before its result existed.
SCENARIO_COUNT: Final = 200
SCENARIO_SEED: Final = 11
DISPERSION_SCALE: Final = 1.0
DOUBLE_GAMEWEEK_SCALE: Final = 1.0
LOWER_QUANTILE: Final = 0.10
S1_PIT_BOUNDS: Final = (0.43, 0.57)
S2_TAIL_BOUNDS: Final = (0.04, 0.16)

#: A representation tolerance, NOT a widening of the band. The gates are declared
#: inclusive, but the mean of 37 identical values of 0.43 evaluates to
#: 0.42999999999999994 -- one ulp below the literal -- so a strict comparison would
#: report a failure at exactly the pre-registered bound, and the protocol forbids a
#: re-run. This restores the declared inclusivity and nothing else: it is orders of
#: magnitude smaller than anything the measurement can resolve, since one fold of 37
#: moves the mean by about 0.027.
BOUND_TOLERANCE: Final = 1e-9
MIN_EVALUATION_FOLDS: Final = 30

#: The declared population. The runner keeps its own constants rather than importing
#: ``DEVELOPMENT_SEASONS`` from the blend benchmark, whose four-season set includes the
#: frozen evaluation season and would put it into the shift fit.
FIT_SEASONS: Final = ("2021-22", "2022-23", "2023-24")
EVALUATION_SEASON: Final = "2024-25"
LOCKED_HOLDOUT_SEASON: Final = "2025-26"


def _belongs(gate: str, family: str) -> bool:
    """Same family rule the contract uses, so the two cannot drift apart."""

    return gate == family or gate.startswith(f"{family}_")


S1_GATE: Final = "S1_squad_pit_location"
S2_GATE: Final = "S2_squad_lower_tail"


class SquadShadowError(ValueError):
    """Raised when a squad-level shadow calibration cannot proceed honestly."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise SquadShadowError(message)


@dataclass(frozen=True, slots=True)
class SquadShadowConfig:
    """The run's controls: the frozen ones checked, the unfixed ones demanded.

    ``bench_weight``, ``decision_universe`` and ``min_history_folds`` have no defaults
    on purpose. The squad-gate amendment records all three as still unfixed, with two
    disagreeing precedents behind the first, and a control chosen after seeing what it
    does to a gate is the failure this protocol exists to prevent.
    """

    bench_weight: float
    decision_universe: str
    min_history_folds: int
    scenario_count: int = SCENARIO_COUNT
    scenario_seed: int = SCENARIO_SEED
    dispersion_scale: float = DISPERSION_SCALE
    double_gameweek_scale: float = DOUBLE_GAMEWEEK_SCALE
    lower_quantile: float = LOWER_QUANTILE
    min_evaluation_folds: int = MIN_EVALUATION_FOLDS

    def __post_init__(self) -> None:
        _require(
            isinstance(self.bench_weight, float) and 0.0 <= self.bench_weight <= 1.0,
            "bench_weight must be a float in [0, 1]. The amendment records it as still "
            "unfixed — the in-season benchmark uses 0.1 and the scenario audit 0.0 — so "
            "it must be named by the caller and recorded, never defaulted.",
        )
        _require(
            self.decision_universe in ("full_roster", "candidate_pool"),
            "decision_universe must be 'full_roster' or 'candidate_pool'. The amendment "
            "records which universe the squad is chosen over as still unfixed; the two "
            "give different squads and different PIT.",
        )
        _require(
            self.decision_universe == "full_roster",
            "decision_universe 'candidate_pool' is not implemented. The squad is chosen "
            "over the whole roster; accepting the name while ignoring it would let a run "
            "declare a universe it did not use.",
        )
        _require(
            isinstance(self.min_history_folds, int)
            and not isinstance(self.min_history_folds, bool)
            and self.min_history_folds >= 2,
            "min_history_folds must be an integer of at least 2 -- the generator's own "
            "floor, checked here so a run is refused at configuration time rather than "
            "dying inside its first fold. It reshapes the development fit that produces "
            "the frozen shift, so it is named rather than inherited.",
        )
        for name, value, expected in (
            ("scenario_count", self.scenario_count, SCENARIO_COUNT),
            ("scenario_seed", self.scenario_seed, SCENARIO_SEED),
            ("dispersion_scale", self.dispersion_scale, DISPERSION_SCALE),
            ("double_gameweek_scale", self.double_gameweek_scale, DOUBLE_GAMEWEEK_SCALE),
            ("lower_quantile", self.lower_quantile, LOWER_QUANTILE),
            ("min_evaluation_folds", self.min_evaluation_folds, MIN_EVALUATION_FOLDS),
        ):
            _require(
                value == expected,
                f"{name} is pre-registered at {expected!r} and a run may not choose "
                f"another; got {value!r}.",
            )


@dataclass(frozen=True, slots=True)
class SquadFold:
    """One decision point's inputs, already built from the target model."""

    fold_id: str
    season: str
    gameweek: int
    projections: pd.DataFrame
    realized_points: pd.DataFrame
    prior_fold_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        _require(bool(self.fold_id), "fold_id must be non-empty.")
        _require(
            self.season != LOCKED_HOLDOUT_SEASON,
            f"{LOCKED_HOLDOUT_SEASON} is the locked holdout and may not be scored.",
        )
        _require(self.gameweek >= 2, f"{self.fold_id}: opening gameweeks are refused.")
        for frame, label in ((self.projections, "projections"), (self.realized_points, "realized")):
            _require(isinstance(frame, pd.DataFrame), f"{label} must be a pandas DataFrame.")
            _require(not frame.empty, f"{self.fold_id}: {label} is empty.")


@dataclass(frozen=True, slots=True)
class FrozenShift:
    """The selection-optimism shift, and the population it was fitted on."""

    shift_points: float
    fold_count: int
    first_fold_id: str
    last_fold_id: str
    seasons: tuple[str, ...]

    def __post_init__(self) -> None:
        _require(math.isfinite(self.shift_points), "shift_points must be finite.")
        _require(self.fold_count >= 1, "a shift needs at least one fold.")
        outside = sorted(set(self.seasons) - set(FIT_SEASONS))
        _require(
            not outside,
            f"seasons {outside!r} are outside the declared fit population "
            f"{list(FIT_SEASONS)!r}; the frozen evaluation season and the locked holdout "
            "are both excluded by that rather than by two separate rules.",
        )


@dataclass(frozen=True, slots=True)
class SquadFoldReading:
    """One evaluation fold's squad-level reading."""

    fold_id: str
    realized_score: float
    scenario_mean_score: float
    lower_quantile_score: float
    probability_integral_transform: float
    below_lower_quantile: bool


def _scenario_config(config: SquadShadowConfig) -> ScenarioConfig:
    """The generator's configuration, with every pinned knob named explicitly.

    Nothing is left to a library default: the generator's own defaults are 1000
    scenarios at seed 0, which would silently contradict an artifact that claims 200
    at seed 11.
    """

    return ScenarioConfig(
        scenario_count=config.scenario_count,
        deterministic_seed=config.scenario_seed,
        double_gameweek_scale=config.double_gameweek_scale,
        min_history_folds=config.min_history_folds,
    )


def _evaluation_config(
    config: SquadShadowConfig, *, shift_points: float
) -> ScenarioEvaluationConfig:
    return ScenarioEvaluationConfig(
        lower_quantile=config.lower_quantile,
        dispersion_scale=config.dispersion_scale,
        location_shift_points=shift_points,
    )


def _history_for(residuals: pd.DataFrame, fold_ids: Sequence[str]) -> pd.DataFrame:
    return residuals.loc[residuals["fold_id"].astype(str).isin(set(fold_ids))]


def _read_fold(
    fold: SquadFold,
    residuals: pd.DataFrame,
    history_fold_ids: Sequence[str],
    provenance: PredictionProvenance,
    config: SquadShadowConfig,
    *,
    shift_points: float,
    fixture_counts: Mapping[object, int] | None,
) -> tuple[SquadFoldReading, float]:
    """Score one fold. Returns its reading and the raw gap the shift is fitted on."""

    decision = optimize_squad(
        fold.projections, OptimizationConfig(bench_weight=config.bench_weight)
    )
    _require(
        decision.has_solution,
        f"{fold.fold_id}: no feasible risk-neutral decision; the fold is refused rather "
        "than scored on a partial squad.",
    )
    snapshot = prepare_optimizer_projection(
        fold.projections.loc[:, ["player_id", "name", "team_id", "position", "price_tenths"]],
        fold.projections.loc[:, ["player_id", "expected_points"]],
        provenance,
    )
    scenarios = generate_scenarios(
        snapshot,
        _history_for(residuals, history_fold_ids),
        ScenarioTarget(fold.season, fold.gameweek),
        _scenario_config(config),
        fixture_counts=fixture_counts,
    )
    evaluated = evaluate_fixed_decision(
        decision, scenarios, _evaluation_config(config, shift_points=shift_points)
    )
    realized_score = score_realized_squad_points(decision, fold.realized_points)

    # Missing is never zero: the audit path defaults this diagnostic to 0.0, which would
    # silently turn an absent mean into a large negative gap and corrupt the shift.
    raw = evaluated.diagnostics.get("mean_score_before_shift")
    _require(
        raw is not None,
        f"{fold.fold_id}: the scenario evaluation reported no pre-shift mean; a missing "
        "term is refused, never read as zero.",
    )
    raw_mean = float(str(raw))
    _require(
        math.isfinite(raw_mean) and math.isfinite(realized_score),
        f"{fold.fold_id}: a non-finite score cannot enter a calibration.",
    )

    scores = np.asarray(evaluated.scenario_scores, dtype="float64")
    lower = float(evaluated.metrics.lower_quantile_score)
    reading = SquadFoldReading(
        fold_id=fold.fold_id,
        realized_score=realized_score,
        scenario_mean_score=float(evaluated.metrics.mean_score),
        lower_quantile_score=lower,
        probability_integral_transform=float((scores <= realized_score).mean()),
        below_lower_quantile=bool(realized_score < lower),
    )
    return reading, raw_mean - realized_score


def fit_frozen_shift(
    folds: Sequence[SquadFold],
    residuals: pd.DataFrame,
    provenance: PredictionProvenance,
    config: SquadShadowConfig,
    *,
    fixture_counts_by_fold: Mapping[str, Mapping[object, int]] | None = None,
) -> FrozenShift:
    """Fit the one shift, on development folds only, each seeing only its own past.

    The fit runs at shift zero — the quantity being measured is exactly the gap a
    zero-shift evaluation leaves — and refuses any fold from the frozen evaluation
    season, so the number applied to 2024-25 cannot have been fitted on it.
    """

    _require(bool(folds), "the shift needs at least one development fold.")
    intruders = sorted({fold.fold_id for fold in folds if fold.season not in FIT_SEASONS})
    _require(
        not intruders,
        f"folds {intruders!r} are outside the declared fit seasons {list(FIT_SEASONS)!r}; "
        "the frozen evaluation season may not enter the shift's fit.",
    )
    ordered = sorted(folds, key=lambda fold: (fold.season, fold.gameweek))
    gaps: list[float] = []
    for fold in ordered:
        _, gap = _read_fold(
            fold,
            residuals,
            fold.prior_fold_ids,
            provenance,
            config,
            shift_points=0.0,
            fixture_counts=(
                None if fixture_counts_by_fold is None else fixture_counts_by_fold.get(fold.fold_id)
            ),
        )
        gaps.append(gap)
    return FrozenShift(
        shift_points=-float(np.mean(gaps)),
        fold_count=len(ordered),
        first_fold_id=ordered[0].fold_id,
        last_fold_id=ordered[-1].fold_id,
        seasons=tuple(sorted({fold.season for fold in ordered})),
    )


def frozen_history_fold_ids(residuals: pd.DataFrame) -> tuple[str, ...]:
    """Every residual fold from the development seasons, and nothing later.

    This is the one history all evaluation folds share. Deriving it from the residual
    table's own seasons rather than from a fold's ``prior_fold_ids`` is what keeps the
    evaluation season's earlier weeks out: those weeks are chronologically prior, and
    a "strictly earlier" rule alone would admit them.
    """

    frame = residuals.loc[residuals["season"].astype(str).isin(set(FIT_SEASONS))]
    return tuple(sorted({str(value) for value in frame["fold_id"]}))


def evaluate_squad_gates(
    folds: Sequence[SquadFold],
    residuals: pd.DataFrame,
    provenance: PredictionProvenance,
    config: SquadShadowConfig,
    shift: FrozenShift,
    *,
    fixture_counts_by_fold: Mapping[str, Mapping[object, int]] | None = None,
) -> tuple[tuple[ShadowGateResult, ...], tuple[SquadFoldReading, ...], dict[str, float | None]]:
    """Score the frozen evaluation season and read gates S1 and S2.

    Returns the gate results, the per-fold readings, and the diagnostics. An
    insufficient population returns no gates at all rather than a thin verdict — the
    caller turns that into an abstention.
    """

    _require(bool(folds), "the evaluation needs at least one fold.")
    intruders = sorted({fold.fold_id for fold in folds if fold.season != EVALUATION_SEASON})
    _require(
        not intruders,
        f"folds {intruders!r} are not in the frozen evaluation season {EVALUATION_SEASON!r}.",
    )
    history = frozen_history_fold_ids(residuals)
    _require(
        bool(history),
        "the frozen residual history is empty; the evaluation season cannot be scored "
        "against nothing.",
    )
    leaked = sorted(fold_id for fold_id in history if fold_id.startswith(EVALUATION_SEASON))
    _require(
        not leaked,
        f"the frozen history contains evaluation-season folds {leaked!r}; the population "
        "is frozen at the end of the development seasons.",
    )

    identifiers = [fold.fold_id for fold in folds]
    _require(
        len(set(identifiers)) == len(identifiers),
        "the evaluation population repeats a fold; the sample floor counts distinct "
        "measurements, not repeated readings of one gameweek.",
    )
    ordered = sorted(folds, key=lambda fold: (fold.season, fold.gameweek))
    readings = [
        _read_fold(
            fold,
            residuals,
            history,
            provenance,
            config,
            shift_points=shift.shift_points,
            fixture_counts=(
                None if fixture_counts_by_fold is None else fixture_counts_by_fold.get(fold.fold_id)
            ),
        )[0]
        for fold in ordered
    ]

    diagnostics: dict[str, float | None] = {
        "evaluation_folds": float(len(readings)),
        "frozen_shift_points": shift.shift_points,
        "shift_fit_folds": float(shift.fold_count),
    }
    if len(readings) < config.min_evaluation_folds:
        return (), tuple(readings), diagnostics

    mean_pit = float(np.mean([reading.probability_integral_transform for reading in readings]))
    tail_rate = float(np.mean([1.0 if r.below_lower_quantile else 0.0 for r in readings]))
    diagnostics["mean_probability_integral_transform"] = mean_pit
    diagnostics["realized_below_lower_quantile_rate"] = tail_rate

    low_pit, high_pit = S1_PIT_BOUNDS
    low_tail, high_tail = S2_TAIL_BOUNDS

    def _within(value: float, low: float, high: float) -> bool:
        """Inclusive as declared, with a representation tolerance at the bounds."""

        return low - BOUND_TOLERANCE <= value <= high + BOUND_TOLERANCE

    gates = (
        ShadowGateResult(
            gate=S1_GATE,
            passes=_within(mean_pit, low_pit, high_pit),
            observed=mean_pit,
            threshold=(
                f"mean PIT in [{low_pit}, {high_pit}] inclusive over {len(readings)} "
                "evaluation folds"
            ),
        ),
        ShadowGateResult(
            gate=S2_GATE,
            passes=_within(tail_rate, low_tail, high_tail),
            observed=tail_rate,
            threshold=(
                f"realized-below-q{int(config.lower_quantile * 100)} rate in "
                f"[{low_tail}, {high_tail}] inclusive over {len(readings)} evaluation folds"
            ),
        ),
    )
    return gates, tuple(readings), diagnostics


def combine_full_protocol(
    *,
    generated_at_utc: str,
    execution: ShadowExecutionMetadata,
    residual_source: ShadowResidualSource,
    player_gates: Sequence[ShadowGateResult],
    squad_gates: Sequence[ShadowGateResult],
    calibration_diagnostics: Mapping[str, float | None],
    interval_diagnostics: Mapping[str, float | None],
    evaluation_folds: int,
    provenance_fingerprints: Mapping[str, str],
    abstention_reasons: Sequence[str] = (),
) -> ShadowCalibrationReport:
    """Merge P1, S1 and S2 into the one verdict the pre-registration asks for.

    The completeness rule lives in the contract, not here: ``declared_gates`` names
    every pre-registered family and the report refuses ``calibrated_internal`` unless
    each has a passing entry. This function's own job is only to decide between the
    three terminal states honestly.

    ``point_estimate`` is deliberately ``None``. A full-protocol verdict has three
    headline numbers — pooled coverage, mean PIT and the tail rate — and electing one
    of them as *the* estimate would privilege a gate; all three live in the
    diagnostics, where each carries its own name.
    """

    gates = (*player_gates, *squad_gates)
    measured = {family for family in PREREG_GATES if any(_belongs(g.gate, family) for g in gates)}
    unasked = tuple(family for family in PREREG_GATES if family not in measured)
    unevaluable = tuple(gate.gate for gate in gates if gate.observed is None)
    failing = tuple(gate.gate for gate in gates if not gate.passes and gate.observed is not None)

    if unevaluable and not failing:
        # A gate that could not be read is missing evidence, not a negative result, and
        # the pre-registration files those under abstention.
        return ShadowCalibrationReport(
            generated_at_utc=generated_at_utc,
            execution=execution,
            horizon=1,
            residual_source=residual_source,
            sample_size=evaluation_folds,
            point_estimate=None,
            calibration_diagnostics=dict(calibration_diagnostics),
            interval_diagnostics=dict(interval_diagnostics),
            gate_results=gates,
            shadow_status="abstained",
            reasons=(
                *abstention_reasons,
                *(f"{gate} was not evaluable and carries no observation." for gate in unevaluable),
            ),
            provenance_fingerprints=dict(provenance_fingerprints),
            declared_gates=PREREG_GATES,
        )

    if failing:
        status = "failed"
        reasons: tuple[str, ...] = (
            *(f"{gate} failed as measured." for gate in failing),
            "A failing gate is the result. The thresholds do not move, and there is no "
            "retry, re-tune or reinterpretation without a new pre-registration.",
        )
    elif unasked or abstention_reasons:
        status = "abstained"
        reasons = (
            *abstention_reasons,
            *(
                (
                    "A partial protocol is not a verdict: "
                    f"{', '.join(unasked)} was pre-registered but not evaluated, so "
                    "calibrated_internal is not claimable.",
                )
                if unasked
                else ()
            ),
        )
    else:
        status = "calibrated_internal"
        reasons = (
            "Every pre-registered gate was asked and passed. This unlocks the internal "
            "status and nothing else: no member-facing surface, published field, "
            "contract or strategy evidence status changes on a pass.",
        )

    return ShadowCalibrationReport(
        generated_at_utc=generated_at_utc,
        execution=execution,
        horizon=1,
        residual_source=residual_source,
        sample_size=evaluation_folds,
        point_estimate=None,
        calibration_diagnostics=dict(calibration_diagnostics),
        interval_diagnostics=dict(interval_diagnostics),
        gate_results=gates,
        shadow_status=status,
        reasons=reasons,
        provenance_fingerprints=dict(provenance_fingerprints),
        declared_gates=PREREG_GATES,
    )


#: One season of prior cross-season history ahead of the fit population, and nothing
#: else. Passing this explicitly IS the holdout boundary: the loader's own default is
#: every supported season, which includes the locked holdout.
HISTORY_SEASONS: Final = ("2020-21", *FIT_SEASONS, EVALUATION_SEASON)


def load_panel_without_the_holdout(archive_root: Path) -> pd.DataFrame:
    """Load exactly the seasons this protocol declares, and prove it afterwards.

    The blend benchmark's own loader calls ``build_panel`` with no season list and
    cuts the result afterwards, which reads the locked holdout before discarding it.
    The protocol is a no-read rule, so the list is passed in and the loaded seasons
    are checked against it rather than assumed.
    """

    panel = build_panel(archive_root, seasons=HISTORY_SEASONS)
    loaded = tuple(sorted({str(season) for season in panel["season"].unique()}))
    _require(
        LOCKED_HOLDOUT_SEASON not in loaded,
        f"{LOCKED_HOLDOUT_SEASON} rows are present in the loaded panel; the run stops "
        "here and writes nothing.",
    )
    _require(
        set(FIT_SEASONS).issubset(loaded) and EVALUATION_SEASON in loaded,
        f"the loaded panel {loaded!r} does not cover the declared population.",
    )
    return panel


def build_squad_folds(
    panel: pd.DataFrame,
    residuals: pd.DataFrame,
    projection_provider: Callable[[DecisionPoint], pd.DataFrame],
    *,
    seasons: Sequence[str],
) -> tuple[SquadFold, ...]:
    """Assemble one fold per decision point, projected by the target model.

    ``projection_provider`` is injected rather than imported: the only assembly that
    produces this model's per-fold table lives beside the blend benchmark in
    ``scripts/``, which this layer may not import, and rebuilding it here would be a
    second copy of the rule that has to keep agreeing with the bound residual export.
    The caller passes the same ``_Inputs.blend`` the export itself uses, so decision
    and residual history describe one model by construction.

    ``prior_fold_ids`` is the chronological "strictly earlier" set. It is what the
    development pass consumes; the evaluation pass deliberately ignores it in favour
    of the frozen history, because chronological priority alone would admit the
    evaluation season's own earlier weeks.
    """

    decisions = walk_forward_decision_points(
        panel, seasons=tuple(seasons), min_prior_gameweeks_in_season=1
    )
    _require(bool(decisions), f"no decision points for seasons {list(seasons)!r}.")
    order = {
        fold_id: index
        for index, fold_id in enumerate(sorted({str(decision.fold_id) for decision in decisions}))
    }
    known = sorted({str(value) for value in residuals["fold_id"]})
    folds: list[SquadFold] = []
    for decision in decisions:
        position = order[str(decision.fold_id)]
        prior = tuple(
            fold_id for fold_id in known if fold_id in order and order[fold_id] < position
        )
        folds.append(
            SquadFold(
                fold_id=decision.fold_id,
                season=decision.season,
                gameweek=decision.gameweek,
                projections=projection_provider(decision),
                realized_points=realized_points_at(panel, decision),
                prior_fold_ids=prior,
            )
        )
    return tuple(folds)
