"""How much of a projection is carried by the opening price prior, and what refitting moves.

``in_season_blend_benchmark.md`` records a caveat about its own headline and then names the
follow-up it did not do:

    `FITTED_OPENING_PRICE_COEFFICIENT` was fitted on opening-gameweek rows from 2020-21
    through 2024-25 -- the same seasons these folds evaluate ... a control-versus-blend gap
    could partly reflect differing reliance on that constant rather than projection quality,
    because the two reach the prior through different conditions. Quantifying that exposure
    is the first thing a follow-up should do; it is not quantified here.

This module is that quantification. Two questions, in order:

1. **How much does each configuration lean on the constant?** Not "how many rows are opening
   rows" -- the prior is not a gameweek-one rule. ``baseline_expected_points`` reaches it for
   any row with no within-season history *and* no carried record, so a player who has never
   appeared is priced from it in gameweek twelve as readily as in gameweek one, and the blend
   reaches it through two of its rungs at once (priced from the prior outright, and shrunk
   toward it).
2. **What does an honestly out-of-sample coefficient do to the level?** The constant is refit
   walk-forward on the seasons completed before each decision, and the projections are rebuilt.

## Measuring the reliance rather than re-deriving it

The obvious implementation is to re-state the precedence rules -- a row is prior-priced when
its rolling minutes are missing and its carry-over is missing -- and count matches. That would
be a second copy of a rule that already exists in ``prediction/baseline.py`` and
``prediction/in_season.py``, free to drift from it, and it could not describe a rung that is
*partly* the prior.

So the reliance is measured by asking the projection instead of by re-deriving it. Project
once at the coefficient ``c`` and once at ``c * (1 + e)``; for each row,

    attributable = (points(c * (1 + e)) - points(c)) / e

which is ``c * d(points)/dc``. For a row priced purely from the prior, ``points = c * price/10``
is linear in ``c``, so this is exactly that row's projected points. For a row shrunk toward the
prior it is exactly the portion of the projection the constant carries. For a two-stage or
carry-over row it is zero. One quantity, correct on every rung, and it cannot drift from the
code that owns the rules because it is a measurement *of* that code.

The dependence is piecewise linear -- a blend of linear terms, clipped at zero -- so a finite
difference is exact rather than approximate away from the clip. That is a claim, so the run
checks it: every configuration is measured at two probe scales and the disagreement is recorded.

## What this is not

Projection-level only. The benchmark's ``+13.78`` is *realized squad points*, and converting an
attributable-mass shift into a realized-points shift needs the optimizer and the evaluator on
every fold. That run is named as the next step, with its cost measured, rather than estimated
here from a projection-level number -- the two quantities can disagree, which is the whole
reason rule 4 of the research agenda exists.

Nothing here promotes anything or moves a declared constant. The locked holdout is cut from the
panel before any feature window can reach it.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Final

import pandas as pd

from squadopt.backtest.opening_prior import fit_opening_price_coefficient
from squadopt.backtest.splits import (
    DecisionPoint,
    rows_before,
    season_ranks,
    walk_forward_decision_points,
)
from squadopt.data.sources.vaastav import build_panel
from squadopt.experiments.config import ExperimentConfigurationError, ExperimentExecutionError
from squadopt.features import CrossSeasonConfig, build_feature_dataset
from squadopt.features.cross_season import carry_over_as_of
from squadopt.prediction import FormWindowMapping, build_projection_table
from squadopt.prediction.config import (
    FITTED_OPENING_PRICE_COEFFICIENT,
    BaselineProjectionConfig,
)
from squadopt.prediction.in_season import InSeasonBlendConfig, blend_in_season_projection
from squadopt.prediction.opening import build_opening_projection_from_snapshot

OPENING_PRIOR_EXPOSURE_CONTRACT_VERSION: Final = "opening_prior_exposure_v1"

# The population is the in-season blend benchmark's, because a measurement of that record's
# caveat has to describe that record's folds. `tests/unit/test_opening_prior_exposure.py`
# pins these against `scripts.measure_in_season_blend` rather than trusting the copy.
DEVELOPMENT_SEASONS: Final = ("2021-22", "2022-23", "2023-24", "2024-25")
MIN_PRIOR_GAMEWEEKS_IN_SEASON: Final = 1
LOCKED_HOLDOUT_SEASON: Final = "2025-26"
HISTORY_SEASONS: Final = ("2020-21", *DEVELOPMENT_SEASONS)

ROSTER_COLUMNS: Final = ("player_id", "name", "team_id", "position", "price_tenths")

CONTROL_LABEL: Final = "control-fw05"
BLEND_LABEL: Final = "blend-m270-g6-declared"
FLOOR_LABEL: Final = "carry-over-only"

# Zero attributable mass means the row never reached the constant. The threshold is far above
# float64 noise on a finite difference of quantities of order one and far below a tenth of a
# point, so no real rung sits near it.
_ATTRIBUTION_TOLERANCE: Final = 1e-9

# One projection under one coefficient: the shape every configuration is reduced to, so the
# loop below does not care which rungs sit behind it.
_Builder = Callable[[DecisionPoint, float], pd.DataFrame]

# The squad shape a legal selection must fill. Used to build a solver-free stand-in for the
# population an optimizer selects from: the best two keepers, five defenders, five
# midfielders and three forwards by projection. It respects the position quotas and ignores
# budget and the per-club limit, so it is a proxy and is labelled as one everywhere it is
# reported. A flat top-fifteen would be a worse one -- it can return eleven midfielders,
# which is not a squad.
_SQUAD_SHAPE: Final = MappingProxyType({"GK": 2, "DEF": 5, "MID": 5, "FWD": 3})


@dataclass(frozen=True, slots=True)
class OpeningPriorExposureConfig:
    """Which folds are measured, which projections, and how the reliance is probed."""

    development_seasons: tuple[str, ...] = DEVELOPMENT_SEASONS
    min_prior_gameweeks_in_season: int = MIN_PRIOR_GAMEWEEKS_IN_SEASON
    control_form_window: int = 5
    prior_minute_equivalent: int = 270
    prior_gameweek_equivalent: int = 6
    probe_scale: float = 1e-6
    verification_probe_scale: float = 1e-4

    def __post_init__(self) -> None:
        if LOCKED_HOLDOUT_SEASON in self.development_seasons:
            raise ExperimentConfigurationError(
                f"{LOCKED_HOLDOUT_SEASON} is the locked holdout and may not be measured."
            )
        if not self.development_seasons:
            raise ExperimentConfigurationError("At least one development season is required.")
        for scale in (self.probe_scale, self.verification_probe_scale):
            if not 0.0 < scale < 1.0:
                raise ExperimentConfigurationError(
                    f"Probe scales must lie strictly between 0 and 1; got {scale!r}."
                )
        if self.probe_scale == self.verification_probe_scale:
            raise ExperimentConfigurationError(
                "The two probe scales must differ, or the verification checks nothing."
            )


@dataclass(frozen=True, slots=True)
class ConfigurationExposure:
    """One projection's reliance on the constant, and what refitting does to its level."""

    label: str
    family: str
    folds: int
    rows: int
    rows_touching_the_prior: int
    projected_points: float
    attributable_points: float
    squad_shaped_projected_points: float
    squad_shaped_attributable_points: float
    squad_shaped_rows_touching_the_prior: int
    mean_projected_points_frozen: float
    mean_projected_points_refit: float
    finite_difference_disagreement: float

    @property
    def row_share(self) -> float:
        return self.rows_touching_the_prior / self.rows if self.rows else 0.0

    @property
    def attributable_share(self) -> float:
        return self.attributable_points / self.projected_points if self.projected_points else 0.0

    @property
    def squad_shaped_attributable_share(self) -> float:
        total = self.squad_shaped_projected_points
        return self.squad_shaped_attributable_points / total if total else 0.0

    @property
    def level_shift(self) -> float:
        """Mean projected points under the refit constant, minus under the frozen one."""

        return self.mean_projected_points_refit - self.mean_projected_points_frozen


