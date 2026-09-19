"""The chip forecast: the weekly chip rule applied to one member, as a pure function.

``docs/chip_forecast_prereg.md`` fixes the rule and this module states it on typed
inputs. It reads no file, no capture and no network, and it solves nothing: what a chip
adds this gameweek is an input (the product already computes it, ``advice_chips``), and
so are the member's present squad with this gameweek's expected points and the fixture
count of every club in every gameweek the forecast looks at.

Two decisions are injected, because a pre-registered measurement makes them and this
module may not: the threshold policy (``fixed`` or ``decaying``) and whether the
reservation applies (``reserve``). Nothing here prefers one: what was measured is
named in ``MEASURED_THRESHOLD_POLICY`` and ``MEASURED_RESERVATION`` for the caller to
pass, so that a later change of rule is a change of one constant and not of this
module's arithmetic.

The rule, for a chip ``c`` held in a window from ``s`` to ``L`` and a decision gameweek
``t``:

- ``threshold(c, w)`` is the holding value ``H(c)`` under ``fixed`` and
  ``H(c) * (L - w) / (L - s)`` under ``decaying``, zero for a window of one gameweek.
- Under the reservation the bench boost is considered only in a gameweek where some
  club plays twice, and the free hit only where some club is blank or plays twice. In
  the window's last gameweek the reservation is lifted, under either threshold policy,
  because a reserved chip that is not played then is lost.
- **Play now** when the reservation allows it and ``gain(c, t) > threshold(c, t)``,
  strictly. Otherwise **hold**.
- A chip whose gain this gameweek was not computed is **unknown this gameweek** where
  the reservation allows it. ``None`` is never read as zero. Where the reservation does
  not allow the chip this gameweek the rule holds it whatever it would add, so the
  verdict is hold, the reason says so, and the gain stays ``None``.

What a hold points at:

- Triple captain and bench boost: the first later gameweek ``w <= L`` the reservation
  allows where an estimate exceeds ``threshold(c, w)``. The estimate is the best scaled
  expected points in the present fifteen for the triple captain (the armband can go to
  anyone held, so the present captain is not read), and the sum of the present bench's
  scaled expected points for the bench boost. Scaled expected points in ``w`` are this
  gameweek's expected points times the club's fixture count in ``w`` over its count in
  ``t``, floored at zero: the arithmetic ``live/horizon.py`` applies to later weeks.
- A player whose club has no fixture in ``t`` has nothing to scale. His scaled value is
  ``None``, he is left out of every later estimate, and the document lists him
  (``players_without_fixture_this_week``) and says so in ``limits``. ``live/horizon.py``
  keeps such a player at zero through the window; leaving him out gives the same sums
  and the same best, and states that the number is absent rather than nought.
- Free hit: the structured gameweeks after ``t`` up to and including ``L``, in order,
  with how many clubs double and how many are blank. No gain is named for them.
- Wildcard: no gameweek. The threshold and this gameweek's gain only.

The document carries codes, gameweeks and expected points, and ``limits`` in English in
the manner of ``WINDOW_STATED_LIMITS``. Member-facing wording in both languages is the
page's work. No field and no sentence expresses how sure anything is.

This module is wired into nothing: no publication, no route, no page.
"""

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

from squadopt.live.rules import CHIP_NAMES

CHIP_FORECAST_CONTRACT_VERSION: Final = "chip_forecast_v1"
CHIP_FORECAST_SCHEMA_PATH: Final = Path("docs") / "contracts" / "chip_forecast_v1.schema.json"

THRESHOLD_FIXED: Final = "fixed"
THRESHOLD_DECAYING: Final = "decaying"
THRESHOLD_POLICIES: Final = (THRESHOLD_FIXED, THRESHOLD_DECAYING)

