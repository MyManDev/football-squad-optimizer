"""Application layer: what the live path knows, shaped for a reader.

This package sits between ``squadopt.live`` and the entry points (``scripts``, and later
an HTTP server). It may import everything below it; nothing below it may import it. It
turns the live path's records - a frozen ledger entry, a tick plan, a run log - into
contract-versioned view models (``ui_view_v1``) and writes them as a static JSON tree a
frontend can render. The frontend computes nothing: every number, name and stated limit
a page shows was produced here, from the same records the ledger froze.
"""

from squadopt.application.build import (
    ledger_view,
    pool_view,
    recommendation_view,
    recommendation_view_from_ledger,
    status_view,
)
from squadopt.application.contract import (
    UI_VIEW_CONTRACT_VERSION,
    UI_VIEW_SCHEMA_PATH,
    ui_view_schema,
    write_ui_view_schema,
)
from squadopt.application.league import (
    LeagueError,
    LeagueView,
    LeagueWeekView,
    OwnershipView,
    league_view,
    ownership_by_player,
    ownership_view,
)
from squadopt.application.site import SiteBuildReport, build_site
from squadopt.application.views import (
    LedgerRowView,
    LedgerView,
    PlayerView,
    PoolPlayerView,
    PoolView,
    RecommendationView,
    RiskView,
    SiteIndex,
    StatusView,
    TransferView,
    ViewEnvelope,
)

__all__ = [
    "UI_VIEW_CONTRACT_VERSION",
    "UI_VIEW_SCHEMA_PATH",
    "LeagueError",
    "LeagueView",
    "LeagueWeekView",
    "LedgerRowView",
    "LedgerView",
    "OwnershipView",
    "PlayerView",
    "PoolPlayerView",
    "PoolView",
    "RecommendationView",
    "RiskView",
    "SiteBuildReport",
    "SiteIndex",
    "StatusView",
    "TransferView",
    "ViewEnvelope",
    "build_site",
    "league_view",
    "ledger_view",
    "ownership_by_player",
    "ownership_view",
    "pool_view",
    "recommendation_view",
    "recommendation_view_from_ledger",
    "status_view",
    "ui_view_schema",
    "write_ui_view_schema",
]
