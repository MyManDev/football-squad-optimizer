"""Pure strict readers for retained observed tactical bytes; no source fetching."""

from __future__ import annotations

import csv
import hashlib
import io
from dataclasses import dataclass, fields, is_dataclass, replace
from decimal import Decimal, InvalidOperation
from types import UnionType
from typing import Any, cast, get_args, get_origin, get_type_hints

from squadopt.features.football_observed_tactical_inputs import (
    INPUT_VERSION,
    ObservedEventFixture,
    ObservedRole,
    ObservedTacticalObservation,
    ObservedTacticalProfile,
    ObservedTacticalProjection,
    ObservedTacticalSource,
    _release,
    sha,
    validate_header,
    validate_outcome,
    validate_projection,
)
from squadopt.features.football_tactical_inputs import TRAITS, _fields, _id, _raw_json, _text

MAX_BYTES = 64 * 1024 * 1024
PANNA_ROLE_MAPPING_VERSION = "panna_named_provider_role_to_four_v1"
PANNA_ROLES = {
    "Goalkeeper": "G",
    "Defender": "D",
    "WingBack": "D",
    "Wing Back": "D",
    "DefensiveMidfielder": "M",
    "Defensive Midfielder": "M",
    "Midfielder": "M",
    "AttackingMidfielder": "M",
    "Attacking Midfielder": "M",
    "Striker": "F",
}


def verified_bytes(payload: bytes, expected_sha256: str) -> bytes:
    sha(expected_sha256)
    if type(payload) is not bytes or not 0 < len(payload) <= MAX_BYTES:
        raise ValueError("Observed tactical source must be bounded original bytes.")
    if hashlib.sha256(payload).hexdigest() != expected_sha256:
        raise ValueError("Observed tactical original byte hash differs.")
    return payload


def _decode(kind: Any, value: object) -> Any:
    """Decode only the declared dataclass schema; never coerce strings or booleans."""
    origin, arguments = get_origin(kind), get_args(kind)
    if origin is UnionType:
        if value is None and type(None) in arguments:
            return None
        return _decode(next(t for t in arguments if t is not type(None)), value)
    if origin is tuple:
        if type(value) is not list:
            raise ValueError("Observed tactical tuple field requires a JSON array.")
        if len(arguments) == 2 and arguments[1] is Ellipsis:
            return tuple(_decode(arguments[0], item) for item in value)
        if len(value) != len(arguments):
            raise ValueError("Observed tactical fixed tuple has the wrong dimension.")
        return tuple(_decode(t, item) for t, item in zip(arguments, value, strict=True))
    if is_dataclass(kind):
        names = tuple(f.name for f in fields(kind))
        data = _fields(value, names, "observed tactical record")
        hints = get_type_hints(kind)
        constructor = cast(Any, kind)
        return constructor(**{name: _decode(hints[name], data[name]) for name in names})
    if kind is float and type(value) in (int, float):
        return float(cast(float, value))
    if type(value) is not kind:
        raise ValueError("Observed tactical scalar has the wrong declared type.")
    return value


def read_observed_projection(
    payload: bytes, *, expected_sha256: str, allow_released_2025_26: bool = False
) -> ObservedTacticalProjection:
    raw = _fields(
        _raw_json(verified_bytes(payload, expected_sha256)),
        ("version", "projection"),
        "observed tactical projection envelope",
    )
    if raw["version"] != INPUT_VERSION:
        raise ValueError("Observed tactical raw projection version differs.")
    result: ObservedTacticalProjection = _decode(ObservedTacticalProjection, raw["projection"])
    validate_projection(result, allow_released_2025_26=allow_released_2025_26)
    return result


def read_observed_observation(
    payload: bytes,
    *,
    expected_sha256: str,
    cutoff: str,
    target_season: str,
    target_gameweek: int,
    allowed_seasons: tuple[str, ...],
    allow_released_2025_26: bool = False,
) -> ObservedTacticalObservation:
    raw = _fields(
        _raw_json(verified_bytes(payload, expected_sha256)),
        ("version", "observation"),
        "observed tactical outcome envelope",
    )
    if raw["version"] != INPUT_VERSION:
        raise ValueError("Observed tactical raw observation version differs.")
    data = _fields(
        raw["observation"],
        tuple(f.name for f in fields(ObservedTacticalObservation)),
        "observed tactical observation",
    )
    # Build and check all source/header fields before decoding physical counts/credits.
    header = ObservedTacticalObservation(
        _decode(ObservedTacticalProjection, data["projection"]),
        _decode(str, data["outcome_available_at"]),
        _decode(ObservedTacticalSource, data["goal_source"]),
        _decode(ObservedTacticalSource, data["credit_source"]),
        (0, 0),
        (),
        _decode(str, data["rules_version"]),
        _decode(bool, data["final"]),
    )
    validate_header(
        header,
        cutoff=cutoff,
        target_season=target_season,
        target_gameweek=target_gameweek,
        allowed_seasons=allowed_seasons,
        allow_released_2025_26=allow_released_2025_26,
    )
    result: ObservedTacticalObservation = _decode(ObservedTacticalObservation, data)
    validate_outcome(result)
    return result


