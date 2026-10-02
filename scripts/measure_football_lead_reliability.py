"""Measure how much the served football forecast loses per week of lead; nothing is tuned.

    python -m scripts.measure_football_lead_reliability check --archive <archive root>
    python -m scripts.measure_football_lead_reliability measure --archive <archive root> \\
        --repository-commit <sha> --output <fresh directory>

Protocol: ``docs/football_lead_reliability_prereg.md``. The served model,
``football_team_share_v1``, is fitted at each origin's decision instant and forecasts up to
fourteen weeks on the archive's final calendar. Each forecast at lead k is set beside the
same player-fixture's lead-1 forecast, and the paired difference in squared error is the
primary quantity. The archive is read only through ``archive_history`` with the protocol's
three seasons, and ``check`` hashes only their files, so 2025-26 is never opened.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final

import pandas as pd

from squadopt.application.football_live import causal_training
from squadopt.data.atomic import write_document_once
from squadopt.data.errors import DataError
from squadopt.data.sources.football_history import archive_history
from squadopt.evaluation.promotion import PromotionPolicy
from squadopt.evaluation.statistics import season_aware_moving_block_interval
from squadopt.live.football_horizon import build_football_horizon
from squadopt.prediction.football import FOOTBALL_MODEL_VERSION, FixtureFootballModel

CONTRACT_VERSION: Final = "football_lead_reliability_v1"
PROTOCOL: Final = "docs/football_lead_reliability_prereg.md"
#: The archive seasons read, the two of them evaluated, and the one never opened.
SELECTED_SEASONS: Final = ("2022-23", "2023-24", "2024-25")
EVALUATED_SEASONS: Final = ("2023-24", "2024-25")
NEVER_OPENED: Final = ("2025-26",)
MEASURED_ORIGINS: Final = (11, 15, 19, 23, 27, 31)
#: Every gameweek from GW11 forecasts its own week, for the lead-1 side of the pairs only.
LEAD_ONE_ORIGINS: Final = tuple(range(11, 39))
MAX_LEAD: Final = 14
LAST_GAMEWEEK: Final = 38
DECISION_BEFORE_KICKOFF: Final = pd.Timedelta(minutes=90)
SETTLED_AFTER_KICKOFF: Final = pd.Timedelta(hours=3)
ROSTER_WEEKS_BEFORE: Final = 2
#: Below this many target gameweeks a lead's interval is reported and marked thin.
THIN_UNITS: Final = 6
TOP_FORECASTS: Final = 10
KEYS: Final = ["season", "fixture", "player_code"]
ARCHIVE_FILES: Final = ("gws/merged_gw.csv", "players_raw.csv", "teams.csv", "fixtures.csv")
#: The columns the roster rule and the calendar name, confirmed before anything is fitted.
REQUIRED_COLUMNS: Final[Mapping[str, tuple[str, ...]]] = {
    "gws/merged_gw.csv": (
        "name",
        "team",
        "position",
        "value",
        "element",
        "fixture",
        "GW",
        "kickoff_time",
        "total_points",
        "was_home",
    ),
    "players_raw.csv": ("id", "code"),
    "teams.csv": ("id", "code"),
    "fixtures.csv": ("id", "event", "kickoff_time", "team_h", "team_a"),
}
#: Stated explicitly, as the protocol requires, rather than inherited from the defaults.
POLICY: Final = PromotionPolicy(
    confidence_level=0.90,
    bootstrap_resamples=5000,
    moving_block_length=4,
    deterministic_seed=0,
)
REPOSITORY_ROOT: Final = Path(__file__).resolve().parents[1]


class LeadReliabilityRefusal(ValueError):
    """A run the protocol does not allow, refused before anything is written."""


def _number(value: object) -> float | None:
    """A finite float for the record, or None: the record carries no NaN."""
    number = float(value)  # type: ignore[arg-type]
    return number if math.isfinite(number) else None


def origin_weeks(origin: int, *, last: int = LAST_GAMEWEEK) -> tuple[int, ...]:
    """The gameweeks a measured origin forecasts: fourteen, or fewer at the season's end."""
    return tuple(range(origin, min(origin + MAX_LEAD - 1, last) + 1))


def decision_instant(history: pd.DataFrame, season: str, week: int) -> pd.Timestamp:
    """The earliest kickoff of the origin's own archive rows, less 90 minutes."""
    kickoffs = history.loc[history.season.eq(season) & history.GW.eq(week), "kickoff"]
    if kickoffs.empty:
        raise LeadReliabilityRefusal(f"{season} GW{week} has no archive rows to time it by.")
    return pd.Timestamp(kickoffs.min()) - DECISION_BEFORE_KICKOFF


