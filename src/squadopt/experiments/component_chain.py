"""The Phase C component base as a season chain's decision-week forecast.

`docs/phase_c_component_evaluation.json` scores the component base on single decisions: one
squad a fold, each solved from nothing. The season chain asks what a planner control is worth
over a carried squad, and until now it could only be walked on the form-window control. This
module composes the component base's per-fold projection exactly as its evaluation record
does and hands each development season to the chain as a `DecisionWeekProjections`, so a
chain measurement can be read on the forecast that decides the served squads.

Nothing is fitted or changed here. The frozen v1 reader verifies the handoff's digests, schema
and chronology and refuses any trace of the locked season; the ridge control folds are built
on the same panel and supply the projection of the handoff's direct-control rows.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Final

import pandas as pd

from squadopt.backtest import build_walk_forward_folds, make_ridge_projection_builder
from squadopt.evaluation import prepare_phase_c_component_folds, read_phase_c_component_handoff
from squadopt.evaluation.promotion import ExperimentConfigurationError, ExperimentExecutionError
from squadopt.experiments.multi_gw_rehearsal import DecisionWeekProjections
from squadopt.experiments.season_chain_runs import (
    DEFAULT_DEVELOPMENT_SEASONS,
    LOCKED_HOLDOUT_SEASON,
)
from squadopt.features import CrossSeasonConfig

HANDOFF_TABLE: Final = "phase_c_component_oof_v1.csv"
HANDOFF_ROSTER: Final = "phase_c_component_oof_v1.roster.csv"
HANDOFF_MANIFEST: Final = "phase_c_component_oof_v1.manifest.json"


@dataclass(frozen=True, slots=True)
class ComponentChainInputs:
    """Each season's component forecast for the chain, with the handoff's identity."""

    projections: Mapping[str, DecisionWeekProjections]
    table_sha256: str
    roster_sha256: str
    manifest_sha256: str
    model_version: str
    producer_repository_commit: str
    folds: int
    direct_control_rows: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "projections", MappingProxyType(dict(self.projections)))

    def identity(self) -> dict[str, object]:
        """The handoff's digests and counts, as a record states them."""

        return {
            "table_sha256": self.table_sha256,
            "roster_sha256": self.roster_sha256,
            "manifest_sha256": self.manifest_sha256,
            "model_version": self.model_version,
            "producer_repository_commit": self.producer_repository_commit,
            "folds": self.folds,
            "direct_control_rows": self.direct_control_rows,
            "decision_gameweeks": {
                season: sorted(item.tables) for season, item in sorted(self.projections.items())
            },
        }


def load_component_chain_inputs(
    handoff_dir: Path,
    panel: pd.DataFrame,
    *,
    seasons: Sequence[str] = DEFAULT_DEVELOPMENT_SEASONS,
) -> ComponentChainInputs:
    """Compose the component base's projection for every decision of ``seasons``.

    ``seasons`` must be the handoff's own seasons in order: the composition takes the
    control fold of every handoff fold, so a subset cannot be prepared on its own. The
    locked season is refused before a file is opened.
    """

    development = tuple(str(season) for season in seasons)
    if not development or len(set(development)) != len(development):
        raise ExperimentConfigurationError("seasons must name each development season once.")
    if LOCKED_HOLDOUT_SEASON in development:
        raise ExperimentConfigurationError(
            f"{LOCKED_HOLDOUT_SEASON} is the locked holdout; the frozen component handoff "
            "holds no forecast for it and none is composed."
        )
    root = Path(handoff_dir)
    handoff = read_phase_c_component_handoff(
        root / HANDOFF_TABLE, root / HANDOFF_ROSTER, root / HANDOFF_MANIFEST
    )
    held = tuple(dict.fromkeys(str(season) for season in handoff.rows["season"].tolist()))
    if held != development:
        raise ExperimentExecutionError(
            f"The component handoff holds seasons {held!r}, not the requested {development!r}."
        )
    controls = build_walk_forward_folds(
        panel,
        seasons=development,
        projection_builder=make_ridge_projection_builder(cross_season=CrossSeasonConfig()),
    )
    folds = prepare_phase_c_component_folds(handoff, controls)
    tables: dict[str, dict[int, pd.DataFrame]] = {season: {} for season in development}
    direct_control_rows = 0
    for fold in folds:
        season = str(fold.metadata["season"])
        gameweek = int(str(fold.metadata["gameweek"]))
        if gameweek in tables[season]:
            raise ExperimentExecutionError(
                f"The component handoff holds two folds for gameweek {gameweek} of {season}."
            )
        tables[season][gameweek] = fold.projections
        direct_control_rows += int(str(fold.metadata["direct_control_rows"]))
    return ComponentChainInputs(
        projections={
            season: DecisionWeekProjections(model_version=handoff.model_version, tables=by_week)
            for season, by_week in tables.items()
        },
        table_sha256=handoff.table_sha256,
        roster_sha256=handoff.roster_sha256,
        manifest_sha256=handoff.manifest_sha256,
        model_version=handoff.model_version,
        producer_repository_commit=handoff.repository_commit,
        folds=len(folds),
        direct_control_rows=direct_control_rows,
    )