def _integral(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise ValueError("Provider numeric identity must be exact integral data.")
    try:
        number = Decimal(str(value))
    except InvalidOperation as error:
        raise ValueError("Provider numeric identity is invalid.") from error
    if not number.is_finite() or number != number.to_integral_value() or not 0 <= number <= 2**53:
        raise ValueError("Provider numeric identity exceeds exact integral support.")
    return int(number)


def read_observed_event_fixture(
    payload: bytes,
    *,
    source: ObservedTacticalSource,
    season: str,
    gameweek: int,
    fixture: int,
    club: int,
    opponent: int,
    kickoff: str,
    finished_at: str,
    provider_match_id: str,
    provider_club_id: str,
    provider_opponent_id: str,
    bridge_sha256: str,
    complete_row_count: int,
    complete_inventory_sha256: str,
    allow_released_2025_26: bool = False,
) -> ObservedEventFixture:
    """Count four declared qualifiers in a complete externally inventoried raw fixture.

    The caller's inventory/bridge hashes are provenance declarations; this reader
    verifies retained event bytes and exact selected-row identity, not those external proofs.
    """
    _release(season, allow_released_2025_26)
    sha(bridge_sha256)
    sha(complete_inventory_sha256)
    raw = _raw_json(verified_bytes(payload, source.sha256))
    if (
        type(raw) is not list
        or type(complete_row_count) is not int
        or not 1 <= complete_row_count <= 100000
        or len(raw) != complete_row_count
    ):
        raise ValueError("Observed event rows do not match the complete selected inventory.")
    if provider_club_id == provider_opponent_id:
        raise ValueError("Observed event provider clubs must differ.")
    required = {"match_id", "event_id", "type_id", "team_id", "qualifier_json", "season"}
    permitted = required | {
        "player_id",
        "player_name",
        "minute",
        "second",
        "period_id",
        "source_parquet_row",
    }
    ids, counts = [], [0, 0, 0, 0]
    seen_ids = set()
    expected_season = season[:4] + "-" + str(int(season[:4]) + 1)
    for row in raw:
        if type(row) is not dict or not required <= set(row) <= permitted:
            raise ValueError("Observed provider event schema differs.")
        if (
            row["match_id"] != provider_match_id
            or row["season"] != expected_season
            or row["team_id"] not in (provider_club_id, provider_opponent_id)
        ):
            raise ValueError("Observed event identity/season is outside the exact paired bridge.")
        event_id, event_type = _integral(row["event_id"]), _integral(row["type_id"])
        if event_id == 0 or event_id in seen_ids:
            raise ValueError("Observed provider event identity is zero or duplicated.")
        ids.append(event_id)
        seen_ids.add(event_id)
        if row["team_id"] != provider_club_id or event_type not in (1, 2, 13, 14, 15, 16):
            continue
        qualifiers = row["qualifier_json"]
        if not isinstance(qualifiers, str):
            raise ValueError("Relevant observed event has unknown qualifier data.")
        parsed = _raw_json(qualifiers.encode())
        if type(parsed) is not dict or any(
            not isinstance(k, str) or not k.isdigit() for k in parsed
        ):
            raise ValueError("Observed event qualifiers must have explicit provider IDs.")
        if event_type in (1, 2):
            counts[0] += int("2" in parsed)
            counts[1] += int("4" in parsed)
        elif "28" not in parsed:
            counts[2] += int("15" in parsed)
            counts[3] += int("23" in parsed)
    return ObservedEventFixture(
        season,
        gameweek,
        fixture,
        club,
        opponent,
        kickoff,
        finished_at,
        provider_match_id,
        provider_club_id,
        bridge_sha256,
        complete_inventory_sha256,
        tuple(counts),
        len(ids),
        tuple(ids),
        source,
        True,
    )


@dataclass(frozen=True, slots=True)
class ObservedFMRow:
    player_code: int
    row_number: int
    expected_name: str
    expected_date_of_birth: str
    mapping_ref: str


def _csv(payload: bytes) -> list[dict[str, str]]:
    try:
        reader = csv.DictReader(io.StringIO(payload.decode("utf-8-sig")))
        if reader.fieldnames is None or len(reader.fieldnames) != len(set(reader.fieldnames)):
            raise ValueError("Observed tactical CSV has missing or repeated column names.")
        rows = list(reader)
    except (UnicodeDecodeError, csv.Error) as error:
        raise ValueError("Observed tactical CSV bytes are invalid.") from error
    if any(None in row or any(v is None for v in row.values()) for row in rows):
        raise ValueError("Observed tactical CSV rows have inconsistent widths.")
    return rows


def read_observed_fm_profiles(
    payload: bytes,
    *,
    source: ObservedTacticalSource,
    profiles: tuple[ObservedTacticalProfile, ...],
    mappings: tuple[ObservedFMRow, ...],
    name_column: str,
    date_of_birth_column: str,
    trait_columns: tuple[tuple[str, str], ...],
) -> tuple[ObservedTacticalProfile, ...]:
    rows = _csv(verified_bytes(payload, source.sha256))
    columns = dict(trait_columns)
    if (
        len(columns) != len(trait_columns)
        or not set(columns) <= set(TRAITS)
        or len(set(columns.values())) != len(columns)
    ):
        raise ValueError("Observed tactical FM trait columns must map distinct named traits.")
    by_code = {p.player_code: p for p in profiles}
    if len(by_code) != len(profiles):
        raise ValueError("Observed tactical FM target roster repeats an identity.")
    seen_codes, seen_rows = set(), set()
    for mapping in mappings:
        if (
            type(mapping) is not ObservedFMRow
            or mapping.player_code not in by_code
            or mapping.player_code in seen_codes
            or type(mapping.row_number) is not int
            or not 2 <= mapping.row_number <= len(rows) + 1
            or mapping.row_number in seen_rows
        ):
            raise ValueError("Observed tactical exact FM mapping is invalid or duplicated.")
        _id(mapping.player_code, "FM persistent player")
        _text(mapping.mapping_ref, "FM mapping evidence")
        _text(mapping.expected_name, "FM exact name")
        _text(mapping.expected_date_of_birth, "FM exact birth date")
        row = rows[mapping.row_number - 2]
        if (
            row.get(name_column) != mapping.expected_name
            or row.get(date_of_birth_column) != mapping.expected_date_of_birth
            or not set(columns.values()) <= set(row)
        ):
            raise ValueError("Observed tactical FM original row does not match exact name/DOB.")
        attributes = []
        for name in TRAITS:
            value = row[columns[name]].strip() if name in columns else ""
            parsed = None if not value else _integral(value)
            if parsed is not None and not 1 <= parsed <= 20:
                raise ValueError("Observed FM trait is outside native integer1..20 support.")
            attributes.append(parsed)
        by_code[mapping.player_code] = replace(
            by_code[mapping.player_code],
            attributes=tuple(attributes),
            original_identity="csv-row:" + str(mapping.row_number),
            mapping_ref=mapping.mapping_ref,
            trait_source=source,
            trait_columns=trait_columns,
        )
        seen_codes.add(mapping.player_code)
        seen_rows.add(mapping.row_number)
    return tuple(by_code[p.player_code] for p in profiles)


def read_observed_role_rows(
    payload: bytes,
    *,
    source: ObservedTacticalSource,
    provider_match_id: str,
    season: str,
    gameweek: int,
    fixture: int,
    kickoff: str,
    finished_at: str,
    club_by_team_side: tuple[tuple[str, int], ...],
    people: tuple[tuple[str, int], ...],
    mapping_ref: str,
    allow_released_2025_26: bool = False,
) -> tuple[ObservedRole, ...]:
    """Read confirmed provider G/D/M/F positions using an explicit per-fixture bridge."""
    _release(season, allow_released_2025_26)
    rows = _csv(verified_bytes(payload, source.sha256))
    clubs, identities = dict(club_by_team_side), dict(people)
    if (
        set(clubs) != {"home", "away"}
        or len(club_by_team_side) != 2
        or len(set(clubs.values())) != 2
        or len(identities) != len(people)
        or len(set(identities.values())) != len(identities)
    ):
        raise ValueError("Observed tactical role fixture/person bridge is not one to one.")
    _text(mapping_ref, "role bridge evidence")
    for label, identifier in (*club_by_team_side, *people):
        _text(label, "role provider identity")
        _id(identifier, "role persistent identity")
    result, seen = [], set()
    for ordinal, row in enumerate(rows, 2):
        required = {"match_id", "team_side", "player_id", "position", "lineup_status"}
        if not required <= set(row):
            raise ValueError("Observed provider role CSV schema is incomplete.")
        if row["match_id"] != provider_match_id:
            continue
        if row["lineup_status"] != "confirmed":
            raise ValueError("Observed provider role is not confirmed.")
        if row["player_id"] not in identities or row["team_side"] not in clubs:
            raise ValueError("Observed provider role lacks an exact person/fixture bridge.")
        code = identities[row["player_id"]]
        if code in seen or row["position"] not in ("G", "D", "M", "F"):
            raise ValueError("Observed provider role identity is repeated or role unavailable.")
        seen.add(code)
        result.append(
            ObservedRole(
                season,
                gameweek,
                fixture,
                kickoff,
                finished_at,
                code,
                clubs[row["team_side"]],
                row["position"],
                row["player_id"],
                ordinal,
                mapping_ref,
                source,
            )
        )
    if not result:
        raise ValueError("Observed provider role selected fixture is absent.")
    return tuple(result)


def read_observed_panna_roles(
    payload: bytes,
    *,
    source: ObservedTacticalSource,
    provider_match_id: str,
    season: str,
    gameweek: int,
    fixture: int,
    kickoff: str,
    finished_at: str,
    clubs: tuple[tuple[str, int], ...],
    people: tuple[tuple[str, int], ...],
    mapping_ref: str,
    allow_released_2025_26: bool = False,
) -> tuple[ObservedRole, ...]:
    """Read named provider roles; a Substitute row supplies no positional evidence."""
    _release(season, allow_released_2025_26)
    raw = _raw_json(verified_bytes(payload, source.sha256))
    if type(raw) is not list or not 1 <= len(raw) <= 100000:
        raise ValueError("Panna role records require a bounded retained row array.")
    team_map, person_map = dict(clubs), dict(people)
    if (
        len(team_map) != len(clubs)
        or len(team_map) != 2
        or len(set(team_map.values())) != 2
        or len(person_map) != len(people)
        or len(set(person_map.values())) != len(person_map)
    ):
        raise ValueError("Panna observed roles need exact one-to-one fixture/person bridges.")
    _text(mapping_ref, "Panna role exact mapping evidence")
    for label, identifier in (*clubs, *people):
        _text(label, "Panna provider identity")
        _id(identifier, "Panna persistent identity")
    required = {"match_id", "player_id", "team_id", "position", "season", "is_starter"}
    allowed = required | {
        "competition",
        "formation_place",
        "match_date",
        "player_name",
        "shirt_number",
        "source_row_in_group",
        "team_name",
        "team_position",
    }
    results, seen = [], set()
    expected_season = season[:4] + "-" + str(int(season[:4]) + 1)
    for ordinal, row in enumerate(raw, 1):
        if type(row) is not dict or not required <= set(row) <= allowed:
            raise ValueError("Panna provider role schema differs.")
        if row["match_id"] != provider_match_id:
            continue
        if (
            row["season"] != expected_season
            or row["team_id"] not in team_map
            or type(row["is_starter"]) is not bool
        ):
            raise ValueError("Panna provider role fixture/season identity differs.")
        provider_person = row["player_id"]
        _text(provider_person, "Panna provider person")
        if provider_person in seen:
            raise ValueError("Panna provider lineup repeats a person.")
        seen.add(provider_person)
        _text(row["position"], "Panna provider role")
        if row["position"] == "Substitute":
            if row["is_starter"]:
                raise ValueError("Panna starter is inconsistently labeled Substitute.")
            continue
        if row["position"] not in PANNA_ROLES or provider_person not in person_map:
            raise ValueError("Panna role lacks an exact positional/person mapping.")
        results.append(
            ObservedRole(
                season,
                gameweek,
                fixture,
                kickoff,
                finished_at,
                person_map[provider_person],
                team_map[row["team_id"]],
                PANNA_ROLES[row["position"]],
                provider_person,
                ordinal,
                mapping_ref + ";role-definition=" + PANNA_ROLE_MAPPING_VERSION,
                source,
            )
        )
    if not seen:
        raise ValueError("Panna observed role selected fixture is absent.")
    return tuple(results)
