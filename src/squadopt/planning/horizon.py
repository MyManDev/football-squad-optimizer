"""Consumer-side contract for multi-gameweek projection handoffs.

The transfer planner already consumes a validated :class:`PlanningHorizon`, but the
production prediction pipeline projects one decision point at a time. This module
fixes, from the planner's side, what a multi-gameweek projection handoff must carry
before real multi-week planning can run: per-gameweek expected points with explicit
blank/double-gameweek representation, a stable player universe, and versioned
provenance tied to one source snapshot.

The builder that produces a :class:`ProjectionHorizon` from a decision snapshot is
owned by the data/prediction side (:class:`ProjectionHorizonBuilder`). This module
only defines what the planner will accept, so both sides implement against the same
contract instead of a prose description.
"""

import hashlib
import json
import math
from dataclasses import dataclass, field
from numbers import Integral, Real
from typing import Final, Protocol

import pandas as pd

from squadopt.optimization.config import POSITIONS
from squadopt.planning.models import (
    PlanningHorizon,
    TransferPlanningValidationError,
)

PROJECTION_HORIZON_CONTRACT_VERSION: Final = "projection_horizon_v1"
PROJECTION_HORIZON_COLUMNS: Final = (
    "gameweek",
    "player_id",
    "name",
    "team_id",
    "position",
    "price_tenths",
    "expected_points",
    "fixture_count",
    "home_fixture_count",
)

_PROVENANCE_FIELDS: Final = (
    "season",
    "source_snapshot_id",
    "model_name",
    "model_version",
    "feature_contract_version",
    "post_processing_contract_version",
)


def _identifier_key(value: object) -> int | str:
    if isinstance(value, Integral) and not isinstance(value, bool):
        return int(value)
    return str(value)


def _typed_identifier(value: object) -> dict[str, object]:
    if isinstance(value, Integral) and not isinstance(value, bool):
        return {"kind": "integer", "value": int(value)}
    return {"kind": "string", "value": str(value)}


