"""Source-specific adapters for real historical data.

Each module here knows exactly one external source: its file layout, its column
names, its encodings, and any correction its data needs. Nothing above this package
learns those details, which is what keeps the canonical layers source-independent.

No third-party data is committed to the repository. Sources are downloaded into
git-ignored directories from a pinned revision, and verified against a committed
manifest of checksums.
"""

from squadopt.data.sources.fpl_live import (
    BOOTSTRAP_PAYLOAD,
    FIXTURES_PAYLOAD,
    FPL_LIVE_SOURCE,
    SEASON_RELATIVE_ELEMENT_FIELDS,
    SNAPSHOT_COLUMNS,
    CaptureSeasonPhase,
    capture_season_phase,
    fixture_snapshot,
    in_season_totals,
    player_snapshot,
    team_codes,
    team_names,
)
from squadopt.data.sources.vaastav import (
    ARCHIVE_COMMIT,
    ARCHIVE_REPOSITORY,
    ARCHIVE_SNAPSHOT_ID,
    FIXTURES_FILE,
    SUPPORTED_SEASONS,
    TEAMS_FILE,
    VAASTAV_ADAPTER,
    attach_player_code,
    build_fixture_panel,
    build_panel,
    load_fixture_snapshot,
    load_season,
    load_team_codes,
    load_upcoming_roster,
    shift_price_to_deadline,
)

__all__ = [
    "ARCHIVE_COMMIT",
    "ARCHIVE_REPOSITORY",
    "ARCHIVE_SNAPSHOT_ID",
    "BOOTSTRAP_PAYLOAD",
    "FIXTURES_FILE",
    "FIXTURES_PAYLOAD",
    "FPL_LIVE_SOURCE",
    "SEASON_RELATIVE_ELEMENT_FIELDS",
    "SNAPSHOT_COLUMNS",
    "SUPPORTED_SEASONS",
    "TEAMS_FILE",
    "VAASTAV_ADAPTER",
    "CaptureSeasonPhase",
    "attach_player_code",
    "build_fixture_panel",
    "build_panel",
    "capture_season_phase",
    "fixture_snapshot",
    "in_season_totals",
    "load_fixture_snapshot",
    "load_season",
    "load_team_codes",
    "load_upcoming_roster",
    "player_snapshot",
    "shift_price_to_deadline",
    "team_codes",
    "team_names",
]
