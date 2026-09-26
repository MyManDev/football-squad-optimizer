"""Does the availability rule cut the same risk twice?

    python -m scripts.measure_double_reduction --fitted <fitted.csv> --dry-run
    python -m scripts.measure_double_reduction --fitted <fitted.csv>

`apply_availability` multiplies a player's expected points by a factor derived from the
captured status and chance of playing. The component path's expected points is already an
appearance probability times points-given-appearance. For a player who is injured **this
week** the two come from different sources and there is no double count: the fitted
probability has not seen the news and the multiplier is exactly the correction.

The player this measurement is about is the one who has been out for three weeks and is
still flagged doubtful. His rolling appearance rate has already fallen, so the fitted
probability is low before the multiplier lands on it. That is the same risk cut twice, and
the size of it is what this reports.

**What is measured, and against what.** For every player whose pre-deadline availability was
below full, the fitted appearance probability the week actually used, beside the appearance
that actually happened, split by how many of the recent settled weeks the player missed. If
the fitted probability already matches the realised rate for the long-absent group, then
whatever the multiplier takes off on top of it is taken off twice.

**It accumulates; it does not wait.** One settled gameweek arrives per week from GW4 onward,
and a measurement that needed a sample size arriving in December would report nothing until
then. So this runs on whatever the record holds, states how many weeks and rows that is, and
**refuses to characterise a bucket that is too thin to characterise** rather than printing a
mean over four players. Re-run it every week; the sentence it writes about what it supports
is generated from the record, not typed.

**The fitted probability arrives as a declared input, and the reason is worth stating.**
Nothing on disk records it today: ``write_projection_handoff`` writes ``expected_points`` per
player and no component, and ``projection_handoff.build`` narrows the component snapshot to
``player_id`` and ``expected_points`` before anything is written. The only production caller
that keeps the components is ``scripts/_phase_e_live``, through ``include_components=True`` on
a private producer function, after checking the rebuild against the week's own handoff
fingerprint.

So this command takes ``--fitted``: one CSV with ``season, gameweek, player_id,
fitted_appearance_probability``, and it refuses to guess one. Reproducing ``build``'s body
here to manufacture it would duplicate the largest runner in the repository at the moment
#554 is removing duplication, and the alternative -- teaching ``build`` to hand its components
back -- is a change to a production signature on somebody else's path, which is a decision and
not a convenience. Either way the numbers must be **the week's own**: a re-fit today, with
more history than the week had, answers a different question than the one asked.

Nothing here promotes anything, changes any control, or reads the locked holdout. It reports
whether a correction is applied twice; what to do about it is a separate decision.
"""

import argparse
import hashlib
import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import pandas as pd
from scripts._experiment_cli import (
    REPOSITORY_ROOT,
    repository_provenance,
    write_json,
    write_text,
)

from squadopt.data.errors import DataSourceError
from squadopt.features.settled_outcomes import read_settled_outcomes_artifact

CONTRACT_VERSION: Final = "double_reduction_v1"

#: How many settled weeks back "recently" reaches. Three, because that is the case the
#: question names -- "out for three weeks and still flagged doubtful" -- and because a window
#: the record cannot fill yet would report nothing rather than something narrow.
RECENCY_WINDOW: Final = 3

#: Below this, a bucket is named and counted and **not** characterised. A mean appearance rate
#: over a handful of players is a number with no reading, and printing one beside the others
#: invites exactly the comparison it cannot support.
MINIMUM_BUCKET_ROWS: Final = 30

#: The rule this measurement is about applies to players the capture priced below full.
FULL_AVAILABILITY: Final = 1.0

DEFAULT_RECORD: Final = Path("docs/double_reduction.json")
DEFAULT_SUMMARY: Final = Path("docs/double_reduction.md")
DEFAULT_OUTCOMES_DIR: Final = Path("artifacts") / "settled_outcomes"


@dataclass(frozen=True, slots=True)
class WeekInputs:
    """One settled week, its realised outcomes and the probability its decision used."""

    season: str
    gameweek: int
    outcomes: pd.DataFrame
    fitted: pd.Series
    fitted_source: str


