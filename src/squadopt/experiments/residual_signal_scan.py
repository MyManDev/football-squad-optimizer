"""Which signals the archive already holds does the control still leave in its residuals?

The prediction side asked one version of this question for opponent strength
(`backtest.opponent_strength_signal`) and found the residuals still move with it. This
module asks it for the enrichment fields the archive carries but the canonical panel does
not: expected goal involvement, recent luck (returns above expected), ownership, the
source's own point expectation, and whether a player has just changed club. Every
covariate is built with a strict lag — only rows before the decision gameweek, or values
published before its deadline — so what is measured is what a model could have seen.

Nothing here adds a feature. The canonical panel and the projection contracts belong to
the prediction side; this is a measurement that says, per signal, whether a feature would
have anything to buy. A residual that moves with a signal is unspent; one that does not is
already captured (or was never worth capturing).

The raw archive is read directly, per season, for the enrichment columns only. Seasons
without a column are reported as absent rather than filled.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from itertools import pairwise
from pathlib import Path
from types import MappingProxyType
from typing import Final

import pandas as pd

from squadopt.data.sources.vaastav import (
    GAMEWEEK_FILE,
    ROSTER_FILE,
    attach_player_code,
    season_directory,
)
from squadopt.experiments.config import ExperimentConfigurationError, ExperimentExecutionError

RESIDUAL_SIGNAL_SCAN_CONTRACT_VERSION: Final = "residual_signal_scan_v1"
QUARTILE_LABELS: Final = ("Q1", "Q2", "Q3", "Q4")

_RAW_NUMERIC: Final = (
    "minutes",
    "goals_scored",
    "assists",
    "expected_goal_involvements",
    "selected",
    "xP",
)
_RESIDUAL_COLUMNS: Final = (
    "season",
    "gameweek",
    "player_id",
    "position",
    "residual",
    "realized_points",
)


@dataclass(frozen=True, slots=True)
class SignalBin:
    """One bin of a covariate: how many rows, and where realized points and residuals sit."""

    label: str
    observations: int
    mean_covariate: float
    mean_realized_points: float
    mean_residual: float


@dataclass(frozen=True, slots=True)
class SignalResult:
    """One covariate's scan: its bins and what the residual spread says."""

    covariate: str
    description: str
    seasons_present: tuple[str, ...]
    rows: int
    bins: tuple[SignalBin, ...]
    residual_spread: float
    realized_spread: float
    monotone_residual: bool

    @property
    def surviving_ratio(self) -> float | None:
        """Residual spread over raw realized spread; above one means the model widened it."""

        if self.realized_spread == 0.0:
            return None
        return self.residual_spread / self.realized_spread


@dataclass(frozen=True, slots=True)
class ResidualSignalScan:
    contract_version: str
    window: int
    signals: tuple[SignalResult, ...]
    diagnostics: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "diagnostics", MappingProxyType(dict(self.diagnostics)))


def _read_season_raw(root: Path, season: str) -> pd.DataFrame:
    directory = season_directory(root, season)
    gameweeks = pd.read_csv(directory / GAMEWEEK_FILE, dtype=str, keep_default_na=False)
    roster = pd.read_csv(directory / ROSTER_FILE, dtype=str, keep_default_na=False)
    for column in ("element", "round", "fixture"):
        if column not in gameweeks.columns:
            raise ExperimentExecutionError(f"{season}: raw gameweek file lacks {column!r}.")
    for column in ("id", "code"):
        if column not in roster.columns:
            raise ExperimentExecutionError(f"{season}: raw roster file lacks {column!r}.")
    frame = gameweeks.drop_duplicates(subset=["element", "fixture", "round"], keep="first").copy()
    frame["element"] = pd.to_numeric(frame["element"], errors="coerce")
    frame["round"] = pd.to_numeric(frame["round"], errors="coerce")
    frame = frame.loc[frame["element"].notna() & frame["round"].notna()]
    roster = roster.copy()
    roster["id"] = pd.to_numeric(roster["id"], errors="coerce")
    roster["code"] = pd.to_numeric(roster["code"], errors="coerce")
    frame["element"] = frame["element"].astype("int64")
    frame["round"] = frame["round"].astype("int64")
    roster = roster.loc[roster["id"].notna() & roster["code"].notna()].copy()
    roster["id"] = roster["id"].astype("int64")
    roster["code"] = roster["code"].astype("int64")
    present = [column for column in _RAW_NUMERIC if column in frame.columns]
    for column in present:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    joined = attach_player_code(frame, roster)
    aggregations: dict[str, str] = {}
    for column in present:
        # Per-fixture quantities add across a double gameweek; ownership and the
        # source's expectation are per-gameweek and are taken once.
        aggregations[column] = "first" if column in ("selected", "xP") else "sum"
    collapsed = (
        joined.groupby(["player_code", "round"], as_index=False, sort=True)
        .agg(aggregations)
        .rename(columns={"player_code": "player_id", "round": "gameweek"})
    )
    collapsed["season"] = season
    for column in _RAW_NUMERIC:
        if column not in collapsed.columns:
            collapsed[column] = float("nan")
    return collapsed