def settled(frame: pd.DataFrame, instant: pd.Timestamp) -> pd.DataFrame:
    """The rows whose kickoff is more than three hours before ``instant``."""
    return frame.loc[frame.kickoff + SETTLED_AFTER_KICKOFF < instant]


def roster_at(
    history: pd.DataFrame, season: str, origin: int, instant: pd.Timestamp
) -> pd.DataFrame:
    """Who an origin forecasts: a settled row in either of the two weeks before it.

    The player's latest such row gives his club, position, name, team and price. Nothing
    after the decision instant decides who is in the roster, so a player who arrives later
    is absent and one who leaves stays, his later fixtures unmatched and counted.
    """
    weeks = range(origin - ROSTER_WEEKS_BEFORE, origin)
    rows = settled(history.loc[history.season.eq(season) & history.GW.isin(weeks)], instant)
    absent = [column for column in ("name", "team", "value") if column not in rows]
    if absent:
        raise LeadReliabilityRefusal(f"The archive rows lack the roster columns {absent}.")
    if rows.empty:
        raise LeadReliabilityRefusal(
            f"{season} GW{origin} has no settled row in the two weeks before it."
        )
    latest = (
        rows.sort_values(["kickoff", "GW", "fixture"], kind="stable")
        .groupby("player_code", sort=True)
        .tail(1)
    )
    roster = pd.DataFrame(
        {
            "player_id": latest.player_code.astype("int64"),
            "name": latest["name"].astype(str),
            "team_id": latest.team.astype(str),
            "position": latest.position.astype(str),
            "price_tenths": latest.value.astype("int64"),
            "club": latest.club,
        }
    )
    return roster.sort_values("player_id", kind="stable").reset_index(drop=True)


