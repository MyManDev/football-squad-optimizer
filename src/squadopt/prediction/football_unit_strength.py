"""Opt-in, baseline-relative projected club-unit model with private inputs.

This observational head learns contribution associations from complete on-field
exposure. Supplied projected states do not establish a joint focal minute law.
"""

from __future__ import annotations

import hashlib
import json
import math
import warnings
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Any

import numpy as np
from scipy.sparse import csr_matrix, vstack
from sklearn.exceptions import ConvergenceWarning  # type: ignore[import-untyped]
from sklearn.linear_model import PoissonRegressor  # type: ignore[import-untyped]
from sklearn.preprocessing import StandardScaler  # type: ignore[import-untyped]

from squadopt.features.football_unit_inputs import (
    POSITIONS,
    UNIT_INPUT_VERSION,
    UNIT_PHYSICAL_CLOCK_VERSION,
    UNIT_PREFIX_CLOCK_VERSION,
    ClubUnit,
    NumericAttributeSpec,
    ProjectedUnitState,
    UnitInputCatalog,
    UnitObservation,
    UnitPhysicalExposureClock,
    UnitProjection,
    utc_time,
    validate_physical_partition,
)

UNIT_MODEL_VERSION = "football_projected_unit_strength_v1"
UNIT_FEATURE_VERSION = "reference_relative_unit_identity_attributes_v1"
UNIT_REPLAY_FIT_VERSION = "football_unit_public_replay_quantized_prefix_fit_v1"
UNIT_LEGACY_MISSINGNESS_POLICY = "per_attribute_v1"
UNIT_SOURCE_MISSINGNESS_POLICY = "source_all_unobserved_residual_v2"
UNIT_SOURCE_MISSINGNESS_MODEL_VERSION = "football_projected_unit_source_missingness_v2"
UNIT_SOURCE_MISSINGNESS_FEATURE_VERSION = "reference_relative_unit_source_missingness_v2"
UNIT_LEGACY_EXPOSURE_POLICY = "reported_minutes_over_90_v1"
UNIT_PHYSICAL_EXPOSURE_POLICY = "physical_seconds_over_forecast_duration_v1"
UNIT_PHYSICAL_MODEL_VERSION = "football_projected_unit_physical_source_missingness_v3"
UNIT_PHYSICAL_FIT_VERSION = "football_unit_public_replay_physical_duration_fit_v1"
UNIT_LEGACY_IDENTITY_POLICY = "exposure_standardized_v1"
UNIT_POOLED_IDENTITY_POLICY = "raw_identity_pooled_no_home_v1"
UNIT_POOLED_MODEL_VERSION = "football_projected_unit_pooled_identity_v4"
UNIT_POOLED_FEATURE_VERSION = "reference_relative_source_missingness_raw_identity_v3"
UNIT_POOLED_SCALING = "raw identity scale=1; train-only exposure-weighted shared SD; no centering"
UNIT_POOLED_OBJECTIVE = (
    "sum(offset * exp(eta) - goals * eta) / sum(offset) "
    "+ alpha / 2 * squared coefficient norm; no intercept"
)
UNIT_POOLED_PRIOR = (
    "zero-centered raw identity Gaussian MAP precision alpha * sum(offset); "
    "shared coefficients retain their standardized-coordinate penalty; no posterior uncertainty"
)
UNIT_PHYSICAL_OFFSET = (
    "physical seconds / (causal forecast duration minutes * 60) "
    "* supplied whole-fixture native mean"
)
UNIT_PHYSICAL_SELECTION = "source-validated complete observed physical matches"
UNIT_PHYSICAL_SEMANTICS = (
    "exact integer physical seconds; actual duration only establishes the observed partition"
)
UNIT_PHYSICAL_PROJECTION = (
    "reference-relative associations modify supplied whole-fixture native means"
)
UNIT_ALL_UNOBSERVED_SEMANTICS = "all declared attributes of this source unobserved; count / 11"
UNIT_RESIDUAL_MISSINGNESS_SEMANTICS = (
    "missing trait among players with at least one observed declared attribute of this source; "
    "count / 11"
)


def source_attribute_groups(
    attributes: tuple[NumericAttributeSpec, ...],
) -> tuple[tuple[str, tuple[NumericAttributeSpec, ...]], ...]:
    """Group only attributes of the same logical source identity."""
    return tuple(
        (
            source_id,
            tuple(
                sorted(
                    (spec for spec in attributes if spec.source_id == source_id),
                    key=lambda spec: spec.name,
                )
            ),
        )
        for source_id in sorted({spec.source_id for spec in attributes})
    )


