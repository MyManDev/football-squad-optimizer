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
    ClubUnit,
    ProjectedUnitState,
    UnitInputCatalog,
    UnitObservation,
    UnitProjection,
    utc_time,
)

UNIT_MODEL_VERSION = "football_projected_unit_strength_v1"
UNIT_FEATURE_VERSION = "reference_relative_unit_identity_attributes_v1"


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _fingerprint(catalog: UnitInputCatalog) -> str:
    payload = asdict(catalog)
    for key in ("sources", "attributes", "mappings", "player_attributes"):
        payload[key] = sorted(payload[key], key=_canonical)
    return hashlib.sha256(_canonical(payload).encode()).hexdigest()


def _observation_fingerprint(observation: UnitObservation) -> str:
    payload = asdict(observation)
    payload["catalog"] = _fingerprint(observation.catalog)
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

    For segment t and supplied causal baseline b, count y has mean
        (t / 90) * b * exp(beta * (unit - reference)).
    PoissonRegressor receives y / exposure with sample weight exposure. Scaling
    preserves zero, so identical projected and reference units reproduce b exactly.
    The declared reference must be known at the observation's decision cutoff.
    """

    model_version = UNIT_MODEL_VERSION
    feature_version = UNIT_FEATURE_VERSION
    regularization = 0.1

    def __init__(self, observations: tuple[UnitObservation, ...], *, cutoff: datetime):
        utc_time(cutoff, "fitting cutoff")
        observations = tuple(
            sorted(observations, key=lambda x: (x.season, x.fixture_id, x.start_minute, x.own.club))
        )
        if not observations:
            raise ValueError("Unit-strength fitting requires historical exposure observations.")
        contract = _attribute_contract(observations[0].catalog)
        spans: dict[tuple[str, int], list[tuple[float, float]]] = {}
        week_cutoffs: dict[tuple[str, int], datetime] = {}
        fixture_bases: dict[tuple[str, int], tuple[object, ...]] = {}
        for observation in observations:
            if observation.season == "2025-26":
                raise ValueError("Locked 2025-26 outcomes are excluded from unit-strength fitting.")
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
            basis = (
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
            if fixture_bases.setdefault(key, basis) != basis:
                raise ValueError(
                    "One fixture must retain the same predecision reference and baseline."
                )
            segment = observation.start_minute, observation.start_minute + observation.minutes
            for previous in spans.setdefault(key, []):
                if max(segment[0], previous[0]) < min(segment[1], previous[1]):
                    raise ValueError("Duplicated or overlapping fixture exposure observations.")
            spans[key].append(segment)
        self.cutoff = cutoff
        self._observations = observations
        self._attribute_contract = contract
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
        # Venue modifies unit gaps. An uncentered home/intercept term would alter
        # an identical reference and double count baseline venue information.
        self.feature_contract = self._base_columns + tuple(
            f"home_interaction:{column}" for column in self._base_columns
        )
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
                        values[len(self._base_columns) + offset + index] = relative
        indexes = sorted(values)
        data = np.asarray([values[index] for index in indexes], dtype=float)
        if not np.isfinite(data).all():
            raise ValueError("Unit-relative features must remain finite.")
        return csr_matrix(
            (data, (np.zeros(len(indexes), dtype=int), indexes)),
            shape=(1, len(self.feature_contract)),
        )

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
            self._head.predict(self._scaler.transform(vstack((forward, reverse), format="csr"))),
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
                "projection_sha256": hashlib.sha256(
                    _canonical(asdict(projection)).encode()
                ).hexdigest(),
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
                "offset": "minutes / 90 * supplied causal baseline",
                "scaling": "train-only exposure-weighted StandardScaler(with_mean=False)",
                "reference": "complete supplied contemporaneous paired units",
                "projection": "supplied complete joint unit states; probability average of rates",
                "availability": "external once; no availability coefficient or redistribution",
                "minute_state_relation": "native minute law independent of supplied unit state",
                "partial_units": "not supported; this version requires eleven players per club",
                "fitting_semantics": "observational associations, not identified causal effects",
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
