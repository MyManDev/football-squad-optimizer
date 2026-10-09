"""Invented complete clubs and independent scoring oracles for workload tests."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from itertools import product

import pandas as pd
from scipy.stats import nbinom

from squadopt.features.football_load_inputs import (
    NATIVE_BASIS_VERSION,
    RAW_LOAD_OUTCOME_VERSION,
    RAW_LOAD_SNAPSHOT_VERSION,
    LoadFixture,
    load_input_digest,
    native_joint_law_digest,
    read_load_outcomes,
    read_load_snapshot,
)
from squadopt.prediction.football import JOINT_ROLE_MODEL_VERSION
from squadopt.prediction.football_minutes_role import ROLE_MINUTE_VERSION

SEASON = "2026-27"
DECISION = "2026-09-22T12:00:00Z"
DEADLINE = "2026-09-22T18:00:00Z"
FIT_CUTOFF = "2025-06-01T00:00:00Z"
LAW = (0.12, 0.08, 0.10, 0.45, 0.10, 0.10, 0.05)
DURATIONS = (0.0, 20.0, 70.0, 90.0, 10.0, 65.0, 90.0)
XI = (1, 3, 4, 5, 8, 9, 10, 11, 13, 14, 15)
BENCH = (2, 6, 7, 12)
COMPETITIONS = ("pl", "cup", "continental", "national")


@dataclass(frozen=True)
class LoadCase:
    components: pd.DataFrame
    weekly: pd.DataFrame
    roster: pd.DataFrame
    calendar: pd.DataFrame
    resources: dict[str, object]
    eligibility: dict[int, float]
    gameweeks: tuple[int, ...]


def document_bytes(document):
    raw = json.dumps(document, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return raw, hashlib.sha256(raw).hexdigest()


def score_row(row, probabilities=LAW, minutes=DURATIONS):
    """Direct seven-point FPL component algebra, independent of native helpers."""
    q = math.fsum(probabilities[1:])
    p60 = math.fsum(p for p, m in zip(probabilities, minutes, strict=True) if m >= 60)
    mean = math.fsum(p * m for p, m in zip(probabilities, minutes, strict=True))
    record = {
        "appearance_probability": q,
        "p60": p60,
        "expected_minutes": mean,
        "zero_probability": probabilities[0],
        "unknown_role_probability": 0.0,
        "expected_minutes_if_appearance": mean / q if q else 0.0,
        "start_probability": math.fsum(probabilities[1:4]),
        "cameo_probability": math.fsum(probabilities[4:7]),
    }
    for role, offset in (("start", 1), ("cameo", 4)):
        for b in (1, 2, 3):
            record[f"{role}_minute_probability_{b}"] = probabilities[offset + b - 1]
            record[f"{role}_minute_value_{b}"] = minutes[offset + b - 1]
    for b, cells in enumerate(((0,), (1, 4), (2, 5), (3, 6))):
        probability = math.fsum(probabilities[i] for i in cells)
        weighted = math.fsum(probabilities[i] * minutes[i] for i in cells)
        record[f"minute_probability_{b}"] = probability
        record[f"minute_value_{b}"] = (
            weighted / probability if probability else (0.0, 30.0, 75.0, 90.0)[b]
        )
    record["clean_sheet_probability"] = math.fsum(
        p * math.exp(-row["opponent_goal_rate"] * m / 90)
        for p, m in zip(probabilities, minutes, strict=True)
        if m >= 60
    )
    threshold = 10 if row["position"] == "DEF" else 12
    size = row["defcon_dispersion"]
    record["defcon_probability"] = (
        0.0
        if row["position"] == "GK"
        else math.fsum(
            p
            * nbinom.sf(
                threshold - 1, size, size / (size + max(row["defcon_rate90"] * m / 90, 1e-12))
            )
            for p, m in zip(probabilities[1:], minutes[1:], strict=True)
        )
    )
    raw = math.fsum(
        (
            q,
            p60,
            {"GK": 10, "DEF": 6, "MID": 5, "FWD": 4}[row["position"]] * row["goals"],
            3 * row["assists"],
            {"GK": 4, "DEF": 4, "MID": 1, "FWD": 0}[row["position"]]
            * record["clean_sheet_probability"],
            2 * record["defcon_probability"],
            q * row["residual_if_appearance"],
        )
    )
    record.update(raw_expected_points=raw, expected_points=max(0.0, raw))
    return record


def native_case(*, double=False, blank=False, extra_week=False):
    positions = ("GK", "GK", *("DEF",) * 5, *("MID",) * 5, *("FWD",) * 3)
    roster = pd.DataFrame(
        [
            {
                "player_id": p,
                "name": f"Load Player {p}",
                "team_id": (p - 1) % 6 + 1,
                "club_code": (p - 1) % 6 + 1,
                "position": positions[p - 1] if p <= 15 else "MID",
                "buy_price_tenths": 50 + p % 10,
                "sell_price_tenths": 49 + p % 10,
                "purchase_snapshot": f"synthetic-purchase-{p}",
            }
            for p in range(1, 67)
        ]
    )
    roster.attrs["private_state"] = {"bank": 18, "captured_owned": list(range(1, 16))}
    weeks = (6, 7) if extra_week else (6,)
    events = []
    if not blank:
        for week in weeks:
            for number, (one, two) in enumerate(((1, 2), (3, 4), (5, 6)), 1):
                for club, other, home in ((one, two, 1), (two, one, 0)):
                    events.append(
                        {
                            "fixture": week * 10 + number,
                            "club": club,
                            "opponent": other,
                            "home": home,
                            "GW": week,
                            "kickoff": f"2026-09-{23 if week == 6 else 30}T15:00:00Z",
                            "decision_at": DECISION,
                        }
                    )
        if double:
            events.extend(
                {**row, "fixture": 69, "kickoff": "2026-09-25T15:00:00Z"}
                for row in tuple(events)
                if row["GW"] == 6 and row["club"] in (3, 4)
            )
    calendar = pd.DataFrame(
        events, columns=("fixture", "club", "opponent", "home", "GW", "kickoff", "decision_at")
    )
    calendar.attrs.update(calendar_complete=True, covered_gameweeks=weeks)
    rows = []
    for match in events:
        for player in roster.loc[roster.club_code.eq(match["club"])].to_dict("records"):
            pid = player["player_id"]
            row = {
                **match,
                "season": SEASON,
                "player_code": pid,
                "position": player["position"],
                "model_version": JOINT_ROLE_MODEL_VERSION,
                "minute_role_version": ROLE_MINUTE_VERSION,
                "minute_role_status": "fitted_known_start_labels",
                "known_start_label_rows": 80,
                "unknown_start_label_rows": 0,
                "minute_prior_rows": 10.0,
                "team_goal_rate": 2.0,
                "opponent_goal_rate": 2.0,
                "goals_share": 1 / 11,
                "assists_share": 1 / 11,
                "goals": 1.1 / 11,
                "assists": 0.77 / 11,
                "defcon_rate90": 12.0,
                "defcon_dispersion": 2.0,
                "availability_multiplier": 1.0,
                "residual_if_appearance": {3: 5.0, 8: 4.0, 13: 3.0, 6: 2.0, 12: 1.0, 66: -20.0}.get(
                    pid, 0.0
                ),
            }
            row.update(score_row(row))
            rows.append(row)
    components = pd.DataFrame(rows) if rows else native_case().components.iloc[:0].copy()
    eligibility = {p: {3: 0.75, 6: 0.5, 7: 0.0, 13: 0.25}.get(p, 1.0) for p in range(1, 67)}
    _, source_sha = document_bytes({"synthetic_eligibility_snapshot": eligibility})
    components.attrs.update(
        season=SEASON,
        native_cutoff=DECISION,
        joint_role=True,
        availability_application="not_applied",
        calendar_complete=True,
        covered_gameweeks=weeks,
        captured_availability_sha256=source_sha,
        captured_availability_evidence_ref="synthetic-only-original-eligibility-capture",
    )
    weekly = pd.DataFrame(
        [
            {
                **player,
                "gameweek": week,
                "expected_points": eligibility[player["player_id"]]
                * math.fsum(part.expected_points),
                "appearance_probability": eligibility[player["player_id"]]
                * (1 - math.prod(1 - q for q in part.appearance_probability)),
            }
            for player in roster.to_dict("records")
            for week in weeks
            for part in [
                components.loc[
                    components.player_code.eq(player["player_id"]) & components.GW.eq(week)
                ]
            ]
        ]
    )
    weekly.attrs["original_forecast"] = "synthetic-unflagged-role-law-plus-eligibility"
    return LoadCase(
        components,
        weekly,
        roster,
        calendar,
        {
            "bank_tenths": 18,
            "free_transfers": 2,
            "chips": {"bboost": True, "3xc": True},
            "transfer_policy": {"hit_cost": 4},
            "owned": list(range(1, 16)),
        },
        eligibility,
        weeks,
    )


def appearance_world_score(squad, xi, bench, captain, vice, *, chip=None, hits=0.0):
    """Enumerate independent player appearances and official greedy slot replacements."""
    records = squad.set_index("player_id").to_dict("index")
    ids = tuple(records)
    q = {p: records[p]["appearance_probability"] for p in ids}
    points = {p: records[p]["expected_points"] / q[p] if q[p] else 0.0 for p in ids}
    positions = {p: records[p]["position"] for p in ids}
    nominal = {pos: sum(positions[p] == pos for p in xi) for pos in ("DEF", "MID", "FWD")}
    output = []
    for vector in product((False, True), repeat=len(ids)):
        plays = dict(zip(ids, vector, strict=True))
        mass = math.prod(q[p] if plays[p] else 1 - q[p] for p in ids)
        if not mass:
            continue
        if chip == "bboost":
            selected = [p for p in ids if plays[p]]
        else:
            selected = [p for p in xi if plays[p]]
            vacancies = [p for p in xi if not plays[p] and positions[p] != "GK"]
            shape = dict(nominal)
            first = next(p for p in xi if positions[p] == "GK")
            reserve = next(p for p in bench if positions[p] == "GK")
            if not plays[first] and plays[reserve]:
                selected.append(reserve)
            for incoming in bench:
                if not plays[incoming] or positions[incoming] == "GK":
                    continue
                for outgoing in tuple(vacancies):
                    trial = dict(shape)
                    trial[positions[outgoing]] -= 1
                    trial[positions[incoming]] += 1
                    if all(
                        low <= trial[pos] <= high
                        for pos, low, high in (("DEF", 3, 5), ("MID", 2, 5), ("FWD", 1, 3))
                    ):
                        vacancies.remove(outgoing)
                        shape = trial
                        selected.append(incoming)
                        break
        leader = captain if plays[captain] else vice if plays[vice] else None
        extra = 0.0 if leader is None else (2 if chip == "3xc" else 1) * points[leader]
        output.append(mass * (math.fsum(points[p] for p in selected) + extra))
    return math.fsum(output) - hits


def joint_native(fixtures):
    states = tuple(product(range(7), repeat=len(fixtures)))
    probabilities = tuple(
        math.prod(fixtures[index].probabilities[cell] for index, cell in enumerate(state))
        for state in states
    )
    return states, probabilities


def workload_document(
    fixtures,
    states,
    probabilities,
    *,
    player,
    position,
    club,
    season=SEASON,
    gameweek=6,
    decision_at=DECISION,
    deadline_at=DEADLINE,
    basis_sha="a" * 64,
    heavy=False,
    covered_gameweeks=(6,),
    basis_kind="prospective",
):
    """Recorded club and national exposure, not imputed from fixture counts."""
    decision = pd.Timestamp(decision_at)
    begin = decision - pd.Timedelta(days=28)
    capture = decision - pd.Timedelta(hours=1)
    provider_player = f"synthetic-provider-{player}"
    matches, club_matches = [], []
    for competition, days, physical, added, extra, team_kind in (
        ("pl", 14, 95.0, 5.0, 0.0, "club"),
        ("continental", 6, 98.0, 8.0, 0.0, "club"),
        ("cup", 4, 125.0, 5.0, 30.0, "club"),
        ("national", 2, 96.0, 6.0, 0.0, "national"),
    ):
        kickoff = decision - pd.Timedelta(days=days)
        known = physical if heavy or competition == "pl" else 0.0
        identity = f"past-{competition}-{club}"
        settled = kickoff + pd.Timedelta(hours=3)
        fact = {
            "fixture_id": identity,
            "competition_id": competition,
            "is_premier_league": competition == "pl",
            "kickoff": kickoff.isoformat(),
            "settled_at": settled.isoformat(),
            "captured_at": (settled + pd.Timedelta(minutes=10)).isoformat(),
            "published_at": (settled + pd.Timedelta(minutes=20)).isoformat(),
            "provider_player_id": provider_player,
            "registered_club_code": club,
            "team_kind": team_kind,
            "team_code": club if team_kind == "club" else 99,
            "opponent_code": 20 if team_kind == "club" else 98,
            "is_home": 1,
            "physical_minutes": known,
            "added_minutes": added if known else 0.0,
            "extra_time_minutes": extra if known else 0.0,
            "physical_minutes_convention": "includes_added_and_extra_time",
            "starts": int(known > 0),
            "recorded_exit_at": (kickoff + pd.Timedelta(minutes=physical + 20)).isoformat()
            if known
            else None,
        }
        matches.append(fact)
        if team_kind == "club":
            club_matches.append(
                {
                    key: fact[key]
                    for key in (
                        "fixture_id",
                        "competition_id",
                        "is_premier_league",
                        "kickoff",
                        "settled_at",
                        "captured_at",
                        "published_at",
                        "team_code",
                        "opponent_code",
                        "is_home",
                    )
                }
                | {
                    "recorded_end_at": (kickoff + pd.Timedelta(minutes=physical + 20)).isoformat(),
                    "target_fpl_fixture_id": None,
                }
            )
    upcoming = [
        {
            "fixture_id": f"target-{fixture.fixture_id}",
            "target_fpl_fixture_id": fixture.fixture_id,
            "competition_id": "pl",
            "is_premier_league": True,
            "kickoff": fixture.kickoff,
            "captured_at": (capture - pd.Timedelta(hours=1)).isoformat(),
            "published_at": (capture - pd.Timedelta(minutes=30)).isoformat(),
            "team_code": fixture.club_code,
            "opponent_code": fixture.opponent_code,
            "is_home": fixture.is_home,
            "recorded_end_at": None,
            "settled_at": None,
        }
        for fixture in fixtures
    ]
    if fixtures:
        upcoming.append(
            {
                "fixture_id": f"announced-cup-{club}",
                "target_fpl_fixture_id": None,
                "competition_id": "cup",
                "is_premier_league": False,
                "kickoff": (decision + pd.Timedelta(hours=4)).isoformat(),
                "captured_at": (capture - pd.Timedelta(hours=1)).isoformat(),
                "published_at": (capture - pd.Timedelta(minutes=30)).isoformat(),
                "team_code": club,
                "opponent_code": 20,
                "is_home": 1,
                "recorded_end_at": None,
                "settled_at": None,
            }
        )
    actual = []
    if heavy:
        actual.append(
            {
                "id": f"recorded-flight-{player}",
                "start_at": (decision - pd.Timedelta(hours=24)).isoformat(),
                "end_at": (decision - pd.Timedelta(hours=20)).isoformat(),
                "distance_km": 2200.0,
                "duration_hours": 4.0,
                "captured_at": (decision - pd.Timedelta(hours=19)).isoformat(),
                "published_at": (decision - pd.Timedelta(hours=18)).isoformat(),
                "evidence_ref": "synthetic-recorded-itinerary",
            }
        )
    return {
        "version": RAW_LOAD_SNAPSHOT_VERSION,
        "season": season,
        "gameweek": gameweek,
        "player_code": player,
        "position": position,
        "decision_at": decision_at,
        "deadline_at": deadline_at,
        "captured_at": capture.isoformat(),
        "published_at": (capture + pd.Timedelta(minutes=30)).isoformat(),
        "model_use_approved": True,
        "model_use_evidence_ref": "synthetic-only-invented-bytes",
        "native_basis_sha256": basis_sha,
        "native_basis_kind": basis_kind,
        "native_basis_fit_cutoff": (decision - pd.Timedelta(days=40)).isoformat(),
        "native_basis_evidence_ref": "synthetic-out-of-fold-native-receipt",
        "native_basis_version": NATIVE_BASIS_VERSION,
        "native_model_version": JOINT_ROLE_MODEL_VERSION,
        "native_joint_law_sha256": native_joint_law_digest(fixtures, states, probabilities),
        "coverage": {
            "start_at": begin.isoformat(),
            "end_at": decision_at,
            "complete": True,
            "competition_ids": list(COMPETITIONS),
            "expected_match_ids": [row["fixture_id"] for row in matches],
            "expected_club_match_ids": [row["fixture_id"] for row in club_matches],
            "expected_upcoming_fixture_ids": [row["fixture_id"] for row in upcoming],
            "evidence_ref": "synthetic-complete-four-competition-interval",
        },
        "mapping": {
            "verified": True,
            "evidence_ref": "synthetic-temporal-identity-proof",
            "player_aliases": [
                {
                    "provider_player_id": provider_player,
                    "player_code": player,
                    "valid_from": begin.isoformat(),
                    "valid_until": None,
                    "evidence_ref": "synthetic-player-map",
                }
            ],
            "club_memberships": [
                {
                    "team_code": club,
                    "valid_from": begin.isoformat(),
                    "valid_until": None,
                    "evidence_ref": "synthetic-club-registration",
                }
            ],
            "national_memberships": [
                {
                    "team_code": 99,
                    "valid_from": begin.isoformat(),
                    "valid_until": None,
                    "evidence_ref": "synthetic-national-registration",
                }
            ],
        },
        "calendar": {
            "complete": True,
            "covered_gameweeks": list(covered_gameweeks),
            "fixture_ids": [fixture.fixture_id for fixture in fixtures],
            "evidence_ref": "synthetic-complete-fpl-calendar",
        },
        "fixture_aliases": [],
        "matches": matches,
        "club_matches": club_matches,
        "upcoming_fixtures": upcoming,
        "travel": {
            "actual": {
                "complete": True,
                "evidence_ref": "synthetic-complete-travel",
                "expected_ids": [row["id"] for row in actual],
                "records": actual,
            },
            "planned": None,
            "venue_distance_proxy": None,
        },
    }


def parse_workload(document, fixtures, states, probabilities):
    raw, sha = document_bytes(document)
    return read_load_snapshot(
        raw,
        sha256=sha,
        season=document["season"],
        gameweek=document["gameweek"],
        player_code=document["player_code"],
        decision_at=document["decision_at"],
        deadline_at=document["deadline_at"],
        native_fixtures=fixtures,
        native_joint_states=states,
        native_joint_probabilities=probabilities,
        native_basis_sha256=document["native_basis_sha256"],
        required_competition_ids=COMPETITIONS,
    )


def case_documents(case, *, heavy_players=()):
    from squadopt.application.football_load_experiment import native_basis_digest

    for player in case.roster.to_dict("records"):
        for gameweek in case.gameweeks:
            rows = case.components.loc[
                case.components.player_code.eq(player["player_id"])
                & case.components.GW.eq(gameweek)
            ].sort_values("kickoff")
            fixtures = tuple(
                LoadFixture(
                    int(row.fixture),
                    str(row.kickoff),
                    int(row.club),
                    int(row.opponent),
                    int(row.home),
                    (
                        float(row.zero_probability),
                        *(
                            float(getattr(row, f"{role}_minute_probability_{b}"))
                            for role in ("start", "cameo")
                            for b in (1, 2, 3)
                        ),
                    ),
                    (
                        0.0,
                        *(
                            float(getattr(row, f"{role}_minute_value_{b}"))
                            for role in ("start", "cameo")
                            for b in (1, 2, 3)
                        ),
                    ),
                )
                for row in rows.itertuples()
            )
            states, probabilities = joint_native(fixtures)
            document = workload_document(
                fixtures,
                states,
                probabilities,
                player=int(player["player_id"]),
                position=player["position"],
                club=int(player["club_code"]),
                gameweek=gameweek,
                basis_sha=native_basis_digest(case.components),
                heavy=player["player_id"] in heavy_players,
                covered_gameweeks=case.gameweeks,
            )
            yield document, fixtures, states, probabilities


def case_inputs(case, *, heavy_players=()):
    return tuple(
        parse_workload(*parts) for parts in case_documents(case, heavy_players=heavy_players)
    )


def training_inputs():
    result = []
    for gameweek in (5, 6):
        decision = pd.Timestamp(f"2024-09-{15 if gameweek == 5 else 22}T12:00:00Z")
        deadline = decision + pd.Timedelta(hours=6)
        for heavy in (False, True):
            for repetition in range(20):
                player = 10000 + int(heavy) * 100 + repetition
                fixtures = tuple(
                    LoadFixture(
                        gameweek * 100 + i,
                        (deadline + pd.Timedelta(days=1 + 2 * i)).isoformat(),
                        1,
                        2,
                        1,
                        LAW,
                        DURATIONS,
                    )
                    for i in range(1 if gameweek == 5 else 2)
                )
                states, probabilities = joint_native(fixtures)
                document = workload_document(
                    fixtures,
                    states,
                    probabilities,
                    player=player,
                    position=("GK", "DEF", "MID", "FWD")[repetition % 4],
                    club=1,
                    season="2024-25",
                    gameweek=gameweek,
                    decision_at=decision.isoformat(),
                    deadline_at=deadline.isoformat(),
                    heavy=heavy,
                    basis_kind="out_of_fold",
                    covered_gameweeks=(gameweek,),
                )
                week = parse_workload(document, fixtures, states, probabilities)
                appears = repetition < (8 if heavy else 18)
                observed = tuple(
                    (4 if heavy else 3)
                    if appears and (not heavy or index == repetition % len(fixtures))
                    else 0
                    for index in range(len(fixtures))
                )
                settled = (pd.Timestamp(fixtures[-1].kickoff) + pd.Timedelta(hours=4)).isoformat()
                outcomes = {
                    "version": RAW_LOAD_OUTCOME_VERSION,
                    "season": week.season,
                    "gameweek": gameweek,
                    "player_code": player,
                    "input_sha256": load_input_digest(week),
                    "settled_at": settled,
                    "captured_at": settled,
                    "published_at": settled,
                    "model_use_approved": True,
                    "model_use_evidence_ref": "synthetic-only-invented-outcomes",
                    "mapping_verified": True,
                    "mapping_evidence_ref": "synthetic-player-map",
                    "calendar_complete": True,
                    "covered_gameweeks": list(week.covered_gameweeks),
                    "fixture_ids": [fixture.fixture_id for fixture in fixtures],
                    "observations": [
                        {
                            "fixture_id": fixture.fixture_id,
                            "kickoff": fixture.kickoff,
                            "club_code": fixture.club_code,
                            "opponent_code": fixture.opponent_code,
                            "is_home": fixture.is_home,
                            "minutes": int(fixture.minutes[state]),
                            "starts": int(1 <= state <= 3),
                            "state": state,
                        }
                        for fixture, state in zip(fixtures, observed, strict=True)
                    ],
                }
                raw, sha = document_bytes(outcomes)
                result.append(
                    read_load_outcomes(
                        raw,
                        sha256=sha,
                        week=week,
                        fit_cutoff=FIT_CUTOFF,
                        target_season=SEASON,
                        target_gameweeks=(6, 7),
                    )
                )
    return tuple(result)
