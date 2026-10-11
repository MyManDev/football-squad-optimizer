"""Invented native clubs, explicit physical profiles and raw score-event sources."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from itertools import product

import numpy as np
import pandas as pd
from scipy.integrate import solve_ivp
from scipy.stats import nbinom

from squadopt.features.football_score_state_inputs import (
    CLOCK_VERSION,
    RAW_SCORE_OUTCOME_VERSION,
    RAW_SCORE_SNAPSHOT_VERSION,
    read_score_outcomes,
    read_score_snapshot,
    score_input_digest,
)
from squadopt.prediction.football import JOINT_ROLE_MODEL_VERSION
from squadopt.prediction.football_minutes_role import ROLE_MINUTE_VERSION

SEASON = "2026-27"
DECISION = "2026-09-22T12:00:00Z"
DEADLINE = "2026-09-22T18:00:00Z"
FIT_CUTOFF = "2025-06-01T00:00:00Z"
PROBABILITIES = (0.12, 0.08, 0.12, 0.43, 0.10, 0.15, 0.0)
MINUTES = (0.0, 20.0, 70.0, 90.0, 10.0, 65.0, 90.0)
PHYSICAL_DURATION = 95.0
XI = (1, 3, 4, 5, 8, 9, 10, 11, 13, 14, 15)
BENCH = (2, 6, 7, 12)


@dataclass(frozen=True)
class ScoreCase:
    native: pd.DataFrame
    weekly: pd.DataFrame
    roster: pd.DataFrame
    calendar: pd.DataFrame
    eligibility: dict[int, float]
    resources: dict[str, object]
    gameweeks: tuple[int, ...]


def encode(document):
    raw = json.dumps(document, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return raw, hashlib.sha256(raw).hexdigest()


def native_moments(row, probabilities=PROBABILITIES, minutes=MINUTES):
    q = math.fsum(probabilities[1:])
    mean = math.fsum(p * m for p, m in zip(probabilities, minutes, strict=True))
    p60 = math.fsum(p for p, m in zip(probabilities, minutes, strict=True) if m >= 60)
    clean = math.fsum(
        p * math.exp(-row["opponent_goal_rate"] * m / 90)
        for p, m in zip(probabilities, minutes, strict=True)
        if m >= 60
    )
    defensive = (
        0.0
        if row["position"] == "GK"
        else math.fsum(
            p
            * nbinom.sf(
                (10 if row["position"] == "DEF" else 12) - 1,
                row["defcon_dispersion"],
                row["defcon_dispersion"]
                / (row["defcon_dispersion"] + max(row["defcon_rate90"] * m / 90, 1e-12)),
            )
            for p, m in zip(probabilities[1:], minutes[1:], strict=True)
        )
    )
    result = {
        "appearance_probability": q,
        "p60": p60,
        "expected_minutes": mean,
        "zero_probability": probabilities[0],
        "unknown_role_probability": 0.0,
        "expected_minutes_if_appearance": mean / q if q else 0.0,
        "start_probability": math.fsum(probabilities[1:4]),
        "cameo_probability": math.fsum(probabilities[4:]),
        "clean_sheet_probability": clean,
        "defcon_probability": defensive,
    }
    for role, begin in (("start", 1), ("cameo", 4)):
        for bucket in range(1, 4):
            result[f"{role}_minute_probability_{bucket}"] = probabilities[begin + bucket - 1]
            result[f"{role}_minute_value_{bucket}"] = minutes[begin + bucket - 1]
    for bucket, cells in enumerate(((0,), (1, 4), (2, 5), (3, 6))):
        mass = math.fsum(probabilities[i] for i in cells)
        result[f"minute_probability_{bucket}"] = mass
        result[f"minute_value_{bucket}"] = (
            math.fsum(probabilities[i] * minutes[i] for i in cells) / mass
            if mass
            else (0.0, 30.0, 75.0, 90.0)[bucket]
        )
    raw = math.fsum(
        (
            q,
            p60,
            {"GK": 10, "DEF": 6, "MID": 5, "FWD": 4}[row["position"]] * row["goals"],
            3 * row["assists"],
            {"GK": 4, "DEF": 4, "MID": 1, "FWD": 0}[row["position"]] * clean,
            2 * defensive,
            q * row["residual_if_appearance"],
        )
    )
    result.update(raw_expected_points=raw, expected_points=max(0.0, raw))
    return result


def invented_case(*, double=False, blank=False):
    quotas = ("GK", "GK", *("DEF",) * 5, *("MID",) * 5, *("FWD",) * 3)
    roster = pd.DataFrame(
        [
            {
                "player_id": pid,
                "name": f"Score Player {pid}",
                "club_code": 1 + (pid - 1) % 6,
                "team_id": 1 + (pid - 1) % 6,
                "position": quotas[pid - 1] if pid <= 15 else "MID",
                "buy_price_tenths": 50 + pid % 7,
                "sell_price_tenths": 49 + pid % 7,
                "ownership_receipt": f"synthetic-owned-{pid}",
            }
            for pid in range(1, 67)
        ]
    )
    roster.attrs["native_private_inventory"] = {"bank": 17, "owned": list(range(1, 16))}
    games = [
        (61, 1, 2, 2.6, 0.7, "2026-09-23T15:00:00Z"),
        (62, 3, 4, 1.3, 1.9, "2026-09-23T17:00:00Z"),
        (63, 5, 6, 0.8, 2.5, "2026-09-24T15:00:00Z"),
    ]
    if double:
        games.append((69, 3, 4, 1.3, 1.9, "2026-09-25T15:00:00Z"))
    if blank:
        games = []
    components, sides = [], []
    for fixture, home_club, away_club, home_goals, away_goals, kickoff in games:
        for club, opponent, home, intensity, opposing in (
            (home_club, away_club, 1, home_goals, away_goals),
            (away_club, home_club, 0, away_goals, home_goals),
        ):
            side = {
                "fixture": fixture,
                "club": club,
                "opponent": opponent,
                "home": home,
                "GW": 6,
                "kickoff": kickoff,
                "decision_at": DECISION,
            }
            sides.append(side)
            for person in roster.loc[roster.club_code.eq(club)].to_dict("records"):
                pid = person["player_id"]
                row = {
                    **side,
                    "player_code": pid,
                    "position": person["position"],
                    "season": SEASON,
                    "model_version": JOINT_ROLE_MODEL_VERSION,
                    "minute_role_version": ROLE_MINUTE_VERSION,
                    "minute_role_status": "fitted_known_start_labels",
                    "known_start_label_rows": 80,
                    "unknown_start_label_rows": 0,
                    "minute_prior_rows": 10.0,
                    "team_goal_rate": intensity,
                    "opponent_goal_rate": opposing,
                    "goals_share": 1 / 11,
                    "assists_share": 1 / 11,
                    "goals": 0.6 * intensity / 11,
                    "assists": 0.3 * intensity / 11,
                    "defcon_rate90": 11.0,
                    "defcon_dispersion": 2.0,
                    "availability_multiplier": 1.0,
                    "residual_if_appearance": {3: 2.0, 8: 3.0, 6: 1.0, 66: -30.0}.get(pid, 0.0),
                }
                row.update(native_moments(row))
                components.append(row)
    native = pd.DataFrame(components) if components else invented_case().native.iloc[:0].copy()
    calendar = pd.DataFrame(
        sides, columns=("fixture", "club", "opponent", "home", "GW", "kickoff", "decision_at")
    )
    calendar.attrs.update(calendar_complete=True, covered_gameweeks=(6,))
    eligibility = {pid: {3: 0.75, 6: 0.5, 7: 0.0, 13: 0.25}.get(pid, 1.0) for pid in range(1, 67)}
    _, availability_sha = encode({"synthetic_original_eligibility": eligibility})
    native.attrs.update(
        season=SEASON,
        native_cutoff=DECISION,
        joint_role=True,
        calendar_complete=True,
        covered_gameweeks=(6,),
        availability_application="not_applied",
        captured_availability_sha256=availability_sha,
        captured_availability_evidence_ref="synthetic-only-original-operator-snapshot",
    )
    weekly = pd.DataFrame(
        [
            {
                **person,
                "gameweek": 6,
                "expected_points": eligibility[person["player_id"]]
                * math.fsum(rows.expected_points),
                "appearance_probability": eligibility[person["player_id"]]
                * (1 - math.prod(1 - q for q in rows.appearance_probability)),
            }
            for person in roster.to_dict("records")
            for rows in [native.loc[native.player_code.eq(person["player_id"])]]
        ]
    )
    weekly.attrs["original_receipt"] = "synthetic-private-native-served-values"
    resources = {
        "owned": list(range(1, 16)),
        "bank_tenths": 17,
        "free_transfers": 2,
        "chips": {"bboost": True, "3xc": True},
        "transfer_policy": {"hit_cost": 4},
    }
    return ScoreCase(native, weekly, roster, calendar, eligibility, resources, (6,))


def snapshot_document(
    *,
    season,
    gameweek,
    fixture_id,
    decision,
    deadline,
    kickoff,
    home,
    away,
    home_goals,
    away_goals,
    people,
    basis,
    version=JOINT_ROLE_MODEL_VERSION,
):
    stamp = pd.Timestamp(decision)
    capture = (stamp - pd.Timedelta(hours=1)).isoformat()
    earlier = (stamp - pd.Timedelta(hours=2)).isoformat()
    projection = {
        "season": season,
        "gameweek": gameweek,
        "fixture_id": fixture_id,
        "decision_at": decision,
        "deadline_at": deadline,
        "kickoff": kickoff,
        "home_club_code": home,
        "away_club_code": away,
        "native_home_goals": home_goals,
        "native_away_goals": away_goals,
        "forecast_duration": PHYSICAL_DURATION,
        "clock_version": CLOCK_VERSION,
        "players": people,
        "native_basis_sha256": basis,
        "native_model_version": version,
        "native_basis_kind": "prospective",
        "native_basis_fit_cutoff": (stamp - pd.Timedelta(days=30)).isoformat(),
        "native_basis_evidence_ref": "synthetic-native-producer-before-decision",
        "coverage_evidence_ref": "synthetic-complete-paired-exposure",
        "calendar_evidence_ref": "synthetic-paired-calendar",
    }
    return {
        "version": RAW_SCORE_SNAPSHOT_VERSION,
        "captured_at": capture,
        "published_at": (stamp - pd.Timedelta(minutes=30)).isoformat(),
        "rights": {"model_use_claim": True, "evidence_ref": "synthetic-only-invented-source"},
        "native_basis_clock": {"captured_at": earlier, "published_at": earlier},
        "coverage": {
            "complete": True,
            "physical_clock_known": True,
            "exit_policies_known": True,
            "player_codes": [person["player_code"] for person in people],
            "evidence_ref": projection["coverage_evidence_ref"],
        },
        "calendar": [
            {
                "fixture_id": fixture_id,
                "club_code": club,
                "opponent_code": opponent,
                "home": int(club == home),
                "kickoff": kickoff,
                "available_at": earlier,
                "evidence_ref": projection["calendar_evidence_ref"],
            }
            for club, opponent in ((home, away), (away, home))
        ],
        "club_mapping": [
            {
                "club_code": club,
                "provider_id": f"invented-club-{club}",
                "available_at": earlier,
                "evidence_ref": "synthetic-club-map",
            }
            for club in (home, away)
        ],
        "person_mapping": [
            {
                "player_code": person["player_code"],
                "club_code": person["club_code"],
                "provider_id": f"invented-person-{person['player_code']}",
                "available_at": earlier,
                "evidence_ref": "synthetic-person-map",
            }
            for person in people
        ],
        "projection": projection,
    }


def explicit_person(player, club, position, probabilities=PROBABILITIES, minutes=MINUTES):
    # These physical profiles are invented source facts, not inferred by the application.
    on, off, policies = [], [], []
    for state, m in enumerate(minutes):
        if state == 0:
            start, end, policy = 0.0, 0.0, "not_playing"
        elif state in (3, 6):
            start, end, policy = 0.0, PHYSICAL_DURATION, "full_time"
        elif state <= 3:
            start, end = 0.0, PHYSICAL_DURATION * m / 90
            policy = "full_time" if end == PHYSICAL_DURATION else "normal_substitution"
        else:
            start, end, policy = PHYSICAL_DURATION * (1 - m / 90), PHYSICAL_DURATION, "full_time"
        on.append(start)
        off.append(end)
        policies.append(policy)
    return {
        "player_code": player,
        "club_code": club,
        "position": position,
        "probabilities": list(probabilities),
        "credited_minutes": list(minutes),
        "physical_on": on,
        "physical_off": off,
        "exit_policies": policies,
        "minute_representation": "seven_roles" if len(minutes) == 7 else "four_bins",
    }


def parse_snapshot(document):
    raw, sha = encode(document)
    p = document["projection"]
    return read_score_snapshot(
        raw,
        sha256=sha,
        season=p["season"],
        gameweek=p["gameweek"],
        fixture_id=p["fixture_id"],
        decision_at=p["decision_at"],
        deadline_at=p["deadline_at"],
        native_basis_sha256=p["native_basis_sha256"],
    )


def case_documents(case):
    from squadopt.application.football_score_state_experiment import native_basis_digest

    for fixture, rows in case.native.groupby("fixture", sort=False):
        home = rows.loc[rows.home.eq(1)].iloc[0]
        away = rows.loc[rows.home.eq(0)].iloc[0]
        people = []
        for row in rows.itertuples():
            if row.model_version == "football_team_share_v1":
                probabilities = tuple(
                    float(getattr(row, f"minute_probability_{b}")) for b in range(4)
                )
                minutes = tuple(float(getattr(row, f"minute_value_{b}")) for b in range(4))
            else:
                probabilities = (
                    float(row.zero_probability),
                    *(
                        float(getattr(row, f"{role}_minute_probability_{b}"))
                        for role in ("start", "cameo")
                        for b in (1, 2, 3)
                    ),
                )
                minutes = (
                    0.0,
                    *(
                        float(getattr(row, f"{role}_minute_value_{b}"))
                        for role in ("start", "cameo")
                        for b in (1, 2, 3)
                    ),
                )
            people.append(
                explicit_person(
                    int(row.player_code), int(row.club), row.position, probabilities, minutes
                )
            )
        yield snapshot_document(
            season=SEASON,
            gameweek=6,
            fixture_id=int(fixture),
            decision=DECISION,
            deadline=DEADLINE,
            kickoff=str(home.kickoff),
            home=int(home.club),
            away=int(away.club),
            home_goals=float(home.team_goal_rate),
            away_goals=float(away.team_goal_rate),
            people=people,
            basis=native_basis_digest(case.native),
            version=str(home.model_version),
        )


def case_inputs(case):
    return tuple(parse_snapshot(document) for document in case_documents(case))


def invented_training():
    training = []
    # Two dated seasons with copied synthetic schedules, not historical outcomes.
    for season, year in (("2023-24", 2023), ("2024-25", 2024)):
        for number in range(8):
            decision = f"{year}-09-22T12:00:00Z"
            deadline = f"{year}-09-22T18:00:00Z"
            kickoff = f"{year}-09-23T15:00:00Z"
            people = [
                explicit_person(pid, club, "MID")
                for club, start in ((1, 101), (2, 201))
                for pid in range(start, start + 11)
            ]
            document = snapshot_document(
                season=season,
                gameweek=6,
                fixture_id=year * 100 + number,
                decision=decision,
                deadline=deadline,
                kickoff=kickoff,
                home=1,
                away=2,
                home_goals=1.5,
                away_goals=1.5,
                people=people,
                basis="a" * 64,
            )
            document["projection"]["native_basis_kind"] = "out_of_fold"
            fixture = parse_snapshot(document)
            # The trailing side often equalises, then the newly trailing side scores.
            timeline = ((5.0, 1), (18.0, 2), (36.0, 2), (47.0, 1), (65.0, 1), (84.0, 2))
            if number % 2:
                timeline = tuple((clock, 3 - club) for clock, club in timeline)
            events, credits = [], []
            for ordinal, (elapsed, club) in enumerate(timeline, 1):
                person = 101 if club == 1 else 201
                event = f"synthetic-{year}-{number}-{ordinal}"
                period = 1 if elapsed <= 48.0 else 2
                events.append(
                    {
                        "event_id": event,
                        "elapsed": elapsed,
                        "period": period,
                        "period_elapsed": elapsed if period == 1 else elapsed - 48.0,
                        "beneficiary_club_code": club,
                        "scorer_club_code": club,
                        "scorer_player_code": person,
                        "own_goal": False,
                        "ordinal": ordinal,
                    }
                )
                credits.append(
                    {
                        "goal_event_id": event,
                        "scorer_player_code": person,
                        "assist_player_code": person + 1,
                    }
                )
            settled = (pd.Timestamp(kickoff) + pd.Timedelta(hours=3)).isoformat()
            outcome = {
                "goals": events,
                "periods": [{"period": 1, "duration": 48.0}, {"period": 2, "duration": 47.0}],
                "actual_duration": 95.0,
                "final_home_goals": 3,
                "final_away_goals": 3,
                "fpl_credits": credits,
                "exposures": [
                    {
                        "player_code": p["player_code"],
                        "club_code": p["club_code"],
                        "physical_on": 0.0,
                        "physical_off": 95.0,
                        "credited_minutes": 90,
                        "starts": 1,
                        "exit_policy": "full_time",
                    }
                    for p in people
                ],
                "settled_at": settled,
                "dismissal_events": [],
            }
            source = {
                "version": RAW_SCORE_OUTCOME_VERSION,
                "season": season,
                "gameweek": 6,
                "fixture_id": fixture.fixture_id,
                "input_sha256": score_input_digest(fixture),
                "captured_at": settled,
                "published_at": settled,
                "rights": {
                    "model_use_claim": True,
                    "evidence_ref": "synthetic-only-invented-final-events",
                },
                "coverage": {
                    "physical_events_complete": True,
                    "physical_periods_complete": True,
                    "physical_exposures_complete": True,
                    "fpl_credits_complete": True,
                    "fpl_credit_scope": "final_fpl_goal_assist_credits_v1",
                    "dismissals_complete": True,
                    "evidence_ref": "synthetic-complete-chronological-final-observations",
                },
                "outcome": outcome,
            }
            raw, sha = encode(source)
            training.append(
                read_score_outcomes(
                    raw,
                    sha256=sha,
                    fixture=fixture,
                    fit_cutoff=FIT_CUTOFF,
                    target_season=SEASON,
                    target_gameweeks=(6,),
                )
            )
    return tuple(training)


def independent_process_moments(fixture, coefficients, *, maximum_goals=14):
    """A full home/away score lattice ODE, independent of the difference solver."""
    width = maximum_goals + 1
    home_counts, away_counts = np.meshgrid(np.arange(width), np.arange(width), indexing="ij")
    difference = home_counts - away_counts
    horizon = fixture.forecast_duration
    base_home, base_away = fixture.native_home_goals / horizon, fixture.native_away_goals / horizon

    def integrate(begin, end, initial, *, no_concede_for=None):
        current = initial
        for phase in range(3):
            left, right = max(begin, phase * horizon / 3), min(end, (phase + 1) * horizon / 3)
            if right <= left:
                continue
            leader, trailer = coefficients[2 * phase : 2 * phase + 2]
            home_rate = base_home * np.exp(
                np.where(difference > 0, leader, np.where(difference < 0, trailer, 0.0))
            )
            away_rate = base_away * np.exp(
                np.where(difference < 0, leader, np.where(difference > 0, trailer, 0.0))
            )

            def derivative(_time, state, home_rate=home_rate, away_rate=away_rate):
                p = state[: width * width].reshape(width, width)
                change = -(home_rate + away_rate) * p
                if no_concede_for != fixture.away_club_code:
                    change[1:, :] += home_rate[:-1, :] * p[:-1, :]
                if no_concede_for != fixture.home_club_code:
                    change[:, 1:] += away_rate[:, :-1] * p[:, :-1]
                rewards = (float(np.sum(p * home_rate)), float(np.sum(p * away_rate)))
                return np.concatenate((change.ravel(), np.array(rewards)))

            solved = solve_ivp(
                derivative, (left, right), current, method="DOP853", rtol=2e-11, atol=2e-13
            )
            assert solved.success
            current = solved.y[:, -1]
        return current

    initial = np.zeros(width * width + 2)
    initial[0] = 1.0
    final = integrate(0.0, horizon, initial)
    assert final[: width * width].sum() > 1 - 2e-7
    survival, cache = {}, {}
    for player in fixture.players:
        values = []
        for _probability, entry, exit_at in zip(
            player.probabilities, player.physical_on, player.physical_off, strict=True
        ):
            if entry == exit_at:
                values.append(0.0)
                continue
            key = (player.club_code, entry, exit_at)
            if key not in cache:
                before = integrate(0.0, entry, initial)
                interval = integrate(entry, exit_at, before, no_concede_for=player.club_code)
                cache[key] = float(interval[: width * width].sum())
            values.append(cache[key])
        survival[player.player_code] = tuple(values)
    return float(final[-2]), float(final[-1]), survival


def independent_lineup_score(squad, xi, bench, captain, vice, *, chip=None, hits=0.0):
    """Enumerate appearances and legal bench replacement slots directly."""
    people = squad.set_index("player_id").to_dict("index")
    ids = tuple(people)
    q = {pid: people[pid]["appearance_probability"] for pid in ids}
    mu = {pid: people[pid]["expected_points"] / q[pid] if q[pid] else 0.0 for pid in ids}
    position = {pid: people[pid]["position"] for pid in ids}
    shape = {p: sum(position[pid] == p for pid in xi) for p in ("DEF", "MID", "FWD")}
    terms = []
    for vector in product((0, 1), repeat=15):
        appears = dict(zip(ids, vector, strict=True))
        mass = math.prod(q[pid] if appears[pid] else 1 - q[pid] for pid in ids)
        if not mass:
            continue
        selected = [pid for pid in (ids if chip == "bboost" else xi) if appears[pid]]
        if chip != "bboost":
            starter = next(pid for pid in xi if position[pid] == "GK")
            reserve = next(pid for pid in bench if position[pid] == "GK")
            if not appears[starter] and appears[reserve]:
                selected.append(reserve)
            vacancies = [pid for pid in xi if not appears[pid] and position[pid] != "GK"]
            current = dict(shape)
            for incoming in bench:
                if not appears[incoming] or position[incoming] == "GK":
                    continue
                for outgoing in tuple(vacancies):
                    proposed = dict(current)
                    proposed[position[outgoing]] -= 1
                    proposed[position[incoming]] += 1
                    if all(
                        low <= proposed[p] <= high
                        for p, low, high in (("DEF", 3, 5), ("MID", 2, 5), ("FWD", 1, 3))
                    ):
                        selected.append(incoming)
                        vacancies.remove(outgoing)
                        current = proposed
                        break
        leader = captain if appears[captain] else vice if appears[vice] else None
        bonus = (2 if chip == "3xc" else 1) * mu[leader] if leader is not None else 0.0
        terms.append(mass * (math.fsum(mu[pid] for pid in selected) + bonus))
    return math.fsum(terms) - hits
