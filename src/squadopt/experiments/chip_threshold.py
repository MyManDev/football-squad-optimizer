"""What waiting for a chip is worth, computed by backward induction over its window.

The chain plays a chip in gameweek ``t`` when what it adds that week, ``g_t``, exceeds a
threshold. The committed chains held a constant, and the chip forecast's protocol
(``docs/chip_forecast_prereg.md``) lets that constant fall linearly to zero at the end of
the chip's window, because a chip not played by then is lost. The line is a guess at a
quantity that has a definition: holding a chip is worth the best later opportunity in
the window, which is an optimal stopping problem. With ``L`` the window's last gameweek,

    tau_L = 0
    tau_t = E[ max(g_{t+1}, tau_{t+1}) ]        for t < L

and the rule is "play at ``t`` when ``g_t > tau_t``". The expectation is over what next
gameweek could offer, and that depends on the kind of gameweek it is: a captain who plays
twice is projected for about twice as much, so a double ahead is worth waiting for and a
run of plain gameweeks is not.

This module is that arithmetic and nothing else. It reads a fixture-count table and chain
week records handed to it, it draws no random number, and it writes nothing. The
expectation is taken over the empirical sample of one kind of gameweek, so there is no
distribution to fit and nothing to tune. Two chips are covered, the two whose exercise
value the chain already records every week at no extra solve: the triple captain (what
the decision expected of its captain) and the bench boost (what it expected of its
bench). A wildcard's and a free hit's value is a whole-squad solve and is not in the
weekly record, so they are out of reach here by construction.

The threshold may only see what a decision could see. The projected columns are read, the
realized ones never: a rule that learned from what captains went on to score would be
tuned on the outcome it is later judged by.

Protocol: ``docs/chip_threshold_induction_prereg.md``. Nothing here is wired into the chain
yet; that is a later change, after the chain records the projected columns.
"""

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

import pandas as pd

from squadopt.evaluation.promotion import (
    ExperimentConfigurationError,
    ExperimentExecutionError,
)
from squadopt.experiments.season_chain import ChipHoldingSchedule, ChipWindowRule

CHIP_THRESHOLD_INDUCTION_CONTRACT_VERSION: Final = "chip_threshold_induction_v1"

SINGLE_GAMEWEEK: Final = "single"
DOUBLE_GAMEWEEK: Final = "double"
BLANK_GAMEWEEK: Final = "blank"
GAMEWEEK_KINDS: Final = (SINGLE_GAMEWEEK, DOUBLE_GAMEWEEK, BLANK_GAMEWEEK)

#: The week-record column that holds each covered chip's exercise value: what playing the
#: chip that week was expected to add. Projected columns only, by design (module docstring).
CHIP_VALUE_FIELDS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "3xc": "captain_projected_points",
        "bboost": "bench_projected_points",
    }
)

_FIXTURE_COUNT_COLUMNS: Final = ("gameweek", "team_id", "fixture_count")


