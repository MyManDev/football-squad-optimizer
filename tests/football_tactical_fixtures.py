"""Independent invented source documents and native controls for tactical E2E tests."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pandas as pd

from squadopt.features.football_tactical_inputs import (
    RAW_FPL_CREDITS_VERSION,
    RAW_PHYSICAL_GOALS_VERSION,
    RAW_PROJECTION_VERSION,
    STYLE_COUNTS,
    STYLE_DEFINITION_VERSION,
    TRAIT_DEFINITION_VERSION,
    TRAITS,
    TacticalJointState,
    TacticalPlayerState,
    TacticalProfile,
    TacticalProjection,
    TacticalSideState,
    TacticalSource,
    TacticalStyle,
    TacticalStyleFixture,
    projection_digest,
    read_tactical_observation,
    read_tactical_projection,
)
from squadopt.live.minute_evidence import _score_components
from squadopt.prediction.football import FOOTBALL_MODEL_VERSION
from squadopt.prediction.football_tactical_matchup import TacticalMatchupModel

SEASON = "2026-27"
GAMEWEEK = 6
CUTOFF = "2026-10-09T00:00:00Z"
CAPTURED = "2026-10-08T23:00:00Z"
DEADLINE = "2026-10-10T10:00:00Z"
XI = (1, 3, 4, 5, 8, 9, 10, 11, 13, 14, 15)
BENCH = (2, 7, 6, 12)
FIXED_POSITIONS = (
    "GK",
    "GK",
    "DEF",
    "DEF",
    "DEF",
    "DEF",
    "DEF",
    "MID",
    "MID",
    "MID",
    "MID",
    "MID",
    "FWD",
    "FWD",
    "FWD",
)
DECLARED_ROLES = {"GK": "goalkeeper", "DEF": "defender", "MID": "midfielder", "FWD": "attacker"}
RESOURCES = {
    "bank_tenths": 17,
    "free_transfers": 2,
    "chip": None,
    "hit_points": 0.0,
    "transfer_policy": {"inventory": "fixed", "budget": "retain"},
}


def payload(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def source(kind: Any, at: str, identity: str, content: object | None = None) -> TacticalSource:
    return TacticalSource(
        identity,
        "synthetic-only",
        "1",
        hashlib.sha256(
            payload(content if content is not None else {"identity": identity})
        ).hexdigest(),
        at,
        at,
        kind,
        True,
        "synthetic-only",
    )


def bound(raw: bytes, receipt: TacticalSource) -> TacticalSource:
    return replace(receipt, raw_sha256=hashlib.sha256(raw).hexdigest())


def club_players(club: int) -> tuple[tuple[int, str], ...]:
    chosen = [(i, FIXED_POSITIONS[i - 1]) for i in range(1, 16) if (i - 1) % 6 + 1 == club]
    target = {"GK": 1, "DEF": 4, "MID": 4, "FWD": 2}
    for position, count in target.items():
        needed = count - sum(p == position for _, p in chosen)
        chosen.extend([(1000 + club * 100 + len(chosen) + i, position) for i in range(needed)])
    if club == 6:
        chosen.append((6000, "DEF"))
    return tuple(chosen)


def style(club: int, season: str) -> TacticalStyle:
    year = int(season[:4])
    end = f"{year}-08-31T00:00:00Z"
    counts = (80, 20, 16, 10, 40, 50) if club == 6 else (20, 8, 16, 10, 40, 50)
    return TacticalStyle(
        club,
        season,
        f"{year}-08-01T00:00:00Z",
        end,
        (
            TacticalStyleFixture(
                club * 100 + 1, 1, f"{year}-08-10T12:00:00Z", f"{year}-08-10T15:00:00Z", 90
            ),
            TacticalStyleFixture(
                club * 100 + 2, 2, f"{year}-08-20T12:00:00Z", f"{year}-08-20T15:00:00Z", 90
            ),
        ),
        counts,
        STYLE_DEFINITION_VERSION,
        "synthetic-only-event-mapping",
        True,
        source("style", end, f"style-{season}-{club}", {"counts": counts, "exposure_minutes": 180}),
    )


def side(club: int, season: str, *, defense: int, present: bool) -> TacticalSideState:
    year = int(season[:4])
    observed = f"{year}-07-01T00:00:00Z"
    players = []
    for code, position in club_players(club):
        attrs = dict.fromkeys(TRAITS, 10)
        if club == 5 and position == "DEF":
            for name in (
                "heading",
                "jumping_reach",
                "anticipation",
                "positioning",
                "marking",
                "tackling",
                "strength",
            ):
                attrs[name] = defense
        if code == 12:
            attrs.update(heading=20, jumping_reach=20, off_the_ball=20, pace=18)
        if code == 6:
            attrs.update(heading=18, crossing=20, passing=20, vision=20, decisions=18)
        if code == 6000:
            attrs.update(heading=3, crossing=3, passing=3, vision=3)
        minutes = 90.0
        if code == 5 and present:
            minutes = 75.0
        if code == 6:
            minutes = 90.0 if present else 0.0
        if code == 6000:
            minutes = 0.0 if present else 90.0
        shares = 0.1 if position != "GK" and minutes else 0.0
        profile = TacticalProfile(
            code,
            club,
            position,
            tuple(attrs[n] for n in TRAITS),
            TRAIT_DEFINITION_VERSION,
            f"synthetic-uid-{code}",
            "uid",
            "synthetic-only-reviewed-temporal-mapping",
            observed,
            f"{year + 1}-07-01T00:00:00Z",
            source(
                "traits",
                observed,
                f"traits-{season}-{club}-{code}-defense-{defense}",
                {"uid": code, "attributes": attrs},
            ),
        )
        players.append(
            TacticalPlayerState(profile, DECLARED_ROLES[position], minutes, shares, shares)
        )
    return TacticalSideState(club, 2.5, 0.8, 0.6, tuple(players))


def projection(
    *,
    season: str = SEASON,
    gameweek: int = GAMEWEEK,
    fixture: int = 7203,
    home: int = 5,
    away: int = 6,
    defense: int = 3,
    kickoff: str = "2026-10-10T18:00:00Z",
    decision: str = CUTOFF,
) -> TacticalProjection:
    states = tuple(
        TacticalJointState(
            "present" if present else "replacement",
            weight,
            side(home, season, defense=defense, present=present),
            side(away, season, defense=defense, present=present),
        )
        for present, weight in ((True, 0.8), (False, 0.2))
    )
    result = TacticalProjection(
        season,
        gameweek,
        fixture,
        home,
        away,
        kickoff,
        decision,
        style(home, season),
        style(away, season),
        states,
        source("projection", decision, f"projection-{season}-{fixture}"),
    )
    return read_projection(result)


def projection_document(value: TacticalProjection) -> dict[str, Any]:
    row = asdict(value)
    del row["source"]
    row["contract_version"] = RAW_PROJECTION_VERSION
    for name in ("home_style", "away_style"):
        row[name]["counts"] = dict(zip(STYLE_COUNTS, row[name]["counts"], strict=True))
    for state in row["states"]:
        for own in (state["home"], state["away"]):
            for player in own["players"]:
                player["profile"]["attributes"] = dict(
                    zip(TRAITS, player["profile"]["attributes"], strict=True)
                )
    return row


def read_projection(
    value: TacticalProjection, document: dict[str, Any] | None = None
) -> TacticalProjection:
    raw = payload(projection_document(value) if document is None else document)
    return read_tactical_projection(
        raw, source=bound(raw, value.source), season=value.season, gameweek=value.gameweek
    )


def observations(*, zero: bool = False) -> tuple[Any, ...]:
    rows = []
    for index in range(12):
        kickoff = datetime(2024, 9, 1, 12, tzinfo=UTC) + timedelta(days=index)
        decision = (kickoff - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
        p = projection(
            season="2024-25",
            gameweek=index + 3,
            fixture=8000 + index,
            defense=3 if index % 2 == 0 else 18,
            kickoff=kickoff.isoformat().replace("+00:00", "Z"),
            decision=decision,
        )
        settled = (kickoff + timedelta(hours=3)).isoformat().replace("+00:00", "Z")
        goals = (0, 0) if zero else (1, 6 if index % 2 == 0 else 1)
        context = {
            "season": p.season,
            "gameweek": p.gameweek,
            "fixture": p.fixture,
            "home_club": p.home_club,
            "away_club": p.away_club,
            "kickoff": p.kickoff,
            "decision_at": p.decision_at,
            "projection_sha256": projection_digest(p),
            "outcome_available_at": settled,
            "final": True,
            "rules_version": "synthetic-fpl-rules-v1",
        }
        credits = []
        for own, count in zip((p.states[0].home, p.states[0].away), goals, strict=True):
            outfield = [player for player in own.players if player.profile.position != "GK"]
            scorer = 12 if own.club == 6 else outfield[-1].profile.player_code
            assister = 6 if own.club == 6 else outfield[0].profile.player_code
            credits.extend(
                {
                    "player_code": player.profile.player_code,
                    "club": own.club,
                    "goals": count if player.profile.player_code == scorer else 0,
                    "assists": (count // 2) if player.profile.player_code == assister else 0,
                }
                for player in own.players
            )
        goal_raw = payload(
            {**context, "contract_version": RAW_PHYSICAL_GOALS_VERSION, "physical_goals": goals}
        )
        credit_raw = payload(
            {**context, "contract_version": RAW_FPL_CREDITS_VERSION, "credits": credits}
        )
        rows.append(
            read_tactical_observation(
                goal_raw,
                credit_raw,
                projection=p,
                goal_source=bound(goal_raw, source("physical-goals", settled, f"goals-{index}")),
                credit_source=bound(credit_raw, source("fpl-totals", settled, f"credits-{index}")),
                training_cutoff=CUTOFF,
                allowed_seasons=("2024-25",),
            )
        )
    return tuple(rows)


def fitted(*, zero: bool = False) -> TacticalMatchupModel:
    return TacticalMatchupModel(max_iter=600).fit(
        observations(zero=zero),
        cutoff=CUTOFF,
        allowed_seasons=("2024-25",),
        target_season=SEASON,
        target_gameweek=GAMEWEEK,
    )


@dataclass(frozen=True)
class TacticalWorld:
    native: pd.DataFrame
    roster: pd.DataFrame
    calendar: pd.DataFrame
    projections: tuple[TacticalProjection, ...]
    availability: dict[int, float]


def world(
    *,
    defense: int = 3,
    double: bool = False,
    blank: bool = False,
    residual: float | None = None,
    zero_rates: bool = False,
) -> TacticalWorld:
    specs = [
        (7201, 6, 1, 2, "2026-10-10T12:00:00Z"),
        (7202, 6, 3, 4, "2026-10-10T15:00:00Z"),
        (
            7203,
            7 if blank else 6,
            5,
            6,
            "2026-10-17T18:00:00Z" if blank else "2026-10-10T18:00:00Z",
        ),
    ]
    if double:
        specs.append((7204, 6, 5, 6, "2026-10-12T18:00:00Z"))
    ps = tuple(
        projection(
            gameweek=gw, fixture=fixture, home=home, away=away, kickoff=kickoff, defense=defense
        )
        for fixture, gw, home, away, kickoff in specs
    )
    if zero_rates:
        ps = tuple(
            read_projection(
                replace(
                    p,
                    states=tuple(
                        replace(
                            s,
                            home=replace(s.home, base_goal_rate=0.0),
                            away=replace(s.away, base_goal_rate=0.0),
                        )
                        for s in p.states
                    ),
                )
            )
            for p in ps
        )
    records, calendar = [], []
    for p in ps:
        for is_home, club, opponent in (
            (True, p.home_club, p.away_club),
            (False, p.away_club, p.home_club),
        ):
            calendar.append(
                dict(
                    GW=p.gameweek,
                    fixture=p.fixture,
                    club=club,
                    opponent=opponent,
                    home=int(is_home),
                    kickoff=p.kickoff,
                    decision_at=p.decision_at,
                )
            )
            states = [s.home if is_home else s.away for s in p.states]
            code_map = [
                {player.profile.player_code: player for player in own.players} for own in states
            ]
            mass = sum(
                s.weight * own.base_goal_rate * own.scored_fraction
                for s, own in zip(p.states, states, strict=True)
            )
            assist_mass = sum(
                s.weight * own.base_goal_rate * own.scored_fraction * own.assist_fraction
                for s, own in zip(p.states, states, strict=True)
            )
            for code, position in club_players(club):
                weights = [s.weight for s in p.states]
                minutes = [mapping[code].minutes for mapping in code_map]
                bins = [0 if m == 0 else 1 if m < 60 else 2 if m < 90 else 3 for m in minutes]
                probabilities = [
                    sum(w for w, b in zip(weights, bins, strict=True) if b == index)
                    for index in range(4)
                ]
                representatives = [
                    sum(w * m for w, m, b in zip(weights, minutes, bins, strict=True) if b == index)
                    / probabilities[index]
                    if probabilities[index]
                    else (0, 30, 75, 90)[index]
                    for index in range(4)
                ]
                goals = sum(
                    s.weight
                    * own.base_goal_rate
                    * own.scored_fraction
                    * mapping[code].native_goal_share
                    for s, own, mapping in zip(p.states, states, code_map, strict=True)
                )
                assists = sum(
                    s.weight
                    * own.base_goal_rate
                    * own.scored_fraction
                    * own.assist_fraction
                    * mapping[code].native_assist_share
                    for s, own, mapping in zip(p.states, states, code_map, strict=True)
                )
                share = sum(
                    s.weight * mapping[code].native_goal_share
                    for s, mapping in zip(p.states, code_map, strict=True)
                )
                records.append(
                    dict(
                        GW=p.gameweek,
                        fixture=p.fixture,
                        club=club,
                        opponent=opponent,
                        home=int(is_home),
                        kickoff=p.kickoff,
                        decision_at=p.decision_at,
                        player_code=code,
                        position=position,
                        team_goal_rate=states[0].base_goal_rate,
                        opponent_goal_rate=states[0].base_goal_rate,
                        goals=goals,
                        assists=assists,
                        goals_share=goals / mass if mass else share,
                        assists_share=assists / assist_mass if assist_mass else share,
                        defcon_rate90=0.0,
                        defcon_dispersion=2.0,
                        residual_if_appearance=0.0 if residual is None else residual,
                        availability_multiplier=1.0,
                        model_version=FOOTBALL_MODEL_VERSION,
                        **{f"minute_probability_{i}": probabilities[i] for i in range(4)},
                        **{f"minute_value_{i}": representatives[i] for i in range(4)},
                    )
                )
    native = pd.DataFrame(records)
    native.attrs.update(
        season=SEASON,
        availability_application="not_applied",
        source_snapshot_id="synthetic-tactical-capture",
        resources=RESOURCES,
    )
    native = _score_components(native)
    if residual is None:
        desired = {6: 3.5, 7: 4.5, 8: 5.9, 11: 4.0, 12: 3.1, 13: 8.0}
        for index, row in native.iterrows():
            if int(row.player_code) <= 15:
                native.at[index, "residual_if_appearance"] = (
                    desired.get(int(row.player_code), 5.0) - float(row.raw_expected_points)
                ) / float(row.appearance_probability)
        native = _score_components(native)
    roster = pd.DataFrame(
        dict(
            player_id=code,
            name=f"Synthetic Player {code}",
            team_id=club,
            club_code=club,
            position=position,
            buy_price_tenths=50 + code % 8,
            sell_price_tenths=49 + code % 8,
        )
        for club in range(1, 7)
        for code, position in club_players(club)
    )
    roster.attrs["resources"] = RESOURCES
    availability = {int(code): 0.75 if code in (6, 13) else 1.0 for code in roster.player_id}
    return TacticalWorld(native, roster, pd.DataFrame(calendar), ps, availability)
