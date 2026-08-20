"""Fit a Dixon-Coles rating once per gameweek and record the opponent signal it implies.

    python -m scripts.build_opponent_signal

This is the input a Route A candidate would read, produced ahead of any declaration so its
coverage is a measured number rather than a hope. It produces nothing that decides anything:
no projection, no squad, no verdict.

**Why a script and not a module.** The rating lives in `squadopt.experiments.team_rating`,
which sits above `prediction/` and `backtest/` in the enforced layer order — neither may
import it, and `docs/architecture/dependency_rules.md` says the baseline may only shrink. A
script is outside `root_package`, so it may read both sides. The signal therefore reaches a
model as **data**, joined onto a feature frame, never as an upward import.

**Why not `build_opponent_rows`.** The study's own row builder starts from the control's
residual table, which restricts the population to players the control projected and skips
both the earliest season and each season's first rated gameweek. A feature has to cover the
whole training slice, including the carry-over season, so this walks the fixture calendar
instead. It also emits no `fixture_count`, which would collide with the feature frame's own.

**Grain.** One row per `(season, gameweek, club)`. That is the signal's true grain: the
rating knows about clubs, not players, and `build_opponent_rows` broadcasts to players only
because its own population is player-shaped. Broadcasting is the consumer's business.

**What has no signal, and why it does not matter.** A rating needs history, so every
season's first gameweek is empty — and those rows are already outside the learned fit,
because the shifted per-90 feature is missing there too. A club with no fixture is empty as
well, and a blank gameweek is forced to zero points by rule regardless of any rate. Both
counts are reported rather than assumed; anything else appearing in them is a defect.
"""

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from scripts._experiment_cli import DEFAULT_ARCHIVE_ROOT, REPOSITORY_ROOT, write_json, write_text

from squadopt.experiments.config import ExperimentConfigurationError, ExperimentError
from squadopt.experiments.team_rating import (
    LOCKED_HOLDOUT_SEASON,
    DixonColesConfig,
    fit_dixon_coles,
    load_match_results,
    measure_promoted_prior,
    promoted_clubs,
    select_dixon_coles_config,
)

OPPONENT_SIGNAL_CONTRACT_VERSION = "opponent_signal_v1"

# The development seasons plus the one before the earliest, because the learned rate's
# training slice reaches back into it for carry-over and its rows need a signal too.
DEFAULT_SEASONS = ("2020-21", "2021-22", "2022-23", "2023-24", "2024-25")

# Selection grids and the gameweek from which a season's folds are judged, matching the
# study that measured the rating so the two are comparable.
HALF_LIFE_GRID = (60.0, 120.0, 180.0, 300.0, 500.0)
RIDGE_GRID = (0.5, 1.0, 2.0, 5.0)
SELECTION_GAMEWEEK = 6

SIGNAL_COLUMNS = (
    "season",
    "gameweek",
    "club",
    "rating_attacking_signal",
    "rating_defensive_signal",
    "fixtures_in_gameweek",
)


@dataclass(frozen=True, slots=True)
class SignalCoverage:
    """How much of the calendar the rating could speak about, counted rather than claimed."""

    club_gameweeks: int
    signalled: int
    first_gameweek_cells: int
    seasons_on_default_config: tuple[str, ...]

    @property
    def unsignalled(self) -> int:
        return self.club_gameweeks - self.signalled


def _selected_config(
    matches: pd.DataFrame, season: str, seasons: tuple[str, ...]
) -> tuple[DixonColesConfig, bool]:
    """Choose the rating's controls on seasons strictly before this one.

    The earliest season has none to choose on. It falls back to the documented defaults,
    and the fallback is recorded: no fold is ever *judged* in that season — it is loaded
    only so carry-over has a completed season to read — so a default there cannot reach a
    measured claim.
    """

    earlier = [value for value in seasons if value < season]
    if not earlier:
        return DixonColesConfig(), True
    chosen = select_dixon_coles_config(
        matches.loc[matches["season"].isin(earlier)],
        earlier,
        half_life_grid=HALF_LIFE_GRID,
        ridge_grid=RIDGE_GRID,
        first_gameweek=SELECTION_GAMEWEEK,
    )
    return chosen, False


