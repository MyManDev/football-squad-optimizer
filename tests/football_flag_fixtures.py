"""Independent synthetic native basis and numerical oracles for flag experiments."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256
from itertools import product
from math import exp, fsum, prod

import pandas as pd
from scipy.stats import nbinom

from squadopt.features.football_flag_inputs import (
    RAW_FLAG_CAPTURE_VERSION,
    RAW_FLAG_OUTCOME_VERSION,
    MinuteFixture,
    PlayerWeekInput,
    TrainingWeek,
    input_digest,
    read_flag_outcome_source,
    read_flag_week_source,
)
from squadopt.prediction.football import JOINT_ROLE_MODEL_VERSION
from squadopt.prediction.football_minutes_role import ROLE_MINUTE_VERSION

SEASON = "2026-27"
DECISION_AT = "2026-09-22T12:00:00+00:00"
DEADLINE_AT = "2026-09-22T18:00:00+00:00"
FIT_CUTOFF = "2025-06-01T12:00:00+00:00"
GAMEWEEK = 6
XI = (1, 3, 4, 5, 8, 9, 10, 11, 13, 14, 15)
BENCH = (2, 6, 7, 12)
STATE_MINUTES = (0.0, 45.0, 75.0, 90.0, 15.0, 65.0, 90.0)
STATE_PROBABILITIES = (0.1, 0.05, 0.1, 0.55, 0.1, 0.05, 0.05)
STATE_BINS = (0, 1, 2, 3, 1, 2, 3)


@dataclass(frozen=True)
class NativeFlagCase:
    components: pd.DataFrame
    weekly: pd.DataFrame
    roster: pd.DataFrame
    calendar: pd.DataFrame
    resource_bundle: dict[str, object]
    captured_availability: dict[int, float]
    gameweeks: tuple[int, ...]


def encoded(document: Mapping[str, object]) -> tuple[bytes, str]:
    raw = json.dumps(document, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return raw, sha256(raw).hexdigest()


def raw_week_document(
    fixtures: tuple[MinuteFixture, ...],
    *,
    season: str,
    gameweek: int,
    player_code: int,
    position: str,
    label: int | None,
    decision_at: str,
    deadline_at: str,
    native_basis_sha256: str,
    native_basis_kind: str = "prospective",
    native_basis_fit_cutoff: str = FIT_CUTOFF,
    covered_gameweeks: tuple[int, ...] | None = None,
    previous_label: int | None = None,
) -> dict[str, object]:
    """Original source fields, not generated participation probabilities."""
    decision = pd.Timestamp(decision_at)
    news = None if label is None else "" if label == 100 else "Synthetic dated fitness report"
    news_added = None if label in (None, 100) else (decision - pd.Timedelta(hours=6)).isoformat()
    captures = []
    for offset in (4, 3):
        current_label = previous_label if offset == 4 and previous_label is not None else label
        captures.append(
            {
                "captured_at": (decision - pd.Timedelta(hours=offset)).isoformat(),
                "published_at": (decision - pd.Timedelta(hours=offset - 0.5)).isoformat(),
                "element_id": player_code + 1000,
                "player_code": player_code,
                "club_code": fixtures[0].club if fixtures else 1,
                "current_event_id": gameweek,
                "next_event_id": gameweek + 1 if gameweek < 38 else None,
                "status": None if label is None else "a" if label == 100 else "d",
                "chance_of_playing_this_round": current_label,
                "chance_of_playing_next_round": current_label,
                "news": news,
                "news_added": news_added,
            }
        )
    return {
        "version": RAW_FLAG_CAPTURE_VERSION,
        "season": season,
        "gameweek": gameweek,
        "player_code": player_code,
        "position": position,
        "mapping_verified": True,
        "mapping_evidence_ref": "synthetic-persistent-player-map",
        "model_use_approved": True,
        "model_use_evidence_ref": "synthetic-only-created-test-bytes",
        "calendar_complete": True,
        "covered_gameweeks": list(covered_gameweeks or (gameweek,)),
        "fixture_ids": [fixture.fixture for fixture in fixtures],
        "calendar_evidence_ref": "synthetic-complete-calendar",
        "history_covered": True,
        "history_start_at": captures[0]["captured_at"],
        "history_end_at": captures[-1]["captured_at"],
        "expected_capture_count": 2,
        "history_evidence_ref": "synthetic-complete-two-capture-history",
        "captures": captures,
        "native_basis_sha256": native_basis_sha256,
        "native_basis_evidence_ref": "synthetic-native-fold-receipt",
        "native_basis_kind": native_basis_kind,
        "native_basis_fit_cutoff": native_basis_fit_cutoff,
    }


def parse_week_document(
    document: Mapping[str, object],
    fixtures: tuple[MinuteFixture, ...],
    *,
    decision_at: str = DECISION_AT,
    deadline_at: str = DEADLINE_AT,
) -> PlayerWeekInput:
    raw, digest = encoded(document)
    return read_flag_week_source(
        raw,
        sha256=digest,
        season=str(document["season"]),
        gameweek=int(document["gameweek"]),
        player_code=int(document["player_code"]),
        decision_at=decision_at,
        deadline_at=deadline_at,
        native_fixtures=fixtures,
        native_basis_sha256=str(document["native_basis_sha256"]),
    )


def case_week_documents(
    case: NativeFlagCase,
    *,
    labels: Mapping[int, int | None] | None = None,
) -> tuple[tuple[dict[str, object], tuple[MinuteFixture, ...]], ...]:
    from squadopt.application.football_flag_experiment import native_basis_digest

    basis = native_basis_digest(case.components)
    label_by_id = {p: int(100 * value) for p, value in case.captured_availability.items()}
    label_by_id.update({} if labels is None else labels)
    output = []
    for gameweek in case.gameweeks:
        for player in case.roster.to_dict("records"):
            selected = case.components.loc[
                case.components.player_code.eq(player["player_id"])
                & case.components.GW.eq(gameweek)
            ].sort_values("kickoff")
            fixtures = tuple(
                MinuteFixture(
                    int(row["fixture"]),
                    str(row["kickoff"]),
                    int(row["club"]),
                    int(row["opponent"]),
                    int(row["home"]),
                    (
                        float(row["zero_probability"]),
                        *(
                            float(row[f"{role}_minute_probability_{b}"])
                            for role in ("start", "cameo")
                            for b in (1, 2, 3)
                        ),
                    ),
                    (
                        0.0,
                        *(
                            float(row[f"{role}_minute_value_{b}"])
                            for role in ("start", "cameo")
                            for b in (1, 2, 3)
                        ),
                    ),
                )
                for row in selected.to_dict("records")
            )
            document = raw_week_document(
                fixtures,
                season=SEASON,
                gameweek=gameweek,
                player_code=int(player["player_id"]),
                position=str(player["position"]),
                label=label_by_id[int(player["player_id"])],
                decision_at=DECISION_AT,
                deadline_at=DEADLINE_AT,
                native_basis_sha256=basis,
                covered_gameweeks=case.gameweeks,
            )
            output.append((document, fixtures))
    return tuple(output)


def case_inputs(
    case: NativeFlagCase,
    *,
    labels: Mapping[int, int | None] | None = None,
) -> tuple[PlayerWeekInput, ...]:
    return tuple(
        parse_week_document(document, fixtures)
        for document, fixtures in case_week_documents(case, labels=labels)
    )


def training_weeks() -> tuple[TrainingWeek, ...]:
    """Raw synthetic settled weeks; categorical ordering is deliberately not imposed."""
    output = []
    appearances = {0: 2, 25: 14, 50: 7, 75: 10, 100: 19, None: 12}
    role_states = {0: 4, 25: 4, 50: 3, 75: 2, 100: 3, None: 1}
    for gameweek, count in ((5, 1), (6, 2)):
        decision = f"2024-09-{15 if gameweek == 5 else 22}T12:00:00+00:00"
        deadline = f"2024-09-{15 if gameweek == 5 else 22}T18:00:00+00:00"
        for category, label in enumerate((0, 25, 50, 75, 100, None)):
            for repetition in range(20):
                player = 10000 + category * 20 + repetition
                fixtures = tuple(
                    MinuteFixture(
                        gameweek * 100 + index,
                        (pd.Timestamp(deadline) + pd.Timedelta(days=1 + index)).isoformat(),
                        1,
                        2,
                        1,
                        STATE_PROBABILITIES,
                        STATE_MINUTES,
                    )
                    for index in range(count)
                )
                document = raw_week_document(
                    fixtures,
                    season="2024-25",
                    gameweek=gameweek,
                    player_code=player,
                    position=("GK", "DEF", "MID", "FWD")[repetition % 4],
                    label=label,
                    decision_at=decision,
                    deadline_at=deadline,
                    native_basis_sha256=sha256(
                        f"synthetic-native-fold-{gameweek}".encode()
                    ).hexdigest(),
                    native_basis_kind="out_of_fold",
                    native_basis_fit_cutoff="2024-09-01T12:00:00+00:00",
                )
                week = parse_week_document(
                    document, fixtures, decision_at=decision, deadline_at=deadline
                )
                appears = repetition < appearances[label]
                observed = tuple(
                    role_states[label]
                    if appears and (count == 1 or index == repetition % count)
                    else 0
                    for index in range(count)
                )
                settled = (pd.Timestamp(fixtures[-1].kickoff) + pd.Timedelta(hours=6)).isoformat()
                outcome = {
                    "version": RAW_FLAG_OUTCOME_VERSION,
                    "season": week.season,
                    "gameweek": week.gameweek,
                    "player_code": week.player_code,
                    "input_sha256": input_digest(week),
                    "settled_at": settled,
                    "captured_at": settled,
                    "published_at": settled,
                    "mapping_verified": True,
                    "mapping_evidence_ref": "synthetic-settled-player-map",
                    "model_use_approved": True,
                    "model_use_evidence_ref": "synthetic-only-created-test-labels",
                    "calendar_complete": True,
                    "covered_gameweeks": [gameweek],
                    "fixture_ids": [fixture.fixture for fixture in fixtures],
                    "observations": [
                        {
                            "fixture": fixture.fixture,
                            "kickoff": fixture.kickoff,
                            "club": fixture.club,
                            "opponent": fixture.opponent,
                            "home": fixture.home,
                            "minutes": int(fixture.minutes[state]),
                            "starts": int(1 <= state <= 3),
                            "state": state,
                        }
                        for fixture, state in zip(fixtures, observed, strict=True)
                    ],
                }
                raw, digest = encoded(outcome)
                output.append(
                    read_flag_outcome_source(
                        raw,
                        sha256=digest,
                        week=week,
                        fit_cutoff=FIT_CUTOFF,
                        target_season=SEASON,
                        target_gameweeks=(6, 7),
                    )
                )
    return tuple(output)


def minute_marginals(probabilities: Sequence[float], minutes: Sequence[float]) -> dict[str, float]:
    """Sum explicit support, rather than invoking any production component scorer."""
    result = {
        "appearance_probability": fsum(probabilities[1:]),
        "expected_minutes": fsum(p * m for p, m in zip(probabilities, minutes, strict=True)),
        "p60": fsum(p for p, m in zip(probabilities, minutes, strict=True) if m >= 60),
    }
    for b in range(4):
        support = [i for i, value in enumerate(STATE_BINS) if value == b]
        mass = fsum(probabilities[i] for i in support)
        result[f"minute_probability_{b}"] = mass
        result[f"minute_value_{b}"] = (
            fsum(probabilities[i] * minutes[i] for i in support) / mass
            if mass
            else (0.0, 30.0, 75.0, 90.0)[b]
        )
        if b == 3:
            result[f"minute_value_{b}"] = 90.0
    for role, offset in (("start", 1), ("cameo", 4)):
        result[role + "_probability"] = fsum(probabilities[offset : offset + 3])
        for b in (1, 2, 3):
            result[f"{role}_minute_probability_{b}"] = probabilities[offset + b - 1]
            result[f"{role}_minute_value_{b}"] = minutes[offset + b - 1]
    result["zero_probability"] = probabilities[0]
    result["unknown_role_probability"] = 0.0
    q = result["appearance_probability"]
    result["expected_minutes_if_appearance"] = result["expected_minutes"] / q if q else 0.0
    return result


def component_oracle(
    row: Mapping[str, object], probabilities: Sequence[float], minutes: Sequence[float]
) -> dict[str, float]:
    result = minute_marginals(probabilities, minutes)
    opponent = float(row["opponent_goal_rate"])
    result["clean_sheet_probability"] = fsum(
        p * exp(-opponent * m / 90) for p, m in zip(probabilities, minutes, strict=True) if m >= 60
    )
    position = str(row["position"])
    threshold = 10 if position == "DEF" else 12
    dispersion = float(row["defcon_dispersion"])
    rate = float(row["defcon_rate90"])
    result["defcon_probability"] = (
        0.0
        if position == "GK"
        else fsum(
            p
            * float(
                nbinom.sf(
                    threshold - 1,
                    dispersion,
                    dispersion / (dispersion + max(rate * m / 90, 1e-12)),
                )
            )
            for p, m in zip(probabilities[1:], minutes[1:], strict=True)
        )
    )
    goal = {"GK": 10, "DEF": 6, "MID": 5, "FWD": 4}[position]
    clean = {"GK": 4, "DEF": 4, "MID": 1, "FWD": 0}[position]
    raw = fsum(
        (
            result["appearance_probability"],
            result["p60"],
            goal * float(row["goals"]),
            3 * float(row["assists"]),
            clean * result["clean_sheet_probability"],
            2 * result["defcon_probability"],
            result["appearance_probability"] * float(row["residual_if_appearance"]),
        )
    )
    result["raw_expected_points"] = raw
    result["expected_points"] = max(0.0, raw)
    return result


def native_case(
    *,
    double: bool = False,
    blank: bool = False,
    extra_week: bool = False,
    residuals: Mapping[int, float] | None = None,
    uncertain_players: Sequence[int] | None = None,
) -> NativeFlagCase:
    """Six full clubs, a legal fixed15, paired fixtures and explicit old eligibility."""
    positions = ["GK"] * 2 + ["DEF"] * 5 + ["MID"] * 5 + ["FWD"] * 3
    clubs = {p: 1 + (p - 1) % 6 for p in range(1, 67)}
    roster = pd.DataFrame(
        [
            {
                "player_id": p,
                "name": f"Synthetic {p}",
                "team_id": clubs[p],
                "club_code": clubs[p],
                "position": positions[p - 1] if p <= 15 else ("GK" if p % 11 == 0 else "MID"),
                "buy_price_tenths": 50 + p % 8,
                "sell_price_tenths": 49 + p % 8,
                "purchase_receipt": f"synthetic-receipt-{p}",
            }
            for p in range(1, 67)
        ]
    )
    roster.attrs["private_inventory"] = {"owned": list(range(1, 16)), "version": "synthetic-v1"}
    gameweeks = (6, 7) if extra_week else (6,)
    calendar_rows = []
    if not blank:
        for week in gameweeks:
            for pair, (home, away) in enumerate(((1, 2), (3, 4), (5, 6)), 1):
                for club, opponent, at_home in ((home, away, 1), (away, home, 0)):
                    calendar_rows.append(
                        {
                            "fixture": week * 10 + pair,
                            "club": club,
                            "opponent": opponent,
                            "home": at_home,
                            "GW": week,
                            "kickoff": f"2026-09-{23 if week == 6 else 30}T15:00:00+00:00",
                            "decision_at": DECISION_AT,
                        }
                    )
        if double:
            calendar_rows.extend(
                {
                    **row,
                    "fixture": 69,
                    "kickoff": "2026-09-25T15:00:00+00:00",
                }
                for row in tuple(calendar_rows)
                if row["GW"] == 6 and row["club"] in (3, 4)
            )
    calendar = pd.DataFrame(
        calendar_rows,
        columns=("fixture", "club", "opponent", "home", "GW", "kickoff", "decision_at"),
    )
    calendar.attrs.update(calendar_complete=True, covered_gameweeks=list(gameweeks))
    defaults = {3: 10.0, 6: 2.0, 7: -4.0, 8: 6.0, 12: 1.0, 13: 8.0}
    defaults.update({} if residuals is None else residuals)
    rows = []
    for fixture in calendar.to_dict("records"):
        for player in roster.loc[roster.club_code.eq(fixture["club"])].to_dict("records"):
            row = {
                **fixture,
                "season": SEASON,
                "player_code": player["player_id"],
                "position": player["position"],
                "model_version": JOINT_ROLE_MODEL_VERSION,
                "minute_role_version": ROLE_MINUTE_VERSION,
                "minute_role_status": "fitted_known_start_labels",
                "known_start_label_rows": 96,
                "unknown_start_label_rows": 0,
                "minute_prior_rows": 10.0,
                "team_goal_rate": 1.5,
                "opponent_goal_rate": 1.5,
                "goals_share": 1 / 11,
                "assists_share": 1 / 11,
                "goals": 1.2 / 11,
                "assists": 0.9 / 11,
                "defcon_rate90": 8.0,
                "defcon_dispersion": 4.0,
                "residual_if_appearance": defaults.get(int(player["player_id"]), 0.0),
                "availability_multiplier": 1.0,
            }
            probabilities = (
                STATE_PROBABILITIES
                if uncertain_players is None or player["player_id"] in uncertain_players
                else (0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0)
            )
            row.update(component_oracle(row, probabilities, STATE_MINUTES))
            rows.append(row)
    if rows:
        components = pd.DataFrame(rows)
    else:
        exemplar = native_case().components
        components = exemplar.iloc[:0].copy()
    components.attrs.update(
        season=SEASON,
        native_cutoff=DECISION_AT,
        calendar_complete=True,
        covered_gameweeks=list(gameweeks),
        availability_application="not_applied",
    )
    eligibility = {p: {3: 0.75, 6: 0.25, 7: 0.0, 13: 0.5}.get(p, 1.0) for p in clubs}
    weekly_rows = []
    for week in gameweeks:
        for player in roster.to_dict("records"):
            group = components.loc[
                components.GW.eq(week) & components.player_code.eq(player["player_id"])
            ]
            a = eligibility[int(player["player_id"])]
            weekly_rows.append(
                {
                    **player,
                    "gameweek": week,
                    "fixture_count": len(group),
                    "home_fixture_count": int(group.home.sum()),
                    "expected_points": a * fsum(group.expected_points),
                    "appearance_probability": a
                    * (1 - prod(1 - q for q in group.appearance_probability)),
                }
            )
    weekly = pd.DataFrame(weekly_rows)
    weekly.attrs["native_private_receipt"] = {"tag": "synthetic-control-v1"}
    resources = {
        "bank_tenths": 23,
        "free_transfers": 2,
        "chips": {"wildcard": True, "freehit": True, "bboost": True, "3xc": True},
        "transfer_policy": {"hit_points": 4, "maximum_transfers": 2},
        "private_inventory": {"owned": list(range(1, 16))},
    }
    return NativeFlagCase(components, weekly, roster, calendar, resources, eligibility, gameweeks)


def week_state_oracle(
    states: Sequence[Sequence[int]],
    probabilities: Sequence[float],
    minutes: Sequence[Sequence[float]],
) -> tuple[float, tuple[tuple[float, ...], ...]]:
    """Marginalize retained week-joint states without assuming fixture independence."""
    q = fsum(p for state, p in zip(states, probabilities, strict=True) if any(state))
    marginals = tuple(
        tuple(
            fsum(p for state, p in zip(states, probabilities, strict=True) if state[f] == s)
            for s in range(7)
        )
        for f in range(len(minutes))
    )
    return q, marginals


def independent_lineup_oracle(
    squad: pd.DataFrame,
    xi: Sequence[int],
    bench: Sequence[int],
    captain: int,
    vice: int,
    *,
    chip: str | None = None,
    hits: float = 0.0,
) -> float:
    """Enumerate worlds and replace actual vacant slots, separately from convolution."""
    table = squad.set_index("player_id")
    ids = tuple(table.index)
    q = {p: float(table.at[p, "appearance_probability"]) for p in ids}
    position = {p: str(table.at[p, "position"]) for p in ids}
    conditional = {p: float(table.at[p, "expected_points"]) / q[p] if q[p] else 0.0 for p in ids}
    choices = [(False, True) if 0 < q[p] < 1 else (bool(q[p]),) for p in ids]
    starter_keeper = next(p for p in xi if position[p] == "GK")
    reserve_keeper = next(p for p in bench if position[p] == "GK")
    nominal = {pos: sum(position[p] == pos for p in xi) for pos in ("DEF", "MID", "FWD")}
    terms = []
    for flags in product(*choices):
        plays = dict(zip(ids, flags, strict=True))
        mass = prod(q[p] if plays[p] else 1 - q[p] for p in ids)
        if chip == "bboost":
            points = fsum(conditional[p] for p in ids if plays[p])
        else:
            scored = [p for p in xi if plays[p]]
            if not plays[starter_keeper] and plays[reserve_keeper]:
                scored.append(reserve_keeper)
            missing = [p for p in xi if position[p] != "GK" and not plays[p]]
            counts = nominal.copy()
            for incoming in bench:
                if position[incoming] == "GK" or not plays[incoming]:
                    continue
                for outgoing in tuple(missing):
                    candidate = counts.copy()
                    candidate[position[outgoing]] -= 1
                    candidate[position[incoming]] += 1
                    if all(
                        low <= candidate[pos] <= high
                        for pos, low, high in (("DEF", 3, 5), ("MID", 2, 5), ("FWD", 1, 3))
                    ):
                        scored.append(incoming)
                        missing.remove(outgoing)
                        counts = candidate
                        break
            points = fsum(conditional[p] for p in scored)
        bonus = (
            conditional[captain] if plays[captain] else conditional[vice] if plays[vice] else 0.0
        )
        points += (2 if chip == "3xc" else 1) * bonus
        terms.append(mass * points)
    return fsum(terms) - hits