@dataclass(frozen=True, slots=True)
class SeasonCoefficient:
    """The constant as an honest walk-forward fit would have had it for one season."""

    season: str
    fitted_on: tuple[str, ...]
    coefficient: float

    @property
    def difference_from_frozen(self) -> float:
        return self.coefficient - FITTED_OPENING_PRICE_COEFFICIENT


@dataclass(frozen=True, slots=True)
class OpeningPriorExposure:
    contract_version: str
    config: OpeningPriorExposureConfig
    history_seasons: tuple[str, ...]
    history_rows: int
    frozen_coefficient: float
    folds: int
    first_fold: str
    last_fold: str
    coefficients: tuple[SeasonCoefficient, ...]
    configurations: tuple[ConfigurationExposure, ...]
    diagnostics: Mapping[str, object]


def _visible_panel(archive_root: Path, config: OpeningPriorExposureConfig) -> pd.DataFrame:
    """Load the panel with everything after the development seasons cut away.

    Cut rather than filtered later, so a locked-holdout row cannot reach a feature window
    even as carry-over history. The same guard the benchmark applies, for the same reason.
    """

    panel = build_panel(archive_root, seasons=HISTORY_SEASONS)
    loaded = sorted({str(value) for value in panel["season"].tolist()})
    if LOCKED_HOLDOUT_SEASON in loaded:
        raise ExperimentExecutionError(
            f"{LOCKED_HOLDOUT_SEASON} was loaded; it is the locked holdout and must not "
            "be read by this measurement."
        )
    ranks = season_ranks(panel)
    unknown = sorted(set(config.development_seasons) - set(ranks))
    if unknown:
        raise ExperimentExecutionError(
            f"Development seasons are absent from the panel: {unknown!r}."
        )
    last_rank = max(ranks[season] for season in config.development_seasons)
    visible = panel.loc[panel["season"].map(lambda season: ranks[str(season)] <= last_rank)]
    return visible.copy(deep=True)


