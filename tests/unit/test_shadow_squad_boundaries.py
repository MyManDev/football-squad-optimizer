"""Numerical boundary probes for the squad-level shadow calibration (gates S1, S2).

Every number the two squad-gate amendments froze is attacked here at its edge: the two
inclusive gate bands, every pinned configuration value, the sign and value of the frozen
shift, the 30-fold sample floor, the granularity S2 really has on a 37-fold season, and
the two comparison conventions the tail rate rests on (which quantile rule produces q10,
and whether a realized score sitting exactly on it counts as below).

The second amendment (2026-08-29) fixed the last open controls, so what a configuration
boundary *is* has changed shape. There is no admissible range left to probe the ends of:
``SquadShadowConfig()`` is the one legal configuration, and the edge is now the nearest
value on either side of a single pre-registered constant -- including the neighbours
Python calls equal, since ``10`` and ``10.0`` compare equal but write different
provenance strings, and ``False`` equals a pre-registered seed of ``0``.

Nothing here reads an archive. The heavy collaborators are replaced by fakes whose
numbers are chosen by hand, so an assertion about a boundary is an assertion about the
runner's arithmetic and not about a data set. Two of the probes deliberately keep the
real ``evaluate_fixed_decision`` in the chain, because the claim under test is exactly
that the runner reads the quantile that function produces.

Fold counts are picked so the bound is *exactly representable*:

* S1 uses 32 folds. ``numpy.mean``'s pairwise summation is exact for a power-of-two
  count of identical values, so a population whose mean PIT is 0.43 is reported as the
  double 0.43 and the inclusive comparison is actually exercised. It is not exact for
  every count -- see the two ``..._inclusivity_holds_at_...`` tests, where at 37 folds
  (the real 2024-25 population) the raw mean sits one ulp off the literal bound and the
  runner's representation tolerance is what preserves the declared inclusivity. That
  tolerance is not a wider band, which ``..._does_not_widen_the_band`` pins separately.
* S2 uses 100 folds, because its statistic is a fraction of folds: 4/100 and 16/100 are
  the bounds exactly, and 3/100 and 17/100 are the nearest achievable misses. On a real
  37-fold season neither bound is representable at all, which is the whole point of the
  event count clause 23 added -- so that one probe runs at 37 folds and reads the count.
"""

import math
from collections.abc import Mapping, Sequence
from dataclasses import MISSING, dataclass, fields
from typing import Any

import numpy as np
import pandas as pd
import pytest

from squadopt.experiments import shadow_squad_calibration as module
from squadopt.experiments.shadow_squad_calibration import (
    BOUND_TOLERANCE,
    EVALUATION_SEASON,
    FIT_SEASONS,
    S1_GATE,
    S2_GATE,
    FrozenShift,
    SquadFold,
    SquadShadowConfig,
    SquadShadowError,
    declared_parameters,
    evaluate_squad_gates,
    fit_frozen_shift,
)
from squadopt.optimization import OptimizationConfig, OptimizationResult, SolverStatus
from squadopt.prediction import PredictionProvenance, prepare_optimizer_projection
from squadopt.prediction.in_season import InSeasonBlendConfig
from squadopt.scenarios import (
    ScenarioConfig,
    ScenarioConfigurationError,
    ScenarioEvaluationConfig,
    ScenarioTarget,
)
from squadopt.scenarios.models import ScenarioSet, _scenario_fingerprint

PROVENANCE = PredictionProvenance(
    model_name="synthetic-boundary-model",
    model_version="1.0.0",
    feature_contract_version="synthetic-boundary-features-v1",
    training_cutoff="synthetic",
    training_data_fingerprint="a" * 64,
)

#: A five-player synthetic projection. Nothing about it is measured; it exists so the
#: fold-level plumbing has real columns to slice.
PLAYERS = pd.DataFrame(
    {
        "player_id": [1, 2, 3, 4, 5],
        "name": ["Aa", "Bb", "Cc", "Dd", "Ee"],
        "team_id": [10, 11, 12, 13, 14],
        "position": ["GK", "DEF", "MID", "FWD", "MID"],
        "price_tenths": [45, 50, 65, 70, 60],
        "expected_points": [1.0, 2.0, 3.0, 4.0, 5.0],
    }
)

#: Score vectors the fake evaluator hands back. Length is the denominator of the PIT:
#: with ``scores[i] == i``, a realized score of ``k - 1`` puts exactly ``k`` scenarios
#: at or below it, so the fold's PIT is exactly ``k / len(scores)``.
SCORES_200 = tuple(float(index) for index in range(200))
SCORES_10K = tuple(float(index) for index in range(10_000))


def _config(**overrides: Any) -> SquadShadowConfig:
    """The run's one legal configuration, plus a way to attempt an illegal override.

    Nothing needs naming any more: every field is pre-registered, so the bare
    constructor is the whole protocol and any override here is an attempt to leave it.
    """

    return SquadShadowConfig(**overrides)


def _residuals() -> pd.DataFrame:
    """A residual table whose only job is to name development folds."""

    return pd.DataFrame(
        {
            "fold_id": [
                f"{season}-gw{gameweek:02d}" for season in FIT_SEASONS for gameweek in (2, 3, 4)
            ],
            "season": [season for season in FIT_SEASONS for _ in (2, 3, 4)],
            "gameweek": [gameweek for _ in FIT_SEASONS for gameweek in (2, 3, 4)],
        }
    )


#: Every development fold the residual fixture names. The shift fit refuses a fold with
#: fewer than ``min_history_folds`` priors, so a fixture needs a real history to reach
#: the generator at all.
DEVELOPMENT_FOLD_IDS: tuple[str, ...] = tuple(
    f"{season}-gw{gameweek:02d}" for season in FIT_SEASONS for gameweek in (2, 3, 4)
)


def _fold(gameweek: int, season: str = EVALUATION_SEASON) -> SquadFold:
    return SquadFold(
        fold_id=f"{season}-gw{gameweek:02d}",
        season=season,
        gameweek=gameweek,
        projections=PLAYERS.copy(deep=True),
        realized_points=PLAYERS.loc[:, ["player_id"]].assign(total_points=1.0),
        prior_fold_ids=DEVELOPMENT_FOLD_IDS,
    )


def _folds(count: int, season: str = EVALUATION_SEASON) -> tuple[SquadFold, ...]:
    """``count`` folds at consecutive gameweeks from 2 upward.

    Above 38 this is not a calendar any season has; it is a population size, and
    ``evaluate_squad_gates`` reads a population size. It is used only where the S2
    denominator has to make a bound exactly representable.
    """

    return tuple(_fold(gameweek) for gameweek in range(2, 2 + count))


