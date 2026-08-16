"""Live calibration: what the season's settled decisions say about our projections.

The ledger accumulates the only out-of-sample series that was produced under real
conditions — decisions frozen before kickoff, outcomes read from later captures. This
module compares that series against the historical references measured on development
folds: the selection-optimism gap (how far below projection a chosen XI lands), the
captain's gap, and player-level error. Nothing here changes a projection or a control;
it only reports whether live behavior matches what the development measurements
promised.

Realized points for the full roster are re-read from the settle capture named in each
outcome, which works because captures are immutable and retained. Interval coverage,
when a residual history is supplied, uses empirical per-position residual quantiles
(`empirical_position_residual_interval_v1`) — deliberately simple, because the frozen
player-adaptive calibration is fit on walk-forward folds that live gameweeks will only
provide later in the season.
"""

import math
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final, cast

import pandas as pd

from squadopt.data.errors import DataError
from squadopt.data.snapshots import read_snapshot
from squadopt.live.ledger import (
    LedgerEntry,
    LedgerError,
    extract_event_points,
    load_ledger,
)

LIVE_CALIBRATION_CONTRACT_VERSION: Final = "live_calibration_v1"
INTERVAL_RULE_VERSION: Final = "empirical_position_residual_interval_v1"

# Development-fold references from docs/selection_optimism.json (147 folds, control
# regime): mean realized-minus-projected per selected starter and for captains.
HISTORICAL_XI_OPTIMISM_PER_STARTER: Final = -2.96
HISTORICAL_CAPTAIN_OPTIMISM: Final = -3.86

_PROJECTIONS_FILE: Final = "projections.csv"


class LiveCalibrationError(DataError):
    """Raised when the live series cannot be built or is not evidence yet."""


@dataclass(frozen=True, slots=True)
class GameweekCalibrationRow:
    """One settled gameweek compared against its own frozen projections."""

    gameweek: int
    source_snapshot_id: str
    projected_xi_score: float
    realized_xi_score: float
    xi_error: float
    xi_optimism_per_starter: float
    captain_optimism: float
    roster_players_scored: int
    roster_mean_error: float
    roster_mae: float
    interval_players: int | None
    interval_coverage: float | None


@dataclass(frozen=True, slots=True)
class LiveCalibrationResult:
    """The season's live series against its historical references."""

    contract_version: str
    season: str
    rows: tuple[GameweekCalibrationRow, ...]
    mean_xi_error: float
    mean_xi_optimism_per_starter: float
    mean_captain_optimism: float
    roster_mean_error: float
    roster_mae: float
    historical_xi_optimism_per_starter: float
    historical_captain_optimism: float
    interval_rule: str | None
    interval_nominal_coverage: float | None
    interval_live_coverage: float | None

    @property
    def settled_gameweeks(self) -> int:
        return len(self.rows)


def _position_interval_offsets(
    residual_history: pd.DataFrame,
    *,
    lower_quantile: float,
    upper_quantile: float,
) -> tuple[dict[str, tuple[float, float]], tuple[float, float]]:
    for column in ("position", "residual"):
        if column not in residual_history.columns:
            raise LiveCalibrationError(
                f"Residual history must carry a {column!r} column (oos_residual_export_v1 shape)."
            )
    residuals = residual_history["residual"].astype("float64")
    if residuals.empty or not bool(residuals.map(math.isfinite).all()):
        raise LiveCalibrationError("Residual history must be non-empty and finite.")
    pooled = (
        float(residuals.quantile(lower_quantile)),
        float(residuals.quantile(upper_quantile)),
    )
    offsets: dict[str, tuple[float, float]] = {}
    for position, group in residual_history.groupby("position")["residual"]:
        values = group.astype("float64")
        offsets[str(position)] = (
            float(values.quantile(lower_quantile)),
            float(values.quantile(upper_quantile)),
        )
    return offsets, pooled