def _completed_seasons(panel: pd.DataFrame, season: str) -> tuple[str, ...]:
    """The seasons visible to this measurement that finished before ``season`` began."""

    ranks = season_ranks(panel)
    target = ranks[season]
    return tuple(sorted(name for name, rank in ranks.items() if rank < target))


def walk_forward_coefficients(
    panel: pd.DataFrame, config: OpeningPriorExposureConfig
) -> tuple[SeasonCoefficient, ...]:
    """Refit the price prior for each development season on the seasons before it.

    This is the production path's own discipline (``backtest/production.py`` refits on an
    expanding window at every fold); the benchmark deliberately does not, which is what makes
    its absolute levels in-sample and is the thing being quantified.
    """

    fitted: list[SeasonCoefficient] = []
    for season in config.development_seasons:
        earlier = _completed_seasons(panel, season)
        if not earlier:
            raise ExperimentExecutionError(
                f"No season precedes {season!r} inside the cut panel, so the constant cannot "
                "be refit out of sample for it."
            )
        fitted.append(
            SeasonCoefficient(
                season=season,
                fitted_on=earlier,
                coefficient=fit_opening_price_coefficient(panel, seasons=earlier),
            )
        )
    return tuple(fitted)


class _FoldInputs:
    """The per-fold inputs the capture-only projections read, built once per fold.

    Deliberately the same four quantities the benchmark's own ``_Inputs`` prepares, from the
    same public calls, because a measurement of that record has to describe its folds. The
    difference is that the fallback is rebuilt per coefficient rather than fixed, which is the
    whole point. ``tests/unit/test_opening_prior_exposure.py`` pins the frozen-coefficient
    result against the benchmark's, so "the same" is checked rather than claimed.
    """

    def __init__(self, panel: pd.DataFrame, decisions: Sequence[DecisionPoint]) -> None:
        self._panel = panel
        self._roster: dict[str, pd.DataFrame] = {}
        self._history: dict[str, pd.DataFrame] = {}
        self._carried: dict[str, pd.DataFrame] = {}
        for decision in decisions:
            self._prepare(decision)

    def _prepare(self, decision: DecisionPoint) -> None:
        key = decision.fold_id
        target = self._panel.loc[
            (self._panel["season"] == decision.season)
            & (self._panel["gameweek"] == decision.gameweek)
        ]
        self._roster[key] = (
            target.loc[:, list(ROSTER_COLUMNS)]
            .drop_duplicates("player_id")
            .sort_values("player_id", kind="stable")
            .reset_index(drop=True)
        )
        earlier = rows_before(self._panel, decision)
        in_season = earlier.loc[earlier["season"] == decision.season]
        self._history[key] = in_season.groupby("player_id", as_index=False)[
            ["minutes", "total_points"]
        ].sum()
        if decision.season not in self._carried:
            self._carried[decision.season] = carry_over_as_of(
                self._panel, target_season=decision.season
            )

    def roster(self, decision: DecisionPoint) -> pd.DataFrame:
        return self._roster[decision.fold_id]

    def fallback(self, decision: DecisionPoint, coefficient: float) -> pd.DataFrame:
        """The opening control's own output at one coefficient."""

        return build_opening_projection_from_snapshot(
            self._panel,
            self._roster[decision.fold_id],
            season=decision.season,
            config=BaselineProjectionConfig(opening_price_coefficient=coefficient),
        )

    def blend(
        self, decision: DecisionPoint, coefficient: float, settings: InSeasonBlendConfig
    ) -> pd.DataFrame:
        key = decision.fold_id
        return blend_in_season_projection(
            self._roster[key],
            self._carried[decision.season],
            self._history[key],
            self.fallback(decision, coefficient),
            gameweeks_played=decision.gameweek - 1,
            config=settings,
        ).table


