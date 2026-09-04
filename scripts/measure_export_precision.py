"""Measure how much precision a residual export must drop to survive crossing machines.

    python -m scripts.measure_export_precision

Two owners regenerated the candidate residual export at the same commit and recorded
different `table_sha256` while every reported decimal agreed. This answers the question
that left open: is rounding the written values enough, and to how many decimals.

Reads an existing export rather than regenerating one. Regenerating on a single machine
cannot show the effect — a machine is bit-identical with itself — so the measurement
perturbs a real table instead and counts what would move.
"""

import argparse
import json
import sys
from pathlib import Path

import pandas as pd
from scripts._experiment_cli import REPOSITORY_ROOT, artifact_metadata, write_json, write_text

from squadopt.backtest.export_precision import (
    measure_export_precision,
    precision_to_dict,
    precision_to_markdown,
)
from squadopt.data.errors import DataError

DEFAULT_TABLE = REPOSITORY_ROOT / "artifacts" / "residuals" / "learned_candidate_residuals.csv"


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--table", type=Path, default=DEFAULT_TABLE)
    parser.add_argument("--column", default="predicted_points")
    parser.add_argument(
        "--json-output",
        type=Path,
        default=REPOSITORY_ROOT / "docs" / "export_precision.json",
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=REPOSITORY_ROOT / "docs" / "export_precision.md",
    )
    return parser.parse_args()


def main() -> int:
    arguments = _parse_arguments()
    table_path: Path = arguments.table
    if not table_path.is_file():
        print(
            f"No export at {table_path}.\n"
            "Produce one first with 'python -m scripts.export_candidate_residuals'."
        )
        return 1

    try:
        table = pd.read_csv(table_path)
        result = measure_export_precision(table, column=str(arguments.column))
    except (DataError, OSError, ValueError) as error:
        print(f"Could not measure export precision:\n  {error}")
        return 1

    document = {
        **artifact_metadata(panel_rows=len(table)),
        **precision_to_dict(result),
        "measured_table": table_path.name,
    }
    markdown = precision_to_markdown(result)

    write_json(arguments.json_output, document)
    write_text(arguments.markdown_output, markdown)
    print(markdown)
    print(json.dumps({"recommended_decimals_at_1e-15": document["recommended_decimals_at_1e-15"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
