"""Append one settled gameweek's projection-versus-reality row to the season scorecard.

    python -m scripts.append_weekly_scorecard --gameweek 1

Run once after each settle, from the ledger's frozen decision and its recorded outcome —
never from anything recomputed. The scorecard is the season's calibration record in the
making: by May it answers "did the projections mean anything" from 38 rows written the
week they happened, not reconstructed afterwards. A gameweek without a recorded outcome
is refused; an already-written row is refused (the ledger is immutable and so is this).
"""

import argparse
import json
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SCORECARD_PATH = REPOSITORY_ROOT / "docs" / "weekly_scorecard.md"
HEADER = (
    "# Weekly scorecard — 2026-27\n\n"
    "Projection versus reality, one row per settled gameweek, appended on settle day\n"
    "from the frozen ledger entry. Errors are realized-XI minus projected; negative\n"
    "means the projection was optimistic. Captain share is the captain's doubled\n"
    "points as a fraction of the realized XI score.\n\n"
    "| GW | model version | projected | realized XI | net | error | captain pts (x2) | captain share |\n"
    "| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |\n"
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gameweek", type=int, required=True)
    parser.add_argument("--season", default="2026-27")
    parser.add_argument("--ledger-root", type=Path, default=REPOSITORY_ROOT / "data" / "ledger")
    parser.add_argument("--output", type=Path, default=SCORECARD_PATH)
    arguments = parser.parse_args()

    entry = arguments.ledger_root / arguments.season / f"gw{arguments.gameweek:02d}"
    decision_path = entry / "decision.json"
    outcome_path = entry / "outcome.json"
    if not decision_path.is_file():
        print(f"No recorded decision at {decision_path}.")
        return 1
    if not outcome_path.is_file():
        print(f"Gameweek {arguments.gameweek} has no recorded outcome yet; settle first.")
        return 1
    decision = json.loads(decision_path.read_text(encoding="utf-8"))
    outcome = json.loads(outcome_path.read_text(encoding="utf-8"))

    projected = float(decision["projected_score"])
    realized = float(outcome["realized_xi_score"])
    net = float(outcome.get("realized_net_score", realized))
    error = realized - projected
    captain = str(decision["captain_player_id"])
    captain_points = float(outcome["realized_points_by_player"].get(captain, 0.0))
    captain_doubled = captain_points * 2.0
    captain_share = captain_doubled / realized if realized else 0.0

    row = (
        f"| {int(decision['gameweek'])} | {decision['model_version']} "
        f"| {projected:.2f} | {realized:.0f} | {net:.0f} | {error:+.2f} "
        f"| {captain_doubled:.0f} | {captain_share:.0%} |\n"
    )

    output: Path = arguments.output
    if output.is_file():
        text = output.read_text(encoding="utf-8")
        marker = f"| {int(decision['gameweek'])} | "
        if any(line.startswith(marker) for line in text.splitlines()):
            print(f"Gameweek {arguments.gameweek} is already on the scorecard; rows are immutable.")
            return 1
    else:
        text = HEADER
    output.write_text(text + row, encoding="utf-8")
    print(row.strip())
    print(f"Appended to {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
