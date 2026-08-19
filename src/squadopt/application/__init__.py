"""Application layer: public operations and read models over the live path.

This package sits between ``squadopt.live`` and the entry points (``scripts``, and later
an HTTP server). It may import everything below it; nothing below it may import it. It
exposes typed commands for deciding, settling, and ticking a season. It also turns the
live path's records - a frozen ledger entry, a tick plan, a run log - into contract-versioned
view models (``ui_view_v1``) and writes them as a static JSON tree a frontend can render.
Entry points adapt these services; they do not import one another or implement engine logic.
"""

from squadopt.application.build import (
    ledger_view,
    pool_view,
    recommendation_view,
    recommendation_view_from_ledger,
    status_view,
)
from squadopt.application.commands import (
    DecideRequest,
    DecideResult,
    DecisionVerificationError,
    SettleRequest,
    SettleResult,
    decide,
    settle,
    verify_decision,
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
from squadopt.application.rivals import (
    TEMPLATE_RIVAL_SOURCE,
    LeagueRivalProvider,
    TemplateRivalProvider,
    iter_rivals,
)
from squadopt.application.season import (
    PerformedTickAction,
    TickObserver,
    TickRequest,
    TickResult,
    TickValue,
    plan_season_tick,
    run_season_tick,
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
    "TEMPLATE_RIVAL_SOURCE",
    "UI_VIEW_CONTRACT_VERSION",
    "UI_VIEW_SCHEMA_PATH",
    "DecideRequest",
    "DecideResult",
    "DecisionVerificationError",
    "LeagueError",
    "LeagueRivalProvider",
    "LeagueView",
    "LeagueWeekView",
    "LedgerRowView",
    "LedgerView",
    "OwnershipView",
    "PerformedTickAction",
    "PlayerView",
    "PoolPlayerView",
    "PoolView",
    "RecommendationView",
    "RiskView",
    "SettleRequest",
    "SettleResult",
    "SiteBuildReport",
    "SiteIndex",
    "StatusView",
    "TemplateRivalProvider",
    "TickObserver",
    "TickRequest",
    "TickResult",
    "TickValue",
    "TransferView",
    "ViewEnvelope",
    "build_site",
    "decide",
    "iter_rivals",
    "league_view",
    "ledger_view",
    "ownership_by_player",
    "ownership_view",
    "plan_season_tick",
    "pool_view",
    "recommendation_view",
    "recommendation_view_from_ledger",
    "run_season_tick",
    "settle",
    "status_view",
    "ui_view_schema",
    "verify_decision",
    "write_ui_view_schema",
]
