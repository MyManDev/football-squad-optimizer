"""Write the static JSON tree a frontend renders.

    data/index.json                              SiteIndex
    data/schema/ui_view_v1.schema.json           the contract
    data/<season>/status.json                    StatusView (when a plan is supplied)
    data/<season>/league.json                    LeagueView (when a capture is supplied)
    data/<season>/ledger.json                    LedgerView
    data/<season>/gw<NN>/recommendation.json     RecommendationView
    data/<season>/gw<NN>/pool.json               PoolView (why these players)

Every file is a ``ViewEnvelope``; the tree is deterministic for a given ledger and clock
(sorted keys, fixed indent, LF line ends) and each file lands through a temporary file
and one rename, so a reader never sees a half-written JSON.
"""

import contextlib
import json
import os
import secrets
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from squadopt.application.build import (
    ledger_view,
    pool_view,
    recommendation_view_from_ledger,
    status_view,
)
from squadopt.application.contract import UI_VIEW_CONTRACT_VERSION, ui_view_schema
from squadopt.application.league import league_view, ownership_view
from squadopt.application.views import (
    JsonValue,
    LedgerView,
    SiteIndex,
    StatusView,
    ViewEnvelope,
    utc_now_iso,
)
from squadopt.data.snapshots import CapturedSnapshot
from squadopt.live.ledger import LedgerEntry, load_ledger
from squadopt.live.tick import LedgerState, TickPlan

DATA_DIRECTORY = "data"
SCHEMA_RELATIVE_PATH = f"schema/{UI_VIEW_CONTRACT_VERSION}.schema.json"


@dataclass(frozen=True, slots=True)
class SiteBuildReport:
    out_dir: Path
    season: str
    generated_at_utc: str
    files: tuple[str, ...]
    decided_gameweeks: tuple[int, ...]
    settled_gameweeks: tuple[int, ...]
    status_written: bool
    league_written: bool


def _write_json(path: Path, payload: dict[str, JsonValue]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}-{secrets.token_hex(4)}")
    try:
        temporary.write_bytes(text.encode("utf-8"))
        os.replace(temporary, path)
    finally:
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()


def _envelope(payload: dict[str, JsonValue], generated_at_utc: str) -> dict[str, JsonValue]:
    return ViewEnvelope(payload=payload, generated_at_utc=generated_at_utc).to_dict()


def build_site(
    *,
    ledger_root: Path,
    season: str,
    out_dir: Path,
    plan: TickPlan | None = None,
    runlog_root: Path | None = None,
    snapshot: CapturedSnapshot | None = None,
    now: datetime | None = None,
) -> SiteBuildReport:
    """Render the season's ledger (and, if given, a tick plan) as the site's data tree.

    ``snapshot`` is the capture the league comparison reads (the game's own weekly
    average and each player's ownership); without it ``league.json`` is not written and
    the page says the comparison has not been published.

    ``plan`` is a ``TickPlan`` the caller already made from the captures and ledger
    (``plan_tick``); the site never plans on its own so building a site can never change
    what a tick would do. ``now`` fixes the generation timestamp (replay, tests).
    """

    generated = utc_now_iso(now)
    data_dir = Path(out_dir) / DATA_DIRECTORY
    written: list[str] = []

    def emit(relative: str, payload: dict[str, JsonValue]) -> None:
        _write_json(data_dir / relative, _envelope(payload, generated))
        written.append(relative)

    entries: tuple[LedgerEntry, ...] = load_ledger(Path(ledger_root), season)
    for entry in entries:
        view = recommendation_view_from_ledger(entry)
        emit(f"{season}/gw{entry.gameweek:02d}/recommendation.json", view.to_dict())
        emit(f"{season}/gw{entry.gameweek:02d}/pool.json", pool_view(entry).to_dict())

    ledger: LedgerView = ledger_view(Path(ledger_root), season)
    emit(f"{season}/ledger.json", ledger.to_dict())

    league_written = False
    if snapshot is not None:
        latest_entry = entries[-1] if entries else None
        ownership = None
        if latest_entry is not None:
            latest_view = recommendation_view_from_ledger(latest_entry)
            ownership = ownership_view(
                snapshot,
                gameweek=latest_view.gameweek,
                starters=latest_view.starting_xi,
                bench=latest_view.bench,
                captain_player_id=latest_view.captain_player_id,
            )
        emit(f"{season}/league.json", league_view(snapshot, ledger, ownership=ownership).to_dict())
        league_written = True

    status_written = False
    if plan is not None:
        state = LedgerState(
            decided=frozenset(row.gameweek for row in ledger.rows),
            settled=frozenset(row.gameweek for row in ledger.rows if row.settled),
        )
        status: StatusView = status_view(plan, ledger=state, runlog_root=runlog_root)
        emit(f"{season}/status.json", status.to_dict())
        status_written = True

    schema_path = data_dir / SCHEMA_RELATIVE_PATH
    _write_json(schema_path, ui_view_schema())
    written.append(SCHEMA_RELATIVE_PATH)

    gameweeks = tuple(row.gameweek for row in ledger.rows)
    latest: dict[str, JsonValue] | None = None
    if gameweeks:
        last = max(gameweeks)
        latest = {
            "season": season,
            "gameweek": last,
            "path": f"{season}/gw{last:02d}/recommendation.json",
        }
    index = SiteIndex(
        generated_at_utc=generated,
        seasons=(season,),
        gameweeks={season: gameweeks},
        latest=latest,
        schema_path=SCHEMA_RELATIVE_PATH,
        files=tuple(sorted(written)),
    )
    emit("index.json", index.to_dict())
    return SiteBuildReport(
        out_dir=Path(out_dir),
        season=season,
        generated_at_utc=generated,
        files=tuple(sorted(written)),
        decided_gameweeks=gameweeks,
        settled_gameweeks=tuple(row.gameweek for row in ledger.rows if row.settled),
        status_written=status_written,
        league_written=league_written,
    )
