"""Public capture-level receipts for the six-family experimental forecast.

These declarations are checked again against the required private reprojection
companion. A matching hash establishes byte identity, not source authenticity.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from squadopt.prediction.football_capabilities import (
    COMPOSITE_ACTIVE_HEADS,
    COMPOSITE_AVAILABILITY_POLICY,
    COMPOSITE_FEATURE_VERSION,
    COMPOSITE_MODEL_VERSION,
    COMPOSITE_REPROJECTION_VERSION,
)

COMPOSITE_ASSET_ROLES = ("flags", "load", "unit", "score", "tactical", "phase")
_FIELDS = {
    "version",
    "active_heads",
    "availability_application",
    "model_artifacts",
    "basis_sha256",
    "fixture_receipts_sha256",
    "generated_at",
    "decision_at",
    "weekly_laws",
}


def _sha(value: Any) -> str:
    if type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError("Composite receipt requires a lowercase SHA256 identity.")
    return value


def _clock(value: Any) -> datetime:
    if type(value) is not str:
        raise ValueError("Composite receipt requires a timestamp string.")
    clock = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if clock.tzinfo is None or clock.utcoffset() is None:
        raise ValueError("Composite receipt timestamp requires an explicit offset.")
    return clock


def composite_weekly_chances(
    document: Mapping[str, Any],
) -> dict[tuple[int, int], float] | None:
    """Check exact receipt inventories and bind every served week to its final law."""
    if document.get("model_version") != COMPOSITE_MODEL_VERSION:
        return None
    try:
        metadata = document["composite_metadata"]
        if (
            document.get("feature_contract_version") != COMPOSITE_FEATURE_VERSION
            or document.get("availability_application") != COMPOSITE_AVAILABILITY_POLICY
            or type(metadata) is not dict
            or set(metadata) != _FIELDS
            or metadata["version"] != COMPOSITE_REPROJECTION_VERSION
            or metadata["active_heads"] != list(COMPOSITE_ACTIVE_HEADS)
            or metadata["availability_application"] != COMPOSITE_AVAILABILITY_POLICY
        ):
            raise ValueError("Composite forecast requires its exact version and active heads.")
        _sha(metadata["basis_sha256"])
        _sha(metadata["fixture_receipts_sha256"])
        if not (
            _clock(document["captured_at_utc"])
            <= _clock(metadata["generated_at"])
            <= _clock(metadata["decision_at"])
        ):
            raise ValueError("Composite assembly and decision must follow the real capture.")
        assets = metadata["model_artifacts"]
        if type(assets) is not list or len(assets) != len(COMPOSITE_ASSET_ROLES):
            raise ValueError("Composite forecast requires all six family asset identities.")
        for role, asset in zip(COMPOSITE_ASSET_ROLES, assets, strict=True):
            if (
                type(asset) is not dict
                or set(asset) != {"role", "kind", "sha256", "fit_sha256"}
                or asset["role"] != role
                or asset["kind"] != ("retained_flag_result" if role == "flags" else "compact_model")
            ):
                raise ValueError("Composite family inventory or source kind differs.")
            _sha(asset["sha256"])
            _sha(asset["fit_sha256"])
        rows = document["rows"]
        laws = metadata["weekly_laws"]
        if (
            type(rows) is not list
            or type(laws) is not list
            or not 0 < len(laws) == len(rows) <= 10000
        ):
            raise ValueError("Composite final weekly law coverage differs from its rows.")
        result = {}
        fixture_counts = {}
        for law in laws:
            if type(law) is not dict or set(law) != {
                "gameweek",
                "player_code",
                "sha256",
                "appearance_probability",
                "fixture_ids",
            }:
                raise ValueError("Composite weekly law receipt fields differ.")
            week, player = law["gameweek"], law["player_code"]
            if (
                type(week) is not int
                or not 1 <= week <= 38
                or type(player) is not int
                or player <= 0
            ):
                raise ValueError("Composite weekly law identity is invalid.")
            key = week, player
            if key in result:
                raise ValueError("Composite weekly law identity is repeated.")
            _sha(law["sha256"])
            fixture_ids = law["fixture_ids"]
            if (
                type(fixture_ids) is not list
                or len(fixture_ids) > 3
                or any(type(f) is not int or f <= 0 for f in fixture_ids)
                or len(set(fixture_ids)) != len(fixture_ids)
            ):
                raise ValueError("Composite weekly law fixture scope is invalid.")
            q = law["appearance_probability"]
            if type(q) not in (int, float) or not math.isfinite(q) or not 0 <= q <= 1:
                raise ValueError("Composite weekly appearance requires a finite probability.")
            if not fixture_ids and q != 0:
                raise ValueError("A blank composite week cannot have positive appearance.")
            result[key] = float(q)
            fixture_counts[key] = len(fixture_ids)
        seen = set()
        for row in rows:
            key = row["gameweek"], row["player_id"]
            if key in seen or key not in result or any(type(v) is not int for v in key):
                raise ValueError("Composite served row identity differs from the final laws.")
            q = row["appearance_probability"]
            if (
                type(q) not in (int, float)
                or not math.isfinite(q)
                or not math.isclose(q, result[key], rel_tol=0, abs_tol=1e-12)
                or type(row["fixture_count"]) is not int
                or row["fixture_count"] != fixture_counts[key]
            ):
                raise ValueError(
                    "Composite weekly appearance or fixture count differs from its law."
                )
            seen.add(key)
        if seen != result.keys():
            raise ValueError("Composite weekly laws lack exact served coverage.")
        return result
    except (KeyError, TypeError, AttributeError, OverflowError) as error:
        raise ValueError("Malformed composite forecast receipt.") from error