def recent_absences(prior_weeks: Sequence[pd.DataFrame], window: int = RECENCY_WINDOW) -> pd.Series:
    """How many of the last ``window`` settled weeks each player was absent from.

    Absent means the settled capture recorded no appearance, which is the same column the
    outcome side of this measurement reads. A player the record has fewer than ``window``
    weeks for is counted over the weeks it has, and the reading says so: the bucket is "missed
    two of the two weeks we hold", not "missed two of three".
    """

    if not prior_weeks:
        return pd.Series(dtype="int64")
    recent = list(prior_weeks)[-window:]
    counts: dict[int, int] = {}
    for week in recent:
        appeared = week.set_index("player_id")["appearance"]
        for player, value in appeared.items():
            key = int(str(player))
            counts.setdefault(key, 0)
            if value is pd.NA or not bool(value):
                counts[key] += 1
    return pd.Series(counts, dtype="int64").sort_index()


def _bucket_reading(frame: pd.DataFrame) -> dict[str, object]:
    """One recency bucket, characterised only if it is thick enough to characterise."""

    rows = len(frame)
    reading: dict[str, object] = {"rows": rows}
    if rows < MINIMUM_BUCKET_ROWS:
        reading["read"] = False
        reading["reason"] = f"fewer than {MINIMUM_BUCKET_ROWS} rows"
        return reading
    per_player_fitted = frame["fitted_appearance_probability"].astype("float64")
    per_player_multiplier = frame["pre_deadline_availability_multiplier"].astype("float64")
    fitted = float(per_player_fitted.mean())
    realised = float(frame["appearance"].astype("float64").mean())
    multiplier = float(per_player_multiplier.mean())
    reading.update(
        {
            "read": True,
            "fitted_appearance_probability": fitted,
            "realised_appearance_rate": realised,
            # Near zero means the fitted probability has already absorbed the absence, which
            # is the condition under which the multiplier is a second cut of one risk.
            "calibration_gap": fitted - realised,
            "availability_multiplier": multiplier,
            # What the multiplier removes on top, in probability units, averaged over the
            # players: each player's fitted probability times one minus his own multiplier.
            # Not the bucket's mean fitted times one minus its mean multiplier, because the
            # two covary (the players the capture cuts hardest are not a random draw), and
            # the product of the means then misstates what happened to these players. It is
            # double counting to the extent the gap above is zero.
            "further_reduction": float((per_player_fitted * (1.0 - per_player_multiplier)).mean()),
            # What is left after both cuts, per player and averaged, so it can be read beside
            # the realised appearance rate.
            "after_multiplier_appearance_probability": float(
                (per_player_fitted * per_player_multiplier).mean()
            ),
        }
    )
    return reading


def measure_double_reduction(weeks: Sequence[WeekInputs]) -> dict[str, object]:
    """The whole reading: the compounding question, answered over whatever has settled.

    The population is declared here rather than filtered by the caller: every row whose
    pre-deadline availability was recorded and below full. A player the pre-deadline capture
    never listed carries no availability and is **not** treated as fully available, which is
    the same rule the settled-outcome table holds to.
    """

    rows: list[pd.DataFrame] = []
    settled: list[dict[str, object]] = []
    history: list[pd.DataFrame] = []
    for week in weeks:
        absences = recent_absences(history)
        frame = week.outcomes.copy(deep=True)
        frame["fitted_appearance_probability"] = frame["player_id"].map(week.fitted)
        frame["recent_weeks_missed"] = frame["player_id"].map(absences)
        frame["recent_weeks_held"] = min(len(history), RECENCY_WINDOW)
        history.append(week.outcomes)
        below_full = frame["pre_deadline_availability_multiplier"].notna() & (
            frame["pre_deadline_availability_multiplier"] < FULL_AVAILABILITY
        )
        priced = frame.loc[below_full & frame["fitted_appearance_probability"].notna()]
        settled.append(
            {
                "season": week.season,
                "gameweek": week.gameweek,
                "rows": len(frame),
                "priced_below_full": len(priced),
                # Priced below full with no fitted probability (a player the component route
                # did not model): counted here and left out, never read as a zero.
                "below_full_without_fitted_probability": int(
                    (below_full & frame["fitted_appearance_probability"].isna()).sum()
                ),
                "recent_weeks_held": int(min(len(history) - 1, RECENCY_WINDOW)),
                "fitted_source": week.fitted_source,
            }
        )
        rows.append(priced)

    population = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame(columns=["player_id"])
    buckets: dict[str, object] = {}
    if not population.empty:
        known = population.loc[population["recent_weeks_missed"].notna()]
        for missed, frame in known.groupby(known["recent_weeks_missed"].astype("int64")):
            buckets[str(int(missed))] = _bucket_reading(frame)
        unknown = population.loc[population["recent_weeks_missed"].isna()]
        if len(unknown):
            buckets["no_prior_weeks"] = {
                "rows": len(unknown),
                "read": False,
                "reason": "the record holds no settled week before this one",
            }
    return {
        "artifact_type": "record",
        "contract_version": CONTRACT_VERSION,
        "question": (
            "Do the fitted appearance probability and the availability multiplier reduce the "
            "same risk twice?"
        ),
        "recency_window": RECENCY_WINDOW,
        "minimum_bucket_rows": MINIMUM_BUCKET_ROWS,
        "settled_weeks": settled,
        "population_rows": len(population),
        "by_recent_weeks_missed": buckets,
        "supports": _supports(settled, buckets),
        "promotes": None,
    }


