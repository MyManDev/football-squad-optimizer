"""One shared hierarchical residual decomposition for scenarios and recalibration."""

import pandas as pd


def decompose_residual_components(frame: pd.DataFrame) -> pd.DataFrame:
    """Return common, team, and idiosyncratic components on validated rows.

    Callers own schema validation because scenario generation and matched recalibration have
    different public input contracts. Sharing this arithmetic prevents their statistical
    definitions from drifting apart.
    """

    decomposed = frame.copy(deep=True)
    decomposed["common_component"] = decomposed.groupby("fold_id", sort=False)[
        "residual"
    ].transform("mean")
    after_common = decomposed["residual"] - decomposed["common_component"]
    decomposed["team_component"] = after_common.groupby(
        [decomposed["fold_id"], decomposed["team_id"]], sort=False
    ).transform("mean")
    decomposed["idiosyncratic_component"] = (
        decomposed["residual"] - decomposed["common_component"] - decomposed["team_component"]
    )
    return decomposed
