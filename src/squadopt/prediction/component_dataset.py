"""The leakage-safe modelling frame the Phase C control components are fitted on.

Two things decide whether a component model is honest, and both live here rather than in
the estimator: **which columns may be features**, and **which rows may be training data**.

**Columns are an allowlist, not a blocklist.** The feature set is exactly what
:func:`squadopt.features.config.feature_column_names` produces for
:data:`COMPONENT_FEATURE_CONFIG` -- every one of which is a rolling aggregate that
``features.rolling`` has already shifted by one gameweek -- plus a short list of columns
the schema classifies as pre-match. A blocklist would have to be extended every time the
panel grew a column, and the one time it was forgotten the leak would be silent. An
allowlist fails the other way: a new column is unused until someone classifies it.

**Rows are ordered by a season order that is handed in, not derived.** Ranking seasons is
``backtest.splits.season_ranks``' job, and ``backtest`` sits far above this layer, so it
cannot be imported here. Rather than reimplement the ranking -- which is how one question
gets two answers -- this module requires the caller to pass the order it already computed
and simply applies it.

The join to the Phase B evidence table is deliberately absent. The control arm must
reproduce without any optional evidence, and the evidence families enter one at a time
under their own measurements. Only the join *boundary* is checked, by a test.
"""

from collections.abc import Sequence
from typing import Final

import pandas as pd

from squadopt.data.schema import (
    AMBIGUOUS_TIMING_COLUMNS,
    DERIVED_OUTCOME_COLUMNS,
    KEY_COLUMNS,
    OUTCOME_COLUMNS,
)
from squadopt.features.builder import build_feature_dataset
from squadopt.features.component_targets import COMPONENT_TARGET_COLUMNS, build_component_targets
from squadopt.features.config import (
    APPEARANCE_SOURCE_COLUMN,
    FeatureConfig,
    feature_column_names,
    rolling_feature_name,
)
from squadopt.features.fixtures import attach_fixture_features
from squadopt.prediction.config import PredictionConfigurationError

DATASET_CONTRACT_VERSION: Final = "phase_c_component_dataset_v1"
COMPONENT_TRAINING_SEASONS: Final = (
    "2021-22",
    "2022-23",
    "2023-24",
    "2024-25",
)

# Declared locally on purpose. The frozen mapping's own version string lives in
# ``backtest.policy_evaluation``, which sits above this layer, so importing it would
# invert the dependency the layer contract enforces. This name identifies *this* feature
# set, which is the default windows plus the appearance decomposition the component split
# needs, and it moves only when that set moves.
FEATURE_CONTRACT_VERSION: Final = "phase_c_component_form_window_v1"

# The appearance decomposition is the reason for a non-default config: `appearance_rate`
# answers how often a player features and `minutes_per_appearance` how long when he does,
# and a minutes average cannot separate the two. Both halves come from the same shifted
# primitive as everything else.
COMPONENT_FEATURE_CONFIG: Final = FeatureConfig(appearance_windows=(3, 5))
COMPONENT_HISTORY_WINDOW: Final = max(
    *COMPONENT_FEATURE_CONFIG.minutes_windows,
    *COMPONENT_FEATURE_CONFIG.points_windows,
    *COMPONENT_FEATURE_CONFIG.appearance_windows,
)

# Pre-match columns used directly. `price_tenths` is in `PRE_MATCH_COLUMNS`; the two
# fixture counts are `features.fixtures.CALENDAR_ONLY_COLUMNS`, which is the subset whose
# pre-match claim does not depend on a capture instant the archive never published.
#
# `position` is deliberately not here. Its category vocabulary lives in
# `optimization.config`, which is above this layer, and declaring a second copy of it for
# one one-hot encoder is a liability out of proportion to the gain: `points_per_90_last_5`
# already carries a player's positional scoring level empirically. Recorded as a deferral
# rather than an oversight.
PRE_MATCH_FEATURE_COLUMNS: Final = ("price_tenths", "fixture_count", "home_fixture_count")

# The calendar column the minutes bound is taken against.
FIXTURE_COUNT_COLUMN: Final = "fixture_count"

_FORBIDDEN_FEATURE_COLUMNS: Final = frozenset(
    (*OUTCOME_COLUMNS, *DERIVED_OUTCOME_COLUMNS, *AMBIGUOUS_TIMING_COLUMNS)
)