def _supports(settled: Sequence[Mapping[str, object]], buckets: Mapping[str, object]) -> str:
    """What this much record can carry, written from the record rather than by hand."""

    weeks = len(settled)
    if weeks == 0:
        return "No settled week has both captures, so nothing is measured yet."
    readable = [
        name for name, value in buckets.items() if isinstance(value, dict) and value.get("read")
    ]
    if not readable:
        thickest = max(
            (
                int(str(value.get("rows", 0)))
                for value in buckets.values()
                if isinstance(value, dict)
            ),
            default=0,
        )
        return (
            f"{weeks} settled week(s) and no bucket reaches {MINIMUM_BUCKET_ROWS} rows "
            f"(the thickest holds {thickest}). The compounding question is not answered yet, "
            "and the counts above are counts rather than evidence."
        )
    if len(readable) < 2:
        return (
            f"{weeks} settled week(s). One bucket ({readable[0]}) is thick enough to read, "
            "which gives a level and not a contrast: the question is whether the gap differs "
            "between recently absent players and present ones, and that needs two."
        )
    return (
        f"{weeks} settled week(s), {len(readable)} buckets thick enough to read. The gaps "
        "below can be compared across recency; whether the difference is stable is a question "
        "for more weeks, and this record will answer it by being re-run rather than re-scoped."
    )


