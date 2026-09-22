"""Expose disagreements between analytic marginals and the constrained match law."""

from __future__ import annotations

import numpy as np
import pandas as pd

from squadopt.scenarios.football import FootballDraws


def football_mean_diagnostics(components: pd.DataFrame, draws: FootballDraws) -> dict[str, float]:
    reference = components.set_index(["fixture", "player_code"])
    sampled = draws.outcomes.rename(columns={"player_id": "player_code"}).copy()
    sampled["appearance"] = sampled.minutes.gt(0).astype(float)
    grouped = sampled.groupby(["fixture", "player_code"])
    means = grouped.mean(numeric_only=True).reindex(reference.index)
    result = {
        "draws": float(draws.outcomes.scenario_id.nunique()),
        "player_fixtures": float(len(reference)),
    }
    for sample, analytic in (
        ("minutes", "expected_minutes"),
        ("appearance", "appearance_probability"),
        ("goals", "goals"),
        ("assists", "assists"),
        ("clean_sheet", "clean_sheet_probability"),
        ("defcon", "defcon_probability"),
        ("total_points", "raw_expected_points"),
    ):
        if analytic not in reference:
            continue
        gap = means[sample].to_numpy(float) - reference[analytic].to_numpy(float)
        if not np.isfinite(gap).all():
            raise ValueError("Mean diagnostics require complete finite scenario coverage.")
        result[sample + "_mean_gap"] = float(gap.mean())
        result[sample + "_mean_absolute_gap"] = float(np.abs(gap).mean())
        result[sample + "_maximum_absolute_gap"] = float(np.abs(gap).max())
    return result