def _zero_shift() -> FrozenShift:
    return FrozenShift(
        shift_points=0.0,
        fold_count=2,
        first_fold_id="2021-22-gw02",
        last_fold_id="2023-24-gw03",
        seasons=("2021-22", "2023-24"),
    )


@dataclass(frozen=True)
class _FakeDecision:
    """Stands in for an ``OptimizationResult`` where only feasibility is read."""

    has_solution: bool = True


@dataclass(frozen=True)
class _FakeMetrics:
    mean_score: float
    lower_quantile_score: float


@dataclass(frozen=True)
class _FakeEvaluation:
    scenario_scores: tuple[float, ...]
    metrics: _FakeMetrics
    diagnostics: Mapping[str, object]


@dataclass(frozen=True)
class _FakeScenarios:
    """Carries the target through, so the fake evaluator can tell folds apart."""

    target: ScenarioTarget


@dataclass(frozen=True)
class _Reading:
    """One fold's numbers, stated as counts rather than as floats."""

    at_or_below: int
    scores: tuple[float, ...] = SCORES_10K
    below_lower_quantile: bool = False
    raw_mean: float = 0.0
    omit_raw_mean: bool = False

    @property
    def realized(self) -> float:
        return float(self.at_or_below - 1)

    @property
    def lower_quantile(self) -> float:
        return self.realized + 1.0 if self.below_lower_quantile else self.realized - 1.0


class _Collaborators:
    """The four heavy collaborators, faked and keyed by gameweek."""

    def __init__(self, readings: Mapping[int, _Reading]) -> None:
        self.readings = dict(readings)
        self.scenario_configs: list[ScenarioConfig] = []
        self.evaluation_configs: list[ScenarioEvaluationConfig] = []
        self.optimization_configs: list[Any] = []
        self.history_fold_ids: list[tuple[str, ...]] = []

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(module, "optimize_squad", self._optimize)
        monkeypatch.setattr(module, "generate_scenarios", self._generate)
        monkeypatch.setattr(module, "evaluate_fixed_decision", self._evaluate)
        monkeypatch.setattr(module, "score_realized_squad_points", self._score)

    def _optimize(self, projections: pd.DataFrame, config: object) -> _FakeDecision:
        self.optimization_configs.append(config)
        return _FakeDecision()

    def _generate(
        self,
        snapshot: object,
        history: pd.DataFrame,
        target: ScenarioTarget,
        config: ScenarioConfig,
        *,
        fixture_counts: Mapping[object, int] | None = None,
    ) -> _FakeScenarios:
        self.scenario_configs.append(config)
        self.history_fold_ids.append(tuple(str(value) for value in history["fold_id"]))
        return _FakeScenarios(target=target)

    def _evaluate(
        self,
        decision: object,
        scenarios: _FakeScenarios,
        config: ScenarioEvaluationConfig,
    ) -> _FakeEvaluation:
        self.evaluation_configs.append(config)
        reading = self.readings[scenarios.target.gameweek]
        diagnostics: dict[str, object] = {}
        if not reading.omit_raw_mean:
            diagnostics["mean_score_before_shift"] = reading.raw_mean
        return _FakeEvaluation(
            scenario_scores=reading.scores,
            metrics=_FakeMetrics(
                mean_score=reading.raw_mean,
                lower_quantile_score=reading.lower_quantile,
            ),
            diagnostics=diagnostics,
        )

    def _score(self, decision: object, realized_points: pd.DataFrame) -> float:
        raise AssertionError("the realized score is supplied per fold by the caller")


class _KeyedCollaborators(_Collaborators):
    """As above, with the realized score also taken from the per-fold reading."""

    def __init__(self, readings: Mapping[int, _Reading]) -> None:
        super().__init__(readings)
        self._pending: list[int] = []

    def _generate(
        self,
        snapshot: object,
        history: pd.DataFrame,
        target: ScenarioTarget,
        config: ScenarioConfig,
        *,
        fixture_counts: Mapping[object, int] | None = None,
    ) -> _FakeScenarios:
        self._pending.append(target.gameweek)
        return super()._generate(snapshot, history, target, config, fixture_counts=fixture_counts)

    def _score(self, decision: object, realized_points: pd.DataFrame) -> float:
        return self.readings[self._pending[-1]].realized


def _gates_for(
    monkeypatch: pytest.MonkeyPatch,
    readings: Mapping[int, _Reading],
    *,
    config: SquadShadowConfig | None = None,
) -> tuple[Any, Any, dict[str, float | None]]:
    """Run ``evaluate_squad_gates`` over folds whose numbers are dictated exactly."""

    collaborators = _KeyedCollaborators(readings)
    collaborators.install(monkeypatch)
    folds = tuple(_fold(gameweek) for gameweek in sorted(readings))
    return evaluate_squad_gates(
        folds,
        _residuals(),
        PROVENANCE,
        _config() if config is None else config,
        _zero_shift(),
    )


def _uniform(count: int, reading: _Reading) -> dict[int, _Reading]:
    return {gameweek: reading for gameweek in range(2, 2 + count)}


def _gate(gates: Sequence[Any], name: str) -> Any:
    matching = [gate for gate in gates if gate.gate == name]
    assert len(matching) == 1, f"expected exactly one {name}, got {[g.gate for g in gates]!r}"
    return matching[0]


# --------------------------------------------------------------------------------
# 1. S1: the mean-PIT band is inclusive at both ends.
# --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("at_or_below", "expected"),
    [(4_300, 0.43), (5_700, 0.57)],
)
def test_s1_passes_when_the_mean_pit_sits_exactly_on_a_bound(
    monkeypatch: pytest.MonkeyPatch, at_or_below: int, expected: float
) -> None:
    """0.43 and 0.57 are inside the band, not outside it."""

    gates, readings, diagnostics = _gates_for(
        monkeypatch, _uniform(32, _Reading(at_or_below=at_or_below))
    )

    assert len(readings) == 32
    gate = _gate(gates, S1_GATE)
    # The comparison is only a boundary test if the observed value IS the boundary.
    assert gate.observed == expected
    assert diagnostics["mean_probability_integral_transform"] == expected
    assert gate.passes is True
    assert "inclusive" in gate.threshold


