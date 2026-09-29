"""Measure dated single-chip holding values on one immutable captured calendar."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

from squadopt.application.football_context import bind_football_context
from squadopt.data.snapshots import read_snapshot
from squadopt.data.sources.football_history import archive_history
from squadopt.experiments.calendar_chip import optimize_calendar_chip
from squadopt.experiments.football_components import ComponentForecast, Components
from squadopt.live import read_inputs
from squadopt.live.football_horizon import build_football_horizon
from squadopt.live.rules import read_season_rules
from squadopt.optimization import OptimizationConfig
from squadopt.planning import ChipAvailability, ChipUseWindow, InitialSquadState
from squadopt.planning.horizon import to_planning_horizon
from squadopt.prediction.football_contextual import ContextualFootballModel


def run(args):
    study, out = args.study, args.output
    out.mkdir(parents=True, exist_ok=False)
    tree = Path(__file__).resolve().parents[1]

    def write(name, value):
        (out / name).write_text(
            json.dumps(value, indent=2, default=str, allow_nan=False) + "\n", encoding="utf-8"
        )

    def read(path):
        table = pd.read_csv(path, low_memory=False)
        for col in ("kickoff", "feature_cutoff"):
            if col in table:
                table[col] = pd.to_datetime(table[col], utc=True)
        return table

    snap = read_snapshot(args.snapshots, args.snapshot_id)
    evidence = json.loads((study / "input-evidence.json").read_text())
    if (
        snap.metadata.snapshot_id != evidence["snapshot_id"]
        or snap.metadata.fingerprint != evidence["snapshot_fingerprint"]
    ):
        raise ValueError("Forward capture must match the measured source identity.")
    if hashlib.sha256(args.training.read_bytes()).hexdigest() != evidence["training_sha256"]:
        raise ValueError("Forward training must match the measured corpus.")
    inputs = read_inputs(snap, season="2026-27")
    if int(inputs.deadline.gameweek) != 6:
        raise ValueError("This prespecified study requires the GW6 decision capture.")
    cutoff = pd.Timestamp(inputs.captured_at_utc)
    for relative, digest in evidence["archive_sha256"].items():
        if (
            hashlib.sha256((args.archive / relative.replace(chr(92), "/")).read_bytes()).hexdigest()
            != digest
        ):
            raise ValueError("Archived training evidence changed.")
    raw = archive_history(args.archive)
    raw = pd.concat([raw, read(study / "current-history.csv")], ignore_index=True)
    train = read(args.training)
    train = train.loc[train.season.ne("2022-23")].copy()
    missing = [c for c in ("starts", "appeared", "long") if c not in train]
    if missing:
        train = train.merge(
            raw[["season", "fixture", "player_code", *missing]],
            on=["season", "fixture", "player_code"],
            validate="one_to_one",
        )
    train = pd.concat([train, read(study / "current-causal-training.csv")], ignore_index=True)
    assert (raw.kickoff + pd.Timedelta(hours=3) < cutoff).all()
    print("FORWARD FIT", flush=True)
    fitted = ContextualFootballModel(train, raw, cutoff=cutoff)

    class ResearchModel(ContextualFootballModel):
        model_version = "football_component_research"

        def __init__(self, reference, history, switches, parameters):
            self.reference, self.history, self.switches, self.parameters = (
                reference,
                history,
                switches,
                parameters,
            )
            self.cutoff = reference.cutoff

        def predict(self, target, *, role_steps=0):
            if role_steps:
                raise ValueError("No role transition")
            return ComponentForecast(self.reference, self.history, target).predict(
                self.switches, attack_only=True, **self.parameters
            )

    boot = json.loads(snap.payloads["bootstrap-static.json"])
    clubs = {t["id"]: t["code"] for t in boot["teams"]}
    player_clubs = {p["code"]: clubs[p["team"]] for p in boot["elements"]}
    roster = inputs.players.copy()
    roster["club"] = roster.player_id.map(player_clubs)
    roster, _audit = bind_football_context(
        roster, inputs.availability, season="2026-27", gameweek=6, cutoff=cutoff, manager_words=None
    )
    fixtures = pd.DataFrame(json.loads(snap.payloads["fixtures.json"]))
    rules = read_season_rules(snap, season="2026-27")
    last = max(p.stop_event for p in rules.chips if p.name in ("3xc", "bboost") and p.covers(6))
    weeks = tuple(range(6, last + 1))
    fixtures = fixtures.loc[fixtures.event.isin(weeks)]
    if fixtures.kickoff_time.isna().any():
        raise ValueError("Captured tail contains undated fixtures; no calendar imputation.")
    calendar = pd.concat(
        [
            pd.DataFrame(
                {
                    "fixture": fixtures.id,
                    "club": fixtures["team_h" if home else "team_a"].map(clubs),
                    "opponent": fixtures["team_a" if home else "team_h"].map(clubs),
                    "home": float(home),
                    "GW": fixtures.event,
                    "kickoff": pd.to_datetime(fixtures.kickoff_time, utc=True),
                }
            )
            for home in (True, False)
        ],
        ignore_index=True,
    )
    opt = OptimizationConfig(
        bench_weight=0, solver_time_limit_seconds=120, solver_deterministic_time_limit=60
    )
    model = ResearchModel(fitted, raw, Components(), {})
    horizon, _ = build_football_horizon(
        model,
        raw,
        roster,
        calendar,
        gameweeks=weeks,
        season="2026-27",
        source_snapshot_id=inputs.snapshot_id,
        captured_at=cutoff,
    )
    plan_horizon = to_planning_horizon(horizon)
    expected = pd.read_csv(args.forward / "control-projections.csv", float_precision="round_trip")
    keys = ["gameweek", "player_id"]
    paired = horizon.table.loc[horizon.table.gameweek.le(10)].merge(
        expected, on=keys, validate="one_to_one", suffixes=("_new", "_old")
    )
    if len(paired) != len(expected) or not np.allclose(
        paired.expected_points_new, paired.expected_points_old, atol=1e-10, rtol=0
    ):
        raise ValueError("Existing five-week forecast parity failed.")
    old = json.loads((args.forward / "protocol.json").read_text())
    initial = InitialSquadState(
        tuple(old["initial_player_ids"]), old["bank_tenths"], old["free_transfers"]
    )
    horizon.table.to_csv(out / "captured-calendar-projections.csv", index=False)
    write(
        "protocol.json",
        {
            "candidate": "fixed_squad_calendar_chip_v1",
            "snapshot_id": snap.metadata.snapshot_id,
            "snapshot_fingerprint": snap.metadata.fingerprint,
            "windows": [1, 3, 5],
            "calendar_weeks": list(weeks),
            "development_only": True,
            "promotion": False,
            "initial_squad": "same constructed study squad; hypothetical unspent single chip",
            "news": "same captured availability, no future recovery or news invented",
            "forecast_method": "frozen component CONTROL extended over captured fixture dates",
            "training_sha256": hashlib.sha256(args.training.read_bytes()).hexdigest(),
            "source_sha256": {
                str(p.relative_to(tree)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in [Path(__file__), tree / "src/squadopt/experiments/calendar_chip.py"]
            },
            "realized_returns": False,
            "fixed_squad": True,
        },
    )
    rows = []
    for chip in ("3xc", "bboost"):
        period = next(p for p in rules.chips if p.name == chip and p.covers(6))
        dates = frozenset(range(6, period.stop_event + 1))
        rights = ChipAvailability({chip: dates}, use_windows={chip: (ChipUseWindow(dates),)})
        for window in (1, 3, 5):
            start = time.perf_counter()
            row = {"chip": chip, "window": window}
            try:
                result = optimize_calendar_chip(plan_horizon, initial, opt, rights, window=window)
                row.update(
                    status=result.solver_status.name,
                    played=dict(result.chips_played),
                    expected_points=result.total_projected_score,
                    diagnostics=dict(result.diagnostics),
                )
            except Exception as error:
                row.update(status="FAILED", error=str(error))
            row["wall_seconds"] = time.perf_counter() - start
            rows.append(row)
            write("results.json", rows)
            print(chip, window, row["status"], row.get("played"), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("archive", "training", "snapshots", "study", "forward", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--snapshot-id", required=True)
    run(parser.parse_args())