def classify_gameweek_kinds(
    fixture_counts: pd.DataFrame, gameweeks: Iterable[int] | None = None
) -> dict[int, str]:
    """The kind of every gameweek of one season: ``single``, ``double`` or ``blank``.

    ``fixture_counts`` has the shape ``season_fixture_counts`` returns: one row per
    (gameweek, club) with the club's number of fixtures. That table is built by counting
    fixtures, so a club with no fixture in a gameweek has no row at all; a missing row is
    therefore read as a blank, exactly as an explicit zero is. The clubs of the season are
    every club the table names in any gameweek.

    A gameweek in which some club doubles is ``double`` even when another club is blank in
    it. Both chips covered here are worth what the best few players are projected for,
    and those are the players who play twice, whoever else sits the week out; a fourth
    kind for the mixed week would also split four seasons' handful of structured
    gameweeks into cells too small to average. ``blank`` is a gameweek where some club
    does not play and none doubles; ``single`` is every club once.

    ``gameweeks`` names the gameweeks to classify; by default, those the table holds. A
    named gameweek with no row is one nobody plays in, and is ``blank``.
    """

    if not isinstance(fixture_counts, pd.DataFrame):
        raise ExperimentExecutionError("fixture_counts must be a pandas DataFrame.")
    missing = [column for column in _FIXTURE_COUNT_COLUMNS if column not in fixture_counts.columns]
    if missing:
        raise ExperimentExecutionError(f"fixture_counts is missing required columns: {missing!r}.")
    counts: dict[tuple[int, object], int] = {}
    for gameweek, club, count in zip(
        fixture_counts["gameweek"].tolist(),
        fixture_counts["team_id"].tolist(),
        fixture_counts["fixture_count"].tolist(),
        strict=True,
    ):
        key = (int(gameweek), club)
        if key in counts:
            raise ExperimentExecutionError(
                f"fixture_counts holds two rows for club {club!r} in gameweek {key[0]}."
            )
        number = _finite(count, f"fixture_count of club {club!r} in gameweek {key[0]}")
        if number < 0 or number != int(number):
            raise ExperimentExecutionError(
                f"fixture_count of club {club!r} in gameweek {key[0]} is not a count: {count!r}."
            )
        counts[key] = int(number)
    if not counts:
        raise ExperimentExecutionError("fixture_counts holds no row.")
    clubs = {club for _, club in counts}
    chosen = sorted({week for week, _ in counts} if gameweeks is None else set(gameweeks))
    kinds: dict[int, str] = {}
    for gameweek in chosen:
        week_counts = [counts.get((int(gameweek), club), 0) for club in clubs]
        if any(count >= 2 for count in week_counts):
            kinds[int(gameweek)] = DOUBLE_GAMEWEEK
        elif any(count == 0 for count in week_counts):
            kinds[int(gameweek)] = BLANK_GAMEWEEK
        else:
            kinds[int(gameweek)] = SINGLE_GAMEWEEK
    return kinds


def exercise_values_by_kind(
    weeks: Iterable[Mapping[str, object]], kinds: Mapping[int, str]
) -> dict[str, dict[str, tuple[float, ...]]]:
    """Each covered chip's weekly exercise values, grouped by the kind of gameweek.

    ``weeks`` are chain week records as ``SeasonChainWeek.as_record()`` writes them, all
    of one season, and ``kinds`` is that season's classification. The result maps chip to
    kind to the values in record order, with every kind present (possibly empty), so a
    caller sees a thin cell instead of a missing key.

    A value of ``None`` is skipped: the chain writes it when the plan's captain row
    carried no projection, and a record written before the projected columns existed has
    none at all. Only the projected columns are read (module docstring). A week whose
    gameweek the classification does not know is an error, not a guess at its kind.
    """

    values: dict[str, dict[str, list[float]]] = {
        chip: {kind: [] for kind in GAMEWEEK_KINDS} for chip in CHIP_VALUE_FIELDS
    }
    for week in weeks:
        gameweek = _gameweek_of(week)
        kind = kinds.get(gameweek)
        if kind is None:
            raise ExperimentExecutionError(
                f"Gameweek {gameweek} of the chain has no kind in the classification."
            )
        _require_kind(kind)
        for chip, column in CHIP_VALUE_FIELDS.items():
            value = week.get(column)
            if value is None:
                continue
            values[chip][kind].append(_finite(value, f"{column} of gameweek {gameweek}"))
    return {
        chip: {kind: tuple(sample) for kind, sample in by_kind.items()}
        for chip, by_kind in values.items()
    }


@dataclass(frozen=True, slots=True)
class InductionThresholds:
    """The thresholds of one window, and whether any of them leaned on the pooled sample."""

    thresholds: tuple[float, ...]
    """``tau`` for every gameweek handed in, in the same order; the last is zero."""
    pooled_fallback_kinds: tuple[str, ...]
    """The kinds that had to be averaged over but had no sample of their own, for which
    the pooled sample of every kind stood in. Empty when every expectation was taken over
    its own kind. A caller that publishes thresholds has to publish this beside them."""


