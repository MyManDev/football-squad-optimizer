"""Fixed-decision scoring over a joint scenario matrix."""

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from numbers import Integral
from types import MappingProxyType

import numpy as np

from squadopt.optimization import OptimizationResult
from squadopt.scenarios.models import (
    ScenarioEvaluationConfig,
    ScenarioEvaluationResult,
    ScenarioRiskMetrics,
    ScenarioSet,
    ScenarioValidationError,
)


def _typed_identifier(value: object) -> dict[str, object]:
    if isinstance(value, Integral) and not isinstance(value, bool):
        return {"kind": "integer", "value": int(value)}
    return {"kind": "string", "value": str(value)}


def _decision_fingerprint(result: OptimizationResult) -> str:
    assert result.captain is not None
    payload = {
        "squad": [_typed_identifier(value) for value in result.selected_squad["player_id"]],
        "starting_xi": [_typed_identifier(value) for value in result.starting_xi["player_id"]],
        "captain": _typed_identifier(result.captain["player_id"]),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def wilson_interval(
    successes: int, trials: int, *, confidence: float = 0.90
) -> tuple[float, float]:
    """Wilson score interval for a probability read off ``trials`` scenarios.

    A probability read off a finite scenario set carries sampling error of its own,
    before any model error; the interval says how much of a "0.14" is the scenario
    count. Two-sided at ``confidence`` (0.90 → z ≈ 1.6449).
    """

    if trials <= 0:
        raise ScenarioValidationError("wilson_interval needs at least one trial.")
    if not 0 <= successes <= trials:
        raise ScenarioValidationError("successes must lie between 0 and trials.")
    z = {0.90: 1.6448536269514722, 0.95: 1.959963984540054}.get(confidence)
    if z is None:
        raise ScenarioValidationError("confidence must be 0.90 or 0.95.")
    p_hat = successes / trials
    denominator = 1.0 + z * z / trials
    centre = (p_hat + z * z / (2 * trials)) / denominator
    half = (
        z * math.sqrt(p_hat * (1.0 - p_hat) / trials + z * z / (4 * trials * trials)) / denominator
    )
    lower = 0.0 if successes == 0 else max(0.0, centre - half)
    upper = 1.0 if successes == trials else min(1.0, centre + half)
    return (lower, upper)


def evaluate_fixed_decision(
    optimization_result: OptimizationResult,
    scenarios: ScenarioSet,
    config: ScenarioEvaluationConfig | None = None,
) -> ScenarioEvaluationResult:
    """Score one already-frozen starting XI and captain without reoptimization."""

    settings = ScenarioEvaluationConfig() if config is None else config
    if not isinstance(settings, ScenarioEvaluationConfig):
        raise ScenarioValidationError("config must be a ScenarioEvaluationConfig.")
    if not isinstance(optimization_result, OptimizationResult):
        raise ScenarioValidationError("optimization_result must be an OptimizationResult.")
    if not optimization_result.has_solution:
        raise ScenarioValidationError(
            "Scenario evaluation requires an OPTIMAL or FEASIBLE fixed decision."
        )
    if optimization_result.captain is None:
        raise ScenarioValidationError("A feasible fixed decision must contain a captain.")
    if not isinstance(scenarios, ScenarioSet):
        raise ScenarioValidationError("scenarios must be a ScenarioSet.")
    verified = scenarios.validated_copy()
    player_ids = verified.projections.table["player_id"].tolist()
    player_column = {player_id: index for index, player_id in enumerate(player_ids)}
    starter_ids = optimization_result.starting_xi["player_id"].tolist()
    captain_id = optimization_result.captain["player_id"]
    required = list(dict.fromkeys([*starter_ids, captain_id]))
    missing = [player_id for player_id in required if player_id not in player_column]
    if missing:
        raise ScenarioValidationError(
            "Scenario players must cover every selected starter and captain; "
            f"missing={missing[:10]!r}."
        )
    starter_columns = [player_column[player_id] for player_id in starter_ids]
    captain_column = player_column[captain_id]
    matrix = verified.scenario_points.to_numpy(dtype="float64", copy=False)
    raw_scores = matrix[:, starter_columns].sum(axis=1) + matrix[:, captain_column]
    # The decision-level correction: the chosen squad's projections are optimistic by
    # construction, so its honest distribution is the raw one shifted by the measured
    # selection optimism (negative), which the caller states in the config.
    raw_mean = float(raw_scores.mean())
    scores = (
        raw_mean
        + settings.dispersion_scale * (raw_scores - raw_mean)
        + settings.location_shift_points
    )

    projections = verified.projections.table.set_index("player_id")["expected_points"]
    point_score = float(projections.loc[starter_ids].sum() + projections.loc[captain_id])
    worst_count = max(1, math.ceil(settings.worst_fraction * len(scores)))
    ordered = np.sort(scores)
    lower_quantile = float(np.quantile(scores, settings.lower_quantile, method="linear"))
    metrics = ScenarioRiskMetrics(
        scenario_count=len(scores),
        point_projection_score=point_score,
        mean_score=float(scores.mean()),
        score_standard_deviation=float(scores.std(ddof=0)),
        lower_quantile_probability=settings.lower_quantile,
        lower_quantile_score=lower_quantile,
        worst_fraction=settings.worst_fraction,
        worst_fraction_count=worst_count,
        mean_worst_fraction_score=float(ordered[:worst_count].mean()),
        minimum_score=float(ordered[0]),
        points_threshold=settings.points_threshold,
        probability_below_threshold=float((scores < settings.points_threshold).mean()),
    )
    return ScenarioEvaluationResult(
        scenario_fingerprint=verified.scenario_fingerprint,
        scenario_scores=tuple(float(value) for value in scores),
        metrics=metrics,
        diagnostics={
            "decision_fingerprint": _decision_fingerprint(optimization_result),
            "scoring_policy": "starting_xi_plus_captain_double_v1",
            "bench_points_included": False,
            "location_shift_points": settings.location_shift_points,
            "dispersion_scale": settings.dispersion_scale,
            "mean_score_before_shift": raw_mean,
            "standard_deviation_before_scale": float(raw_scores.std(ddof=0)),
            "probability_below_threshold_interval": wilson_interval(
                int((scores < settings.points_threshold).sum()), len(scores)
            ),
            "decision_reoptimized_per_scenario": False,
            "standard_deviation": "population",
            "quantile_interpolation": "linear",
            "worst_fraction_count_rule": "ceil",
            "threshold_comparison": "strictly_below",
        },
    )


@dataclass(frozen=True, slots=True)
class RivalSquad:
    """Another manager's fielded eleven and captain, as the capture showed them."""

    label: str
    starter_ids: tuple[object, ...]
    captain_id: object

    def __post_init__(self) -> None:
        if not isinstance(self.label, str) or not self.label.strip():
            raise ScenarioValidationError("A rival squad needs a non-empty label.")
        starters = tuple(self.starter_ids)
        if len(starters) != len(set(starters)) or not starters:
            raise ScenarioValidationError(
                "A rival squad's starters must be distinct and non-empty."
            )
        if self.captain_id not in starters:
            raise ScenarioValidationError("A rival squad's captain must be one of its starters.")
        object.__setattr__(self, "starter_ids", starters)


@dataclass(frozen=True, slots=True)
class ScenarioComparisonResult:
    """My fixed decision against one rival squad under the same scenarios."""

    rival_label: str
    scenario_count: int
    probability_ahead: float
    probability_ahead_interval: tuple[float, float]
    probability_level: float
    mean_difference: float
    difference_quantiles: Mapping[str, float]
    shared_starters: int
    diagnostics: Mapping[str, object]

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "difference_quantiles", MappingProxyType(dict(self.difference_quantiles))
        )
        object.__setattr__(self, "diagnostics", MappingProxyType(dict(self.diagnostics)))