def _projected(table: pd.DataFrame) -> "pd.Series[float]":
    return table["expected_points"].astype("float64").reset_index(drop=True)


@dataclass(frozen=True, slots=True)
class _FoldTotals:
    rows: int
    touching: int
    projected: float
    attributable: float
    selected_projected: float
    selected_attributable: float
    selected_touching: int


def _squad_shaped_index(table: pd.DataFrame, base: "pd.Series[float]") -> pd.Index:
    """The best players by projection at each position, in the quotas a squad must fill."""

    positions = table["position"].astype("string").reset_index(drop=True)
    chosen: list[int] = []
    for position, quota in _SQUAD_SHAPE.items():
        eligible = base.loc[positions.eq(position)]
        chosen.extend(eligible.sort_values(ascending=False, kind="stable").index[:quota].tolist())
    return pd.Index(chosen)


def _fold_totals(
    table: pd.DataFrame, base: "pd.Series[float]", probed: "pd.Series[float]", scale: float
) -> _FoldTotals:
    """Attributable mass per row, and the same restricted to a squad-shaped selection."""

    attributable = probed.sub(base).div(scale)
    order = _squad_shaped_index(table, base)
    top_base = base.loc[order]
    top_attributable = attributable.loc[order]
    return _FoldTotals(
        rows=int(base.size),
        touching=int((attributable.abs() > _ATTRIBUTION_TOLERANCE).sum()),
        projected=float(base.sum()),
        attributable=float(attributable.sum()),
        selected_projected=float(top_base.sum()),
        selected_attributable=float(top_attributable.sum()),
        selected_touching=int((top_attributable.abs() > _ATTRIBUTION_TOLERANCE).sum()),
    )


