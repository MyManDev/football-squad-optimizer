"""Turn a captured deadline snapshot into a squad recommendation.

Two modes, and the difference between them is the whole point. **Live** resolves the next
deadline that has not closed and recommends for it. **Replay** rebuilds a past
recommendation from a stored snapshot and must return exactly what it returned then —
which is only possible because the capture is immutable and every input is either in it or
pinned.

The projection comes from the **operational control**, the deterministic baseline, and not
from the production candidate. The candidate was measured against the pre-registered gates
and did not clear them, so it is not what decides a real squad. That is not a formality:
recommending from an unpromoted model would make the gates decorative.

Availability is applied after the projection as an explicit multiplier, never as a model
input, because a live capture can prove it preceded the deadline and the archive cannot.
Every adjustment it makes is reported.
"""

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Final

import pandas as pd

from squadopt.data.errors import DataSourceError
from squadopt.data.snapshots import CapturedSnapshot
from squadopt.data.sources.fpl_live import (
    BOOTSTRAP_PAYLOAD,
    GameweekDeadline,
    availability_snapshot,
    gameweek_deadlines,
    next_open_deadline,
    player_snapshot,
)
from squadopt.data.timestamps import as_instant
from squadopt.features.cross_season import CrossSeasonConfig
from squadopt.prediction.availability import (
    AvailabilityRuleConfig,
    apply_availability,
)
from squadopt.prediction.config import BaselineProjectionConfig
from squadopt.prediction.elite_evidence import (
    ELITE_EVIDENCE_FEATURE_CONTRACT_VERSION,
    ELITE_EVIDENCE_MODEL_VERSION,
)
from squadopt.prediction.in_season import IN_SEASON_MODEL_VERSION
from squadopt.prediction.opening import build_opening_projection_from_snapshot

# Named so a report cannot describe itself as coming from a model that was never promoted.
CONTROL_MODEL_NAME: Final = "squadopt-deterministic-baseline"
CONTROL_MODEL_VERSION: Final = "opening-carry-over-v1"
OPENING_FEATURE_CONTRACT_VERSION: Final = "opening-carry-over-features-v1"

# What the projection can answer on its own. The opening path carries a completed season
# into a season with no played gameweeks; a later gameweek needs the current season's own
# history, which no live source in this project captures, so a mid-season projection is
# handed in by its producer under the contract below and the live path records whose it was.
SUPPORTED_TARGET_GAMEWEEK: Final = 1
PROJECTION_HANDOFF_CONTRACT_VERSION: Final = "projection_handoff_v1"
# Model versions promoted to decide a live mid-season squad through a handoff. Empty
# until an in-season control clears its gates: pinning a version here is the promotion
# decision, made in a reviewed change, and until then a mid-season decision is refused at
# verification rather than made from an unpromoted model.
IN_SEASON_CONTROL_MODEL_VERSIONS: Final[tuple[str, ...]] = (
    IN_SEASON_MODEL_VERSION,
    ELITE_EVIDENCE_MODEL_VERSION,
)


