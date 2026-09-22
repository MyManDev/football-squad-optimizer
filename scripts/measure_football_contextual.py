"""Frozen development comparison for contextual football; no live reads or promotion.

Use the existing causal training CSV and archived seasons. Reused historical calendars,
rosters and seasons are development evidence, never an untouched prospective holdout.
Every scheduled fold is retained, including explicit failures and unmatched labels.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import traceback
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import poisson

from squadopt.data.sources.football_history import ARCHIVE_SEASONS, archive_history
from squadopt.live.football_horizon import build_football_horizon
from squadopt.prediction.football import FixtureFootballModel
from squadopt.prediction.football_contextual import ContextualFootballModel

SEASONS = ("2024-25", "2025-26")
ORIGINS = (11, 15, 19, 23, 27, 31)
KEYS = ["season", "fixture", "player_code"]


def write(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, indent=2, allow_nan=False, default=str) + "\n", encoding="utf-8"
    )


def losses(actual: pd.DataFrame, prediction: pd.DataFrame) -> dict[str, float | int]:
    actual, prediction = actual.reset_index(drop=True), prediction.reset_index(drop=True)
    result: dict[str, float | int] = {
        "rows": len(actual),
        "missing": int(actual.total_points.isna().sum()),
    }
    for label, observed, forecast, kind in (
        ("points", "total_points", "expected_points", "mse"),
        ("minutes", "minutes", "expected_minutes", "mae"),
        ("appearance", "appeared", "appearance_probability", "brier"),
        ("goals", "goals_scored", "goals", "mse"),
        ("assists", "assists", "assists", "mse"),
        ("cs", "clean_sheets", "clean_sheet_probability", "brier"),
        ("dc", "dc_event", "defcon_probability", "brier"),
    ):
        mask = actual[observed].notna()
        if label == "dc":
            mask &= actual.position.ne("GK") & actual.season.ge("2025-26")
        if not mask.any():
            continue
        y, p = (
            actual.loc[mask, observed].to_numpy(float),
            prediction.loc[mask, forecast].to_numpy(float),
        )
        delta = p - y
        result[label + "_" + kind] = float(np.mean(np.abs(delta) if kind == "mae" else delta**2))
        if label in ("goals", "assists"):
            result[label + "_poisson_nll"] = float(-poisson.logpmf(y, np.maximum(p, 1e-12)).mean())
        if kind == "brier":
            result[label + "_mean_probability"] = float(p.mean())
            result[label + "_event_rate"] = float(y.mean())
    return result


def run(archive: Path, training: Path, rosters: Path, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=False)
    hashes = {
        "training": hashlib.sha256(training.read_bytes()).hexdigest(),
        "rosters": hashlib.sha256(rosters.read_bytes()).hexdigest(),
    }
    for season in ARCHIVE_SEASONS:
        for name in ("gws/merged_gw.csv", "players_raw.csv", "teams.csv", "fixtures.csv"):
            hashes[season + "/" + name] = hashlib.sha256(
                (archive / "data" / season / name).read_bytes()
            ).hexdigest()
    write(output / "input-hashes.json", hashes)
    project = Path(__file__).resolve().parents[1]
    code = [
        Path(__file__),
        *sorted((project / "src/squadopt/prediction").glob("football*.py")),
        project / "src/squadopt/live/football_horizon.py",
    ]
    write(
        output / "source-hashes.json",
        {str(p.relative_to(project)): hashlib.sha256(p.read_bytes()).hexdigest() for p in code},
    )
    write(
        output / "protocol.json",
        {
            "seasons": SEASONS,
            "component_gameweeks": list(range(11, 39)),
            "future_origins": ORIGINS,
            "windows": [1, 3, 5],
            "arms": ["v1", "contextual", "attack_only_ablation"],
            "tuning": False,
            "development_data_reused": True,
            "promotion": False,
            "current_taker_and_news_backfill": False,
            "future_calendar": "historical final calendar, not deadline-verified",
            "forecast_input": "existing causal feature corpus; only past labels at each origin",
        },
    )
    raw = archive_history(archive)
    frame = pd.read_csv(training, low_memory=False)
    for col in ("kickoff", "feature_cutoff"):
        frame[col] = pd.to_datetime(frame[col], utc=True)
    missing = [c for c in ("starts", "appeared", "long") if c not in frame]
    if missing:
        frame = frame.merge(raw[[*KEYS, *missing]], on=KEYS, validate="one_to_one")
    roster_table = pd.read_csv(rosters)
    weekly, future, failures = [], [], []
    for season in SEASONS:
        base = archive / "data" / season
        teams = pd.read_csv(base / "teams.csv")
        matches = pd.read_csv(base / "fixtures.csv")
        club_ids, names = teams.set_index("id").code, teams.set_index("name").code
        calendar = pd.concat(
            [
                pd.DataFrame(
                    {
                        "fixture": matches.id,
                        "club": matches["team_h" if home else "team_a"].map(club_ids),
                        "opponent": matches["team_a" if home else "team_h"].map(club_ids),
                        "home": float(home),
                        "GW": matches.event,
                        "kickoff": pd.to_datetime(matches.kickoff_time, utc=True),
                    }
                )
                for home in (True, False)
            ],
            ignore_index=True,
        )
        for week in range(11, 39):
            fold = f"{season}-gw{week:02d}"
            print(fold + " START", flush=True)
            try:
                target = frame.loc[frame.season.eq(season) & frame.GW.eq(week)].copy()
                cutoff = target.feature_cutoff.min()
                past = (raw.season < season) | (raw.season.eq(season) & raw.GW.lt(week))
                history = raw.loc[past & (raw.kickoff + pd.Timedelta(hours=3) < cutoff)]
                earlier = (frame.season < season) | (frame.season.eq(season) & frame.GW.lt(week))
                train = frame.loc[
                    earlier
                    & frame.season.ne(ARCHIVE_SEASONS[0])
                    & (frame.kickoff + pd.Timedelta(hours=3) < cutoff)
                ]
                candidate = ContextualFootballModel(train, history, cutoff=cutoff)
                # The inherited fit is unchanged v1; direct base predict freezes its heads.
                control = FixtureFootballModel.predict(candidate, target)
                full = candidate.predict(target)
                attack = control.copy()
                for col in ("goals", "assists"):
                    attack[col] = full[col]
                coefficients = target.position.map(
                    {"GK": 10, "DEF": 6, "MID": 5, "FWD": 4}
                ).to_numpy(float)
                attack["expected_points"] = np.maximum(
                    0,
                    control.raw_expected_points.to_numpy()
                    + coefficients * (full.goals.to_numpy() - control.goals.to_numpy())
                    + 3 * (full.assists.to_numpy() - control.assists.to_numpy()),
                )
                for arm, prediction in (
                    ("v1", control),
                    ("contextual", full),
                    ("attack_only_ablation", attack),
                ):
                    weekly.append(
                        {"season": season, "GW": week, "arm": arm, **losses(target, prediction)}
                    )
                if week in ORIGINS:
                    deadline = cutoff - pd.Timedelta(minutes=90)
                    h = history.loc[history.kickoff + pd.Timedelta(hours=3) < deadline]
                    t = train.loc[train.kickoff + pd.Timedelta(hours=3) < deadline]
                    model = ContextualFootballModel(t, h, cutoff=deadline)
                    reference = FixtureFootballModel(t, h, cutoff=deadline)
                    roster = roster_table.loc[roster_table.fold_id.eq(f"{season}-gw{week}")].copy()
                    roster["club"] = roster.team_id.map(names)
                    actual = raw.loc[
                        raw.season.eq(season),
                        [
                            *KEYS,
                            "position",
                            "minutes",
                            "appeared",
                            "goals_scored",
                            "assists",
                            "clean_sheets",
                            "dc_event",
                            "total_points",
                        ],
                    ]
                    for arm, fitted in (("v1", reference), ("contextual", model)):
                        _, parts = build_football_horizon(
                            fitted,
                            h,
                            roster,
                            calendar,
                            gameweeks=tuple(range(week, week + 5)),
                            season=season,
                            source_snapshot_id="development-final-calendar-" + fold,
                            captured_at=deadline,
                        )
                        labels = parts[KEYS].merge(
                            actual, on=KEYS, how="left", validate="one_to_one"
                        )
                        parts.to_csv(output / (fold + "-" + arm + "-future.csv"), index=False)
                        for window in (1, 3, 5):
                            mask = parts.GW.lt(week + window).to_numpy()
                            future.append(
                                {
                                    "season": season,
                                    "origin": week,
                                    "window": window,
                                    "arm": arm,
                                    **losses(labels.loc[mask], parts.loc[mask]),
                                }
                            )
                print(fold + " PASS", flush=True)
            except Exception as error:
                failures.append(
                    {"fold": fold, "error": str(error), "traceback": traceback.format_exc()}
                )
                print(fold + " FAILED: " + str(error), flush=True)
            pd.DataFrame(weekly).to_csv(output / "component-losses.csv", index=False)
            pd.DataFrame(future).to_csv(output / "future-losses.csv", index=False)
            write(output / "failures.json", failures)
    write(
        output / "summary.json",
        {
            "component_records": len(weekly),
            "future_records": len(future),
            "failures": len(failures),
            "development_only": True,
            "independent_promotion_evidence": False,
        },
    )
    if failures:
        raise RuntimeError(f"{len(failures)} folds failed; retained in failures.json")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("archive", "training", "rosters", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    run(args.archive, args.training, args.rosters, args.output)


if __name__ == "__main__":
    main()
