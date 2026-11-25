"""Credential-free identity for one confirmed planning run (ADR 0018)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from squadopt.contracts.repair_origin import RepairOrigin, repair_origin_schema


@dataclass(frozen=True, slots=True)
class RunReference:
    run_id: str
    stage: Literal["base", "followup", "repair"]
    repair_origin: RepairOrigin | None = None

    @classmethod
    def parse(cls, value: object) -> RunReference:
        if not isinstance(value, dict) or set(value) - {"repair_origin"} != {
            "contract_version",
            "run_id",
            "stage",
        }:
            raise ValueError("Invalid planning run reference.")
        if value["contract_version"] != "llmopt_run_v1":
            raise ValueError("Unsupported planning run reference.")
        identifier, stage = value["run_id"], value["stage"]
        if not isinstance(identifier, str) or re.fullmatch(r"[0-9a-f]{32}", identifier) is None:
            raise ValueError("run_id must contain 32 lowercase hexadecimal digits.")
        if stage not in ("base", "followup", "repair"):
            raise ValueError("Unknown planning run stage.")
        origin = RepairOrigin.parse(value["repair_origin"]) if "repair_origin" in value else None
        if origin is not None and stage == "followup":
            raise ValueError("Original repair rules apply only to candidates and selection.")
        return cls(identifier, stage, origin)


def workflow_enabled(window: int, *, master: bool, three_week: bool) -> bool:
    """The server grants one week directly and three weeks through both controls."""
    return master and (window == 1 or (window == 3 and three_week))


def run_capacity(window: int) -> float:
    """The four-job capacity measured and explained in ADR 0018."""
    if window not in (1, 3):
        raise ValueError("Planning runs support one or three weeks.")
    return 84.0 if window == 1 else 488.0


def job_capacity(window: int) -> float:
    return run_capacity(window) / 4


def run_reference_schema() -> dict[str, object]:
    return {
        "type": "object",
        "properties": {
            "contract_version": {"type": "string", "const": "llmopt_run_v1"},
            "run_id": {"type": "string", "pattern": "^[0-9a-f]{32}$"},
            "stage": {"type": "string", "enum": ["base", "followup", "repair"]},
            "repair_origin": repair_origin_schema(),
        },
        "if": {"required": ["repair_origin"]},
        "then": {"properties": {"stage": {"enum": ["base", "repair"]}}},
        "required": ["contract_version", "run_id", "stage"],
        "additionalProperties": False,
    }


def run_ledger_schema() -> dict[str, object]:
    """Internal durable ledger, including bounded pre-admission cancellations."""
    identifier = {"type": "string", "pattern": "^[0-9a-f]{32}$"}
    key = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
    run = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "binding",
            "capture",
            "window",
            "base",
            "closed",
            "base_cached",
            "requests",
            "reserved",
        ],
        "properties": {
            "binding": key,
            "capture": {"type": ["string", "null"]},
            "window": {"type": "integer", "enum": [1, 3]},
            "base": key,
            "closed": {"type": "boolean"},
            "base_cached": {"type": "boolean"},
            "repair_candidates": {
                "type": "array",
                "items": key,
                "maxItems": 2,
                "uniqueItems": True,
            },
            "requests": {
                "type": "object",
                "maxProperties": 4,
                "propertyNames": key,
                "additionalProperties": {"type": "string"},
            },
            "reserved": {"type": "number", "minimum": 0, "maximum": 488},
        },
    }
    job = {
        "type": "object",
        "additionalProperties": False,
        "required": ["limit", "runs", "receipt", "legacy_consumer"],
        "properties": {
            "limit": {"type": "number", "enum": [21, 63, 122, 366]},
            "runs": {"type": "array", "items": identifier, "minItems": 1, "uniqueItems": True},
            "legacy_consumer": {"type": "boolean"},
            "receipt": {
                "type": ["object", "null"],
                "properties": {
                    "answer_sha256": key,
                    "attempt": {"type": "integer", "minimum": 1},
                    "finished": {"type": "boolean"},
                    "calls": {"type": "integer", "minimum": 0},
                    **{
                        name: {"type": "number", "minimum": 0}
                        for name in (
                            "cp_used",
                            "native_reserved",
                            "pending",
                            "unconfirmed",
                            "charged",
                        )
                    },
                },
                "dependentRequired": {
                    "attempt": [
                        "finished",
                        "calls",
                        "cp_used",
                        "native_reserved",
                        "pending",
                        "unconfirmed",
                    ],
                    "charged": ["attempt"],
                },
            },
        },
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["contract_version", "runs", "jobs", "cancelled"],
        "properties": {
            "contract_version": {"type": "string", "const": "llmopt_run_ledger_v2"},
            "runs": {"type": "object", "propertyNames": identifier, "additionalProperties": run},
            "jobs": {"type": "object", "additionalProperties": job},
            "cancelled": {
                "type": "object",
                "propertyNames": identifier,
                "maxProperties": 1024,
                "additionalProperties": {"type": "number", "minimum": 0},
            },
        },
    }