def induction_thresholds(
    kinds_ahead: Sequence[str], values_by_kind: Mapping[str, Sequence[float]]
) -> InductionThresholds:
    """``tau`` for every remaining gameweek of a window, by backward induction.

    ``kinds_ahead`` are the kinds of the window's remaining gameweeks in order, the
    gameweek being decided first and the window's last gameweek last.
    ``values_by_kind`` is the empirical sample of the chip's exercise value per kind.

    The last gameweek's threshold is zero: a chip held past it is lost, so anything it
    adds is worth taking. Before that, ``tau_t`` is the mean over the sample of next
    gameweek's kind of ``max(value, tau_{t+1})``: what the next gameweek is worth with the
    option to pass it up for the ones after. The kind of the first gameweek is never
    averaged over, because its own value is known when it is decided. Since the last
    threshold is zero and each earlier one averages numbers no smaller than the one after
    it, thresholds are never negative and never rise as the window runs out: they step
    down as each good gameweek goes by.

    A kind that has to be averaged over and has no sample falls back to the pooled sample
    of every kind, and the result says so in ``pooled_fallback_kinds``. An empty pooled
    sample is an error even for a window of one gameweek, where no sample is consulted:
    it means the records carried no projected value at all, which a caller should hear
    about here and not as a row of zeros later.
    """

    kinds = tuple(kinds_ahead)
    if not kinds:
        raise ExperimentConfigurationError("kinds_ahead must name at least one gameweek.")
    for kind in kinds:
        _require_kind(kind)
    samples: dict[str, tuple[float, ...]] = {}
    for kind, sample in values_by_kind.items():
        _require_kind(kind)
        samples[kind] = tuple(
            _finite(value, f"a value of kind {kind!r}") for value in tuple(sample)
        )
    pooled = tuple(value for kind in GAMEWEEK_KINDS for value in samples.get(kind, ()))
    if not pooled:
        raise ExperimentExecutionError(
            "No exercise value of any kind was given, so no threshold can be computed."
        )
    thresholds = [0.0] * len(kinds)
    fallbacks: set[str] = set()
    for index in range(len(kinds) - 2, -1, -1):
        next_kind = kinds[index + 1]
        sample = samples.get(next_kind, ())
        if not sample:
            fallbacks.add(next_kind)
            sample = pooled
        waiting = thresholds[index + 1]
        thresholds[index] = math.fsum(max(value, waiting) for value in sample) / len(sample)
    return InductionThresholds(
        thresholds=tuple(thresholds),
        pooled_fallback_kinds=tuple(kind for kind in GAMEWEEK_KINDS if kind in fallbacks),
    )


@dataclass(frozen=True, slots=True)
class WindowThresholds:
    """One chip window's thresholds for one season, with what they were computed from."""

    chip: str
    start_gameweek: int
    stop_gameweek: int
    gameweeks: tuple[int, ...]
    """The classified gameweeks the window covers, in order. A gameweek of the range that
    the season's classification does not hold is no opportunity and has no threshold."""
    thresholds: tuple[float, ...]
    pooled_fallback_kinds: tuple[str, ...]
    sample_seasons: tuple[str, ...]
    """The seasons whose chains supplied the sample. Never the season the thresholds are
    for, when they come from ``leave_one_season_out_thresholds``."""
    sample_sizes: tuple[tuple[str, int], ...]
    """(kind, number of values) for every kind, so a thin cell is visible in the record."""

    def threshold_at(self, gameweek: int) -> float:
        """The threshold of one gameweek of the window."""

        for week, threshold in zip(self.gameweeks, self.thresholds, strict=True):
            if week == gameweek:
                return threshold
        raise ExperimentExecutionError(
            f"Gameweek {gameweek} is not a classified gameweek of the {self.chip!r} window "
            f"{self.start_gameweek}-{self.stop_gameweek}."
        )

    def as_schedule(self) -> ChipHoldingSchedule:
        """The chain's own shape of this window's thresholds."""

        return ChipHoldingSchedule(
            name=self.chip,
            start_gameweek=self.start_gameweek,
            stop_gameweek=self.stop_gameweek,
            values=tuple(zip(self.gameweeks, self.thresholds, strict=True)),
        )

    def as_record(self) -> dict[str, object]:
        return {
            "chip": self.chip,
            "start_gameweek": self.start_gameweek,
            "stop_gameweek": self.stop_gameweek,
            "thresholds": {
                str(week): threshold
                for week, threshold in zip(self.gameweeks, self.thresholds, strict=True)
            },
            "pooled_fallback_kinds": list(self.pooled_fallback_kinds),
            "sample_seasons": list(self.sample_seasons),
            "sample_sizes": dict(self.sample_sizes),
        }