def _roster_frame(entry: LedgerEntry, realized_points: Mapping[int, float]) -> pd.DataFrame:
    projections = pd.read_csv(entry.directory / _PROJECTIONS_FILE)
    missing = [
        int(player)
        for player in projections["player_id"].tolist()
        if int(player) not in realized_points
    ]
    if missing:
        raise LiveCalibrationError(
            f"GW{entry.gameweek}: settle capture lacks realized points for projected "
            f"players {sorted(missing)[:10]!r}; the roster series would be partial."
        )
    frame = projections.loc[:, ["player_id", "position", "expected_points"]].copy()
    frame["realized_points"] = [
        float(realized_points[int(player)]) for player in frame["player_id"].tolist()
    ]
    frame["error"] = frame["realized_points"] - frame["expected_points"]
    return frame


def _row_for_entry(
    entry: LedgerEntry,
    snapshot_root: Path,
    offsets: dict[str, tuple[float, float]] | None,
    pooled_offset: tuple[float, float] | None,
) -> GameweekCalibrationRow:
    outcome = entry.outcome
    assert outcome is not None  # callers filter to settled entries
    source_snapshot_id = str(outcome["source_snapshot_id"])
    try:
        snapshot = read_snapshot(snapshot_root, source_snapshot_id)
    except DataError as error:
        raise LiveCalibrationError(
            f"GW{entry.gameweek}: settle capture {source_snapshot_id!r} is not "
            f"readable under {snapshot_root}; the immutable capture is required to "
            f"rebuild the full-roster series. ({error})"
        ) from error
    realized_points = extract_event_points(snapshot, gameweek=entry.gameweek)
    roster = _roster_frame(entry, realized_points)

    starters_raw = cast("list[object]", entry.decision["starting_xi_player_ids"])
    starters = [int(str(player)) for player in starters_raw]
    captain = int(str(entry.decision["captain_player_id"]))
    by_player = dict(
        zip(
            [int(player) for player in roster["player_id"].tolist()],
            [float(value) for value in roster["error"].tolist()],
            strict=True,
        )
    )
    starter_errors = [by_player[player] for player in starters]

    interval_players: int | None = None
    interval_coverage: float | None = None
    if offsets is not None and pooled_offset is not None:
        covered = 0
        for position, expected, realized in zip(
            [str(value) for value in roster["position"].tolist()],
            [float(value) for value in roster["expected_points"].tolist()],
            [float(value) for value in roster["realized_points"].tolist()],
            strict=True,
        ):
            lower_offset, upper_offset = offsets.get(position, pooled_offset)
            if expected + lower_offset <= realized <= expected + upper_offset:
                covered += 1
        interval_players = len(roster)
        interval_coverage = covered / len(roster)

    projected_xi = float(str(entry.decision["projected_score"]))
    realized_xi = float(str(outcome["realized_xi_score"]))
    return GameweekCalibrationRow(
        gameweek=entry.gameweek,
        source_snapshot_id=source_snapshot_id,
        projected_xi_score=projected_xi,
        realized_xi_score=realized_xi,
        xi_error=realized_xi - projected_xi,
        xi_optimism_per_starter=sum(starter_errors) / len(starter_errors),
        captain_optimism=by_player[captain],
        roster_players_scored=len(roster),
        roster_mean_error=float(roster["error"].mean()),
        roster_mae=float(roster["error"].abs().mean()),
        interval_players=interval_players,
        interval_coverage=interval_coverage,
    )


