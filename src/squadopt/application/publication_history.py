"""Explicit historical inputs for prospective current-season publication."""

from collections.abc import Sequence

from squadopt.data.errors import DataSourceError

PROSPECTIVE_SEASON = "2026-27"
PROSPECTIVE_ARCHIVE_SEASONS = ("2022-23", "2023-24", "2024-25")


def explicit_archive_seasons(
    selected: Sequence[str], *, current_season: str = PROSPECTIVE_SEASON
) -> tuple[str, ...]:
    """Validate the whole selection before any historical file is opened.

    Current-season evidence comes from the named capture, never an archive directory.
    It must be explicitly permitted because these publication paths use that capture.
    Legacy callers omit the selection and retain their existing policy.
    """
    allowed = {*PROSPECTIVE_ARCHIVE_SEASONS, PROSPECTIVE_SEASON}
    if (
        current_season != PROSPECTIVE_SEASON
        or isinstance(selected, (str, bytes))
        or not isinstance(selected, Sequence)
        or not selected
        or any(not isinstance(season, str) or season not in allowed for season in selected)
        or len(set(selected)) != len(selected)
        or PROSPECTIVE_SEASON not in selected
    ):
        raise DataSourceError(
            "Explicit training seasons must be unique allowed seasons (2022-23, 2023-24, "
            "2024-25, 2026-27), including the current captured season 2026-27."
        )
    archives = tuple(sorted(set(selected) & set(PROSPECTIVE_ARCHIVE_SEASONS)))
    if not archives:
        raise DataSourceError(
            "Explicit training seasons require at least one allowed archive season."
        )
    return archives