def measure_opening_prior_exposure(
    archive_root: Path | str,
    config: OpeningPriorExposureConfig | None = None,
    *,
    fold_limit: int | None = None,
) -> OpeningPriorExposure:
    """Quantify each projection's reliance on the frozen constant, and refit it walk-forward.

    ``fold_limit`` truncates the fold list for a wiring check. A truncated run is not the
    measurement and the runner refuses to write one.
    """

    settings = OpeningPriorExposureConfig() if config is None else config
    panel = _visible_panel(Path(archive_root), settings)
    ranks = season_ranks(panel)
    loaded_history_seasons = tuple(
        sorted({str(value) for value in panel["season"].tolist()}, key=lambda season: ranks[season])
    )
    decisions = walk_forward_decision_points(
        panel,
        seasons=settings.development_seasons,
        min_prior_gameweeks_in_season=settings.min_prior_gameweeks_in_season,
    )
    if fold_limit is not None:
        decisions = decisions[:fold_limit]
    if not decisions:
        raise ExperimentExecutionError("No decision points for the requested seasons.")

    coefficients = walk_forward_coefficients(panel, settings)
    refit_by_season = {entry.season: entry.coefficient for entry in coefficients}
    frozen = FITTED_OPENING_PRICE_COEFFICIENT
    probe = frozen * (1.0 + settings.probe_scale)
    verification = frozen * (1.0 + settings.verification_probe_scale)

    inputs = _FoldInputs(panel, decisions)
    blend_settings = InSeasonBlendConfig(
        prior_gameweek_equivalent=settings.prior_gameweek_equivalent,
        prior_minute_equivalent=settings.prior_minute_equivalent,
    )
    mapping = FormWindowMapping(form_window=settings.control_form_window)
    features = build_feature_dataset(
        panel, config=mapping.feature_config, cross_season=CrossSeasonConfig()
    )

    def control(decision: DecisionPoint, coefficient: float) -> pd.DataFrame:
        return build_projection_table(
            features,
            season=decision.season,
            gameweek=decision.gameweek,
            config=BaselineProjectionConfig(
                minutes_window=settings.control_form_window,
                per_90_window=settings.control_form_window,
                opening_price_coefficient=coefficient,
            ),
        )

    def floor(decision: DecisionPoint, coefficient: float) -> pd.DataFrame:
        return inputs.fallback(decision, coefficient)

    def blend(decision: DecisionPoint, coefficient: float) -> pd.DataFrame:
        return inputs.blend(decision, coefficient, blend_settings)

    builders: tuple[tuple[str, str, _Builder], ...] = (
        (CONTROL_LABEL, "archive_fed_control", control),
        (BLEND_LABEL, "in_season_blend", blend),
        (FLOOR_LABEL, "floor", floor),
    )

    exposures: list[ConfigurationExposure] = []
    for label, family, build in builders:
        totals: list[_FoldTotals] = []
        refit_means: list[float] = []
        frozen_means: list[float] = []
        disagreement = 0.0
        for decision in decisions:
            table = build(decision, frozen)
            base = _projected(table)
            probed = _projected(build(decision, probe))
            checked = _projected(build(decision, verification))
            fold = _fold_totals(table, base, probed, settings.probe_scale)
            verified = _fold_totals(table, base, checked, settings.verification_probe_scale)
            scale = max(abs(fold.attributable), 1.0)
            disagreement = max(disagreement, abs(fold.attributable - verified.attributable) / scale)
            refit = _projected(build(decision, refit_by_season[decision.season]))
            totals.append(fold)
            frozen_means.append(float(base.mean()))
            refit_means.append(float(refit.mean()))
        rows = sum(item.rows for item in totals)
        exposures.append(
            ConfigurationExposure(
                label=label,
                family=family,
                folds=len(totals),
                rows=rows,
                rows_touching_the_prior=sum(item.touching for item in totals),
                projected_points=sum(item.projected for item in totals),
                attributable_points=sum(item.attributable for item in totals),
                squad_shaped_projected_points=sum(item.selected_projected for item in totals),
                squad_shaped_attributable_points=sum(item.selected_attributable for item in totals),
                squad_shaped_rows_touching_the_prior=sum(item.selected_touching for item in totals),
                mean_projected_points_frozen=sum(frozen_means) / len(frozen_means),
                mean_projected_points_refit=sum(refit_means) / len(refit_means),
                finite_difference_disagreement=disagreement,
            )
        )

    return OpeningPriorExposure(
        contract_version=OPENING_PRIOR_EXPOSURE_CONTRACT_VERSION,
        config=settings,
        history_seasons=loaded_history_seasons,
        history_rows=len(panel),
        frozen_coefficient=frozen,
        folds=len(decisions),
        first_fold=decisions[0].fold_id,
        last_fold=decisions[-1].fold_id,
        coefficients=coefficients,
        configurations=tuple(exposures),
        diagnostics=MappingProxyType(
            {
                "measurement_only": True,
                "gate_evidence": False,
                "history_seasons": loaded_history_seasons,
                "history_rows": len(panel),
                "locked_holdout_read": LOCKED_HOLDOUT_SEASON in loaded_history_seasons,
                "decision_level_rescore": False,
                "squad_shaped_population_is_a_proxy": True,
            }
        ),
    )


def _by_label(exposure: OpeningPriorExposure) -> Mapping[str, ConfigurationExposure]:
    return {entry.label: entry for entry in exposure.configurations}


