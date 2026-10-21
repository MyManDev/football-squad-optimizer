"""Process boundary for the server's native window solver.

Run the driver by file path: importing ``planning`` executes its public initializer,
which loads OR-Tools and would collide with highspy's Linux library of the same name.
Only this composition root starts the child; the decision core receives a callback.
"""

from __future__ import annotations

import json
import runpy
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from time import perf_counter
from typing import Any


def execute_native_window(packet: Mapping[str, Any], seconds: float) -> Mapping[str, Any]:
    if seconds <= 0:
        raise TimeoutError("The native window has no wall time remaining.")
    try:
        completed = subprocess.run(
            [sys.executable, str(Path(__file__).resolve())],
            input=json.dumps({"model": packet, "seconds": seconds}),
            text=True,
            capture_output=True,
            timeout=seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise TimeoutError("The native window reached its wall ceiling.") from error
    if completed.returncode != 0:
        raise RuntimeError("The isolated native window solver failed.")
    result = json.loads(completed.stdout)
    if not isinstance(result, dict):
        raise ValueError("The native window returned no result object.")
    return result


def main() -> None:
    started = perf_counter()
    packet = json.load(sys.stdin)
    driver = Path(__file__).parents[1] / "planning" / "native_highs.py"
    namespace = runpy.run_path(str(driver), run_name="_squadopt_native_highs")
    if any(name == "ortools" or name.startswith("ortools.") for name in sys.modules):
        raise RuntimeError("The native child unexpectedly loaded OR-Tools.")
    result = namespace["native_solve"](
        packet["model"], max(0.0, float(packet["seconds"]) - (perf_counter() - started))
    )
    print(json.dumps(result, allow_nan=False))


if __name__ == "__main__":
    main()