def _lagged_rolling_ratio(
    frame: pd.DataFrame,
    numerator: str,
    denominator: str,
    *,
    window: int,
    scale: float,
) -> pd.Series:
    """Ratio of rolling sums over the previous ``window`` rows, excluding the current one."""

    grouped = frame.groupby(["season", "player_id"], sort=False)
    top = grouped[numerator].transform(
        lambda values: values.shift(1).rolling(window, min_periods=1).sum()
    )
    bottom = grouped[denominator].transform(
        lambda values: values.shift(1).rolling(window, min_periods=1).sum()
    )
    ratio = top.div(bottom).mul(scale)
    return ratio.where(bottom.gt(0.0))


def build_lagged_covariates(
    raw: pd.DataFrame,
    panel: pd.DataFrame,
    *,
    window: int,
) -> pd.DataFrame:
    """Attach strictly lagged enrichment covariates to canonical player-gameweek keys.

    Every value is either computed from rows strictly before the gameweek (rolling
    quantities) or published before the deadline (ownership and the source's own
    expectation for the gameweek itself), so nothing here reaches into the outcome.
    """

    if window < 1:
        raise ExperimentConfigurationError("window must be a positive integer.")
    frame = raw.sort_values(["season", "player_id", "gameweek"], kind="stable").reset_index(
        drop=True
    )
    frame["returns"] = frame["goals_scored"].fillna(0.0) + frame["assists"].fillna(0.0)
    frame["xgi_per_90_last"] = _lagged_rolling_ratio(
        frame, "expected_goal_involvements", "minutes", window=window, scale=90.0
    )
    grouped = frame.groupby(["season", "player_id"], sort=False)
    lagged_returns = grouped["returns"].transform(
        lambda values: values.shift(1).rolling(window, min_periods=1).sum()
    )
    lagged_xgi = grouped["expected_goal_involvements"].transform(
        lambda values: values.shift(1).rolling(window, min_periods=1).sum()
    )
    frame["luck_last"] = (lagged_returns - lagged_xgi).where(lagged_xgi.notna())
    frame["ownership_prev"] = grouped["selected"].shift(1)
    frame["source_xp"] = frame["xP"]

    keys = panel.loc[:, ["season", "gameweek", "player_id", "team_id"]].copy()
    keys = keys.sort_values(["season", "player_id", "gameweek"], kind="stable").reset_index(
        drop=True
    )
    previous_team = keys.groupby(["season", "player_id"], sort=False)["team_id"].shift(1)
    changed = previous_team.notna() & (previous_team != keys["team_id"])
    # Weeks since the last club change inside the season; NaN when never changed.
    change_index = keys.index.to_series().where(changed)
    last_change = change_index.groupby([keys["season"], keys["player_id"]]).ffill()
    keys["recently_moved"] = (
        (keys.index.to_series() - last_change).le(window - 1).fillna(False).astype("int64")
    )
    covariates = keys.merge(
        frame.loc[
            :,
            [
                "season",
                "gameweek",
                "player_id",
                "xgi_per_90_last",
                "luck_last",
                "ownership_prev",
                "source_xp",
            ],
        ],
        on=["season", "gameweek", "player_id"],
        how="left",
    )
    return covariates.drop(columns=["team_id"])


SIGNALS: Final[tuple[tuple[str, str, str], ...]] = (
    (
        "xgi_per_90_last",
        "quartiles",
        "expected goal involvement per 90 over the previous window (xG data from 2022-23)",
    ),
    (
        "luck_last",
        "quartiles",
        "returns minus expected goal involvement over the previous window; positive = ran hot",
    ),
    ("ownership_prev", "quartiles", "ownership count at the previous gameweek"),
    ("source_xp", "quartiles", "the source's own published point expectation for the gameweek"),
    ("recently_moved", "binary", "changed club within the previous window (in-season)"),
)


def _monotone(values: Sequence[float]) -> bool:
    increasing = all(b >= a for a, b in pairwise(values))
    decreasing = all(b <= a for a, b in pairwise(values))
    return increasing or decreasing


def _bins(frame: pd.DataFrame, column: str, kind: str) -> tuple[SignalBin, ...]:
    if kind == "binary":
        labels = frame[column].map({0: "unchanged", 1: "recently_moved"})
    else:
        try:
            # Ties at the quartile edges collapse bins; keep however many distinct
            # bins the data supports and label them in order.
            codes, edges = pd.qcut(frame[column], 4, labels=False, retbins=True, duplicates="drop")
        except ValueError as error:
            raise ExperimentExecutionError(
                f"Covariate {column!r} cannot be split into quartiles: {error}"
            ) from error
        names = list(QUARTILE_LABELS[: len(edges) - 1])
        labels = pd.Series(codes, index=frame.index).map(dict(enumerate(names)))
    bins: list[SignalBin] = []
    for label, group in frame.groupby(labels, observed=True, sort=True):
        bins.append(
            SignalBin(
                label=str(label),
                observations=len(group),
                mean_covariate=float(group[column].mean()),
                mean_realized_points=float(group["realized_points"].mean()),
                mean_residual=float(group["residual"].mean()),
            )
        )
    return tuple(bins)