def source_missingness_base_columns(
    vocabulary: tuple[int, ...], attributes: tuple[NumericAttributeSpec, ...]
) -> tuple[str, ...]:
    return tuple(
        column
        for side in ("own", "opponent")
        for column in (
            *(f"{side}_player_{identity}" for identity in vocabulary),
            *(
                f"{side}_{position}_{label}"
                for position in POSITIONS
                for label in (
                    "count",
                    *(
                        label
                        for source_id, specs in source_attribute_groups(attributes)
                        for label in (
                            f"{source_id}:all_attributes_unobserved",
                            *(
                                f"{source_id}:{spec.name}_{suffix}"
                                for spec in specs
                                for suffix in ("value", "residual_missing")
                            ),
                        )
                    ),
                )
            ),
        )
    )


def pooled_identity_columns(vocabulary: tuple[int, ...]) -> tuple[str, ...]:
    return tuple(
        f"{side}_player_{identity}" for side in ("own", "opponent") for identity in vocabulary
    )


def pooled_feature_columns(
    vocabulary: tuple[int, ...], attributes: tuple[NumericAttributeSpec, ...]
) -> tuple[str, ...]:
    base = source_missingness_base_columns(vocabulary, attributes)
    identities = set(pooled_identity_columns(vocabulary))
    return base + tuple(f"home_interaction:{column}" for column in base if column not in identities)


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _fingerprint(catalog: UnitInputCatalog) -> str:
    payload = asdict(catalog)
    if catalog.replay is None:
        payload.pop("replay")
    for key in ("sources", "attributes", "mappings", "player_attributes"):
        payload[key] = sorted(payload[key], key=_canonical)
    return hashlib.sha256(_canonical(payload).encode()).hexdigest()


def _observation_fingerprint(observation: UnitObservation) -> str:
    payload = asdict(observation)
    if observation.exposure_clock is None:
        payload.pop("exposure_clock")
    payload["catalog"] = _fingerprint(observation.catalog)
    return hashlib.sha256(_canonical(payload).encode()).hexdigest()


def _projection_fingerprint(projection: UnitProjection) -> str:
    payload = asdict(projection)
    if projection.catalog.replay is None:
        payload["catalog"].pop("replay")
    return hashlib.sha256(_canonical(payload).encode()).hexdigest()


def _attribute_contract(catalog: UnitInputCatalog) -> tuple[tuple[Any, ...], ...]:
    sources = {x.source_id: x for x in catalog.sources}
    return tuple(
        sorted(
            (
                spec.source_id,
                spec.name,
                spec.minimum,
                spec.maximum,
                spec.unit,
                spec.definition,
                sources[spec.source_id].provider,
                sources[spec.source_id].kind,
            )
            for spec in catalog.attributes
        )
    )


@dataclass(frozen=True)
class UnitStateRate:
    probability: float
    own_goal_rate: float
    opponent_goal_rate: float
    own: ClubUnit
    opponent: ClubUnit


@dataclass(frozen=True)
class UnitStrengthResult:
    fixture_id: int
    season: str
    gameweek: int
    decision_cutoff: datetime
    kickoff: datetime
    home: bool
    club: int
    opponent: int
    own_goal_rate: float
    opponent_goal_rate: float
    causal_baseline_own_goal_rate: float
    causal_baseline_opponent_goal_rate: float
    state_rates: tuple[UnitStateRate, ...]
    model_version: str
    feature_contract: tuple[str, ...]
    metadata: Mapping[str, object]

    @property
    def own_replacement_gap(self) -> float:
        return self.own_goal_rate - self.causal_baseline_own_goal_rate

    @property
    def opponent_replacement_gap(self) -> float:
        return self.opponent_goal_rate - self.causal_baseline_opponent_goal_rate