def window_thresholds(
    window: ChipWindowRule,
    kinds: Mapping[int, str],
    values_by_kind: Mapping[str, Sequence[float]],
    *,
    sample_seasons: Sequence[str] = (),
) -> WindowThresholds:
    """The thresholds of one chip window over one season's classified gameweeks."""

    if window.name not in CHIP_VALUE_FIELDS:
        raise ExperimentConfigurationError(
            f"No weekly exercise value is recorded for chip {window.name!r}; the induction "
            f"covers {tuple(CHIP_VALUE_FIELDS)!r}."
        )
    gameweeks = tuple(sorted(week for week in kinds if window.covers(int(week))))
    if not gameweeks:
        raise ExperimentExecutionError(
            f"The {window.name!r} window {window.start_gameweek}-{window.stop_gameweek} "
            "covers no classified gameweek."
        )
    result = induction_thresholds([kinds[week] for week in gameweeks], values_by_kind)
    return WindowThresholds(
        chip=window.name,
        start_gameweek=window.start_gameweek,
        stop_gameweek=window.stop_gameweek,
        gameweeks=gameweeks,
        thresholds=result.thresholds,
        pooled_fallback_kinds=result.pooled_fallback_kinds,
        sample_seasons=tuple(sample_seasons),
        sample_sizes=tuple(
            (kind, len(tuple(values_by_kind.get(kind, ())))) for kind in GAMEWEEK_KINDS
        ),
    )


def leave_one_season_out_thresholds(
    chains: Iterable[Mapping[str, object]],
    kinds_by_season: Mapping[str, Mapping[int, str]],
    windows: Sequence[ChipWindowRule],
    *,
    variant: str,
) -> dict[str, tuple[WindowThresholds, ...]]:
    """Every season's window thresholds, computed from the other seasons' chains only.

    ``chains`` are chain records as the runners write them (``season``, ``variant``,
    ``weeks``); only those of ``variant`` are read, one per season. The thresholds a
    season is later walked with must not have seen that season: its weekly values are
    left out of its own sample, so an evaluation of the rule on season ``S`` is an
    evaluation on gameweeks the rule never averaged over. The kinds of ``S``'s own
    gameweeks are read, because the calendar is what the rule is a function of.

    Returns season to one ``WindowThresholds`` per window, in the order given.
    """

    by_season: dict[str, list[Mapping[str, object]]] = {}
    for chain in chains:
        if chain.get("variant") != variant:
            continue
        if chain.get("season") is None:
            raise ExperimentExecutionError("A chain record names no season.")
        season = str(chain["season"])
        if season in by_season:
            raise ExperimentExecutionError(
                f"Two chains of variant {variant!r} were given for season {season}."
            )
        by_season[season] = _week_records(chain.get("weeks"), season)
    if len(by_season) < 2:
        raise ExperimentExecutionError(
            f"Leaving one season out needs chains of variant {variant!r} for at least two "
            f"seasons; got {sorted(by_season)!r}."
        )
    unclassified = sorted(season for season in by_season if season not in kinds_by_season)
    if unclassified:
        raise ExperimentExecutionError(f"No gameweek kinds were given for {unclassified!r}.")
    season_values = {
        season: exercise_values_by_kind(weeks, kinds_by_season[season])
        for season, weeks in by_season.items()
    }
    result: dict[str, tuple[WindowThresholds, ...]] = {}
    for held_out in sorted(by_season):
        others = tuple(season for season in sorted(by_season) if season != held_out)
        result[held_out] = tuple(
            window_thresholds(
                window,
                kinds_by_season[held_out],
                {
                    kind: tuple(
                        value
                        for season in others
                        for value in season_values[season].get(window.name, {}).get(kind, ())
                    )
                    for kind in GAMEWEEK_KINDS
                },
                sample_seasons=others,
            )
            for window in windows
        )
    return result


def _require_kind(kind: object) -> None:
    if kind not in GAMEWEEK_KINDS:
        raise ExperimentConfigurationError(
            f"A gameweek kind must be one of {GAMEWEEK_KINDS!r}; got {kind!r}."
        )


def _gameweek_of(week: Mapping[str, object]) -> int:
    gameweek = week.get("gameweek")
    if isinstance(gameweek, bool) or not isinstance(gameweek, int):
        raise ExperimentExecutionError(f"A chain week record has no integer gameweek: {week!r}.")
    return gameweek


def _finite(value: object, what: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ExperimentExecutionError(f"{what} is not a number: {value!r}.")
    number = float(value)
    if not math.isfinite(number):
        raise ExperimentExecutionError(f"{what} is not finite: {value!r}.")
    return number


def _week_records(value: object, season: str) -> list[Mapping[str, object]]:
    if not isinstance(value, list) or any(not isinstance(item, Mapping) for item in value):
        raise ExperimentExecutionError(f"The chain of {season} has no list of week records.")
    return list(value)