@dataclass(frozen=True, slots=True)
class AnchoredClaim:
    """A windowed P(ahead of the crowd), built through the risk-neutral anchor.

    ``candidate - crowd`` is decomposed as ``(candidate - anchor)`` under the scenario
    draws plus ``(anchor - crowd)`` resampled from the measured weekly edge series —
    the scenario-implied gap to the crowd, which `rival_calibration.md` proved to be a
    location fiction, never enters (`anchored_differential_prereg.md`).
    """

    probability_ahead: float
    probability_ahead_interval: tuple[float, float]
    scenario_differential_mean: float
    edge_draw_mean: float
    edge_draw_sd: float
    scenario_count: int
    diagnostics: Mapping[str, object]


def crowd_overlap(result: OptimizationResult, crowd: "RivalSquad") -> float:
    """Captain-weighted starter share against the crowd's eleven, as declared.

    Shared starters count one, a shared captain counts two, denominator twelve —
    `overlap_scaled_edge_prereg.md` fixes this once; it is not a knob.
    """

    if not isinstance(result, OptimizationResult) or result.captain is None:
        raise ScenarioValidationError("result must be a feasible OptimizationResult.")
    crowd_ids = {int(str(p)) for p in crowd.starter_ids}
    starters = {int(v) for v in result.starting_xi["player_id"]}
    weight = float(len(starters & crowd_ids))
    if int(result.captain["player_id"]) == int(str(crowd.captain_id)):
        weight += 1.0
    return weight / 12.0


