"""End-to-end construction of the canonical player-gameweek dataset.

One function composes the whole raw-to-canonical path so callers do not have to
remember the stage order, and so the ordering guarantee has a single owner.
"""

import pandas as pd

from squadopt.data.adapters import IDENTITY_ADAPTER, SourceAdapter, apply_adapter
from squadopt.data.cleaning import clean_canonical_dataset
from squadopt.data.errors import InvalidValueError, format_examples
from squadopt.data.schema import CANONICAL_SORT_COLUMNS
from squadopt.data.validation import validate_canonical_dataset


def _apply_declared_season(frame: pd.DataFrame, season: str) -> pd.DataFrame:
    """Attach a caller-declared season label, refusing to relabel other seasons.

    A single-season extract legitimately omits the season, so the caller may
    declare it. Overwriting an existing and different label would silently merge
    two seasons into one rolling-window group, so that is rejected instead.
    """

    if not isinstance(season, str) or not season.strip():
        raise InvalidValueError(f"season must be a non-empty string; got {season!r}.")
    label = season.strip()

    if "season" in frame.columns:
        existing = {str(value).strip() for value in frame["season"].dropna().tolist()}
        conflicting = sorted(existing - {label})
        if conflicting:
            raise InvalidValueError(
                f"Cannot declare season={label!r} for data that already contains "
                f"{format_examples(conflicting)}; relabelling would merge separate seasons."
            )

    return frame.assign(season=label)


def build_canonical_dataset(
    raw_data: pd.DataFrame,
    *,
    adapter: SourceAdapter = IDENTITY_ADAPTER,
    season: str | None = None,
    max_gameweek: int | None = None,
) -> pd.DataFrame:
    """Turn raw player-gameweek records into the canonical dataset.

    Runs adaptation, optional season declaration, cleaning, validation, and
    deterministic ordering. The input frame is never modified, and the same input
    with the same arguments always produces the identical result, including row
    order, regardless of how the source rows were ordered.

    ``season`` declares the season label for a source that does not carry one.
    ``max_gameweek`` optionally bounds the gameweek range, which is
    competition-specific and therefore not hard-coded in the schema.
    """

    if not isinstance(raw_data, pd.DataFrame):
        raise InvalidValueError("build_canonical_dataset expects a pandas DataFrame.")

    adapted = apply_adapter(raw_data, adapter)
    if season is not None:
        adapted = _apply_declared_season(adapted, season)

    cleaned = clean_canonical_dataset(adapted, price_unit=adapter.price_unit)
    validated = validate_canonical_dataset(cleaned, max_gameweek=max_gameweek)

    ordered = validated.sort_values(list(CANONICAL_SORT_COLUMNS), kind="stable")
    return ordered.reset_index(drop=True)
