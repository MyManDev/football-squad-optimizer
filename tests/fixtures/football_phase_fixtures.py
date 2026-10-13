"""Invented byte receipts and complete fixtures for private phase checks."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import UTC, datetime, timedelta

import pandas as pd

from squadopt.data.snapshots import (
    SNAPSHOT_SCHEMA_VERSION,
    CapturedSnapshot,
    SnapshotMetadata,
    build_snapshot_id,
    payload_checksum,
    snapshot_fingerprint,
)
from squadopt.data.sources.fpl_live import BOOTSTRAP_PAYLOAD, FPL_LIVE_SOURCE
from squadopt.data.timestamps import normalize_utc_timestamp
from squadopt.features.football_phase_inputs import (
    PHASE_DEFINITION_VERSION,
    PhaseSource,
    read_phase_duties,
    read_phase_observation,
    read_phase_projection,
)
from squadopt.prediction.football import FOOTBALL_MODEL_VERSION

DECISION = "2026-09-22T12:00:00Z"
SEASON = "2026-27"
XI = (1, 3, 4, 5, 8, 9, 10, 11, 13, 14, 15)
BENCH = (2, 7, 6, 12)
CLUBS = {code: (code - 1) % 6 + 1 for code in range(1, 67)}
POSITIONS = {
    code: (["GK"] * 2 + ["DEF"] * 5 + ["MID"] * 5 + ["FWD"] * 3)[code - 1]
    if code <= 15
    else ("GK" if code % 11 == 0 else "MID")
    for code in CLUBS
}


def raw_bytes(document):
    return json.dumps(document, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def bootstrap_document(*, penalty=18, delivery=24):
    return {
        "teams": [{"id": club + 100, "code": club} for club in range(1, 7)],
        "elements": [
            {
                "id": code + 1000,
                "code": code,
                "team": CLUBS[code] + 100,
                "penalties_order": 1 if code == penalty else 2,
                "direct_freekicks_order": None,
                "corners_and_indirect_freekicks_order": 1 if code == delivery else 2,
            }
            for code in CLUBS
        ],
    }


def captured_snapshot(document=None, *, captured_at=DECISION):
    captured_at = normalize_utc_timestamp(captured_at, label="synthetic capture")
    payload = raw_bytes(bootstrap_document() if document is None else document)
    checksums = {BOOTSTRAP_PAYLOAD: payload_checksum(payload)}
    fingerprint = snapshot_fingerprint(
        source=FPL_LIVE_SOURCE,
        captured_at_utc=captured_at,
        schema_version=SNAPSHOT_SCHEMA_VERSION,
        checksums=checksums,
    )
    identifier = build_snapshot_id(
        source=FPL_LIVE_SOURCE, captured_at_utc=captured_at, fingerprint=fingerprint
    )
    return CapturedSnapshot(
        SnapshotMetadata(
            identifier,
            FPL_LIVE_SOURCE,
            captured_at,
            SNAPSHOT_SCHEMA_VERSION,
            checksums,
            fingerprint,
        ),
        {BOOTSTRAP_PAYLOAD: payload},
    )


def duty_capture(*, penalty=18, delivery=24, season=SEASON, decision=DECISION):
    snapshot = captured_snapshot(
        bootstrap_document(penalty=penalty, delivery=delivery), captured_at=decision
    )
    return read_phase_duties(
        snapshot,
        season=season,
        decision_at=decision,
        valid_until="2027-07-01T00:00:00Z",
        model_use_approved=True,
        model_use_evidence_ref="synthetic-only",
    )


def source(payload, *, kind, when, identifier="invented"):
    return PhaseSource(
        identifier,
        "synthetic-only",
        "v1",
        hashlib.sha256(payload).hexdigest(),
        when,
        when,
        kind,
        True,
        "synthetic-only",
    )


def observation_documents(*, gameweek=1, penalty=18, delivery=24, season="2024-25"):
    decision_time = datetime(2024, 8, 1, 12, tzinfo=UTC) + timedelta(days=7 * (gameweek - 1))
    decision = decision_time.isoformat()
    kickoff = (decision_time + timedelta(days=1)).isoformat()
    available = (decision_time + timedelta(days=1, hours=3)).isoformat()
    context = {
        "season": season,
        "gameweek": gameweek,
        "fixture": 1000 + gameweek,
        "club": 6,
        "opponent": 5,
        "home": False,
        "kickoff": kickoff,
        "decision_at": decision,
    }
    players = [
        {
            "player_code": code,
            "position": POSITIONS[code],
            "goal_weight90": 1.0,
            "assist_weight90": 1.0,
        }
        for code, club in CLUBS.items()
        if club == 6
    ]
    events = [
        {
            "event_id": f"{gameweek}:penalty:{index}",
            "phase": "penalty",
            "scorer": penalty,
            "assist": None,
            "own_goal": False,
            "credit_evidence_ref": "synthetic-final-fpl-credit",
            "credit_status": "final",
        }
        for index in range(2)
    ]
    for index, scorer in enumerate((42, 48)):
        events.append(
            {
                "event_id": f"{gameweek}:corner:{index}",
                "phase": "corner",
                "scorer": scorer,
                "assist": delivery,
                "own_goal": False,
                "credit_evidence_ref": "synthetic-final-fpl-credit",
                "credit_status": "final",
            }
        )
    events.append(
        {
            "event_id": f"{gameweek}:other",
            "phase": "other",
            "scorer": 54,
            "assist": None,
            "own_goal": False,
            "credit_evidence_ref": "synthetic-final-fpl-credit",
            "credit_status": "final",
        }
    )
    return (
        {
            **context,
            "schema_version": "football_phase_credits_v1",
            "rules_version": "synthetic-fpl-rules-v1",
            "phase_definition_version": PHASE_DEFINITION_VERSION,
            "outcome_available_at": available,
            "complete_coverage": True,
            "events": events,
        },
        {
            **context,
            "schema_version": "football_phase_fpl_totals_v1",
            "rules_version": "synthetic-fpl-rules-v1",
            "outcome_available_at": available,
            "final": True,
            "players": [
                {
                    "player_code": p["player_code"],
                    "minutes": 90.0,
                    "goals": sum(e["scorer"] == p["player_code"] for e in events),
                    "assists": sum(e["assist"] == p["player_code"] for e in events),
                }
                for p in players
            ],
        },
        {**context, "schema_version": "football_phase_baseline_v1", "players": players},
    )


def read_observation(documents=None, *, duties=None, **overrides):
    events, totals, baseline = observation_documents() if documents is None else documents
    event_bytes, total_bytes, baseline_bytes = map(raw_bytes, (events, totals, baseline))
    arguments = {
        "duties": duty_capture(season=events["season"], decision=events["decision_at"])
        if duties is None
        else duties,
        "outcome_source": source(
            event_bytes, kind="phase-events", when=events["outcome_available_at"]
        ),
        "totals_source": source(
            total_bytes, kind="fpl-totals", when=totals["outcome_available_at"]
        ),
        "baseline_source": source(baseline_bytes, kind="baseline", when=baseline["decision_at"]),
        "season": events["season"],
        "gameweek": events["gameweek"],
        "training_cutoff": DECISION,
        "allowed_seasons": ("2024-25",),
        "excluded_target": (SEASON, 6),
    }
    return read_phase_observation(
        event_bytes, total_bytes, baseline_bytes, **(arguments | overrides)
    )


def fitted_model():
    from squadopt.prediction.football_phase_duties import PhaseDutyModel

    observations = []
    for week in range(1, 19):
        penalty = (18, 24, 30)[week % 3]
        delivery = (6, 24, 36)[week % 3]
        documents = observation_documents(gameweek=week, penalty=penalty, delivery=delivery)
        duties = duty_capture(
            penalty=penalty,
            delivery=delivery,
            season="2024-25",
            decision=documents[0]["decision_at"],
        )
        observations.append(read_observation(documents, duties=duties))
    return PhaseDutyModel().fit(
        tuple(observations),
        cutoff=DECISION,
        allowed_seasons=("2024-25",),
        target_season=SEASON,
        target_gameweek=6,
    )


def native_case(*, dgw=False, bgw=False, probabilities=None, zero_mass=False, negative_player=None):
    probabilities = {} if probabilities is None else probabilities
    calendar = []
    for match, (home, away) in enumerate(((1, 2), (3, 4), (5, 6)), 1):
        for club, opponent, is_home in ((home, away, True), (away, home, False)):
            calendar.append(
                {
                    "GW": 6,
                    "fixture": 60 + match,
                    "club": club,
                    "opponent": opponent,
                    "home": is_home,
                    "kickoff": "2026-09-23T15:00:00Z",
                    "decision_at": DECISION,
                }
            )
    if dgw:
        calendar += [
            {**row, "fixture": 69, "kickoff": "2026-09-25T15:00:00Z"}
            for row in calendar
            if row["club"] in (5, 6)
        ]
    if bgw:
        calendar += [
            {
                **row,
                "GW": 7,
                "fixture": 73,
                "kickoff": "2026-09-30T15:00:00Z",
                "decision_at": "2026-09-29T12:00:00Z",
            }
            for row in calendar
            if row["fixture"] == 63
        ]
    rows = []
    for side in calendar:
        q = {
            code: probabilities.get((side["fixture"], code), 1.0)
            for code, club in CLUBS.items()
            if club == side["club"]
        }
        denominator = math.fsum(q.values())
        for code, chance in q.items():
            position = POSITIONS[code]
            goal = 0.0 if zero_mass else 3.0 * chance / denominator
            assist = 0.0 if zero_mass else 0.9 * chance / denominator
            clean = chance * math.exp(-3.0)
            goal_coefficient = {"GK": 10, "DEF": 6, "MID": 5, "FWD": 4}[position]
            clean_coefficient = {"GK": 4, "DEF": 4, "MID": 1, "FWD": 0}[position]
            target = {6: 3.5, 7: 4.5, 8: 5.9, 11: 4.0, 12: 3.1, 13: 8.0}.get(code, 5.0)
            if code == negative_player:
                target = -2.0
            base = 2 * chance + goal_coefficient * goal + 3 * assist + clean_coefficient * clean
            residual = (target - base) / chance if chance else 0.0
            raw = base + chance * residual
            rows.append(
                {
                    **side,
                    "player_code": code,
                    "position": position,
                    "expected_minutes": 90.0 * chance,
                    "appearance_probability": chance,
                    "p60": chance,
                    "team_goal_rate": 3.0,
                    "opponent_goal_rate": 3.0,
                    "goals": goal,
                    "assists": assist,
                    "goals_share": chance / denominator,
                    "assists_share": chance / denominator,
                    "clean_sheet_probability": clean,
                    "defcon_probability": 0.0,
                    "defcon_rate90": 0.0,
                    "defcon_dispersion": 4.0,
                    "residual_if_appearance": residual,
                    "raw_expected_points": raw,
                    "expected_points": max(raw, 0.0),
                    "model_version": FOOTBALL_MODEL_VERSION,
                    **{
                        f"minute_probability_{b}": [1 - chance, 0.0, 0.0, chance][b]
                        for b in range(4)
                    },
                    **{f"minute_value_{b}": [0.0, 30.0, 75.0, 90.0][b] for b in range(4)},
                }
            )
    components = pd.DataFrame(rows)
    components.attrs.update(
        native_reference="synthetic baseline v1", availability_application="not_applied"
    )
    roster = pd.DataFrame(
        {
            "player_id": range(1, 16),
            "position": [POSITIONS[code] for code in range(1, 16)],
            "team_id": [CLUBS[code] + 100 for code in range(1, 16)],
            "club_code": [CLUBS[code] for code in range(1, 16)],
            "price_tenths": [50] * 15,
        }
    )
    roster.attrs.update(
        bank_tenths=17,
        free_transfers=2,
        chip=None,
        hit_points=0,
        transfer_policy={"inventory": "fixed", "budget": "retain"},
    )
    return components, roster, pd.DataFrame(calendar)


def projection_document(components, *, fixture=63, club=6):
    side = components.loc[components.fixture.eq(fixture) & components.club.eq(club)]
    first = side.iloc[0]
    uncertain = side.loc[side.appearance_probability.lt(1)]
    if len(uncertain) > 1:
        raise ValueError("This invented fixture declares at most one native uncertain player.")
    states = []
    support = [("full", 1.0, None)]
    if not uncertain.empty:
        focal = int(uncertain.player_code.iloc[0])
        chance = float(uncertain.appearance_probability.iloc[0])
        support = [("absent", 1 - chance, focal), ("full", chance, None)]
    for identifier, weight, absent in support:
        if weight == 0:
            continue
        states.append(
            {
                "state_id": identifier,
                "weight": weight,
                "goal_mass": float(side.goals.sum()),
                "assist_mass": float(side.assists.sum()),
                "physical_goal_mass": float(first.team_goal_rate),
                "players": [
                    {
                        "player_code": int(row.player_code),
                        "position": row.position,
                        "minutes": 0.0 if row.player_code == absent else 90.0,
                        "goal_weight90": 1.0,
                        "assist_weight90": 1.0,
                    }
                    for row in side.itertuples()
                ],
            }
        )
    return {
        "schema_version": "football_phase_projection_v1",
        "season": SEASON,
        "gameweek": int(first.GW),
        "fixture": fixture,
        "club": club,
        "opponent": int(first.opponent),
        "home": bool(first.home),
        "kickoff": first.kickoff,
        "decision_at": first.decision_at,
        "states": states,
    }


def read_projection(document, *, penalty=18, delivery=24, **overrides):
    payload = raw_bytes(document)
    arguments = {
        "duties": duty_capture(
            penalty=penalty,
            delivery=delivery,
            season=document["season"],
            decision=document["decision_at"],
        ),
        "source": source(payload, kind="projection", when=document["decision_at"]),
        "model_cutoff": DECISION,
    }
    return read_phase_projection(payload, **(arguments | overrides))
