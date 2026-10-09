"""Private learned scoring marginals with conserved full-club attacking mass.

This module does not fetch sources or fit the retained native football forecast.
Captured ranks are explanatory observations, not manually assigned frequencies.
Separate goal and assist marginals are not a joint match-event generator.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

import numpy as np
import numpy.typing as npt
from scipy.optimize import minimize
from scipy.special import logsumexp

from squadopt.features.football_phase_inputs import (
    PHASE_DEFINITION_VERSION,
    PHASES,
    PhaseDutyCapture,
    PhaseObservation,
    PhasePlayer,
    PhaseProjection,
    PhaseSource,
    observation_digest,
    projection_digest,
    validate_observation,
    validate_observation_header,
    validate_projection,
)

MODEL_VERSION: Final = "football_phase_duties_v1"
FEATURE_VERSION: Final = "captured_phase_duty_exposure_features_v1"
POSITIONS: Final = ("GK", "DEF", "MID", "FWD")
POSITION_FEATURES: Final = tuple("position_" + position.lower() for position in POSITIONS)
RANK_FEATURES: Final = (
    "published_rank",
    "published_rank_unknown",
    "active_higher_priority_players",
    "active_equal_priority_players",
    "active_unknown_priority_players",
)
PENALTY_MISS_POLICY: Final = "retained_native_residual_no_additive_adjustment"
Array = npt.NDArray[np.float64]


@dataclass(frozen=True)
class PhaseAllocatedPlayer:
    player_code: int
    goals: float
    assists: float
    goals_share: float
    assists_share: float


@dataclass(frozen=True)
class PhaseStateAllocation:
    state_id: str
    weight: float
    players: tuple[PhaseAllocatedPlayer, ...]
    total_goals: float
    total_assists: float
    physical_goal_mass: float


@dataclass(frozen=True)
class PhaseHeadMetadata:
    head: str
    phase: str
    features: tuple[str, ...]
    coefficients: tuple[float, ...]
    credited_events: int
    fitting_groups: int


@dataclass(frozen=True)
class PhaseTrainingReceipt:
    observation_sha256: str
    season: str
    gameweek: int
    fixture: int
    club: int
    opponent: int
    home: bool
    kickoff: str
    decision_at: str
    outcome_available_at: str
    duties: PhaseDutyCapture
    baseline_source: PhaseSource
    outcome_source: PhaseSource
    totals_source: PhaseSource
    phase_definition_version: str
    rules_version: str
    complete_coverage: bool


@dataclass(frozen=True)
class PhaseModelMetadata:
    contract_version: str
    cutoff: str
    target_season: str
    target_gameweek: int
    allowed_seasons: tuple[str, ...]
    phase_definition_version: str
    observation_sha256: tuple[str, ...]
    training_receipts: tuple[PhaseTrainingReceipt, ...]
    goal_events: int
    assist_events: int
    goal_status: str
    assist_status: str
    alpha: float
    max_iter: int
    recipient_heads: tuple[PhaseHeadMetadata, ...]
    penalty_miss_treatment: str = PENALTY_MISS_POLICY
    output_scope: str = "separate_expected_scoring_marginals"
    physical_check: str = "per_state_player_goals_plus_assists_not_above_physical_goals"


@dataclass(frozen=True)
class PhaseAllocation:
    players: tuple[PhaseAllocatedPlayer, ...]
    states: tuple[PhaseStateAllocation, ...]
    goal_phase_shares: tuple[float, ...]
    assist_phase_shares: tuple[float, ...]
    total_goals: float
    total_assists: float
    physical_goal_mass: float
    projection_sha256: str
    model_version: str
    feature_version: str
    metadata: PhaseModelMetadata


@dataclass(frozen=True)
class _FittingGroup:
    features: Array
    offsets: Array
    counts: Array


@dataclass(frozen=True)
class _FittedState:
    metadata: PhaseModelMetadata
    phase_shares: Mapping[str, Array]
    coefficients: Mapping[tuple[str, str], Array]


def _immutable_array(values: Array) -> Array:
    # A read-only flag alone can be reversed when NumPy owns mutable storage.
    # Immutable bytes keep both direct writes and setflags(write=True) refused.
    return np.frombuffer(values.tobytes(), dtype=np.float64).reshape(values.shape)


def _rank_field(head: str, phase: str) -> str | None:
    if head == "goals" and phase == "penalty":
        return "penalties_order"
    if head == "goals" and phase == "direct_free_kick":
        return "direct_freekicks_order"
    if head == "assists" and phase in ("corner", "delivered_free_kick"):
        return "corners_and_indirect_freekicks_order"
    # A penalty or direct free-kick assist credits the fouled/handball winner,
    # not a guessed taker. Delivery priorities do not identify corner scorers.
    return None


def _features(
    players: Sequence[PhasePlayer], duties: PhaseDutyCapture, *, head: str, phase: str
) -> tuple[Array, tuple[str, ...]]:
    matrix = np.array(
        [[float(player.position == position) for position in POSITIONS] for player in players],
        dtype=float,
    )
    field = _rank_field(head, phase)
    if field is None:
        return matrix, POSITION_FEATURES
    source = {player.player_code: player for player in duties.players}
    ranks = [getattr(source[player.player_code], field) for player in players]
    active = [rank for player, rank in zip(players, ranks, strict=True) if player.minutes > 0]
    unknown = sum(rank is None for rank in active)
    rank_matrix = []
    for player, rank in zip(players, ranks, strict=True):
        try:
            value = 0.0 if rank is None else float(rank)
        except (OverflowError, ValueError) as error:
            raise ValueError(
                "Captured priority is outside finite recipient feature support."
            ) from error
        if not math.isfinite(value):
            raise ValueError("Captured priority is outside finite recipient feature support.")
        rank_matrix.append(
            [
                value,
                float(rank is None),
                float(
                    sum(other is not None and rank is not None and other < rank for other in active)
                ),
                float(
                    sum(
                        other is not None and rank is not None and other == rank for other in active
                    )
                    - int(player.minutes > 0 and rank is not None)
                ),
                float(unknown - int(player.minutes > 0 and rank is None)),
            ]
        )
    return np.column_stack((matrix, np.asarray(rank_matrix, dtype=float))), (
        *POSITION_FEATURES,
        *RANK_FEATURES,
    )


def _exposure(players: Sequence[PhasePlayer], head: str) -> Array:
    field = "goal_weight90" if head == "goals" else "assist_weight90"
    values = np.array(
        [float(getattr(player, field)) * player.minutes / 90 for player in players], dtype=float
    )
    if not np.isfinite(values).all():
        raise ValueError("Phase recipient exposure must be finite.")
    return values


def _probabilities(features: Array, exposure: Array, coefficients: Array) -> Array:
    active = exposure > 0
    result = np.zeros(len(exposure), dtype=float)
    if active.any():
        logits = np.log(exposure[active]) + features[active] @ coefficients
        if not np.isfinite(logits).all():
            raise ValueError("Phase recipient logits must be finite.")
        result[active] = np.exp(logits - logsumexp(logits))
    return result


def _fit_recipient(groups: tuple[_FittingGroup, ...], *, alpha: float, max_iter: int) -> Array:
    width = groups[0].features.shape[1]

    def objective(coefficients: Array) -> tuple[float, Array]:
        loss = alpha * float(coefficients @ coefficients) / 2
        gradient = alpha * coefficients.copy()
        for group in groups:
            logits = group.offsets + group.features @ coefficients
            normalizer = float(logsumexp(logits))
            total = float(group.counts.sum())
            loss += total * normalizer - float(group.counts @ logits)
            gradient += group.features.T @ (total * np.exp(logits - normalizer) - group.counts)
        return loss, gradient

    fitted = minimize(
        objective,
        np.zeros(width, dtype=float),
        jac=True,
        method="L-BFGS-B",
        options={"maxiter": max_iter, "ftol": 1e-12, "gtol": 1e-7},
    )
    coefficients = np.asarray(fitted.x, dtype=float)
    if not fitted.success or not np.isfinite(coefficients).all() or not math.isfinite(fitted.fun):
        raise ValueError("Phase recipient fit did not converge.")
    return coefficients


def _records(
    codes: tuple[int, ...], goals: Array, assists: Array, gs: Array, aps: Array
) -> tuple[PhaseAllocatedPlayer, ...]:
    return tuple(
        PhaseAllocatedPlayer(code, float(g), float(a), float(sg), float(sa))
        for code, g, a, sg, sa in zip(codes, goals, assists, gs, aps, strict=True)
    )


def _close(first: float, second: float) -> bool:
    return math.isclose(first, second, rel_tol=1e-12, abs_tol=1e-12)


class PhaseDutyModel:
    """Conditional multinomial recipient effects with empirical phase composition.

    The offset is baseline per-90 weight times actual observed/state minutes.
    State minutes already encode participation, so no appearance multiplier is
    applied here. Native penalty misses/saves remain in the retained residual.
    """

    model_version = MODEL_VERSION
    feature_version = FEATURE_VERSION

    def __init__(self, alpha: float = 0.1, max_iter: int = 200):
        try:
            finite_alpha = isinstance(alpha, (int, float)) and math.isfinite(float(alpha))
        except OverflowError:
            finite_alpha = False
        if (
            isinstance(alpha, bool)
            or not isinstance(alpha, (int, float))
            or not finite_alpha
            or alpha < 0
            or isinstance(max_iter, bool)
            or not isinstance(max_iter, int)
            or max_iter <= 0
        ):
            raise ValueError("Phase fit requires finite nonnegative alpha and positive max_iter.")
        self._alpha = float(alpha)
        self._max_iter = max_iter
        self._fitted: _FittedState | None = None

    @property
    def alpha(self) -> float:
        return self._alpha

    @property
    def max_iter(self) -> int:
        return self._max_iter

    @property
    def metadata(self) -> PhaseModelMetadata:
        fitted = self._fitted
        if fitted is None:
            raise ValueError("Phase duty model must be fitted before metadata is available.")
        return fitted.metadata

    @property
    def _metadata(self) -> PhaseModelMetadata | None:
        return None if self._fitted is None else self._fitted.metadata

    @property
    def _phase_shares(self) -> Mapping[str, Array]:
        return MappingProxyType({}) if self._fitted is None else self._fitted.phase_shares

    @property
    def _coefficients(self) -> Mapping[tuple[str, str], Array]:
        return MappingProxyType({}) if self._fitted is None else self._fitted.coefficients

    def fit(
        self,
        observations: tuple[PhaseObservation, ...],
        *,
        cutoff: str,
        allowed_seasons: tuple[str, ...],
        target_season: str,
        target_gameweek: int,
    ) -> PhaseDutyModel:
        if not isinstance(observations, tuple) or not observations:
            raise ValueError("Phase fitting requires nonempty immutable observations.")
        if (
            isinstance(target_gameweek, bool)
            or not isinstance(target_gameweek, int)
            or not 1 <= target_gameweek <= 38
            or not isinstance(target_season, str)
            or not re.fullmatch(r"20\d{2}-\d{2}", target_season)
            or int(target_season[-2:]) != (int(target_season[:4]) + 1) % 100
            or target_season == "2025-26"
        ):
            raise ValueError("Phase fitting requires an admitted target season and gameweek.")
        identities = set()
        # Validate every metadata/source gate before extracting any event labels.
        for observation in observations:
            validate_observation_header(
                observation,
                training_cutoff=cutoff,
                allowed_seasons=allowed_seasons,
                excluded_target=(target_season, target_gameweek),
            )
            if observation.season > target_season or (
                observation.season == target_season and observation.gameweek >= target_gameweek
            ):
                raise ValueError(
                    "Phase training cannot include the target or a later gameweek/season."
                )
            identity = (observation.season, observation.fixture, observation.club)
            if identity in identities:
                raise ValueError("Duplicate phase training club-fixture.")
            identities.add(identity)
        for observation in observations:
            validate_observation(
                observation,
                training_cutoff=cutoff,
                allowed_seasons=allowed_seasons,
                excluded_target=(target_season, target_gameweek),
            )
        ordered = tuple(sorted(observations, key=lambda row: (row.season, row.fixture, row.club)))
        alpha, max_iter = self.alpha, self.max_iter
        phase_shares: dict[str, Array] = {}
        coefficients: dict[tuple[str, str], Array] = {}
        fitted_heads = []
        event_totals: dict[str, int] = {}
        for head, credit in (("goals", "scorer"), ("assists", "assist")):
            phase_counts = np.zeros(len(PHASES), dtype=float)
            for phase_index, phase in enumerate(PHASES):
                groups = []
                feature_names: tuple[str, ...] = ()
                for observation in ordered:
                    players = tuple(
                        sorted(observation.players, key=lambda player: player.player_code)
                    )
                    counts_by_code = {player.player_code: 0 for player in players}
                    for event in observation.events:
                        code = getattr(event, credit)
                        if event.phase == phase and code is not None:
                            counts_by_code[code] += 1
                    counts = np.array(
                        [counts_by_code[player.player_code] for player in players], float
                    )
                    if counts.sum() == 0:
                        continue
                    exposure = _exposure(players, head)
                    if ((counts > 0) & (exposure <= 0)).any():
                        raise ValueError("Credited phase event has no observed recipient exposure.")
                    features, feature_names = _features(
                        players, observation.duties, head=head, phase=phase
                    )
                    active = exposure > 0
                    groups.append(
                        _FittingGroup(features[active], np.log(exposure[active]), counts[active])
                    )
                    phase_counts[phase_index] += counts.sum()
                if groups:
                    fitted = _fit_recipient(tuple(groups), alpha=alpha, max_iter=max_iter)
                    coefficients[head, phase] = fitted
                    fitted_heads.append(
                        PhaseHeadMetadata(
                            head,
                            phase,
                            feature_names,
                            tuple(float(v) for v in fitted),
                            int(phase_counts[phase_index]),
                            len(groups),
                        )
                    )
            total = int(phase_counts.sum())
            phase_shares[head] = phase_counts / total if total else phase_counts
            event_totals[head] = total
        metadata = PhaseModelMetadata(
            contract_version="football_phase_duty_fit_v1",
            cutoff=cutoff,
            target_season=target_season,
            target_gameweek=target_gameweek,
            allowed_seasons=allowed_seasons,
            phase_definition_version=PHASE_DEFINITION_VERSION,
            observation_sha256=tuple(observation_digest(row) for row in ordered),
            training_receipts=tuple(
                PhaseTrainingReceipt(
                    observation_sha256=observation_digest(row),
                    season=row.season,
                    gameweek=row.gameweek,
                    fixture=row.fixture,
                    club=row.club,
                    opponent=row.opponent,
                    home=row.home,
                    kickoff=row.kickoff,
                    decision_at=row.decision_at,
                    outcome_available_at=row.outcome_available_at,
                    duties=row.duties,
                    baseline_source=row.baseline_source,
                    outcome_source=row.outcome_source,
                    totals_source=row.totals_source,
                    phase_definition_version=row.phase_definition_version,
                    rules_version=row.rules_version,
                    complete_coverage=row.complete_coverage,
                )
                for row in ordered
            ),
            goal_events=event_totals["goals"],
            assist_events=event_totals["assists"],
            goal_status="fitted" if event_totals["goals"] else "unavailable_no_credited_events",
            assist_status="fitted" if event_totals["assists"] else "unavailable_no_credited_events",
            alpha=alpha,
            max_iter=max_iter,
            recipient_heads=tuple(fitted_heads),
        )
        self._fitted = _FittedState(
            metadata=metadata,
            phase_shares=MappingProxyType(
                {head: _immutable_array(values) for head, values in phase_shares.items()}
            ),
            coefficients=MappingProxyType(
                {key: _immutable_array(values) for key, values in coefficients.items()}
            ),
        )
        return self

    def predict(self, projection: PhaseProjection) -> PhaseAllocation:
        fitted = self._fitted
        if fitted is None:
            raise ValueError("Phase duty model must be fitted before prediction.")
        metadata = fitted.metadata
        validate_projection(projection, model_cutoff=metadata.cutoff)
        if (
            projection.season != metadata.target_season
            or projection.gameweek < metadata.target_gameweek
        ):
            raise ValueError("Phase prediction must belong to the fitted target season/window.")
        codes = tuple(sorted(player.player_code for player in projection.states[0].players))
        total = {head: np.zeros(len(codes), float) for head in ("goals", "assists")}
        zero_mass_shares = {head: np.zeros(len(codes), float) for head in total}
        masses = {head: 0.0 for head in total}
        physical = 0.0
        state_results = []
        for state in projection.states:
            players = tuple(sorted(state.players, key=lambda player: player.player_code))
            allocated = {}
            shares = {}
            for head, mass in (("goals", state.goal_mass), ("assists", state.assist_mass)):
                composition = fitted.phase_shares[head]
                if mass > 0 and not composition.any():
                    raise ValueError(
                        f"Phase {head} unavailable without historical credited events."
                    )
                recipient = np.zeros(len(codes), float)
                exposure = _exposure(players, head)
                for phase, phase_share in zip(PHASES, composition, strict=True):
                    if phase_share == 0:
                        continue
                    features, _ = _features(players, projection.duties, head=head, phase=phase)
                    probabilities = _probabilities(
                        features, exposure, fitted.coefficients[head, phase]
                    )
                    if mass > 0 and not probabilities.any():
                        raise ValueError("Positive phase mass has no projected recipient exposure.")
                    recipient += phase_share * probabilities
                allocated[head] = mass * recipient
                shares[head] = recipient
                total[head] += state.weight * allocated[head]
                zero_mass_shares[head] += state.weight * recipient
                masses[head] += state.weight * mass
                if not _close(float(allocated[head].sum()), mass):
                    raise ValueError("Phase allocation did not conserve full-club attacking mass.")
            if any(
                value > state.physical_goal_mass
                and not _close(float(value), state.physical_goal_mass)
                for value in allocated["goals"] + allocated["assists"]
            ):
                raise ValueError(
                    "Player goal plus assist mass exceeds physical scoring-event mass."
                )
            physical += state.weight * state.physical_goal_mass
            state_results.append(
                PhaseStateAllocation(
                    state.state_id,
                    state.weight,
                    _records(
                        codes,
                        allocated["goals"],
                        allocated["assists"],
                        shares["goals"],
                        shares["assists"],
                    ),
                    state.goal_mass,
                    state.assist_mass,
                    state.physical_goal_mass,
                )
            )
        gs = total["goals"] / masses["goals"] if masses["goals"] else zero_mass_shares["goals"]
        aps = (
            total["assists"] / masses["assists"]
            if masses["assists"]
            else zero_mass_shares["assists"]
        )
        return PhaseAllocation(
            players=_records(codes, total["goals"], total["assists"], gs, aps),
            states=tuple(state_results),
            goal_phase_shares=tuple(float(value) for value in fitted.phase_shares["goals"]),
            assist_phase_shares=tuple(float(value) for value in fitted.phase_shares["assists"]),
            total_goals=masses["goals"],
            total_assists=masses["assists"],
            physical_goal_mass=physical,
            projection_sha256=projection_digest(projection),
            model_version=self.model_version,
            feature_version=self.feature_version,
            metadata=metadata,
        )
