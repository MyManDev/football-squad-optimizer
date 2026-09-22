"""Opt-in football forecasts for a complete roster and a captured fixture calendar."""

from __future__ import annotations

from collections.abc import Sequence
from numbers import Integral
from typing import cast

import pandas as pd

from squadopt.planning.horizon import (
    APPEARANCE_HORIZON_CONTRACT_VERSION,
    PROJECTION_HORIZON_CONTRACT_VERSION,
    ProjectionHorizon,
)
from squadopt.prediction.football import (
    FOOTBALL_MODEL_VERSION,
    ROLE_MODEL_VERSION,
    FixtureFootballModel,
)
from squadopt.prediction.football_features import football_features


def weekly_appearance(group: pd.DataFrame) -> float:
    """One captured eligibility state across a double week, then conditional appearances.

    Each fixture's marginal already contains the multiplier. Reusing the same health
    information cannot create independent extra chances to recover within the week.
    Conditional fixture appearances remain an explicit independence approximation.
    """
    if group.availability_multiplier.nunique() != 1:
        raise ValueError("A player-week requires one shared captured availability state.")
    eligibility = float(group.availability_multiplier.iloc[0])
    if eligibility == 0:
        return 0.0
    conditional = (group.appearance_probability.to_numpy(float) / eligibility).clip(0, 1)
    return eligibility * (1 - float((1 - conditional).prod()))


def build_football_horizon(
    model: FixtureFootballModel,
    history: pd.DataFrame,
    roster: pd.DataFrame,
    fixtures: pd.DataFrame,
    *,
    gameweeks: Sequence[int],
    season: str,
    source_snapshot_id: str,
    captured_at: pd.Timestamp,
    role_transitions: bool = False,
) -> tuple[ProjectionHorizon, pd.DataFrame]:
    """Forecast each match; blank weeks never poison later fixture forecasts.

    roster: player_id/name/team_id/position/price_tenths/club.
    fixtures: one row per side, fixture/club/opponent/home/GW/kickoff.
    Both must come from the caller's named pre-deadline snapshot. Historical final
    calendars must not be labeled as prospective evidence by a caller.
    """
    weeks = tuple(gameweeks)
    if not isinstance(role_transitions, bool):
        raise ValueError("role_transitions must be a boolean.")
    if (
        not weeks
        or any(
            isinstance(w, bool) or not isinstance(w, Integral) or not 1 <= w <= 38 for w in weeks
        )
        or weeks != tuple(range(weeks[0], weeks[-1] + 1))
    ):
        raise ValueError("Gameweeks must be nonempty, unique and consecutive.")
    if captured_at.tzinfo is None or captured_at > model.cutoff:
        raise ValueError("The source capture must precede the model decision cutoff.")
    if roster.player_id.duplicated().any() or roster.empty:
        raise ValueError("A unique nonempty decision-time roster is required.")
    schedule = fixtures.loc[fixtures.GW.isin(weeks)].copy()
    if schedule.duplicated(["fixture", "club"]).any():
        raise ValueError("Duplicate club-fixture calendar row.")
    for _, match in schedule.groupby("fixture"):
        if (
            len(match) != 2
            or set(match.home) != {0, 1}
            or set(match.club) != set(match.opponent)
            or match.club.nunique() != 2
            or match.GW.nunique() != 1
            or match.kickoff.nunique() != 1
        ):
            raise ValueError("Calendar requires two consistent opposing fixture sides.")
    if not schedule.empty and not (schedule.kickoff > model.cutoff).all():
        raise ValueError("Forecast calendar contains a match already underway.")
    base = roster.rename(columns={"player_id": "player_code"})
    targets = base.merge(schedule, on="club", validate="many_to_many").assign(season=season)
    target_parts: list[pd.DataFrame] = []
    if not targets.empty:
        targets = targets.sort_values(["kickoff", "fixture", "player_code"], kind="stable")
        targets["role_steps"] = targets.groupby("player_code").cumcount() if role_transitions else 0
        # Each club's player shares must be normalized across the entire roster for
        # that match. Role steps are common to its players under a fixed roster.
        for steps, target in targets.groupby("role_steps", sort=True):
            features = football_features(history, target, model.cutoff)
            target = pd.concat([target.drop(columns="home"), features], axis=1)
            prediction = model.predict(target, role_steps=int(cast(int, steps)))
            target_parts.append(pd.concat([target, prediction], axis=1))
    components = pd.concat(target_parts, ignore_index=True) if target_parts else pd.DataFrame()
    rows: list[pd.DataFrame] = []
    contextual = model.model_version != FOOTBALL_MODEL_VERSION
    for week in weeks:
        part = roster[["player_id", "name", "team_id", "position", "price_tenths"]].copy()
        part["gameweek"] = week
        for col in ("expected_points", "fixture_count", "home_fixture_count"):
            part[col] = 0.0 if col == "expected_points" else 0
        if not components.empty:
            data = (
                components.loc[components.GW.eq(week)]
                .groupby("player_code")
                .agg(
                    expected_points=("expected_points", "sum"),
                    fixture_count=("fixture", "count"),
                    home_fixture_count=("home", "sum"),
                )
            )
            for col in ("expected_points", "fixture_count", "home_fixture_count"):
                part[col] = part.player_id.map(data[col]).fillna(0)
        for col in ("fixture_count", "home_fixture_count"):
            part[col] = part[col].astype(int)
        if contextual:
            chance = (
                pd.Series(
                    {
                        player: weekly_appearance(group)
                        for player, group in components.loc[components.GW.eq(week)].groupby(
                            "player_code"
                        )
                    },
                    dtype=float,
                )
                if not components.empty
                else pd.Series(dtype=float)
            )
            part["appearance_probability"] = part.player_id.map(chance).fillna(0)
        rows.append(part)
    horizon = ProjectionHorizon(
        pd.concat(rows, ignore_index=True),
        season,
        source_snapshot_id,
        "fixture_football_candidate",
        ROLE_MODEL_VERSION if role_transitions else model.model_version,
        "causal_football_fixture_features_v1",
        "fixture_sum_blank_zero_v1",
        contract_version=(
            APPEARANCE_HORIZON_CONTRACT_VERSION
            if contextual
            else PROJECTION_HORIZON_CONTRACT_VERSION
        ),
    )
    return horizon, components
