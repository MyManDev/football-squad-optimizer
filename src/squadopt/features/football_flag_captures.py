"""Flag-minute inputs from original retained FPL payloads, without file or network IO.

Reconstructed historical decisions are explicitly out of fold. Their reference
decision is supplied separately from the actual capture and native information
cutoff. This reader never labels a reconstruction as an original live forecast.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from typing import Any

from squadopt.data.errors import DataError
from squadopt.data.timestamps import as_instant, normalize_utc_timestamp
from squadopt.features.football_flag_inputs import (
    LABELS,
    POSITIONS,
    STATUSES,
    MinuteFixture,
    PlayerWeekInput,
    TrainingWeek,
    validate_training_week,
    validate_week_input,
)

CAPTURE_ADAPTER_VERSION = "retained_fpl_flag_inputs_v1"


def _json(raw: bytes) -> Any:
    if type(raw) is not bytes:
        raise DataError("Retained FPL payloads must be original bytes.")

    def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in items:
            if key in result:
                raise DataError("Duplicate retained FPL JSON key.")
            result[key] = value
        return result

    try:
        return json.loads(raw, object_pairs_hook=pairs)
    except (ValueError, UnicodeDecodeError) as error:
        raise DataError("Invalid retained FPL JSON.") from error


def _id(value: object, label: str, *, minimum: int = 1, maximum: int | None = None) -> int:
    if type(value) is not int or value < minimum or (maximum is not None and value > maximum):
        raise DataError(f"Invalid retained FPL {label}.")
    return value


def _clock(value: object) -> str:
    return normalize_utc_timestamp(value, label="retained FPL source clock")


def _season(season: str) -> None:
    if season == "2025-26":
        raise DataError("Protected 2025-26 is excluded before payload decoding.")
    if not isinstance(season, str) or re.fullmatch(r"20\d{2}-\d{2}", season) is None:
        raise DataError("A consecutive YYYY-YY source season is required.")
    if int(season[-2:]) != (int(season[:4]) + 1) % 100:
        raise DataError("A consecutive YYYY-YY source season is required.")


def _same_season(bootstrap: dict[str, Any], season: str) -> None:
    first_year = int(str(min(event["deadline_time"] for event in bootstrap["events"]))[:4])
    if season != f"{first_year}-{(first_year + 1) % 100:02d}":
        raise DataError("Captured event calendar belongs to another season.")


def _hash(**payloads: bytes) -> str:
    receipt = {name: hashlib.sha256(raw).hexdigest() for name, raw in payloads.items()}
    return hashlib.sha256(json.dumps(receipt, sort_keys=True).encode()).hexdigest()


def _players(bootstrap: dict[str, Any]) -> dict[int, dict[str, Any]]:
    result = {}
    elements = set()
    for player in bootstrap["elements"]:
        if _id(player["element_type"], "position", maximum=5) == 5:
            continue
        code, element = _id(player["code"], "person code"), _id(player["id"], "element")
        if code in result or element in elements:
            raise DataError("Duplicate retained FPL player identity.")
        result[code] = player
        elements.add(element)
    if not result:
        raise DataError("An explicit nonempty retained FPL roster is required.")
    return result


def captured_flag_weeks(
    *,
    bootstrap: bytes,
    fixtures: bytes,
    season: str,
    gameweek: int,
    captured_at: str,
    decision_at: str,
    native_fixtures: Mapping[int, tuple[MinuteFixture, ...]],
    native_basis_sha256: str,
    native_fit_cutoff: str,
    reconstructed: bool,
) -> tuple[PlayerWeekInput, ...]:
    """Bind original next-event labels and complete native supports for one week.

    Later horizon weeks need a separately declared policy. This function refuses
    to relabel a captured next-event flag as another gameweek's source fact.
    """
    _season(season)
    _id(gameweek, "gameweek", maximum=38)
    captured, decision = _clock(captured_at), _clock(decision_at)
    if as_instant(captured) >= as_instant(decision):
        raise DataError("The actual capture must precede the explicit reference decision.")
    if type(reconstructed) is not bool:
        raise DataError("Reconstructed status must be explicit.")
    if as_instant(_clock(native_fit_cutoff)) > as_instant(captured):
        raise DataError("Native information cutoff must not follow the original capture.")
    boot = _json(bootstrap)
    events = [event for event in boot["events"] if event.get("is_next") is True]
    if len(events) != 1 or events[0]["id"] != gameweek:
        raise DataError("Captured next-event flags do not address the requested gameweek.")
    _same_season(boot, season)
    deadline = _clock(events[0]["deadline_time"])
    if as_instant(decision) >= as_instant(deadline):
        raise DataError("Reference decision must precede the captured deadline.")
    players = _players(boot)
    if set(players) != set(native_fixtures):
        raise DataError("Native minute supports must cover the exact captured roster.")
    clubs = {_id(team["id"], "team"): _id(team["code"], "club") for team in boot["teams"]}
    matches = [match for match in _json(fixtures) if match["event"] == gameweek]
    if len({match["id"] for match in matches}) != len(matches):
        raise DataError("Repeated retained FPL fixture.")
    source = _hash(bootstrap=bootstrap, fixtures=fixtures)
    output = []
    for code, player in sorted(players.items()):
        mine = [match for match in matches if player["team"] in (match["team_h"], match["team_a"])]
        supports = native_fixtures[code]
        if {item.fixture for item in supports} != {match["id"] for match in mine}:
            raise DataError("Native supports differ from the captured complete club calendar.")
        by_id = {match["id"]: match for match in mine}
        for item in supports:
            match = by_id[item.fixture]
            home = player["team"] == match["team_h"]
            if (
                item.club != clubs[player["team"]]
                or item.opponent != clubs[match["team_a"] if home else match["team_h"]]
                or item.home != int(home)
                or as_instant(_clock(item.kickoff)) != as_instant(_clock(match["kickoff_time"]))
            ):
                raise DataError("Native support differs from its captured fixture identity.")
        status = player["status"]
        label = player["chance_of_playing_next_round"]
        if status not in (*STATUSES, None) or (
            label is not None and (type(label) is not int or label not in LABELS)
        ):
            raise DataError("Unknown retained FPL flag category.")
        news, added = player["news"], player["news_added"]
        if not isinstance(news, str):
            raise DataError("Captured news must be explicit text.")
        age = None
        if added is not None:
            age = (as_instant(decision) - as_instant(_clock(added))).total_seconds() / 3600
            if as_instant(_clock(added)) > as_instant(captured):
                raise DataError("News was added after the source capture.")
        news_state = "flagged" if news.strip() else "cleared" if added is not None else "unknown"
        week = PlayerWeekInput(
            season=season,
            gameweek=gameweek,
            player_code=code,
            decision_at=decision,
            deadline_at=deadline,
            position=POSITIONS[player["element_type"] - 1],
            status=status,
            label=label,
            news_state=news_state,
            news_age_hours=age,
            capture_age_hours=(as_instant(decision) - as_instant(captured)).total_seconds() / 3600,
            history_covered=False,
            label_changed=None,
            fixtures=supports,
            source_sha256=source,
            native_basis_sha256=native_basis_sha256,
            native_basis_evidence_ref=f"{CAPTURE_ADAPTER_VERSION}:{native_basis_sha256}",
            native_basis_kind="out_of_fold" if reconstructed else "prospective",
            native_basis_fit_cutoff=_clock(native_fit_cutoff),
            calendar_complete=True,
            covered_gameweeks=(gameweek,),
            calendar_evidence_ref=f"sha256:{hashlib.sha256(fixtures).hexdigest()}",
            legacy_next_round_label=label,
        )
        validate_week_input(week)
        output.append(week)
    return tuple(output)


def captured_flag_outcome(
    week: PlayerWeekInput,
    *,
    bootstrap: bytes,
    fixtures: bytes,
    event: bytes,
    captured_at: str,
    fit_cutoff: str,
    target_season: str,
    target_gameweeks: tuple[int, ...],
) -> TrainingWeek:
    """Read explicit settled SGW start/minute labels, refusing ambiguous doubles.

    Weekly starts cannot identify each fixture's starting role in a double. That
    case needs an actual fixture-level source and is refused before outcome IO.
    """
    _season(week.season)
    _season(target_season)
    if (
        week.season > target_season
        or not target_gameweeks
        or (week.season == target_season and week.gameweek >= min(target_gameweeks))
    ):
        raise DataError("Target and future outcomes are excluded before payload decoding.")
    validate_week_input(week)
    if len(week.fixtures) != 1:
        raise DataError("This retained weekly outcome adapter requires exactly one fixture.")
    settled = _clock(captured_at)
    if as_instant(settled) >= as_instant(_clock(fit_cutoff)):
        raise DataError("Outcome capture must precede the model fit cutoff.")
    boot = _json(bootstrap)
    _same_season(boot, week.season)
    players = _players(boot)
    player = players.get(week.player_code)
    if player is None:
        raise DataError("Settled source lacks the original persistent player identity.")
    match_rows = [row for row in _json(fixtures) if row["id"] == week.fixtures[0].fixture]
    if len(match_rows) != 1:
        raise DataError("Settled fixture identity is missing or repeated.")
    match = match_rows[0]
    if match["event"] != week.gameweek or match.get("finished") is not True:
        raise DataError("The original target fixture is not settled in its target gameweek.")
    clubs = {_id(team["id"], "team"): _id(team["code"], "club") for team in boot["teams"]}
    native = week.fixtures[0]
    expected = (native.club, native.opponent) if native.home else (native.opponent, native.club)
    if (clubs[match["team_h"]], clubs[match["team_a"]]) != expected:
        raise DataError("Settled fixture clubs differ from the original native calendar.")
    if (as_instant(settled) - as_instant(_clock(match["kickoff_time"]))).total_seconds() <= 10800:
        raise DataError("Outcome capture does not establish settled match minutes.")
    items = [row for row in _json(event)["elements"] if row["id"] == player["id"]]
    if len(items) != 1:
        raise DataError("Explicit settled player minutes are missing or repeated.")
    item = items[0]
    minutes = _id(item["stats"].get("minutes"), "minutes", minimum=0, maximum=120)
    starts = _id(item["stats"].get("starts"), "starts", minimum=0, maximum=1)
    if minutes == 0 and starts:
        raise DataError("Zero-minute recorded starts are outside this state support.")
    explained = item.get("explain", [])
    if any(row["fixture"] != match["id"] for row in explained) or (minutes > 0 and not explained):
        raise DataError("Player outcome does not belong to its original target fixture.")
    state = (
        0
        if minutes == 0
        else (1 if minutes < 60 else 2 if minutes < 90 else 3) + (0 if starts else 3)
    )
    result = TrainingWeek(
        input=week,
        observed_states=(state,),
        settled_at=settled,
        outcome_sha256=_hash(bootstrap=bootstrap, fixtures=fixtures, event=event),
    )
    validate_training_week(
        result,
        fit_cutoff=fit_cutoff,
        target_season=target_season,
        target_gameweeks=target_gameweeks,
    )
    return result
