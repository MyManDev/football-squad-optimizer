"""Private learned paired intensities and conditional tactical recipient marginals.

Predecision state weights are supplied, not inferred from final lineups. Training
transforms use those prior weights only. The paired physical-goal law conditions
recipient fitting on its posterior states without repeating labels in every state.
Separate recipient marginals do not define a joint scorer/assister event generator.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

import numpy as np
import numpy.typing as npt
from scipy.optimize import minimize
from scipy.special import gammaln, logsumexp, xlogy

from squadopt.data.timestamps import normalize_utc_timestamp
from squadopt.features.football_tactical_inputs import (
    TEAM_FEATURES,
    TacticalObservation,
    TacticalProfile,
    TacticalProjection,
    TacticalSource,
    TacticalStyle,
    observation_digest,
    projection_digest,
    recipient_feature_names,
    recipient_features,
    team_features,
    validate_observation,
    validate_observation_header,
    validate_tactical_projection,
)

MODEL_VERSION: Final = "football_tactical_matchup_v1"
FEATURE_VERSION: Final = "causal_named_tactical_matchup_features_v1"
HEADS: Final = ("goals", "assists")
Array = npt.NDArray[np.float64]


@dataclass(frozen=True)
class TacticalAllocatedPlayer:
    player_code: int
    club: int
    position: str
    goals: float
    assists: float
    clean_sheet_probability: float


@dataclass(frozen=True)
class TacticalSideAllocation:
    club: int
    team_goal_rate: float
    players: tuple[TacticalAllocatedPlayer, ...]


@dataclass(frozen=True)
class TacticalStateAllocation:
    state_id: str
    weight: float
    home_goal_rate: float
    away_goal_rate: float
    home_players: tuple[TacticalAllocatedPlayer, ...]
    away_players: tuple[TacticalAllocatedPlayer, ...]


@dataclass(frozen=True)
class TacticalTransformReceipt:
    features: tuple[str, ...]
    means: tuple[float, ...]
    scales: tuple[float, ...]
    weighting: str


@dataclass(frozen=True)
class TacticalOptimizerReceipt:
    head: str
    method: str
    initialization: str
    success: bool
    status: int
    iterations: int
    evaluations: int
    objective: float
    gradient_max_abs: float
    optimum_scope: str = "converged_local_solution_only"


@dataclass(frozen=True)
class TacticalTrainingReceipt:
    observation_sha256: str
    projection_sha256: str
    season: str
    gameweek: int
    fixture: int
    home_club: int
    away_club: int
    kickoff: str
    decision_at: str
    outcome_available_at: str
    rules_version: str
    projection_source: TacticalSource
    goal_source: TacticalSource
    credit_source: TacticalSource
    home_style: TacticalStyle
    away_style: TacticalStyle
    profiles: tuple[TacticalProfile, ...]
    state_weights: tuple[tuple[str, float], ...]


@dataclass(frozen=True)
class TacticalModelMetadata:
    contract_version: str
    cutoff: str
    target_season: str
    target_gameweek: int
    allowed_seasons: tuple[str, ...]
    training_receipts: tuple[TacticalTrainingReceipt, ...]
    team_transform: TacticalTransformReceipt
    goal_transform: TacticalTransformReceipt
    assist_transform: TacticalTransformReceipt
    beta: tuple[float, ...]
    goal_gamma: tuple[float, ...]
    assist_gamma: tuple[float, ...]
    goal_events: int
    assist_events: int
    goal_status: str
    assist_status: str
    alpha: float
    max_iter: int
    optimizers: tuple[TacticalOptimizerReceipt, ...]
    recipient_state_basis: str = "fitted_physical_pair_posterior"
    residual_scope: str = "native_residual_retained_no_additional_scoring_heads"
    event_scope: str = "conditional_pair_poisson_and_separate_recipient_marginals"
    state_weight_policy: str = "validated_unit_mass_normalized_fsum_roundoff_v1"


@dataclass(frozen=True)
class TacticalAllocation:
    home: TacticalSideAllocation
    away: TacticalSideAllocation
    states: tuple[TacticalStateAllocation, ...]
    projection_sha256: str
    model_version: str
    feature_version: str
    metadata: TacticalModelMetadata
    control: bool


@dataclass(frozen=True)
class _Transform:
    means: Array
    scales: Array
    receipt: TacticalTransformReceipt

    def apply(self, values: Array) -> Array:
        result = (values - self.means) / self.scales
        if not np.isfinite(result).all():
            raise ValueError("Tactical transformed features exceed finite support.")
        return result


@dataclass(frozen=True)
class _PairGroup:
    features: Array
    bases: Array
    weights: Array
    outcomes: Array


@dataclass(frozen=True)
class _RecipientGroup:
    features: Array
    shares: Array
    weights: Array
    counts: Array


@dataclass(frozen=True)
class _FittedState:
    metadata: TacticalModelMetadata
    beta: Array
    gammas: Mapping[str, Array]
    team_transform: _Transform
    recipient_transforms: Mapping[str, _Transform]


def _immutable(values: Array) -> Array:
    return np.frombuffer(values.tobytes(), dtype=np.float64).reshape(values.shape)


def normalized_state_weights(projection: TacticalProjection) -> Array:
    """Normalize only validated near-unit weights, preserving the original source digest.

    The source contract already refuses mass outside its 1e-12 tolerance. Division by
    the fsum total and a final rounding correction on the largest entry give exact
    fsum unit mass. This is numerical normalization, not learned state calibration.
    """
    weights = np.asarray([state.weight for state in projection.states], dtype=float)
    total = math.fsum(float(v) for v in weights)
    if (
        not math.isfinite(total)
        or total <= 0
        or not math.isclose(total, 1, rel_tol=1e-12, abs_tol=1e-12)
    ):
        raise ValueError("Tactical state weights must have validated near-unit finite mass.")
    if not np.isfinite(weights).all() or (weights < 0).any():
        raise ValueError("Tactical state weights must be finite and nonnegative.")
    weights /= total
    weights[int(np.argmax(weights))] += 1 - math.fsum(float(v) for v in weights)
    if (weights < 0).any() or math.fsum(float(v) for v in weights) != 1:
        raise ValueError("Tactical state weights failed exact numerical unit normalization.")
    return _immutable(weights)


def _transform(values: Array, weights: Array, names: tuple[str, ...], weighting: str) -> _Transform:
    if not np.isfinite(values).all() or not np.isfinite(weights).all() or (weights < 0).any():
        raise ValueError("Tactical transform inputs must be finite and nonnegative weighted.")
    total = math.fsum(weights)
    means = np.zeros(values.shape[1], dtype=float)
    scales = np.ones(values.shape[1], dtype=float)
    if total:
        for index in range(values.shape[1]):
            observed = values[weights > 0, index]
            if (observed == observed[0]).all():
                means[index] = observed[0]
                continue
            means[index] = math.fsum(weights * values[:, index]) / total
            variance = math.fsum(weights * (values[:, index] - means[index]) ** 2) / total
            scales[index] = math.sqrt(variance) if variance else 1.0
    if not np.isfinite(means).all() or not np.isfinite(scales).all() or (scales <= 0).any():
        raise ValueError("Tactical transform moments exceed finite support.")
    receipt = TacticalTransformReceipt(
        names, tuple(float(v) for v in means), tuple(float(v) for v in scales), weighting
    )
    return _Transform(_immutable(means), _immutable(scales), receipt)


def _team_matrix(projection: TacticalProjection) -> Array:
    return np.asarray(
        [
            [
                team_features(projection, state, home=True),
                team_features(projection, state, home=False),
            ]
            for state in projection.states
        ],
        dtype=float,
    )


def _rates(bases: Array, features: Array, beta: Array) -> Array:
    result = np.zeros_like(bases)
    positive = bases > 0
    linear = features @ beta
    with np.errstate(over="raise", invalid="raise", under="ignore"):
        try:
            result[positive] = np.exp(np.log(bases[positive]) + linear[positive])
        except FloatingPointError as error:
            raise ValueError("Tactical adjusted goal intensity exceeds finite support.") from error
    if not np.isfinite(result).all():
        raise ValueError("Tactical adjusted goal intensity exceeds finite support.")
    return result


def _pair_terms(group: _PairGroup, beta: Array) -> tuple[float, Array, Array]:
    rates = _rates(group.bases, group.features, beta)
    conditional = (xlogy(group.outcomes, rates) - rates - gammaln(group.outcomes + 1)).sum(axis=1)
    logweights = np.full(len(group.weights), -np.inf, dtype=float)
    positive = group.weights > 0
    logweights[positive] = np.log(group.weights[positive])
    joint = logweights + conditional
    normalizer = float(logsumexp(joint))
    if not math.isfinite(normalizer):
        raise ValueError("Observed physical goals have no positive joint-state intensity support.")
    posterior = np.exp(joint - normalizer)
    gradient = np.einsum("s,sk,skd->d", posterior, rates - group.outcomes, group.features)
    return normalizer, posterior, gradient


def _recipient_probabilities(shares: Array, features: Array, gamma: Array) -> tuple[Array, Array]:
    logits = np.full(shares.shape, -np.inf, dtype=float)
    positive = shares > 0
    linear = features @ gamma
    logits[positive] = np.log(shares[positive]) + linear[positive]
    normalizers = logsumexp(logits, axis=1)
    logprobabilities = np.full_like(logits, -np.inf)
    supported = np.isfinite(normalizers)
    logprobabilities[supported] = logits[supported] - normalizers[supported, None]
    probabilities = np.exp(logprobabilities)
    if not np.isfinite(probabilities).all():
        raise ValueError("Tactical recipient probabilities exceed finite support.")
    return probabilities, logprobabilities


def _recipient_terms(group: _RecipientGroup, gamma: Array) -> tuple[float, Array]:
    probabilities, logprobabilities = _recipient_probabilities(group.shares, group.features, gamma)
    total = float(group.counts.sum())
    credited = group.counts > 0
    conditional = (logprobabilities[:, credited] * group.counts[credited]).sum(axis=1)
    conditional += float(gammaln(total + 1) - gammaln(group.counts + 1).sum())
    logweights = np.full(len(group.weights), -np.inf, dtype=float)
    positive = group.weights > 0
    logweights[positive] = np.log(group.weights[positive])
    joint = logweights + conditional
    normalizer = float(logsumexp(joint))
    if not math.isfinite(normalizer):
        raise ValueError("Credited player counts have no shared projected recipient support.")
    posterior = np.exp(joint - normalizer)
    gradient = np.einsum(
        "s,sn,snd->d", posterior, total * probabilities - group.counts, group.features
    )
    return normalizer, gradient


def _optimize(
    objective: Callable[[Array], tuple[float, Array]], *, width: int, max_iter: int, head: str
) -> tuple[Array, TacticalOptimizerReceipt]:
    result = minimize(
        objective,
        np.zeros(width, dtype=float),
        jac=True,
        method="L-BFGS-B",
        options={"maxiter": max_iter, "ftol": 1e-12, "gtol": 1e-7},
    )
    coefficients = np.asarray(result.x, dtype=float)
    value, gradient = objective(coefficients)
    if (
        not result.success
        or not np.isfinite(coefficients).all()
        or not math.isfinite(value)
        or not np.isfinite(gradient).all()
    ):
        raise ValueError(f"Tactical {head} fit did not converge to finite parameters.")
    receipt = TacticalOptimizerReceipt(
        head,
        "L-BFGS-B",
        "zero_vector",
        bool(result.success),
        int(result.status),
        int(result.nit),
        int(result.nfev),
        float(value),
        float(np.max(np.abs(gradient))),
    )
    return _immutable(coefficients), receipt


def _receipt(observation: TacticalObservation) -> TacticalTrainingReceipt:
    projection = observation.projection
    profiles = {
        player.profile
        for state in projection.states
        for side in (state.home, state.away)
        for player in side.players
    }
    return TacticalTrainingReceipt(
        observation_digest(observation),
        projection_digest(projection),
        projection.season,
        projection.gameweek,
        projection.fixture,
        projection.home_club,
        projection.away_club,
        projection.kickoff,
        projection.decision_at,
        observation.outcome_available_at,
        observation.rules_version,
        projection.source,
        observation.goal_source,
        observation.credit_source,
        projection.home_style,
        projection.away_style,
        tuple(sorted(profiles, key=lambda p: (p.club, p.player_code, p.original_identity))),
        tuple(
            (state.state_id, float(weight))
            for state, weight in zip(
                projection.states, normalized_state_weights(projection), strict=True
            )
        ),
    )


class TacticalMatchupModel:
    """Learn paired team effects and separate conditional credited recipient effects."""

    model_version = MODEL_VERSION
    feature_version = FEATURE_VERSION

    def __init__(self, alpha: float = 0.1, max_iter: int = 200):
        try:
            finite = isinstance(alpha, (float, int)) and math.isfinite(float(alpha))
        except OverflowError:
            finite = False
        if (
            isinstance(alpha, bool)
            or not finite
            or alpha < 0
            or type(max_iter) is not int
            or max_iter <= 0
        ):
            raise ValueError(
                "Tactical fitting needs finite nonnegative alpha and positive max_iter."
            )
        self._alpha, self._max_iter = float(alpha), max_iter
        self._fitted: _FittedState | None = None

    @property
    def alpha(self) -> float:
        return self._alpha

    @property
    def max_iter(self) -> int:
        return self._max_iter

    @property
    def metadata(self) -> TacticalModelMetadata:
        if self._fitted is None:
            raise ValueError("Tactical model must be fitted before metadata is available.")
        return self._fitted.metadata

    def fit(
        self,
        observations: tuple[TacticalObservation, ...],
        *,
        cutoff: str,
        allowed_seasons: tuple[str, ...],
        target_season: str,
        target_gameweek: int,
    ) -> TacticalMatchupModel:
        if type(observations) is not tuple or not observations:
            raise ValueError("Tactical fit requires complete immutable observations.")
        if (
            type(target_gameweek) is not int
            or not 1 <= target_gameweek <= 38
            or not isinstance(target_season, str)
            or not re.fullmatch(r"20\d{2}-\d{2}", target_season)
            or int(target_season[-2:]) != (int(target_season[:4]) + 1) % 100
            or target_season == "2025-26"
        ):
            raise ValueError("Tactical fit requires an admitted target season and gameweek.")
        seen = set()
        week_clocks: dict[tuple[str, int], str] = {}
        for observation in observations:
            validate_observation_header(
                observation,
                training_cutoff=cutoff,
                allowed_seasons=allowed_seasons,
                excluded_target=(target_season, target_gameweek),
            )
            p = observation.projection
            clock = normalize_utc_timestamp(p.decision_at, label="historical tactical decision")
            week_key = (p.season, p.gameweek)
            if week_key in week_clocks and week_clocks[week_key] != clock:
                raise ValueError(
                    "Tactical historical gameweek requires one original decision clock."
                )
            week_clocks[week_key] = clock
            if p.season > target_season or (
                p.season == target_season and p.gameweek >= target_gameweek
            ):
                raise ValueError(
                    "The target and later tactical gameweeks/seasons cannot train the model."
                )
            key = (p.season, p.fixture)
            if key in seen:
                raise ValueError("A paired physical fixture occurs twice in tactical training.")
            seen.add(key)
        for observation in observations:
            validate_observation(
                observation,
                training_cutoff=cutoff,
                allowed_seasons=allowed_seasons,
                excluded_target=(target_season, target_gameweek),
            )
        ordered = tuple(
            sorted(observations, key=lambda o: (o.projection.season, o.projection.fixture))
        )
        raw_teams = [_team_matrix(o.projection) for o in ordered]
        prior_weights = [normalized_state_weights(o.projection) for o in ordered]
        team_transform = _transform(
            np.concatenate([matrix.reshape(-1, len(TEAM_FEATURES)) for matrix in raw_teams]),
            np.concatenate([np.repeat(weights / 2, 2) for weights in prior_weights]),
            TEAM_FEATURES,
            "one_fixture_prior_state_weight_half_per_side",
        )
        pair_groups = tuple(
            _PairGroup(
                team_transform.apply(matrix),
                np.asarray(
                    [[s.home.base_goal_rate, s.away.base_goal_rate] for s in o.projection.states],
                    float,
                ),
                weights,
                np.asarray(o.physical_goals, float),
            )
            for o, matrix, weights in zip(ordered, raw_teams, prior_weights, strict=True)
        )
        alpha, max_iter = self.alpha, self.max_iter

        def pair_objective(beta: Array) -> tuple[float, Array]:
            value, gradient = alpha * float(beta @ beta) / 2, alpha * beta.copy()
            for group in pair_groups:
                likelihood, _, score = _pair_terms(group, beta)
                value -= likelihood
                gradient += score
            return value, gradient

        beta, pair_receipt = _optimize(
            pair_objective, width=len(TEAM_FEATURES), max_iter=max_iter, head="physical_pair"
        )
        posterior_weights = [_pair_terms(group, beta)[1] for group in pair_groups]
        transforms: dict[str, _Transform] = {}
        gammas: dict[str, Array] = {}
        counts: dict[str, int] = {}
        optimizer_receipts = [pair_receipt]
        for head in HEADS:
            raw_recipient = []
            transform_values = []
            transform_weights = []
            count_total = 0
            for observation, prior, posterior in zip(
                ordered, prior_weights, posterior_weights, strict=True
            ):
                projection = observation.projection
                credit = {row.player_code: getattr(row, head) for row in observation.credits}
                for home in (True, False):
                    sides = [state.home if home else state.away for state in projection.states]
                    players = [
                        tuple(sorted(side.players, key=lambda p: p.profile.player_code))
                        for side in sides
                    ]
                    matrix = np.asarray(
                        [
                            [
                                recipient_features(projection, state, p, home=home, head=head)
                                for p in lineup
                            ]
                            for state, lineup in zip(projection.states, players, strict=True)
                        ],
                        float,
                    )
                    shares = np.asarray(
                        [
                            [
                                getattr(
                                    p,
                                    "native_goal_share"
                                    if head == "goals"
                                    else "native_assist_share",
                                )
                                for p in lineup
                            ]
                            for lineup in players
                        ],
                        float,
                    )
                    labels = np.asarray([credit[p.profile.player_code] for p in players[0]], float)
                    count_total += int(labels.sum())
                    raw_recipient.append((matrix, shares, posterior, labels))
                    transform_values.append(matrix.reshape(-1, matrix.shape[-1]))
                    transform_weights.append((prior[:, None] * shares / 2).reshape(-1))
            names = recipient_feature_names(head)
            transform = _transform(
                np.concatenate(transform_values),
                np.concatenate(transform_weights),
                names,
                "one_fixture_prior_state_native_share_half_per_side_no_outcome_weights",
            )
            transforms[head], counts[head] = transform, count_total
            groups = tuple(
                _RecipientGroup(transform.apply(matrix), shares, posterior, labels)
                for matrix, shares, posterior, labels in raw_recipient
                if labels.sum() > 0
            )
            if not groups:
                gammas[head] = _immutable(np.zeros(len(names), float))
                continue

            def recipient_objective(
                gamma: Array, fitting_groups: tuple[_RecipientGroup, ...] = groups
            ) -> tuple[float, Array]:
                value, gradient = alpha * float(gamma @ gamma) / 2, alpha * gamma.copy()
                for group in fitting_groups:
                    likelihood, score = _recipient_terms(group, gamma)
                    value -= likelihood
                    gradient += score
                return value, gradient

            gamma, receipt = _optimize(
                recipient_objective, width=len(names), max_iter=max_iter, head=head
            )
            gammas[head] = gamma
            optimizer_receipts.append(receipt)
        metadata = TacticalModelMetadata(
            contract_version="football_tactical_fit_v1",
            cutoff=cutoff,
            target_season=target_season,
            target_gameweek=target_gameweek,
            allowed_seasons=allowed_seasons,
            training_receipts=tuple(_receipt(o) for o in ordered),
            team_transform=team_transform.receipt,
            goal_transform=transforms["goals"].receipt,
            assist_transform=transforms["assists"].receipt,
            beta=tuple(float(v) for v in beta),
            goal_gamma=tuple(float(v) for v in gammas["goals"]),
            assist_gamma=tuple(float(v) for v in gammas["assists"]),
            goal_events=counts["goals"],
            assist_events=counts["assists"],
            goal_status="fitted" if counts["goals"] else "unavailable_no_credited_events",
            assist_status="fitted" if counts["assists"] else "unavailable_no_credited_events",
            alpha=alpha,
            max_iter=max_iter,
            optimizers=tuple(optimizer_receipts),
        )
        self._fitted = _FittedState(
            metadata, beta, MappingProxyType(gammas), team_transform, MappingProxyType(transforms)
        )
        return self

    def predict(
        self, projection: TacticalProjection, *, control: bool = False
    ) -> TacticalAllocation:
        fitted = self._fitted
        if fitted is None:
            raise ValueError("Tactical model must be fitted before prediction.")
        if type(control) is not bool:
            raise ValueError("Tactical control must be an explicit boolean.")
        validate_tactical_projection(projection, model_cutoff=fitted.metadata.cutoff)
        if (
            projection.season != fitted.metadata.target_season
            or projection.gameweek < fitted.metadata.target_gameweek
        ):
            raise ValueError("Tactical projection lies outside the fitted target window.")
        bases = np.asarray(
            [[s.home.base_goal_rate, s.away.base_goal_rate] for s in projection.states], float
        )
        rates = (
            bases
            if control
            else _rates(bases, fitted.team_transform.apply(_team_matrix(projection)), fitted.beta)
        )
        aggregate: dict[int, dict[int, list[Array]]] = {
            projection.home_club: {},
            projection.away_club: {},
        }
        totals: dict[int, list[float]] = {projection.home_club: [], projection.away_club: []}
        identities = {}
        states = []
        for index, (state, weight) in enumerate(
            zip(projection.states, normalized_state_weights(projection), strict=True)
        ):
            records = []
            for side_index, side in enumerate((state.home, state.away)):
                home = side_index == 0
                players = tuple(sorted(side.players, key=lambda p: p.profile.player_code))
                expectations = {}
                own, opponent = float(rates[index, side_index]), float(rates[index, 1 - side_index])
                for head, fraction in (
                    ("goals", side.scored_fraction),
                    ("assists", side.scored_fraction * side.assist_fraction),
                ):
                    mass = own * fraction
                    if (
                        not control
                        and mass > 0
                        and getattr(
                            fitted.metadata, "goal_events" if head == "goals" else "assist_events"
                        )
                        == 0
                    ):
                        raise ValueError(
                            f"Tactical {head} unavailable without historical credited events."
                        )
                    shares = np.asarray(
                        [
                            getattr(
                                p, "native_goal_share" if head == "goals" else "native_assist_share"
                            )
                            for p in players
                        ],
                        float,
                    )
                    if control:
                        probabilities = shares
                    else:
                        features = np.asarray(
                            [
                                recipient_features(projection, state, p, home=home, head=head)
                                for p in players
                            ],
                            float,
                        )
                        probabilities = _recipient_probabilities(
                            shares[None, :],
                            fitted.recipient_transforms[head].apply(features)[None, :, :],
                            fitted.gammas[head],
                        )[0][0]
                    expectations[head] = mass * probabilities
                    if not math.isclose(
                        math.fsum(expectations[head]), mass, rel_tol=1e-12, abs_tol=1e-12
                    ):
                        raise ValueError(
                            "Tactical attacking marginals failed full-club mass closure."
                        )
                side_records = []
                for player, goals, assists in zip(
                    players, expectations["goals"], expectations["assists"], strict=True
                ):
                    if goals + assists > own and not math.isclose(
                        float(goals + assists), own, rel_tol=1e-12, abs_tol=1e-12
                    ):
                        raise ValueError(
                            "Player goal plus assist marginal exceeds physical event intensity."
                        )
                    clean = (
                        math.exp(-opponent * player.minutes / 90) if player.minutes >= 60 else 0.0
                    )
                    profile = player.profile
                    record = TacticalAllocatedPlayer(
                        profile.player_code,
                        profile.club,
                        profile.position,
                        float(goals),
                        float(assists),
                        clean,
                    )
                    side_records.append(record)
                    key = profile.player_code
                    identities[key] = (profile.club, profile.position)
                    values = np.asarray((goals, assists, clean), float)
                    aggregate[side.club].setdefault(key, []).append(weight * values)
                totals[side.club].append(float(weight) * own)
                records.append(tuple(side_records))
            states.append(
                TacticalStateAllocation(
                    state.state_id,
                    float(weight),
                    float(rates[index, 0]),
                    float(rates[index, 1]),
                    records[0],
                    records[1],
                )
            )

        def side_result(club: int) -> TacticalSideAllocation:
            records = tuple(
                TacticalAllocatedPlayer(
                    code,
                    identities[code][0],
                    identities[code][1],
                    *(math.fsum(float(value[index]) for value in values) for index in range(3)),
                )
                for code, values in sorted(aggregate[club].items())
            )
            return TacticalSideAllocation(club, math.fsum(totals[club]), records)

        return TacticalAllocation(
            side_result(projection.home_club),
            side_result(projection.away_club),
            tuple(states),
            projection_digest(projection),
            self.model_version,
            self.feature_version,
            fitted.metadata,
            control,
        )
