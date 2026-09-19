"""Before the 147-fold sweep is run: could its answer change anything for this league?

    python -m scripts.measure_rank_tail_selector_inertness --league 352490

The tail-mean rank criterion pre-registered in ``docs/rank_tail_selector_prereg.md`` reads
each rival's side off the captured standings gap against the published band edge
(``application/strategies/rule.py::band_edge_points``). A rival inside the band contributes
its full mean, and a fold in which **every** rival is inside the band reproduces today's mean
selector exactly, arm for arm -- that is the null property
``tests/unit/test_rank_tail_selector.py`` pins.

So there is a cheaper question than the sweep, and it should be asked first: on the standings
this league actually has, how many rivals are outside the band, and from which gameweek? If
the answer is none, then whatever the sweep says, wiring the criterion changes no member's
recommendation until the answer stops being none.

This is **not** the pre-registered measurement. It reads no development fold, runs no
scenario draw and scores nothing against an outcome. It is a precondition reading, and the
record says so in its own contract name.

Two honest limits belong with the number. The standings are held fixed at the capture while
the band edge shrinks with the weeks remaining, so the crossing gameweek this reports is the
one implied by *today's* spread; real gaps widen over a season and the true crossing comes
earlier. And the band's scale constant is thin by its own declaration --
``WEEKLY_POINTS_DIFFERENTIAL_POINTS`` is 21.2 from 315 pair-weeks over three gameweeks
(``rule.py:52-63``) -- so the reading is as provisional as that constant is.

Reads the capture; writes nothing to it and nothing under any data directory.
"""

import argparse
import json
import statistics
from itertools import permutations
from pathlib import Path
from time import perf_counter

from scripts._experiment_cli import REPOSITORY_ROOT, write_json, write_text

from squadopt.application.strategies.rule import (
    BAND_EDGE_DIFFERENTIALS,
    SEASON_FINAL_GAMEWEEK,
    STRATEGY_RULE_ID,
    WEEKLY_POINTS_DIFFERENTIAL_POINTS,
    band_edge_points,
    gameweeks_remaining,
)
from squadopt.experiments.rank_tail_selector import (
    RANK_TAIL_SELECTOR_CONTRACT_VERSION,
    TAIL_FRACTION_GRID,
    TailSide,
    select_rank_tail_candidate,
    tail_side_from_gap,
)

INERTNESS_CONTRACT_VERSION = "rank_tail_selector_inertness_v1"
SNAPSHOT_ROOT = REPOSITORY_ROOT / "data" / "snapshots"

#: The shape the design's own tractability claim was stated at, timed here rather than
#: taken on trust: sixteen candidates, fourteen rivals, one thousand scenarios.
CLAIMED_SHAPE = (16, 14, 1000)
TIMING_REPEATS = 7


def _totals(snapshot_root: Path, league: int, snapshot_id: str | None) -> tuple[int, ...]:
    """Every registered member's league total from the most recent live capture."""

    captures = sorted(
        path for path in snapshot_root.glob("fpl-live-*") if (path / "payloads").is_dir()
    )
    if snapshot_id is not None:
        captures = [path for path in captures if path.name == snapshot_id]
    if not captures:
        raise SystemExit(f"No live capture found under {snapshot_root}.")
    payload = captures[-1] / "payloads" / f"league-{league}-standings.json"
    if not payload.is_file():
        raise SystemExit(f"{payload} does not exist; the capture did not read this league.")
    document = json.loads(payload.read_text(encoding="utf-8"))
    rows = document["standings"]["results"]
    return tuple(sorted((int(row["total"]) for row in rows), reverse=True))


def _sides_by_gameweek(totals: tuple[int, ...]) -> list[dict[str, object]]:
    """How many ordered member pairs sit outside the band, week by week."""

    pairs = list(permutations(totals, 2))
    rows: list[dict[str, object]] = []
    for gameweek in range(1, SEASON_FINAL_GAMEWEEK + 1):
        edge = band_edge_points(gameweeks_remaining(gameweek))
        counts = dict.fromkeys(TailSide, 0)
        for mine, theirs in pairs:
            counts[tail_side_from_gap(float(mine - theirs), edge)] += 1
        rows.append(
            {
                "gameweek": gameweek,
                "band_edge_points": edge,
                "ordered_pairs": len(pairs),
                "level_pairs": counts[TailSide.LEVEL],
                "behind_pairs": counts[TailSide.BEHIND],
                "ahead_pairs": counts[TailSide.AHEAD],
            }
        )
    return rows


def _criterion_seconds() -> dict[str, float]:
    """Time the criterion itself at the claimed shape, on fixed arrays."""

    import random

    candidates, rivals, scenarios = CLAIMED_SHAPE
    generator = random.Random(0)
    candidate_rows = [
        [float(generator.randint(20, 110)) for _ in range(scenarios)] for _ in range(candidates)
    ]
    rival_rows = [
        [float(generator.randint(20, 110)) for _ in range(scenarios)] for _ in range(rivals)
    ]
    sides = [
        (TailSide.BEHIND, TailSide.LEVEL, TailSide.AHEAD)[index % 3] for index in range(rivals)
    ]
    elapsed: list[float] = []
    for _ in range(TIMING_REPEATS):
        started = perf_counter()
        select_rank_tail_candidate(
            candidate_rows, rival_rows, sides, tail_fraction=TAIL_FRACTION_GRID[0]
        )
        elapsed.append(perf_counter() - started)
    return {"median_seconds": statistics.median(elapsed), "minimum_seconds": min(elapsed)}


