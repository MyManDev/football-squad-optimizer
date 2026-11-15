"""Explicit human constraints, independent of forecasts and their probability scale."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal

_PLAYER_FIELDS = ("keep_players", "avoid_players", "include_players", "buy_players")
_LEGACY_FIELDS = {*_PLAYER_FIELDS[:3], "no_hits", "save_chips", "hold_transfers", "club_counts"}
_WINDOW_FIELDS = {
    "week_rules",
    "max_hit_points",
    "wildcard_week",
    "hold_opening_transfers",
    "min_opening_bank_tenths",
    "net_points_priority",
}


@dataclass(frozen=True, slots=True)
class ClubCount:
    """An exact number of squad members or incoming transfers from one club."""

    club: str
    count: int
    scope: Literal["squad", "transfers_in"] = "squad"

    def __post_init__(self) -> None:
        if (
            not isinstance(self.club, str)
            or not 1 <= len(self.club) <= 80
            or self.club.strip() != self.club
            or not self.club.isprintable()
        ):
            raise ValueError("A club count requires a canonical club name.")
        if type(self.count) is not int or not 1 <= self.count <= 3:
            raise ValueError("A club count must be an integer from 1 to 3.")
        if self.scope not in ("squad", "transfers_in"):
            raise ValueError("A club count must apply to the squad or incoming transfers.")

    def payload(self) -> dict[str, object]:
        result: dict[str, object] = {"club": self.club, "count": self.count}
        if self.scope != "squad":
            result["scope"] = self.scope
        return result


@dataclass(frozen=True, slots=True)
class WeekRules:
    week: int
    rules: DecisionPreferences

    def __post_init__(self) -> None:
        if type(self.week) is not int or not 1 <= self.week <= 3:
            raise ValueError("A rule week must be an offset from 1 to 3.")
        if not isinstance(self.rules, DecisionPreferences) or not self.rules.active:
            raise ValueError("A rule week requires active preferences.")
        if self.rules.needs_full_window:
            raise ValueError("Weekly rules cannot contain window preferences.")


@dataclass(frozen=True, slots=True)
class DecisionPreferences:
    """Window-wide preferences and optional rules for specific week offsets."""

    keep_players: tuple[int, ...] = ()
    avoid_players: tuple[int, ...] = ()
    no_hits: bool = False
    save_chips: bool = False
    include_players: tuple[int, ...] = ()
    hold_transfers: bool = False
    club_counts: tuple[ClubCount, ...] = ()
    week_rules: tuple[WeekRules, ...] = ()
    max_hit_points: int | None = None
    wildcard_week: int | None = None
    buy_players: tuple[int, ...] = ()
    hold_opening_transfers: bool = False
    min_opening_bank_tenths: int | None = None
    net_points_priority: bool = False

    def __post_init__(self) -> None:
        for name in _PLAYER_FIELDS:
            raw = getattr(self, name)
            if not isinstance(raw, (list, tuple)) or len(raw) > 15:
                raise ValueError(f"{name} must contain at most 15 player ids.")
            if any(isinstance(v, bool) or not isinstance(v, int) or v < 1 for v in raw):
                raise ValueError(f"{name} must contain positive integer player ids.")
            if len(set(raw)) != len(raw):
                raise ValueError(f"{name} contains duplicate player ids.")
            object.__setattr__(self, name, tuple(sorted(raw)))
        if set(self.keep_players) & set(self.avoid_players):
            raise ValueError("A player cannot be both kept and avoided.")
        if set(self.include_players) & set(self.avoid_players):
            raise ValueError("A player cannot be both included and avoided.")
        if set(self.buy_players) & (set(self.avoid_players) | set(self.keep_players)):
            raise ValueError("An incoming player cannot also be avoided or kept.")
        if self.hold_transfers and self.buy_players:
            raise ValueError("Holding transfers conflicts with buying a player.")
        if not isinstance(self.no_hits, bool) or not isinstance(self.save_chips, bool):
            raise ValueError("no_hits and save_chips must be booleans.")
        if not isinstance(self.hold_transfers, bool):
            raise ValueError("hold_transfers must be a boolean.")
        if not isinstance(self.hold_opening_transfers, bool):
            raise ValueError("hold_opening_transfers must be a boolean.")
        if not isinstance(self.net_points_priority, bool):
            raise ValueError("net_points_priority must be a boolean.")
        if self.min_opening_bank_tenths is not None and (
            type(self.min_opening_bank_tenths) is not int
            or not 1 <= self.min_opening_bank_tenths <= 10000
        ):
            raise ValueError("The opening bank minimum must be an integer from 1 to 10000.")
        if (
            not isinstance(self.club_counts, (list, tuple))
            or len(self.club_counts) > 16
            or any(not isinstance(rule, ClubCount) for rule in self.club_counts)
        ):
            raise ValueError("Invalid club counts.")
        counts = {(rule.club, rule.scope): rule.count for rule in self.club_counts}
        if len(counts) != len(self.club_counts):
            raise ValueError("A club count may be set only once per scope.")
        incoming = {
            rule.club: rule.count for rule in self.club_counts if rule.scope == "transfers_in"
        }
        squad = {rule.club: rule.count for rule in self.club_counts if rule.scope == "squad"}
        if any(club in squad and count > squad[club] for club, count in incoming.items()):
            raise ValueError("Incoming club players exceed the club's final squad count.")
        if sum((incoming | squad).values()) > 15:
            raise ValueError("Club counts exceed the squad size.")
        if self.hold_transfers and incoming:
            raise ValueError("Holding transfers conflicts with a club transfer count.")
        object.__setattr__(
            self,
            "club_counts",
            tuple(sorted(self.club_counts, key=lambda rule: (rule.club, rule.scope))),
        )
        if self.max_hit_points is not None and (
            type(self.max_hit_points) is not int or not 0 <= self.max_hit_points <= 60
        ):
            raise ValueError("The total hit limit must be an integer from zero to 60.")
        if self.wildcard_week is not None and (
            type(self.wildcard_week) is not int or self.wildcard_week not in (2, 3)
        ):
            raise ValueError("A future Wildcard must be in week 2 or 3.")
        if (
            not isinstance(self.week_rules, (list, tuple))
            or len(self.week_rules) > 3
            or any(not isinstance(row, WeekRules) for row in self.week_rules)
        ):
            raise ValueError("Invalid week rules.")
        if len({row.week for row in self.week_rules}) != len(self.week_rules):
            raise ValueError("Rules may be grouped only once per week.")
        object.__setattr__(
            self, "week_rules", tuple(sorted(self.week_rules, key=lambda row: row.week))
        )
        for row in self.week_rules:
            self._combined(row.rules)
        if self.hold_opening_transfers:
            opening = self.for_week(1)
            if opening.buy_players or any(
                rule.scope == "transfers_in" for rule in opening.club_counts
            ):
                raise ValueError(
                    "Holding opening transfers conflicts with an opening-week purchase."
                )
        if self.wildcard_week is not None:
            target = self.for_week(self.wildcard_week)
            if target.save_chips or target.hold_transfers:
                raise ValueError("The future Wildcard conflicts with rules for that week.")

    def _combined(self, weekly: DecisionPreferences) -> DecisionPreferences:
        counts = {(rule.club, rule.scope): rule for rule in self.club_counts}
        for rule in weekly.club_counts:
            existing = counts.setdefault((rule.club, rule.scope), rule)
            if existing != rule:
                raise ValueError("Window and weekly club counts conflict.")
        return DecisionPreferences(
            keep_players=tuple(set(self.keep_players) | set(weekly.keep_players)),
            avoid_players=tuple(set(self.avoid_players) | set(weekly.avoid_players)),
            include_players=tuple(set(self.include_players) | set(weekly.include_players)),
            buy_players=weekly.buy_players,
            no_hits=self.no_hits or weekly.no_hits,
            save_chips=self.save_chips or weekly.save_chips,
            hold_transfers=self.hold_transfers or weekly.hold_transfers,
            club_counts=tuple(counts.values()),
        )

    def for_week(self, week: int) -> DecisionPreferences:
        for row in self.week_rules:
            if row.week == week:
                return self._combined(row.rules)
        return self

    def validate_window(self, window: int) -> None:
        if self.scoped and (type(window) is not int or window < 1):
            raise ValueError("The selected planning window is invalid.")
        if (self.wildcard_week is not None and self.wildcard_week > window) or any(
            row.week > window for row in self.week_rules
        ):
            raise ValueError("A rule names a week outside the selected window.")

    @property
    def scoped(self) -> bool:
        return bool(
            self.week_rules
            or self.wildcard_week
            or self.hold_opening_transfers
            or self.min_opening_bank_tenths is not None
        )

    @property
    def uses_game_transfer_limits(self) -> bool:
        return bool(
            self.week_rules
            or self.wildcard_week
            or self.max_hit_points is not None
            or self.net_points_priority
        )

    @property
    def needs_full_window(self) -> bool:
        return self.scoped or self.uses_game_transfer_limits

    @property
    def active(self) -> bool:
        return bool(
            self.keep_players
            or self.avoid_players
            or self.no_hits
            or self.save_chips
            or self.include_players
            or self.hold_transfers
            or self.club_counts
            or self.scoped
            or self.max_hit_points is not None
            or self.buy_players
            or self.net_points_priority
        )

    def payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "keep_players": list(self.keep_players),
            "avoid_players": list(self.avoid_players),
            "no_hits": self.no_hits,
            "save_chips": self.save_chips,
        }
        # Old queued jobs and cached plans retain their canonical preference identity.
        if self.include_players:
            payload["include_players"] = list(self.include_players)
        if self.hold_transfers:
            payload["hold_transfers"] = True
        if self.club_counts:
            payload["club_counts"] = [rule.payload() for rule in self.club_counts]
        if self.buy_players:
            payload["buy_players"] = list(self.buy_players)
        if self.week_rules:
            payload["week_rules"] = [
                {"week": row.week, "rules": row.rules.payload()} for row in self.week_rules
            ]
        if self.max_hit_points is not None:
            payload["max_hit_points"] = self.max_hit_points
        if self.wildcard_week is not None:
            payload["wildcard_week"] = self.wildcard_week
        if self.hold_opening_transfers:
            payload["hold_opening_transfers"] = True
        if self.min_opening_bank_tenths is not None:
            payload["min_opening_bank_tenths"] = self.min_opening_bank_tenths
        if self.net_points_priority:
            payload["net_points_priority"] = True
        return payload

    def canonical(self) -> str:
        return json.dumps(self.payload(), sort_keys=True, separators=(",", ":"))

    def validate_selection(
        self, strategy: str, managers_word: bool, chip: str | None, *, top100_weight: int = 0
    ) -> None:
        if self.active and (strategy != "saf-puan" or managers_word):
            raise ValueError("Preferences require pure points with manager news off.")
        if self.net_points_priority and (top100_weight or chip == "auto"):
            raise ValueError("Net points comparisons cannot use Top100 or automatic chips.")
        if self.save_chips and chip is not None:
            raise ValueError("Saving chips conflicts with a chip selection.")
        if self.hold_transfers and chip in ("wildcard", "freehit", "auto"):
            raise ValueError("Holding transfers conflicts with rebuilding or automatic chips.")
        if self.wildcard_week is not None and chip is not None:
            raise ValueError("A future Wildcard conflicts with another chip selection.")
        if chip is not None and chip != "auto":
            current = self.for_week(1)
            opening_hold = current.hold_transfers or self.hold_opening_transfers
            if current.save_chips or (opening_hold and chip in ("wildcard", "freehit")):
                raise ValueError("The chip conflicts with rules for the first week.")

    @classmethod
    def parse(cls, value: object) -> DecisionPreferences:
        return cls._parse(value, weekly=False)

    @classmethod
    def _parse(cls, value: object, *, weekly: bool) -> DecisionPreferences:
        fields = _LEGACY_FIELDS | ({"buy_players"} if weekly else _WINDOW_FIELDS)
        if not isinstance(value, dict) or value.keys() - fields:
            raise ValueError("Invalid decision preferences object.")
        raw_counts = value.get("club_counts", [])
        if not isinstance(raw_counts, list) or len(raw_counts) > 16:
            raise ValueError("Invalid club counts.")
        counts = []
        for rule in raw_counts:
            if (
                not isinstance(rule, dict)
                or not {"club", "count"} <= rule.keys()
                or rule.keys() - {"club", "count", "scope"}
            ):
                raise ValueError("Invalid club count.")
            counts.append(ClubCount(**rule))
        rows = value.get("week_rules", [])
        if not isinstance(rows, list) or len(rows) > 3:
            raise ValueError("Invalid week rules.")
        week_rules = []
        for row in rows:
            if not isinstance(row, dict) or row.keys() != {"week", "rules"}:
                raise ValueError("Invalid rule week.")
            week_rules.append(WeekRules(row["week"], cls._parse(row["rules"], weekly=True)))
        if any(
            name in value and value[name] is None
            for name in ("max_hit_points", "wildcard_week", "min_opening_bank_tenths")
        ):
            raise ValueError("Invalid window preference.")
        return cls(**(value | {"club_counts": tuple(counts), "week_rules": tuple(week_rules)}))


NO_PREFERENCES = DecisionPreferences()


def preferences_schema() -> dict[str, object]:
    ids = {
        "type": "array",
        "items": {"type": "integer", "minimum": 1},
        "maxItems": 15,
        "uniqueItems": True,
    }
    legacy: dict[str, object] = {
        "keep_players": ids,
        "avoid_players": ids,
        "no_hits": {"type": "boolean"},
        "save_chips": {"type": "boolean"},
        "include_players": ids,
        "hold_transfers": {"type": "boolean"},
        "club_counts": {
            "type": "array",
            "maxItems": 16,
            "uniqueItems": True,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["club", "count"],
                "properties": {
                    "club": {"type": "string", "minLength": 1, "maxLength": 80},
                    "count": {"type": "integer", "minimum": 1, "maximum": 3},
                    "scope": {"enum": ["squad", "transfers_in"]},
                },
            },
        },
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            **legacy,
            "max_hit_points": {"type": "integer", "minimum": 0, "maximum": 60},
            "wildcard_week": {"enum": [2, 3]},
            "hold_opening_transfers": {"type": "boolean"},
            "min_opening_bank_tenths": {"type": "integer", "minimum": 1, "maximum": 10000},
            "net_points_priority": {"type": "boolean"},
            "week_rules": {
                "type": "array",
                "maxItems": 3,
                "uniqueItems": True,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["week", "rules"],
                    "properties": {
                        "week": {"type": "integer", "minimum": 1, "maximum": 3},
                        "rules": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {**legacy, "buy_players": ids},
                        },
                    },
                },
            },
        },
    }
