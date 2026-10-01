"""Shared match-world evaluation across complete three/five-week candidate plans.

This consumer needs explicit player-fixture components. It never reconstructs goals,
assists or clean sheets from weekly point totals, and never fits or fetches a model.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import pandas as pd

from squadopt.application.football_candidate import freeze_planning_week
from squadopt.planning import ProjectionHorizon, TransferPlanResult
from squadopt.scenarios.football import sample_football_events, score_football_candidates
from squadopt.scenarios.football_diagnostics import football_mean_diagnostics


@dataclass(frozen=True)
class FootballWindowReview:
    weekly_scores: pd.DataFrame
    window_scores: pd.DataFrame
    component_diagnostics: Mapping[int, Mapping[str, float]]
    samples: int
    seed: int
    contract_version: str = "shared_football_window_review_v1"
    assumption: str = (
        "Independent match draws across weeks; fixed plans, no future-score knowledge."
    )


def review_football_window(
    components: pd.DataFrame,
    horizon: ProjectionHorizon,
    plans: Mapping[str, TransferPlanResult],
    *,
    samples: int = 64,
    seed: int = 0,
    coherent_lineups: bool = False,
) -> FootballWindowReview:
    """Official substitutions/captain/chips/hits on common worlds for every plan.

    This diagnostic does not select the best sample and call it validated improvement.
    Analytic/sampled mean gaps remain visible. Empty weeks require explicit fixture_count0.
    """
    if isinstance(samples, bool) or not isinstance(samples, int) or not 2 <= samples <= 256:
        raise ValueError("Window review uses between two and256 shared worlds.")
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise ValueError("A nonnegative integer seed is required.")
    weeks = horizon.target_gameweeks
    if len(weeks) not in (3, 5) or not plans:
        raise ValueError("Complete three/five-week plans are required.")
    for plan in plans.values():
        if not plan.has_solution or tuple(w.gameweek for w in plan.weeks) != weeks:
            raise ValueError("Every plan must cover exactly the same window.")
    if not components.empty and (
        set(components.season) != {horizon.season} or not set(components.GW).issubset(weeks)
    ):
        raise ValueError("Components belong to another season or window.")
    frames = []
    diagnostics = {}
    for index, week in enumerate(weeks):
        table = horizon.table.loc[horizon.table.gameweek.eq(week)]
        current = components.loc[components.GW.eq(week)] if not components.empty else components
        counts = (
            current.groupby("player_code").fixture.nunique()
            if not current.empty
            else pd.Series(dtype="int64")
        )
        expected = table.set_index("player_id").fixture_count
        if (
            set(counts.index) - set(expected.index)
            or not counts.reindex(expected.index, fill_value=0).eq(expected).all()
        ):
            raise ValueError(
                "Components must cover every scheduled player-fixture, including doubles."
            )
        selected = {name: plan.weeks[index] for name, plan in plans.items()}
        if current.empty:
            scored = pd.DataFrame(
                [
                    {
                        "scenario_id": scenario,
                        "candidate": name,
                        "net_points": -w.transfer_hit_points,
                    }
                    for scenario in range(samples)
                    for name, w in selected.items()
                ]
            )
            diagnostics[week] = {"draws": float(samples), "player_fixtures": 0.0}
        else:
            draws = sample_football_events(
                current, samples=samples, seed=seed + week, coherent_lineups=coherent_lineups
            )
            diagnostics[week] = football_mean_diagnostics(current, draws)
            scored = score_football_candidates(
                draws,
                {name: freeze_planning_week(w) for name, w in selected.items()},
                hits={name: w.transfer_hit_points for name, w in selected.items()},
                chips={name: w.chip for name, w in selected.items()},
                blank_player_ids=frozenset(expected.index[expected.eq(0)]),
            )
        frames.append(scored.assign(gameweek=week))
    weekly = pd.concat(frames, ignore_index=True)
    totals = weekly.groupby(["scenario_id", "candidate"], as_index=False)[["net_points"]].sum()
    return FootballWindowReview(weekly, totals, diagnostics, samples, seed)
