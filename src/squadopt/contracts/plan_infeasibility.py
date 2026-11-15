"""Proven infeasibility and solver-verified edits for a captured decision."""

from __future__ import annotations

from typing import Literal, NotRequired, TypedDict, cast

from jsonschema import Draft202012Validator


class BankInfeasibility(TypedDict):
    required: int
    reachable: int
    exact: bool
    week: NotRequired[int]


class LowerBankFloor(TypedDict):
    kind: Literal["lower_bank_floor"]
    tenths: int


class DeferPurchase(TypedDict):
    kind: Literal["defer_purchase"]
    player_id: int
    from_week: int
    to_week: int


class ReleasePurchase(TypedDict):
    kind: Literal["release_purchase"]
    player_id: int
    week: int


PlanRepair = LowerBankFloor | DeferPurchase | ReleasePurchase


class PlanInfeasibility(TypedDict):
    repairs: list[PlanRepair]
    bank: NotRequired[BankInfeasibility]


def _object(properties: dict[str, object], required: list[str] | None = None) -> dict[str, object]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties) if required is None else required,
        "additionalProperties": False,
    }


def infeasibility_schema() -> dict[str, object]:
    week = {"type": "integer", "minimum": 1, "maximum": 3}
    amount = {"type": "integer", "minimum": 0, "maximum": 10_000}
    player = {"type": "integer", "minimum": 1, "maximum": 2**53 - 1}
    return _object(
        {
            "repairs": {
                "type": "array",
                "maxItems": 3,
                "uniqueItems": True,
                "items": {
                    "oneOf": [
                        _object({"kind": {"const": "lower_bank_floor"}, "tenths": amount}),
                        _object(
                            {
                                "kind": {"const": "defer_purchase"},
                                "player_id": player,
                                "from_week": week,
                                "to_week": week,
                            }
                        ),
                        _object(
                            {
                                "kind": {"const": "release_purchase"},
                                "player_id": player,
                                "week": week,
                            }
                        ),
                    ]
                },
            },
            "bank": _object(
                {
                    "required": {**amount, "minimum": 1},
                    "reachable": amount,
                    "exact": {"type": "boolean"},
                    "week": week,
                },
                ["required", "reachable", "exact"],
            ),
        },
        ["repairs"],
    )


_VALIDATOR = Draft202012Validator(infeasibility_schema())


def parse_infeasibility(value: object) -> PlanInfeasibility:
    if not _VALIDATOR.is_valid(value):
        raise ValueError("Invalid plan infeasibility.")
    details = cast(PlanInfeasibility, value)
    bank = details.get("bank")
    if bank is not None and bank["reachable"] >= bank["required"]:
        raise ValueError("The reachable bank must be below the required bank.")
    for repair in details["repairs"]:
        if repair["kind"] == "lower_bank_floor" and (
            bank is None or repair["tenths"] != bank["reachable"]
        ):
            raise ValueError("A lower bank repair needs a matching verified balance.")
        if repair["kind"] == "defer_purchase" and repair["from_week"] >= repair["to_week"]:
            raise ValueError("A deferred purchase must target a later week.")
    return details
