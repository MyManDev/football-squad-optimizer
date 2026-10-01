"""Captured official FPL facts, separate from coach interpretation and model features.

The feed is a view of held bootstrap bytes, never a new network collector. Editorial
text stays private. Source percentages are reported as source statements, not calibrated
forecasts of starts. A content revision excludes observation time so an unchanged fetch
does not create a new information event.
"""

import hashlib
import json
from collections.abc import Iterable
from dataclasses import asdict, dataclass

from squadopt.data.errors import DataError
from squadopt.data.sources.fpl_live import (
    availability_snapshot,
    news_snapshot,
    player_codes,
    player_snapshot,
    team_codes,
    team_names,
)
from squadopt.data.timestamps import as_instant, normalize_utc_timestamp

FPL_NEWS_VERSION = "fpl_information_v1"
FPL_NEWS_URL = "https://fantasy.premierleague.com/"
_CHANGE_FIELDS = ("status", "chance_percent", "news_sha256", "source_added_at", "team_code")


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class FplPlayerInformation:
    player_id: int
    element_id: int
    name: str
    team_code: int
    team_name: str
    status: str
    chance_percent: int | None
    source_added_at: str | None
    news_state: str
    news_sha256: str

    @property
    def fingerprint(self) -> str:
        return _digest(asdict(self))


@dataclass(frozen=True, slots=True)
class FplInformation:
    season: str
    gameweek: int
    snapshot_id: str
    observed_at: str
    players: tuple[FplPlayerInformation, ...]
    declared_team_count: int

    @property
    def revision(self) -> str:
        return _digest(
            {
                "version": FPL_NEWS_VERSION,
                "season": self.season,
                "gameweek": self.gameweek,
                "players": [asdict(row) for row in self.players],
                "declared_team_count": self.declared_team_count,
            }
        )

    def public_record(self, player_ids: Iterable[int] = ()) -> dict[str, object]:
        selected = set(player_ids)
        return {
            "version": FPL_NEWS_VERSION,
            "season": self.season,
            "gameweek": self.gameweek,
            "source_snapshot_id": self.snapshot_id,
            "observed_at": self.observed_at,
            "revision": self.revision,
            "source_url": FPL_NEWS_URL,
            "player_count": len(self.players),
            "team_count": len({row.team_code for row in self.players}),
            "declared_team_count": self.declared_team_count,
            "players": [
                {
                    "player_id": row.player_id,
                    "name": row.name,
                    "team_name": row.team_name,
                    "status": row.status,
                    "source_chance_percent": row.chance_percent,
                    "source_added_at": row.source_added_at,
                    "news_state": row.news_state,
                }
                for row in self.players
                if row.player_id in selected
            ],
        }


def captured_fpl_information(
    bootstrap: bytes, *, season: str, gameweek: int, snapshot_id: str, observed_at: str
) -> FplInformation | None:
    """Read optional editorial facts without widening the projection feature matrix.

    Older minimal captures have no editorial columns and return None. Once all editorial
    columns are declared, malformed identities, timestamps and percentages fail closed.
    """
    raw = json.loads(bootstrap)
    elements = raw.get("elements", [])
    if not elements or any(
        not {"news", "news_added", "id", "code", "team"}.issubset(row) for row in elements
    ):
        return None
    observed = normalize_utc_timestamp(observed_at, label="FPL observation")
    names, clubs = team_names(bootstrap), team_codes(bootstrap)
    identifiers = {code: element for element, code in player_codes(bootstrap).items()}
    roster = player_snapshot(bootstrap).set_index("player_id")
    availability = availability_snapshot(bootstrap).set_index("player_id")
    news = news_snapshot(bootstrap).set_index("player_id")
    element_by_code = {int(row["code"]): row for row in elements}
    result: list[FplPlayerInformation] = []
    for code in sorted(int(item) for item in roster.index):
        row = element_by_code[code]
        club = row["team"]
        if club not in names or club not in clubs:
            raise DataError("Official information names an unknown team.")
        percentage = availability.at[code, "chance_of_playing"]
        chance = None if percentage is None or str(percentage) == "<NA>" else int(str(percentage))
        if chance is not None and not 0 <= chance <= 100:
            raise DataError("Official playing percentage must be between zero and 100.")
        added = news.at[code, "news_added_utc"]
        source_at = None if added is None or str(added) == "<NA>" else str(added)
        if source_at is not None and as_instant(source_at) > as_instant(observed):
            raise DataError("Official news timestamp is after the observation.")
        text = str(news.at[code, "news"])
        state = "present" if text else ("cleared" if source_at else "not_reported")
        result.append(
            FplPlayerInformation(
                player_id=code,
                element_id=identifiers[code],
                name=str(roster.at[code, "name"]),
                team_code=clubs[club],
                team_name=names[club],
                status=str(availability.at[code, "status"]),
                chance_percent=chance,
                source_added_at=source_at,
                news_state=state,
                news_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
            )
        )
    return FplInformation(season, gameweek, snapshot_id, observed, tuple(result), len(names))


def information_changes(before: FplInformation, after: FplInformation) -> dict[str, object]:
    """Compare same-season facts; a changed percentage needs no changed news date."""
    if before.season != after.season:
        raise DataError("Official information comparison requires one season.")
    if as_instant(before.observed_at) >= as_instant(after.observed_at):
        raise DataError("Information comparison needs a later observation.")
    old = {row.player_id: row for row in before.players}
    new = {row.player_id: row for row in after.players}
    changes: list[dict[str, object]] = []
    for code in sorted(old.keys() | new.keys()):
        if code not in old:
            fields = ["added"]
        elif code not in new:
            fields = ["removed"]
        else:
            fields = [
                field
                for field in _CHANGE_FIELDS
                if getattr(old[code], field) != getattr(new[code], field)
            ]
        if fields:
            changes.append({"player_id": code, "fields": fields})
    return {
        "season": after.season,
        "previous_snapshot_id": before.snapshot_id,
        "source_snapshot_id": after.snapshot_id,
        "previous_revision": before.revision,
        "revision": after.revision,
        "target_week_changed": before.gameweek != after.gameweek,
        "changed_player_count": len(changes),
        "changes": changes,
        "decision_effect": "not_recomputed",
    }
