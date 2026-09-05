"""Phase C component targets, derived from realized outcomes.

Four questions a single expected-points value cannot separate need four labels. Three of
them are available from the canonical panel; the fourth is not, and this module refuses to
invent it.

**Appearance** is ``minutes > 0``. It is the only unconditional target here, so it is the
only one that is never missing.

**Start** is ``unavailable`` in this version. The pre-registration
(``docs/phase_c_component_model_prereg.md``) admits the source's verified ``starts``
indicator and nothing else -- not ``minutes >= 60``, not lineup membership, not points --
and the archive adapter does not map ``starts`` at all: ``data/sources/vaastav.py`` maps
"only columns present in every supported season", and ``starts`` is one of the advanced
metrics that "appear in some seasons and not others". So the set of seasons with a verified
start label is currently **empty**, which is why :data:`START_TARGET_SUPPORTED_SEASONS` is
an empty tuple rather than a season range. Declaring a source and a population is a
pre-registration act, not something a builder may do on its own.

**Conditional minutes** and **conditional points** are the realized values on rows where
the player appeared, and missing everywhere else. Missing, not zero: a player who did not
appear has no conditional minutes, and a zero there would train the conditional model on a
population it is not conditioned over.

Nothing here reads a feature or fits anything. It turns outcomes into labels.
"""

from typing import Final

import pandas as pd

from squadopt.data.errors import DuplicateRecordsError
from squadopt.data.schema import KEY_COLUMNS, REQUIRED_COLUMNS
from squadopt.features.config import FeatureConfigurationError

TARGET_CONTRACT_VERSION: Final = "phase_c_component_targets_v1"

# The start component's status in this contract version, and the seasons that could
# support it. The tuple is empty on purpose -- see the module docstring.
START_TARGET_STATUS: Final = "unavailable"
START_TARGET_SUPPORTED_SEASONS: Final[tuple[str, ...]] = ()

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
            # The start label the pre-registration would admit does not exist in this
            # panel. Missing rather than zero, and missing even when the column happens
            # to be present, because what is absent is the declared population and not
            # only the column.
            "start_target": pd.Series(pd.NA, index=canonical.index, dtype="Int64"),
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