def _markdown(record: dict[str, object]) -> str:
    rows = list(record["by_gameweek"])  # type: ignore[call-overload]
    first = record["first_gameweek_with_a_pair_outside_the_band"]
    timing = dict(record["criterion_cost"])  # type: ignore[call-overload]
    lines = [
        "# The tail-mean rank criterion, against this league's own standings",
        "",
        "Not the pre-registered measurement. `docs/rank_tail_selector_prereg.md` registers a",
        "147-fold paired sweep; this is the precondition that should be read before that sweep",
        "is worth running, and it reads no development fold and scores nothing.",
        "",
        f"- Members in the capture: **{record['members']}**; ordered member pairs: "
        f"**{record['ordered_pairs']}**",
        f"- Widest gap in the captured standings: **{record['widest_gap_points']} points**",
        f"- Band: `{STRATEGY_RULE_ID}`, edge "
        f"{BAND_EDGE_DIFFERENTIALS} x {WEEKLY_POINTS_DIFFERENTIAL_POINTS} x sqrt(weeks left)",
        "",
        "## How to reproduce it",
        "",
        "```",
        "python -m scripts.measure_rank_tail_selector_inertness --league 352490",
        "```",
        "",
        "## What it establishes",
        "",
        "Holding the captured standings fixed, **no member pair leaves the band until",
        f"gameweek {first}**. A rival inside the band contributes its full mean, so on every",
        "earlier week the criterion returns today's pick for every member at every arm. Wiring",
        "it would change nothing for this league over that stretch, whatever the sweep says.",
        "",
        "| Gameweek | Band edge (points) | Pairs outside the band |",
        "| --- | --- | --- |",
    ]
    for row in rows:
        outside = int(row["ordered_pairs"]) - int(row["level_pairs"])
        if int(row["gameweek"]) % 4 == 0 or outside:
            lines.append(
                f"| {row['gameweek']} | {row['band_edge_points']} | "
                f"{outside} of {row['ordered_pairs']} |"
            )
    lines += [
        "",
        "## The criterion's own cost",
        "",
        f"At {CLAIMED_SHAPE[0]} candidates, {CLAIMED_SHAPE[1]} rivals and {CLAIMED_SHAPE[2]} "
        "scenarios, one selection takes a median "
        f"**{timing['median_seconds'] * 1000:.1f} ms** over {TIMING_REPEATS} repeats "
        f"(minimum {timing['minimum_seconds'] * 1000:.1f} ms), in the pure-Python",
        "implementation this module ships. Fifteen members is that many times over, so the",
        "criterion is not what would make a weekly run expensive. The design's own estimate for",
        "this shape was 2.84 ms, so the figure to plan against is the measured one.",
        "",
        "## Limits",
        "",
        "- The standings are frozen at the capture while the edge shrinks with the weeks left.",
        "  Real gaps widen over a season, so the crossing week here is an upper bound on when",
        "  the criterion starts to bite, not a forecast of it.",
        "- `WEEKLY_POINTS_DIFFERENTIAL_POINTS` is 21.2 from 315 pair-weeks over three",
        "  gameweeks (`rule.py:52-63`). The inertness above is a property of that constant, and",
        "  it is the constant this reading puts a question against, not the criterion.",
        "- No probability, quantile or rate is computed or published here; the table is counts.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--league", type=int, required=True)
    parser.add_argument("--snapshot-root", type=Path, default=SNAPSHOT_ROOT)
    parser.add_argument("--snapshot-id")
    parser.add_argument(
        "--json-output",
        type=Path,
        default=REPOSITORY_ROOT / "docs" / "rank_tail_selector_inertness.json",
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=REPOSITORY_ROOT / "docs" / "rank_tail_selector_inertness.md",
    )
    arguments = parser.parse_args()

    totals = _totals(arguments.snapshot_root, arguments.league, arguments.snapshot_id)
    rows = _sides_by_gameweek(totals)
    outside = [row for row in rows if int(row["level_pairs"]) != int(row["ordered_pairs"])]
    record: dict[str, object] = {
        "artifact_type": "rank_tail_selector_inertness",
        "contract_version": INERTNESS_CONTRACT_VERSION,
        "criterion_contract_version": RANK_TAIL_SELECTOR_CONTRACT_VERSION,
        "strategy_rule_id": STRATEGY_RULE_ID,
        "is_the_preregistered_measurement": False,
        "measurement_only": True,
        "gate_evidence": False,
        "locked_holdout_accessed": False,
        "members": len(totals),
        "ordered_pairs": len(totals) * (len(totals) - 1),
        "widest_gap_points": max(totals) - min(totals),
        "first_gameweek_with_a_pair_outside_the_band": (
            int(outside[0]["gameweek"]) if outside else None
        ),
        "by_gameweek": rows,
        "criterion_cost": _criterion_seconds(),
        "criterion_cost_shape": {
            "candidates": CLAIMED_SHAPE[0],
            "rivals": CLAIMED_SHAPE[1],
            "scenarios": CLAIMED_SHAPE[2],
            "repeats": TIMING_REPEATS,
        },
    }
    write_json(arguments.json_output, record)
    write_text(arguments.markdown_output, _markdown(record))
    print(f"Wrote {arguments.json_output} and {arguments.markdown_output}.")
    return 0


if __name__ == "__main__":  # pragma: no cover - shell entry point
    raise SystemExit(main())