@pytest.mark.parametrize(
    ("bulk", "outlier", "bound", "direction"),
    [
        (4_300, 4_299, 0.43, "below"),
        (5_700, 5_701, 0.57, "above"),
    ],
)
def test_s1_fails_just_outside_a_bound(
    monkeypatch: pytest.MonkeyPatch, bulk: int, outlier: int, bound: float, direction: str
) -> None:
    """One fold moved by a ten-thousandth of a PIT is enough to fail the gate."""

    readings = _uniform(32, _Reading(at_or_below=bulk))
    readings[33] = _Reading(at_or_below=outlier)

    gates, _, _ = _gates_for(monkeypatch, readings)

    gate = _gate(gates, S1_GATE)
    assert gate.passes is False
    assert gate.observed != bound
    if direction == "below":
        assert gate.observed < bound
        assert bound - gate.observed < 1e-4
    else:
        assert gate.observed > bound
        assert gate.observed - bound < 1e-4


def test_s1_lower_bound_inclusivity_holds_at_thirty_seven_folds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An exactly-on-bound population passes even where the float mean is one ulp off.

    Thirty-seven folds is the real 2024-25 evaluation population, and 86/200 is a
    reachable per-fold PIT at the pre-registered 200 scenarios. Their exact mean is
    0.43, the pre-registered bound, which the amendment declares INCLUSIVE -- but
    ``numpy.mean`` sums thirty-seven copies to 0.42999999999999994, one ulp below the
    literal. A strict comparison would report a failure at exactly the pre-registered
    bound, and the protocol forbids a re-run, so the wrong verdict would stand. The
    runner's representation tolerance is what keeps the declared inclusivity here: the
    observed value is still reported raw, and it is still below the literal 0.43.
    """

    gates, readings, _ = _gates_for(
        monkeypatch,
        _uniform(37, _Reading(at_or_below=86, scores=SCORES_200)),
    )

    assert len(readings) == 37
    assert all(reading.probability_integral_transform == 0.43 for reading in readings)
    gate = _gate(gates, S1_GATE)
    # The observation is not rounded to hide the discrepancy; only the verdict tolerates it.
    assert gate.observed == 0.42999999999999994
    assert gate.observed < 0.43
    assert 0.43 - gate.observed < BOUND_TOLERANCE
    assert gate.passes is True


def test_s1_upper_bound_inclusivity_holds_at_thirty_folds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The same guarantee at the other end, at the smallest admissible population."""

    gates, readings, _ = _gates_for(
        monkeypatch,
        _uniform(30, _Reading(at_or_below=114, scores=SCORES_200)),
    )

    assert all(reading.probability_integral_transform == 0.57 for reading in readings)
    gate = _gate(gates, S1_GATE)
    assert gate.observed == 0.5700000000000001
    assert gate.observed > 0.57
    assert gate.observed - 0.57 < BOUND_TOLERANCE
    assert gate.passes is True


@pytest.mark.parametrize(
    ("fold_count", "at_or_below", "expected", "bound"),
    [
        (37, 84, 0.42, 0.43),
        (30, 116, 0.58, 0.57),
    ],
)
def test_the_bound_tolerance_does_not_widen_the_band(
    monkeypatch: pytest.MonkeyPatch,
    fold_count: int,
    at_or_below: int,
    expected: float,
    bound: float,
) -> None:
    """A mean clearly outside the band still fails, tolerance or no tolerance.

    The tolerance restores an inclusivity the amendment already declared; it is not a
    licence to pass a population that misses. One hundredth of a PIT -- the nearest
    thing to a near miss that 200 scenarios can produce -- is seven orders of magnitude
    larger than the tolerance, and it fails.
    """

    gates, readings, _ = _gates_for(
        monkeypatch,
        _uniform(fold_count, _Reading(at_or_below=at_or_below, scores=SCORES_200)),
    )

    assert len(readings) == fold_count
    gate = _gate(gates, S1_GATE)
    assert gate.observed == pytest.approx(expected)
    assert abs(gate.observed - bound) > 1_000_000 * BOUND_TOLERANCE
    assert gate.passes is False


# --------------------------------------------------------------------------------
# 2. S2: the tail-rate band is inclusive at both ends.
# --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("fold_count", "below_count", "expected", "passes"),
    [
        # 100 folds: both bounds exactly representable, nearest miss one hundredth away.
        (100, 4, 0.04, True),
        (100, 16, 0.16, True),
        (100, 3, 0.03, False),
        (100, 17, 0.17, False),
        # 50 folds: the smallest admissible population that represents 0.04 exactly.
        (50, 2, 0.04, True),
        (50, 8, 0.16, True),
        (50, 1, 0.02, False),
        (50, 9, 0.18, False),
    ],
)
def test_s2_tail_rate_band_is_inclusive_at_both_ends(
    monkeypatch: pytest.MonkeyPatch,
    fold_count: int,
    below_count: int,
    expected: float,
    passes: bool,
) -> None:
    """The bounds themselves pass; the nearest achievable rate on either side fails.

    The statistic is a fraction of folds, so how close a miss can get is 1/n and no
    closer. Unlike the mean PIT, this one is exact at every fold count: a sum of ones
    is exact, so a single correctly-rounded division lands on the same double as the
    literal bound.
    """

    readings = _uniform(fold_count, _Reading(at_or_below=5_000))
    for gameweek in range(2, 2 + below_count):
        readings[gameweek] = _Reading(at_or_below=5_000, below_lower_quantile=True)

    gates, folds, diagnostics = _gates_for(monkeypatch, readings)

    assert sum(1 for fold in folds if fold.below_lower_quantile) == below_count
    gate = _gate(gates, S2_GATE)
    assert gate.observed == expected
    assert diagnostics["realized_below_lower_quantile_rate"] == expected
    assert gate.passes is passes


