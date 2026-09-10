"""The weekly scoreboard: our paper squad beside the league, the Top-100, and the field.

    python -m scripts.build_scoreboard --league 352490 --out web/public
    python -m scripts.build_scoreboard --league 352490 --snapshot-id <fpl-live id> \\
        --cohort-snapshot <fpl-top100 id> --elite-snapshot <fpl-elite-picks id>

Writes ``<out>/data/league/scoreboard.json`` in the provisional league envelope: one row
per gameweek whose deadline had passed when the live capture was taken, each carrying what
the files on disk prove and ``null`` where they prove nothing. Nothing is decided here; the
ledger is read, never written.

Where each number comes from, and what it is:

- ``average_entry_score`` and ``highest_score``: the game's own summary of every manager's
  week, from the live capture's bootstrap ``events[]``. Published for a finished gameweek
  only — before that the source carries ``0`` and ``null``, and a zero average is not a
  measurement.
- ``members[]``: each registered member's week from that member's own
  ``entry-<id>-history.json`` in the same capture. The history's ``points`` is gross of the
  week's transfer cost (its ``total_points`` advances by ``points - event_transfers_cost``),
  so a row carries both and ``net`` is the difference — the same net our ledger records,
  which is what makes the two columns comparable.
- ``ours``: the ledger entry for the gameweek, when one exists: the settled net and named-
  eleven score, the hit points, the projection, and the mode the decision was made in
  (``live`` decided before its deadline from a capture that run took; ``replay`` recorded
  after that deadline, or from a capture the run did not take but named). Its
  ``scoring_basis`` is ``named_eleven_no_autosubs``, and that is not FPL's own net: the
  eleven the decision named is scored as named, the game's automatic substitutions are
  not applied, and the ledger's decision carries no vice-captain to recover a captain who
  did not play. Both corrections only ever add points, so our figure reads low beside a
  member's ``points - event_transfers_cost``. Neither is computable from what the ledger
  holds — the frozen decision records the bench as a set, not in the order the game's
  autosubs walk it, and it names no vice-captain — so the basis is published rather than
  guessed.
- ``top100``: the Top-100 cohort's mean week, for the cohort capture's current gameweek
  only. The cohort is re-ranked every week, so a total is never differenced across
  captures; ``final`` says whether the gameweek was finished and checked in the cohort
  capture's own bootstrap. ``basis`` says what the mean is:

  - ``net`` — every one of ranks 1..100 was found in the elite-picks capture for that same
    gameweek, so the mean is over each member's ``entry_history.points`` minus their
    ``event_transfers_cost``. ``hit_points`` is the cost taken off across the cohort. This
    is the same net the members' and our columns carry, so the numbers compare.
  - ``gross`` — no picks capture covered the cohort, so the mean is over the standings'
    ``event_total``, which is **before** the transfer cost (in the 2026-09-07 capture,
    entry 7018833's standings row reads ``event_total 78`` while its own history reads
    ``points 78, event_transfers_cost 4``). A gross mean is not comparable with the net
    columns, and the card says so rather than letting it sit beside them unmarked.
"""

import argparse
import sys
from pathlib import Path

from squadopt.application.scoreboard import (
    OUR_SCORING_BASIS as OUR_SCORING_BASIS,
)
from squadopt.application.scoreboard import (
    SCOREBOARD_FILE as SCOREBOARD_FILE,
)
from squadopt.application.scoreboard import (
    TOP100_SIZE as TOP100_SIZE,
)
from squadopt.application.scoreboard import (
    CohortCapture as CohortCapture,
)
from squadopt.application.scoreboard import (
    CohortPicks as CohortPicks,
)
from squadopt.application.scoreboard import (
    ScoreboardPublicationRequest,
    publish_scoreboard,
)
from squadopt.application.scoreboard import (
    cohort_standings as cohort_standings,
)
from squadopt.application.scoreboard import (
    played_gameweeks as played_gameweeks,
)
from squadopt.application.scoreboard import (
    read_cohort as read_cohort,
)
from squadopt.application.scoreboard import (
    read_cohort_picks as read_cohort_picks,
)
from squadopt.application.scoreboard import (
    resolve_live_snapshot_id as resolve_live_snapshot_id,
)
from squadopt.application.scoreboard import (
    scoreboard_payload as scoreboard_payload,
)
from squadopt.application.scoreboard import (
    top100_week as top100_week,
)
from squadopt.data.errors import DataError
from squadopt.live import LedgerError

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_ROOT = REPOSITORY_ROOT / "data" / "snapshots"
REGISTRY_PATH = REPOSITORY_ROOT / "data" / "entries" / "registry.json"
LEDGER_ROOT = REPOSITORY_ROOT / "data" / "ledger"
SITE_OUT = REPOSITORY_ROOT / "web" / "public"


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--league", type=int, required=True)
    parser.add_argument("--snapshot-id", help="default: the most recent live capture")
    parser.add_argument("--snapshot-root", type=Path, default=SNAPSHOT_ROOT)
    parser.add_argument("--registry", type=Path, default=REGISTRY_PATH)
    parser.add_argument("--ledger-root", type=Path, default=LEDGER_ROOT)
    parser.add_argument("--cohort-snapshot", help="an fpl-top100 capture for the Top-100 mean")
    parser.add_argument(
        "--elite-snapshot",
        help="the fpl-elite-picks capture of that cohort's same week; without it the "
        "Top-100 mean is published gross of transfer costs and labelled gross",
    )
    parser.add_argument("--season", help="default: inferred from the capture")
    parser.add_argument("--out", type=Path, default=SITE_OUT, help="site root (web/public)")
    arguments = parser.parse_args()
    try:
        snapshot_id = resolve_live_snapshot_id(arguments.snapshot_root, arguments.snapshot_id)
        result = publish_scoreboard(
            ScoreboardPublicationRequest(
                snapshot_root=arguments.snapshot_root,
                snapshot_id=snapshot_id,
                registry_path=arguments.registry,
                ledger_root=arguments.ledger_root,
                out_dir=arguments.out,
                league_id=arguments.league,
                season=arguments.season,
                cohort_snapshot_id=arguments.cohort_snapshot,
                elite_snapshot_id=arguments.elite_snapshot,
            )
        )
    except (DataError, LedgerError, OSError, ValueError, KeyError) as error:
        print(f"build_scoreboard failed:\n  {error}", file=sys.stderr)
        return 1
    document, target, season = result.document, result.target, result.season
    payload = document["payload"]
    assert isinstance(payload, dict)
    rows = payload["gameweeks"]
    ours = [row["gameweek"] for row in rows if row["ours"] is not None]
    top100 = [row["top100"] for row in rows if row["top100"] is not None]
    cohort_line = (
        "no gameweek"
        if not top100
        else ", ".join(f"GW{week['gameweek']} {week['basis']}" for week in top100)
    )
    print(
        f"capture {snapshot_id}: {season}, gameweeks {[row['gameweek'] for row in rows]} "
        f"played; histories for {result.histories_held} of {result.registered_members} registered; "
        f"ours recorded for {ours} ({OUR_SCORING_BASIS}); Top-100 for {cohort_line}"
    )
    if any(week["basis"] == "gross" for week in top100):
        print(
            "  The Top-100 mean is gross of transfer costs: no elite-picks capture covered "
            "every one of the hundred for that week. Pass --elite-snapshot to net it."
        )
    print(f"Wrote {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