class FootballUnitStrengthModel:
    """A fixed regularized Poisson offset head, independent of accepted forecasts.

    The legacy segment offset is (minutes / 90) * supplied baseline.
    Explicit physical exposure uses seconds / forecast duration seconds instead.
    Count y has mean offset * exp(beta * (unit - reference)).
    PoissonRegressor receives y / exposure with sample weight exposure. Scaling
    preserves zero, so identical projected and reference units reproduce b exactly.
    The declared reference must be known at the observation's decision cutoff.
    """

    model_version = UNIT_MODEL_VERSION
    feature_version = UNIT_FEATURE_VERSION
    regularization = 0.1

    def __init__(
        self,
        observations: tuple[UnitObservation, ...],
        *,
        cutoff: datetime,
        allow_released_2025_26: bool = False,
        missingness_policy: str = UNIT_LEGACY_MISSINGNESS_POLICY,
        exposure_policy: str = UNIT_LEGACY_EXPOSURE_POLICY,
        identity_policy: str = UNIT_LEGACY_IDENTITY_POLICY,
    ):
        utc_time(cutoff, "fitting cutoff")
        if type(allow_released_2025_26) is not bool:
            raise ValueError("Released season use must be an explicit boolean.")
        if type(missingness_policy) is not str or missingness_policy not in (
            UNIT_LEGACY_MISSINGNESS_POLICY,
            UNIT_SOURCE_MISSINGNESS_POLICY,
        ):
            raise ValueError("Unit missingness requires an explicitly supported policy.")
        self.missingness_policy = missingness_policy
        if missingness_policy == UNIT_SOURCE_MISSINGNESS_POLICY:
            self.model_version = UNIT_SOURCE_MISSINGNESS_MODEL_VERSION
            self.feature_version = UNIT_SOURCE_MISSINGNESS_FEATURE_VERSION
        if type(exposure_policy) is not str or exposure_policy not in (
            UNIT_LEGACY_EXPOSURE_POLICY,
            UNIT_PHYSICAL_EXPOSURE_POLICY,
        ):
            raise ValueError("Unit exposure requires an explicitly supported fitting policy.")
        physical = exposure_policy == UNIT_PHYSICAL_EXPOSURE_POLICY
        if type(identity_policy) is not str or identity_policy not in (
            UNIT_LEGACY_IDENTITY_POLICY,
            UNIT_POOLED_IDENTITY_POLICY,
        ):
            raise ValueError("Unit identity requires an explicitly supported pooling policy.")
        pooled = identity_policy == UNIT_POOLED_IDENTITY_POLICY
        if pooled and (not physical or missingness_policy != UNIT_SOURCE_MISSINGNESS_POLICY):
            raise ValueError(
                "Pooled identity requires physical exposure and source missingness v2."
            )
        if physical:
            if missingness_policy != UNIT_SOURCE_MISSINGNESS_POLICY:
                raise ValueError(
                    "Physical exposure requires the source missingness v2 feature policy."
                )
            self.exposure_policy = exposure_policy
            self.model_version = UNIT_PHYSICAL_MODEL_VERSION
        if pooled:
            self.identity_policy = identity_policy
            self.model_version = UNIT_POOLED_MODEL_VERSION
            self.feature_version = UNIT_POOLED_FEATURE_VERSION
        observations = tuple(
            sorted(observations, key=lambda x: (x.season, x.fixture_id, x.start_minute, x.own.club))
        )
        if not observations:
            raise ValueError("Unit-strength fitting requires historical exposure observations.")
        if any(
            isinstance(x.exposure_clock, UnitPhysicalExposureClock) != physical
            for x in observations
        ):
            raise ValueError(
                "Physical, reported-prefix and legacy exposure populations "
                "require separate explicit fits."
            )
        replayed = tuple(x.catalog.replay is not None for x in observations)
        if any(replayed) and not all(replayed):
            raise ValueError(
                "Reported prefix replay and legacy exposure need separate fit contracts."
            )
        exposure_ids = [
            (x.exposure_clock.source_sha256, x.exposure_clock.interval_id)
            for x in observations
            if x.exposure_clock is not None
        ]
        if len(set(exposure_ids)) != len(exposure_ids):
            raise ValueError("Reported source interval identities must not be reused.")
        contract = _attribute_contract(observations[0].catalog)
        spans: dict[tuple[str, int], list[tuple[float, float]]] = {}
        week_cutoffs: dict[tuple[str, int], datetime] = {}
        fixture_bases: dict[tuple[str, int], tuple[object, ...]] = {}
        physical_spans: dict[tuple[str, int], list[tuple[int, int]]] = {}
        physical_totals: dict[tuple[str, int], int] = {}
        for observation in observations:
            if observation.season == "2025-26" and not allow_released_2025_26:
                raise ValueError("Locked 2025-26 outcomes are excluded from unit-strength fitting.")
            if (
                observation.catalog.replay is not None
                and observation.catalog.replay.generated_at >= cutoff
            ):
                raise ValueError(
                    "Reconstructed unit features must exist before the fitting cutoff."
                )
            if observation.outcome_available_at >= cutoff:
                raise ValueError("Historical outcome was unavailable at the fitting cutoff.")
            if _attribute_contract(observation.catalog) != contract:
                raise ValueError(
                    "Training attribute definitions and logical source families must agree."
                )
            week_key = observation.season, observation.gameweek
            if week_cutoffs.setdefault(week_key, observation.decision_cutoff) != (
                observation.decision_cutoff
            ):
                raise ValueError("Every fixture in one gameweek must share its decision cutoff.")
            key = observation.season, observation.fixture_id
            basis: tuple[object, ...] = (
                observation.gameweek,
                observation.decision_cutoff,
                observation.kickoff,
                observation.home,
                observation.reference_own,
                observation.reference_opponent,
                observation.causal_baseline_own_goal_rate,
                observation.causal_baseline_opponent_goal_rate,
                _fingerprint(observation.catalog),
            )
            if isinstance(observation.exposure_clock, UnitPhysicalExposureClock):
                clock = observation.exposure_clock
                basis += (clock.fixture_basis(),)
                physical_spans.setdefault(key, []).append((clock.start_seconds, clock.end_seconds))
                physical_totals[key] = clock.actual_duration_seconds
            if fixture_bases.setdefault(key, basis) != basis:
                raise ValueError(
                    "One fixture must retain the same predecision reference and baseline."
                )
            segment = (
                (observation.exposure_clock.start_seconds, observation.exposure_clock.end_seconds)
                if isinstance(observation.exposure_clock, UnitPhysicalExposureClock)
                else (observation.start_minute, observation.start_minute + observation.minutes)
            )
            for previous in spans.setdefault(key, []):
                if max(segment[0], previous[0]) < min(segment[1], previous[1]):
                    raise ValueError("Duplicated or overlapping fixture exposure observations.")
            spans[key].append(segment)
        for key, segments in physical_spans.items():
            validate_physical_partition(segments, physical_totals[key])
        self.cutoff = cutoff
        self._observations = observations
        self._attribute_contract = contract
        self._replay_metadata: dict[str, object] = {}
        if allow_released_2025_26 or any(replayed):
            self._replay_metadata = {
                "fit_contract": (
                    UNIT_REPLAY_FIT_VERSION
                    if any(replayed)
                    else "football_unit_explicit_release_fit_v1"
                ),
                "allow_released_2025_26": allow_released_2025_26,
            }
        if any(replayed):
            self._replay_metadata.update(
                {
                    "training_exposure_clock": UNIT_PREFIX_CLOCK_VERSION,
                    "training_selection": "source-validated first-half reported minute bins 0..40",
                    "training_replay_receipts": tuple(
                        _canonical(
                            {
                                "replay": asdict(x.catalog.replay),
                                "decision_cutoff": x.decision_cutoff,
                                "baseline_source_id": x.catalog.baseline_source_id,
                                "reference_source_id": x.catalog.reference_source_id,
                            }
                        )
                        for x in observations
                        if x.catalog.replay is not None
                    ),
                    "training_exposure_receipts": tuple(
                        _canonical(
                            {
                                "clock": asdict(x.exposure_clock),
                                "season": x.season,
                                "gameweek": x.gameweek,
                                "fixture_id": x.fixture_id,
                                "start_minute": x.start_minute,
                                "minutes": x.minutes,
                                "kickoff": x.kickoff,
                                "outcome_source": asdict(x.outcome_source),
                                "outcome_available_at": x.outcome_available_at,
                            }
                        )
                        for x in observations
                        if x.exposure_clock is not None
                    ),
                    "exposure_semantics": (
                        "quantized observed intervals, not exact physical seconds"
                    ),
                    "projection_extrapolation": (
                        "whole-match rates extrapolate associations fitted on "
                        "selected first-half prefixes"
                    ),
                    "fm_game_vintage": "unknown",
                    "fm_effective_semantics": (
                        "published frozen feature eligibility, not game/save date"
                    ),
                }
            )
        if physical:
            self._replay_metadata.update(
                {
                    "fit_contract": UNIT_PHYSICAL_FIT_VERSION,
                    "training_exposure_clock": UNIT_PHYSICAL_CLOCK_VERSION,
                    "training_selection": UNIT_PHYSICAL_SELECTION,
                    "exposure_semantics": UNIT_PHYSICAL_SEMANTICS,
                    "projection_extrapolation": UNIT_PHYSICAL_PROJECTION,
                    "exposure_policy": UNIT_PHYSICAL_EXPOSURE_POLICY,
                }
            )
        self.attributes = tuple(
            sorted(observations[0].catalog.attributes, key=lambda x: (x.source_id, x.name))
        )
        self.player_vocabulary = tuple(
            sorted(
                {
                    player.player_id
                    for observation in observations
                    for unit in (
                        observation.own,
                        observation.opponent,
                        observation.reference_own,
                        observation.reference_opponent,
                    )
                    for player in unit.players
                }
            )
        )
        self._identity_indexes = {
            identity: index for index, identity in enumerate(self.player_vocabulary)
        }
        self._unit_width = len(self.player_vocabulary) + len(POSITIONS) * (
            1 + 2 * len(self.attributes)
        )
        self._base_columns = tuple(
            column
            for side in ("own", "opponent")
            for column in (
                *(f"{side}_player_{identity}" for identity in self.player_vocabulary),
                *(
                    f"{side}_{position}_{label}"
                    for position in POSITIONS
                    for label in (
                        "count",
                        *(
                            f"{spec.source_id}:{spec.name}_{suffix}"
                            for spec in self.attributes
                            for suffix in ("value", "missing")
                        ),
                    )
                ),
            )
        )
        if missingness_policy == UNIT_SOURCE_MISSINGNESS_POLICY:
            self._source_attribute_groups = source_attribute_groups(self.attributes)
            self._base_columns = source_missingness_base_columns(
                self.player_vocabulary, self.attributes
            )
            self._unit_width = len(self._base_columns) // 2
        # Venue modifies unit gaps. An uncentered home/intercept term would alter
        # an identical reference and double count baseline venue information.
        self.feature_contract = self._base_columns + tuple(
            f"home_interaction:{column}" for column in self._base_columns
        )
        if pooled:
            identities = set(pooled_identity_columns(self.player_vocabulary))
            self.feature_contract = pooled_feature_columns(self.player_vocabulary, self.attributes)
            self._pooled_identity_indexes = tuple(
                index for index, column in enumerate(self._base_columns) if column in identities
            )
            self._pooled_home_indexes = {
                index: len(self._base_columns) + home_index
                for home_index, index in enumerate(
                    index
                    for index, column in enumerate(self._base_columns)
                    if column not in identities
                )
            }
        rows: list[Any] = []
        targets: list[float] = []
        weights: list[float] = []
        for observation in observations:
            for reverse in (False, True):
                own, opponent, reference_own, reference_opponent = (
                    (
                        observation.opponent,
                        observation.own,
                        observation.reference_opponent,
                        observation.reference_own,
                    )
                    if reverse
                    else (
                        observation.own,
                        observation.opponent,
                        observation.reference_own,
                        observation.reference_opponent,
                    )
                )
                rows.append(
                    self._relative(
                        observation.catalog,
                        own,
                        opponent,
                        reference_own,
                        reference_opponent,
                        not observation.home if reverse else observation.home,
                    )
                )
                baseline = (
                    observation.causal_baseline_opponent_goal_rate
                    if reverse
                    else observation.causal_baseline_own_goal_rate
                )
                if physical:
                    physical_clock = observation.exposure_clock
                    assert isinstance(physical_clock, UnitPhysicalExposureClock)
                    exposure = (
                        (physical_clock.end_seconds - physical_clock.start_seconds)
                        / (physical_clock.forecast_duration_minutes * 60)
                        * baseline
                    )
                else:
                    exposure = observation.minutes / 90 * baseline
                if not math.isfinite(exposure) or exposure <= 0:
                    raise ValueError("Baseline-weighted exposure must remain finite and positive.")
                try:
                    target = (
                        observation.opponent_goals if reverse else observation.own_goals
                    ) / exposure
                except OverflowError as error:
                    raise ValueError(
                        "Observed goal count exceeds the supported numerical range."
                    ) from error
                targets.append(target)
                weights.append(exposure)
        x = vstack(rows, format="csr")
        self.training_matrix_shape = (int(x.shape[0]), int(x.shape[1]))
        self.training_matrix_nnz = int(x.nnz)
        self.training_matrix_storage_bytes = int(x.data.nbytes + x.indices.nbytes + x.indptr.nbytes)
        if not all(
            np.isfinite(a).all() for a in (x.data, np.asarray(targets), np.asarray(weights))
        ):
            raise ValueError("Fitting matrix, targets and exposures must remain finite.")
        self._scaler: Any = StandardScaler(with_mean=False)
        with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
            standardized = self._scaler.fit_transform(x, sample_weight=np.asarray(weights))
        if pooled:
            # Keep the observed training statistics distinct from applied prior scales.
            self._feature_scales = np.asarray(self._scaler.scale_, dtype=float).copy()
            self._feature_scales[list(self._pooled_identity_indexes)] = 1.0
            self._training_offset_sum = float(np.asarray(weights).sum())
            if not math.isfinite(self._training_offset_sum) or self._training_offset_sum <= 0:
                raise ValueError("Pooled identity requires finite positive total offset exposure.")
            standardized = self._transform(x)
        if not all(
            np.isfinite(a).all()
            for a in (standardized.data, self._scaler.var_, self._scaler.scale_)
        ):
            raise ValueError("Train-only standardized features must remain finite.")
        self._head: Any = PoissonRegressor(
            alpha=self.regularization, fit_intercept=False, max_iter=1000, tol=1e-12
        )
        with warnings.catch_warnings():
            warnings.simplefilter("error", ConvergenceWarning)
            try:
                self._head.fit(standardized, np.asarray(targets), sample_weight=np.asarray(weights))
            except ConvergenceWarning as error:
                raise ValueError("Unit-strength Poisson fit did not converge.") from error
        if not np.isfinite(self._head.coef_).all():
            raise ValueError("Unit-strength fit produced nonfinite coefficients.")
        self.training_rows = len(rows)
        self._training_receipts = tuple(_fingerprint(x.catalog) for x in observations)
        self._observation_receipts = tuple(_observation_fingerprint(x) for x in observations)
        self._source_receipts = tuple(
            tuple(
                (
                    s.source_id,
                    s.provider,
                    s.kind,
                    s.version,
                    s.sha256,
                    s.published_at.isoformat(),
                    s.captured_at.isoformat(),
                    s.effective_at.isoformat(),
                    s.valid_until.isoformat(),
                    s.rights_reference,
                )
                for s in sorted(x.catalog.sources, key=lambda s: s.source_id)
            )
            for x in observations
        )

    def _unit_values(self, catalog: UnitInputCatalog, unit: ClubUnit) -> dict[int, float]:
        if getattr(self, "missingness_policy", UNIT_LEGACY_MISSINGNESS_POLICY) == (
            UNIT_SOURCE_MISSINGNESS_POLICY
        ):
            return self._source_unit_values(catalog, unit)
        values = {
            self._identity_indexes[x.player_id]: 1.0
            for x in unit.players
            if x.player_id in self._identity_indexes
        }
        offset = len(self.player_vocabulary)
        for position in POSITIONS:
            players = [x.player_id for x in unit.players if x.position == position]
            if players:
                values[offset] = len(players) / 11
            offset += 1
            for spec in self.attributes:
                numeric = [catalog.value(identity, spec) for identity in players]
                # Missing values have a separate field. No attribute is assigned
                # a manual contribution multiplier or an inferred numerical rating.
                measured = math.fsum(x / 11 for x in numeric if x is not None)
                missing = sum(x is None for x in numeric) / 11
                if measured:
                    values[offset] = measured
                if missing:
                    values[offset + 1] = missing
                offset += 2
        return values

    def _source_unit_values(self, catalog: UnitInputCatalog, unit: ClubUnit) -> dict[int, float]:
        values = {
            self._identity_indexes[x.player_id]: 1.0
            for x in unit.players
            if x.player_id in self._identity_indexes
        }
        offset = len(self.player_vocabulary)
        for position in POSITIONS:
            players = [x.player_id for x in unit.players if x.position == position]
            if players:
                values[offset] = len(players) / 11
            offset += 1
            for _, specs in self._source_attribute_groups:
                profiles = [
                    tuple(catalog.value(identity, spec) for spec in specs) for identity in players
                ]
                observed = [any(value is not None for value in row) for row in profiles]
                all_unobserved = sum(not present for present in observed) / 11
                if all_unobserved:
                    values[offset] = all_unobserved
                offset += 1
                for index, _ in enumerate(specs):
                    numeric = [row[index] for row in profiles]
                    measured = math.fsum(value / 11 for value in numeric if value is not None)
                    residual_missing = (
                        sum(
                            present and row[index] is None
                            for present, row in zip(observed, profiles, strict=True)
                        )
                        / 11
                    )
                    if measured:
                        values[offset] = measured
                    if residual_missing:
                        values[offset + 1] = residual_missing
                    offset += 2
        return values

    def _unit(self, catalog: UnitInputCatalog, unit: ClubUnit) -> list[float]:
        """Dense single-unit inspection only; fitting and prediction stay sparse."""
        values = self._unit_values(catalog, unit)
        return [values.get(index, 0.0) for index in range(self._unit_width)]

    def _relative(
        self,
        catalog: UnitInputCatalog,
        own: ClubUnit,
        opponent: ClubUnit,
        reference_own: ClubUnit,
        reference_opponent: ClubUnit,
        home: bool,
    ) -> Any:
        values: dict[int, float] = {}
        for offset, actual, reference in (
            (0, own, reference_own),
            (self._unit_width, opponent, reference_opponent),
        ):
            actual_values = self._unit_values(catalog, actual)
            reference_values = self._unit_values(catalog, reference)
            for index in actual_values.keys() | reference_values.keys():
                relative = actual_values.get(index, 0.0) - reference_values.get(index, 0.0)
                if relative:
                    values[offset + index] = relative
                    if home:
                        if getattr(self, "identity_policy", UNIT_LEGACY_IDENTITY_POLICY) == (
                            UNIT_POOLED_IDENTITY_POLICY
                        ):
                            home_index = self._pooled_home_indexes.get(offset + index)
                            if home_index is not None:
                                values[home_index] = relative
                        else:
                            values[len(self._base_columns) + offset + index] = relative
        indexes = sorted(values)
        data = np.asarray([values[index] for index in indexes], dtype=float)
        if not np.isfinite(data).all():
            raise ValueError("Unit-relative features must remain finite.")
        return csr_matrix(
            (data, (np.zeros(len(indexes), dtype=int), indexes)),
            shape=(1, len(self.feature_contract)),
        )

    def _transform(self, matrix: Any) -> Any:
        if (
            getattr(self, "identity_policy", UNIT_LEGACY_IDENTITY_POLICY)
            == UNIT_POOLED_IDENTITY_POLICY
        ):
            return matrix.multiply(1 / self._feature_scales).tocsr()
        return self._scaler.transform(matrix)

    def _state_rates(self, projection: UnitProjection, state: ProjectedUnitState) -> UnitStateRate:
        forward = self._relative(
            projection.catalog,
            state.own,
            state.opponent,
            projection.reference_own,
            projection.reference_opponent,
            projection.home,
        )
        reverse = self._relative(
            projection.catalog,
            state.opponent,
            state.own,
            projection.reference_opponent,
            projection.reference_own,
            not projection.home,
        )
        ratios = np.asarray(
            self._head.predict(self._transform(vstack((forward, reverse), format="csr"))),
            dtype=float,
        )
        rates = ratios * np.asarray(
            [
                projection.causal_baseline_own_goal_rate,
                projection.causal_baseline_opponent_goal_rate,
            ]
        )
        if not np.isfinite(rates).all() or np.any(rates <= 0):
            raise ValueError("Projected unit produced unsupported nonfinite or zero goal rates.")
        return UnitStateRate(
            state.probability, float(rates[0]), float(rates[1]), state.own, state.opponent
        )

    def predict(self, projection: UnitProjection) -> UnitStrengthResult:
        if self.cutoff > projection.decision_cutoff:
            raise ValueError("Fitted model was unavailable at the projection decision cutoff.")
        for observation in self._observations:
            if observation.season > projection.season or (
                observation.season == projection.season
                and observation.gameweek >= projection.gameweek
            ):
                raise ValueError("Prediction cannot train on the same or a future gameweek.")
        if _attribute_contract(projection.catalog) != self._attribute_contract:
            raise ValueError(
                "Prediction attribute definitions and logical source families differ from fit."
            )
        states = tuple(
            sorted(
                projection.states,
                key=lambda x: (
                    tuple((p.player_id, p.position) for p in x.own.players),
                    tuple((p.player_id, p.position) for p in x.opponent.players),
                ),
            )
        )
        state_rates = tuple(self._state_rates(projection, state) for state in states)
        own_rate = math.fsum(x.probability * x.own_goal_rate for x in state_rates)
        opponent_rate = math.fsum(x.probability * x.opponent_goal_rate for x in state_rates)
        missingness_metadata: dict[str, object] = {}
        if getattr(self, "missingness_policy", UNIT_LEGACY_MISSINGNESS_POLICY) == (
            UNIT_SOURCE_MISSINGNESS_POLICY
        ):
            missingness_metadata = {
                "missingness_policy": UNIT_SOURCE_MISSINGNESS_POLICY,
                "source_attribute_groups": tuple(
                    (source_id, tuple(spec.name for spec in specs))
                    for source_id, specs in self._source_attribute_groups
                ),
                "all_unobserved_semantics": UNIT_ALL_UNOBSERVED_SEMANTICS,
                "residual_missingness_semantics": UNIT_RESIDUAL_MISSINGNESS_SEMANTICS,
            }
        identity_metadata: dict[str, object] = {}
        if (
            getattr(self, "identity_policy", UNIT_LEGACY_IDENTITY_POLICY)
            == UNIT_POOLED_IDENTITY_POLICY
        ):
            identity_metadata = {
                "identity_policy": UNIT_POOLED_IDENTITY_POLICY,
                "identity_feature_columns": pooled_identity_columns(self.player_vocabulary),
                "player_home_interactions": False,
                "scaling": UNIT_POOLED_SCALING,
                "feature_scales": tuple(float(value) for value in self._feature_scales),
                "training_scaler_scales": tuple(float(value) for value in self._scaler.scale_),
                "regularization_objective": UNIT_POOLED_OBJECTIVE,
                "identity_prior": UNIT_POOLED_PRIOR,
                "training_offset_sum": self._training_offset_sum,
                "raw_identity_count_prior_precision": self.regularization
                * self._training_offset_sum,
            }
        metadata: Mapping[str, object] = MappingProxyType(
            {
                "input_version": UNIT_INPUT_VERSION,
                "feature_version": self.feature_version,
                "feature_columns": self.feature_contract,
                "player_vocabulary": self.player_vocabulary,
                "attribute_contract": self._attribute_contract,
                "training_cutoff": self.cutoff.isoformat(),
                "training_rows": self.training_rows,
                "training_catalog_sha256": self._training_receipts,
                "training_observation_sha256": self._observation_receipts,
                "training_source_receipts": self._source_receipts,
                "projection_catalog_sha256": _fingerprint(projection.catalog),
                "projection_sha256": _projection_fingerprint(projection),
                "reference_unit_identity": tuple(
                    (u.club, tuple((p.player_id, p.position) for p in u.players))
                    for u in (projection.reference_own, projection.reference_opponent)
                ),
                "baseline_source_id": projection.catalog.baseline_source_id,
                "reference_source_id": projection.catalog.reference_source_id,
                "projection_source_id": projection.catalog.projection_source_id,
                "projection_source_receipts": tuple(
                    (
                        s.source_id,
                        s.provider,
                        s.kind,
                        s.version,
                        s.sha256,
                        s.published_at.isoformat(),
                        s.captured_at.isoformat(),
                        s.effective_at.isoformat(),
                        s.valid_until.isoformat(),
                        s.rights_reference,
                    )
                    for s in sorted(projection.catalog.sources, key=lambda s: s.source_id)
                ),
                "regularization": self.regularization,
                "offset": UNIT_PHYSICAL_OFFSET
                if getattr(self, "exposure_policy", UNIT_LEGACY_EXPOSURE_POLICY)
                == UNIT_PHYSICAL_EXPOSURE_POLICY
                else "minutes / 90 * supplied causal baseline",
                "scaling": "train-only exposure-weighted StandardScaler(with_mean=False)",
                "reference": "complete supplied contemporaneous paired units",
                "projection": "supplied complete joint unit states; probability average of rates",
                "availability": "external once; no availability coefficient or redistribution",
                "minute_state_relation": "native minute law independent of supplied unit state",
                "partial_units": "not supported; this version requires eleven players per club",
                "fitting_semantics": "observational associations, not identified causal effects",
                **self._replay_metadata,
                **missingness_metadata,
                **identity_metadata,
            }
        )
        return UnitStrengthResult(
            fixture_id=projection.fixture_id,
            season=projection.season,
            gameweek=projection.gameweek,
            decision_cutoff=projection.decision_cutoff,
            kickoff=projection.kickoff,
            home=projection.home,
            club=projection.reference_own.club,
            opponent=projection.reference_opponent.club,
            own_goal_rate=own_rate,
            opponent_goal_rate=opponent_rate,
            causal_baseline_own_goal_rate=projection.causal_baseline_own_goal_rate,
            causal_baseline_opponent_goal_rate=projection.causal_baseline_opponent_goal_rate,
            state_rates=state_rates,
            model_version=self.model_version,
            feature_contract=self.feature_contract,
            metadata=metadata,
        )
