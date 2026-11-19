"""Freeze two published captures and their matching saved projection handoffs, offline."""

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

from scripts.measure_window_solver_highs import fixture_counts

HERE = Path(__file__).resolve().parent
SOURCES = ("927ae33a2129", "6cc16168ed8d")


def digest(value):
    normalized = json.loads(json.dumps(value))
    return hashlib.sha256(json.dumps(normalized, sort_keys=True).encode()).hexdigest()


def published(commit, path):
    raw = subprocess.check_output(["git", "show", f"{commit}:{path}"])
    return json.loads(raw)["payload"]


def freeze(handoffs):
    records = []
    for source in SOURCES:
        commit = subprocess.check_output(["git", "rev-parse", source], text=True).strip()
        league = "web/public/data/leagues/352490"
        table = published(commit, f"{league}/device-plan.json")
        projection_path = handoffs / f"2026-27-gw{table['gameweek']:02d}.json"
        projection = json.loads(projection_path.read_text(encoding="utf-8"))
        assert projection["source_snapshot_id"] == table["source_snapshot_id"]
        calendar = published(commit, "web/public/data/fixtures.json")
        assert calendar["source_snapshot_id"] == table["source_snapshot_id"]
        names = subprocess.check_output(
            ["git", "ls-tree", "-r", "--name-only", commit, f"{league}/entries"], text=True
        ).splitlines()
        members = {}
        for name in sorted(names, key=lambda p: int(Path(p).stem)):
            member = published(commit, name)
            if member.get("device_plan"):
                assert member["source_snapshot_id"] == table["source_snapshot_id"]
                members[Path(name).stem] = member["device_plan"]
            if len(members) == 10:
                break
        keep = ("id", "name", "team", "position", "buy_tenths", "expected_points", "coefficients")
        table = {**table, "players": [{k: p[k] for k in keep} for p in table["players"]]}
        snapshot = {
            "source_commit": commit,
            "table": table,
            "members": members,
            "fixture_counts": fixture_counts(calendar),
            "projection": projection,
            "projection_file_sha256": hashlib.sha256(projection_path.read_bytes()).hexdigest(),
        }
        target = HERE / f"gw{table['gameweek']}.json"
        target.write_text(json.dumps(snapshot, sort_keys=True, separators=(",", ":")) + "\n")
        records.append({"path": target.name, "sha256": digest(snapshot)})
    manifest = {"version": 1, "snapshots": records, "member_weeks": 20}
    (HERE / "inputs.json").write_text(json.dumps(manifest, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--handoffs", required=True, type=Path)
    freeze(parser.parse_args().handoffs)
