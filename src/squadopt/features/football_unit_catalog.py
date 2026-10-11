"""Strict private JSON input boundary for the explicit club-unit experiment.

This module performs no network or filesystem access. A source grant is a supplied
receipt, not permission inferred from a public page or from this parser succeeding.
"""

from __future__ import annotations

import json
import math
from datetime import datetime
from typing import Any, Literal, NoReturn, cast

from squadopt.features.football_unit_inputs import (
    UNIT_INPUT_VERSION,
    ClubUnit,
    NumericAttributeSpec,
    PlayerAttributes,
    PlayerMapping,
    ProjectedUnitState,
    SourceRecord,
    UnitInputCatalog,
    UnitObservation,
    UnitPlayer,
    UnitProjection,
)


def _object(value: object, fields: tuple[str, ...], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != set(fields):
        raise ValueError(f"{label} requires exactly its versioned fields.")
    return value


def _list(value: object, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be a JSON array.")
    return value


def _string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a nonempty string.")
    return value


def _integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{label} must be an integer JSON identity.")
    return value


def _number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a numeric JSON value.")
    try:
        result = float(value)
    except OverflowError as error:
        raise ValueError(f"{label} exceeds the supported numeric range.") from error
    if not math.isfinite(result):
        raise ValueError(f"{label} must be finite.")
    return result


def _boolean(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{label} must be boolean.")
    return value


def _time(value: object, label: str) -> datetime:
    text = _string(value, label)
    try:
        result = datetime.fromisoformat(text)
    except ValueError as error:
        raise ValueError(f"{label} must be an ISO timestamp.") from error
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError(f"{label} must have an explicit timezone.")
    return result


def _source(value: object) -> SourceRecord:
    row = _object(
        value,
        (
            "source_id",
            "provider",
            "version",
            "kind",
            "sha256",
            "published_at",
            "captured_at",
            "effective_at",
            "valid_until",
            "rights_reference",
            "permitted_model_development",
        ),
        "source",
    )
    kind = _string(row["kind"], "source kind")
    if kind not in ("synthetic", "provider", "fm"):
        raise ValueError("Unsupported source kind.")
    return SourceRecord(
        source_id=_string(row["source_id"], "source_id"),
        provider=_string(row["provider"], "provider"),
        version=_string(row["version"], "source version"),
        kind=cast(Literal["synthetic", "provider", "fm"], kind),
        sha256=_string(row["sha256"], "source SHA256"),
        published_at=_time(row["published_at"], "published_at"),
        captured_at=_time(row["captured_at"], "captured_at"),
        effective_at=_time(row["effective_at"], "effective_at"),
        valid_until=_time(row["valid_until"], "valid_until"),
        rights_reference=_string(row["rights_reference"], "rights_reference"),
        permitted_model_development=_boolean(row["permitted_model_development"], "model use"),
    )


def _spec(value: object) -> NumericAttributeSpec:
    row = _object(
        value,
        ("name", "source_id", "minimum", "maximum", "unit", "definition"),
        "attribute specification",
    )
    return NumericAttributeSpec(
        name=_string(row["name"], "attribute name"),
        source_id=_string(row["source_id"], "attribute source"),
        minimum=_number(row["minimum"], "attribute minimum"),
        maximum=_number(row["maximum"], "attribute maximum"),
        unit=_string(row["unit"], "attribute unit"),
        definition=_string(row["definition"], "attribute definition"),
    )


def _mapping(value: object) -> PlayerMapping:
    row = _object(
        value,
        ("source_id", "source_player_id", "player_id", "club", "valid_from", "valid_until"),
        "player mapping",
    )
    return PlayerMapping(
        source_id=_string(row["source_id"], "mapping source"),
        source_player_id=_string(row["source_player_id"], "source player identity"),
        player_id=_integer(row["player_id"], "persistent player identity"),
        club=_integer(row["club"], "club identity"),
        valid_from=_time(row["valid_from"], "mapping valid_from"),
        valid_until=_time(row["valid_until"], "mapping valid_until"),
    )


def _attributes(value: object) -> PlayerAttributes:
    row = _object(value, ("source_id", "source_player_id", "values"), "player attributes")
    values = row["values"]
    if not isinstance(values, dict) or any(not isinstance(name, str) for name in values):
        raise ValueError("Player attribute values must be a named JSON object.")
    return PlayerAttributes(
        source_id=_string(row["source_id"], "attribute source"),
        source_player_id=_string(row["source_player_id"], "attribute player identity"),
        values=tuple(
            (
                _string(name, "attribute name"),
                None if number is None else _number(number, "attribute value"),
            )
            for name, number in values.items()
        ),
    )


def _catalog(value: object) -> UnitInputCatalog:
    row = _object(
        value,
        (
            "season",
            "gameweek",
            "fixture_id",
            "decision_cutoff",
            "sources",
            "attributes",
            "mappings",
            "player_attributes",
            "baseline_source_id",
            "reference_source_id",
            "projection_source_id",
        ),
        "unit catalog",
    )
    return UnitInputCatalog(
        season=_string(row["season"], "season"),
        gameweek=_integer(row["gameweek"], "gameweek"),
        fixture_id=_integer(row["fixture_id"], "fixture_id"),
        decision_cutoff=_time(row["decision_cutoff"], "decision_cutoff"),
        sources=tuple(_source(x) for x in _list(row["sources"], "sources")),
        attributes=tuple(_spec(x) for x in _list(row["attributes"], "attribute definitions")),
        mappings=tuple(_mapping(x) for x in _list(row["mappings"], "mappings")),
        player_attributes=tuple(
            _attributes(x) for x in _list(row["player_attributes"], "attribute snapshots")
        ),
        baseline_source_id=_string(row["baseline_source_id"], "baseline source identity"),
        reference_source_id=_string(row["reference_source_id"], "reference source identity"),
        projection_source_id=_string(row["projection_source_id"], "projection source identity"),
    )


def _unit(value: object) -> ClubUnit:
    row = _object(value, ("club", "players"), "club unit")
    players = []
    for item in _list(row["players"], "unit players"):
        player = _object(item, ("player_id", "position"), "unit player")
        players.append(
            UnitPlayer(
                _integer(player["player_id"], "unit player identity"),
                _string(player["position"], "unit position"),
            )
        )
    return ClubUnit(_integer(row["club"], "unit club"), tuple(players))


def _state(value: object) -> ProjectedUnitState:
    row = _object(value, ("probability", "own", "opponent"), "joint unit state")
    return ProjectedUnitState(
        _number(row["probability"], "state probability"), _unit(row["own"]), _unit(row["opponent"])
    )


def _reject_constant(_: str) -> NoReturn:
    raise ValueError("Nonfinite JSON values are refused.")


def _unique_fields(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON fields are refused.")
        result[key] = value
    return result


def _document(payload: bytes, kind: str, field: str) -> object:
    if not isinstance(payload, bytes):
        raise ValueError("Private unit inputs require immutable UTF-8 JSON bytes.")
    try:
        value = json.loads(
            payload.decode("utf-8"),
            parse_constant=_reject_constant,
            object_pairs_hook=_unique_fields,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("Private unit input is not valid UTF-8 JSON.") from error
    row = _object(value, ("version", "kind", field), "private unit document")
    if row["version"] != UNIT_INPUT_VERSION or row["kind"] != kind:
        raise ValueError("Private unit input has an unsupported identity.")
    return row[field]


def read_unit_catalog(payload: bytes) -> UnitInputCatalog:
    return _catalog(_document(payload, "catalog", "catalog"))


def read_unit_projection(payload: bytes) -> UnitProjection:
    row = _object(
        _document(payload, "projection", "projection"),
        (
            "season",
            "gameweek",
            "fixture_id",
            "decision_cutoff",
            "kickoff",
            "captured_at",
            "catalog",
            "home",
            "reference_own",
            "reference_opponent",
            "states",
            "causal_baseline_own_goal_rate",
            "causal_baseline_opponent_goal_rate",
        ),
        "unit projection",
    )
    return UnitProjection(
        season=_string(row["season"], "season"),
        gameweek=_integer(row["gameweek"], "gameweek"),
        fixture_id=_integer(row["fixture_id"], "fixture_id"),
        decision_cutoff=_time(row["decision_cutoff"], "decision_cutoff"),
        kickoff=_time(row["kickoff"], "kickoff"),
        captured_at=_time(row["captured_at"], "captured_at"),
        catalog=_catalog(row["catalog"]),
        home=_boolean(row["home"], "home"),
        reference_own=_unit(row["reference_own"]),
        reference_opponent=_unit(row["reference_opponent"]),
        states=tuple(_state(x) for x in _list(row["states"], "states")),
        causal_baseline_own_goal_rate=_number(row["causal_baseline_own_goal_rate"], "own baseline"),
        causal_baseline_opponent_goal_rate=_number(
            row["causal_baseline_opponent_goal_rate"], "opponent baseline"
        ),
    )


def read_unit_observations(payload: bytes) -> tuple[UnitObservation, ...]:
    result = []
    for item in _list(_document(payload, "observations", "observations"), "observations"):
        row = _object(
            item,
            (
                "season",
                "gameweek",
                "fixture_id",
                "decision_cutoff",
                "kickoff",
                "outcome_available_at",
                "outcome_source",
                "catalog",
                "home",
                "own",
                "opponent",
                "reference_own",
                "reference_opponent",
                "start_minute",
                "minutes",
                "own_goals",
                "opponent_goals",
                "causal_baseline_own_goal_rate",
                "causal_baseline_opponent_goal_rate",
            ),
            "unit observation",
        )
        result.append(
            UnitObservation(
                season=_string(row["season"], "season"),
                gameweek=_integer(row["gameweek"], "gameweek"),
                fixture_id=_integer(row["fixture_id"], "fixture_id"),
                decision_cutoff=_time(row["decision_cutoff"], "decision_cutoff"),
                kickoff=_time(row["kickoff"], "kickoff"),
                outcome_available_at=_time(row["outcome_available_at"], "outcome_available_at"),
                outcome_source=_source(row["outcome_source"]),
                catalog=_catalog(row["catalog"]),
                home=_boolean(row["home"], "home"),
                own=_unit(row["own"]),
                opponent=_unit(row["opponent"]),
                reference_own=_unit(row["reference_own"]),
                reference_opponent=_unit(row["reference_opponent"]),
                start_minute=_number(row["start_minute"], "start_minute"),
                minutes=_number(row["minutes"], "minutes"),
                own_goals=_integer(row["own_goals"], "own_goals"),
                opponent_goals=_integer(row["opponent_goals"], "opponent_goals"),
                causal_baseline_own_goal_rate=_number(
                    row["causal_baseline_own_goal_rate"], "own baseline"
                ),
                causal_baseline_opponent_goal_rate=_number(
                    row["causal_baseline_opponent_goal_rate"], "opponent baseline"
                ),
            )
        )
    if not result:
        raise ValueError("Unit training observations must be nonempty.")
    return tuple(result)
