"""Shared match-score football draws, separate from calibrated residual scenarios.

This candidate couples goals, credited scorers, distinct assisters and clean sheets.
The default v1 retains independent player minutes and full-match CS. The explicit
contextual mode conditions on a legal XI and paired changes, shares uncertain scoring
intensities, and grants CS using opponent events during the player's active interval.
Its constrained lineup law is a working approximation, not a fitted substitution hazard.
Residual expectation is retained; it is not a calibrated bonus/card event generator.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np
import pandas as pd

from squadopt.evaluation.models import FrozenSquadDecision
from squadopt.evaluation.scoring import score_frozen_squad_decision
from squadopt.scenarios.football_lineups import sample_intervals


@dataclass(frozen=True)
class FootballDraws:
    outcomes: pd.DataFrame
    match_scores: pd.DataFrame
    seed: int
    contract_version: str = "shared_football_score_candidate_v1"


def sample_football_events(
    components: pd.DataFrame, *, samples: int, seed: int, coherent_lineups: bool = False
) -> FootballDraws:
    """Draw identical worlds for all candidate decisions; never resample per squad."""
    if isinstance(samples, bool) or not isinstance(samples, int) or not 1 <= samples <= 10000:
        raise ValueError("samples must be an integer between1 and10000.")
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise ValueError("seed must be a nonnegative integer.")
    if components.empty or components.duplicated(["fixture", "player_code"]).any():
        raise ValueError("Nonempty unique player-fixture components are required.")
    if components.season.nunique() != 1 or components.GW.nunique() != 1:
        raise ValueError("Draw one season/gameweek at a time, including all its fixtures.")
    if not components.position.isin(("GK", "DEF", "MID", "FWD")).all():
        raise ValueError("Unknown football position.")
    nonnegative = components[
        ["goals", "assists", "goals_share", "assists_share", "expected_minutes"]
    ].to_numpy(dtype=float)
    if (
        not np.isfinite(nonnegative).all()
        or (nonnegative < 0).any()
        or not np.isfinite(components.residual_if_appearance).all()
    ):
        raise ValueError(
            "Football event weights and residuals must be finite; weights nonnegative."
        )
    season = str(components.season.iloc[0])
    frame = components.sort_values(["fixture", "club", "player_code"], kind="stable")
    rng = np.random.default_rng(seed)
    records: list[dict[str, object]] = []
    scores: list[dict[str, object]] = []
    for fixture, match in frame.groupby("fixture", sort=True):
        clubs = list(match.sort_values("home", ascending=False).club.unique())
        if len(clubs) != 2:
            raise ValueError("Joint score simulation needs both fixture sides.")
        groups = [match.loc[match.club.eq(club)].reset_index(drop=True) for club in clubs]
        if not groups[0].home.eq(1).all() or not groups[1].home.eq(0).all():
            raise ValueError("One home and one away side are required.")
        for i, group in enumerate(groups):
            if not group.opponent.eq(clubs[1 - i]).all():
                raise ValueError("Fixture opponents are inconsistent.")
            if not np.allclose(group.team_goal_rate, group.team_goal_rate.iloc[0]):
                raise ValueError("One team cannot have multiple match goal rates.")
            if not np.allclose(group.opponent_goal_rate, groups[1 - i].team_goal_rate.iloc[0]):
                raise ValueError("Opposing goal intensities are inconsistent.")
        lambdas = np.array([g.team_goal_rate.iloc[0] for g in groups], dtype=float)
        if not np.isfinite(lambdas).all() or (lambdas < 0).any():
            raise ValueError("Match goal rates must be finite and nonnegative.")
        if coherent_lineups:
            variances = np.array([g.team_goal_variance.iloc[0] for g in groups], dtype=float)
            if not np.isfinite(variances).all() or (variances <= 0).any() or (lambdas <= 0).any():
                raise ValueError("Contextual intensity moments must be positive and finite.")
            for side, group in enumerate(groups):
                if not np.allclose(group.team_goal_variance, variances[side]) or not np.allclose(
                    group.opponent_goal_variance, variances[1 - side]
                ):
                    raise ValueError("Opposing intensity variances are inconsistent.")
            intensity = rng.gamma(lambdas**2 / variances, variances / lambdas, size=(samples, 2))
            goal_draws = rng.poisson(intensity)
        else:
            goal_draws = rng.poisson(lambdas, size=(samples, 2))
        for sample in range(samples):
            event_times = (
                [rng.uniform(0, 90, size=int(count)) for count in goal_draws[sample]]
                if coherent_lineups
                else []
            )
            scores.append(
                {
                    "scenario_id": sample,
                    "fixture": fixture,
                    "home_club": clubs[0],
                    "away_club": clubs[1],
                    "home_goals": int(goal_draws[sample, 0]),
                    "away_goals": int(goal_draws[sample, 1]),
                }
            )
            for side, group in enumerate(groups):
                probabilities = group[[f"minute_probability_{b}" for b in range(4)]].to_numpy(
                    dtype=float
                )
                if (
                    not np.isfinite(probabilities).all()
                    or (probabilities < 0).any()
                    or not np.allclose(probabilities.sum(axis=1), 1)
                ):
                    raise ValueError("Minute probabilities must be finite and sum to one.")
                bins = np.array([rng.choice(4, p=p) for p in probabilities])
                minute_values = group[[f"minute_value_{b}" for b in range(4)]].to_numpy(dtype=float)
                if (
                    not np.isfinite(minute_values).all()
                    or (minute_values < 0).any()
                    or (minute_values > 120).any()
                ):
                    raise ValueError("Invalid minute support.")
                minutes = np.rint(minute_values[np.arange(len(group)), bins]).astype(int)
                entry, exit_time = np.zeros(len(group)), minutes.astype(float)
                if coherent_lineups:
                    entry, exit_time = sample_intervals(group, rng)
                    minutes = (exit_time - entry).astype(int)
                goals = np.zeros(len(group), dtype=int)
                assists = np.zeros(len(group), dtype=int)
                available = minutes > 0
                expected_minutes = group.expected_minutes.to_numpy(dtype=float)
                exposure = np.divide(
                    minutes, expected_minutes, out=np.zeros(len(group)), where=expected_minutes > 0
                )
                gw = group.goals_share.to_numpy(dtype=float) * exposure
                aw = group.assists_share.to_numpy(dtype=float) * exposure
                goal_mass = float(group.goals.sum())
                credit = min(1.0, goal_mass / lambdas[side]) if lambdas[side] > 0 else 0.0
                assist_fraction = (
                    min(1.0, float(group.assists.sum()) / goal_mass) if goal_mass > 0 else 0.0
                )
                for event in range(int(goal_draws[sample, side])):
                    if coherent_lineups:
                        time = event_times[side][event]
                        active = (entry <= time) & (time < exit_time)
                        goal_weight = (
                            np.divide(
                                group.goals_share.to_numpy(float),
                                expected_minutes,
                                out=np.zeros(len(group)),
                                where=expected_minutes > 0,
                            )
                            * active
                        )
                        assist_base = (
                            np.divide(
                                group.assists_share.to_numpy(float),
                                expected_minutes,
                                out=np.zeros(len(group)),
                                where=expected_minutes > 0,
                            )
                            * active
                        )
                    else:
                        goal_weight, assist_base = gw, aw
                    if goal_weight.sum() <= 0 or rng.random() >= credit:
                        continue  # uncredited/own goal, never assigned to an absent player
                    scorer = int(rng.choice(len(group), p=goal_weight / goal_weight.sum()))
                    goals[scorer] += 1
                    assist_weight = assist_base.copy()
                    assist_weight[scorer] = 0
                    if assist_weight.sum() > 0 and rng.random() < assist_fraction:
                        assister = int(
                            rng.choice(len(group), p=assist_weight / assist_weight.sum())
                        )
                        assists[assister] += 1
                rate = group.defcon_rate90.to_numpy(dtype=float) * minutes / 90
                kappa = group.defcon_dispersion.to_numpy(dtype=float)
                if (
                    not np.isfinite(rate).all()
                    or not np.isfinite(kappa).all()
                    or (rate < 0).any()
                    or (kappa <= 0).any()
                ):
                    raise ValueError("Invalid defensive-contribution count distribution.")
                actions = rng.negative_binomial(kappa, kappa / (kappa + rate))
                dc = actions >= np.where(group.position.eq("DEF"), 10, 12)
                dc[group.position.eq("GK")] = False
                cs = (minutes >= 60) & (goal_draws[sample, 1 - side] == 0)
                if coherent_lineups:
                    conceded = np.array(
                        [
                            (
                                (event_times[1 - side] >= entered) & (event_times[1 - side] < left)
                            ).sum()
                            for entered, left in zip(entry, exit_time, strict=True)
                        ]
                    )
                    cs = (minutes >= 60) & (conceded == 0)
                goal_coeff = group.position.map(
                    {"GK": 10 if season >= "2024-25" else 6, "DEF": 6, "MID": 5, "FWD": 4}
                ).to_numpy()
                cs_coeff = group.position.map({"GK": 4, "DEF": 4, "MID": 1, "FWD": 0}).to_numpy()
                points = (
                    available.astype(float)
                    + (minutes >= 60)
                    + goal_coeff * goals
                    + 3 * assists
                    + cs_coeff * cs
                )
                points += (
                    2 * dc if season >= "2025-26" else 0
                ) + available * group.residual_if_appearance.to_numpy(dtype=float)
                for index, (_, row) in enumerate(group.iterrows()):
                    records.append(
                        {
                            "scenario_id": sample,
                            "fixture": fixture,
                            "player_id": row.player_code,
                            "minutes": int(minutes[index]),
                            "goals": int(goals[index]),
                            "assists": int(assists[index]),
                            "clean_sheet": bool(cs[index]),
                            "defcon": bool(dc[index]),
                            "total_points": float(points[index]),
                        }
                    )
                    if coherent_lineups:
                        records[-1]["entered_at"] = float(entry[index])
                        records[-1]["left_at"] = float(exit_time[index])
    return FootballDraws(
        pd.DataFrame(records),
        pd.DataFrame(scores),
        seed,
        "shared_football_intervals_v2"
        if coherent_lineups
        else "shared_football_score_candidate_v1",
    )


def score_football_candidates(
    draws: FootballDraws,
    decisions: Mapping[str, FrozenSquadDecision],
    *,
    rival: str | None = None,
    hits: Mapping[str, float] | None = None,
    chips: Mapping[str, str | None] | None = None,
    blank_player_ids: frozenset[object] = frozenset(),
) -> pd.DataFrame:
    """Official autosub/captain scores and paired rival differences on common worlds."""
    if not decisions or (rival is not None and rival not in decisions):
        raise ValueError("Decisions and a known rival name are required.")
    hits = hits or {}
    chips = chips or {}
    if set(chips) - set(decisions) or any(
        c not in (None, "3xc", "bboost", "wildcard", "freehit") for c in chips.values()
    ):
        raise ValueError("Unknown candidate chip.")
    if set(hits) - set(decisions) or any(not np.isfinite(v) or v < 0 for v in hits.values()):
        raise ValueError("Hits must be finite nonnegative costs for known candidates.")
    covered = set(draws.outcomes.player_id) | blank_player_ids
    if any(set(d.squad.player_id) - covered for d in decisions.values()):
        raise ValueError("Scenario coverage is missing a player not explicitly marked blank.")
    if set(draws.outcomes.player_id) & blank_player_ids:
        raise ValueError("A player cannot be both blank and scheduled.")
    expected_keys = set(zip(draws.outcomes.fixture, draws.outcomes.player_id, strict=True))
    if (
        draws.outcomes.empty
        or draws.outcomes.duplicated(["scenario_id", "fixture", "player_id"]).any()
    ):
        raise ValueError("Scenario coverage must contain unique, nonempty player-fixture rows.")
    records: list[dict[str, object]] = []
    for scenario, outcomes in draws.outcomes.groupby("scenario_id", sort=True):
        if set(zip(outcomes.fixture, outcomes.player_id, strict=True)) != expected_keys:
            raise ValueError("Scenario coverage is incomplete for a scheduled player-fixture.")
        week = outcomes.groupby("player_id", as_index=False)[["minutes", "total_points"]].sum()
        week["minutes"] = week.minutes.astype(int)
        for name, decision in decisions.items():
            # A squad player without any match is explicitly a blank, not a missing label.
            roster = decision.squad[["player_id"]].merge(week, on="player_id", how="left")
            roster[["minutes", "total_points"]] = roster[["minutes", "total_points"]].fillna(0)
            roster["minutes"] = roster.minutes.astype(int)
            official = score_frozen_squad_decision(decision, roster)
            score = official.total_points
            if chips.get(name) == "3xc":
                score += official.captain_bonus_points
            elif chips.get(name) == "bboost":
                score = float(roster.total_points.sum()) + official.captain_bonus_points
            score -= hits.get(name, 0.0)
            records.append({"scenario_id": scenario, "candidate": name, "net_points": score})
    result = pd.DataFrame(records)
    if rival is not None:
        opponent = result.loc[result.candidate.eq(rival)].set_index("scenario_id").net_points
        result["rival_difference"] = result.net_points - result.scenario_id.map(opponent)
        result["beat_rival"] = result.rival_difference.gt(0)
    return result