@dataclass(frozen=True, slots=True)
class ProjectionHorizon:
    """Per-gameweek projections for one decision point, from one source snapshot.

    Blank and double gameweeks are represented, never inferred: every player carries a
    row for every target gameweek, `fixture_count` says how many fixtures that row
    covers, and a blank row (zero fixtures) must project exactly zero points. All
    rows must come from the same captured snapshot; mixing snapshots would blend two
    different information states into one decision.
    """

    table: pd.DataFrame
    season: str
    source_snapshot_id: str
    model_name: str
    model_version: str
    feature_contract_version: str
    post_processing_contract_version: str
    contract_version: str = PROJECTION_HORIZON_CONTRACT_VERSION
    horizon_fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        if self.contract_version != PROJECTION_HORIZON_CONTRACT_VERSION:
            raise TransferPlanningValidationError(
                "Unsupported projection horizon contract_version."
            )
        for name in _PROVENANCE_FIELDS:
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise TransferPlanningValidationError(f"{name} must be non-empty text.")
            object.__setattr__(self, name, value.strip())
        if not isinstance(self.table, pd.DataFrame):
            raise TransferPlanningValidationError("table must be a pandas DataFrame.")
        if self.table.columns.duplicated().any():
            raise TransferPlanningValidationError("Projection horizon columns must be unique.")
        missing = [column for column in PROJECTION_HORIZON_COLUMNS if column not in self.table]
        if missing:
            raise TransferPlanningValidationError(
                f"Projection horizon is missing required columns: {missing!r}."
            )
        table = self.table.loc[:, list(PROJECTION_HORIZON_COLUMNS)].copy(deep=True)
        if table.empty:
            raise TransferPlanningValidationError(
                "Projection horizon must contain at least one row."
            )
        if bool(table.isna().any().any()):
            raise TransferPlanningValidationError(
                "Projection horizon required columns may not be missing."
            )

        gameweeks: list[int] = []
        for value in table["gameweek"].tolist():
            if isinstance(value, bool) or not isinstance(value, Integral) or int(value) < 1:
                raise TransferPlanningValidationError("gameweek must contain positive integers.")
            gameweeks.append(int(value))
        table.loc[:, "gameweek"] = gameweeks
        ordered = tuple(sorted(set(gameweeks)))
        if ordered != tuple(range(ordered[0], ordered[-1] + 1)):
            raise TransferPlanningValidationError(
                "Projection gameweeks must be consecutive; a blank gameweek is a row "
                "with zero fixtures, not a missing gameweek."
            )
        if bool(table.duplicated(subset=["gameweek", "player_id"]).any()):
            raise TransferPlanningValidationError("Each (gameweek, player_id) row must be unique.")

        first_ids = set(table.loc[table["gameweek"] == ordered[0], "player_id"])
        for gameweek in ordered[1:]:
            observed = set(table.loc[table["gameweek"] == gameweek, "player_id"])
            if observed != first_ids:
                missing_ids = sorted(first_ids - observed, key=str)
                extra_ids = sorted(observed - first_ids, key=str)
                raise TransferPlanningValidationError(
                    "Every projected gameweek must contain the same player universe; "
                    f"gameweek={gameweek}, missing={missing_ids[:10]!r}, "
                    f"extra={extra_ids[:10]!r}."
                )

        if any(not isinstance(value, str) or not value.strip() for value in table["name"]):
            raise TransferPlanningValidationError("name must contain non-empty strings.")
        invalid_positions = sorted(set(table["position"]) - set(POSITIONS), key=str)
        if invalid_positions:
            raise TransferPlanningValidationError(
                f"position contains unsupported values: {invalid_positions!r}."
            )

        prices: list[int] = []
        for value in table["price_tenths"].tolist():
            if isinstance(value, bool) or not isinstance(value, Integral) or int(value) < 0:
                raise TransferPlanningValidationError(
                    "price_tenths must contain non-negative integers."
                )
            prices.append(int(value))
        table.loc[:, "price_tenths"] = prices

        for column in ("fixture_count", "home_fixture_count"):
            counts: list[int] = []
            for value in table[column].tolist():
                if isinstance(value, bool) or not isinstance(value, Integral) or int(value) < 0:
                    raise TransferPlanningValidationError(
                        f"{column} must contain non-negative integers."
                    )
                counts.append(int(value))
            table.loc[:, column] = counts
        if bool((table["home_fixture_count"] > table["fixture_count"]).any()):
            raise TransferPlanningValidationError(
                "home_fixture_count may not exceed fixture_count."
            )

        points: list[float] = []
        for value in table["expected_points"].tolist():
            if isinstance(value, bool) or not isinstance(value, Real):
                raise TransferPlanningValidationError(
                    "expected_points must contain finite non-negative numbers."
                )
            number = float(value)
            if not math.isfinite(number) or number < 0.0:
                raise TransferPlanningValidationError(
                    "expected_points must contain finite non-negative numbers."
                )
            points.append(number)
        table.loc[:, "expected_points"] = points
        blank_with_points = table.loc[
            (table["fixture_count"] == 0) & (table["expected_points"] > 0.0)
        ]
        if not blank_with_points.empty:
            examples = blank_with_points.loc[:, ["gameweek", "player_id"]].head(5)
            raise TransferPlanningValidationError(
                "A blank gameweek row must project exactly zero points; violations: "
                f"{examples.to_dict(orient='records')!r}."
            )

        object.__setattr__(self, "table", table)
        object.__setattr__(self, "horizon_fingerprint", self._fingerprint(table))

    def _fingerprint(self, table: pd.DataFrame) -> str:
        rows: list[dict[str, object]] = []
        for gameweek in sorted(int(value) for value in table["gameweek"].unique().tolist()):
            week = table.loc[table["gameweek"] == gameweek]
            player_ids = week["player_id"].tolist()
            order = sorted(range(len(week)), key=lambda index: _identifier_key(player_ids[index]))
            for index in order:
                row = week.iloc[index]
                rows.append(
                    {
                        "gameweek": gameweek,
                        "player_id": _typed_identifier(row["player_id"]),
                        "team_id": _typed_identifier(row["team_id"]),
                        "position": str(row["position"]),
                        "price_tenths": int(row["price_tenths"]),
                        "expected_points": float(row["expected_points"]).hex(),
                        "fixture_count": int(row["fixture_count"]),
                        "home_fixture_count": int(row["home_fixture_count"]),
                    }
                )
        payload = {
            "contract_version": self.contract_version,
            "season": self.season,
            "source_snapshot_id": self.source_snapshot_id,
            "model_name": self.model_name,
            "model_version": self.model_version,
            "feature_contract_version": self.feature_contract_version,
            "post_processing_contract_version": self.post_processing_contract_version,
            "rows": rows,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @property
    def target_gameweeks(self) -> tuple[int, ...]:
        """Return the consecutive projected gameweeks in decision order."""

        return tuple(sorted(int(value) for value in self.table["gameweek"].unique().tolist()))


class ProjectionHorizonBuilder(Protocol):
    """The prediction-side builder that produces multi-gameweek projections.

    One call projects every requested target gameweek from a single captured decision
    snapshot: separate expected points and fixture context per gameweek, one shared
    information state, and the provenance fields the horizon contract requires. The
    implementation is owned by the data/prediction side and must be leakage-safe with
    respect to the snapshot's capture time.
    """

    def __call__(
        self,
        decision_snapshot: object,
        target_gameweeks: tuple[int, ...],
    ) -> ProjectionHorizon: ...


def to_planning_horizon(horizon: ProjectionHorizon) -> PlanningHorizon:
    """Convert a projection handoff into the planner's transaction table.

    Buy and sell prices are both set to the projected `price_tenths`: no price
    transitions are modeled, and inventing them here would smuggle an unversioned
    price model into the planner. A future price-transition contract replaces this
    conversion rather than widening it.
    """

    if not isinstance(horizon, ProjectionHorizon):
        raise TransferPlanningValidationError("horizon must be a ProjectionHorizon.")
    table = horizon.table.loc[
        :, ["gameweek", "player_id", "name", "team_id", "position", "expected_points"]
    ].copy(deep=True)
    table["buy_price_tenths"] = horizon.table["price_tenths"].astype("int64")
    table["sell_price_tenths"] = horizon.table["price_tenths"].astype("int64")
    return PlanningHorizon(table)