def build_opponent_signal(
    matches: pd.DataFrame, seasons: tuple[str, ...]
) -> tuple[pd.DataFrame, SignalCoverage]:
    """Return one signal row per club-gameweek, and what the rating could not cover.

    The locked holdout is refused here and not only in the loader. `load_match_results`
    already refuses it, but this function is importable and takes an already-loaded frame,
    so a caller could hand it holdout rows without going through the loader at all. The
    guard belongs at every door, not just the front one.
    """

    if LOCKED_HOLDOUT_SEASON in set(seasons):
        raise ExperimentConfigurationError(
            f"{LOCKED_HOLDOUT_SEASON} is the locked holdout and may not be read."
        )

    promoted = promoted_clubs(matches)
    rows: list[dict[str, object]] = []
    club_gameweeks = 0
    first_gameweek_cells = 0
    defaults: list[str] = []

    for season in seasons:
        season_matches = matches.loc[matches["season"] == season]
        if season_matches.empty:
            continue
        config, used_default = _selected_config(matches, season, seasons)
        if used_default:
            defaults.append(season)
        earlier = [value for value in seasons if value < season]
        prior = measure_promoted_prior(matches, earlier, config) if earlier else (0.0, 0.0)
        arrivals = promoted.get(season, ())

        gameweeks = sorted({int(value) for value in season_matches["gameweek"]})
        first_gameweek = gameweeks[0] if gameweeks else None

        for gameweek in gameweeks:
            block = season_matches.loc[season_matches["gameweek"] == gameweek]
            playing = sorted(
                {int(value) for value in block["home_club"]}
                | {int(value) for value in block["away_club"]}
            )
            club_gameweeks += len(playing)

            as_of = pd.Timestamp(block["kickoff"].min())
            if matches.loc[matches["kickoff"] < as_of].empty:
                # A rating with no history is not a rating. These are each season's opening
                # gameweek, and the learned fit already excludes those rows because the
                # shifted per-90 feature is missing there as well.
                if gameweek == first_gameweek:
                    first_gameweek_cells += len(playing)
                continue

            rating = fit_dixon_coles(
                matches,
                as_of=as_of,
                config=config,
                promoted_prior=prior,
                newly_promoted=arrivals,
            )

            sides = [
                (int(home), int(away))
                for home, away in zip(
                    block["home_club"].astype("int64").tolist(),
                    block["away_club"].astype("int64").tolist(),
                    strict=True,
                )
            ]
            for club in playing:
                attacking: list[float] = []
                defensive: list[float] = []
                for home, away in sides:
                    if club not in (home, away):
                        continue
                    is_home = club == home
                    opponent = away if is_home else home
                    home_rate, away_rate = rating.expected_goals(home, away)
                    attacking.append(home_rate if is_home else away_rate)
                    defensive.append(
                        rating.clean_sheet_probability(club, opponent, is_home=is_home)
                    )
                if not attacking:
                    continue
                rows.append(
                    {
                        "season": season,
                        "gameweek": gameweek,
                        "club": club,
                        "rating_attacking_signal": sum(attacking) / len(attacking),
                        "rating_defensive_signal": sum(defensive) / len(defensive),
                        "fixtures_in_gameweek": len(attacking),
                    }
                )

    table = pd.DataFrame(rows, columns=list(SIGNAL_COLUMNS))
    for column in ("season",):
        table[column] = table[column].astype("string")
    for column in ("gameweek", "club", "fixtures_in_gameweek"):
        table[column] = table[column].astype("int64")
    for column in ("rating_attacking_signal", "rating_defensive_signal"):
        table[column] = table[column].astype("float64")
    ordered = table.sort_values(["season", "gameweek", "club"], kind="stable").reset_index(
        drop=True
    )
    coverage = SignalCoverage(
        club_gameweeks=club_gameweeks,
        signalled=len(ordered),
        first_gameweek_cells=first_gameweek_cells,
        seasons_on_default_config=tuple(defaults),
    )
    return ordered, coverage


def signal_record(
    table: pd.DataFrame, coverage: SignalCoverage, seasons: tuple[str, ...]
) -> dict[str, object]:
    """The committed record: what was covered, not the table itself."""

    return {
        "artifact_type": "opponent_signal",
        "contract_version": OPPONENT_SIGNAL_CONTRACT_VERSION,
        "seasons": list(seasons),
        "grain": "season/gameweek/club",
        "columns": list(SIGNAL_COLUMNS),
        "club_gameweeks_in_calendar": coverage.club_gameweeks,
        "club_gameweeks_signalled": coverage.signalled,
        "club_gameweeks_without_a_signal": coverage.unsignalled,
        "opening_gameweek_cells": coverage.first_gameweek_cells,
        "seasons_using_default_rating_config": list(coverage.seasons_on_default_config),
        "attacking_signal_mean": float(table["rating_attacking_signal"].mean()),
        "defensive_signal_mean": float(table["rating_defensive_signal"].mean()),
        "locked_holdout_accessed": False,
        "measurement_only": True,
        "gate_evidence": False,
    }