def measure_live_calibration(
    ledger_root: Path,
    season: str,
    *,
    snapshot_root: Path,
    residual_history: pd.DataFrame | None = None,
    interval_lower_quantile: float = 0.05,
    interval_upper_quantile: float = 0.95,
    historical_xi_optimism_per_starter: float = HISTORICAL_XI_OPTIMISM_PER_STARTER,
    historical_captain_optimism: float = HISTORICAL_CAPTAIN_OPTIMISM,
) -> LiveCalibrationResult:
    """Build the live out-of-sample series from every settled ledger entry."""

    if not 0.0 < interval_lower_quantile < interval_upper_quantile < 1.0:
        raise LiveCalibrationError("Interval quantiles must satisfy 0 < lower < upper < 1.")
    try:
        entries = load_ledger(ledger_root, season)
    except LedgerError as error:
        raise LiveCalibrationError(f"Ledger for {season} cannot be trusted: {error}") from error
    settled = [entry for entry in entries if entry.outcome is not None]
    if not settled:
        raise LiveCalibrationError(
            f"No settled gameweeks for {season} under {ledger_root}; live calibration "
            "is measured on real outcomes or not at all."
        )

    offsets: dict[str, tuple[float, float]] | None = None
    pooled_offset: tuple[float, float] | None = None
    if residual_history is not None:
        offsets, pooled_offset = _position_interval_offsets(
            residual_history,
            lower_quantile=interval_lower_quantile,
            upper_quantile=interval_upper_quantile,
        )

    rows = tuple(_row_for_entry(entry, snapshot_root, offsets, pooled_offset) for entry in settled)
    total_roster = sum(row.roster_players_scored for row in rows)
    roster_error_sum = sum(row.roster_mean_error * row.roster_players_scored for row in rows)
    roster_mae_sum = sum(row.roster_mae * row.roster_players_scored for row in rows)
    interval_live_coverage: float | None = None
    if residual_history is not None:
        covered = sum((row.interval_coverage or 0.0) * (row.interval_players or 0) for row in rows)
        interval_live_coverage = covered / total_roster
    return LiveCalibrationResult(
        contract_version=LIVE_CALIBRATION_CONTRACT_VERSION,
        season=season,
        rows=rows,
        mean_xi_error=sum(row.xi_error for row in rows) / len(rows),
        mean_xi_optimism_per_starter=(sum(row.xi_optimism_per_starter for row in rows) / len(rows)),
        mean_captain_optimism=sum(row.captain_optimism for row in rows) / len(rows),
        roster_mean_error=roster_error_sum / total_roster,
        roster_mae=roster_mae_sum / total_roster,
        historical_xi_optimism_per_starter=historical_xi_optimism_per_starter,
        historical_captain_optimism=historical_captain_optimism,
        interval_rule=INTERVAL_RULE_VERSION if residual_history is not None else None,
        interval_nominal_coverage=(
            (interval_upper_quantile - interval_lower_quantile)
            if residual_history is not None
            else None
        ),
        interval_live_coverage=interval_live_coverage,
    )


def calibration_markdown(result: LiveCalibrationResult) -> str:
    """Render the live calibration report for `docs/`."""

    lines = [
        f"# Live Calibration {result.season} (through GW{result.rows[-1].gameweek})",
        "",
        f"- Contract: `{result.contract_version}`",
        f"- Settled gameweeks measured: {result.settled_gameweeks}",
        "- Optimism = realized minus projected; negative means the projection was "
        "optimistic. Historical references come from the 147-fold development "
        "selection-optimism profile.",
        "",
        "| GW | Projected XI | Realized XI | XI error | Optimism/starter "
        "| Captain optimism | Roster MAE | Interval coverage |",
        "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in result.rows:
        coverage = "-" if row.interval_coverage is None else f"{row.interval_coverage:.2f}"
        lines.append(
            f"| {row.gameweek} | {row.projected_xi_score:.1f} "
            f"| {row.realized_xi_score:.1f} | {row.xi_error:+.1f} "
            f"| {row.xi_optimism_per_starter:+.2f} | {row.captain_optimism:+.2f} "
            f"| {row.roster_mae:.2f} | {coverage} |"
        )
    lines += [
        "",
        "## Against the development references",
        "",
        f"- XI optimism per starter: live {result.mean_xi_optimism_per_starter:+.2f} "
        f"vs historical {result.historical_xi_optimism_per_starter:+.2f}",
        f"- Captain optimism: live {result.mean_captain_optimism:+.2f} "
        f"vs historical {result.historical_captain_optimism:+.2f}",
        f"- Full-roster bias {result.roster_mean_error:+.2f}, MAE {result.roster_mae:.2f} "
        f"over {sum(row.roster_players_scored for row in result.rows)} player-gameweeks",
    ]
    if result.interval_rule is not None:
        assert result.interval_nominal_coverage is not None
        assert result.interval_live_coverage is not None
        lines.append(
            f"- Interval coverage (`{result.interval_rule}`): live "
            f"{result.interval_live_coverage:.2f} vs nominal "
            f"{result.interval_nominal_coverage:.2f}"
        )
    lines += [
        "",
        "Measurement only: no projection, control, or ledger entry was changed. A "
        "handful of gameweeks is a small sample; treat gaps as watch items, not "
        "verdicts.",
    ]
    return "\n".join(lines) + "\n"
