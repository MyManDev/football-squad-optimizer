"""Process boundary for the server's native window solver.

Run the driver by file path: importing ``planning`` executes its public initializer,
which loads OR-Tools and would collide with highspy's Linux library of the same name.
Only this composition root starts the child; the decision core receives a callback.
"""

from __future__ import annotations

import json
import math
import runpy
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from time import perf_counter
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    # Annotations only: the child runs this file by path and must never import
    # ``squadopt.planning``, whose initializer loads OR-Tools.
    from squadopt.planning.native_highs import NativeWindowOutcome

#: How much of the child's standard error an error message carries: the end of a
#: traceback names the failure, and the rest would only lengthen a receipt line.
STDERR_TAIL_CHARACTERS = 600
#: The version probe imports highspy and builds no model, so it needs seconds, not a
#: window's wall ceiling.
PROBE_SECONDS = 60.0


def _tail(stream: str | bytes | None) -> str:
    if stream is None:
        return ""
    text = stream.decode("utf-8", "replace") if isinstance(stream, bytes) else stream
    text = " ".join(text.split())
    return text[-STDERR_TAIL_CHARACTERS:]


def _with_tail(message: str, stderr: str | bytes | None) -> str:
    tail = _tail(stderr)
    return f"{message} Child stderr: {tail}" if tail else message


def _run_child(request: Mapping[str, Any], seconds: float) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            [sys.executable, str(Path(__file__).resolve())],
            input=json.dumps(request),
            text=True,
            capture_output=True,
            timeout=seconds if math.isfinite(seconds) else None,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise TimeoutError(
            _with_tail(f"The native window reached its wall ceiling of {seconds:g}s.", error.stderr)
        ) from error
    if completed.returncode != 0:
        raise RuntimeError(
            _with_tail(
                f"The isolated native window solver failed with exit code {completed.returncode}.",
                completed.stderr,
            )
        )
    try:
        result = json.loads(completed.stdout)
    except ValueError as error:
        raise ValueError(
            _with_tail(f"The native window returned unreadable output ({error}).", completed.stderr)
        ) from error
    if not isinstance(result, dict):
        raise ValueError("The native window returned no result object.")
    return result


def execute_native_window(packet: Mapping[str, Any], seconds: float) -> Mapping[str, Any]:
    """Solve one exported window in a fresh interpreter, inside ``seconds`` of wall time."""

    if seconds <= 0:
        raise TimeoutError("The native window has no wall time remaining.")
    return _run_child({"model": packet, "seconds": seconds}, seconds)


def native_window_version(seconds: float = PROBE_SECONDS) -> str:
    """The HiGHS version the isolated child loads in this environment, or an error.

    The weekly preflight asks this before anything is captured or solved, so a missing or
    different highspy is named then rather than discovered as a fallback on every window.
    """

    version = _run_child({"probe": True}, seconds).get("version")
    if not isinstance(version, str):
        raise ValueError("The native window probe reported no version.")
    return version


def summarize_native_windows(
    outcomes: Sequence[NativeWindowOutcome],
) -> list[dict[str, object]]:
    """One row per window length: how many searches each backend answered, and why not.

    The rows are what the weekly receipt, its run log and the API worker's job log carry.
    Fallback reasons are counted by their text, so a reason shared by every member's
    windows reads once with its count.
    """

    rows: list[dict[str, object]] = []
    for weeks in sorted({outcome.weeks for outcome in outcomes}):
        listed = [outcome for outcome in outcomes if outcome.weeks == weeks]
        reasons: dict[str, int] = {}
        for outcome in listed:
            if outcome.fallback_reason:
                reasons[outcome.fallback_reason] = reasons.get(outcome.fallback_reason, 0) + 1
        rows.append(
            {
                "weeks": weeks,
                "solves": len(listed),
                "native": sum(1 for outcome in listed if outcome.fallback_reason == ""),
                "fallback": sum(1 for outcome in listed if outcome.fallback_reason != ""),
                "backends": sorted({outcome.backend for outcome in listed}),
                "native_versions": sorted(
                    {outcome.version for outcome in listed if outcome.version is not None}
                ),
                "fallback_reasons": dict(sorted(reasons.items())),
            }
        )
    return rows


def main() -> None:
    started = perf_counter()
    packet = json.load(sys.stdin)
    driver = Path(__file__).parents[1] / "planning" / "native_highs.py"
    namespace = runpy.run_path(str(driver), run_name="_squadopt_native_highs")
    if any(name == "ortools" or name.startswith("ortools.") for name in sys.modules):
        raise RuntimeError("The native child unexpectedly loaded OR-Tools.")
    if packet.get("probe") is True:
        result = namespace["native_version"]()
    else:
        result = namespace["native_solve"](
            packet["model"], max(0.0, float(packet["seconds"]) - (perf_counter() - started))
        )
    print(json.dumps(result, allow_nan=False))


if __name__ == "__main__":
    main()