def _joined(value: object) -> str:
    """Render a recorded list without assuming the record's loose value type."""

    return ", ".join(str(item) for item in value) if isinstance(value, list) else str(value)


def signal_markdown(record: dict[str, object]) -> str:
    """Render the record. The table stays local; this is what is committed."""

    unsignalled = int(str(record["club_gameweeks_without_a_signal"]))
    opening = int(str(record["opening_gameweek_cells"]))
    lines = [
        "# Opponent Signal",
        "",
        f"- Contract: `{record['contract_version']}`",
        f"- Grain: `{record['grain']}`",
        f"- Seasons: {_joined(record['seasons'])}",
        "",
        "The Dixon-Coles rating refitted once per gameweek, at that gameweek's first kickoff, "
        "and recorded as the attacking and defensive signal it implies for each club. This is "
        "an input a declared candidate would read; it decides nothing on its own.",
        "",
        "## Coverage",
        "",
        "| | Club-gameweeks |",
        "| --- | ---: |",
        f"| In the calendar | {record['club_gameweeks_in_calendar']} |",
        f"| Carrying a signal | {record['club_gameweeks_signalled']} |",
        f"| Without a signal | {unsignalled} |",
        f"| …of which each season's opening gameweek | {opening} |",
        "",
    ]
    if unsignalled == opening:
        lines.append(
            "Every uncovered cell is an opening gameweek, which is the only honest answer: a "
            "rating needs a match before it can rate anybody. Those rows are already outside "
            "the learned fit, because the shifted per-90 feature is missing there too — so "
            "the signal's coverage costs the fit nothing."
        )
    else:
        lines.append(
            f"**{unsignalled - opening} cells are uncovered for a reason other than an opening "
            "gameweek.** That is a defect rather than a property, and a candidate must not be "
            "declared against this file until it is explained: a declared input that is "
            "missing on a non-blank row drops that row down the rate ladder silently."
        )
    defaults = record["seasons_using_default_rating_config"]
    if isinstance(defaults, list) and defaults:
        lines += [
            "",
            f"Rating controls fell back to the documented defaults for "
            f"{_joined(defaults)}, which has no earlier season to "
            "select on. No fold is judged in that season — it is loaded so carry-over has a "
            "completed season to read — so the fallback cannot reach a measured claim.",
        ]
    lines += [
        "",
        "## Reproduction",
        "",
        "```powershell",
        ".venv\\Scripts\\python -m scripts.build_opponent_signal",
        "```",
        "",
        "The table itself stays under `artifacts/`: it is the per-fold expansion behind this "
        "record, which [ADR 0003](architecture/decisions/0003-measurement-artifacts.md) routes "
        "away from the repository.",
    ]
    return "\n".join(lines) + "\n"


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-root", type=Path, default=DEFAULT_ARCHIVE_ROOT)
    parser.add_argument(
        "--output-dir", type=Path, default=REPOSITORY_ROOT / "artifacts" / "opponent_signal"
    )
    parser.add_argument(
        "--summary-output", type=Path, default=REPOSITORY_ROOT / "docs" / "opponent_signal.md"
    )
    parser.add_argument(
        "--json-output", type=Path, default=REPOSITORY_ROOT / "docs" / "opponent_signal.json"
    )
    return parser.parse_args()


def main() -> int:
    arguments = _parse_arguments()
    seasons = DEFAULT_SEASONS
    archive_root: Path = arguments.archive_root
    if not archive_root.is_dir():
        print(f"Archive not found at {archive_root}. Run scripts.fetch_historical_data first.")
        return 1

    print(f"Loading {', '.join(seasons)} from {archive_root}")
    try:
        matches = load_match_results(archive_root, seasons)
        table, coverage = build_opponent_signal(matches, seasons)
    except ExperimentError as error:
        print(f"Could not build the opponent signal:\n  {error}")
        return 1

    record = signal_record(table, coverage, seasons)
    print(
        f"\n{coverage.signalled} of {coverage.club_gameweeks} club-gameweeks carry a signal; "
        f"{coverage.unsignalled} do not ({coverage.first_gameweek_cells} of those are opening "
        "gameweeks)."
    )

    output_dir: Path = arguments.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    table_path = output_dir / "opponent_signal.csv"
    table.to_csv(table_path, index=False, lineterminator="\n")
    write_json(arguments.json_output, record)
    write_text(arguments.summary_output, signal_markdown(record))

    print(f"Wrote {table_path}")
    print(f"Wrote {arguments.json_output}")
    print(f"Wrote {arguments.summary_output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
