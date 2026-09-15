"""A member's explicit Top-100 preference, applied once to the existing projection."""

from collections.abc import Mapping
from dataclasses import replace

import pandas as pd

from squadopt.application.advice import HorizonBuilder
from squadopt.application.entries import EntryError
from squadopt.live import Projection
from squadopt.planning.horizon import ProjectionHorizon
from squadopt.prediction.elite_evidence import validate_top100_weight


class Top100InputsUnavailable(EntryError):
    """The handoff cannot support the requested change of evidence weight."""


def weighted_member_inputs(
    projection: Projection,
    horizon_builder: HorizonBuilder,
    *,
    source_weight: int,
    requested_weight: int,
    counts: Mapping[int, int] | None,
) -> tuple[Projection, HorizonBuilder]:
    weight = validate_top100_weight(requested_weight)
    if counts is None and source_weight != weight:
        raise Top100InputsUnavailable(
            "The handoff has no fingerprinted Top-100 counts for this adjustment."
        )
    if counts is None and weight != 0:
        raise Top100InputsUnavailable("Verified counts are required to price this preference.")

    def adjusted(table: pd.DataFrame) -> pd.DataFrame:
        result = table.copy(deep=True)
        if source_weight != weight:
            assert counts is not None
            support = result["player_id"].map(counts).fillna(0).astype(float) / 100
            # Replace the existing uplift, never stack another uplift on top.
            ratio = (1 + weight / 100 * support) / (1 + source_weight / 100 * support)
            result["expected_points"] = result["expected_points"].astype(float) * ratio
        return result

    def horizon(targets: tuple[int, ...]) -> ProjectionHorizon:
        original = horizon_builder(targets)
        return replace(
            original,
            table=adjusted(original.table),
            post_processing_contract_version=f"{original.post_processing_contract_version}:top100-{weight}",
        )

    return replace(
        projection,
        table=adjusted(projection.table),
        diagnostics={
            **dict(projection.diagnostics),
            "personal_top100_weight_percent": weight,
            "top100_base_point_ratios": {
                int(player): 1 / (1 + weight * (counts or {}).get(int(player), 0) / 10_000)
                for player in projection.table["player_id"]
            },
        },
    ), horizon
