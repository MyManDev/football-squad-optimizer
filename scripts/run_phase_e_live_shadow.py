"""Explicit E4 decide entry point; the ordinary decide command stays unchanged."""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from scripts._phase_e_shadow_live import make_live_shadow_hook

from squadopt.application import DecideRequest, decide
from squadopt.data import DataError
from squadopt.scenarios import ScenarioError


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in (
        "binding",
        "runtime-probe",
        "shadow-evaluation",
        "table",
        "roster",
        "manifest",
        "in-season-projection",
        "snapshot-root",
        "ledger-root",
        "archive-root",
    ):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--snapshot-id", required=True)
    arguments = parser.parse_args(argv)
    try:
        hook = make_live_shadow_hook(
            binding_path=arguments.binding,
            runtime_path=arguments.runtime_probe,
            shadow_path=arguments.shadow_evaluation,
            table_path=arguments.table,
            roster_path=arguments.roster,
            manifest_path=arguments.manifest,
            projection_path=arguments.in_season_projection,
            archive_root=arguments.archive_root,
        )
        result = decide(
            DecideRequest(
                snapshot_root=arguments.snapshot_root,
                ledger_root=arguments.ledger_root,
                archive_root=arguments.archive_root,
                snapshot_id=arguments.snapshot_id,
                in_season_projection=arguments.in_season_projection,
                mode="live",
            ),
            phase_e_shadow=hook,
        )
    except (DataError, ScenarioError, ValueError, OSError) as error:
        print(f"E4 refused: {error}", file=sys.stderr)
        return 1
    print(result.report)
    print(f"Ledger: {result.decision_directory}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
