"""Distinct conditional-recipient training with no fitted or placeholder count head."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from types import MappingProxyType

from squadopt.features.football_observed_tactical_inputs import (
    CONTEXT_POLICY,
    INPUT_VERSION,
    ROLE_POLICY,
    STYLE_VERSION,
    ObservedTacticalObservation,
    ObservedTacticalProjection,
    digest,
    instant,
    validate_projection,
)
from squadopt.prediction.football_observed_tactical import (
    FEATURE_VERSION,
    ObservedTacticalRecipientAllocation,
    ObservedTacticalTrainingReceipt,
    ObservedTacticalTransform,
    _fit_recipients,
    _projection_sources,
    _receipt,
    _recipient_sides,
    _validated_training,
)
from squadopt.prediction.football_tactical_matchup import Array, TacticalOptimizerReceipt

MODEL_VERSION = "football_observed_tactical_recipients_v1"
FIT_SCOPE = "conditional_recipient_likelihoods_only_no_count_head"


@dataclass(frozen=True)
class ObservedTacticalRecipientMetadata:
    model_version: str
    feature_version: str
    cutoff: str
    target_season: str
    target_gameweek: int
    allowed_seasons: tuple[str, ...]
    allow_released_2025_26: bool
    goal_transform: ObservedTacticalTransform
    assist_transform: ObservedTacticalTransform
    goal_gamma: tuple[float, ...]
    assist_gamma: tuple[float, ...]
    goal_events: int
    assist_events: int
    alpha: float
    max_iter: int
    training_receipts: tuple[ObservedTacticalTrainingReceipt, ...]
    optimizers: tuple[TacticalOptimizerReceipt, ...]
    fit_scope: str = FIT_SCOPE
    input_version: str = INPUT_VERSION
    style_version: str = STYLE_VERSION
    role_policy: str = ROLE_POLICY
    context_policy: str = CONTEXT_POLICY
    scope: str = (
        "four_observed_channels_nullable_FM_prior_provider_roles_not_complete_tactical_family"
    )
    native_share_policy: str = "supplied_native_recipient_shares_already_include_native_exposure"


@dataclass(frozen=True)
class _RecipientFitted:
    metadata: ObservedTacticalRecipientMetadata
    metadata_json: str
    sha256: str
    gammas: Mapping[str, Array]


def _canonical(metadata: ObservedTacticalRecipientMetadata) -> str:
    return json.dumps(asdict(metadata), sort_keys=True, separators=(",", ":"), allow_nan=False)


def _verify(fitted: _RecipientFitted) -> None:
    m = fitted.metadata
    if (
        _canonical(m) != fitted.metadata_json
        or hashlib.sha256(fitted.metadata_json.encode()).hexdigest() != fitted.sha256
        or m.model_version != MODEL_VERSION
        or m.feature_version != FEATURE_VERSION
        or m.fit_scope != FIT_SCOPE
        or tuple(fitted.gammas["goals"]) != m.goal_gamma
        or tuple(fitted.gammas["assists"]) != m.assist_gamma
        or any(r.head not in ("goals", "assists") for r in m.optimizers)
    ):
        raise ValueError("Observed tactical recipient coefficients and metadata differ.")


class ObservedTacticalRecipientModel:
    """Fit only the two conditional recipient likelihoods at native marginal context."""

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
        self._fitted: _RecipientFitted | None = None

    def _require(self) -> _RecipientFitted:
        if self._fitted is None:
            raise ValueError("Observed tactical recipient model has not been fitted.")
        _verify(self._fitted)
        return self._fitted

    @property
    def metadata(self) -> ObservedTacticalRecipientMetadata:
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
    ) -> ObservedTacticalRecipientModel:
        ordered = _validated_training(
            observations,
            cutoff=cutoff,
            target_season=target_season,
            target_gameweek=target_gameweek,
            allowed_seasons=allowed_seasons,
            allow_released_2025_26=allow_released_2025_26,
        )
        transforms, gammas, counts, optimizers = _fit_recipients(
            ordered,
            alpha=self._alpha,
            max_iter=self._max_iter,
        )
        metadata = ObservedTacticalRecipientMetadata(
            MODEL_VERSION,
            FEATURE_VERSION,
            cutoff,
            target_season,
            target_gameweek,
            allowed_seasons,
            allow_released_2025_26,
            transforms["goals"],
            transforms["assists"],
            tuple(float(v) for v in gammas["goals"]),
            tuple(float(v) for v in gammas["assists"]),
            counts["goals"],
            counts["assists"],
            self._alpha,
            self._max_iter,
            tuple(_receipt(o) for o in ordered),
            tuple(optimizers),
        )
        document = _canonical(metadata)
        fitted = _RecipientFitted(
            metadata,
            document,
            hashlib.sha256(document.encode()).hexdigest(),
            MappingProxyType(gammas),
        )
        _verify(fitted)
        self._fitted = fitted
        return self

    def predict_recipients(
        self, p: ObservedTacticalProjection, *, control: bool = False
    ) -> ObservedTacticalRecipientAllocation:
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
        home, away = _recipient_sides(
            p,
            goal_transform=m.goal_transform,
            assist_transform=m.assist_transform,
            goal_events=m.goal_events,
            assist_events=m.assist_events,
            gammas=fitted.gammas,
            control=control,
        )
        return ObservedTacticalRecipientAllocation(
            home,
            away,
            digest(p),
            fitted.sha256,
            MODEL_VERSION,
            FEATURE_VERSION,
            m.cutoff,
            tuple(sorted(_projection_sources(p))),
            control,
        )
