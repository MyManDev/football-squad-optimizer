"""Credential-free identity for one confirmed planning run (ADR 0018)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class RunReference:
    run_id: str
    stage: Literal["base", "followup"]

    @classmethod
    def parse(cls, value: object) -> RunReference:
        if not isinstance(value, dict) or set(value) != {"contract_version", "run_id", "stage"}:
            raise ValueError("Invalid planning run reference.")
        if value["contract_version"] != "llmopt_run_v1":
            raise ValueError("Unsupported planning run reference.")
        identifier, stage = value["run_id"], value["stage"]
        if not isinstance(identifier, str) or re.fullmatch(r"[0-9a-f]{32}", identifier) is None:
            raise ValueError("run_id must contain 32 lowercase hexadecimal digits.")
        if stage not in ("base", "followup"):
            raise ValueError("Unknown planning run stage.")
        return cls(identifier, stage)


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
            "stage": {"type": "string", "enum": ["base", "followup"]},
        },
        "required": ["contract_version", "run_id", "stage"],
        "additionalProperties": False,
    }