def component_feature_columns(config: FeatureConfig | None = None) -> tuple[str, ...]:
    """Return the feature columns a component model may read, in a fixed order.

    The order is fixed because a design matrix built in a different column order is a
    different model, and nothing downstream would report the difference.

    **The per-appearance ratios are deliberately absent**, and the reason is a measurement
    rather than a preference. ``points_per_90_last_5`` and
    ``minutes_per_appearance_last_{3,5}`` divide by a window's appearances, so they are
    *undefined* -- not unobserved -- for a player who logged no minutes in that window.
    On 2024-25 that is 45 to 49 per cent of rows, against 2.9 per cent for the genuine
    no-history case. Requiring them would drop half the population, and precisely the half
    the appearance model should be most confident about. Imputing them would put a number
    where the quantity does not exist.

    What is lost is real and recorded: a linear model cannot form a ratio, so the scoring
    *rate* is only implicit in the mean minutes and mean points it is given. That is a
    known limitation of this control, not a claim that the rate does not matter.
    """

    settings = COMPONENT_FEATURE_CONFIG if config is None else config
    if not isinstance(settings, FeatureConfig):
        raise PredictionConfigurationError("config must be a FeatureConfig.")
    # Built from the same naming helpers the feature layer uses, so a name cannot drift
    # from the column the builder writes; a test asserts every one of these is a name the
    # configuration actually produces.
    names = [rolling_feature_name("minutes", window) for window in settings.minutes_windows]
    names.extend(rolling_feature_name("total_points", window) for window in settings.points_windows)
    names.extend(
        rolling_feature_name(APPEARANCE_SOURCE_COLUMN, window)
        for window in settings.appearance_windows
    )
    columns = (*names, *PRE_MATCH_FEATURE_COLUMNS)
    leaking = sorted(set(columns) & _FORBIDDEN_FEATURE_COLUMNS)
    if leaking:
        raise PredictionConfigurationError(
            f"Feature columns {leaking!r} carry outcome or unproven timing. A gameweek's "
            "own outcome may score a decision, never inform it."
        )
    return columns


def excluded_ratio_features(config: FeatureConfig | None = None) -> tuple[str, ...]:
    """The configuration's feature names this contract deliberately does not read.

    Derived as a difference rather than written out, so it cannot fall out of step with
    what :func:`component_feature_columns` returns. Recorded in the export manifest: a
    reader should be able to see what was left on the table without reading this module.
    """

    settings = COMPONENT_FEATURE_CONFIG if config is None else config
    used = set(component_feature_columns(settings))
    return tuple(name for name in feature_column_names(settings) if name not in used)


def build_component_modelling_frame(
    panel: pd.DataFrame,
    fixtures: pd.DataFrame,
    team_codes: pd.DataFrame,
    *,
    seasons: Sequence[str],
    config: FeatureConfig | None = None,
) -> pd.DataFrame:
    """Build the source-neutral training frame used by the Phase C estimators."""

    settings = COMPONENT_FEATURE_CONFIG if config is None else config
    ordered_seasons = tuple(str(season) for season in seasons)
    if not ordered_seasons:
        raise PredictionConfigurationError("seasons must name at least one training season.")
    features = build_feature_dataset(panel, config=settings)
    attached = [
        attach_fixture_features(
            features.loc[features["season"].astype("string") == season],
            fixtures.loc[fixtures["season"].astype("string") == season],
            team_codes.loc[team_codes["season"].astype("string") == season],
            unproven_difficulty="omit",
        )
        for season in ordered_seasons
    ]
    targets = build_component_targets(panel)
    return build_component_frame(pd.concat(attached, ignore_index=True), targets, config=settings)


def build_component_scoring_frame(
    panel: pd.DataFrame,
    fixtures: pd.DataFrame,
    team_codes: pd.DataFrame,
    *,
    season: str,
    gameweek: int,
    config: FeatureConfig | None = None,
) -> pd.DataFrame:
    """Build one deadline's component features from prior outcomes and its calendar."""

    settings = COMPONENT_FEATURE_CONFIG if config is None else config
    features = build_feature_dataset(panel, config=settings)
    scoring = rows_at(features, season=season, gameweek=gameweek)
    if scoring.empty:
        raise PredictionConfigurationError(
            f"No scoring rows exist for {season} gameweek {gameweek}."
        )
    return attach_fixture_features(
        scoring,
        fixtures,
        team_codes,
        unproven_difficulty="omit",
    )