def _summary(record: Mapping[str, object]) -> str:
    lines = [
        "# Double reduction: is one risk cut twice?",
        "",
        str(record["question"]),
        "",
        f"**What this much record supports.** {record['supports']}",
        "",
        "| Settled week | Rows | Priced below full, read | Below full, no fitted value "
        "| Earlier weeks held | Fitted source |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    settled = record["settled_weeks"]
    assert isinstance(settled, list)
    for week in settled:
        assert isinstance(week, dict)
        lines.append(
            f"| {week['season']} GW{int(week['gameweek']):02d} | {week['rows']} | "
            f"{week['priced_below_full']} | "
            f"{week.get('below_full_without_fitted_probability', 'n/a')} | "
            f"{week['recent_weeks_held']} | `{week['fitted_source']}` |"
        )
    lines += [
        "",
        "| Recent weeks missed | Rows | Fitted P(appearance) | Realised rate | Gap "
        "| Multiplier | Further reduction | Left after the multiplier |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    buckets = record["by_recent_weeks_missed"]
    assert isinstance(buckets, dict)
    for name, value in buckets.items():
        assert isinstance(value, dict)
        if not value.get("read"):
            lines.append(f"| {name} | {value['rows']} | not read: {value['reason']} | | | | | |")
            continue
        lines.append(
            f"| {name} | {value['rows']} | {float(value['fitted_appearance_probability']):.4f} | "
            f"{float(value['realised_appearance_rate']):.4f} | "
            f"{float(value['calibration_gap']):+.4f} | "
            f"{float(value['availability_multiplier']):.4f} | "
            f"{float(value['further_reduction']):.4f} | "
            f"{float(value['after_multiplier_appearance_probability']):.4f} |"
        )
    lines += [
        "",
        "Fitted, realised, gap and multiplier are bucket means. Further reduction is the mean "
        "over the bucket's players of each one's fitted probability times one minus his own "
        "multiplier, and the last column is the mean of fitted times multiplier: what the "
        "projection carried after both cuts, to read beside the realised rate. Neither is the "
        "product of the bucket means, because the players the capture cuts hardest do not "
        "carry the bucket's average fitted probability.",
        "",
        "A gap near zero means the fitted probability has already absorbed the absence, and "
        "whatever the multiplier removes on top of it is removed twice. A gap that is large "
        "and positive means the fitted probability had not seen the news and the multiplier is "
        "the correction it is meant to be.",
        "",
        "Promotes nothing, changes no control, publishes no probability to a member.",
    ]
    return "\n".join(lines) + "\n"


def _parse_arguments(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--outcomes-dir", type=Path, default=REPOSITORY_ROOT / DEFAULT_OUTCOMES_DIR)
    parser.add_argument(
        "--fitted",
        type=Path,
        required=True,
        help="CSV of the appearance probabilities the weeks actually used: season, gameweek, "
        "player_id, fitted_appearance_probability",
    )
    parser.add_argument("--json-output", type=Path, default=REPOSITORY_ROOT / DEFAULT_RECORD)
    parser.add_argument("--markdown-output", type=Path, default=REPOSITORY_ROOT / DEFAULT_SUMMARY)
    parser.add_argument("--dry-run", action="store_true", help="report, write nothing")
    return parser.parse_args(argv)


def collect_weeks(outcomes_dir: Path, fitted_path: Path) -> list[WeekInputs]:
    """Every settled week on disk, in gameweek order, joined to its own fitted probabilities.

    A settled week whose fitted probabilities are not in the supplied file is **refused**, not
    skipped: a measurement that silently drops the weeks it cannot explain reports a population
    nobody declared.
    """

    fitted = pd.read_csv(fitted_path)
    expected = {"season", "gameweek", "player_id", "fitted_appearance_probability"}
    missing = sorted(expected - set(fitted.columns))
    if missing:
        raise ValueError(f"{fitted_path.name} is missing columns {missing!r}.")

    weeks: list[WeekInputs] = []
    for table_path in sorted(Path(outcomes_dir).glob("*.csv")):
        manifest_path = table_path.with_suffix(".manifest.json")
        if not manifest_path.is_file():
            raise ValueError(
                f"No manifest beside {table_path.name}: expected {manifest_path.name}."
            )
        outcomes = read_settled_outcomes_artifact(table_path, manifest_path)
        season = str(outcomes["season"].iloc[0])
        gameweek = int(outcomes["gameweek"].iloc[0])
        rows = fitted.loc[
            (fitted["season"].astype("string") == season)
            & (fitted["gameweek"].astype("int64") == gameweek)
        ]
        if rows.empty:
            raise ValueError(
                f"{fitted_path.name} carries no appearance probabilities for {season} "
                f"GW{gameweek:02d}, which {table_path.name} settles."
            )
        weeks.append(
            WeekInputs(
                season=season,
                gameweek=gameweek,
                outcomes=outcomes,
                fitted=rows.set_index("player_id")["fitted_appearance_probability"],
                fitted_source=str(fitted_path.name),
            )
        )
    return sorted(weeks, key=lambda week: (week.season, week.gameweek))


def main(argv: list[str] | None = None) -> int:
    arguments = _parse_arguments(argv)
    try:
        weeks = collect_weeks(arguments.outcomes_dir, arguments.fitted)
    except (DataSourceError, OSError, ValueError) as error:
        print(f"Refused: {error}")
        return 1

    record = measure_double_reduction(weeks)
    print(json.dumps(record["supports"])[1:-1])
    buckets = record["by_recent_weeks_missed"]
    assert isinstance(buckets, dict)
    for name, value in buckets.items():
        assert isinstance(value, dict)
        if value.get("read"):
            print(
                f"  missed {name:>3}  rows {value['rows']:>5}  fitted "
                f"{float(value['fitted_appearance_probability']):.4f}  realised "
                f"{float(value['realised_appearance_rate']):.4f}  gap "
                f"{float(value['calibration_gap']):+.4f}"
            )
        else:
            print(f"  missed {name:>3}  rows {value['rows']:>5}  not read: {value['reason']}")
    if arguments.dry_run:
        print("Dry run: nothing written.")
        return 0
    # Which code wrote the record, and which bytes of the declared input it read: the file
    # name alone does not say whether the probabilities were the week's own.
    record["provenance"] = repository_provenance()
    record["fitted_sha256"] = hashlib.sha256(arguments.fitted.read_bytes()).hexdigest()
    write_json(arguments.json_output, record)
    write_text(arguments.markdown_output, _summary(record))
    print(f"Wrote {arguments.json_output} and {arguments.markdown_output}")
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through main
    sys.exit(main())


__all__ = [
    "CONTRACT_VERSION",
    "MINIMUM_BUCKET_ROWS",
    "RECENCY_WINDOW",
    "WeekInputs",
    "collect_weeks",
    "main",
    "measure_double_reduction",
    "recent_absences",
]
