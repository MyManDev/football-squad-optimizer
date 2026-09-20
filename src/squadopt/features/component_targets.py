"""Phase C component targets, derived from realized outcomes.

Four questions a single expected-points value cannot separate need four labels. Three of
them are available from the canonical panel; the fourth is not, and this module refuses to
invent it.

**Appearance** is ``minutes > 0``. It is the only unconditional target here, so it is the
only one that is never missing.

**Start** is the source's verified ``starts`` indicator, over a declared population and
nowhere else. ``docs/phase_c_component_model_prereg.md`` admits that column and nothing
else -- not ``minutes >= 60``, not lineup membership, not points -- and
``docs/participation_model_prereg.md`` declares the population, because declaring a source
and a population is a pre-registration act, not something a builder may do on its own.

The population is two seasons, and it is narrower than the set of seasons whose files carry
the column. Those are different claims: ``src/squadopt/data/sources/vaastav.py`` says which
seasons the archive carries ``starts`` for *completely*, while
:data:`START_TARGET_SUPPORTED_SEASONS` says which of them this contract may label. 2025-26 is
carried and not labelled, because it is the locked holdout. A row outside the declared
population gets ``pd.NA`` even when its season's column is right there -- missing, not zero,
because what is absent is the declaration and not the data.

**Conditional minutes** and **conditional points** are the realized values on rows where
the player appeared, and missing everywhere else. Missing, not zero: a player who did not
appear has no conditional minutes, and a zero there would train the conditional model on a
population it is not conditioned over.

Nothing here reads a feature or fits anything. It turns outcomes into labels.
"""

from typing import Any, Final

import pandas as pd

from squadopt.data.errors import DuplicateRecordsError
from squadopt.data.schema import KEY_COLUMNS, REQUIRED_COLUMNS
from squadopt.features.config import FeatureConfigurationError

TARGET_CONTRACT_VERSION: Final = "phase_c_component_targets_v1"

# The start component's status in this contract version, and the seasons it is declared
# over. Declared here rather than imported from the archive adapter on purpose: the adapter
# states what the archive carries, this states what the pre-registration admits, and a test
# pins that the second never exceeds the first. Two names for one tuple would hide the day
# they need to differ.
START_TARGET_STATUS: Final = "available"
START_TARGET_SUPPORTED_SEASONS: Final[tuple[str, ...]] = ("2023-24", "2024-25")

# The source column a verified start label would have to come from. Named so the refusal
# below is about a specific absent column rather than about the idea of a start.
START_SOURCE_COLUMN: Final = "starts"

COMPONENT_TARGET_COLUMNS: Final = (
    *KEY_COLUMNS,
    "appearance_target",
    "start_target",
    "minutes_target",
    "points_target",
)

_TARGET_DTYPES: Final = {
    "season": "string",
    "gameweek": "int64",
    "player_id": "int64",
    "appearance_target": "Int64",
    "start_target": "Int64",
    "minutes_target": "Int64",
    "points_target": "Int64",
}


def _start_target(canonical: pd.DataFrame) -> "pd.Series[Any]":
    """The verified start label where it is declared, and ``pd.NA`` everywhere else.

    Three things have to be true at once for a row to carry a label, and each failure is a
    different fact rather than a shade of the same one:

    - the row's season is in the declared population;
    - the panel carries :data:`START_SOURCE_COLUMN` at all, which it does not for seasons
      the archive adapter does not list;
    - the value is present for that row.

    A double gameweek can start twice, so the label is ``starts > 0`` rather than the count
    -- the same reading the pre-registration fixes with "start means starting at least one
    fixture". The count itself is not discarded; it stays in the panel for anyone who
    declares a use for it.
    """

    labelled = pd.Series(pd.NA, index=canonical.index, dtype="Int64")
    if START_SOURCE_COLUMN not in canonical.columns:
        return labelled
    starts = pd.to_numeric(canonical[START_SOURCE_COLUMN], errors="coerce")
    declared = canonical["season"].astype("string").isin(START_TARGET_SUPPORTED_SEASONS)
    admissible = declared & starts.notna()
    labelled[admissible] = (starts[admissible] > 0).astype("Int64")
    return labelled


def build_component_targets(canonical: pd.DataFrame) -> pd.DataFrame:
    """Derive the Phase C component targets from a canonical player-gameweek panel.

    One row per ``(season, gameweek, player_id)``, which is the grain the panel already
    guarantees. A double gameweek is one row carrying the gameweek's total minutes and
    total points, so summing across fixtures is the panel's job and not repeated here.

    The input is never modified, and the result does not depend on the input's row order
    or index.
    """

    if not isinstance(canonical, pd.DataFrame):
        raise FeatureConfigurationError("build_component_targets expects a pandas DataFrame.")
    missing = [column for column in REQUIRED_COLUMNS if column not in canonical.columns]
    if missing:
        raise FeatureConfigurationError(
            f"Canonical dataset is missing required columns: {missing!r}."
        )
    duplicated = canonical.columns[canonical.columns.duplicated()].tolist()
    if duplicated:
        raise FeatureConfigurationError(f"Duplicate columns are not allowed: {duplicated!r}.")
    keys = canonical.loc[:, list(KEY_COLUMNS)]
    if bool(keys.duplicated().any()):
        raise DuplicateRecordsError(
            "A player may appear once per season and gameweek; the panel repeats a key, so "
            "a gameweek total cannot be read off a single row."
        )

    minutes = pd.to_numeric(canonical["minutes"], errors="raise")
    points = pd.to_numeric(canonical["total_points"], errors="raise")
    appeared = minutes > 0

    targets = pd.DataFrame(
        {
            "season": canonical["season"],
            "gameweek": canonical["gameweek"],
            "player_id": canonical["player_id"],
            "appearance_target": appeared.astype("int64"),
            "start_target": _start_target(canonical),
            "minutes_target": minutes.where(appeared),
            "points_target": points.where(appeared),
        }
    )
    targets = targets.astype(_TARGET_DTYPES)
    return (
        targets.sort_values(list(KEY_COLUMNS), kind="stable")
        .reset_index(drop=True)
        .loc[:, list(COMPONENT_TARGET_COLUMNS)]
    )