#: What `chip_forecast_rule` chose, so that one place says it and every caller reads it
#: from here. The function itself prefers neither policy and takes both as inputs.
#: `decaying - fixed` was -0.44 points a gameweek with an interval of [-1.35, +0.99]
#: over four development seasons, so the two were not separated and the protocol's own
#: rule kept the decaying threshold for the structural reason: it cannot let a chip
#: expire, where the fixed threshold let ten of thirty-two windows expire unplayed.
MEASURED_THRESHOLD_POLICY: Final = THRESHOLD_DECAYING
#: The same record's amended comparison, `decaying - threshold_only`, was -0.15 points a
#: gameweek, a negative pooled difference, and the amendment said the reservation is kept
#: only on a positive one. So the forecast offers every chip in every gameweek of its
#: window and lets the threshold do the holding.
MEASURED_RESERVATION: Final = False

VERDICT_PLAY_NOW: Final = "play_now"
VERDICT_HOLD: Final = "hold"
VERDICT_UNKNOWN_THIS_WEEK: Final = "unknown_this_week"
VERDICT_WINDOW_NOT_OPEN: Final = "window_not_open"
VERDICT_EXPIRED_WINDOW: Final = "expired_window"
VERDICTS: Final = (
    VERDICT_PLAY_NOW,
    VERDICT_HOLD,
    VERDICT_UNKNOWN_THIS_WEEK,
    VERDICT_WINDOW_NOT_OPEN,
    VERDICT_EXPIRED_WINDOW,
)

#: Why the rule holds a chip: what it adds does not exceed the threshold, or the
#: reservation keeps it for another kind of gameweek whatever it would add.
HOLD_BELOW_THRESHOLD: Final = "gain_not_above_threshold"
HOLD_RESERVED: Final = "reserved_for_structured_gameweek"
HOLD_REASONS: Final = (HOLD_BELOW_THRESHOLD, HOLD_RESERVED)

BENCH_BOOST: Final = "bboost"
TRIPLE_CAPTAIN: Final = "3xc"
FREE_HIT: Final = "freehit"
WILDCARD: Final = "wildcard"

#: How every later-gameweek number in the document was made, named so a consumer can
#: tell it from a projection of that gameweek.
LATER_WEEK_BASIS: Final = "this_week_projection_scaled_by_relative_fixture_count_v1"

#: The holding values of the committed chain records, the constants both threshold arms
#: of ``docs/chip_forecast_prereg.md`` use. They are an input of the forecast, not a
#: default of it: a caller passes them, or others, by name.
PROTOCOL_HOLDING_VALUES: Final[Mapping[str, float]] = MappingProxyType(
    {BENCH_BOOST: 20.0, TRIPLE_CAPTAIN: 18.0, WILDCARD: 12.0, FREE_HIT: 15.0}
)

POSITIONS: Final = ("GK", "DEF", "MID", "FWD")
SQUAD_SIZE: Final = 15
BENCH_SIZE: Final = 4

LIMIT_LATER_WEEKS: Final = (
    "Later gameweeks repeat this gameweek's projection over the fixture calendar, "
    "rescaled by each club's fixture count in that gameweek relative to its count in "
    "this one; they are not a forecast of those gameweeks."
)
LIMIT_PRESENT_SQUAD: Final = (
    "The member's present fifteen and present bench are assumed to be held unchanged in "
    "every later gameweek; transfers, injuries and rotation before then are not seen."
)
LIMIT_RULE_SOURCE: Final = (
    "The rule's worth was measured on the system's own squad over past seasons with one "
    "set of chips; this season has two, and no gain is claimed for the member."
)
LIMIT_RECOMPUTED: Final = (
    "A named gameweek is a reading of the calendar under the rule as it stands at this "
    "capture and is recomputed at every publish; the planner never plays a chip for a "
    "member."
)
LIMIT_WHOLE_SQUAD_CHIPS: Final = (
    "No later gain is estimated for a Free Hit or a Wildcard: each would need a "
    "whole-squad solve for every gameweek, and none is spent here."
)
LIMIT_NO_FIXTURE_THIS_WEEK: Final = (
    "A player whose club has no fixture this gameweek has no projection to rescale, so "
    "he is left out of every later gameweek's estimate; that understates a squad that "
    "holds him."
)

