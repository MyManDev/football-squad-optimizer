"""Validate one of the repository's own measurement artifacts.

    python -m scripts.run_measurement_preflight \
        --artifact docs/baseline_policy_grid.json --kind policy_grid

Exit code 0 only when every governance check passed, so the command can gate a
regenerated artifact before it is committed.
"""

import argparse
import json
import sys
from pathlib import Path

from squadopt.preflight import (
    MEASUREMENT_KINDS,
    PreflightError,
    preflight_report_to_dict,
    preflight_report_to_markdown,
    run_measurement_preflight,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--kind", required=True, choices=sorted(MEASUREMENT_KINDS))
    parser.add_argument("--json-output", type=Path)
    arguments = parser.parse_args()

    if not arguments.artifact.is_file():
        print(f"Artifact not found at {arguments.artifact}.")
        return 1
    document = json.loads(arguments.artifact.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        print(f"Artifact {arguments.artifact} must contain a JSON object.")
        return 1

    try:
        report = run_measurement_preflight(
            document, arguments.kind, artifact_label=arguments.artifact.name
        )
    except PreflightError as error:
        print(f"Could not examine the artifact:\n  {error}")
        return 1

    print(preflight_report_to_markdown(report))
    if arguments.json_output is not None:
        arguments.json_output.parent.mkdir(parents=True, exist_ok=True)
        arguments.json_output.write_text(
            json.dumps(preflight_report_to_dict(report), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(f"Wrote {arguments.json_output}")
    return 0 if report.passed else 1


if __name__ == "__main__":
    sys.exit(main())