def test_the_s2_threshold_names_q10_and_not_a_truncated_neighbour(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``int(0.10 * 100)`` truncates, so the recorded label is worth pinning."""

    gates, _, _ = _gates_for(monkeypatch, _uniform(30, _Reading(at_or_below=5_000)))

    threshold = _gate(gates, S2_GATE).threshold
    assert "q10" in threshold
    assert "q9" not in threshold
    assert "0.04" in threshold and "0.16" in threshold


@pytest.mark.parametrize(
    ("below_count", "passes"),
    [(1, False), (2, True), (5, True), (6, False)],
)
def test_the_s2_count_is_recorded_beside_the_rate_and_is_what_decides_the_gate(
    monkeypatch: pytest.MonkeyPatch, below_count: int, passes: bool
) -> None:
    """On the real 37-fold season the band [0.04, 0.16] is the count 2 to 5 inclusive.

    Clause 23 records the event count beside the rate because 37 folds cannot represent
    either bound: the attainable rates near the band are 1/37, 2/37, 5/37 and 6/37, so
    the gate a reader sees as a two-decimal interval is in truth an integer test. Both
    misses are checked as well as both hits, and neither miss is anywhere near the
    representation tolerance -- 6/37 clears the upper bound by about 0.0022, six orders
    of magnitude more than ``BOUND_TOLERANCE`` can excuse.
    """

    readings = _uniform(37, _Reading(at_or_below=5_000))
    for gameweek in range(2, 2 + below_count):
        readings[gameweek] = _Reading(at_or_below=5_000, below_lower_quantile=True)

    gates, folds, diagnostics = _gates_for(monkeypatch, readings)

    assert len(folds) == 37
    # The count is the honest statement of the granularity; the rate is derived from it.
    assert diagnostics["realized_below_lower_quantile_folds"] == float(below_count)
    assert diagnostics["realized_below_lower_quantile_rate"] == below_count / 37
    gate = _gate(gates, S2_GATE)
    assert gate.observed == below_count / 37
    assert gate.passes is passes
    if not passes:
        assert abs(gate.observed - (0.04 if below_count < 2 else 0.16)) > 1e6 * BOUND_TOLERANCE


def test_repeating_one_fold_is_refused_rather_than_inflating_the_population(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The sample floor counts distinct folds, because it refuses a repeated one.

    Without the guard, thirty copies of one gameweek would clear the thirty-fold
    minimum and produce a full S1/S2 verdict off a single measurement. The CLI builds
    its folds from ``walk_forward_decision_points``, which does not repeat one, so the
    binding run was never at risk; what is pinned here is that the runner refuses the
    population outright instead of scoring it and reporting ``evaluation_folds`` of 30.
    """

    collaborators = _KeyedCollaborators({2: _Reading(at_or_below=5_000)})
    collaborators.install(monkeypatch)

    thirty_copies = (_fold(2),) * 30
    with pytest.raises(SquadShadowError, match="repeats a fold"):
        evaluate_squad_gates(thirty_copies, _residuals(), PROVENANCE, _config(), _zero_shift())


def test_s2_verdict_is_independent_of_s1(monkeypatch: pytest.MonkeyPatch) -> None:
    """A passing tail rate does not rescue a failing PIT, and the two are separate."""

    readings = _uniform(100, _Reading(at_or_below=9_000))
    for gameweek in range(2, 6):
        readings[gameweek] = _Reading(at_or_below=9_000, below_lower_quantile=True)

    gates, _, _ = _gates_for(monkeypatch, readings)

    # Not an exact comparison: summing a hundred copies of 0.9 is the same pairwise
    # rounding the two ``..._inclusivity_holds_at_...`` tests record.
    assert _gate(gates, S1_GATE).observed == pytest.approx(0.9)
    assert _gate(gates, S1_GATE).passes is False
    assert _gate(gates, S2_GATE).observed == 0.04
    assert _gate(gates, S2_GATE).passes is True


# --------------------------------------------------------------------------------
# 3. Every pinned value refuses its nearest neighbour on either side.
# --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("knob", "value"),
    [
        ("scenario_count", 199),
        ("scenario_count", 201),
        ("scenario_count", 1_000),
        ("scenario_seed", 0),
        ("scenario_seed", 12),
        ("dispersion_scale", 1.1),
        ("dispersion_scale", 0.9),
        ("double_gameweek_scale", 1.3),
        ("double_gameweek_scale", 0.0),
        ("lower_quantile", 0.05),
        ("lower_quantile", 0.11),
        ("lower_quantile", 0.9),
        # Clauses 19 to 21: the three the generator used to inherit silently.
        ("min_player_observations", 7),
        ("min_player_observations", 9),
        ("player_scale_shrinkage", math.nextafter(10.0, math.inf)),
        ("player_scale_shrinkage", 0.0),
        ("player_location_shrinkage", 0.0),
        ("player_location_shrinkage", 10.0),
        # The two summaries no gate reads, and the diagnostic bootstrap's three.
        ("worst_fraction", 0.09),
        ("worst_fraction", 0.11),
        ("points_threshold", 39.5),
        ("points_threshold", 40.5),
        ("bootstrap_resamples", 4_999),
        ("bootstrap_resamples", 5_001),
        ("bootstrap_seed", 1),
        ("confidence_level", 0.95),
        ("confidence_level", math.nextafter(0.90, 1.0)),
    ],
)
def test_a_pinned_knob_may_not_be_given_another_value(knob: str, value: object) -> None:
    """One step from a pre-registered constant, in either direction, is refused.

    The knobs no gate reads are here too. They are pinned precisely because they are
    uninteresting today: a later protocol that does read ``worst_fraction`` or the
    bootstrap interval must not be able to claim this run's numbers were taken under
    values of its own choosing.
    """

    with pytest.raises(SquadShadowError, match="is pre-registered at"):
        _config(**{knob: value})


def test_the_pinned_knobs_hold_their_amendment_values(monkeypatch: pytest.MonkeyPatch) -> None:
    """The defaults are the amendment's numbers, and they reach the generator."""

    config = _config()
    assert (config.scenario_count, config.scenario_seed) == (200, 11)
    assert (config.dispersion_scale, config.double_gameweek_scale) == (1.0, 1.0)
    assert config.lower_quantile == 0.10
    assert (config.worst_fraction, config.points_threshold) == (0.10, 40.0)
    assert (config.bootstrap_resamples, config.bootstrap_seed) == (5_000, 0)
    assert config.confidence_level == 0.90

    collaborators = _KeyedCollaborators(_uniform(1, _Reading(at_or_below=100)))
    collaborators.install(monkeypatch)
    evaluate_squad_gates((_fold(2),), _residuals(), PROVENANCE, config, _zero_shift())

    generated = collaborators.scenario_configs[0]
    assert generated.scenario_count == 200
    assert generated.deterministic_seed == 11
    assert generated.double_gameweek_scale == 1.0
    assert generated.min_history_folds == 8
    evaluated = collaborators.evaluation_configs[0]
    assert evaluated.lower_quantile == 0.10
    assert evaluated.dispersion_scale == 1.0
    # Pinned and passed on even though neither gate reads them: a value that is declared
    # but not handed over would be a declaration about a run that did not happen.
    assert evaluated.worst_fraction == 0.10
    assert evaluated.points_threshold == 40.0


