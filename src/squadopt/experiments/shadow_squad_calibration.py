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
* **Every control is pinned, and none is inherited.** ``bench_weight``, the decision
  universe and ``min_history_folds`` change which squad is chosen or which folds are
  fitted; ``min_player_observations``, ``player_scale_shrinkage`` and
  ``player_location_shrinkage`` change the spread the scenarios are drawn with. The
  first three were the controls the first amendment refused to choose; the second
  three were reaching the generator as library defaults and never reaching the
  artifact. The second amendment fixed all six, so the configuration accepts exactly
  one value for each of them and records every one of them.
* **The bootstrap decides nothing.** The interval is computed by a different function
  from the one that reads the gates, because clause 22 makes it diagnostic only: the
  verdict is taken on the point estimate against the pre-registered band.
"""

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, fields
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
from squadopt.experiments.shadow_calibration import (
    BOOTSTRAP_SEED,
    CONFIDENCE_LEVEL,
    GROUP_COVERAGE_TOLERANCE,
    POOLED_COVERAGE_TOLERANCE,
    bootstrap_interval,
)
from squadopt.experiments.shadow_report import (
    PREREG_GATE_FAMILIES,
    SHADOW_CALIBRATION_CONTRACT_V2,
    ShadowCalibrationReport,
    ShadowExecutionMetadata,
    ShadowGateResult,
    ShadowResidualSource,
    read_shadow_report,
)
from squadopt.optimization import OptimizationConfig, optimize_squad
from squadopt.prediction import PredictionProvenance, prepare_optimizer_projection
from squadopt.prediction.in_season import InSeasonBlendConfig
from squadopt.scenarios import (
    ScenarioConfig,
    ScenarioEvaluationConfig,
    ScenarioTarget,
    evaluate_fixed_decision,
    generate_scenarios,
)

SQUAD_SHADOW_CONTRACT_VERSION: Final = "shadow_squad_calibration_v1"

#: The squad-gate amendments' own numbers. Constants, not parameters: a run cannot be
#: given a kinder threshold than the one committed before its result existed.
#:
#: The first six come from the second amendment, which fixed the three controls the
#: first one refused to choose and the three the generator had been inheriting from its
#: library defaults. Each is the live product default or the library canon, and each is
#: here rather than in a call site because a control chosen at the call site is a
#: control nobody pre-registered.
BENCH_WEIGHT: Final = 0.1
DECISION_UNIVERSE: Final = "full_roster"
MIN_HISTORY_FOLDS: Final = 8
MIN_PLAYER_OBSERVATIONS: Final = 8
PLAYER_SCALE_SHRINKAGE: Final = 10.0
PLAYER_LOCATION_SHRINKAGE: Final = None

SCENARIO_COUNT: Final = 200
SCENARIO_SEED: Final = 11
DISPERSION_SCALE: Final = 1.0
DOUBLE_GAMEWEEK_SCALE: Final = 1.0
LOWER_QUANTILE: Final = 0.10

#: Two evaluation summaries neither S1 nor S2 reads. Pinned at their defaults and
#: recorded anyway, so a later protocol that does read them cannot claim this run's
#: numbers were taken under different ones.
WORST_FRACTION: Final = 0.10
POINTS_THRESHOLD: Final = 40.0

#: The bootstrap the second amendment declares: fold-level, and diagnostic only. The
#: gate decision is read from the point estimate, so these three never reach a verdict.
BOOTSTRAP_RESAMPLES: Final = 5000

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

#: A gameweek becomes a decision point once the season has one behind it. It is a
#: constant rather than a literal at two call sites because it decides which gameweeks
#: are folds at all, and the artifact records it with everything else.
MIN_PRIOR_GAMEWEEKS_IN_SEASON: Final = 1


def _belongs(gate: str, family: str) -> bool:
    """Same family rule the contract uses, so the two cannot drift apart."""

    return gate == family or gate.startswith(f"{family}_")


S1_GATE: Final = "S1_squad_pit_location"
S2_GATE: Final = "S2_squad_lower_tail"

#: The family this instrument does not measure. P1 belongs to the player-level runner,
#: and the full protocol's verdict merges that runner's recorded result rather than
#: measuring it again — two measurements of one gate would be two answers to it.
PLAYER_GATE_FAMILY: Final = PREREG_GATE_FAMILIES[0]


class SquadShadowError(ValueError):
    """Raised when a squad-level shadow calibration cannot proceed honestly."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise SquadShadowError(message)