def scan_residual_signals(
    residuals: pd.DataFrame,
    covariates: pd.DataFrame,
    *,
    window: int,
    min_rows: int = 1_000,
) -> ResidualSignalScan:
    """Join lagged covariates to control residuals and bin the residual by each one."""

    missing = [column for column in _RESIDUAL_COLUMNS if column not in residuals.columns]
    if missing:
        raise ExperimentConfigurationError(f"Residual table lacks columns {missing!r}.")
    merged = residuals.merge(covariates, on=["season", "gameweek", "player_id"], how="left")
    if len(merged) != len(residuals):
        raise ExperimentExecutionError("Covariate join changed the residual row count.")
    results: list[SignalResult] = []
    for column, kind, description in SIGNALS:
        subset = merged.loc[
            merged[column].notna(), [column, "season", "residual", "realized_points"]
        ]
        seasons = tuple(sorted({str(value) for value in subset["season"].tolist()}))
        if len(subset) < min_rows:
            results.append(
                SignalResult(
                    covariate=column,
                    description=description,
                    seasons_present=seasons,
                    rows=len(subset),
                    bins=(),
                    residual_spread=0.0,
                    realized_spread=0.0,
                    monotone_residual=False,
                )
            )
            continue
        bins = _bins(subset, column, kind)
        residual_means = [entry.mean_residual for entry in bins]
        realized_means = [entry.mean_realized_points for entry in bins]
        results.append(
            SignalResult(
                covariate=column,
                description=description,
                seasons_present=seasons,
                rows=len(subset),
                bins=bins,
                residual_spread=float(max(residual_means) - min(residual_means)),
                realized_spread=float(max(realized_means) - min(realized_means)),
                monotone_residual=_monotone(residual_means),
            )
        )
    return ResidualSignalScan(
        contract_version=RESIDUAL_SIGNAL_SCAN_CONTRACT_VERSION,
        window=window,
        signals=tuple(results),
        diagnostics={
            "residual_rows": len(residuals),
            "covariate_rows": len(covariates),
            "seasons": sorted({str(value) for value in residuals["season"].tolist()}),
        },
    )


def load_enrichment_rows(root: Path, seasons: Sequence[str]) -> pd.DataFrame:
    """Read the enrichment columns for the named seasons from the raw archive."""

    pieces = [_read_season_raw(Path(root), season) for season in seasons]
    if not pieces:
        raise ExperimentConfigurationError("At least one season is required.")
    return pd.concat(pieces, ignore_index=True)


def _seasons(scan: ResidualSignalScan) -> list[str]:
    value = scan.diagnostics.get("seasons", [])
    assert isinstance(value, list | tuple)
    return [str(item) for item in value]


def scan_to_markdown(scan: ResidualSignalScan) -> str:
    lines = [
        "# Residual signal scan",
        "",
        f"- Contract: `{scan.contract_version}`; lag window {scan.window} gameweeks",
        f"- Seasons: {', '.join(str(value) for value in _seasons(scan))}"
        f"; residual rows {scan.diagnostics.get('residual_rows')}",
        "- Every covariate is strictly lagged or published before the deadline. Residual "
        "spread = max minus min mean residual across bins; surviving ratio = residual "
        "spread over raw realized spread (above one: the model widened the effect).",
        "",
    ]
    for signal in scan.signals:
        lines += [f"## `{signal.covariate}` — {signal.description}", ""]
        if not signal.bins:
            lines += [
                f"Not measured: {signal.rows} rows with the covariate present "
                f"(seasons: {', '.join(signal.seasons_present) or 'none'}).",
                "",
            ]
            continue
        lines += [
            f"- Rows {signal.rows}; seasons {', '.join(signal.seasons_present)}",
            f"- Residual spread **{signal.residual_spread:+.4f}**; realized spread "
            f"{signal.realized_spread:+.4f}; surviving ratio "
            f"{'-' if signal.surviving_ratio is None else f'{signal.surviving_ratio:.2f}'}; "
            f"monotone residual: {'yes' if signal.monotone_residual else 'no'}",
            "",
            "| Bin | Rows | Mean covariate | Realized | Residual |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
        for entry in signal.bins:
            lines.append(
                f"| {entry.label} | {entry.observations} | {entry.mean_covariate:.3f} "
                f"| {entry.mean_realized_points:.4f} | {entry.mean_residual:+.4f} |"
            )
        lines.append("")
    lines += [
        "Measurement only: no feature, contract, or model changed; the locked holdout was",
        "not read.",
    ]
    return "\n".join(lines) + "\n"


__all__ = [
    "RESIDUAL_SIGNAL_SCAN_CONTRACT_VERSION",
    "SIGNALS",
    "ResidualSignalScan",
    "SignalBin",
    "SignalResult",
    "build_lagged_covariates",
    "load_enrichment_rows",
    "scan_residual_signals",
    "scan_to_markdown",
]