def test_the_three_formerly_inherited_generator_knobs_are_now_declared(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The finding this test used to record has been closed by the second amendment.

    ``min_player_observations``, ``player_scale_shrinkage`` and
    ``player_location_shrinkage`` reached the generator as ``ScenarioConfig`` library
    defaults: all three change the scenario spread, hence the PIT and the tail rate, and
    none of them was declared anywhere. Clauses 19 to 21 pin them at exactly the library
    canon and ``_scenario_config`` now names them. Two things are pinned here as a
    result -- that the declared value is what the generator is actually handed, and that
    it still equals the library's own, so a library-side change breaks this test loudly
    instead of moving a gate underneath the protocol.
    """

    collaborators = _KeyedCollaborators(_uniform(1, _Reading(at_or_below=100)))
    collaborators.install(monkeypatch)
    evaluate_squad_gates((_fold(2),), _residuals(), PROVENANCE, _config(), _zero_shift())

    generated = collaborators.scenario_configs[0]
    assert generated.min_player_observations == 8
    assert generated.player_scale_shrinkage == 10.0
    assert generated.player_location_shrinkage is None
    library = ScenarioConfig()
    assert generated.min_player_observations == library.min_player_observations
    assert generated.player_scale_shrinkage == library.player_scale_shrinkage
    assert generated.player_location_shrinkage == library.player_location_shrinkage


def test_the_declared_parameters_record_every_field_at_its_pre_registered_type() -> None:
    """Clause 24: the provenance strings, read off the objects the run constructs.

    A parameter is only pre-registered if a reader of the artifact can see which value
    it took, and the string is where the pinned *type* becomes visible: ``10`` and
    ``10.0`` are the same number and different provenance. The key set is compared
    against the three configurations' own fields rather than a literal list, because a
    hand-kept list is the failure clause 24 exists to prevent -- a field added upstream
    would drop out of the artifact silently.
    """

    parameters = declared_parameters(_config(), shift_points=-7.5)

    assert parameters["generator_min_player_observations"] == "8"
    assert parameters["generator_player_scale_shrinkage"] == "10.0"
    assert parameters["generator_player_location_shrinkage"] == "None"
    assert parameters["optimizer_bench_weight"] == "0.1"
    # The decision universe belongs to no library configuration, so only the protocol's
    # own object carries it; recording just the three constructed ones would lose it.
    assert parameters["protocol_decision_universe"] == "full_roster"
    # The fitted shift is a parameter of the evaluation too, at full precision.
    assert parameters["evaluation_location_shift_points"] == "-7.5"
    # Recorded although the amendment leaves it open: a wall-clock limit that could in
    # principle change a squad under load is exactly what a reader needs to see.
    assert parameters["optimizer_solver_time_limit_seconds"] == "10.0"

    # The fifth configuration decides the projections, therefore the squad, therefore
    # both gates; it reached nothing until an adversarial read of the runner found it.
    assert parameters["projection_prior_gameweek_equivalent"] == "6"
    assert parameters["projection_prior_minute_equivalent"] == "270"
    # And two numbers that belong to no configuration object at all: the tolerance the
    # bands are read with, and the rule that decides which gameweeks are folds.
    assert parameters["protocol_bound_tolerance"] == "1e-09"
    assert parameters["protocol_min_prior_gameweeks_in_season"] == "1"

    expected = {
        f"{prefix}_{entry.name}"
        for prefix, settings in (
            ("protocol", SquadShadowConfig()),
            ("generator", ScenarioConfig()),
            ("evaluation", ScenarioEvaluationConfig()),
            ("optimizer", OptimizationConfig()),
            ("projection", InSeasonBlendConfig()),
        )
        for entry in fields(settings)
    } | {
        "protocol_bound_tolerance",
        "protocol_min_prior_gameweeks_in_season",
        "protocol_fit_seasons",
        "protocol_evaluation_season",
        "protocol_s1_bounds",
        "protocol_s2_bounds",
    }
    assert set(parameters) == expected


def test_min_evaluation_folds_is_pinned_and_cannot_lower_the_sample_floor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The sample floor is a constant, not a caller-chosen number.

    ``MIN_EVALUATION_FOLDS`` is declared beside the pinned knobs as one of "the
    squad-gate amendment's own numbers -- constants, not parameters", and the
    pinned-value loop now checks it like the rest. A caller who set it to one would be
    reading a full S1/S2 verdict off a single fold; that request is refused at
    configuration time, and a one-fold population still yields no gates at all.
    """

    with pytest.raises(SquadShadowError, match="is pre-registered at"):
        _config(min_evaluation_folds=1)

    assert _config().min_evaluation_folds == 30

    one_fold = _uniform(1, _Reading(at_or_below=5_000))
    gates, readings, diagnostics = _gates_for(monkeypatch, one_fold)

    assert len(readings) == 1
    assert gates == ()
    assert "mean_probability_integral_transform" not in diagnostics


def test_min_evaluation_folds_refuses_a_meaningless_floor() -> None:
    """The same guarantee at its extreme: zero and a negative are refused too."""

    for floor in (0, -5):
        with pytest.raises(SquadShadowError, match="is pre-registered at"):
            _config(min_evaluation_folds=floor)


# --------------------------------------------------------------------------------
# 4. The three formerly open controls: pinned, not ranged.
# --------------------------------------------------------------------------------


def test_no_control_is_a_required_argument_any_more() -> None:
    """``SquadShadowConfig()`` is the whole protocol, and every field is pinned.

    These three used to have no default at all: a run that could not name them did not
    start, and this test proved that omitting any of them was a ``TypeError``. Clauses
    16 to 18 fixed all three, and the rule that replaced the requirement is stronger
    rather than kinder -- naming them is not optional, it is pointless, because the only
    value each accepts is the pre-registered one. What has to be pinned now is that no
    field can drift back into being open: a field added later without a default would
    make the protocol configurable again, and one added with a default nobody checks
    would be a control nobody pre-registered.
    """

    for entry in fields(SquadShadowConfig):
        assert entry.default is not MISSING or entry.default_factory is not MISSING

    config = SquadShadowConfig()
    assert (config.bench_weight, config.decision_universe, config.min_history_folds) == (
        0.1,
        "full_roster",
        8,
    )
    assert (config.min_player_observations, config.player_scale_shrinkage) == (8, 10.0)
    assert config.player_location_shrinkage is None


@pytest.mark.parametrize(
    "bench_weight",
    [
        0.0,
        0.5,
        1.0,
        math.nextafter(0.1, math.inf),
        math.nextafter(0.1, 0.0),
        0.11,
        2.0,
        -0.5,
        float("nan"),
        float("inf"),
        True,
        0,
        1,
        "0.1",
        None,
    ],
)
def test_a_bench_weight_other_than_the_pinned_one_is_refused(bench_weight: object) -> None:
    """Every value the old range rule accepted is refused now, one ulp included.

    ``bench_weight`` was "any float in [0, 1]", which is a control a run could choose
    after seeing what it did to a gate; clause 16 fixes it at the live optimizer's own
    default of 0.1. So 0.0 -- the scenario audit's weight -- along with 0.5 and 1.0 were
    admissible and are not any more, and the two neighbours of 0.1 are here because a
    pinning rule is only worth the name if it refuses the closest representable miss.
    """

    with pytest.raises(SquadShadowError, match="is pre-registered at"):
        _config(bench_weight=bench_weight)


def test_the_pinned_bench_weight_reaches_the_optimizer_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A pinned control is only honest if the value declared is the value used."""

    collaborators = _KeyedCollaborators(_uniform(2, _Reading(at_or_below=100)))
    collaborators.install(monkeypatch)
    evaluate_squad_gates(_folds(2), _residuals(), PROVENANCE, _config(), _zero_shift())

    assert [config.bench_weight for config in collaborators.optimization_configs] == [0.1, 0.1]
    # Clause 16 names the product's own default as the reason for the number, so the
    # two have to keep agreeing: a change to the optimizer's default is a change to the
    # weight the pre-registration was written about.
    assert _config().bench_weight == OptimizationConfig().bench_weight


@pytest.mark.parametrize(
    "universe",
    ["", "FULL_ROSTER", "full-roster", "full_roster ", "candidate pool", "starting_xi", None, 0],
)
def test_a_decision_universe_other_than_the_pinned_one_is_refused(universe: object) -> None:
    """The check is exact equality, so casing, spacing and separators all miss."""

    with pytest.raises(SquadShadowError, match="is pre-registered at"):
        _config(decision_universe=universe)


def test_the_candidate_pool_decision_universe_is_refused_as_not_pre_registered() -> None:
    """The one alternative the first amendment named is now refused by name.

    ``candidate_pool`` was the other universe the amendment listed, so the old range
    check had to admit the spelling and a separate rule refused it as unimplemented.
    Clause 17 fixes the universe at the full roster -- the product's real selection
    space -- and a reduced pool is recorded there as "a different problem with a
    different answer". One refusal now covers both: the name is not the pre-registered
    one, so a run cannot declare a universe it would not have chosen over.
    """

    with pytest.raises(SquadShadowError, match="is pre-registered at"):
        _config(decision_universe="candidate_pool")


@pytest.mark.parametrize(
    "min_history_folds",
    [7, 9, 2, 3, 40, 1, 0, -1, -8, True, False, 8.0, 8.5, "8", None],
)
def test_a_min_history_folds_other_than_eight_is_refused(min_history_folds: object) -> None:
    """The generator's floor of 2 used to be the boundary; the pinned 8 is the boundary now.

    2, 3 and 40 were all admissible under "an integer of at least 2" and are refused
    here, as are 7 and 9 on either side of the pinned value. ``8.0`` is refused too
    although it equals 8: the amendment pre-registered the canonical ``int`` default of
    ``ScenarioConfig``, and a float writes a different string into the artifact.
    """

    with pytest.raises(SquadShadowError, match="is pre-registered at"):
        _config(min_history_folds=min_history_folds)


def test_min_history_folds_of_one_is_refused_at_configuration_time() -> None:
    """The refusal still comes before the run, which is what keeps it a refusal.

    The pinning subsumes the old floor of 2 -- nothing but 8 is admissible, so 1 can no
    longer reach the generator -- but *where* it is refused still matters. Were
    ``SquadShadowConfig`` to accept 1, the mismatch would surface as a
    ``ScenarioConfigurationError`` raised from inside the first fold, long after the
    panel had been loaded, and that class is not a ``SquadShadowError``, so the CLI's
    own refusal handler would not catch it and the run would die mid-flight on an
    exception it cannot turn into a refusal. Refusing while the config is being built is
    what stops that: the run never starts.
    """

    with pytest.raises(SquadShadowError, match="is pre-registered at"):
        _config(min_history_folds=1)

    # The downstream floor this one anticipates, and why anticipating it is necessary.
    with pytest.raises(ScenarioConfigurationError, match="min_history_folds"):
        ScenarioConfig(min_history_folds=1)
    assert not isinstance(ScenarioConfigurationError("x"), SquadShadowError)


@pytest.mark.parametrize(
    ("knob", "value"),
    [
        ("player_scale_shrinkage", 10),
        ("points_threshold", 40),
        ("dispersion_scale", 1),
        ("double_gameweek_scale", 1),
        ("min_history_folds", 8.0),
        ("min_player_observations", 8.0),
        ("bootstrap_resamples", 5_000.0),
    ],
)
def test_a_value_of_the_wrong_type_is_refused_even_where_python_calls_it_equal(
    knob: str, value: object
) -> None:
    """``10 == 10.0`` is true and ``repr(10) == repr(10.0)`` is not.

    Equality alone would admit every one of these, and the run would then record a
    provenance string the amendment never wrote. Two runs whose artifacts disagree on
    ``10`` against ``10.0`` are indistinguishable as measurements and distinguishable as
    files, which is the worst of both: the create-once writer would call them a
    conflict, and a reader could not say which parameter had actually moved.
    """

    with pytest.raises(SquadShadowError, match="is pre-registered at"):
        _config(**{knob: value})


def test_a_numpy_float_is_refused_although_it_equals_the_pinned_weight() -> None:
    """The subclass case, which an ``isinstance`` check would have let through.

    ``numpy.float64`` subclasses ``float`` and compares equal to 0.1, so it satisfies
    both a type test and an equality test -- yet it is exactly what the check was
    written for: the artifact would read ``np.float64(0.1)`` where every other run
    reads ``0.1``. It is a reachable value rather than a contrived one, since anything
    taken from a DataFrame column or a numpy array arrives as one, so two runs under
    the identical pre-registered weight would write different artifacts and read as a
    conflict to the create-once writer. The check demands the exact type for that
    reason, and this is the case that proves it.
    """

    assert isinstance(np.float64(0.1), float)
    assert np.float64(0.1) == 0.1
    with pytest.raises(SquadShadowError, match=r"pre-registered at 0.1"):
        _config(bench_weight=np.float64(0.1))


@pytest.mark.parametrize("seed", [False, True])
def test_a_boolean_is_refused_where_an_integer_seed_is_pre_registered(seed: bool) -> None:
    """``False`` is the sharp end of this one: it *is* the pre-registered value.

    ``bootstrap_seed`` is pinned at 0, and ``False == 0`` while ``isinstance(False, int)``
    is ``True`` -- so an equality check and an ``isinstance`` check would both pass it,
    and only the demand for the exact type refuses it. ``True`` is caught by the value
    as well. A seed recorded as ``False`` is a seed no one can re-run from.
    """

    with pytest.raises(SquadShadowError, match="is pre-registered at"):
        _config(bootstrap_seed=seed)


# --------------------------------------------------------------------------------
# 5. The shift's sign and value.
# --------------------------------------------------------------------------------


def _fit_folds(gameweeks: Sequence[int]) -> tuple[SquadFold, ...]:
    return tuple(_fold(gameweek, season=FIT_SEASONS[0]) for gameweek in gameweeks)


def test_the_frozen_shift_is_the_negated_mean_gap_and_is_negative_when_optimistic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two folds, two different gaps: shift == -mean(raw scenario mean - realized)."""

    readings = {
        2: _Reading(at_or_below=51, raw_mean=60.0),
        3: _Reading(at_or_below=46, raw_mean=50.0),
    }
    collaborators = _KeyedCollaborators(readings)
    collaborators.install(monkeypatch)

    shift = fit_frozen_shift(_fit_folds((2, 3)), _residuals(), PROVENANCE, _config())

    # realized are 50.0 and 45.0, so the raw gaps are +10.0 and +5.0.
    assert shift.shift_points == -7.5
    assert shift.shift_points == -((10.0 + 5.0) / 2.0)
    assert shift.shift_points < 0.0
    assert shift.fold_count == 2
    assert EVALUATION_SEASON not in shift.seasons


def test_the_frozen_shift_is_positive_when_the_scenario_mean_is_pessimistic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    readings = {
        2: _Reading(at_or_below=61, raw_mean=48.0),
        3: _Reading(at_or_below=41, raw_mean=38.0),
    }
    collaborators = _KeyedCollaborators(readings)
    collaborators.install(monkeypatch)

    shift = fit_frozen_shift(_fit_folds((2, 3)), _residuals(), PROVENANCE, _config())

    # realized are 60.0 and 40.0, so the raw gaps are -12.0 and -2.0.
    assert shift.shift_points == 7.0


def test_a_single_fold_shift_is_exactly_that_folds_negated_gap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    collaborators = _KeyedCollaborators({2: _Reading(at_or_below=101, raw_mean=103.25)})
    collaborators.install(monkeypatch)

    shift = fit_frozen_shift(_fit_folds((2,)), _residuals(), PROVENANCE, _config())

    assert shift.shift_points == -(103.25 - 100.0)


def test_the_pre_shift_mean_survives_the_fit_at_full_double_precision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``float(str(raw))`` must round-trip: a shift is not allowed to lose digits."""

    awkward = 0.1 + 0.2
    assert awkward != 0.3
    collaborators = _KeyedCollaborators({2: _Reading(at_or_below=1, raw_mean=awkward)})
    collaborators.install(monkeypatch)

    shift = fit_frozen_shift(_fit_folds((2,)), _residuals(), PROVENANCE, _config())

    assert shift.shift_points == -awkward
    assert shift.shift_points != -0.3


def test_a_pre_shift_mean_of_exactly_zero_is_a_value_and_not_a_miss(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Zero is a measurement; only an absent term is refused."""

    collaborators = _KeyedCollaborators({2: _Reading(at_or_below=11, raw_mean=0.0)})
    collaborators.install(monkeypatch)

    shift = fit_frozen_shift(_fit_folds((2,)), _residuals(), PROVENANCE, _config())

    assert shift.shift_points == 10.0


def test_an_absent_pre_shift_mean_is_refused_rather_than_read_as_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    collaborators = _KeyedCollaborators(
        {2: _Reading(at_or_below=11, raw_mean=0.0, omit_raw_mean=True)}
    )
    collaborators.install(monkeypatch)

    with pytest.raises(SquadShadowError, match="reported no pre-shift mean"):
        fit_frozen_shift(_fit_folds((2,)), _residuals(), PROVENANCE, _config())


@pytest.mark.parametrize("raw_mean", [float("nan"), float("inf"), float("-inf")])
def test_a_non_finite_pre_shift_mean_cannot_enter_the_shift(
    monkeypatch: pytest.MonkeyPatch, raw_mean: float
) -> None:
    collaborators = _KeyedCollaborators({2: _Reading(at_or_below=11, raw_mean=raw_mean)})
    collaborators.install(monkeypatch)

    with pytest.raises(SquadShadowError, match="non-finite score cannot enter"):
        fit_frozen_shift(_fit_folds((2,)), _residuals(), PROVENANCE, _config())


def test_the_fit_runs_at_zero_shift_and_the_evaluation_applies_the_fitted_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The fitted quantity is the gap a zero-shift evaluation leaves, and only that."""

    collaborators = _KeyedCollaborators({2: _Reading(at_or_below=51, raw_mean=60.0)})
    collaborators.install(monkeypatch)
    fit_frozen_shift(_fit_folds((2,)), _residuals(), PROVENANCE, _config())

    assert [c.location_shift_points for c in collaborators.evaluation_configs] == [0.0]

    applied = FrozenShift(
        shift_points=-7.5,
        fold_count=2,
        first_fold_id="2021-22-gw02",
        last_fold_id="2021-22-gw03",
        seasons=("2021-22",),
    )
    evaluating = _KeyedCollaborators(_uniform(2, _Reading(at_or_below=100)))
    evaluating.install(monkeypatch)
    evaluate_squad_gates(_folds(2), _residuals(), PROVENANCE, _config(), applied)

    assert [c.location_shift_points for c in evaluating.evaluation_configs] == [-7.5, -7.5]
    assert all(c.dispersion_scale == 1.0 for c in evaluating.evaluation_configs)


# --------------------------------------------------------------------------------
# 6. The sample floor sits exactly between 29 and 30.
# --------------------------------------------------------------------------------


def test_twenty_nine_evaluation_folds_produce_no_gate_and_no_diagnostic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gates, readings, diagnostics = _gates_for(
        monkeypatch, _uniform(29, _Reading(at_or_below=5_000))
    )

    assert gates == ()
    assert len(readings) == 29
    assert diagnostics["evaluation_folds"] == 29.0
    assert "mean_probability_integral_transform" not in diagnostics
    assert "realized_below_lower_quantile_rate" not in diagnostics


def test_thirty_evaluation_folds_produce_both_gates(monkeypatch: pytest.MonkeyPatch) -> None:
    gates, readings, diagnostics = _gates_for(
        monkeypatch, _uniform(30, _Reading(at_or_below=5_000))
    )

    assert len(readings) == 30
    assert [gate.gate for gate in gates] == [S1_GATE, S2_GATE]
    assert diagnostics["evaluation_folds"] == 30.0
    assert diagnostics["mean_probability_integral_transform"] == 0.5
    assert diagnostics["realized_below_lower_quantile_rate"] == 0.0


# --------------------------------------------------------------------------------
# 7 and 8. Which q10, and which inequality.
# --------------------------------------------------------------------------------

#: Five scenario scores on which the quantile conventions visibly disagree: numpy's
#: linear interpolation puts q10 at 4.0, every rank-based rule puts it at 0.0.
DIVERGENT_SCORES = (0.0, 10.0, 20.0, 30.0, 40.0)


def _real_decision() -> OptimizationResult:
    """A hand-built feasible decision -- no solver, but a genuine result object."""

    return OptimizationResult(
        solver_status=SolverStatus.OPTIMAL,
        selected_squad=PLAYERS.loc[PLAYERS["player_id"] <= 4].reset_index(drop=True),
        starting_xi=PLAYERS.loc[PLAYERS["player_id"] <= 3].reset_index(drop=True),
        bench=PLAYERS.loc[PLAYERS["player_id"] == 4].reset_index(drop=True),
        captain=PLAYERS.loc[PLAYERS["player_id"] == 1].iloc[0],
        total_cost_tenths=230,
        projected_score=7.0,
        objective_value=7.0,
        diagnostics={},
    )


def _real_scenarios() -> ScenarioSet:
    """A genuine ``ScenarioSet`` whose fixed-decision scores are ``DIVERGENT_SCORES``.

    Only player 2 varies, and player 2 is a non-captain starter, so the decision's
    score in each scenario is that player's own number.
    """

    snapshot = prepare_optimizer_projection(
        PLAYERS.loc[:, ["player_id", "name", "team_id", "position", "price_tenths"]],
        PLAYERS.loc[:, ["player_id", "expected_points"]],
        PROVENANCE,
    )
    config = ScenarioConfig(scenario_count=5, deterministic_seed=11, min_history_folds=2)
    scenario_ids = tuple(f"scenario-{index:06d}" for index in range(5))
    source_fold_ids = ("2023-24-gw10",) * 5
    matrix = pd.DataFrame(
        {
            1: [0.0] * 5,
            2: list(DIVERGENT_SCORES),
            3: [0.0] * 5,
            4: [0.0] * 5,
            5: [0.0] * 5,
        },
        index=list(scenario_ids),
    )
    target = ScenarioTarget(EVALUATION_SEASON, 8)
    return ScenarioSet(
        projections=snapshot,
        target=target,
        config=config,
        scenario_ids=scenario_ids,
        source_fold_ids=source_fold_ids,
        scenario_points=matrix,
        scenario_fingerprint=_scenario_fingerprint(
            snapshot, target, config, scenario_ids, source_fold_ids, matrix
        ),
    )


def _read_with_the_real_evaluator(monkeypatch: pytest.MonkeyPatch, realized: float) -> Any:
    """One fold read through the real ``evaluate_fixed_decision``.

    Only the inputs are faked: the decision, the scenario set and the realized score.
    The quantile and the below-q10 flag come from the production code path.
    """

    scenarios = _real_scenarios()
    monkeypatch.setattr(module, "optimize_squad", lambda frame, config: _real_decision())
    monkeypatch.setattr(
        module,
        "generate_scenarios",
        lambda snapshot, history, target, config, **kwargs: scenarios,
    )
    monkeypatch.setattr(module, "score_realized_squad_points", lambda decision, points: realized)
    _, readings, _ = evaluate_squad_gates(
        (_fold(8),), _residuals(), PROVENANCE, _config(), _zero_shift()
    )
    assert len(readings) == 1
    return readings[0]


def test_the_lower_quantile_is_numpy_linear_interpolation_not_a_rank_rule(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """q10 of (0, 10, 20, 30, 40) is 4.0 by interpolation and 0.0 by every rank rule."""

    reading = _read_with_the_real_evaluator(monkeypatch, realized=100.0)

    scores = np.asarray(DIVERGENT_SCORES)
    assert reading.lower_quantile_score == 4.0
    assert reading.lower_quantile_score == float(np.quantile(scores, 0.10, method="linear"))
    for rank_rule in ("inverted_cdf", "nearest", "lower", "closest_observation"):
        assert float(np.quantile(scores, 0.10, method=rank_rule)) == 0.0
        assert reading.lower_quantile_score != float(np.quantile(scores, 0.10, method=rank_rule))
    assert reading.lower_quantile_score not in scores.tolist()


@pytest.mark.parametrize(
    ("realized", "below"),
    [
        (4.0, False),
        (math.nextafter(4.0, math.inf), False),
        (4.000001, False),
        (math.nextafter(4.0, -math.inf), True),
        (3.999999, True),
        (0.0, True),
    ],
)
def test_below_the_lower_quantile_is_a_strict_inequality(
    monkeypatch: pytest.MonkeyPatch, realized: float, below: bool
) -> None:
    """A realized score exactly on q10 is not below it; one ulp under it is."""

    reading = _read_with_the_real_evaluator(monkeypatch, realized=realized)

    assert reading.lower_quantile_score == 4.0
    assert reading.below_lower_quantile is below


def test_the_runner_reads_the_evaluators_quantile_rather_than_recomputing_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The reading carries ``metrics.lower_quantile_score`` verbatim.

    The fake evaluator returns a q10 that no rule would derive from its own scores, so
    a runner that recomputed the quantile from ``scenario_scores`` would disagree.
    """

    readings_by_gameweek = {
        2: _Reading(at_or_below=5_000, scores=DIVERGENT_SCORES, below_lower_quantile=True)
    }
    collaborators = _KeyedCollaborators(readings_by_gameweek)
    collaborators.install(monkeypatch)
    _, readings, _ = evaluate_squad_gates(
        (_fold(2),), _residuals(), PROVENANCE, _config(), _zero_shift()
    )

    stated = readings_by_gameweek[2].lower_quantile
    reading_value = readings[0].lower_quantile_score
    assert reading_value == stated
    assert reading_value != float(np.quantile(np.asarray(DIVERGENT_SCORES), 0.10))


def test_the_pit_counts_a_scenario_equal_to_the_realized_score(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The PIT is the empirical CDF at the realized score: ties count as at-or-below."""

    on_a_scenario = _read_with_the_real_evaluator(monkeypatch, realized=20.0)
    just_under = _read_with_the_real_evaluator(monkeypatch, realized=math.nextafter(20.0, 0.0))

    assert on_a_scenario.probability_integral_transform == 0.6
    assert just_under.probability_integral_transform == 0.4


def test_a_realized_score_below_every_scenario_gives_a_zero_pit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reading = _read_with_the_real_evaluator(monkeypatch, realized=-1.0)

    assert reading.probability_integral_transform == 0.0
    assert reading.below_lower_quantile is True


def test_a_realized_score_above_every_scenario_gives_a_unit_pit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reading = _read_with_the_real_evaluator(monkeypatch, realized=1_000.0)

    assert reading.probability_integral_transform == 1.0
    assert reading.below_lower_quantile is False
