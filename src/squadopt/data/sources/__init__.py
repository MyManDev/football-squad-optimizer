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
    SNAPSHOT_COLUMNS,
    player_snapshot,
    team_names,
)
from squadopt.data.sources.vaastav import (
    ARCHIVE_COMMIT,
    ARCHIVE_REPOSITORY,
    SUPPORTED_SEASONS,
    VAASTAV_ADAPTER,
    attach_player_code,
    build_panel,
    load_season,
    load_upcoming_roster,
    shift_price_to_deadline,
)

__all__ = [
    "ARCHIVE_COMMIT",
    "ARCHIVE_REPOSITORY",
    "BOOTSTRAP_PAYLOAD",
    "FIXTURES_PAYLOAD",
    "FPL_LIVE_SOURCE",
    "SNAPSHOT_COLUMNS",
    "SUPPORTED_SEASONS",
    "VAASTAV_ADAPTER",
    "attach_player_code",
    "build_panel",
    "load_season",
    "load_upcoming_roster",
    "player_snapshot",
    "shift_price_to_deadline",
    "team_names",
]
