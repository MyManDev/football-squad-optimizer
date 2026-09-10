"""Compatibility shell for the installed weekly operations runner."""

import argparse
import sys
from pathlib import Path

from squadopt.application.weekly_plan import (
    CHIP_CHOICES as CHIP_CHOICES,
)
from squadopt.application.weekly_plan import (
    MODE_RULE as MODE_RULE,
)
from squadopt.application.weekly_plan import (
    STEPS as STEPS,
)
from squadopt.application.weekly_plan import (
    WeekError as WeekError,
)
from squadopt.application.weekly_plan import (
    WeekPlan as WeekPlan,
)
from squadopt.application.weekly_plan import (
    capture_deadline as capture_deadline,
)
from squadopt.application.weekly_plan import (
    check_evidence_for_reused_capture as check_evidence_for_reused_capture,
)
from squadopt.application.weekly_plan import (
    check_rotation_for_reused_capture as check_rotation_for_reused_capture,
)
from squadopt.application.weekly_plan import (
    decision_mode_for as decision_mode_for,
)
from squadopt.application.weekly_plan import (
    evidence_artifact as evidence_artifact,
)
from squadopt.application.weekly_plan import (
    latest_live_snapshot as latest_live_snapshot,
)
from squadopt.application.weekly_plan import (
    new_snapshot as new_snapshot,
)
from squadopt.application.weekly_plan import (
    plan_week as plan_week,
)
from squadopt.application.weekly_plan import (
    preflight_decide as preflight_decide,
)
from squadopt.application.weekly_plan import (
    rotation_artifact as rotation_artifact,
)
from squadopt.application.weekly_plan import (
    rules_before_capture as rules_before_capture,
)
from squadopt.platform.weekly_operations import main as _main

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    return _main(["--workspace", str(REPOSITORY_ROOT), *(sys.argv[1:] if argv is None else argv)])


def run_week(arguments: argparse.Namespace) -> int:
    argv = []
    for key, value in vars(arguments).items():
        if value is None or value is False:
            continue
        argv.append("--" + key.replace("_", "-"))
        if value is not True:
            argv.append(str(value))
    return main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
