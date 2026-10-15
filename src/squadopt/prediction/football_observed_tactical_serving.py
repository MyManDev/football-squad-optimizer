"""Compact recipient-only inference; retained byte integrity is not source authenticity."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field, fields
from types import MappingProxyType
from typing import Any

import numpy as np

from squadopt.features.football_observed_tactical_inputs import (
    CHANNELS,
    CONTEXT_POLICY,
    INPUT_VERSION,
    ROLE_POLICY,
    ROLES,
    STYLE_VERSION,
    ObservedTacticalProjection,
    _release,
    digest,
    instant,
    sha,
    validate_projection,
)
from squadopt.features.football_tactical_inputs import (
    ATTACK_TRAITS,
    DEFENSE_TRAITS,
    DELIVERY_TRAITS,
)
from squadopt.prediction.football_observed_tactical import (
    FEATURE_VERSION,
    MODEL_VERSION,
    RECIPIENT_POLICY,
    TRANSFORM_VERSION,
    ObservedTacticalModel,
    ObservedTacticalRecipientSide,
    ObservedTacticalTransform,
    _projection_sources,
    _recipient_sides,
)
from squadopt.prediction.football_observed_tactical_recipients import (
    FIT_SCOPE as RECIPIENT_FIT_SCOPE,
)
from squadopt.prediction.football_observed_tactical_recipients import (
    MODEL_VERSION as RECIPIENT_MODEL_VERSION,
)
from squadopt.prediction.football_observed_tactical_recipients import (
    ObservedTacticalRecipientModel,
)
from squadopt.prediction.football_tactical_matchup import Array, _immutable

SERVING_VERSION = "football_observed_tactical_recipient_serving_v2"
FULL_FIT_SCOPE = "paired_Poisson_and_separate_recipient_marginals_at_native_marginal_context"
MAX_ARTIFACT_BYTES = 262_144
WEIGHTING = "one_paired_fixture_native_marginal_context_native_share_half_per_side_no_labels"
UNSUPPORTED_POLICY = "training_unobserved_numeric_and_mask_columns_remain_disabled"


@dataclass(frozen=True)
class ObservedTacticalServingMetadata:
    serving_version: str
    original_metadata_sha256: str
    observation_count: int
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
    fit_scope: str = FULL_FIT_SCOPE
    model_version: str = MODEL_VERSION
    feature_version: str = FEATURE_VERSION
    input_version: str = INPUT_VERSION
    style_version: str = STYLE_VERSION
    role_policy: str = ROLE_POLICY
    context_policy: str = CONTEXT_POLICY
    recipient_policy: str = RECIPIENT_POLICY


@dataclass(frozen=True)
class ObservedTacticalServingReceipt:
    serving_version: str
    artifact_sha256: str
    original_metadata_sha256: str
    cutoff: str
    target_season: str
    target_gameweek: int


@dataclass(frozen=True)
class ObservedTacticalServingAllocation:
    home: ObservedTacticalRecipientSide
    away: ObservedTacticalRecipientSide
    projection_sha256: str
    source_hashes: tuple[str, ...]
    model_version: str
    feature_version: str
    policy: str
    control: bool
    serving_receipt: ObservedTacticalServingReceipt


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _finite(value: object) -> float:
    if type(value) not in (int, float):
        raise ValueError("Observed tactical serving values must be real numbers.")
    try:
        result = float(value)  # type: ignore[arg-type]
    except OverflowError as error:
        raise ValueError("Observed tactical serving value exceeds finite support.") from error
    if not math.isfinite(result):
        raise ValueError("Observed tactical serving values must be finite.")
    return result


def _count(value: object, minimum: int = 0) -> int:
    if type(value) is not int or not minimum <= value <= 2**53:
        raise ValueError("Observed tactical serving counts must be exact supported integers.")
    return value


def _feature_names(head: str) -> tuple[str, ...]:
    names = [
        prefix + suffix
        for prefix in ("own_", "opponent_")
        for suffix in (*(f"observed_{c}_per_fixture" for c in CHANNELS), "observed_fixture_count")
    ]
    for prefix, traits in (
        ("opponent_defending_", DEFENSE_TRAITS),
        ("opponent_keeper_", ("gk_aerial_reach",)),
    ):
        for trait in traits:
            names.extend(
                prefix + trait + suffix
                for suffix in ("", "_observed_weight_fraction", "_known_player_count")
            )
    names.extend("player_" + t for t in (ATTACK_TRAITS if head == "goals" else DELIVERY_TRAITS))
    names.extend("provider_role_" + role for role in ROLES)
    names.extend(
        (
            "own_observed_cross_attempts_per_fixture*player_heading*opponent_defending_heading",
            "own_observed_throughball_attempts_per_fixture*player_off_the_ball*opponent_defending_positioning",
        )
        if head == "goals"
        else (
            "own_observed_cross_attempts_per_fixture*player_crossing*opponent_defending_heading",
            "own_observed_throughball_attempts_per_fixture*player_vision*opponent_defending_anticipation",
        )
    )
    return tuple(names)


def _transform(t: ObservedTacticalTransform, head: str, observations: int) -> None:
    if (
        type(t) is not ObservedTacticalTransform
        or type(t.features) is not tuple
        or t.features != _feature_names(head)
        or t.version != TRANSFORM_VERSION
        or t.weighting != WEIGHTING
        or t.unsupported_policy != UNSUPPORTED_POLICY
    ):
        raise ValueError("Observed tactical serving transform feature/policy contract differs.")
    vectors = (
        t.means,
        t.scales,
        t.observed_weights,
        t.observed_counts,
        t.mask_means,
        t.mask_scales,
        t.active,
    )
    if any(type(v) is not tuple or len(v) != len(t.features) for v in vectors):
        raise ValueError("Observed tactical serving transform dimensions differ.")
    for mean, scale, weight, count, fraction, mask_scale, active in zip(*vectors, strict=True):
        mean, scale, weight, fraction, mask_scale = (
            _finite(v) for v in (mean, scale, weight, fraction, mask_scale)
        )
        count = _count(count)
        if (
            type(active) is not bool
            or active != (count > 0)
            or active != (weight > 0)
            or scale <= 0
            or mask_scale <= 0
            or weight < 0
            or weight > observations + 1e-12 * max(1, observations)
            or count > 128 * observations
            or not 0 <= fraction <= 1
            or active != (fraction > 0)
            or not math.isclose(fraction, weight / observations, rel_tol=1e-12, abs_tol=1e-12)
        ):
            raise ValueError("Observed tactical serving transform support/moments disagree.")
        expected_mask_scale = math.sqrt(fraction * (1 - fraction)) if 0 < fraction < 1 else 1.0
        if not math.isclose(mask_scale, expected_mask_scale, rel_tol=1e-12, abs_tol=1e-12):
            raise ValueError("Observed tactical serving mask scale disagrees with its support.")
        if not active and (mean, scale, weight, count, fraction, mask_scale) != (0, 1, 0, 0, 0, 1):
            raise ValueError("Observed tactical serving disabled column must remain neutral.")


def _validate(m: ObservedTacticalServingMetadata) -> None:
    if type(m) is not ObservedTacticalServingMetadata or (
        m.serving_version != SERVING_VERSION
        or (m.model_version, m.fit_scope)
        not in (
            (MODEL_VERSION, FULL_FIT_SCOPE),
            (RECIPIENT_MODEL_VERSION, RECIPIENT_FIT_SCOPE),
        )
        or m.feature_version != FEATURE_VERSION
        or m.input_version != INPUT_VERSION
        or m.style_version != STYLE_VERSION
        or m.role_policy != ROLE_POLICY
        or m.context_policy != CONTEXT_POLICY
        or m.recipient_policy != RECIPIENT_POLICY
    ):
        raise ValueError("Observed tactical serving versions or policies differ.")
    sha(m.original_metadata_sha256)
    instant(m.cutoff)
    observations = _count(m.observation_count, 1)
    _release(m.target_season, m.allow_released_2025_26)
    if not 1 <= _count(m.target_gameweek) <= 38:
        raise ValueError("Observed tactical serving target gameweek is invalid.")
    if (
        type(m.allowed_seasons) is not tuple
        or not m.allowed_seasons
        or len(set(m.allowed_seasons)) != len(m.allowed_seasons)
    ):
        raise ValueError("Observed tactical serving season allowlist is invalid.")
    for season in m.allowed_seasons:
        _release(season, m.allow_released_2025_26)
        if season > m.target_season:
            raise ValueError("Observed tactical serving includes a future training season.")
    for head, transform, gamma, events in (
        ("goals", m.goal_transform, m.goal_gamma, m.goal_events),
        ("assists", m.assist_transform, m.assist_gamma, m.assist_events),
    ):
        _transform(transform, head, observations)
        _count(events)
        if type(gamma) is not tuple or len(gamma) != 2 * len(transform.features):
            raise ValueError("Observed tactical serving coefficient dimensions differ.")
        coefficients = tuple(_finite(v) for v in gamma)
        if events == 0 and any(v != 0 for v in coefficients):
            raise ValueError("Observed tactical serving unsupported head has nonzero coefficients.")
        if any(
            not active and (coefficients[2 * i] != 0 or coefficients[2 * i + 1] != 0)
            for i, active in enumerate(transform.active)
        ):
            raise ValueError("Observed tactical serving disabled column has nonzero coefficients.")


@dataclass(frozen=True)
class ObservedTacticalServingModel:
    metadata: ObservedTacticalServingMetadata
    artifact_sha256: str
    _gammas: Mapping[str, Array] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        _validate(self.metadata)
        if hashlib.sha256(_canonical(asdict(self.metadata))).hexdigest() != sha(
            self.artifact_sha256
        ):
            raise ValueError("Observed tactical serving metadata differs from artifact hash.")
        object.__setattr__(
            self,
            "_gammas",
            MappingProxyType(
                {
                    "goals": _immutable(np.asarray(self.metadata.goal_gamma)),
                    "assists": _immutable(np.asarray(self.metadata.assist_gamma)),
                }
            ),
        )

    def predict_recipients(
        self, p: ObservedTacticalProjection, *, control: bool = False
    ) -> ObservedTacticalServingAllocation:
        if type(control) is not bool:
            raise ValueError("Observed tactical control must be Boolean.")
        if p.replay is not None:
            raise ValueError("Observed tactical prediction requires prospective source clocks.")
        validate_projection(p)
        m = self.metadata
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
            gammas=self._gammas,
            control=control,
        )
        return ObservedTacticalServingAllocation(
            home,
            away,
            digest(p),
            tuple(sorted(_projection_sources(p))),
            m.model_version,
            FEATURE_VERSION,
            RECIPIENT_POLICY,
            control,
            ObservedTacticalServingReceipt(
                SERVING_VERSION,
                self.artifact_sha256,
                m.original_metadata_sha256,
                m.cutoff,
                m.target_season,
                m.target_gameweek,
            ),
        )


def export_observed_tactical_serving_model(
    model: ObservedTacticalModel | ObservedTacticalRecipientModel,
) -> bytes:
    """Export exact fitted recipient parameters and the original full metadata digest."""
    if type(model) not in (ObservedTacticalModel, ObservedTacticalRecipientModel):
        raise ValueError("Observed tactical serving export requires its fitted model type.")
    full = model.metadata
    if (
        full.scope
        != "four_observed_channels_nullable_FM_prior_provider_roles_not_complete_tactical_family"
        or full.native_share_policy
        != "supplied_native_recipient_shares_already_include_native_exposure"
    ):
        raise ValueError("Original observed tactical metadata declares another fitted scope.")
    fit_scope = (
        model.metadata.event_scope
        if isinstance(model, ObservedTacticalModel)
        else model.metadata.fit_scope
    )
    metadata = ObservedTacticalServingMetadata(
        SERVING_VERSION,
        model.model_sha256,
        len(full.training_receipts),
        full.cutoff,
        full.target_season,
        full.target_gameweek,
        full.allowed_seasons,
        full.allow_released_2025_26,
        full.goal_transform,
        full.assist_transform,
        full.goal_gamma,
        full.assist_gamma,
        full.goal_events,
        full.assist_events,
        fit_scope=fit_scope,
        model_version=full.model_version,
        feature_version=full.feature_version,
        input_version=full.input_version,
        style_version=full.style_version,
        role_policy=full.role_policy,
        context_policy=full.context_policy,
    )
    _validate(metadata)
    raw = _canonical(asdict(metadata))
    if len(raw) > MAX_ARTIFACT_BYTES:
        raise ValueError("Observed tactical serving artifact exceeds its bounded contract.")
    return raw


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Observed tactical serving JSON repeats a field.")
        result[key] = value
    return result


def read_observed_tactical_serving_model(
    payload: bytes, *, expected_sha256: str
) -> ObservedTacticalServingModel:
    """Restore canonical bytes using external expected SHA; integrity is not authenticity."""
    expected = sha(expected_sha256)
    if type(payload) is not bytes or not 0 < len(payload) <= MAX_ARTIFACT_BYTES:
        raise ValueError("Observed tactical serving requires bounded retained JSON bytes.")
    if hashlib.sha256(payload).hexdigest() != expected:
        raise ValueError("Observed tactical serving artifact differs from expected SHA256.")
    try:
        document = json.loads(payload, object_pairs_hook=_object)
        if type(document) is not dict or set(document) != {
            f.name for f in fields(ObservedTacticalServingMetadata)
        }:
            raise ValueError("Observed tactical serving artifact fields differ.")
        if _canonical(document) != payload:
            raise ValueError("Observed tactical serving artifact must be canonical JSON.")
        transforms = {}
        for name in ("goal_transform", "assist_transform"):
            value = document[name]
            if type(value) is not dict or set(value) != {
                f.name for f in fields(ObservedTacticalTransform)
            }:
                raise ValueError("Observed tactical serving transform fields differ.")
            for key in (
                "features",
                "means",
                "scales",
                "observed_weights",
                "observed_counts",
                "mask_means",
                "mask_scales",
                "active",
            ):
                if type(value[key]) is not list:
                    raise ValueError("Observed tactical serving transform vectors must be arrays.")
                value[key] = tuple(value[key])
            transforms[name] = ObservedTacticalTransform(**value)
        for name in ("allowed_seasons", "goal_gamma", "assist_gamma"):
            if type(document[name]) is not list:
                raise ValueError("Observed tactical serving parameter vectors must be arrays.")
            document[name] = tuple(document[name])
        return ObservedTacticalServingModel(
            ObservedTacticalServingMetadata(**{**document, **transforms}), expected
        )
    except (TypeError, UnicodeError, OverflowError, RecursionError) as error:
        raise ValueError("Malformed observed tactical serving artifact.") from error