def anchored_probability_ahead(
    candidate: OptimizationResult,
    anchor: OptimizationResult,
    scenarios: ScenarioSet,
    *,
    edge_samples: tuple[float, ...],
    edge_weeks: int,
    edge_seed: int,
    overlap_scaling_crowd: "RivalSquad | None" = None,
) -> AnchoredClaim:
    """The anchored claim: P((candidate - anchor)_scenario > edge_draw).

    The anchor is the fold's risk-neutral squad. For ``candidate == anchor`` the
    scenario term vanishes exactly (same players cancel per scenario) and the claim
    degenerates to the share of negative resampled window edges — the identity the
    pre-registration's first clause pins.
    """

    for name, result in (("candidate", candidate), ("anchor", anchor)):
        if not isinstance(result, OptimizationResult):
            raise ScenarioValidationError(f"{name} must be an OptimizationResult.")
        if not result.has_solution or result.captain is None:
            raise ScenarioValidationError(f"{name} must be a feasible decision.")
    verified = scenarios.validated_copy()
    player_ids = verified.projections.table["player_id"].tolist()
    column = {player_id: index for index, player_id in enumerate(player_ids)}
    matrix = verified.scenario_points.to_numpy(dtype="float64", copy=False)

    def squad_scores(result: OptimizationResult) -> np.ndarray:
        starters = result.starting_xi["player_id"].tolist()
        assert result.captain is not None
        captain = result.captain["player_id"]
        missing = [p for p in [*starters, captain] if p not in column]
        if missing:
            raise ScenarioValidationError(
                f"Scenario players must cover the squad; missing={missing[:10]!r}."
            )
        scores: np.ndarray = matrix[:, [column[p] for p in starters]].sum(axis=1)
        total: np.ndarray = scores + matrix[:, column[captain]]
        return total

    differential = squad_scores(candidate) - squad_scores(anchor)
    edge = rival_edge_draws(
        edge_samples, scenarios=matrix.shape[0], weeks=edge_weeks, seed=edge_seed
    )
    scale = 1.0
    if overlap_scaling_crowd is not None:
        # The crowd's edge is carried by its players: a candidate holding them inherits
        # that share, so the edge it still faces is scaled by its non-overlap
        # (overlap_scaled_edge_prereg). None (the default) is the anchored construction,
        # bit for bit.
        scale = 1.0 - crowd_overlap(candidate, overlap_scaling_crowd)
    wins = differential - edge * scale > 0.0
    ahead = int(wins.sum())
    count = int(matrix.shape[0])
    return AnchoredClaim(
        probability_ahead=ahead / count,
        probability_ahead_interval=wilson_interval(ahead, count),
        scenario_differential_mean=float(differential.mean()),
        edge_draw_mean=float(edge.mean()),
        edge_draw_sd=float(edge.std()),
        scenario_count=count,
        diagnostics=MappingProxyType(
            {
                "construction": "anchored_differential_v1",
                "edge_samples": len(edge_samples),
                "edge_weeks": int(edge_weeks),
                "edge_seed": int(edge_seed),
                "edge_scale": float(scale),
            }
        ),
    )


def rival_edge_draws(
    samples: tuple[float, ...],
    *,
    scenarios: int,
    weeks: int,
    seed: int,
) -> np.ndarray:
    """One resampled window edge per scenario: the sum of ``weeks`` iid draws.

    ``samples`` are measured weekly edges (the crowd's realized advantage over the
    projection, week by week); resampling the empirical series keeps the location and
    the spread the measurement saw, with no distributional fit. Independence across
    weeks is itself measured (lag-1 autocorrelation 0.07 on 2024-25, negative on the
    other seasons), so a window's edge is a plain sum. Deterministic under ``seed``.
    """

    if not isinstance(seed, int) or isinstance(seed, bool):
        raise ScenarioValidationError("seed must be an integer.")
    if not isinstance(weeks, int) or isinstance(weeks, bool) or weeks < 1:
        raise ScenarioValidationError("weeks must be a positive integer.")
    if not isinstance(scenarios, int) or isinstance(scenarios, bool) or scenarios < 1:
        raise ScenarioValidationError("scenarios must be a positive integer.")
    if not samples:
        raise ScenarioValidationError("samples must be non-empty.")
    values = np.asarray(samples, dtype="float64")
    if not np.isfinite(values).all():
        raise ScenarioValidationError("Every edge sample must be finite.")
    generator = np.random.default_rng(seed)
    indices = generator.integers(0, len(values), size=(scenarios, weeks))
    result: np.ndarray = values[indices].sum(axis=1)
    return result


