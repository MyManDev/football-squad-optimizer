"""Is opponent strength signal the control leaves on the table?

`squadopt.features.strength` has estimated opponent attacking and defensive strength since
Sprint 10 and no production path consumes it. Its docstring records a *ceiling* — measured
with season-average strength, which sees the whole season — and says so explicitly. The
promise was never measured, so a module sits in the tree whose value is unknown and whose
fate cannot be decided on evidence.

The question this answers is deliberately narrower than "does opponent strength correlate
with points". It does, and the existing features already capture part of it: a player's own
rolling per-90 partly encodes the fixtures he has faced. The question that decides anything
is whether the correlation **survives the model** — whether the operational control's
out-of-sample residuals still move with opponent strength after it has made its projection.

A residual that moves with something the model could have seen is signal left on the table.
A residual that does not is a signal already spent.

Both are reported, side by side, because the difference between them is the part the
existing feature set already captures, and quoting only the raw effect would overstate what
a new feature could buy.

The two sides are kept apart throughout. A defender's opponent is an attack and an
attacker's opponent is a defence; folding them into one "difficulty" would describe
neither, which is the same reason `features.strength` splits them in the first place.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise
from typing import Final

import pandas as pd

from squadopt.backtest.splits import BacktestConfigurationError
from squadopt.features.strength import OPPONENT_STRENGTH_COLUMNS, attach_opponent_strength

OPPONENT_STRENGTH_SIGNAL_CONTRACT_VERSION: Final = "opponent_strength_signal_v1"

# Which side of the ball each position group is exposed to. An attacker's return depends on
# the defence he faces; a defender's on the attack.
SIDES: Final = (
    ("attacking", ("MID", "FWD"), "opponent_defence_strength"),
    ("defensive", ("GK", "DEF"), "opponent_attack_strength"),
)

QUARTILE_LABELS: Final = ("Q1", "Q2", "Q3", "Q4")


@dataclass(frozen=True, slots=True)
class QuartileRow:
    """One opponent-strength quartile, on one side of the ball."""

    quartile: str
    observations: int
    mean_opponent_strength: float
    mean_realized_points: float
    mean_residual: float


@dataclass(frozen=True, slots=True)
class SideSignal:
    """What one side of the ball shows, raw and after the model."""

    side: str
    positions: tuple[str, ...]
    strength_column: str
    observations: int
    quartiles: tuple[QuartileRow, ...]
    raw_spread: float
    residual_spread: float
    raw_monotone: bool
    residual_monotone: bool

    @property
    def surviving_ratio(self) -> float:
        """How much of the raw effect is still there after the model has projected.

        Deliberately a ratio rather than a "share captured". Both sides measure above
        1.0 — the effect is *larger* in the residuals than in the raw outcomes — and a
        share-captured framing would report that as a negative percentage, which reads
        like an error rather than the finding it is.

        The reason it exceeds 1.0 is worth stating: players facing the strongest
        opponents are on average the better players on the better teams, so the raw
        spread is dampened by squad quality moving against the fixture. Projecting
        removes most of that quality term and leaves the opponent effect more exposed
        than it looked to begin with.

        Undefined without a raw effect to divide by, and reported as such.
        """

        if self.raw_spread == 0.0:
            return float("nan")
        return self.residual_spread / self.raw_spread


@dataclass(frozen=True, slots=True)
class OpponentStrengthSignalResult:
    """The measurement, both sides."""

    contract_version: str
    window: int
    seasons: tuple[str, ...]
    folds: int
    observations: int
    sides: tuple[SideSignal, ...]


def _monotone(values: Sequence[float]) -> bool:
    """Report whether the trend runs one way across every quartile.

    A spread without a trend is weaker evidence than the same spread with one: two noisy
    end quartiles can produce a gap that the middle contradicts.
    """

    decreasing = all(later <= earlier for earlier, later in pairwise(values))
    increasing = all(later >= earlier for earlier, later in pairwise(values))
    return decreasing or increasing


def _quartile_rows(frame: pd.DataFrame, strength_column: str) -> tuple[QuartileRow, ...]:
    labelled = frame.assign(
        quartile=pd.qcut(frame[strength_column], 4, labels=list(QUARTILE_LABELS))
    )
    rows: list[QuartileRow] = []
    for label in QUARTILE_LABELS:
        subset = labelled.loc[labelled["quartile"] == label]
        if subset.empty:
            continue
        rows.append(
            QuartileRow(
                quartile=label,
                observations=len(subset),
                mean_opponent_strength=float(subset[strength_column].mean()),
                mean_realized_points=float(subset["realized_points"].mean()),
                mean_residual=float(subset["residual"].mean()),
            )
        )
    return tuple(rows)


def measure_opponent_strength_signal(
    residuals: pd.DataFrame,
    panel: pd.DataFrame,
    fixtures: pd.DataFrame,
    team_codes: pd.DataFrame,
    *,
    window: int = 6,
) -> OpponentStrengthSignalResult:
    """Attach opponent strength to a residual population and report what survives.

    ``residuals`` is an ``oos_residual_export_v1`` table. Reusing that artifact rather than
    recomputing a projection is deliberate: the residuals being examined are then literally
    the ones the recalibration and gate work already consumed, so a finding here cannot be
    an artefact of a differently-built population.
    """

    for name, frame in (("residuals", residuals), ("panel", panel)):
        if not isinstance(frame, pd.DataFrame):
            raise BacktestConfigurationError(f"{name} must be a pandas DataFrame.")
    required = ("season", "gameweek", "player_id", "realized_points", "residual", "fold_id")
    missing = [column for column in required if column not in residuals.columns]
    if missing:
        raise BacktestConfigurationError(f"residuals is missing columns: {missing!r}.")

    enriched = attach_opponent_strength(panel, fixtures, team_codes, window=window)
    keys = ["season", "gameweek", "player_id"]
    joined = residuals.merge(
        enriched.loc[:, [*keys, "position", *OPPONENT_STRENGTH_COLUMNS]],
        on=keys,
        how="left",
        validate="one_to_one",
        suffixes=("", "_panel"),
    )

    sides: list[SideSignal] = []
    for side, positions, strength_column in SIDES:
        frame = joined.loc[
            joined["position"].isin(positions) & joined[strength_column].notna()
        ].copy(deep=True)
        if frame.empty:
            continue
        rows = _quartile_rows(frame, strength_column)
        if len(rows) < 2:
            continue
        realized = [row.mean_realized_points for row in rows]
        residual = [row.mean_residual for row in rows]
        sides.append(
            SideSignal(
                side=side,
                positions=tuple(positions),
                strength_column=strength_column,
                observations=len(frame),
                quartiles=rows,
                raw_spread=realized[0] - realized[-1],
                residual_spread=residual[0] - residual[-1],
                raw_monotone=_monotone(realized),
                residual_monotone=_monotone(residual),
            )
        )

    if not sides:
        raise BacktestConfigurationError("No comparable rows were produced.")

    return OpponentStrengthSignalResult(
        contract_version=OPPONENT_STRENGTH_SIGNAL_CONTRACT_VERSION,
        window=window,
        seasons=tuple(sorted({str(value) for value in residuals["season"]})),
        folds=int(residuals["fold_id"].nunique()),
        observations=len(joined),
        sides=tuple(sides),
    )


def signal_to_dict(result: OpponentStrengthSignalResult) -> dict[str, object]:
    """Render the measurement as a serialisable document."""

    return {
        "artifact_type": "opponent_strength_signal",
        "contract_version": result.contract_version,
        "strength_window": result.window,
        "seasons": list(result.seasons),
        "folds": result.folds,
        "observations": result.observations,
        "sides": [
            {
                "side": side.side,
                "positions": list(side.positions),
                "strength_column": side.strength_column,
                "observations": side.observations,
                "raw_spread": side.raw_spread,
                "residual_spread": side.residual_spread,
                "raw_monotone": side.raw_monotone,
                "residual_monotone": side.residual_monotone,
                "surviving_ratio": (
                    None if math.isnan(side.surviving_ratio) else side.surviving_ratio
                ),
                "quartiles": [
                    {
                        "quartile": row.quartile,
                        "observations": row.observations,
                        "mean_opponent_strength": row.mean_opponent_strength,
                        "mean_realized_points": row.mean_realized_points,
                        "mean_residual": row.mean_residual,
                    }
                    for row in side.quartiles
                ],
            }
            for side in result.sides
        ],
        "gate_evidence": False,
        "locked_holdout_accessed": False,
    }


def _side_table(side: SideSignal) -> list[str]:
    lines = [
        f"### {side.side.capitalize()} side — {', '.join(side.positions)} "
        f"against `{side.strength_column}`",
        "",
        "| Quartile | Rows | Mean opponent strength | Mean realized | Mean residual |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for row in side.quartiles:
        lines.append(
            f"| {row.quartile} | {row.observations:,} | {row.mean_opponent_strength:.4f} "
            f"| {row.mean_realized_points:.4f} | {row.mean_residual:+.4f} |"
        )
    surviving = side.surviving_ratio
    lines += [
        "",
        f"- Raw spread (Q1 minus Q4): **{side.raw_spread:+.4f}**"
        f"{', monotone' if side.raw_monotone else ', not monotone'}",
        f"- Residual spread (Q1 minus Q4): **{side.residual_spread:+.4f}**"
        f"{', monotone' if side.residual_monotone else ', not monotone'}",
        (
            "- Surviving ratio (residual / raw): "
            + ("undefined" if math.isnan(surviving) else f"**{surviving:.2f}x**")
        ),
        "",
    ]
    return lines


def signal_to_markdown(result: OpponentStrengthSignalResult) -> str:
    """Render the measurement as a report."""

    lines = [
        "# Opponent Strength — signal the control leaves on the table",
        "",
        f"- Contract: `{result.contract_version}`",
        f"- Strength window: {result.window} matches, shifted",
        f"- Population: {result.observations:,} rows over {result.folds} folds, "
        f"{', '.join(result.seasons)}",
        "",
        "The residual is what the operational control did not explain. If it moves with "
        "opponent strength, that is signal the control could have used and did not.",
        "",
    ]
    for side in result.sides:
        lines += _side_table(side)
    lines += [
        "## Limits",
        "",
        "This is not gate evidence and it is not a candidate. A prediction model that "
        "consumes opponent strength changes the expected-points rate and needs its own "
        "declaration, frozen fingerprints and a single run under the existing "
        "pre-registered conditions.",
        "",
        "Quartiles are a coarse instrument: they show whether a relationship exists and "
        "roughly how large, not the functional form a model would fit.",
        "",
        "The strength estimate is a proxy built from fantasy points split by unit, not a "
        "goal model, and it inherits every limitation `features.strength` names.",
    ]
    return "\n".join(lines) + "\n"