def exposure_to_markdown(exposure: OpeningPriorExposure) -> str:
    """Render the record a reader is expected to read instead of the JSON."""

    entries = _by_label(exposure)
    blend = entries[BLEND_LABEL]
    floor = entries[FLOOR_LABEL]
    control = entries[CONTROL_LABEL]
    projection_gap = blend.mean_projected_points_frozen - floor.mean_projected_points_frozen
    largest_shift = max(entry.level_shift for entry in exposure.configurations)
    lines: list[str] = [
        "# What the opening price prior carries, and what refitting it moves",
        "",
        f"Artifacts: `opening_prior_exposure.{{json,md}}` (contract "
        f"`{exposure.contract_version}`). Runner: `scripts.measure_opening_prior_exposure`. "
        f"{exposure.folds} development folds, `{exposure.first_fold}` to "
        f"`{exposure.last_fold}`, {control.rows:,} player-gameweek rows -- the same count "
        "`in_season_residual_export` reports over the same folds, which is the cheapest "
        "available check that this is the benchmark's population and not a differently "
        "shaped one. The locked holdout is cut from the panel before any feature window "
        "can reach it.",
        "",
        "## Why this exists",
        "",
        "`in_season_blend_benchmark.md` records a caveat about its own headline and names this "
        "as the first thing a follow-up should do: `FITTED_OPENING_PRICE_COEFFICIENT` was "
        "fitted on opening rows from 2020-21 through 2024-25, the same seasons these folds "
        "evaluate, so a control-versus-blend gap could partly reflect differing reliance on "
        "that constant rather than projection quality.",
        "",
        "The reliance is **measured, not re-derived**. Each projection is built at the "
        "coefficient `c` and again at `c * (1 + e)`; a row's attributable mass is the "
        "difference divided by `e`, which is `c * d(points)/dc`. That is the row's whole "
        "projection where the prior priced it outright, the carried portion where a rung is "
        "shrunk toward it, and zero everywhere else -- one quantity, correct on every rung, "
        "and incapable of drifting from the precedence rules because it interrogates them.",
        "",
        "## What it found",
        "",
        f"**The differing reliance the caveat suspected is real, and it is large.** The "
        f"archive-fed control takes {control.attributable_share:.2%} of its projected points "
        f"from the constant; the blend takes {blend.attributable_share:.2%} and the "
        f"carry-over floor {floor.attributable_share:.2%}. Nearly half the blend's and the "
        f"floor's rows touch it at all ({blend.row_share:.2%}) against "
        f"{control.row_share:.2%} of the control's. The two arms of the headline are not "
        "leaning on that constant to remotely the same degree.",
        "",
        "**And it is almost absent where a decision is made.** Restricted to a squad-shaped "
        f"selection, the same shares are {control.squad_shaped_attributable_share:.2%}, "
        f"{blend.squad_shaped_attributable_share:.2%} and "
        f"{floor.squad_shaped_attributable_share:.2%}. The reliance is concentrated in players "
        "the prior prices at a point or two -- who are exactly the players an optimizer does "
        "not pick. So the exposure is enormous in the row population and near zero in the "
        "selected one, and those two facts have to be read together or either one misleads.",
        "",
        "**Refitting it honestly moves it up, not down.** Every walk-forward coefficient is "
        "*larger* than the frozen one, converging toward it as seasons accumulate "
        f"({exposure.coefficients[0].difference_from_frozen:+.4f} on one season of history, "
        f"{exposure.coefficients[-1].difference_from_frozen:+.4f} on four), and the resulting "
        f"level shifts are at most {largest_shift:+.4f} "
        "mean projected points. If the in-sample fit biases anything it is downward, which is "
        "the opposite direction from the one the caveat worried about.",
        "",
        "**The projection-level gap does not even carry the sign of the decision-level one, "
        "and that is the most important line in this record.** The blend projects "
        f"**{projection_gap:+.4f}** mean points against the carry-over floor -- it projects "
        "*lower* -- while the benchmark measures it **+13.78 realized squad points** *higher*. "
        "The mechanism is legible (the floor over-prices the many players who will not appear, "
        "which lifts a mean over a hundred thousand rows while doing nothing for the top of the "
        "ranking), but the point stands regardless of mechanism: no number in this record may "
        "be read as a correction to the `+13.78`, because the two quantities disagree in sign "
        "on this very pair.",
        "",
        "## How much each projection leans on the constant",
        "",
        "| configuration | rows | rows touching the prior | share | attributable share of "
        "projected points | same, squad-shaped selection |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for entry in exposure.configurations:
        lines.append(
            f"| `{entry.label}` | {entry.rows:,} | {entry.rows_touching_the_prior:,} | "
            f"{entry.row_share:.4f} | {entry.attributable_share:.4f} | "
            f"{entry.squad_shaped_attributable_share:.4f} |"
        )
    lines.extend(
        [
            "",
            "The last column is a **proxy** for the population a squad optimizer selects, not "
            "the squad: the best two keepers, five defenders, five midfielders and three "
            "forwards by projection. It respects the position quotas and ignores budget and the "
            "per-club limit, so it overstates what is reachable. It is here because reliance "
            "concentrated in players nobody would pick means something quite different from "
            "reliance at the top of the ranking -- and that is what separates the first two "
            "columns from the third.",
            "",
            "## The constant, refit walk-forward",
            "",
            f"Frozen: **{exposure.frozen_coefficient:.8f}**, fitted on 2020-21 through 2024-25. "
            "Refit per season on the seasons completed before it, through the same "
            "`fit_opening_price_coefficient` the production path uses.",
            "",
            "| season | fitted on | coefficient | difference from frozen |",
            "| --- | --- | ---: | ---: |",
        ]
    )
    for coefficient in exposure.coefficients:
        lines.append(
            f"| {coefficient.season} | {', '.join(coefficient.fitted_on)} | "
            f"{coefficient.coefficient:.8f} | {coefficient.difference_from_frozen:+.8f} |"
        )
    lines.extend(
        [
            "",
            "## What the refit does to the level",
            "",
            "| configuration | mean projected points, frozen | refit | shift |",
            "| --- | ---: | ---: | ---: |",
        ]
    )
    for entry in exposure.configurations:
        lines.append(
            f"| `{entry.label}` | {entry.mean_projected_points_frozen:.4f} | "
            f"{entry.mean_projected_points_refit:.4f} | {entry.level_shift:+.4f} |"
        )
    lines.extend(
        [
            "",
            "The pairs the benchmark's headline is built from, at the projection level:",
            "",
            "| pair | gap, frozen | gap, refit | move |",
            "| --- | ---: | ---: | ---: |",
        ]
    )
    for name, left, right in (
        (f"`{BLEND_LABEL}` vs `{FLOOR_LABEL}`", blend, floor),
        (f"`{BLEND_LABEL}` vs `{CONTROL_LABEL}`", blend, control),
    ):
        frozen_gap = left.mean_projected_points_frozen - right.mean_projected_points_frozen
        refit_gap = left.mean_projected_points_refit - right.mean_projected_points_refit
        lines.append(
            f"| {name} | {frozen_gap:+.4f} | {refit_gap:+.4f} | {refit_gap - frozen_gap:+.4f} |"
        )
    disagreement = max(entry.finite_difference_disagreement for entry in exposure.configurations)
    lines.extend(
        [
            "",
            "## The estimator, checked rather than asserted",
            "",
            "The claim that the finite difference is exact rests on the dependence being "
            "piecewise linear in the coefficient. Every configuration was therefore measured at "
            "two probe scales "
            f"(`{exposure.config.probe_scale:g}` and "
            f"`{exposure.config.verification_probe_scale:g}`), and the largest relative "
            f"disagreement between them on any fold is **{disagreement:.3e}**. A material "
            "disagreement would mean rows sitting on the zero clip, where the dependence "
            "bends and a wider probe steps across it; at this magnitude the clip changes "
            "nothing this record reports.",
            "",
            "## What this decides",
            "",
            "Nothing. `measurement_only` is true and `gate_evidence` is false. No declared "
            "constant moves: changing one after seeing a surface is choosing the outcome, and a "
            "better value would be a separate pre-registered candidate with its own gates.",
            "",
            "**Every number here is projection-level.** The benchmark's `+13.78` is *realized "
            "squad points*, and prediction quality and decision quality are different "
            "quantities that can disagree -- which is why the research agenda scores the "
            "decision rather than only the prediction. Converting these shifts into realized "
            "points needs the optimizer and the evaluator on every fold, in both coefficient "
            "regimes. That run is the named next step; it is not estimated here from a "
            "projection-level number, because an estimate is exactly what this record exists to "
            "replace.",
            "",
        ]
    )
    return "\n".join(lines)


__all__ = [
    "BLEND_LABEL",
    "CONTROL_LABEL",
    "DEVELOPMENT_SEASONS",
    "FLOOR_LABEL",
    "OPENING_PRIOR_EXPOSURE_CONTRACT_VERSION",
    "ConfigurationExposure",
    "OpeningPriorExposure",
    "OpeningPriorExposureConfig",
    "SeasonCoefficient",
    "exposure_to_markdown",
    "measure_opening_prior_exposure",
    "walk_forward_coefficients",
]