def compare_fixed_decisions(
    optimization_result: OptimizationResult,
    rival: RivalSquad,
    scenarios: ScenarioSet,
    config: ScenarioEvaluationConfig | None = None,
    *,
    rival_edge_points: float = 0.0,
    rival_edge_samples: tuple[float, ...] = (),
    rival_edge_weeks: int = 1,
    rival_edge_seed: int = 0,
) -> ScenarioComparisonResult:
    """Score my decision and a rival's squad in the same scenarios and read the gap.

    Both squads are scored under one scenario matrix, so shared players cancel exactly
    and only the differential is uncertain — scoring the two separately would count the
    common ground twice. The location shift is applied to neither: it corrects a
    selected squad's optimism, and both squads were selected, so it cancels in the
    difference (stated in the diagnostics rather than assumed silently).
    """

    settings = ScenarioEvaluationConfig() if config is None else config
    if not isinstance(settings, ScenarioEvaluationConfig):
        raise ScenarioValidationError("config must be a ScenarioEvaluationConfig.")
    if not isinstance(rival, RivalSquad):
        raise ScenarioValidationError("rival must be a RivalSquad.")
    if not isinstance(optimization_result, OptimizationResult):
        raise ScenarioValidationError("optimization_result must be an OptimizationResult.")
    if not optimization_result.has_solution or optimization_result.captain is None:
        raise ScenarioValidationError("Comparison requires a feasible fixed decision.")
    if not isinstance(scenarios, ScenarioSet):
        raise ScenarioValidationError("scenarios must be a ScenarioSet.")
    verified = scenarios.validated_copy()
    player_ids = verified.projections.table["player_id"].tolist()
    column = {player_id: index for index, player_id in enumerate(player_ids)}
    my_starters = optimization_result.starting_xi["player_id"].tolist()
    my_captain = optimization_result.captain["player_id"]
    missing = [
        player
        for player in [*my_starters, my_captain, *rival.starter_ids, rival.captain_id]
        if player not in column
    ]
    if missing:
        raise ScenarioValidationError(
            f"Scenario players must cover both squads; missing={missing[:10]!r}."
        )
    matrix = verified.scenario_points.to_numpy(dtype="float64", copy=False)
    mine = matrix[:, [column[p] for p in my_starters]].sum(axis=1) + matrix[:, column[my_captain]]
    if isinstance(rival_edge_points, bool) or not isinstance(rival_edge_points, int | float):
        raise ScenarioValidationError("rival_edge_points must be a finite number.")
    if not math.isfinite(float(rival_edge_points)):
        raise ScenarioValidationError("rival_edge_points must be a finite number.")
    if rival_edge_samples and float(rival_edge_points) != 0.0:
        raise ScenarioValidationError(
            "rival_edge_samples carry the measured location already; combining them "
            "with a non-zero rival_edge_points would count the edge twice."
        )
    if rival_edge_samples:
        edge = rival_edge_draws(
            tuple(float(v) for v in rival_edge_samples),
            scenarios=matrix.shape[0],
            weeks=rival_edge_weeks,
            seed=rival_edge_seed,
        )
    else:
        edge = np.full(matrix.shape[0], float(rival_edge_points))
    theirs = (
        matrix[:, [column[p] for p in rival.starter_ids]].sum(axis=1)
        + matrix[:, column[rival.captain_id]]
        + edge
    )
    difference = mine - theirs
    ahead = int((difference > 0.0).sum())
    count = len(difference)
    quantiles = {
        f"q{int(level * 100):02d}": float(np.quantile(difference, level, method="linear"))
        for level in (0.10, 0.25, 0.50, 0.75, 0.90)
    }
    return ScenarioComparisonResult(
        rival_label=rival.label,
        scenario_count=count,
        probability_ahead=ahead / count,
        probability_ahead_interval=wilson_interval(ahead, count),
        probability_level=0.90,
        mean_difference=float(difference.mean()),
        difference_quantiles=quantiles,
        shared_starters=len(set(my_starters) & set(rival.starter_ids)),
        diagnostics={
            "scenario_fingerprint": verified.scenario_fingerprint,
            "decision_fingerprint": _decision_fingerprint(optimization_result),
            "rival_captain_shared": rival.captain_id == my_captain,
            "rival_edge_points": float(rival_edge_points),
            "location_shift_applied": False,
            "location_shift_note": (
                "the selection-optimism shift is not applied to the difference: both squads "
                "were selected, so it cancels"
            ),
            "scoring_policy": "starting_xi_plus_captain_double_v1",
            "probability_ties_counted_as_behind": True,
        },
    )
