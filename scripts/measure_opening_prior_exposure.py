"""Quantify how much of each projection the opening price prior carries.

    python -m scripts.measure_opening_prior_exposure
    python -m scripts.measure_opening_prior_exposure --quick   # a short fold prefix, for wiring

`in_season_blend_benchmark.md` records a caveat about its own headline and names this as the
first thing a follow-up should do: the coefficient was fitted on the same seasons those folds
evaluate, so a control-versus-blend gap could partly reflect differing reliance on that
constant rather than projection quality. This measures the reliance and refits the constant
walk-forward.

Projection-level only, and deliberately so -- see the module docstring for why an estimate of
the realized-points effect is exactly what this record exists to replace rather than provide.
Measurement only: nothing is promoted, no declared constant moves, and the locked holdout is
cut from the panel before any feature window can reach it.
"""

import argparse
import sys
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from scripts._experiment_cli import (
    DEFAULT_ARCHIVE_ROOT,
    REPOSITORY_ROOT,
    artifact_metadata,
    write_json,
    write_text,
)

from squadopt.experiments import ExperimentError
from squadopt.experiments.opening_prior_exposure import (
    OPENING_PRIOR_EXPOSURE_CONTRACT_VERSION,
    OpeningPriorExposure,
    OpeningPriorExposureConfig,
    exposure_to_markdown,
    measure_opening_prior_exposure,
)


def _document(exposure: OpeningPriorExposure, created_utc: str) -> dict[str, object]:
    return {
        **artifact_metadata(panel_rows=0, created_utc=created_utc),
        "artifact_type": "opening_prior_exposure",
        "contract_version": OPENING_PRIOR_EXPOSURE_CONTRACT_VERSION,
        "config": asdict(exposure.config),
        "frozen_coefficient": exposure.frozen_coefficient,
        "folds": exposure.folds,
        "first_fold": exposure.first_fold,
        "last_fold": exposure.last_fold,
        "coefficients": [
            {**asdict(entry), "difference_from_frozen": entry.difference_from_frozen}
            for entry in exposure.coefficients
        ],
        "configurations": [
            {
                **asdict(entry),
                "row_share": entry.row_share,
                "attributable_share": entry.attributable_share,
                "squad_shaped_attributable_share": entry.squad_shaped_attributable_share,
                "level_shift": entry.level_shift,
            }
            for entry in exposure.configurations
        ],
        "diagnostics": dict(exposure.diagnostics),
        "measurement_only": True,
        "locked_holdout_accessed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-root", type=Path, default=DEFAULT_ARCHIVE_ROOT)
    parser.add_argument(
        "--json-output",
        type=Path,
        default=REPOSITORY_ROOT / "docs" / "opening_prior_exposure.json",
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=REPOSITORY_ROOT / "docs" / "opening_prior_exposure.md",
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="measure a short fold prefix, for checking the wiring rather than measuring",
    )
    parser.add_argument("--fold-limit", type=int, default=None)
    arguments = parser.parse_args()

    if not arguments.archive_root.is_dir():
        print(f"Archive not found at {arguments.archive_root}.")
        return 1

    limit = 6 if arguments.quick else arguments.fold_limit
    created_utc = datetime.now(UTC).isoformat(timespec="seconds")
    try:
        exposure = measure_opening_prior_exposure(
            arguments.archive_root, OpeningPriorExposureConfig(), fold_limit=limit
        )
    except ExperimentError as error:
        print(f"Could not measure the opening prior's exposure:\n  {error}")
        return 1

    print(f"Folds {exposure.folds}  ({exposure.first_fold} .. {exposure.last_fold})")
    print()
    for entry in exposure.configurations:
        squad_share = entry.squad_shaped_attributable_share
        print(
            f"  {entry.label:24} rows {entry.rows:>7,}  touching {entry.row_share:.4f}"
            f"  mass {entry.attributable_share:.4f}  squad {squad_share:.4f}"
            f"  level {entry.level_shift:+.4f}"
        )
    print()
    for coefficient in exposure.coefficients:
        print(
            f"  {coefficient.season}  {coefficient.coefficient:.8f}"
            f"  ({coefficient.difference_from_frozen:+.8f} vs frozen)"
            f"  fitted on {', '.join(coefficient.fitted_on)}"
        )

    if limit is not None:
        print(f"\nFold-limited run ({limit} folds): nothing written.")
        return 0

    write_json(arguments.json_output, _document(exposure, created_utc))
    write_text(arguments.markdown_output, exposure_to_markdown(exposure))
    print(f"\nWrote {arguments.json_output}")
    print(f"Wrote {arguments.markdown_output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