def final_calendar(fixtures: pd.DataFrame, teams: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """The archive's final calendar, one row per side; a fixture with no event is dropped."""
    scheduled = fixtures.loc[fixtures.event.notna()]
    clubs = teams.set_index("id").code
    sides = [
        pd.DataFrame(
            {
                "fixture": scheduled.id,
                "club": scheduled["team_h" if home else "team_a"].map(clubs),
                "opponent": scheduled["team_a" if home else "team_h"].map(clubs),
                "home": float(home),
                "GW": scheduled.event.astype("int64"),
                "kickoff": pd.to_datetime(scheduled.kickoff_time, utc=True),
            }
        )
        for home in (True, False)
    ]
    return pd.concat(sides, ignore_index=True), len(fixtures) - len(scheduled)


def irregular_weeks(calendar: pd.DataFrame) -> list[int]:
    """The gameweeks in which some club plays other than once: a blank or a double."""
    counts = calendar.groupby(["GW", "club"]).size().unstack(fill_value=0)
    counts = counts.reindex(columns=sorted(calendar.club.unique()), fill_value=0)
    return sorted(int(week) for week, row in counts.iterrows() if bool((row != 1).any()))


def forecast_origin(
    training: pd.DataFrame,
    history: pd.DataFrame,
    calendar: pd.DataFrame,
    *,
    season: str,
    origin: int,
    weeks: Sequence[int],
) -> tuple[pd.DataFrame, pd.Timestamp, int]:
    """Fit the served model at one origin's decision instant and forecast its weeks."""
    instant = decision_instant(history, season, origin)
    past = settled(history, instant)
    roster = roster_at(history, season, origin, instant)
    model = FixtureFootballModel(settled(training, instant), past, cutoff=instant)
    _, parts = build_football_horizon(
        model,
        past,
        roster,
        calendar,
        gameweeks=tuple(weeks),
        season=season,
        source_snapshot_id=f"development-final-calendar-{season}-gw{origin:02d}",
        captured_at=instant,
    )
    if parts.empty:
        forecast = pd.DataFrame(columns=[*KEYS, "GW", "position", "expected_points"])
    else:
        forecast = parts.loc[:, [*KEYS, "GW", "position", "expected_points"]].copy()
    forecast["origin"] = origin
    forecast["lead"] = forecast.GW.astype("int64") - origin + 1
    return forecast, instant, len(roster)


def with_outcomes(forecast: pd.DataFrame, history: pd.DataFrame) -> pd.DataFrame:
    """Each forecast beside its realized points; an unmatched one stays unknown, never zero."""
    realized = history.loc[:, [*KEYS, "total_points"]]
    labelled = forecast.merge(realized, on=KEYS, how="left", validate="many_to_one")
    labelled["error"] = labelled.expected_points - labelled.total_points
    return labelled


def _irregular(frame: pd.DataFrame, irregular: Mapping[str, Sequence[int]]) -> pd.Series:
    weeks = {(season, int(week)) for season, values in irregular.items() for week in values}
    return pd.Series(
        [(str(s), int(g)) in weeks for s, g in zip(frame.season, frame.GW, strict=True)],
        index=frame.index,
        dtype=bool,
    )


def paired_differences(
    labelled: pd.DataFrame,
    *,
    measured: Sequence[int],
    irregular: Mapping[str, Sequence[int]],
) -> pd.DataFrame:
    """Each matched lead-k forecast of a measured origin beside the same lead-1 forecast.

    A target gameweek with a blank or a double for any club is kept apart, so it is not
    paired here.
    """
    matched = labelled.loc[labelled.error.notna()]
    later = matched.loc[matched.origin.isin(measured) & matched.lead.ge(2)]
    first = matched.loc[matched.lead.eq(1), [*KEYS, "error"]].rename(columns={"error": "error_1"})
    pairs = later.merge(first, on=KEYS, how="inner", validate="many_to_one")
    pairs = pairs.loc[~_irregular(pairs, irregular)].copy()
    pairs["difference"] = pairs.error**2 - pairs.error_1**2
    return pairs


def lead_figures(pairs: pd.DataFrame, *, policy: PromotionPolicy = POLICY) -> list[dict[str, Any]]:
    """Per lead: the mean over target gameweeks of the mean paired difference, and its interval.

    The units of each season are ordered by target gameweek, because the interval resamples
    blocks of neighbouring units within a season.
    """
    figures: list[dict[str, Any]] = []
    for lead in range(2, MAX_LEAD + 1):
        rows = pairs.loc[pairs.lead.eq(lead)]
        units = rows.groupby(["season", "GW"], sort=True).difference.mean().reset_index()
        entry: dict[str, Any] = {
            "lead": lead,
            "pairs": len(rows),
            "units": len(units),
            "thin": len(units) < THIN_UNITS,
            "mean_squared_error": _number((rows.error**2).mean()) if len(rows) else None,
            "mean_squared_error_lead_1": _number((rows.error_1**2).mean()) if len(rows) else None,
            "mean_difference": None,
            "interval": None,
        }
        if len(units):
            entry["mean_difference"] = _number(units.difference.mean())
            low, high = season_aware_moving_block_interval(
                [(str(s), float(v)) for s, v in zip(units.season, units.difference, strict=True)],
                policy=policy,
                candidate_id=f"lead_{lead}",
            )
            entry["interval"] = [_number(low), _number(high)]
        figures.append(entry)
    return figures


def descriptive(labelled: pd.DataFrame, *, measured: Sequence[int]) -> list[dict[str, Any]]:
    """By lead, over the measured origins' matched forecasts; no figure here is a gate."""
    rows: list[dict[str, Any]] = []
    frame = labelled.loc[labelled.error.notna() & labelled.origin.isin(measured)]
    for lead, group in frame.groupby("lead", sort=True):
        forecast, realized = group.expected_points, group.total_points
        variance = float(forecast.var(ddof=0))
        slope = (
            _number(((forecast - forecast.mean()) * (realized - realized.mean())).mean() / variance)
            if variance > 0
            else None
        )
        top = (
            group.sort_values("expected_points", ascending=False, kind="stable")
            .groupby(["season", "origin", "GW", "position"], sort=True)
            .head(TOP_FORECASTS)
        )
        rows.append(
            {
                "lead": int(str(lead)),
                "matched": len(group),
                "mean_signed_error": _number(group.error.mean()),
                "slope_realized_on_forecast": slope,
                "spearman_by_position": {
                    str(position): (
                        _number(part.expected_points.corr(part.total_points, method="spearman"))
                        if len(part) > 1
                        else None
                    )
                    for position, part in group.groupby("position", sort=True)
                },
                "top_ten_optimism": _number((top.expected_points - top.total_points).mean()),
            }
        )
    return rows


def counts(labelled: pd.DataFrame, pairs: pd.DataFrame) -> list[dict[str, Any]]:
    """Forecast, matched, unmatched and paired player-fixtures, by origin and lead."""
    paired = pairs.groupby(["season", "origin", "lead"]).size()
    rows: list[dict[str, Any]] = []
    for (season, origin, lead), group in labelled.groupby(["season", "origin", "lead"], sort=True):
        matched = int(group.error.notna().sum())
        rows.append(
            {
                "season": str(season),
                "origin": int(str(origin)),
                "lead": int(str(lead)),
                "forecast": len(group),
                "matched": matched,
                "unmatched": len(group) - matched,
                "paired": int(paired.get((season, origin, lead), 0)),
            }
        )
    return rows


def measure_frames(
    history: pd.DataFrame,
    training: pd.DataFrame,
    calendars: Mapping[str, pd.DataFrame],
    *,
    seasons: Sequence[str] = EVALUATED_SEASONS,
    measured: Sequence[int] = MEASURED_ORIGINS,
    lead_one: Sequence[int] = LEAD_ONE_ORIGINS,
    last: int = LAST_GAMEWEEK,
) -> tuple[dict[str, Any], pd.DataFrame]:
    """Every origin of every evaluated season, then the protocol's quantities.

    An origin is forecast once: a measured origin over its weeks, any other lead-1 origin
    over its own week. A failed origin is recorded with its error and never rerun.
    """
    forecasts: list[pd.DataFrame] = []
    origins: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for season in seasons:
        for origin in sorted(set(measured) | set(lead_one)):
            weeks = origin_weeks(origin, last=last) if origin in measured else (origin,)
            try:
                forecast, instant, players = forecast_origin(
                    training, history, calendars[season], season=season, origin=origin, weeks=weeks
                )
            except Exception as error:  # the protocol records a failed origin, never retries it
                failures.append(
                    {
                        "season": season,
                        "origin": origin,
                        "error": f"{type(error).__name__}: {error}",
                    }
                )
                continue
            forecasts.append(forecast)
            origins.append(
                {
                    "season": season,
                    "origin": origin,
                    "measured": origin in measured,
                    "gameweeks": [weeks[0], weeks[-1]],
                    "decision_instant": instant.isoformat(),
                    "roster_players": players,
                }
            )
    if forecasts:
        labelled = with_outcomes(pd.concat(forecasts, ignore_index=True), history)
    else:
        labelled = with_outcomes(
            pd.DataFrame(columns=[*KEYS, "GW", "position", "expected_points", "origin", "lead"]),
            history,
        )
    irregular = {season: irregular_weeks(calendars[season]) for season in seasons}
    pairs = paired_differences(labelled, measured=measured, irregular=irregular)
    later = labelled.loc[labelled.origin.isin(measured) & labelled.lead.ge(2)]
    kept_apart = later.loc[_irregular(later, irregular)]
    record: dict[str, Any] = {
        "contract_version": CONTRACT_VERSION,
        "protocol": PROTOCOL,
        "model_version": FOOTBALL_MODEL_VERSION,
        "seasons_loaded": list(SELECTED_SEASONS),
        "seasons_evaluated": list(seasons),
        "seasons_never_opened": list(NEVER_OPENED),
        "locked_holdout_accessed": False,
        "measured_origins": list(measured),
        "lead_one_origins": list(lead_one),
        "policy": {
            "confidence_level": POLICY.confidence_level,
            "bootstrap_resamples": POLICY.bootstrap_resamples,
            "moving_block_length": POLICY.moving_block_length,
            "deterministic_seed": POLICY.deterministic_seed,
            "thin_below_units": THIN_UNITS,
        },
        "calendar": "the archive's final calendar, not a deadline snapshot",
        "roster": "settled rows of the two gameweeks before each origin, not a deadline snapshot",
        "rescheduled_fixtures": (
            "not identifiable in the archive; the primary quantity may contain them"
        ),
        "irregular_gameweeks": irregular,
        "origins": origins,
        "failed_origins": failures,
        "primary": lead_figures(pairs),
        "kept_apart_irregular": {
            str(lead): int(size) for lead, size in kept_apart.groupby("lead").size().items()
        },
        "secondary": descriptive(labelled, measured=measured),
        "counts": counts(labelled, pairs),
    }
    return record, labelled


def check(archive: Path) -> dict[str, str]:
    """Hash the selected seasons' files and confirm the columns the protocol names."""
    hashes: dict[str, str] = {}
    missing: list[str] = []
    for season in SELECTED_SEASONS:
        for name in ARCHIVE_FILES:
            path = archive / "data" / season / name
            if not path.is_file():
                raise LeadReliabilityRefusal(f"The archive has no {season}/{name}.")
            hashes[f"{season}/{name}"] = hashlib.sha256(path.read_bytes()).hexdigest()
            header = set(pd.read_csv(path, nrows=0).columns)
            absent = [column for column in REQUIRED_COLUMNS[name] if column not in header]
            if absent:
                missing.append(f"{season}/{name} lacks {', '.join(absent)}")
    if missing:
        raise LeadReliabilityRefusal("Stopped before any fit: " + "; ".join(missing) + ".")
    return hashes


def _refuse_destination(output: Path, archive: Path) -> None:
    """The record goes into a fresh directory of the operator's, never into the inputs."""
    target = output.resolve()
    for forbidden, why in (
        (archive.resolve(), "inside the archive"),
        ((REPOSITORY_ROOT / "data").resolve(), "under the repository's data/"),
        ((REPOSITORY_ROOT / "docs").resolve(), "under the repository's docs/"),
    ):
        if target == forbidden or forbidden in target.parents:
            raise LeadReliabilityRefusal(f"Refusing to write {why}: {output}.")
    if output.exists():
        raise LeadReliabilityRefusal(f"Output directory already exists: {output}.")


def summary(record: Mapping[str, Any]) -> str:
    """The record's primary table and its limits, for the reading's pull request."""

    def shown(value: object) -> str:
        return "" if value is None else f"{float(value):.4f}"  # type: ignore[arg-type]

    lines = [
        "# Football forecast reliability by lead",
        "",
        f"Model `{record['model_version']}`, seasons {', '.join(record['seasons_evaluated'])}, "
        f"protocol `{record['protocol']}`. 2025-26 was not opened.",
        "",
        "| lead | units | pairs | mean e_k^2 | mean e_1^2 | mean difference | 90% interval "
        "| thin |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in record["primary"]:
        interval = row["interval"]
        bounds = "" if interval is None else f"[{shown(interval[0])}, {shown(interval[1])}]"
        lines.append(
            f"| {row['lead']} | {row['units']} | {row['pairs']} | "
            f"{shown(row['mean_squared_error'])} | {shown(row['mean_squared_error_lead_1'])} | "
            f"{shown(row['mean_difference'])} | {bounds} | {'yes' if row['thin'] else 'no'} |"
        )
    if record["failed_origins"]:
        lines += ["", "Failed origins, recorded and not rerun:"]
        lines += [
            f"- {f['season']} GW{f['origin']}: {f['error']}" for f in record["failed_origins"]
        ]
    lines += [
        "",
        "The calendar and the roster are reconstructed from the archive, not deadline",
        "snapshots. Rescheduled fixtures cannot be told apart. Nothing here chooses a horizon.",
    ]
    return "\n".join(lines) + "\n"


def run(archive: Path, output: Path, *, repository_commit: str) -> dict[str, Any]:
    """Check, measure, then create the directory, so a refusal leaves nothing behind."""
    _refuse_destination(output, archive)
    hashes = check(archive)
    history = archive_history(archive, seasons=SELECTED_SEASONS)
    training = causal_training(history)
    calendars: dict[str, pd.DataFrame] = {}
    dropped: dict[str, int] = {}
    for season in EVALUATED_SEASONS:
        base = archive / "data" / season
        calendars[season], dropped[season] = final_calendar(
            pd.read_csv(base / "fixtures.csv"), pd.read_csv(base / "teams.csv")
        )
    record, labelled = measure_frames(history, training, calendars)
    record = {
        **record,
        "repository_commit": repository_commit,
        "archive_hashes": hashes,
        "fixtures_without_event_dropped": dropped,
    }
    output.mkdir(parents=True, exist_ok=False)
    write_document_once(record, output / "record.json")
    labelled.to_csv(output / "forecasts.csv", index=False)
    (output / "summary.md").write_text(summary(record), encoding="utf-8")
    return record


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    checked = commands.add_parser("check", help="hash the selected seasons and confirm columns")
    checked.add_argument("--archive", type=Path, required=True, help="the archive root, read only")
    measured = commands.add_parser("measure", help="the protocol's one run")
    measured.add_argument("--archive", type=Path, required=True, help="the archive root, read only")
    measured.add_argument("--repository-commit", required=True, help="the commit being run")
    measured.add_argument(
        "--output", type=Path, required=True, help="a directory that must not exist yet"
    )
    arguments = parser.parse_args(argv)
    try:
        if arguments.command == "check":
            print(json.dumps({"archive_hashes": check(arguments.archive)}, indent=2))
            return 0
        result = run(
            arguments.archive, arguments.output, repository_commit=arguments.repository_commit
        )
    except (LeadReliabilityRefusal, DataError, OSError) as error:
        print(f"Refused: {error}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "origins": len(result["origins"]),
                "failed_origins": len(result["failed_origins"]),
                "leads_with_units": sum(1 for row in result["primary"] if row["units"]),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
