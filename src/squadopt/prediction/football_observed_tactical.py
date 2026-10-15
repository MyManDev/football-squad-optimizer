"""Observed tactical effects at a declared full-roster native marginal context."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Any

import numpy as np
from scipy.optimize import minimize

from squadopt.features.football_observed_tactical_inputs import (
    CONTEXT_POLICY,
    INPUT_VERSION,
    ROLE_POLICY,
    STYLE_VERSION,
    ObservedTacticalObservation,
    ObservedTacticalProjection,
    digest,
    instant,
    recipient_features,
    team_features,
    validate_header,
    validate_outcome,
    validate_projection,
)
from squadopt.prediction.football_tactical_matchup import (
    Array,
    TacticalOptimizerReceipt,
    _immutable,
    _pair_terms,
    _PairGroup,
    _rates,
    _recipient_probabilities,
    _recipient_terms,
    _RecipientGroup,
)

MODEL_VERSION = "football_observed_tactical_marginal_context_v2"
FEATURE_VERSION = "four_event_observed_support_lagged_roles_masked_traits_v2"
TRANSFORM_VERSION = "training_weighted_observed_values_and_missing_masks_v1"
RECIPIENT_POLICY = "native_offset_observed_tactical_recipient_only_v1"
HEADS = ("goals", "assists")


@dataclass(frozen=True)
class ObservedTacticalTransform:
    features: tuple[str, ...]
    means: tuple[float, ...]
    scales: tuple[float, ...]
    observed_weights: tuple[float, ...]
    observed_counts: tuple[int, ...]
    mask_means: tuple[float, ...]
    mask_scales: tuple[float, ...]
    active: tuple[bool, ...]
    weighting: str
    version: str = TRANSFORM_VERSION
    unsupported_policy: str = "training_unobserved_numeric_and_mask_columns_remain_disabled"

    def apply(self, rows: Sequence[Mapping[str, float | None]]) -> Array:
        result = np.zeros((len(rows), 2 * len(self.features)), dtype=float)
        for i, row in enumerate(rows):
            if tuple(row) != self.features:
                raise ValueError("Observed tactical prediction feature contract differs.")
            for j, name in enumerate(self.features):
                value = row[name]
                if value is not None and (
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(value)
                ):
                    raise ValueError(
                        "Observed tactical feature must be finite or explicitly unknown."
                    )
                if self.active[j]:
                    if value is not None:
                        result[i, 2 * j] = (value - self.means[j]) / self.scales[j]
                    result[i, 2 * j + 1] = (
                        float(value is not None) - self.mask_means[j]
                    ) / self.mask_scales[j]
        if not np.isfinite(result).all():
            raise ValueError("Observed tactical transformed feature exceeds finite support.")
        return result


def fit_transform(
    rows: Sequence[Mapping[str, float | None]], weights: Sequence[float], *, weighting: str
) -> ObservedTacticalTransform:
    """Estimate every value/mask moment solely on positive training input weights."""
    if not rows or len(rows) != len(weights):
        raise ValueError("Observed tactical transform requires aligned nonempty inputs.")
    names = tuple(rows[0])
    if not names or any(tuple(row) != names for row in rows):
        raise ValueError("Observed tactical transform feature identities differ.")
    if any(
        isinstance(w, bool) or not isinstance(w, (int, float)) or not math.isfinite(w) or w < 0
        for w in weights
    ):
        raise ValueError("Observed tactical transform weights must be finite and nonnegative.")
    total = math.fsum(weights)
    if total <= 0 or not math.isfinite(total):
        raise ValueError("Observed tactical transform needs positive finite native input support.")
    means, scales, known_weights, counts, mask_means, mask_scales, active = (
        [],
        [],
        [],
        [],
        [],
        [],
        [],
    )
    for name in names:
        observed = []
        for row, weight in zip(rows, weights, strict=True):
            value = row[name]
            if value is not None:
                if (
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(value)
                ):
                    raise ValueError(
                        "Observed tactical transform cannot impute nonfinite evidence."
                    )
                if weight > 0:
                    observed.append((value, weight))
        support = math.fsum(w for _, w in observed)
        mean = math.fsum(v * w for v, w in observed) / support if support else 0.0
        variance = math.fsum(w * (v - mean) ** 2 for v, w in observed) / support if support else 0.0
        spread = math.sqrt(variance)
        scale = spread if observed and spread > 1e-12 * max(abs(v) for v, _ in observed) else 1.0
        fraction = support / total
        mask_scale = math.sqrt(max(0.0, fraction * (1 - fraction))) if 0 < fraction < 1 else 1.0
        if (
            not all(math.isfinite(v) for v in (support, mean, scale, fraction, mask_scale))
            or scale <= 0
        ):
            raise ValueError("Observed tactical transform moments exceed finite support.")
        means.append(mean)
        scales.append(scale)
        known_weights.append(support)
        counts.append(len(observed))
        mask_means.append(fraction)
        mask_scales.append(mask_scale)
        active.append(bool(support))
    return ObservedTacticalTransform(
        names,
        tuple(means),
        tuple(scales),
        tuple(known_weights),
        tuple(counts),
        tuple(mask_means),
        tuple(mask_scales),
        tuple(active),
        weighting,
    )


@dataclass(frozen=True)
class ObservedTacticalTrainingReceipt:
    observation_sha256: str
    projection_sha256: str
    season: str
    gameweek: int
    fixture: int
    feature_cutoff: str
    generated_at: str
    outcome_available_at: str
    observed_fixture_ids: tuple[tuple[int, tuple[int, ...]], ...]
    source_hashes: tuple[str, ...]
    replay_version: str | None


@dataclass(frozen=True)
class ObservedTacticalMetadata:
    model_version: str
    feature_version: str
    cutoff: str
    target_season: str
    target_gameweek: int
    allowed_seasons: tuple[str, ...]
    allow_released_2025_26: bool
    team_transform: ObservedTacticalTransform
    goal_transform: ObservedTacticalTransform
    assist_transform: ObservedTacticalTransform
    beta: tuple[float, ...]
    goal_gamma: tuple[float, ...]
    assist_gamma: tuple[float, ...]
    goal_events: int
    assist_events: int
    alpha: float
    max_iter: int
    training_receipts: tuple[ObservedTacticalTrainingReceipt, ...]
    optimizers: tuple[TacticalOptimizerReceipt, ...]
    input_version: str = INPUT_VERSION
    style_version: str = STYLE_VERSION
    role_policy: str = ROLE_POLICY
    context_policy: str = CONTEXT_POLICY
    scope: str = (
        "four_observed_channels_nullable_FM_prior_provider_roles_not_complete_tactical_family"
    )
    native_share_policy: str = "supplied_native_recipient_shares_already_include_native_exposure"
    event_scope: str = "paired_Poisson_and_separate_recipient_marginals_at_native_marginal_context"


@dataclass(frozen=True)
class ObservedTacticalAllocatedPlayer:
    player_code: int
    club: int
    position: str
    goals: float
    assists: float


@dataclass(frozen=True)
class ObservedTacticalSideAllocation:
    club: int
    team_goal_rate: float
    players: tuple[ObservedTacticalAllocatedPlayer, ...]


@dataclass(frozen=True)
class ObservedTacticalAllocation:
    home: ObservedTacticalSideAllocation
    away: ObservedTacticalSideAllocation
    projection_sha256: str
    model_sha256: str
    model_version: str
    feature_version: str
    metadata: ObservedTacticalMetadata
    control: bool


@dataclass(frozen=True)
class ObservedTacticalRecipient:
    player_code: int
    club: int
    position: str
    goal_share: float
    assist_share: float


@dataclass(frozen=True)
class ObservedTacticalRecipientSide:
    club: int
    players: tuple[ObservedTacticalRecipient, ...]


@dataclass(frozen=True)
class ObservedTacticalRecipientAllocation:
    home: ObservedTacticalRecipientSide
    away: ObservedTacticalRecipientSide
    projection_sha256: str
    model_sha256: str
    model_version: str
    feature_version: str
    model_cutoff: str
    source_hashes: tuple[str, ...]
    control: bool
    policy: str = RECIPIENT_POLICY


@dataclass(frozen=True)
class _Fitted:
    metadata: ObservedTacticalMetadata
    metadata_json: str
    sha256: str
    beta: Array
    gammas: Mapping[str, Array]


def _canonical(metadata: ObservedTacticalMetadata) -> str:
    return json.dumps(asdict(metadata), sort_keys=True, separators=(",", ":"), allow_nan=False)


def _verify(fitted: _Fitted) -> None:
    m = fitted.metadata
    if (
        _canonical(m) != fitted.metadata_json
        or hashlib.sha256(fitted.metadata_json.encode()).hexdigest() != fitted.sha256
        or m.model_version != MODEL_VERSION
        or m.feature_version != FEATURE_VERSION
        or tuple(fitted.beta) != m.beta
        or tuple(fitted.gammas["goals"]) != m.goal_gamma
        or tuple(fitted.gammas["assists"]) != m.assist_gamma
    ):
        raise ValueError("Observed tactical fitted coefficients and metadata differ.")


class ObservedTacticalOptimizationError(ValueError):
    """Rejected optimizer output, with safe exact diagnostic declarations retained."""

    def __init__(self, message: str, diagnostics: dict[str, object]):
        super().__init__(message)
        self.diagnostics = diagnostics


def _optimizer_failure(
    result: Any, raw: Array, *, head: str, max_iter: int, reason: str
) -> ObservedTacticalOptimizationError:
    values: dict[str, object] = {"head": head, "max_iter": max_iter, "reason": reason}
    for name in ("status", "nit", "nfev"):
        value = getattr(result, name, None)
        values[name] = value if type(value) is int else None
    success = getattr(result, "success", None)
    values["success"] = bool(success) if isinstance(success, (bool, np.bool_)) else None
    message, objective = getattr(result, "message", None), getattr(result, "fun", None)
    values["message"] = message[:1024] if type(message) is str else None
    values["reported_objective"] = (
        float(objective)
        if isinstance(objective, (float, np.floating)) and math.isfinite(float(objective))
        else None
    )
    values["coefficient_dtype"] = str(raw.dtype)
    values["coefficient_shape"] = tuple(int(n) for n in raw.shape)
    values["coefficients_finite"] = (
        bool(np.isfinite(raw).all()) if raw.dtype.kind in "fiu" else False
    )
    return ObservedTacticalOptimizationError(reason, values)


def _optimize(
    objective: Callable[[Array], tuple[float, Array]], width: int, max_iter: int, head: str
) -> tuple[Array, TacticalOptimizerReceipt]:
    result: Any = minimize(
        objective,
        np.zeros(width),
        jac=True,
        method="L-BFGS-B",
        options={"maxiter": max_iter, "ftol": 1e-12, "gtol": 1e-7},
    )
    raw_coefficients = np.asarray(getattr(result, "x", ()))
    if raw_coefficients.dtype.kind not in "fiu":
        raise _optimizer_failure(
            result,
            raw_coefficients,
            head=head,
            max_iter=max_iter,
            reason="Observed tactical optimizer coefficients must be real numeric values.",
        )
    coefficients = raw_coefficients.astype(float, copy=False)
    if (
        not isinstance(getattr(result, "success", None), (bool, np.bool_))
        or not result.success
        or type(getattr(result, "status", None)) is not int
        or result.status != 0
        or type(getattr(result, "nit", None)) is not int
        or not 0 <= result.nit <= max_iter
        or type(getattr(result, "nfev", None)) is not int
        or result.nfev <= 0
        or coefficients.shape != (width,)
        or not np.isfinite(coefficients).all()
    ):
        raise _optimizer_failure(
            result,
            raw_coefficients,
            head=head,
            max_iter=max_iter,
            reason="Observed tactical optimizer did not converge finitely.",
        )
    value, gradient = objective(coefficients)
    if not math.isfinite(value) or gradient.shape != (width,) or not np.isfinite(gradient).all():
        raise _optimizer_failure(
            result,
            raw_coefficients,
            head=head,
            max_iter=max_iter,
            reason="Observed tactical objective/gradient is not finite.",
        )
    return _immutable(coefficients), TacticalOptimizerReceipt(
        head,
        "L-BFGS-B",
        "zero_vector",
        True,
        result.status,
        result.nit,
        result.nfev,
        float(value),
        float(np.max(np.abs(gradient))),
    )


def _projection_sources(p: ObservedTacticalProjection) -> set[str]:
    sources = {
        p.native_source.sha256,
        p.roster_source.sha256,
    }
    for side in (p.home, p.away):
        for fixture in side.observed_fixtures:
            sources.update((fixture.source.sha256, fixture.bridge_sha256, fixture.inventory_sha256))
        for player in side.players:
            profile = player.profile
            if profile.role_inventory_sha256 is not None:
                sources.add(profile.role_inventory_sha256)
            if profile.trait_source is not None:
                sources.add(profile.trait_source.sha256)
            sources.update(r.source.sha256 for r in profile.role_history)
    if p.replay is not None:
        sources.update(h for _, h in p.replay.source_hashes)
    return sources


def _receipt(o: ObservedTacticalObservation) -> ObservedTacticalTrainingReceipt:
    p = o.projection
    sources = _projection_sources(p) | {o.goal_source.sha256, o.credit_source.sha256}
    return ObservedTacticalTrainingReceipt(
        digest(o),
        digest(p),
        p.season,
        p.gameweek,
        p.fixture,
        p.feature_cutoff,
        p.generated_at,
        o.outcome_available_at,
        tuple((s.club, tuple(f.fixture for f in s.observed_fixtures)) for s in (p.home, p.away)),
        tuple(sorted(sources)),
        p.replay.version if p.replay is not None else None,
    )


def _recipient_sides(
    p: ObservedTacticalProjection,
    *,
    goal_transform: ObservedTacticalTransform,
    assist_transform: ObservedTacticalTransform,
    goal_events: int,
    assist_events: int,
    gammas: Mapping[str, Array],
    control: bool,
) -> tuple[ObservedTacticalRecipientSide, ObservedTacticalRecipientSide]:
    """Shared exact conditional allocation, without a count head or training receipt."""
    result = []
    for i, side in enumerate((p.home, p.away)):
        players = sorted(side.players, key=lambda x: x.profile.player_code)
        heads = {}
        for head, fraction, transform in (
            ("goals", side.scored_fraction, goal_transform),
            ("assists", side.scored_fraction * side.assist_fraction, assist_transform),
        ):
            if (
                not control
                and fraction > 0
                and (goal_events if head == "goals" else assist_events) == 0
            ):
                raise ValueError("Observed tactical head has no historical credited-event support.")
            shares = np.asarray(
                [
                    getattr(x, "native_goal_share" if head == "goals" else "native_assist_share")
                    for x in players
                ]
            )
            probabilities = (
                shares
                if control
                else _recipient_probabilities(
                    shares[None, :],
                    transform.apply(
                        [recipient_features(p, x, home=i == 0, head=head) for x in players]
                    )[None, :, :],
                    gammas[head],
                )[0][0]
            )
            if (
                probabilities.shape != shares.shape
                or not np.isfinite(probabilities).all()
                or np.any(probabilities < 0)
                or np.any(probabilities > 1)
                or np.any(probabilities[shares == 0] != 0)
                or not math.isclose(math.fsum(probabilities), 1.0, rel_tol=1e-12, abs_tol=1e-12)
            ):
                raise ValueError("Observed tactical recipient shares violate support or mass.")
            heads[head] = probabilities
        allocated = []
        for player, goals, assists in zip(players, heads["goals"], heads["assists"], strict=True):
            physical_fraction = side.scored_fraction * (goals + side.assist_fraction * assists)
            if physical_fraction > 1 and not math.isclose(
                float(physical_fraction), 1.0, rel_tol=1e-12, abs_tol=1e-12
            ):
                raise ValueError("Observed tactical player G+A exceeds physical goal share.")
            allocated.append(
                ObservedTacticalRecipient(
                    player.profile.player_code,
                    side.club,
                    player.profile.fpl_position,
                    float(goals),
                    float(assists),
                )
            )
        result.append(ObservedTacticalRecipientSide(side.club, tuple(allocated)))
    return result[0], result[1]


def _validated_training(
    observations: tuple[ObservedTacticalObservation, ...],
    *,
    cutoff: str,
    target_season: str,
    target_gameweek: int,
    allowed_seasons: tuple[str, ...],
    allow_released_2025_26: bool,
) -> list[ObservedTacticalObservation]:
    if type(observations) is not tuple or not observations:
        raise ValueError("Observed tactical fit requires immutable nonempty observations.")
    seen: set[tuple[str, int]] = set()
    clocks: dict[tuple[str, int], datetime] = {}
    for o in observations:
        validate_header(
            o,
            cutoff=cutoff,
            target_season=target_season,
            target_gameweek=target_gameweek,
            allowed_seasons=allowed_seasons,
            allow_released_2025_26=allow_released_2025_26,
        )
        p = o.projection
        if (p.season, p.fixture) in seen:
            raise ValueError("Observed tactical training repeats a paired fixture.")
        seen.add((p.season, p.fixture))
        key, clock = (p.season, p.gameweek), instant(p.decision_at)
        if key in clocks and clocks[key] != clock:
            raise ValueError("Observed tactical historical GW requires one original decision.")
        clocks[key] = clock
    for o in observations:
        validate_outcome(o)
    return sorted(observations, key=lambda o: (o.projection.season, o.projection.fixture))


def _fit_recipients(
    ordered: Sequence[ObservedTacticalObservation],
    *,
    alpha: float,
    max_iter: int,
) -> tuple[
    dict[str, ObservedTacticalTransform],
    dict[str, Array],
    dict[str, int],
    list[TacticalOptimizerReceipt],
]:
    optimizers: list[TacticalOptimizerReceipt] = []
    transforms, gammas, counts = {}, {}, {}
    for head in HEADS:
        feature_rows: list[dict[str, float | None]] = []
        feature_weights: list[float] = []
        bases, labels, sizes = [], [], []
        for o in ordered:
            credit = {c.player_code: getattr(c, head) for c in o.credits}
            for home, side in ((True, o.projection.home), (False, o.projection.away)):
                players = sorted(side.players, key=lambda p: p.profile.player_code)
                shares = np.asarray(
                    [
                        getattr(
                            p, "native_goal_share" if head == "goals" else "native_assist_share"
                        )
                        for p in players
                    ]
                )
                feature_rows.extend(
                    recipient_features(o.projection, p, home=home, head=head) for p in players
                )
                feature_weights.extend(float(s) / 2 for s in shares)
                bases.append(shares)
                labels.append(np.asarray([credit[p.profile.player_code] for p in players], float))
                sizes.append(len(players))
        rt = fit_transform(
            feature_rows,
            feature_weights,
            weighting="one_paired_fixture_native_marginal_context_native_share_half_per_side_no_labels",
        )
        transformed = rt.apply(feature_rows)
        groups, offset = [], 0
        for shares, label, size in zip(bases, labels, sizes, strict=True):
            if label.sum() > 0:
                groups.append(
                    _RecipientGroup(
                        transformed[offset : offset + size][None, :, :],
                        shares[None, :],
                        np.ones(1),
                        label,
                    )
                )
            offset += size
        transforms[head] = rt
        counts[head] = sum(int(label.sum()) for label in labels)

        def recipient_objective(
            gamma: Array, fitting_groups: tuple[_RecipientGroup, ...] = tuple(groups)
        ) -> tuple[float, Array]:
            value, gradient = alpha * float(gamma @ gamma) / 2, alpha * gamma.copy()
            for group in fitting_groups:
                likelihood, score = _recipient_terms(group, gamma)
                value -= likelihood
                gradient += score
            return value, gradient

        if groups:
            gammas[head], optimizer = _optimize(
                recipient_objective, transformed.shape[1], max_iter, head
            )
            optimizers.append(optimizer)
        else:
            gammas[head] = _immutable(np.zeros(transformed.shape[1]))
    return transforms, gammas, counts, optimizers


class ObservedTacticalModel:
    """Learn only the distinct declared observed-source effects, never missing facts."""

    model_version = MODEL_VERSION
    feature_version = FEATURE_VERSION

    def __init__(self, *, alpha: float = 0.1, max_iter: int = 500):
        if (
            isinstance(alpha, bool)
            or not isinstance(alpha, (float, int))
            or not math.isfinite(alpha)
            or alpha < 0
            or type(max_iter) is not int
            or not 1 <= max_iter <= 2000
        ):
            raise ValueError("Observed tactical fit requires finite alpha and bounded iterations.")
        self._alpha, self._max_iter = float(alpha), max_iter
        self._fitted: _Fitted | None = None

    def _require(self) -> _Fitted:
        if self._fitted is None:
            raise ValueError("Observed tactical model has not been fitted.")
        _verify(self._fitted)
        return self._fitted

    @property
    def metadata(self) -> ObservedTacticalMetadata:
        return self._require().metadata

    @property
    def metadata_json(self) -> str:
        return self._require().metadata_json

    @property
    def model_sha256(self) -> str:
        return self._require().sha256

    def fit(
        self,
        observations: tuple[ObservedTacticalObservation, ...],
        *,
        cutoff: str,
        target_season: str,
        target_gameweek: int,
        allowed_seasons: tuple[str, ...],
        allow_released_2025_26: bool = False,
    ) -> ObservedTacticalModel:
        ordered = _validated_training(
            observations,
            cutoff=cutoff,
            target_season=target_season,
            target_gameweek=target_gameweek,
            allowed_seasons=allowed_seasons,
            allow_released_2025_26=allow_released_2025_26,
        )
        raw = [team_features(o.projection, home=home) for o in ordered for home in (True, False)]
        transform = fit_transform(
            raw,
            [0.5] * len(raw),
            weighting="one_paired_fixture_native_marginal_context_half_per_side_no_labels",
        )
        matrix = transform.apply(raw)
        pairs = tuple(
            _PairGroup(
                matrix[2 * i : 2 * i + 2][None, :, :],
                np.asarray([[o.projection.home.base_goal_rate, o.projection.away.base_goal_rate]]),
                np.ones(1),
                np.asarray(o.physical_goals, float),
            )
            for i, o in enumerate(ordered)
        )
        alpha = self._alpha

        def pair_objective(beta: Array) -> tuple[float, Array]:
            value, gradient = alpha * float(beta @ beta) / 2, alpha * beta.copy()
            for group in pairs:
                likelihood, _, score = _pair_terms(group, beta)
                value -= likelihood
                gradient += score
            return value, gradient

        beta, optimizer = _optimize(
            pair_objective, matrix.shape[1], self._max_iter, "physical_pair"
        )
        optimizers = [optimizer]
        transforms, gammas, counts, recipient_optimizers = _fit_recipients(
            ordered,
            alpha=alpha,
            max_iter=self._max_iter,
        )
        optimizers.extend(recipient_optimizers)
        metadata = ObservedTacticalMetadata(
            MODEL_VERSION,
            FEATURE_VERSION,
            cutoff,
            target_season,
            target_gameweek,
            allowed_seasons,
            allow_released_2025_26,
            transform,
            transforms["goals"],
            transforms["assists"],
            tuple(float(v) for v in beta),
            tuple(float(v) for v in gammas["goals"]),
            tuple(float(v) for v in gammas["assists"]),
            counts["goals"],
            counts["assists"],
            alpha,
            self._max_iter,
            tuple(_receipt(o) for o in ordered),
            tuple(optimizers),
        )
        encoded = _canonical(metadata)
        fitted = _Fitted(
            metadata,
            encoded,
            hashlib.sha256(encoded.encode()).hexdigest(),
            beta,
            MappingProxyType(gammas),
        )
        _verify(fitted)
        self._fitted = fitted
        return self

    def _serving_context(self, p: ObservedTacticalProjection, control: bool) -> _Fitted:
        fitted = self._require()
        if type(control) is not bool:
            raise ValueError("Observed tactical control must be Boolean.")
        if p.replay is not None:
            raise ValueError("Observed tactical prediction requires prospective source clocks.")
        validate_projection(p)
        m = fitted.metadata
        if (
            p.season != m.target_season
            or p.gameweek < m.target_gameweek
            or instant(p.decision_at) < instant(m.cutoff)
        ):
            raise ValueError("Observed tactical projection is outside the fitted target window.")
        return fitted

    def predict_recipients(
        self, p: ObservedTacticalProjection, *, control: bool = False
    ) -> ObservedTacticalRecipientAllocation:
        """Apply only conditional recipient heads, without evaluating the paired-rate head."""
        fitted = self._serving_context(p, control)
        m = fitted.metadata
        result = _recipient_sides(
            p,
            goal_transform=m.goal_transform,
            assist_transform=m.assist_transform,
            goal_events=m.goal_events,
            assist_events=m.assist_events,
            gammas=fitted.gammas,
            control=control,
        )
        return ObservedTacticalRecipientAllocation(
            result[0],
            result[1],
            digest(p),
            fitted.sha256,
            MODEL_VERSION,
            FEATURE_VERSION,
            m.cutoff,
            tuple(sorted(_projection_sources(p))),
            control,
        )

    def predict(
        self, p: ObservedTacticalProjection, *, control: bool = False
    ) -> ObservedTacticalAllocation:
        fitted = self._serving_context(p, control)
        m = fitted.metadata
        bases = np.asarray([p.home.base_goal_rate, p.away.base_goal_rate])
        rates = (
            bases
            if control
            else _rates(
                bases,
                m.team_transform.apply([team_features(p, home=True), team_features(p, home=False)]),
                fitted.beta,
            )
        )
        result = []
        for i, side in enumerate((p.home, p.away)):
            players = sorted(side.players, key=lambda x: x.profile.player_code)
            expectations = {}
            for head, fraction, transform in (
                ("goals", side.scored_fraction, m.goal_transform),
                ("assists", side.scored_fraction * side.assist_fraction, m.assist_transform),
            ):
                mass = float(rates[i]) * fraction
                if (
                    not control
                    and mass > 0
                    and (m.goal_events if head == "goals" else m.assist_events) == 0
                ):
                    raise ValueError(
                        "Observed tactical head has no historical credited-event support."
                    )
                shares = np.asarray(
                    [
                        getattr(
                            x, "native_goal_share" if head == "goals" else "native_assist_share"
                        )
                        for x in players
                    ]
                )
                probabilities = (
                    shares
                    if control
                    else _recipient_probabilities(
                        shares[None, :],
                        transform.apply(
                            [recipient_features(p, x, home=i == 0, head=head) for x in players]
                        )[None, :, :],
                        fitted.gammas[head],
                    )[0][0]
                )
                expectations[head] = mass * probabilities
                if not math.isclose(
                    math.fsum(expectations[head]), mass, rel_tol=1e-12, abs_tol=1e-12
                ):
                    raise ValueError(
                        "Observed tactical full-club recipient mass was not conserved."
                    )
            allocated = []
            for player, goals, assists in zip(
                players, expectations["goals"], expectations["assists"], strict=True
            ):
                own = float(rates[i])
                if goals + assists > own and not math.isclose(
                    float(goals + assists), own, rel_tol=1e-12, abs_tol=1e-12
                ):
                    raise ValueError(
                        "Observed tactical player G+A exceeds physical goal intensity."
                    )
                allocated.append(
                    ObservedTacticalAllocatedPlayer(
                        player.profile.player_code,
                        side.club,
                        player.profile.fpl_position,
                        float(goals),
                        float(assists),
                    )
                )
            result.append(
                ObservedTacticalSideAllocation(side.club, float(rates[i]), tuple(allocated))
            )
        return ObservedTacticalAllocation(
            result[0],
            result[1],
            digest(p),
            fitted.sha256,
            MODEL_VERSION,
            FEATURE_VERSION,
            m,
            control,
        )
