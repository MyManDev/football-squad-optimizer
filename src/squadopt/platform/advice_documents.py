"""The public read contracts: what the advice route and the league route may serve.

The cache stores bytes and the api serves them verbatim â€” that is the design, and it
is exactly why the boundary needs its own contract: without one, a cache writer or a
corrupted disk entry could make the api publish arbitrary JSON while the route claims
a versioned answer. These schemas are that contract, committed beside the other wire
schemas, validated **at read** (a corrupted entry is an internal error, never a
published document) and by the compute adapter at write when the composition root
lands â€” the worker itself stays ignorant of document semantics by design.

The advice document is the league tree's own envelope â€” the same
``provisional_league_ui_v1`` bytes the static site serves â€” so the two distribution
paths cannot drift apart. The payload keeps ``additionalProperties`` open because the
producer grows honest fields (``solver_status`` arrived that way); the required core
and its types are the contract.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Final

import jsonschema

from squadopt.application.advice_capabilities import MEMBER_WINDOWS, PREDICTION_MODELS
from squadopt.contracts.football_explanations import policy_comparison_schema, role_forecast_schema
from squadopt.contracts.information import decision_information_schema, official_information_schema
from squadopt.contracts.injuries import official_injuries_schema
from squadopt.contracts.league import LEAGUE_VIEW_CONTRACT_VERSION
from squadopt.contracts.preferences import preferences_schema
from squadopt.planning.chip_strategy import CHIP_STRATEGY_VERSION

LEAGUE_STATE_CONTRACT_VERSION: Final = "league_state_v1"
LEAGUE_CAPABILITIES_CONTRACT_VERSION: Final = "league_capabilities_v1"
ADVICE_READ_SCHEMA_PATH: Final = Path("docs") / "contracts" / "advice_read_v1.schema.json"
LEAGUE_STATE_SCHEMA_PATH: Final = Path("docs") / "contracts" / "league_state_v1.schema.json"
LEAGUE_CAPABILITIES_SCHEMA_PATH: Final = (
    Path("docs") / "contracts" / "league_capabilities_v1.schema.json"
)


class AdviceDocumentError(ValueError):
    """Bytes that claim to be a versioned advice answer, and are not."""


def lineup_expectation_schema() -> dict[str, Any]:
    fields: dict[str, Any] = {
        "version": {"const": "expected_lineup_v1"},
        **{
            name: {"type": "number"}
            for name in (
                "expected_net_points",
                "starting_points",
                "autosub_points",
                "captain_bonus_points",
                "vice_bonus_points",
                "bench_boost_points",
            )
        },
        "assumptions": {"type": "array", "items": {"type": "string"}},
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": fields,
        "required": list(fields),
    }


def participation_evidence_schema() -> dict[str, Any]:
    fields: dict[str, Any] = {
        "version": {"const": "football_participation_evidence_v1"},
        "as_of": {"type": ["string", "null"]},
        "gameweek": {"type": ["integer", "null"], "minimum": 1},
        **{
            name: {"type": "integer", "minimum": 0}
            for name in (
                "applied_player_count",
                "unapplied_statement_count",
                "captured_percentage_count",
                "manager_statement_count",
            )
        },
        "assumptions": {"type": "array", "items": {"type": "string"}},
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            **fields,
            "statement_outcomes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "player_id": {"type": "integer", "minimum": 1},
                        "disposition": {"type": "string"},
                        "applied": {"type": "boolean"},
                        "reason": {"type": "string"},
                        "source_url": {"type": ["string", "null"]},
                        "source_published_at": {"type": ["string", "null"]},
                    },
                    "required": [
                        "player_id",
                        "disposition",
                        "applied",
                        "reason",
                        "source_url",
                        "source_published_at",
                    ],
                },
            },
        },
        "required": list(fields),
    }


def lineup_decision_schema(player: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "starting_xi": {"type": "array", "items": player, "minItems": 11, "maxItems": 11},
            "captain": player,
            "vice_captain": player,
            "bench": {"type": "array", "items": player, "minItems": 4, "maxItems": 4},
        },
        "required": ["starting_xi", "captain", "vice_captain", "bench"],
    }


def information_review_schema() -> dict[str, Any]:
    names = {"type": "array", "items": {"type": "string"}}
    nullable = {"type": ["number", "null"]}
    chip = {"enum": [None, "bboost", "3xc", "wildcard", "freehit"]}
    week = {
        "gameweek": {"type": "integer", "minimum": 1},
        "transfers_in": names,
        "transfers_out": names,
        "chip": chip,
        "bank_tenths": {"type": "integer", "minimum": 0},
        "free_transfers": {"type": "integer", "minimum": 0},
        "lineup": lineup_decision_schema({"type": "string"}),
    }
    branch = {
        "state": {"enum": ["eligible", "unavailable"]},
        "expected_net_points": nullable,
        "hit_points": {"type": "number", "minimum": 0},
        "weeks": {
            "type": "array",
            "minItems": 2,
            "maxItems": 4,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": week,
                "required": [name for name in week if name != "lineup"],
            },
        },
    }
    candidate = {
        "selected": {"type": "boolean"},
        "baseline": {"type": "boolean"},
        "transfers_in": names,
        "transfers_out": names,
        "chip": chip,
        "expected_net_points": nullable,
        "first_lineup": lineup_decision_schema({"type": "string"}),
        "branches": {
            "type": "array",
            "minItems": 2,
            "maxItems": 2,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": branch,
                "required": list(branch),
            },
        },
    }
    fields = {
        "version": {"const": "football_information_review_v1"},
        "status": {"enum": ["compared", "baseline_retained"]},
        "reason": {"type": "string"},
        "source_snapshot_id": {"type": "string"},
        "captured_at_utc": {"type": "string"},
        "player_name": {"type": ["string", "null"]},
        "source_playing_chance_percent": {"enum": [None, 25, 50, 75]},
        "information_gameweek": {"type": ["integer", "null"]},
        "candidates": {
            "type": "array",
            "maxItems": 4,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": candidate,
                "required": [name for name in candidate if name != "first_lineup"],
            },
        },
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {**fields, "comparison": policy_comparison_schema()},
        "required": list(fields),
    }


def advice_read_schema() -> dict[str, Any]:
    """The strict shape of one served advice document."""

    player = {
        "type": "object",
        "properties": {
            "player_id": {"type": "integer", "minimum": 1},
            "name": {"type": "string"},
            "short_name": {"type": "string"},
            "position": {"enum": ["GK", "DEF", "MID", "FWD"]},
            "team": {"type": "string"},
            "expected_points": {"type": "number"},
        },
        "required": ["player_id", "name", "short_name", "position", "team"],
    }
    chip = {"enum": [None, "bboost", "3xc", "wildcard", "freehit"]}
    plan_week = {
        "type": "object",
        "properties": {
            "gameweek": {"type": "integer", "minimum": 1},
            "transfers_in": {"type": "array", "items": player},
            "transfers_out": {"type": "array", "items": player},
            "transfer_hit_points": {"type": "number"},
            "chip": chip,
            "free_transfers_before": {"type": "integer", "minimum": 0},
            "free_transfers_after": {"type": "integer", "minimum": 0},
            "expected_points": {"type": "number"},
            "lineup_expectation": lineup_expectation_schema(),
            "lineup": lineup_decision_schema(player),
        },
        "required": [
            "gameweek",
            "transfers_in",
            "transfers_out",
            "transfer_hit_points",
            "chip",
            "free_transfers_before",
            "free_transfers_after",
            "expected_points",
        ],
    }
    nullable_number = {"type": ["number", "null"]}
    optional_fields: dict[str, Any] = {
        name: {"type": "number"}
        for name in (
            "transfer_hit_points",
            "expected_points_cost",
            "expected_points_cost_ceiling",
            "overlap_count",
            "expected_gap_vs_rival",
            "transfer_cap",
            "overlap_target",
            "overlap_applied",
        )
    }
    optional_fields.update(
        {
            "source_snapshot_id": {"type": ["string", "null"]},
            "preferences": preferences_schema(),
            "preferences_scope": {"const": "all_selected_weeks"},
            "selection_top100_weight": {"enum": [0, 5, 10, 20, 30, 40, 50]},
            "prediction_model": {
                "type": "object",
                "properties": {
                    "id": {"const": "football"},
                    "version": {
                        "enum": [
                            "football_team_share_v1",
                            "football_contextual_v3",
                            "football_match_context_v1",
                            "football_joint_role_minutes_v1",
                            "football_joint_role_retained_history_v1",
                        ]
                    },
                    "experimental": {"const": True},
                    "fingerprint": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
                },
                "required": ["id", "version", "experimental", "fingerprint"],
                "additionalProperties": False,
            },
            "rival_label": {"type": ["string", "null"]},
            "rival_entry_id": {"type": "integer", "minimum": 1},
            "solver_status": {"type": ["string", "null"]},
            "wall_clock_stopped_the_search": {"type": ["boolean", "null"]},
            "control_solver_status": {"type": ["string", "null"]},
            "optimality_gap": nullable_number,
            "control_optimality_gap": nullable_number,
            # The manager's word as it entered this plan: present on the switched-on
            # document only. The words are the source's, cut from captured bytes; the
            # category is the model's; the role is the declared rule's. No probability.
            "evidence": {
                "type": "object",
                "properties": {
                    "kind": {"const": "managers_word"},
                    "rule_version": {"type": "string"},
                    "source_kind": {"type": "string"},
                    "source_label": {"type": "string"},
                    "evidence_table": {"type": "string"},
                    "clubs_covered": {"type": "array", "items": {"type": "string"}},
                    "binding": {"type": "boolean"},
                    "applied": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "player_id": {"type": "integer", "minimum": 1},
                                "name": {"type": ["string", "null"]},
                                "disposition": {"type": "string"},
                                "role": {"enum": ["not_starting", "not_captain", None]},
                                "speaker": {"type": ["string", "null"]},
                                "published_at_utc": {"type": ["string", "null"]},
                                "published_precision": {"type": ["string", "null"]},
                                "club": {"type": ["string", "null"]},
                                "source_url": {"type": ["string", "null"]},
                                "fetched_at_utc": {"type": ["string", "null"]},
                                "words": {"type": ["string", "null"]},
                                "words_status": {
                                    "enum": ["shown", "unresolved", "withheld_figure"]
                                },
                            },
                            "required": ["player_id", "disposition", "role", "words"],
                        },
                    },
                },
                "required": ["kind", "source_kind", "clubs_covered", "applied"],
            },
            # The Top 100 influence a weighted document was chosen under. The weight is a
            # setting, not a share; every expected-points number in the document is the
            # base model's.
            "top100": {
                "type": "object",
                "properties": {
                    "weight": {"enum": [5, 10, 20, 30, 40, 50]},
                    "changed": {"type": "boolean"},
                    "price_basis": {"const": "base_model_pure_points_v1"},
                    "cohort_snapshot_id": {"type": "string"},
                    "picks_snapshot_id": {"type": "string"},
                    "table_sha256": {"type": "string"},
                    "picks_gameweek": {"type": "integer", "minimum": 1},
                },
                "required": ["weight", "changed", "price_basis"],
            },
            # A chip the member chose to play: the chip, the chip week's expected points
            # above the member's own no-chip plan net of hits, and the chip's windows as
            # the member stands before this gameweek. One gameweek's difference, never a
            # reading of when the chip is best played.
            "chip_strategy": {
                "type": "object",
                "properties": {
                    "version": {"const": CHIP_STRATEGY_VERSION},
                    "mode": {"enum": ["auto", "manual"]},
                    "requested_chip": {"enum": ["auto", "bboost", "3xc", "wildcard", "freehit"]},
                    "selected_chip": chip,
                    "top100_weight": {"enum": [0, 5, 10, 20, 30, 40, 50]},
                    "objective_gap": nullable_number,
                    "objective_basis": {"const": "selection_utility_with_chip_reserve"},
                    "experimental": {"type": "boolean"},
                    "reservations": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "chip": {"enum": ["bboost", "3xc", "wildcard", "freehit"]},
                                "first_gameweek": {"type": "integer", "minimum": 1},
                                "last_gameweek": {"type": "integer", "minimum": 1},
                                "remaining_opportunities": {"type": "integer", "minimum": 0},
                                "holding_value": {"type": "number", "minimum": 0},
                                "sample_min": {"type": "number", "minimum": 0},
                                "sample_max": {"type": "number", "minimum": 0},
                            },
                            "required": [
                                "chip",
                                "first_gameweek",
                                "last_gameweek",
                                "remaining_opportunities",
                                "holding_value",
                                "sample_min",
                                "sample_max",
                            ],
                            "additionalProperties": False,
                        },
                    },
                    "limits": {"type": "array", "items": {"type": "string"}},
                },
                "required": [
                    "version",
                    "mode",
                    "requested_chip",
                    "selected_chip",
                    "top100_weight",
                    "objective_gap",
                    "objective_basis",
                    "experimental",
                    "reservations",
                    "limits",
                ],
                "additionalProperties": False,
            },
            "chip_choice": {
                "type": "object",
                "properties": {
                    "chip": {"enum": ["bboost", "3xc", "wildcard", "freehit"]},
                    "gain_vs_no_chip": {"type": "number"},
                    "basis": {"const": "one_week_expected_points_v1"},
                    "windows_left": {
                        "type": "object",
                        "additionalProperties": {
                            "anyOf": [
                                {"type": "null"},
                                {
                                    "type": "object",
                                    "properties": {
                                        "state": {
                                            "enum": [
                                                "used",
                                                "expired",
                                                "not_yet",
                                                "available",
                                                "unknown",
                                            ]
                                        },
                                        "gameweek": {"type": ["integer", "null"]},
                                        "start_event": {"type": "integer", "minimum": 1},
                                        "stop_event": {"type": "integer", "minimum": 1},
                                    },
                                    "required": ["state", "start_event", "stop_event"],
                                },
                            ]
                        },
                    },
                },
                "required": ["chip", "gain_vs_no_chip", "basis"],
            },
            "expected_own_points": nullable_number,
            "lineup_expectation": lineup_expectation_schema(),
            "participation_evidence": participation_evidence_schema(),
            "role_forecast": role_forecast_schema(),
            "official_information": official_information_schema(),
            "official_injuries": official_injuries_schema(),
            "decision_information": decision_information_schema(),
            # Null where the comparison against holding could not be walked, which is
            # not the same fact as a plan that gains nothing.
            "expected_gain_vs_hold": nullable_number,
            "captain_agreement": {"type": "boolean"},
            "captain": {"anyOf": [player, {"type": "null"}]},
            "vice_captain": {"anyOf": [player, {"type": "null"}]},
            "starting_xi": {"type": ["array", "null"], "items": player},
            "bench": {"type": ["array", "null"], "items": player},
            "chip": chip,
            "plan_weeks": {"type": ["array", "null"], "items": plan_week},
            "information_review": information_review_schema(),
            "stated_limits": {"type": ["array", "null"], "items": {"type": "string"}},
            "squad_basis": {"type": "string"},
            "plan_kind": {"enum": ["within_free_transfers", "with_hits"]},
            "alternative_plan": {
                "type": ["object", "null"],
                "properties": {
                    "kind": {"enum": ["within_free_transfers", "with_hits"]},
                    "overlap_applied": {"type": "number"},
                    "transfer_hit_points": nullable_number,
                    "expected_points_cost": {"type": "number"},
                    "expected_points_cost_ceiling": {"type": "number"},
                },
                "required": [
                    "kind",
                    "overlap_applied",
                    "transfer_hit_points",
                    "expected_points_cost",
                ],
            },
        }
    )
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://squadopt.dev/contracts/advice_read_v1.schema.json",
        "title": "SquadOpt served advice document",
        "type": "object",
        "properties": {
            "contract_version": {"type": "string", "const": LEAGUE_VIEW_CONTRACT_VERSION},
            "generated_at_utc": {"type": "string", "pattern": "Z$"},
            "source_kind": {"enum": ["live", "example"]},
            "payload": {
                "type": "object",
                "properties": {
                    "season": {"type": "string"},
                    "gameweek": {"type": "integer", "minimum": 1},
                    "entry_id": {"type": "integer", "minimum": 1},
                    "league_id": {"type": "integer", "minimum": 1},
                    "mode": {"type": "string"},
                    "window": {"type": "integer", "enum": list(MEMBER_WINDOWS)},
                    "moves": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "move_id": {"type": "string"},
                                "player_out": {"anyOf": [player, {"type": "null"}]},
                                "player_in": {"anyOf": [player, {"type": "null"}]},
                                # Null where the row's share of the plan's gain could
                                # not be measured; the row still names the swap.
                                "expected_points_delta": nullable_number,
                                "reason_code": {
                                    "enum": [
                                        "window_value",
                                        "mode_tradeoff",
                                        "points_gain",
                                        "manager_word",
                                        "top100_preference",
                                    ]
                                },
                            },
                            "required": [
                                "move_id",
                                "player_out",
                                "player_in",
                                "expected_points_delta",
                                "reason_code",
                            ],
                        },
                    },
                    "data_quality": {"enum": ["complete", "partial", "empty"]},
                    "missing_fields": {"type": "array", "items": {"type": "string"}},
                    **optional_fields,
                },
                "required": [
                    "season",
                    "gameweek",
                    "entry_id",
                    "league_id",
                    "mode",
                    "window",
                    "moves",
                    "data_quality",
                    "missing_fields",
                ],
                "additionalProperties": True,
            },
        },
        "required": ["contract_version", "generated_at_utc", "source_kind", "payload"],
        "additionalProperties": False,
    }


def league_state_schema() -> dict[str, Any]:
    """The strict shape of the league-connection answer."""

    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://squadopt.dev/contracts/league_state_v1.schema.json",
        "title": "SquadOpt league connection state",
        "type": "object",
        "properties": {
            "contract_version": {"type": "string", "const": LEAGUE_STATE_CONTRACT_VERSION},
            "league_id": {"type": "integer", "minimum": 1},
            "connected": {"type": "boolean"},
            "league_name": {"anyOf": [{"type": "string"}, {"type": "null"}]},
            "season": {"anyOf": [{"type": "string"}, {"type": "null"}]},
            "gameweek": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
            "member_count": {"type": "integer", "minimum": 0},
        },
        "required": ["contract_version", "league_id", "connected"],
        "additionalProperties": False,
    }


def league_capabilities_schema() -> dict[str, Any]:
    """The strict shape of what may be asked for a league right now.

    A page reads this before it enables a control: the strategies and their windows are
    the deployment's, and each switch is ``available`` only while the current capture has
    the input it is computed from. ``weights`` are the Top 100 settings that would be
    accepted now, so zero (off) is always among them.
    """

    flag = {
        "type": "object",
        "properties": {"available": {"type": "boolean"}},
        "required": ["available"],
        "additionalProperties": False,
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://squadopt.dev/contracts/league_capabilities_v1.schema.json",
        "title": "SquadOpt league advice capabilities",
        "type": "object",
        "properties": {
            "contract_version": {
                "type": "string",
                "const": LEAGUE_CAPABILITIES_CONTRACT_VERSION,
            },
            "league_id": {"type": "integer", "minimum": 1},
            "capture_snapshot_id": {"type": "string", "minLength": 1},
            "preferences": {
                "type": "object",
                "properties": {"available": {"type": "boolean"}},
                "required": ["available"],
                "additionalProperties": False,
            },
            "season": {"type": "string", "minLength": 1},
            "gameweek": {"type": "integer", "minimum": 1},
            "strategies": {
                "type": "object",
                "additionalProperties": {
                    "type": "object",
                    "properties": {
                        "windows": {
                            "type": "array",
                            "items": {"type": "integer", "enum": list(MEMBER_WINDOWS)},
                            "uniqueItems": True,
                        },
                        "requires_rival": {"type": "boolean"},
                    },
                    "required": ["windows", "requires_rival"],
                    "additionalProperties": False,
                },
            },
            "top100": {
                "type": "object",
                "properties": {
                    "available": {"type": "boolean"},
                    "weights": {
                        "type": "array",
                        "items": {"type": "integer", "minimum": 0, "maximum": 100},
                        "uniqueItems": True,
                    },
                },
                "required": ["available", "weights"],
                "additionalProperties": False,
            },
            "decision_information": decision_information_schema(),
            "models": {
                "type": "array",
                "items": {"enum": list(PREDICTION_MODELS)},
                "uniqueItems": True,
            },
            "managers_word": flag,
            "chips": {
                "type": "object",
                "properties": {
                    "strategy": {
                        "type": "object",
                        "properties": {
                            "version": {"const": CHIP_STRATEGY_VERSION},
                            "windows": {
                                "type": "array",
                                "items": {"enum": list(MEMBER_WINDOWS)},
                                "uniqueItems": True,
                            },
                        },
                        "required": ["version", "windows"],
                        "additionalProperties": False,
                    },
                    "held_by_entry": {
                        "type": "object",
                        "patternProperties": {
                            "^[1-9][0-9]*$": {
                                "type": "array",
                                "items": {"enum": ["wildcard", "freehit", "bboost", "3xc"]},
                                "uniqueItems": True,
                            }
                        },
                        "additionalProperties": False,
                    },
                },
                "required": ["held_by_entry"],
                "additionalProperties": False,
            },
        },
        "required": [
            "contract_version",
            "league_id",
            "capture_snapshot_id",
            "season",
            "gameweek",
            "strategies",
            "top100",
            "managers_word",
        ],
        "additionalProperties": False,
    }


_ADVICE_VALIDATOR: Final = jsonschema.Draft202012Validator(advice_read_schema())
_LEAGUE_STATE_VALIDATOR: Final = jsonschema.Draft202012Validator(league_state_schema())
_LEAGUE_CAPABILITIES_VALIDATOR: Final = jsonschema.Draft202012Validator(
    league_capabilities_schema()
)


def validate_advice_document(raw: bytes) -> None:
    """Refuse bytes that do not carry the versioned advice shape."""

    try:
        document = json.loads(raw, parse_constant=_invalid_number, parse_float=_finite_float)
    except (UnicodeDecodeError, ValueError) as error:
        raise AdviceDocumentError("The advice document is not valid JSON.") from error
    errors = sorted(_ADVICE_VALIDATOR.iter_errors(document), key=str)
    if errors:
        raise AdviceDocumentError(
            f"The advice document violates advice_read_v1: {errors[0].message}"
        )


def _invalid_number(value: str) -> None:
    raise ValueError(f"Non-finite JSON number: {value}.")


def _finite_float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("The JSON number is outside the finite range.")
    return number


def validate_league_state(document: dict[str, object]) -> None:
    errors = sorted(_LEAGUE_STATE_VALIDATOR.iter_errors(document), key=str)
    if errors:
        raise AdviceDocumentError(f"The league state violates league_state_v1: {errors[0].message}")


def validate_league_capabilities(document: dict[str, object]) -> None:
    errors = sorted(_LEAGUE_CAPABILITIES_VALIDATOR.iter_errors(document), key=str)
    if errors:
        raise AdviceDocumentError(
            f"The capabilities violate league_capabilities_v1: {errors[0].message}"
        )