@dataclass(frozen=True, slots=True)
class SquadShadowConfig:
    """Every control this protocol runs under, and every one of them pre-registered.

    Nothing here is a choice a call site gets to make. The first six fields were the
    open ones — three the first amendment refused to fix and three the generator was
    inheriting from its library defaults — and the second amendment fixed all six at
    the live product default or the library canon. They stay named fields rather than
    disappearing into the constants so that they can be read off the object, recorded
    in provenance, and checked against the amendment in one place.

    The check is deliberately equality against the pre-registered value rather than a
    range: a control that may be "any float in [0, 1]" is a control a run can choose
    after seeing what it does to a gate.
    """

    bench_weight: float = BENCH_WEIGHT
    decision_universe: str = DECISION_UNIVERSE
    min_history_folds: int = MIN_HISTORY_FOLDS
    min_player_observations: int = MIN_PLAYER_OBSERVATIONS
    player_scale_shrinkage: float = PLAYER_SCALE_SHRINKAGE
    player_location_shrinkage: float | None = PLAYER_LOCATION_SHRINKAGE
    scenario_count: int = SCENARIO_COUNT
    scenario_seed: int = SCENARIO_SEED
    dispersion_scale: float = DISPERSION_SCALE
    double_gameweek_scale: float = DOUBLE_GAMEWEEK_SCALE
    lower_quantile: float = LOWER_QUANTILE
    worst_fraction: float = WORST_FRACTION
    points_threshold: float = POINTS_THRESHOLD
    min_evaluation_folds: int = MIN_EVALUATION_FOLDS
    bootstrap_resamples: int = BOOTSTRAP_RESAMPLES
    bootstrap_seed: int = BOOTSTRAP_SEED
    confidence_level: float = CONFIDENCE_LEVEL

    def __post_init__(self) -> None:
        for name, value, expected in (
            ("bench_weight", self.bench_weight, BENCH_WEIGHT),
            ("decision_universe", self.decision_universe, DECISION_UNIVERSE),
            ("min_history_folds", self.min_history_folds, MIN_HISTORY_FOLDS),
            ("min_player_observations", self.min_player_observations, MIN_PLAYER_OBSERVATIONS),
            ("player_scale_shrinkage", self.player_scale_shrinkage, PLAYER_SCALE_SHRINKAGE),
            (
                "player_location_shrinkage",
                self.player_location_shrinkage,
                PLAYER_LOCATION_SHRINKAGE,
            ),
            ("scenario_count", self.scenario_count, SCENARIO_COUNT),
            ("scenario_seed", self.scenario_seed, SCENARIO_SEED),
            ("dispersion_scale", self.dispersion_scale, DISPERSION_SCALE),
            ("double_gameweek_scale", self.double_gameweek_scale, DOUBLE_GAMEWEEK_SCALE),
            ("lower_quantile", self.lower_quantile, LOWER_QUANTILE),
            ("worst_fraction", self.worst_fraction, WORST_FRACTION),
            ("points_threshold", self.points_threshold, POINTS_THRESHOLD),
            ("min_evaluation_folds", self.min_evaluation_folds, MIN_EVALUATION_FOLDS),
            ("bootstrap_resamples", self.bootstrap_resamples, BOOTSTRAP_RESAMPLES),
            ("bootstrap_seed", self.bootstrap_seed, BOOTSTRAP_SEED),
            ("confidence_level", self.confidence_level, CONFIDENCE_LEVEL),
        ):
            # The type is checked as well as the value, and exactly rather than by
            # isinstance: 1 equals 1.0 in Python but writes a different string into
            # provenance, True equals a seed of 0, and numpy.float64 is a float that
            # reprs as np.float64(0.1). A value read out of a DataFrame column arrives
            # as exactly that last one, and two runs under the identical pre-registered
            # weight would then write different artifacts and read as a conflict.
            _require(
                type(value) is type(expected) and value == expected,
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
    """The generator's configuration, with every knob named explicitly.

    Every field, not only the interesting ones. The generator's own defaults are 1000
    scenarios at seed 0, which would silently contradict an artifact claiming 200 at
    seed 11 — and three quieter knobs did exactly that until the second amendment
    named them.
    """

    return ScenarioConfig(
        scenario_count=config.scenario_count,
        deterministic_seed=config.scenario_seed,
        min_history_folds=config.min_history_folds,
        min_player_observations=config.min_player_observations,
        player_scale_shrinkage=config.player_scale_shrinkage,
        player_location_shrinkage=config.player_location_shrinkage,
        double_gameweek_scale=config.double_gameweek_scale,
    )


def _evaluation_config(
    config: SquadShadowConfig, *, shift_points: float
) -> ScenarioEvaluationConfig:
    """Every summary control named, including the two the gates never read."""

    return ScenarioEvaluationConfig(
        lower_quantile=config.lower_quantile,
        worst_fraction=config.worst_fraction,
        points_threshold=config.points_threshold,
        location_shift_points=shift_points,
        dispersion_scale=config.dispersion_scale,
    )


def _optimizer_config(config: SquadShadowConfig) -> OptimizationConfig:
    """The squad the product would choose, at the weight the product decides under."""

    return OptimizationConfig(bench_weight=config.bench_weight)


def _readable(value: object) -> str:
    """One deterministic string per parameter, mappings included.

    A string is written as itself rather than as its repr, so an artifact reads
    ``full_roster`` and not ``'full_roster'``; everything else keeps the repr, which is
    what distinguishes 1 from 1.0 and None from the string "None".
    """

    if isinstance(value, Mapping):
        entries = sorted((str(key), str(item)) for key, item in value.items())
        return "{" + ", ".join(f"{key}={item}" for key, item in entries) + "}"
    if isinstance(value, str):
        return value
    return repr(value)


def declared_parameters(config: SquadShadowConfig, *, shift_points: float) -> dict[str, str]:
    """Every field of every configuration this run actually constructs.

    Read off the constructed objects rather than from a hand-kept list. Clause 24 of
    the second amendment exists because three generator knobs reached the generator as
    library defaults and never reached the artifact; a list maintained by hand is the
    same failure waiting to happen. A field added to any of these three configurations
    upstream appears in the next run's provenance without this module being edited,
    and a library default that moves underneath the protocol shows up as a changed
    artifact rather than as a silent difference.
    """

    parameters: dict[str, str] = {
        # Two numbers that belong to no configuration object and still decide things:
        # the representation tolerance the gates are read with, and the rule that makes
        # a gameweek a fold.
        "protocol_bound_tolerance": _readable(BOUND_TOLERANCE),
        "protocol_min_prior_gameweeks_in_season": _readable(MIN_PRIOR_GAMEWEEKS_IN_SEASON),
        "protocol_fit_seasons": ",".join(FIT_SEASONS),
        "protocol_evaluation_season": EVALUATION_SEASON,
        "protocol_s1_bounds": _readable(S1_PIT_BOUNDS),
        "protocol_s2_bounds": _readable(S2_TAIL_BOUNDS),
    }
    for prefix, settings in (
        # The protocol's own configuration first. Some of its fields — the decision
        # universe above all — belong to no library object, so a run that recorded only
        # the constructed library configurations would leave them out of the artifact.
        ("protocol", config),
        ("generator", _scenario_config(config)),
        ("evaluation", _evaluation_config(config, shift_points=shift_points)),
        ("optimizer", _optimizer_config(config)),
        # The fifth configuration, and the one the review found missing: it decides the
        # projections, therefore the squad, therefore both gates.
        ("projection", InSeasonBlendConfig()),
    ):
        for entry in fields(settings):
            parameters[f"{prefix}_{entry.name}"] = _readable(getattr(settings, entry.name))
    return parameters


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

    decision = optimize_squad(fold.projections, _optimizer_config(config))
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

    Clause 27: the development population is one chronological chain, so its earliest
    folds carry less residual history than ``min_history_folds`` declares. They are a
    burn-in and do not enter the mean. Eligibility is read from each fold's own
    declared history before anything is generated (clause 28), never from which folds
    the generator happened to refuse.
    """

    _require(bool(folds), "the shift needs at least one development fold.")
    intruders = sorted({fold.fold_id for fold in folds if fold.season not in FIT_SEASONS})
    _require(
        not intruders,
        f"folds {intruders!r} are outside the declared fit seasons {list(FIT_SEASONS)!r}; "
        "the frozen evaluation season may not enter the shift's fit.",
    )
    ordered = sorted(folds, key=lambda fold: (fold.season, fold.gameweek))

    strangers = sorted(
        {
            fold_id
            for fold in ordered
            for fold_id in fold.prior_fold_ids
            if not any(fold_id.startswith(f"{season}-") for season in FIT_SEASONS)
        }
    )
    _require(
        not strangers,
        f"prior residual folds {strangers!r} are outside the declared fit seasons "
        f"{list(FIT_SEASONS)!r}. The fit population is checked at the fold level and at "
        "the history level, because a fold from the right season can still be handed a "
        "history from the wrong one.",
    )

    burn_in = tuple(
        fold for fold in ordered if len(set(fold.prior_fold_ids)) < config.min_history_folds
    )
    eligible = tuple(
        fold for fold in ordered if len(set(fold.prior_fold_ids)) >= config.min_history_folds
    )
    _require(
        [fold.fold_id for fold in burn_in] == [fold.fold_id for fold in ordered[: len(burn_in)]],
        "the folds with too little history are not the earliest of the chain; the "
        "development population is not the chronological chain this protocol declares.",
    )
    _require(
        len(burn_in) <= config.min_history_folds,
        f"the burn-in is {len(burn_in)} folds where the declared history depth of "
        f"{config.min_history_folds} allows at most that many: the fold at position "
        f"{config.min_history_folds} of the chain already has that much history behind "
        "it. A longer burn-in means the residual export is missing folds this "
        "population expected, so the run stops rather than dropping folds nobody "
        "declared.",
    )
    _require(
        bool(eligible),
        f"every one of the {len(ordered)} development folds is burn-in, so the shift "
        "would be a mean of nothing.",
    )

    gaps: list[float] = []
    for fold in eligible:
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
    # Clause 30: the folds that actually entered the mean, not the folds handed in.
    return FrozenShift(
        shift_points=-float(np.mean(gaps)),
        fold_count=len(eligible),
        first_fold_id=eligible[0].fold_id,
        last_fold_id=eligible[-1].fold_id,
        seasons=tuple(sorted({fold.season for fold in eligible})),
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
    # And again on the rows themselves. The check above reads fold ids, the selection
    # reads the season column, and one residual fold id carrying rows from two seasons
    # would otherwise satisfy both while smuggling the later season into the history.
    selected = _history_for(residuals, history)
    seasons = sorted({str(value) for value in selected["season"]})
    _require(
        set(seasons) <= set(FIT_SEASONS),
        f"the frozen history's rows carry seasons {seasons!r}, outside the development "
        f"population {list(FIT_SEASONS)!r}. A fold id is a label; the season column is "
        "what the generator actually reads.",
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
    tail_events = sum(1 for reading in readings if reading.below_lower_quantile)
    tail_rate = float(np.mean([1.0 if r.below_lower_quantile else 0.0 for r in readings]))
    diagnostics["mean_probability_integral_transform"] = mean_pit
    diagnostics["realized_below_lower_quantile_rate"] = tail_rate
    # Clause 23: the count beside the rate. At 37 folds the attainable rates near the
    # band are 2/37 and 5/37, so S2 is decided by whether this integer is 2 to 5, and a
    # reader who sees only the rate cannot tell how coarse the gate really is.
    diagnostics["realized_below_lower_quantile_folds"] = float(tail_events)

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


def bootstrap_diagnostics(
    readings: Sequence[SquadFoldReading], config: SquadShadowConfig
) -> dict[str, float | None]:
    """The second amendment's fold-level bootstrap — and nothing it may decide.

    Clause 22 makes this diagnostic only: the gate is read from the point estimate
    against the pre-registered band, and an interval that straddles a bound neither
    rescues a failing estimate nor overturns a passing one. It is computed by a
    different function than the one that reads the gates for exactly that reason —
    ``evaluate_squad_gates`` never sees these numbers.
    """

    _require(bool(readings), "a bootstrap needs at least one evaluation fold.")
    pit = [reading.probability_integral_transform for reading in readings]
    tail = [1.0 if reading.below_lower_quantile else 0.0 for reading in readings]
    interval = {
        "mean_pit": bootstrap_interval(
            pit,
            resamples=config.bootstrap_resamples,
            seed=config.bootstrap_seed,
            confidence_level=config.confidence_level,
        ),
        "below_lower_quantile_rate": bootstrap_interval(
            tail,
            resamples=config.bootstrap_resamples,
            seed=config.bootstrap_seed,
            confidence_level=config.confidence_level,
        ),
    }
    diagnostics: dict[str, float | None] = {
        "bootstrap_folds": float(len(readings)),
        "bootstrap_resamples": float(config.bootstrap_resamples),
        "bootstrap_confidence_level": float(config.confidence_level),
    }
    for name, (low, high) in interval.items():
        diagnostics[f"{name}_bootstrap_low"] = low
        diagnostics[f"{name}_bootstrap_high"] = high
    return diagnostics


@dataclass(frozen=True, slots=True)
class PlayerEvidence:
    """One recorded player-level measurement, already proved to be about this export."""

    gates: tuple[ShadowGateResult, ...]
    calibration_diagnostics: Mapping[str, float | None]
    interval_diagnostics: Mapping[str, float | None]
    provenance: Mapping[str, str]
    abstentions: tuple[str, ...]
    sample_size: int


#: The one cell the pre-registration measures unconditionally. The per-group cells are
#: gated only when a group clears its row floor, so a report may legitimately carry
#: fewer of them — but a P1 answered without the pooled coverage is not P1.
POOLED_CELL: Final = f"{PLAYER_GATE_FAMILY}_pooled"


def _recomputed(gate: ShadowGateResult) -> bool:
    """P1's verdict read from its own observation, against the pre-registered band.

    The recorded ``passes`` flag is not evidence about anything: it is a claim the
    artifact makes about its own number. The bands are pre-registered constants, so the
    verdict can be recomputed, and a record whose flag disagrees with its observation is
    refused rather than believed.
    """

    tolerance = POOLED_COVERAGE_TOLERANCE if gate.gate == POOLED_CELL else GROUP_COVERAGE_TOLERANCE
    return abs(float(gate.observed or 0.0) - CONFIDENCE_LEVEL) <= tolerance


def load_bound_player_report(
    path: Path,
    residual_source: ShadowResidualSource,
    config: SquadShadowConfig,
    *,
    expect_sha256: str | None,
    expect_fingerprints: Mapping[str, str],
) -> PlayerEvidence:
    """Read P1's recorded result, and refuse it unless it measured the same thing.

    Clause 26 of the second amendment: the full-protocol verdict carries P1 as the
    player-level runner measured it, and the merge is refused unless every field of
    that artifact's residual provenance is identical to the one this run is bound to.
    Two instruments' evidence may be added together only when they were pointed at the
    same model, the same export and the same cutoff — otherwise the merged report is
    an average of two different questions.

    A mismatch raises. Everything else that could make P1's evidence unusable — no P1
    gate at all, a gate with no observation, a population below the floor, a report
    whose own provenance is missing or was produced from a modified tree — comes back
    as an abstention reason instead, because those are missing evidence rather than a
    contradiction. A P1 gate that failed as measured is neither: it is carried through
    as it stands, and the report contract turns it into a failed verdict.
    """

    report, digest = read_shadow_report(path)
    _require(
        expect_sha256 is None or digest == expect_sha256,
        f"the player report at {path.name} has digest {digest}, not the pre-registered "
        f"{expect_sha256}. Which recorded measurement P1 comes from is part of the "
        "protocol, not a path the caller happens to pass.",
    )
    recorded = report.residual_source
    for name in (
        "export_label",
        "model_name",
        "model_version",
        "feature_contract_version",
        "table_sha256",
        "seasons",
        "cutoff_fold_id",
    ):
        theirs = getattr(recorded, name)
        ours = getattr(residual_source, name)
        _require(
            theirs == ours,
            f"the recorded player report at {path.name} was measured against a "
            f"different {name} ({theirs!r}, against this run's {ours!r}). P1 and the "
            "squad gates may only be merged when they measured the same export.",
        )

    for key, expected in expect_fingerprints.items():
        theirs = report.provenance_fingerprints.get(key)
        _require(
            theirs is None or theirs == expected,
            f"the recorded player report was produced against a different {key} "
            f"({theirs!r}, against this run's {expected!r}). The residual export is not "
            "the only thing two instruments have to share.",
        )

    dropped = tuple(
        gate.gate
        for gate in report.gate_results
        if not _belongs(gate.gate, PLAYER_GATE_FAMILY)
        and not gate.passes
        and gate.observed is not None
    )
    _require(
        not dropped,
        f"the recorded player report carries measured failures {list(dropped)!r} outside "
        f"{PLAYER_GATE_FAMILY}. Merging it would keep the P1 cells and drop a recorded "
        "negative, which is the one thing a merge may never do.",
    )

    gates = tuple(gate for gate in report.gate_results if _belongs(gate.gate, PLAYER_GATE_FAMILY))
    for gate in gates:
        _require(
            gate.observed is None or gate.passes == _recomputed(gate),
            f"{gate.gate} records passes={gate.passes} for an observed coverage of "
            f"{gate.observed}, which the pre-registered band does not support. A record "
            "that disagrees with its own numbers is refused, not believed.",
        )
    _require(
        report.shadow_status != "failed"
        or any(not gate.passes and gate.observed is not None for gate in gates),
        f"the recorded player report is 'failed' but carries no failing "
        f"{PLAYER_GATE_FAMILY} cell; whatever failed in it is not what this merge would "
        "carry forward.",
    )

    abstentions: list[str] = []
    if not gates:
        abstentions.append(
            f"the recorded player report at {path.name} carries no "
            f"{PLAYER_GATE_FAMILY} gate, so P1 is unanswered here."
        )
    elif not any(gate.gate == POOLED_CELL for gate in gates):
        abstentions.append(
            f"the recorded player report carries no {POOLED_CELL} cell. The per-group "
            "cells are gated only when a group clears its row floor, so P1 without its "
            "pooled coverage is not P1 answered."
        )
    for gate in gates:
        if gate.observed is None:
            abstentions.append(
                f"{gate.gate} carries no observation in the recorded player report; "
                "an unread gate is missing evidence, not a negative result."
            )
    if report.sample_size < config.min_evaluation_folds:
        abstentions.append(
            f"the recorded player report measured {report.sample_size} folds, below "
            f"the pre-registered floor of {config.min_evaluation_folds}."
        )
    dirty = report.provenance_fingerprints.get("working_tree_dirty")
    if dirty is None:
        abstentions.append(
            "the recorded player report does not say whether its working tree was "
            "clean; missing provenance is an abstention, never an assumption."
        )
    elif dirty != "false":
        abstentions.append(
            "the recorded player report was produced from a modified working tree, so "
            "its numbers cannot be reproduced from a commit."
        )
    commit = report.provenance_fingerprints.get("repository_commit")
    if not commit:
        abstentions.append(
            "the recorded player report names no repository commit, so what produced "
            "its numbers cannot be recovered."
        )

    provenance = {
        "player_report_file": path.name,
        "player_report_sha256": digest,
        "player_report_contract_version": report.contract_version,
        "player_report_status": report.shadow_status,
        "player_report_generated_at_utc": report.generated_at_utc,
        "player_report_sample_size": str(report.sample_size),
    }
    if commit:
        provenance["player_report_repository_commit"] = commit
    # What produced the numbers on the other side of the merge. Dropping these would
    # leave the merged artifact unable to say which archive snapshot, which residual
    # generation and which model identity P1 was measured under.
    for key in (
        "dataset_snapshot_id",
        "residual_generation_commit",
        "model_identity",
        "conformal_fingerprint",
    ):
        carried = report.provenance_fingerprints.get(key)
        if carried:
            provenance[f"player_report_{key}"] = carried
    return PlayerEvidence(
        gates=gates,
        calibration_diagnostics={
            f"player_{name}": value for name, value in report.calibration_diagnostics.items()
        },
        interval_diagnostics={
            f"player_{name}": value for name, value in report.interval_diagnostics.items()
        },
        provenance=provenance,
        abstentions=tuple(abstentions),
        sample_size=report.sample_size,
    )


def combine_full_protocol(
    *,
    generated_at_utc: str,
    execution: ShadowExecutionMetadata,
    residual_source: ShadowResidualSource,
    player: PlayerEvidence,
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

    P1 arrives as a ``PlayerEvidence`` rather than as a sequence of gates, and there is
    no default. A caller that has not loaded a bound player report cannot call this at
    all — which is the point: an empty gate sequence is easy to pass by accident, and
    it would leave P1 permanently unanswered while the two squad gates looked like a
    protocol.
    """

    gates = (*player.gates, *squad_gates)
    calibration_diagnostics = {**player.calibration_diagnostics, **calibration_diagnostics}
    interval_diagnostics = {**player.interval_diagnostics, **interval_diagnostics}
    provenance_fingerprints = {**player.provenance, **provenance_fingerprints}
    abstention_reasons = (*player.abstentions, *abstention_reasons)
    measured = {
        family for family in PREREG_GATE_FAMILIES if any(_belongs(g.gate, family) for g in gates)
    }
    unasked = tuple(family for family in PREREG_GATE_FAMILIES if family not in measured)
    unevaluable = tuple(gate.gate for gate in gates if gate.observed is None)
    failing = tuple(gate.gate for gate in gates if not gate.passes and gate.observed is not None)

    # Everything that is missing rather than negative, in one place. A gate that could
    # not be read is missing evidence, and so is a family nobody asked; both belong in
    # the record even when something else also went wrong, which is why this is built
    # once rather than in whichever branch is reached first.
    missing: tuple[str, ...] = (
        *abstention_reasons,
        *(f"{gate} was not evaluable and carries no observation." for gate in unevaluable),
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

    if failing:
        status = "failed"
        reasons: tuple[str, ...] = (
            *(f"{gate} failed as measured." for gate in failing),
            "A failing gate is the result. The thresholds do not move, and there is no "
            "retry, re-tune or reinterpretation without a new pre-registration.",
            # A failure is the verdict, but it does not erase what else was missing.
            *missing,
        )
    elif missing:
        status = "abstained"
        reasons = missing
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
        declared_gates=PREREG_GATE_FAMILIES,
        contract_version=SHADOW_CALIBRATION_CONTRACT_V2,
    )


#: One season of prior cross-season history ahead of the fit population, and nothing
#: else. Passing this explicitly IS the holdout boundary: the loader's own default is
#: every supported season, which includes the locked holdout.
HISTORY_SEASONS: Final = ("2020-21", *FIT_SEASONS, EVALUATION_SEASON)


def loaded_seasons(panel: pd.DataFrame) -> tuple[str, ...]:
    """Which seasons a loaded panel actually holds.

    The pre-registration's holdout clause asks the artifact to record the seasons that
    were actually read, not the ones that were requested. Those are the same thing only
    if someone checks, which is what this is for.
    """

    return tuple(sorted({str(season) for season in panel["season"].unique()}))


def load_panel_without_the_holdout(archive_root: Path) -> pd.DataFrame:
    """Load exactly the seasons this protocol declares, and prove it afterwards.

    The blend benchmark's own loader calls ``build_panel`` with no season list and
    cuts the result afterwards, which reads the locked holdout before discarding it.
    The protocol is a no-read rule, so the list is passed in and the loaded seasons
    are checked against it rather than assumed.
    """

    panel = build_panel(archive_root, seasons=HISTORY_SEASONS)
    loaded = loaded_seasons(panel)
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
        panel,
        seasons=tuple(seasons),
        min_prior_gameweeks_in_season=MIN_PRIOR_GAMEWEEKS_IN_SEASON,
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
