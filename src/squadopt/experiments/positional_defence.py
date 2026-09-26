"""A positional structure for goalkeepers and defenders, as its protocol fixes it.

The protocol is ``docs/positional_defence_prereg.md`` and this module only implements it.
Nothing here chooses a threshold, a population or a tolerance: each was fixed before any of
it was fitted, and a value that appears here and not there is a bug rather than a decision.

The candidate prices one row of the control's population:

.. code-block:: text

    long(row) = 1 if expected_minutes_if_appearance >= 60 else 0
    expected  = appearance_probability
                * ( (1 + long) + 4 * long * P(clean sheet) + bonus(position) )

Three things about that shape are protocol rather than taste, and each closes a mistake an
earlier draft made. ``long`` is an indicator on a **scalar**, because the shipped model
carries a point estimate of conditional minutes and no distribution to take a probability
from. The clean-sheet term is multiplied by ``long`` and not by the appearance probability
alone, because the game pays the four points at sixty minutes and pays a twenty-minute
substitute nothing. And ``bonus(position)`` is a mean over **appeared** rows rather than over
clean-sheet matches, because a mean taken on clean sheets and then added everywhere would
over-price every defender in the direction the level audit already finds them mispriced.

**Where the inputs come from is part of the protocol, not an implementation detail.**
``position`` is not a column of the out-of-fold table; the handoff reader joins it from the
companion roster. ``team_id`` is in that roster too, is *not* joined across, and is a club
**name** rather than a code, so the clean-sheet join bridges it through
``load_team_codes``. Realized ``bonus`` is in neither file: it is the archive's own column in
``merged_gw.csv``, and the canonical panel does not carry it either, because the adapter's
column map does not declare it. A runner that reached for ``build_panel`` would find no bonus
at all, so this module reads the archive file for that term and says so here.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import pandas as pd

from squadopt.data.sources.vaastav import load_team_codes
from squadopt.evaluation.promotion import ExperimentExecutionError

#: Identifies this reading in a record. It moves when the candidate's meaning moves.
POSITIONAL_DEFENCE_CONTRACT_VERSION: Final = "positional_defence_v1"

#: The group the protocol names, and nothing else.
DEFENCE_POSITIONS: Final = ("GK", "DEF")

#: Judged seasons and the first target gameweek, both fixed by the protocol.
JUDGED_SEASONS: Final = ("2022-23", "2023-24", "2024-25")
FIRST_TARGET_GAMEWEEK: Final = 4

#: The minutes at which the game pays the second appearance point and the clean sheet.
LONG_MINUTES: Final = 60.0

#: The clean sheet's value to a goalkeeper or defender under the judged seasons' rules.
CLEAN_SHEET_POINTS: Final = 4.0

#: Carried unchanged from `opening_two_part_prereg` so the two clauses are comparable.
ORDERING_TOLERANCE: Final = 0.010

#: How close to the tolerance still counts as inside it, for representation only.
#:
#: The protocol's words are that the ordering "must not fall below the shipped composition's
#: by more than 0.010", so a shortfall of exactly the tolerance passes. The shortfall is a
#: difference of two correlations and carries floating error of order 1e-16, and the point is
#: not that an unguarded comparison is stricter -- it is that it is **inconsistent**. Every
#: one of these is a true shortfall of exactly 0.010::
#:
#:     0.500 against 0.490 -> 0.010000000000000009  fails
#:     0.563 against 0.553 -> 0.009999999999999898  passes
#:
#: So without the guard, whether a candidate on the boundary passes depends on where its two
#: correlations happen to sit on the number line, which is not a reading of the protocol at
#: all. The guard implements the sentence. It is not a widening and may not be used as one:
#: 1e-12 is a ten-billionth of the tolerance, which is itself about one standard error of a
#: rank correlation on this population, so nothing can be rescued that is not exactly on the
#: line. It was fixed before the run and before any result was visible.
#:
#: ``opening_two_part`` carries the same constant and does not have this problem, because its
#: runner passes the pooled shortfall in as a value and the comparison meets an exact float.
#: Here the shortfall is computed from two correlations, so the boundary is reachable in a way
#: it was not there. **Same constant, different exposure**, which is worth saying because the
#: next protocol to carry 0.010 across will inherit the number and not the exposure.
ORDERING_REPRESENTATION_GUARD: Final = 1e-12

#: A judged season with fewer appeared goalkeeper and defender training rows is not judged.
#: The rows are archive rows of strictly earlier seasons, which is what the protocol fixes.
MINIMUM_TRAINING_ROWS: Final = 200

#: Clause 3's allowance: at most one of the three judged seasons may lose.
MAXIMUM_LOSING_SEASONS: Final = 1


@dataclass(frozen=True, slots=True)
class PopulationCounts:
    """What the drop rules removed, counted rather than described."""

    rows_before_drops: int
    appeared_before_drops: int
    direct_control_dropped: int
    double_gameweek_dropped: int
    blank_gameweek_dropped: int
    dropped_by_both: int
    rows: int
    appeared_rows: int
    rows_without_a_club_rating: int


def eligible_rows(rows: pd.DataFrame) -> tuple[pd.DataFrame, PopulationCounts]:
    """The protocol's population, with both drop rules applied and counted.

    Both drops are named in the protocol and both are applied here rather than in the runner,
    so a reading and a decision cannot disagree about which rows they cover. The counts
    travel with the frame because the record has to state them.
    """

    group = rows.loc[
        rows["position"].astype("string").isin(list(DEFENCE_POSITIONS))
        & rows["season"].astype("string").isin(list(JUDGED_SEASONS))
        & (pd.to_numeric(rows["target_gameweek"], errors="raise") >= FIRST_TARGET_GAMEWEEK)
    ]
    appeared_before = pd.to_numeric(group["appearance_target"], errors="coerce") == 1
    direct = group["control_expected_points"].isna()
    fixtures = pd.to_numeric(group["fixture_count"], errors="raise")
    doubles = fixtures > 1
    # The protocol drops a row whose club has no fixture that gameweek beside the doubles,
    # for the same reason: the structure prices one match. On this population that rule binds
    # on nothing, and the count says so rather than the rule being left out because it does.
    blanks = fixtures == 0
    kept = group.loc[~direct & (fixtures == 1)].copy(deep=True)
    counts = PopulationCounts(
        rows_before_drops=len(group),
        appeared_before_drops=int(appeared_before.sum()),
        direct_control_dropped=int(direct.sum()),
        double_gameweek_dropped=int(doubles.sum()),
        blank_gameweek_dropped=int(blanks.sum()),
        dropped_by_both=int((direct & (doubles | blanks)).sum()),
        rows=len(kept),
        appeared_rows=int((pd.to_numeric(kept["appearance_target"], errors="coerce") == 1).sum()),
        # Filled by the caller once the ratings are known; zero here is not a claim.
        rows_without_a_club_rating=0,
    )
    return kept, counts


def long_indicator(rows: pd.DataFrame) -> "pd.Series[Any]":
    """One where the shipped conditional-minutes scalar reaches sixty, zero below it.

    A row whose scalar is missing gets ``pd.NA`` rather than a zero. ``NaN >= 60`` is False,
    which would quietly price such a row as a certain substitute without anybody choosing
    that; the protocol drops those rows instead, and this makes the absence visible so the
    caller can.
    """

    minutes = pd.to_numeric(rows["expected_minutes_if_appearance"], errors="coerce")
    indicator = (minutes >= LONG_MINUTES).astype("Float64")
    return indicator.where(minutes.notna())


def realized_bonus(archive_root: Path | str, seasons: Sequence[str]) -> pd.DataFrame:
    """Realized bonus per player-gameweek, read from the archive's own file.

    The canonical panel does not carry ``bonus``: the vaastav adapter's column map does not
    declare it, so ``build_panel`` returns a frame without it. This reads
    ``<season>/gws/merged_gw.csv`` directly for the one column the protocol's bonus term
    needs, keeps the position and the minutes beside it, and does nothing else with the file.
    """

    root = Path(archive_root)
    frames: list[pd.DataFrame] = []
    for season in seasons:
        path = root / "data" / str(season) / "gws" / "merged_gw.csv"
        if not path.exists():
            raise ExperimentExecutionError(
                f"The archive has no gameweek file for {season!r} at {path}; the bonus term "
                "cannot be fitted on a season that is not there."
            )
        frame = pd.read_csv(path, usecols=["element", "round", "position", "minutes", "bonus"])
        frame["season"] = str(season)
        frames.append(frame)
    joined = pd.concat(frames, ignore_index=True)
    joined["position"] = joined["position"].astype("string").replace({"GKP": "GK"})
    return joined


def bonus_by_position(bonus_rows: pd.DataFrame, seasons: Sequence[str]) -> dict[str, float]:
    """The per-position mean realized bonus over appeared rows of the named seasons.

    Over appeared rows, not over clean-sheet matches. A position with no appeared row in the
    training seasons is absent from the mapping rather than present at zero: the caller has
    to decide what an unpriced position means, and a zero would decide it silently.
    """

    frame = bonus_rows.loc[bonus_rows["season"].astype("string").isin(list(seasons))]
    appeared = frame.loc[pd.to_numeric(frame["minutes"], errors="coerce") > 0]
    means: dict[str, float] = {}
    for position in DEFENCE_POSITIONS:
        held = appeared.loc[appeared["position"].astype("string") == position]
        if held.empty:
            continue
        means[position] = float(pd.to_numeric(held["bonus"], errors="raise").mean())
    return means


def training_row_counts(bonus_rows: pd.DataFrame, seasons: Sequence[str]) -> int:
    """Appeared goalkeeper and defender archive rows of the named seasons.

    This is what the protocol's 200-row minimum counts, and it counts archive rows rather
    than out-of-fold table rows: the table begins at 2021-22 while 2022-23 trains on 2020-21
    and 2021-22, so one training season is not in the table at all.
    """

    frame = bonus_rows.loc[bonus_rows["season"].astype("string").isin(list(seasons))]
    appeared = frame.loc[pd.to_numeric(frame["minutes"], errors="coerce") > 0]
    return int((appeared["position"].astype("string").isin(list(DEFENCE_POSITIONS))).sum())


def club_codes(archive_root: Path | str, seasons: Sequence[str]) -> pd.DataFrame:
    """The roster's club **name** bridged to the persistent club code, per season.

    The decision roster spells a club as a name ("Liverpool"), and the rating and the fixture
    table speak codes. The bridge is the archive's own team file, read the way
    `player_fixture_rows` reads it, rather than a mapping written here.
    """

    root = Path(archive_root)
    frames: list[pd.DataFrame] = []
    for season in seasons:
        codes = load_team_codes(root, season).loc[:, ["code", "name"]].copy(deep=True)
        codes["season"] = str(season)
        frames.append(codes)
    bridge = pd.concat(frames, ignore_index=True).rename(columns={"name": "team_id"})
    bridge["club"] = pd.to_numeric(bridge["code"], errors="raise").astype("int64")
    return bridge.loc[:, ["season", "team_id", "club"]]


def candidate_points(
    rows: pd.DataFrame,
    long: "pd.Series[Any]",
    clean_sheet: "pd.Series[Any]",
    bonus: Mapping[str, float],
) -> "pd.Series[Any]":
    """The protocol's expression, evaluated term by term.

    Every factor is required: a row missing its appearance probability, its ``long``
    indicator, its clean-sheet probability or its position's bonus yields ``pd.NA`` rather
    than a partially priced number. Half a structure is not a price.
    """

    appearance = pd.to_numeric(rows["appearance_probability"], errors="coerce").astype("Float64")
    indicator = pd.to_numeric(long, errors="coerce").astype("Float64")
    probability = pd.to_numeric(clean_sheet, errors="coerce").astype("Float64")
    position = rows["position"].astype("string")
    per_position = position.map(lambda value: bonus.get(str(value)))
    extra = pd.to_numeric(per_position, errors="coerce").astype("Float64")
    conditional = (1.0 + indicator) + CLEAN_SHEET_POINTS * indicator * probability + extra
    return (appearance * conditional).astype("Float64")


def _errors(forecast: "pd.Series[Any]", realized: "pd.Series[Any]") -> "pd.Series[Any]":
    values = pd.to_numeric(forecast, errors="coerce").astype("float64")
    outcomes = pd.to_numeric(realized, errors="coerce").astype("float64")
    return (values - outcomes).dropna()


def mean_absolute_error(forecast: "pd.Series[Any]", realized: "pd.Series[Any]") -> float | None:
    """Mean absolute error over the rows both sides are present on, or ``None``."""

    error = _errors(forecast, realized)
    return None if error.empty else float(error.abs().mean())


def within_position_rank(
    frame: pd.DataFrame, forecast: "pd.Series[Any]", realized: "pd.Series[Any]"
) -> dict[str, float | None]:
    """Spearman between a forecast and the outcome, separately for each position.

    Separately, because a pooled correlation over two positions would be partly a reading of
    the gap between them rather than of the ordering inside either.
    """

    values = pd.to_numeric(forecast, errors="coerce")
    outcomes = pd.to_numeric(realized, errors="coerce")
    position = frame["position"].astype("string")
    ranks: dict[str, float | None] = {}
    for label in DEFENCE_POSITIONS:
        selected = position == label
        paired = pd.DataFrame(
            {"forecast": values.loc[selected], "realized": outcomes.loc[selected]}
        )
        paired = paired.dropna()
        if len(paired) < 2 or paired["forecast"].nunique() < 2 or paired["realized"].nunique() < 2:
            ranks[label] = None
            continue
        ranks[label] = float(paired["forecast"].corr(paired["realized"], method="spearman"))
    return ranks


def accuracy_clause(
    appeared: Mapping[str, Any],
    seasons: Mapping[str, Mapping[str, float | None]],
    floor: Mapping[str, float | None],
) -> dict[str, Any]:
    """Clause 1: binding on appeared rows, with a floor over the surviving rows.

    The floor is not over the whole population and is not called that here either: two drop
    rules narrowed it before either half read anything.
    """

    interval = appeared.get("interval")
    lower = None if interval is None else float(interval[0])

    def improves(reading: Mapping[str, float | None]) -> bool:
        candidate = reading.get("candidate")
        control = reading.get("control")
        # A season that could not be read has not improved. Treating it as silent would let a
        # candidate clear the clause on the seasons that happened to be readable.
        return candidate is not None and control is not None and float(candidate) < float(control)

    every_season = all(improves(reading) for reading in seasons.values())
    candidate_floor = floor.get("candidate")
    control_floor = floor.get("control")
    floor_passes = (
        candidate_floor is not None
        and control_floor is not None
        # A floor, not an improvement: an exact tie passes.
        and float(candidate_floor) <= float(control_floor)
    )
    binding = lower is not None and lower > 0.0 and every_season and bool(seasons)
    return {
        "binding_on_appeared_rows": {
            "mean_difference": appeared.get("mean_difference"),
            "interval": None if interval is None else [float(interval[0]), float(interval[1])],
            "interval_lower_above_zero": lower is not None and lower > 0.0,
            "improves_every_judged_season": every_season,
            "by_season": {name: dict(reading) for name, reading in seasons.items()},
            "passes": binding,
        },
        "floor_over_surviving_rows": {
            "candidate": candidate_floor,
            "control": control_floor,
            "not_worse": floor_passes,
            "passes": floor_passes,
        },
        "passes": bool(binding and floor_passes),
    }


def ordering_clause(
    by_season: Mapping[str, Mapping[str, Mapping[str, float | None]]],
    pooled: Mapping[str, Mapping[str, float | None]],
) -> dict[str, Any]:
    """Clause 2: within-position Spearman on appeared rows, against a fixed tolerance.

    A missing correlation fails rather than being skipped. A season whose ordering could not
    be read is a season the clause could not clear, and treating it as silent would let a
    candidate pass on the seasons that happened to be readable.
    """

    shortfalls: dict[str, Any] = {}
    passes = True
    for label, readings in (("pooled", pooled), *by_season.items()):
        block: dict[str, Any] = {}
        for position in DEFENCE_POSITIONS:
            reading = readings.get(position, {})
            candidate = reading.get("candidate")
            control = reading.get("control")
            if candidate is None or control is None:
                block[position] = {"candidate": candidate, "control": control, "passes": False}
                passes = False
                continue
            shortfall = float(control) - float(candidate)
            inside = shortfall <= ORDERING_TOLERANCE + ORDERING_REPRESENTATION_GUARD
            passes = passes and inside
            block[position] = {
                "candidate": float(candidate),
                "control": float(control),
                "rank_shortfall": shortfall,
                "passes": inside,
            }
        shortfalls[label] = block
    return {
        "tolerance": ORDERING_TOLERANCE,
        "representation_guard": ORDERING_REPRESENTATION_GUARD,
        "readings": shortfalls,
        "passes": bool(passes),
    }


def decision_clause(
    mean_difference: float | None,
    season_means: Mapping[str, float],
    interval: tuple[float, float] | None,
    paired_decisions: int,
) -> dict[str, Any]:
    """Clause 3: mean realized difference at least zero, at most one judged season losing.

    The interval is reported and does not gate. The protocol says so, and saying it here
    keeps a later reader from treating a wide interval as a failure the clause never declared.
    """

    losing = sorted(name for name, value in season_means.items() if value < 0.0)
    mean_passes = mean_difference is not None and mean_difference >= 0.0
    seasons_pass = len(losing) <= MAXIMUM_LOSING_SEASONS
    return {
        "paired_decisions": paired_decisions,
        "mean_difference": mean_difference,
        "mean_at_least_zero": mean_passes,
        "losing_seasons": losing,
        "at_most_one_losing_season": seasons_pass,
        "maximum_losing_seasons": MAXIMUM_LOSING_SEASONS,
        "interval": None if interval is None else [float(interval[0]), float(interval[1])],
        "interval_gates": False,
        "passes": bool(mean_passes and seasons_pass),
    }


def positional_defence_gate(
    accuracy: Mapping[str, Any], ordering: Mapping[str, Any], decision: Mapping[str, Any]
) -> dict[str, Any]:
    """All three clauses, and the verdict the protocol reads once."""

    clauses = {
        "accuracy": bool(accuracy["passes"]),
        "ordering": bool(ordering["passes"]),
        "decision": bool(decision["passes"]),
    }
    passes = all(clauses.values())
    return {
        "clauses": clauses,
        "passes": passes,
        "verdict": "passes" if passes else "fails",
        "failing_clauses": sorted(name for name, value in clauses.items() if not value),
    }


def calibration_by_decile(
    probability: "pd.Series[Any]", outcome: "pd.Series[Any]"
) -> tuple[dict[str, object], ...]:
    """Ten equal-count cells of the clean-sheet probability, predicted against realized."""

    values = pd.to_numeric(probability, errors="coerce")
    outcomes = pd.to_numeric(outcome, errors="coerce")
    paired = pd.DataFrame({"probability": values, "outcome": outcomes}).dropna()
    if paired.empty:
        return ()
    ranked = paired["probability"].rank(method="first")
    cells = (ranked * 10 / (len(paired) + 1)).astype("int64").clip(upper=9)
    rows: list[dict[str, object]] = []
    for index in range(10):
        held = paired.loc[cells == index]
        rows.append(
            {
                "decile": index + 1,
                "rows": len(held),
                "mean_predicted": None if held.empty else float(held["probability"].mean()),
                "realized_rate": None if held.empty else float(held["outcome"].mean()),
            }
        )
    return tuple(rows)


__all__ = [
    "CLEAN_SHEET_POINTS",
    "DEFENCE_POSITIONS",
    "FIRST_TARGET_GAMEWEEK",
    "JUDGED_SEASONS",
    "LONG_MINUTES",
    "MAXIMUM_LOSING_SEASONS",
    "MINIMUM_TRAINING_ROWS",
    "ORDERING_REPRESENTATION_GUARD",
    "ORDERING_TOLERANCE",
    "POSITIONAL_DEFENCE_CONTRACT_VERSION",
    "PopulationCounts",
    "accuracy_clause",
    "bonus_by_position",
    "calibration_by_decile",
    "candidate_points",
    "club_codes",
    "decision_clause",
    "eligible_rows",
    "long_indicator",
    "mean_absolute_error",
    "ordering_clause",
    "positional_defence_gate",
    "realized_bonus",
    "training_row_counts",
    "within_position_rank",
]