@dataclass(frozen=True, slots=True)
class InSeasonProjection:
    """A mid-season projection handed to the live path by the model that produced it.

    Rows map the persistent player code to expected points for one deadline; identity,
    club, position, and price come from the capture, which is the deadline-known source
    for them. The producer states its model identity and the capture it projected from,
    and the live path refuses a handoff for a different season, gameweek, or capture.
    Which model versions may decide a live squad is the promotion decision, checked at
    decision time, not here.
    """

    season: str
    gameweek: int
    source_snapshot_id: str
    model_name: str
    model_version: str
    feature_contract_version: str
    expected_points: Mapping[int, float]
    evidence_fingerprint: str | None = None
    diagnostics: Mapping[str, object] = field(default_factory=dict)
    contract_version: str = PROJECTION_HANDOFF_CONTRACT_VERSION

    def __post_init__(self) -> None:
        if self.contract_version != PROJECTION_HANDOFF_CONTRACT_VERSION:
            raise DataSourceError("Unsupported projection handoff contract_version.")
        for name in ("season", "source_snapshot_id", "model_name", "model_version"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise DataSourceError(f"Projection handoff {name} must be non-empty text.")
        if not isinstance(self.feature_contract_version, str):
            raise DataSourceError("Projection handoff feature_contract_version must be text.")
        if (
            isinstance(self.gameweek, bool)
            or not isinstance(self.gameweek, int)
            or self.gameweek < 1
        ):
            raise DataSourceError("Projection handoff gameweek must be a positive integer.")
        points: dict[int, float] = {}
        for player, value in dict(self.expected_points).items():
            if isinstance(player, bool) or not isinstance(player, int):
                raise DataSourceError("Projection handoff player ids must be integers.")
            number = float(value)
            if not math.isfinite(number):
                raise DataSourceError(f"Projection handoff has a non-finite value for {player}.")
            points[int(player)] = number
        if not points:
            raise DataSourceError("Projection handoff carries no rows.")
        if self.evidence_fingerprint is not None and (
            len(self.evidence_fingerprint) != 64
            or any(character not in "0123456789abcdef" for character in self.evidence_fingerprint)
        ):
            raise DataSourceError(
                "Projection handoff evidence_fingerprint must be a lowercase SHA-256 digest."
            )
        if self.model_version == ELITE_EVIDENCE_MODEL_VERSION and (
            self.evidence_fingerprint is None
            or self.feature_contract_version != ELITE_EVIDENCE_FEATURE_CONTRACT_VERSION
        ):
            raise DataSourceError(
                "The operational elite model requires its evidence fingerprint and exact "
                f"feature contract {ELITE_EVIDENCE_FEATURE_CONTRACT_VERSION!r}."
            )
        if self.model_version == IN_SEASON_MODEL_VERSION and self.evidence_fingerprint is not None:
            raise DataSourceError(
                "The legacy in-season control cannot claim an elite evidence fingerprint."
            )
        object.__setattr__(self, "expected_points", MappingProxyType(points))
        object.__setattr__(self, "diagnostics", MappingProxyType(dict(self.diagnostics)))

    @property
    def fingerprint(self) -> str:
        payload = {
            "season": self.season,
            "gameweek": self.gameweek,
            "source_snapshot_id": self.source_snapshot_id,
            "model_name": self.model_name,
            "model_version": self.model_version,
            "feature_contract_version": self.feature_contract_version,
            "expected_points": {
                str(player): f"{value:.9f}"
                for player, value in sorted(self.expected_points.items())
            },
        }
        if self.evidence_fingerprint is not None:
            payload["evidence_fingerprint"] = self.evidence_fingerprint
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


def write_projection_handoff(path: Path, projection: InSeasonProjection) -> Path:
    """Write a handoff file a producer hands to the live path."""

    document = {
        "contract_version": projection.contract_version,
        "season": projection.season,
        "gameweek": projection.gameweek,
        "source_snapshot_id": projection.source_snapshot_id,
        "model_name": projection.model_name,
        "model_version": projection.model_version,
        "feature_contract_version": projection.feature_contract_version,
        "expected_points": {
            str(player): value for player, value in sorted(projection.expected_points.items())
        },
        "diagnostics": dict(projection.diagnostics),
        "fingerprint": projection.fingerprint,
    }
    if projection.evidence_fingerprint is not None:
        document["evidence_fingerprint"] = projection.evidence_fingerprint
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def read_projection_handoff(path: Path) -> InSeasonProjection:
    """Read a producer's handoff file, refusing one whose fingerprint does not match."""

    if not Path(path).is_file():
        raise DataSourceError(f"No projection handoff at {path}.")
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise DataSourceError("Projection handoff must be a JSON object.")
    rows = document.get("expected_points")
    if not isinstance(rows, dict):
        raise DataSourceError("Projection handoff must map player codes to expected points.")
    try:
        projection = InSeasonProjection(
            season=str(document.get("season", "")),
            gameweek=int(document.get("gameweek", 0)),
            source_snapshot_id=str(document.get("source_snapshot_id", "")),
            model_name=str(document.get("model_name", "")),
            model_version=str(document.get("model_version", "")),
            feature_contract_version=str(document.get("feature_contract_version", "")),
            expected_points={int(player): float(value) for player, value in rows.items()},
            evidence_fingerprint=(
                str(document["evidence_fingerprint"])
                if document.get("evidence_fingerprint") is not None
                else None
            ),
            diagnostics=dict(document.get("diagnostics") or {}),
            contract_version=str(document.get("contract_version", "")),
        )
    except (TypeError, ValueError) as error:
        raise DataSourceError(f"Projection handoff at {path} is malformed: {error}") from error
    recorded = document.get("fingerprint")
    if recorded is not None and recorded != projection.fingerprint:
        raise DataSourceError(
            f"Projection handoff at {path} does not match its recorded fingerprint; "
            "the file was edited after it was written."
        )
    return projection


def _training_identity(panel: pd.DataFrame) -> tuple[str, str]:
    """Fingerprint the completed history supplied to the opening control."""

    columns = [
        column
        for column in (
            "season",
            "gameweek",
            "player_id",
            "team_id",
            "position",
            "price_tenths",
            "minutes",
            "total_points",
        )
        if column in panel.columns
    ]
    ordered = panel.loc[:, columns].sort_values(["season", "gameweek", "player_id"], kind="stable")
    fingerprint = hashlib.sha256(
        ordered.to_csv(index=False, lineterminator="\n").encode("utf-8")
    ).hexdigest()
    last = ordered.iloc[-1]
    cutoff = f"{last['season']}:GW{int(last['gameweek']):02d}"
    return cutoff, fingerprint


def infer_season(snapshot: CapturedSnapshot) -> str:
    """Name the season a capture describes, from its own published deadlines.

    A season is named for the calendar year it starts in, and its first deadline falls in
    that year, so the earliest published deadline settles it. Deriving it beats asking the
    caller: a season passed by hand can be wrong, and a capture filed under the wrong
    season would join the wrong history.
    """

    bootstrap = snapshot.payloads.get(BOOTSTRAP_PAYLOAD)
    if bootstrap is None:
        raise DataSourceError(
            f"Snapshot {snapshot.metadata.snapshot_id!r} carries no {BOOTSTRAP_PAYLOAD!r} "
            "payload, so its season cannot be determined."
        )
    deadlines = gameweek_deadlines(bootstrap)
    earliest = min(deadlines, key=lambda entry: entry.gameweek)
    start = as_instant(earliest.deadline_utc).year
    return f"{start}-{(start + 1) % 100:02d}"


@dataclass(frozen=True, slots=True)
class RecommendationInputs:
    """Everything read out of a capture, before any projection is made."""

    snapshot_id: str
    captured_at_utc: str
    season: str
    deadline: GameweekDeadline
    players: pd.DataFrame
    availability: pd.DataFrame


@dataclass(frozen=True, slots=True)
class Projection:
    """A projection with the route it took and what availability did to it."""

    table: pd.DataFrame
    unavailable_players: tuple[int, ...]
    diagnostics: Mapping[str, object]
    unprojected_players: tuple[int, ...] = ()
    """Roster players the projection had no number for and carries at zero; a decision
    that selects one of them is refused at verification."""


def read_inputs(
    snapshot: CapturedSnapshot,
    *,
    season: str,
    gameweek: int | None = None,
) -> RecommendationInputs:
    """Read the roster, the availability and the target deadline out of one capture.

    ``gameweek`` names a target explicitly, which is what replay does. Left out, the
    target is the earliest deadline that had not closed when the capture was taken —
    resolved from the capture's own instant rather than from the clock now, so replaying
    an old capture asks the question that capture was taken to answer.
    """

    bootstrap = snapshot.payloads.get(BOOTSTRAP_PAYLOAD)
    if bootstrap is None:
        raise DataSourceError(
            f"Snapshot {snapshot.metadata.snapshot_id!r} carries no {BOOTSTRAP_PAYLOAD!r} "
            "payload, so it cannot describe a roster."
        )

    deadlines = gameweek_deadlines(bootstrap)
    if gameweek is None:
        deadline = next_open_deadline(deadlines, as_of_utc=snapshot.metadata.captured_at_utc)
    else:
        matched = [entry for entry in deadlines if entry.gameweek == gameweek]
        if not matched:
            published = sorted(entry.gameweek for entry in deadlines)
            raise DataSourceError(
                f"Snapshot {snapshot.metadata.snapshot_id!r} publishes no gameweek "
                f"{gameweek}; it carries {published[:5]!r} through {published[-1:]!r}."
            )
        deadline = matched[0]

    return RecommendationInputs(
        snapshot_id=snapshot.metadata.snapshot_id,
        captured_at_utc=snapshot.metadata.captured_at_utc,
        season=season,
        deadline=deadline,
        players=player_snapshot(bootstrap),
        availability=availability_snapshot(bootstrap),
    )


def project(
    inputs: RecommendationInputs,
    panel: pd.DataFrame | None = None,
    *,
    projection_config: BaselineProjectionConfig | None = None,
    cross_season: CrossSeasonConfig | None = None,
    availability_config: AvailabilityRuleConfig | None = None,
    in_season: InSeasonProjection | None = None,
) -> Projection:
    """Project the captured roster, then apply availability.

    An opening gameweek is projected here with the operational control's carry-over
    path. A later gameweek needs the current season's played history, which the archive
    publishes only after it has been played and no captured source provides, so it must
    arrive as an ``in_season`` handoff from the model that produced it; the live path
    joins it to the capture's roster, applies availability, and records whose it was.
    Refusing without one is the honest answer: projecting from carry-over alone in
    gameweek twenty would silently ignore everything that had happened that season.
    """

    if inputs.deadline.gameweek != SUPPORTED_TARGET_GAMEWEEK:
        if in_season is None:
            raise DataSourceError(
                f"Gameweek {inputs.deadline.gameweek} needs the current season's played "
                "history, which no captured source provides. Hand in a projection under "
                f"{PROJECTION_HANDOFF_CONTRACT_VERSION!r} for this capture and gameweek; "
                "only the opening gameweek can be projected from a capture plus completed "
                "seasons."
            )
        return _project_in_season(inputs, in_season, availability_config=availability_config)
    if in_season is not None:
        raise DataSourceError(
            "The opening gameweek is projected by the operational control from the "
            "capture; an in-season handoff is not read for it."
        )
    if panel is None:
        raise DataSourceError(
            "The opening gameweek is projected from the completed seasons' panel; none was "
            "supplied."
        )

    table = build_opening_projection_from_snapshot(
        panel,
        inputs.players,
        season=inputs.season,
        config=projection_config,
        cross_season=cross_season,
    )
    adjusted = apply_availability(table, inputs.availability, config=availability_config)
    training_cutoff, training_fingerprint = _training_identity(panel)

    projected = adjusted.table
    carried = int(projected["has_prior_record"].sum())
    return Projection(
        table=projected,
        unavailable_players=adjusted.unavailable_players,
        diagnostics={
            **dict(adjusted.diagnostics),
            "players": len(projected),
            "players_with_prior_record": carried,
            "players_priced_from_prior": len(projected) - carried,
            "model_name": CONTROL_MODEL_NAME,
            "model_version": CONTROL_MODEL_VERSION,
            "feature_contract_version": OPENING_FEATURE_CONTRACT_VERSION,
            "training_cutoff": training_cutoff,
            "training_data_fingerprint": training_fingerprint,
            "projection_source": "operational_control",
        },
    )


def _project_in_season(
    inputs: RecommendationInputs,
    handoff: InSeasonProjection,
    *,
    availability_config: AvailabilityRuleConfig | None,
) -> Projection:
    for name, expected, actual in (
        ("season", inputs.season, handoff.season),
        ("gameweek", inputs.deadline.gameweek, handoff.gameweek),
        ("capture", inputs.snapshot_id, handoff.source_snapshot_id),
    ):
        if expected != actual:
            raise DataSourceError(
                f"Projection handoff is for {name} {actual!r}; this decision is for "
                f"{expected!r}. A projection made from another capture or for another "
                "deadline does not describe this roster."
            )
    players = inputs.players
    codes = [int(value) for value in players["player_id"].tolist()]
    missing = tuple(sorted(code for code in codes if code not in handoff.expected_points))
    if missing:
        # A roster player without a number would be carried at 0.0 and therefore never
        # selected — a silent quality loss no downstream check can see, because the
        # selected-player verification only inspects players that were picked. The
        # producer reads the same capture, so full coverage is always achievable and a
        # gap is a producer defect, surfaced here where it first becomes wrong.
        shown = ", ".join(str(code) for code in missing[:5])
        raise DataSourceError(
            f"Projection handoff omits {len(missing)} roster player(s) (first: {shown}). "
            "Every player in this capture's roster needs a number; a missing one would "
            "silently price the player at zero and exclude them from selection."
        )
    unknown = sorted(set(handoff.expected_points) - set(codes))
    table = players.loc[:, ["player_id", "name", "team_id", "position", "price_tenths"]].copy(
        deep=True
    )
    table["expected_points"] = [float(handoff.expected_points[code]) for code in codes]
    adjusted = apply_availability(table, inputs.availability, config=availability_config)
    return Projection(
        table=adjusted.table,
        unavailable_players=adjusted.unavailable_players,
        diagnostics={
            **dict(adjusted.diagnostics),
            "players": len(adjusted.table),
            "players_without_projection": 0,
            "handoff_players_not_on_roster": len(unknown),
            "model_name": handoff.model_name,
            "model_version": handoff.model_version,
            "feature_contract_version": handoff.feature_contract_version,
            "projection_handoff_contract_version": handoff.contract_version,
            "projection_handoff_fingerprint": handoff.fingerprint,
            "projection_evidence_fingerprint": handoff.evidence_fingerprint,
            "projection_source": "in_season_handoff",
            **{f"handoff_{key}": value for key, value in handoff.diagnostics.items()},
        },
    )