__all__ = [
    "CHIP_FORECAST_CONTRACT_VERSION",
    "CHIP_FORECAST_SCHEMA_PATH",
    "HOLD_REASONS",
    "LATER_WEEK_BASIS",
    "PROTOCOL_HOLDING_VALUES",
    "THRESHOLD_POLICIES",
    "VERDICTS",
    "ChipForecastError",
    "ChipForecastInputs",
    "GameweekFixtures",
    "HeldChip",
    "SquadRow",
    "chip_forecast",
    "chip_forecast_schema",
    "holding_threshold",
    "scaled_expected_points",
    "write_chip_forecast_schema",
]


class ChipForecastError(ValueError):
    """Inputs the forecast cannot state the rule on."""


def _gameweek(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ChipForecastError(f"{label} must be a positive integer, got {value!r}.")
    return value


def _finite(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ChipForecastError(f"{label} must be a number, got {value!r}.")
    number = float(value)
    if not math.isfinite(number):
        raise ChipForecastError(f"{label} must be finite, got {value!r}.")
    return number


@dataclass(frozen=True, slots=True)
class HeldChip:
    """One chip the member still holds in the current half, and what it adds now.

    ``gain_this_week`` is the chip week's expected points over the member's own plan
    without the chip, as the product computed it, or ``None`` when it did not. ``None``
    is carried through as unknown; it is never read as zero.
    """

    name: str
    first_gameweek: int
    last_gameweek: int
    gain_this_week: float | None

    def __post_init__(self) -> None:
        if self.name not in CHIP_NAMES:
            raise ChipForecastError(f"Unknown chip {self.name!r}; the game has {CHIP_NAMES!r}.")
        _gameweek(self.first_gameweek, f"{self.name} first_gameweek")
        _gameweek(self.last_gameweek, f"{self.name} last_gameweek")
        if self.last_gameweek < self.first_gameweek:
            raise ChipForecastError(f"The {self.name!r} window ends before it starts.")
        if self.gain_this_week is not None:
            object.__setattr__(
                self, "gain_this_week", _finite(self.gain_this_week, f"{self.name} gain_this_week")
            )


@dataclass(frozen=True, slots=True)
class SquadRow:
    """One of the member's present fifteen, with this gameweek's expected points.

    ``bench_order`` is ``None`` for a player in the present eleven and 1 to 4 for the
    bench, in the order the member set it.
    """

    player_id: int
    club_id: int
    position: str
    expected_points: float
    bench_order: int | None = None
    is_captain: bool = False

    def __post_init__(self) -> None:
        _gameweek(self.player_id, "player_id")
        _gameweek(self.club_id, "club_id")
        if self.position not in POSITIONS:
            raise ChipForecastError(f"Player {self.player_id} has position {self.position!r}.")
        object.__setattr__(
            self,
            "expected_points",
            _finite(self.expected_points, f"Player {self.player_id} expected_points"),
        )
        if self.bench_order is not None and (
            isinstance(self.bench_order, bool)
            or not isinstance(self.bench_order, int)
            or not 1 <= self.bench_order <= BENCH_SIZE
        ):
            raise ChipForecastError(
                f"Player {self.player_id} has bench order {self.bench_order!r}; "
                f"the bench is 1 to {BENCH_SIZE}."
            )
        if not isinstance(self.is_captain, bool):
            raise ChipForecastError(f"Player {self.player_id} needs a boolean captain flag.")


@dataclass(frozen=True, slots=True)
class GameweekFixtures:
    """How many fixtures each club has in one gameweek. A blank is a stated zero."""

    gameweek: int
    fixture_count_by_club: Mapping[int, int]

    def __post_init__(self) -> None:
        _gameweek(self.gameweek, "gameweek")
        counts: dict[int, int] = {}
        for club, count in dict(self.fixture_count_by_club).items():
            _gameweek(club, "club_id")
            if isinstance(count, bool) or not isinstance(count, int) or count < 0:
                raise ChipForecastError(
                    f"Club {club} has fixture count {count!r} in gameweek {self.gameweek}."
                )
            counts[club] = count
        if not counts:
            raise ChipForecastError(f"Gameweek {self.gameweek} lists no club.")
        object.__setattr__(
            self, "fixture_count_by_club", MappingProxyType(dict(sorted(counts.items())))
        )

    @property
    def clubs_doubling(self) -> int:
        return sum(1 for count in self.fixture_count_by_club.values() if count >= 2)

    @property
    def clubs_blank(self) -> int:
        return sum(1 for count in self.fixture_count_by_club.values() if count == 0)


@dataclass(frozen=True, slots=True)
class ChipForecastInputs:
    """Everything the forecast reads, and nothing it has to fetch.

    ``calendar`` holds the decision gameweek and every gameweek after it, without a gap,
    up to the last gameweek of every held window that is still open; each gameweek lists
    the same clubs, so a blank is a stated zero and never a missing row.
    ``holding_values`` names a value for every held chip. ``threshold`` and ``reserve``
    are the two decisions a measurement makes (``docs/chip_forecast_prereg.md``).
    """

    decision_gameweek: int
    chips: Sequence[HeldChip]
    squad: Sequence[SquadRow]
    calendar: Sequence[GameweekFixtures]
    holding_values: Mapping[str, float]
    threshold: str
    reserve: bool

    def __post_init__(self) -> None:
        _gameweek(self.decision_gameweek, "decision_gameweek")
        if self.threshold not in THRESHOLD_POLICIES:
            raise ChipForecastError(
                f"Threshold policy {self.threshold!r} is not one of {THRESHOLD_POLICIES!r}."
            )
        if not isinstance(self.reserve, bool):
            raise ChipForecastError("reserve must be a boolean.")
        object.__setattr__(self, "chips", tuple(self.chips))
        object.__setattr__(self, "squad", tuple(self.squad))
        object.__setattr__(
            self, "calendar", tuple(sorted(self.calendar, key=lambda week: week.gameweek))
        )
        self._check_chips()
        self._check_squad()
        self._check_calendar()

    def _check_chips(self) -> None:
        names = [chip.name for chip in self.chips]
        if len(set(names)) != len(names):
            raise ChipForecastError(f"A chip is held once in a half; got {names!r}.")
        holding: dict[str, float] = {}
        for name, value in dict(self.holding_values).items():
            if name not in CHIP_NAMES:
                raise ChipForecastError(f"holding_values names unknown chip {name!r}.")
            number = _finite(value, f"holding_values[{name}]")
            if number < 0.0:
                raise ChipForecastError(f"holding_values[{name}] must not be negative.")
            holding[name] = number
        missing = sorted(set(names) - set(holding))
        if missing:
            raise ChipForecastError(
                f"No holding value was given for {missing!r}; an absent value is not zero."
            )
        object.__setattr__(self, "holding_values", MappingProxyType(holding))
        for chip in self.chips:
            if chip.gain_this_week is not None and not (
                chip.first_gameweek <= self.decision_gameweek <= chip.last_gameweek
            ):
                raise ChipForecastError(
                    f"{chip.name!r} states a gain for gameweek {self.decision_gameweek}, "
                    "outside its window; a chip that cannot be played adds nothing to state."
                )

    def _check_squad(self) -> None:
        players = [row.player_id for row in self.squad]
        if len(players) != SQUAD_SIZE or len(set(players)) != SQUAD_SIZE:
            raise ChipForecastError(f"The present squad must be {SQUAD_SIZE} distinct players.")
        bench = sorted(row.bench_order for row in self.squad if row.bench_order is not None)
        if bench != list(range(1, BENCH_SIZE + 1)):
            raise ChipForecastError(
                f"The present bench must be orders 1 to {BENCH_SIZE}, once each; got {bench!r}."
            )
        captains = [row for row in self.squad if row.is_captain]
        if len(captains) != 1 or captains[0].bench_order is not None:
            raise ChipForecastError("The present eleven must hold exactly one captain.")

    def _check_calendar(self) -> None:
        weeks = [week.gameweek for week in self.calendar]
        if not weeks or weeks[0] != self.decision_gameweek:
            raise ChipForecastError(
                f"The calendar must start at the decision gameweek {self.decision_gameweek}."
            )
        if weeks != list(range(weeks[0], weeks[0] + len(weeks))):
            raise ChipForecastError(
                f"The calendar must list consecutive gameweeks once each; got {weeks!r}."
            )
        clubs = set(self.calendar[0].fixture_count_by_club)
        for week in self.calendar:
            if set(week.fixture_count_by_club) != clubs:
                raise ChipForecastError(
                    f"Gameweek {week.gameweek} lists other clubs than gameweek {weeks[0]}; "
                    "a blank is a stated zero, not a club left out."
                )
        strangers = sorted({row.club_id for row in self.squad} - clubs)
        if strangers:
            raise ChipForecastError(f"The calendar does not list the squad's clubs {strangers!r}.")
        decision = self.calendar[0].fixture_count_by_club
        idle = [
            row.player_id
            for row in self.squad
            if decision[row.club_id] == 0 and row.expected_points != 0.0
        ]
        if idle:
            raise ChipForecastError(
                f"Players {idle!r} have no fixture this gameweek and expected points other "
                "than zero; the projection and the calendar disagree."
            )
        needed = max(
            (
                chip.last_gameweek
                for chip in self.chips
                if chip.last_gameweek >= self.decision_gameweek
            ),
            default=self.decision_gameweek,
        )
        if weeks[-1] < needed:
            raise ChipForecastError(
                f"The calendar ends at gameweek {weeks[-1]} and a held window runs to "
                f"{needed}; a gameweek that was not given is not a blank."
            )


def holding_threshold(
    policy: str, holding_value: float, first_gameweek: int, last_gameweek: int, gameweek: int
) -> float:
    """What waiting is worth in ``gameweek`` of a window, under one threshold policy.

    ``fixed`` is the holding value for as long as the window is open. ``decaying`` is
    linear in the share of the window still ahead: the holding value in the window's
    first gameweek, zero in its last, and zero for a window of a single gameweek.
    """

    if policy not in THRESHOLD_POLICIES:
        raise ChipForecastError(
            f"Threshold policy {policy!r} is not one of {THRESHOLD_POLICIES!r}."
        )
    if not first_gameweek <= gameweek <= last_gameweek:
        raise ChipForecastError(
            f"Gameweek {gameweek} is outside the window {first_gameweek} to {last_gameweek}."
        )
    if policy == THRESHOLD_FIXED:
        return float(holding_value)
    span = last_gameweek - first_gameweek
    if span <= 0:
        return 0.0
    return float(holding_value) * (last_gameweek - gameweek) / span


def scaled_expected_points(
    expected_points: float, fixtures_this_week: int, fixtures_that_week: int
) -> float | None:
    """This gameweek's expected points restated for a later gameweek's fixture count.

    ``None`` when the club has no fixture this gameweek: there is no per-fixture value
    to rescale, and an absent number is not nought. Floored at zero, as the horizon
    builder floors it.
    """

    if fixtures_this_week <= 0:
        return None
    return max(0.0, expected_points * fixtures_that_week / fixtures_this_week)


def _reservation_allows(chip: HeldChip, week: GameweekFixtures, reserve: bool) -> bool:
    if not reserve or week.gameweek == chip.last_gameweek:
        return True
    if chip.name == BENCH_BOOST:
        return week.clubs_doubling > 0
    if chip.name == FREE_HIT:
        return week.clubs_doubling > 0 or week.clubs_blank > 0
    return True


def _estimate(
    chip: HeldChip, inputs: ChipForecastInputs, week: GameweekFixtures
) -> tuple[float, list[int]] | None:
    """What the chip is estimated to add in a later gameweek, and the players counted."""

    decision = inputs.calendar[0].fixture_count_by_club
    scaled: list[tuple[float, int]] = []
    for row in inputs.squad:
        if chip.name == BENCH_BOOST and row.bench_order is None:
            continue
        value = scaled_expected_points(
            row.expected_points, decision[row.club_id], week.fixture_count_by_club[row.club_id]
        )
        if value is not None:
            scaled.append((value, row.player_id))
    if not scaled:
        return None
    if chip.name == BENCH_BOOST:
        return math.fsum(value for value, _ in scaled), sorted(player for _, player in scaled)
    best, player = min(scaled, key=lambda pair: (-pair[0], pair[1]))
    return best, [player]


def _points_at(
    chip: HeldChip, inputs: ChipForecastInputs, later: Sequence[GameweekFixtures]
) -> dict[str, object] | None:
    if chip.name not in (TRIPLE_CAPTAIN, BENCH_BOOST):
        return None
    holding = inputs.holding_values[chip.name]
    for week in later:
        if not _reservation_allows(chip, week, inputs.reserve):
            continue
        estimate = _estimate(chip, inputs, week)
        if estimate is None:
            continue
        threshold = holding_threshold(
            inputs.threshold, holding, chip.first_gameweek, chip.last_gameweek, week.gameweek
        )
        if estimate[0] > threshold:
            return {
                "gameweek": week.gameweek,
                "estimated_gain": estimate[0],
                "threshold": threshold,
                "player_ids": estimate[1],
            }
    return None


def _chip_forecast(chip: HeldChip, inputs: ChipForecastInputs) -> dict[str, object]:
    now = inputs.decision_gameweek
    holding = inputs.holding_values[chip.name]
    later = [
        week
        for week in inputs.calendar
        if now < week.gameweek and chip.first_gameweek <= week.gameweek <= chip.last_gameweek
    ]
    entry: dict[str, object] = {
        "name": chip.name,
        "window": {"first_gameweek": chip.first_gameweek, "last_gameweek": chip.last_gameweek},
        "holding_value": holding,
        "verdict": VERDICT_EXPIRED_WINDOW,
        "hold_reason": None,
        "gain_this_week": chip.gain_this_week,
        "threshold_this_week": None,
        "reservation_allows_this_week": None,
        "points_at_gameweek": None,
        "structured_gameweeks": None,
    }
    if now > chip.last_gameweek:
        return entry
    entry["points_at_gameweek"] = _points_at(chip, inputs, later)
    if chip.name == FREE_HIT:
        entry["structured_gameweeks"] = [
            {
                "gameweek": week.gameweek,
                "clubs_doubling": week.clubs_doubling,
                "clubs_blank": week.clubs_blank,
            }
            for week in later
            if week.clubs_doubling > 0 or week.clubs_blank > 0
        ]
    if now < chip.first_gameweek:
        entry["verdict"] = VERDICT_WINDOW_NOT_OPEN
        return entry
    threshold = holding_threshold(
        inputs.threshold, holding, chip.first_gameweek, chip.last_gameweek, now
    )
    allowed = _reservation_allows(chip, inputs.calendar[0], inputs.reserve)
    entry["threshold_this_week"] = threshold
    entry["reservation_allows_this_week"] = allowed
    if not allowed:
        entry["verdict"], entry["hold_reason"] = VERDICT_HOLD, HOLD_RESERVED
    elif chip.gain_this_week is None:
        entry["verdict"] = VERDICT_UNKNOWN_THIS_WEEK
    elif chip.gain_this_week > threshold:
        entry["verdict"] = VERDICT_PLAY_NOW
        entry["points_at_gameweek"] = None
    else:
        entry["verdict"], entry["hold_reason"] = VERDICT_HOLD, HOLD_BELOW_THRESHOLD
    return entry


def chip_forecast(inputs: ChipForecastInputs) -> dict[str, object]:
    """The ``chip_forecast_v1`` document for one member at one decision gameweek.

    Chips are stated in the game's own order (``CHIP_NAMES``) whatever order they were
    given in, so the same inputs always make the same document.
    """

    decision = inputs.calendar[0].fixture_count_by_club
    idle = sorted(row.player_id for row in inputs.squad if decision[row.club_id] == 0)
    held = {chip.name: chip for chip in inputs.chips}
    chips = [_chip_forecast(held[name], inputs) for name in CHIP_NAMES if name in held]
    limits = [LIMIT_LATER_WEEKS, LIMIT_PRESENT_SQUAD, LIMIT_RULE_SOURCE, LIMIT_RECOMPUTED]
    if FREE_HIT in held or WILDCARD in held:
        limits.append(LIMIT_WHOLE_SQUAD_CHIPS)
    if idle:
        limits.append(LIMIT_NO_FIXTURE_THIS_WEEK)
    return {
        "contract_version": CHIP_FORECAST_CONTRACT_VERSION,
        "decision_gameweek": inputs.decision_gameweek,
        "threshold_policy": inputs.threshold,
        "reserve": inputs.reserve,
        "later_week_basis": LATER_WEEK_BASIS,
        "players_without_fixture_this_week": idle,
        "chips": chips,
        "limits": limits,
    }


def chip_forecast_schema() -> dict[str, Any]:
    """The strict shape of one ``chip_forecast_v1`` document.

    The conditions at the end are the rule's honesty written as a contract: a verdict of
    play now needs a stated gain and names no later gameweek, unknown this gameweek
    means the gain is ``null`` and never a number, and a window that is not open states
    neither a gain nor a threshold.
    """

    gameweek = {"type": "integer", "minimum": 1}
    number_or_null = {"type": ["number", "null"]}
    player_ids = {"type": "array", "items": {"type": "integer", "minimum": 1}, "uniqueItems": True}
    points_at = {
        "type": "object",
        "properties": {
            "gameweek": gameweek,
            "estimated_gain": {"type": "number", "minimum": 0},
            "threshold": {"type": "number", "minimum": 0},
            "player_ids": {**player_ids, "minItems": 1},
        },
        "required": ["gameweek", "estimated_gain", "threshold", "player_ids"],
        "additionalProperties": False,
    }
    structured = {
        "type": "object",
        "properties": {
            "gameweek": gameweek,
            "clubs_doubling": {"type": "integer", "minimum": 0},
            "clubs_blank": {"type": "integer", "minimum": 0},
        },
        "required": ["gameweek", "clubs_doubling", "clubs_blank"],
        "additionalProperties": False,
    }

    def verdict_is(*verdicts: str) -> dict[str, Any]:
        return {"properties": {"verdict": {"enum": list(verdicts)}}, "required": ["verdict"]}

    null = {"type": "null"}
    chip = {
        "type": "object",
        "properties": {
            "name": {"enum": list(CHIP_NAMES)},
            "window": {
                "type": "object",
                "properties": {"first_gameweek": gameweek, "last_gameweek": gameweek},
                "required": ["first_gameweek", "last_gameweek"],
                "additionalProperties": False,
            },
            "holding_value": {"type": "number", "minimum": 0},
            "verdict": {"enum": list(VERDICTS)},
            "hold_reason": {"enum": [None, *HOLD_REASONS]},
            "gain_this_week": number_or_null,
            "threshold_this_week": {"type": ["number", "null"], "minimum": 0},
            "reservation_allows_this_week": {"type": ["boolean", "null"]},
            "points_at_gameweek": {"anyOf": [points_at, null]},
            "structured_gameweeks": {"anyOf": [{"type": "array", "items": structured}, null]},
        },
        "required": [
            "name",
            "window",
            "holding_value",
            "verdict",
            "hold_reason",
            "gain_this_week",
            "threshold_this_week",
            "reservation_allows_this_week",
            "points_at_gameweek",
            "structured_gameweeks",
        ],
        "additionalProperties": False,
        "allOf": [
            {
                "if": verdict_is(VERDICT_PLAY_NOW),
                "then": {
                    "properties": {
                        "gain_this_week": {"type": "number"},
                        "threshold_this_week": {"type": "number"},
                        "reservation_allows_this_week": {"const": True},
                        "points_at_gameweek": null,
                    }
                },
            },
            {
                "if": verdict_is(VERDICT_UNKNOWN_THIS_WEEK),
                "then": {
                    "properties": {
                        "gain_this_week": null,
                        "threshold_this_week": {"type": "number"},
                        "reservation_allows_this_week": {"const": True},
                    }
                },
            },
            {
                "if": verdict_is(VERDICT_HOLD),
                "then": {
                    "properties": {
                        "hold_reason": {"enum": list(HOLD_REASONS)},
                        "threshold_this_week": {"type": "number"},
                        "reservation_allows_this_week": {"type": "boolean"},
                    }
                },
                "else": {"properties": {"hold_reason": null}},
            },
            {
                "if": verdict_is(VERDICT_WINDOW_NOT_OPEN, VERDICT_EXPIRED_WINDOW),
                "then": {
                    "properties": {
                        "gain_this_week": null,
                        "threshold_this_week": null,
                        "reservation_allows_this_week": null,
                    }
                },
            },
            {
                "if": verdict_is(VERDICT_EXPIRED_WINDOW),
                "then": {"properties": {"points_at_gameweek": null, "structured_gameweeks": null}},
            },
            {
                "if": {
                    "properties": {"name": {"enum": [WILDCARD, FREE_HIT]}},
                    "required": ["name"],
                },
                "then": {"properties": {"points_at_gameweek": null}},
            },
            {
                "if": {
                    "properties": {"name": {"enum": [WILDCARD, TRIPLE_CAPTAIN, BENCH_BOOST]}},
                    "required": ["name"],
                },
                "then": {"properties": {"structured_gameweeks": null}},
            },
        ],
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://squadopt.dev/contracts/chip_forecast_v1.schema.json",
        "title": "SquadOpt chip forecast",
        "type": "object",
        "properties": {
            "contract_version": {"type": "string", "const": CHIP_FORECAST_CONTRACT_VERSION},
            "decision_gameweek": gameweek,
            "threshold_policy": {"enum": list(THRESHOLD_POLICIES)},
            "reserve": {"type": "boolean"},
            "later_week_basis": {"type": "string", "const": LATER_WEEK_BASIS},
            "players_without_fixture_this_week": player_ids,
            "chips": {"type": "array", "items": chip, "maxItems": len(CHIP_NAMES)},
            "limits": {
                "type": "array",
                "items": {"type": "string", "minLength": 1},
                "minItems": 1,
                "uniqueItems": True,
            },
        },
        "required": [
            "contract_version",
            "decision_gameweek",
            "threshold_policy",
            "reserve",
            "later_week_basis",
            "players_without_fixture_this_week",
            "chips",
            "limits",
        ],
        "additionalProperties": False,
    }


def write_chip_forecast_schema(path: Path | None = None) -> Path:
    """Write the schema to ``path`` (default: the committed contract file)."""

    target = Path(path) if path is not None else CHIP_FORECAST_SCHEMA_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(chip_forecast_schema(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return target
