"""Explicit human constraints, independent of forecasts and their probability scale."""

import json
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DecisionPreferences:
    """Apply to every week of the selected window; require squad membership only."""

    keep_players: tuple[int, ...] = ()
    avoid_players: tuple[int, ...] = ()
    no_hits: bool = False
    save_chips: bool = False
    include_players: tuple[int, ...] = ()
    hold_transfers: bool = False

    def __post_init__(self) -> None:
        for name in ("keep_players", "avoid_players", "include_players"):
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
        if not isinstance(self.no_hits, bool) or not isinstance(self.save_chips, bool):
            raise ValueError("no_hits and save_chips must be booleans.")
        if not isinstance(self.hold_transfers, bool):
            raise ValueError("hold_transfers must be a boolean.")

    @property
    def active(self) -> bool:
        return bool(
            self.keep_players
            or self.avoid_players
            or self.no_hits
            or self.save_chips
            or self.include_players
            or self.hold_transfers
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
        return payload

    def canonical(self) -> str:
        return json.dumps(self.payload(), sort_keys=True, separators=(",", ":"))

    def validate_selection(self, strategy: str, managers_word: bool, chip: str | None) -> None:
        if self.active and (strategy != "saf-puan" or managers_word):
            raise ValueError("Preferences require pure points with manager news off.")
        if self.save_chips and chip is not None:
            raise ValueError("Saving chips conflicts with a chip selection.")
        if self.hold_transfers and chip in ("wildcard", "freehit", "auto"):
            raise ValueError("Holding transfers conflicts with rebuilding or automatic chips.")

    @classmethod
    def parse(cls, value: object) -> "DecisionPreferences":
        if not isinstance(value, dict) or set(value) - {
            "keep_players",
            "avoid_players",
            "no_hits",
            "save_chips",
            "include_players",
            "hold_transfers",
        }:
            raise ValueError("Invalid decision preferences object.")
        return cls(**value)


NO_PREFERENCES = DecisionPreferences()


def preferences_schema() -> dict[str, object]:
    ids = {
        "type": "array",
        "items": {"type": "integer", "minimum": 1},
        "maxItems": 15,
        "uniqueItems": True,
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "keep_players": ids,
            "avoid_players": ids,
            "no_hits": {"type": "boolean"},
            "save_chips": {"type": "boolean"},
            "include_players": ids,
            "hold_transfers": {"type": "boolean"},
        },
    }