def _season_rank(season_order: Sequence[str]) -> dict[str, int]:
    order = [str(season).strip() for season in season_order]
    if not order:
        raise PredictionConfigurationError("season_order must name at least one season.")
    if len(set(order)) != len(order):
        raise PredictionConfigurationError(f"season_order repeats a season: {order!r}.")
    return {season: rank for rank, season in enumerate(order)}


def build_component_frame(
    features: pd.DataFrame,
    targets: pd.DataFrame,
    *,
    config: FeatureConfig | None = None,
) -> pd.DataFrame:
    """Join features to targets on the canonical key, keeping only allowed columns.

    An inner join: a feature row with no target is not a modelling row, and a target row
    with no features cannot be predicted from. Both counts are recoverable by the caller
    from the input lengths, so nothing is dropped silently at a level that matters.

    Neither input is modified.
    """

    if not isinstance(features, pd.DataFrame) or not isinstance(targets, pd.DataFrame):
        raise PredictionConfigurationError("build_component_frame expects pandas DataFrames.")
    columns = component_feature_columns(config)
    missing = [column for column in (*KEY_COLUMNS, *columns) if column not in features.columns]
    if missing:
        raise PredictionConfigurationError(f"Feature frame is missing columns: {missing!r}.")
    missing_targets = [
        column for column in COMPONENT_TARGET_COLUMNS if column not in targets.columns
    ]
    if missing_targets:
        raise PredictionConfigurationError(f"Target frame is missing columns: {missing_targets!r}.")

    left = features.loc[:, [*KEY_COLUMNS, *columns]].copy(deep=True)
    right = targets.loc[:, list(COMPONENT_TARGET_COLUMNS)].copy(deep=True)
    for frame in (left, right):
        frame["season"] = frame["season"].astype("string")
        frame["gameweek"] = pd.to_numeric(frame["gameweek"], errors="raise").astype("int64")
        frame["player_id"] = pd.to_numeric(frame["player_id"], errors="raise").astype("int64")

    joined = left.merge(right, on=list(KEY_COLUMNS), how="inner", validate="one_to_one")
    return joined.sort_values(list(KEY_COLUMNS), kind="stable").reset_index(drop=True)


def rows_strictly_before(
    frame: pd.DataFrame,
    *,
    season_order: Sequence[str],
    season: str,
    gameweek: int,
) -> pd.DataFrame:
    """Return the rows that precede one decision, in the order the caller declared.

    Strictly before: the decision's own gameweek is excluded in every season, which is
    what keeps a fold's outcome out of the model that predicts it. A season the order does
    not name is refused rather than sorted to the end, because an unranked season silently
    placed last is a leak with a plausible-looking cause.
    """

    if not isinstance(frame, pd.DataFrame):
        raise PredictionConfigurationError("rows_strictly_before expects a pandas DataFrame.")
    ranks = _season_rank(season_order)
    target_season = str(season).strip()
    if target_season not in ranks:
        raise PredictionConfigurationError(
            f"season {target_season!r} is not in season_order {list(ranks)!r}."
        )
    week = int(gameweek)
    seasons = frame["season"].astype("string")
    unknown = sorted(set(seasons.dropna().tolist()) - set(ranks))
    if unknown:
        raise PredictionConfigurationError(
            f"The frame carries seasons absent from season_order: {unknown!r}."
        )
    rank = seasons.map(ranks).astype("int64")
    weeks = pd.to_numeric(frame["gameweek"], errors="raise").astype("int64")
    boundary = ranks[target_season]
    earlier = (rank < boundary) | ((rank == boundary) & (weeks < week))
    return frame.loc[earlier].copy(deep=True).reset_index(drop=True)


def rows_at(
    frame: pd.DataFrame,
    *,
    season: str,
    gameweek: int,
) -> pd.DataFrame:
    """Return the rows of one decision -- the population an out-of-fold row scores."""

    if not isinstance(frame, pd.DataFrame):
        raise PredictionConfigurationError("rows_at expects a pandas DataFrame.")
    selected = (frame["season"].astype("string") == str(season).strip()) & (
        pd.to_numeric(frame["gameweek"], errors="raise").astype("int64") == int(gameweek)
    )
    return frame.loc[selected].copy(deep=True).reset_index(drop=True)
