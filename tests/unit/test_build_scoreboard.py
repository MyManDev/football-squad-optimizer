"""The scoreboard producer's pure half, over hand-built payload bytes.

Hand-built rather than captured, for the reason ``test_build_league_site`` gives: the
captures are gitignored, and a test that needs one passes only where one exists. What is
pinned here is every rule the scoreboard rests on — a member's week is gross in the source
and net on the board, an unfinished week has no average, our row is the ledger entry with
its mode and the basis its number is on, the Top-100 mean belongs to the cohort capture's
own week and is net only when a picks capture covers all hundred, and the cumulative
figures name what they cover.
"""

import json
import sys
from pathlib import Path
from typing import Any

import pytest
import scripts.build_scoreboard as cli
from scripts.build_scoreboard import (
    OUR_SCORING_BASIS,
    CohortCapture,
    CohortPicks,
    played_gameweeks,
    read_cohort_picks,
    scoreboard_payload,
    top100_week,
)

from squadopt.data.errors import DataError
from squadopt.data.snapshots import write_snapshot
from squadopt.live import LedgerEntry

SEASON = "2026-27"
DEADLINES = {
    1: "2026-08-21T17:30:00Z",
    2: "2026-08-28T17:30:00Z",
    3: "2026-09-04T17:30:00Z",
    4: "2026-09-12T12:30:00Z",
}


def _event(gameweek: int, *, finished: bool, checked: bool | None = None, **extra: Any) -> dict:
    record: dict[str, Any] = {
        "id": gameweek,
        "deadline_time": DEADLINES[gameweek],
        "finished": finished,
        "data_checked": finished if checked is None else checked,
        # What the source carries before a week finishes: a zero, not an absence.
        "average_entry_score": 0,
        "highest_score": None,
    }
    record.update(extra)
    return record


def _bootstrap(events: list[dict[str, Any]]) -> bytes:
    return json.dumps({"events": events}).encode("utf-8")


def _history(rows: list[dict[str, Any]]) -> bytes:
    return json.dumps({"chips": [], "current": rows}).encode("utf-8")


def _picks(gameweek: int, *, points: int, cost: int) -> bytes:
    return json.dumps(
        {
            "active_chip": None,
            "automatic_subs": [],
            "entry_history": {
                "event": gameweek,
                "points": points,
                "event_transfers_cost": cost,
            },
            "picks": [],
        }
    ).encode("utf-8")


def _page(page: int, ranks: range, *, event_total: int | None = None) -> bytes:
    rows = [
        {
            "entry": 900_000 + rank,
            "rank": rank,
            "rank_sort": rank,
            "event_total": rank if event_total is None else event_total,
            "total": 300,
        }
        for rank in ranks
    ]
    return json.dumps(
        {"league": {"id": 314}, "standings": {"page": page, "has_next": True, "results": rows}}
    ).encode("utf-8")


def _entry(
    gameweek: int,
    *,
    mode: str | None,
    settled: bool,
    hits: float = 0.0,
    net: float = 26.0,
) -> LedgerEntry:
    decision: dict[str, Any] = {
        "snapshot_id": f"fpl-live-gw{gameweek:02d}",
        "projected_score": 56.1,
        "metadata": {} if mode is None else {"mode": mode},
    }
    if hits:
        decision["transfers"] = {"transfer_hit_points": hits, "chip": None}
    outcome = (
        {"realized_net_score": net, "realized_xi_score": net + hits, "transfer_hit_points": hits}
        if settled
        else None
    )
    return LedgerEntry(SEASON, gameweek, decision, outcome, Path("."))


THREE_WEEKS = [
    _event(1, finished=True, average_entry_score=50, highest_score=131),
    _event(2, finished=True, average_entry_score=81, highest_score=161),
    _event(3, finished=False),
    _event(4, finished=False),
]


def _payload(**overrides: Any) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "season": SEASON,
        "league_id": 352490,
        "bootstrap": _bootstrap(THREE_WEEKS),
        "captured_at_utc": "2026-09-07T13:14:14Z",
        "source_snapshot_id": "fpl-live-20260907T131414Z-db9314d00961",
        "histories": {},
        "registered": [11, 22],
        "ledger_entries": (),
        "cohort": None,
        "cohort_picks": None,
        "generated_at_utc": "2026-09-07T13:20:00Z",
    }
    fields.update(overrides)
    document = scoreboard_payload(**fields)
    assert document["contract_version"] == "provisional_league_ui_v1"
    assert document["source_kind"] == "live"
    payload = document["payload"]
    assert isinstance(payload, dict)
    return payload


def _rows(payload: dict[str, Any]) -> dict[int, dict[str, Any]]:
    return {row["gameweek"]: row for row in payload["gameweeks"]}


# --- members: gross in the source, net on the board ----------------------------------


def test_a_members_week_is_published_gross_and_net_from_their_own_history() -> None:
    """The history's ``points`` is gross of the transfer cost: 78 with a 4-point cost
    advances the total by 74. Our ledger row is net, so the board carries both and nets."""

    payload = _payload(
        histories={
            11: _history(
                [
                    {"event": 1, "points": 64, "total_points": 64, "event_transfers_cost": 0},
                    {"event": 2, "points": 78, "total_points": 138, "event_transfers_cost": 4},
                ]
            ),
            22: _history(
                [{"event": 1, "points": 40, "total_points": 40, "event_transfers_cost": 0}]
            ),
        }
    )

    rows = _rows(payload)
    assert rows[2]["members"] == [
        {"entry_id": 11, "points": 78, "hit_cost": 4, "net": 74, "total_points": 138}
    ]
    assert rows[1]["members_mean_net"] == pytest.approx((64 + 40) / 2)
    assert rows[1]["members_counted"] == 2
    # A member with no row for the week is omitted, not zeroed.
    assert rows[2]["members_counted"] == 1
    assert payload["histories_held"] == 2 and payload["registered_members"] == 2


def test_a_history_row_without_a_transfer_cost_has_no_net() -> None:
    payload = _payload(histories={11: _history([{"event": 1, "points": 64, "total_points": 64}])})

    member = _rows(payload)[1]["members"][0]
    assert member["hit_cost"] is None and member["net"] is None
    assert _rows(payload)[1]["members_mean_net"] is None
    assert _rows(payload)[1]["members_counted"] == 0


# --- the game's own summary ------------------------------------------------------------


def test_an_unfinished_gameweek_publishes_no_average_and_no_highest() -> None:
    """The source carries ``average_entry_score: 0`` before a week finishes; a zero average
    is not a measurement, so the row says null."""

    rows = _rows(_payload())

    assert sorted(rows) == [1, 2, 3], "played weeks: deadlines passed at capture time"
    assert rows[1]["average_entry_score"] == 50.0 and rows[1]["highest_score"] == 131.0
    assert rows[3]["finished"] is False
    assert rows[3]["average_entry_score"] is None and rows[3]["highest_score"] is None


def test_played_gameweeks_are_the_deadlines_passed_at_the_capture_instant() -> None:
    bootstrap = _bootstrap(THREE_WEEKS)
    assert played_gameweeks(bootstrap, as_of_utc="2026-08-21T17:29:59Z") == []
    # Exactly at the deadline counts as passed, the boundary next_open_deadline draws.
    assert played_gameweeks(bootstrap, as_of_utc="2026-08-21T17:30:00Z") == [1]
    assert played_gameweeks(bootstrap, as_of_utc="2026-09-07T13:14:14Z") == [1, 2, 3]


# --- our row: the ledger entry with its mode ------------------------------------------


def test_our_row_is_the_ledger_entry_with_its_mode_and_null_where_unsettled() -> None:
    payload = _payload(
        ledger_entries=(
            _entry(1, mode="live", settled=True),
            _entry(2, mode="replay", settled=False, hits=4.0),
        )
    )

    rows = _rows(payload)
    assert rows[1]["ours"] == {
        "net": 26.0,
        "xi": 26.0,
        "hits": 0.0,
        "projected": 56.1,
        "mode": "live",
        "scoring_basis": OUR_SCORING_BASIS,
        "vice_captain_named": False,
    }
    assert rows[2]["ours"] == {
        "net": None,
        "xi": None,
        "hits": 4.0,
        "projected": 56.1,
        "mode": "replay",
        "scoring_basis": OUR_SCORING_BASIS,
        "vice_captain_named": False,
    }
    assert rows[3]["ours"] is None


def test_our_row_says_its_net_is_the_named_eleven_and_names_no_vice_captain() -> None:
    """Our net is ``score_named_eleven`` minus hits: no automatic substitutions, and the
    frozen decision names no vice-captain to recover a captain who did not play. Both
    only ever add points, so the row reads low beside a member's own net — and the basis
    travels with the number rather than being left for the reader to infer."""

    ours = _rows(_payload(ledger_entries=(_entry(1, mode="live", settled=True),)))[1]["ours"]
    assert ours["scoring_basis"] == "named_eleven_no_autosubs"
    assert ours["vice_captain_named"] is False


def test_an_entry_recorded_before_the_mode_was_stamped_has_a_null_mode() -> None:
    rows = _rows(_payload(ledger_entries=(_entry(1, mode=None, settled=True),)))
    assert rows[1]["ours"]["mode"] is None


# --- the Top-100 ------------------------------------------------------------------------


def _cohort(events: list[dict[str, Any]], *, captured: str, ranks: int = 100) -> CohortCapture:
    return CohortCapture(
        snapshot_id="fpl-top100-test",
        captured_at_utc=captured,
        bootstrap=_bootstrap(events),
        pages=(_page(1, range(1, 51)), _page(2, range(51, ranks + 1))),
    )


def _cohort_picks(gameweek: int = 3, *, ranks: range = range(1, 101), cost: int = 0) -> CohortPicks:
    """A picks capture for the same hundred the pages carry, with ``event_total`` as the
    gross week: rank ``n``'s ``event_total`` is ``n``, so its net is ``n - cost``."""

    return CohortPicks(
        snapshot_id="fpl-elite-picks-test",
        gameweek=gameweek,
        net={900_000 + rank: rank - cost for rank in ranks},
        hits={900_000 + rank: cost for rank in ranks},
    )


def test_the_top100_mean_belongs_to_the_cohort_captures_own_week_only() -> None:
    """The cohort is re-ranked weekly, so its pages describe one gameweek: the last
    deadline passed when it was captured. Final only when that week is scored there."""

    scored = [
        _event(1, finished=True, average_entry_score=50, highest_score=131),
        _event(2, finished=True, average_entry_score=81, highest_score=161),
        _event(3, finished=False),
        _event(4, finished=False),
    ]
    cohort = _cohort(scored, captured="2026-09-07T13:11:12Z")

    week = top100_week(cohort)
    assert week == {
        "gameweek": 3,
        "basis": "gross",
        "mean_score": pytest.approx(5050 / 100),
        "hit_points": None,
        "picks_snapshot_id": None,
        "cohort_size": 100,
        "final": False,
    }
    rows = _rows(_payload(cohort=cohort))
    assert rows[3]["top100"] == week
    assert rows[1]["top100"] is None and rows[2]["top100"] is None

    checked = [*scored[:2], _event(3, finished=True), _event(4, finished=False)]
    assert top100_week(_cohort(checked, captured="2026-09-07T13:11:12Z"))["final"] is True
    # Finished but unchecked is not final: bonus has not landed.
    unchecked = [*scored[:2], _event(3, finished=True, checked=False), _event(4, finished=False)]
    assert top100_week(_cohort(unchecked, captured="2026-09-07T13:11:12Z"))["final"] is False


def test_the_standings_event_total_is_gross_so_the_picks_capture_is_what_nets_it() -> None:
    """A standings row's ``event_total`` is the week before the transfer cost — in the
    2026-09-07 capture, entry 7018833 reads ``event_total 78`` in the league standings and
    ``points 78, event_transfers_cost 4`` in its own history. The same is true of the
    Overall standings the cohort is read from, so the cohort's own picks capture, which
    carries each member's ``entry_history``, is what puts the mean on the members' basis."""

    cohort = _cohort(THREE_WEEKS, captured="2026-09-07T13:11:12Z")
    gross = top100_week(cohort)
    net = top100_week(cohort, _cohort_picks(cost=4))

    assert gross["basis"] == "gross" and gross["hit_points"] is None
    assert net == {
        "gameweek": 3,
        "basis": "net",
        "mean_score": pytest.approx(5050 / 100 - 4),
        "hit_points": 400.0,
        "picks_snapshot_id": "fpl-elite-picks-test",
        "cohort_size": 100,
        "final": False,
    }
    payload = _payload(cohort=cohort, cohort_picks=_cohort_picks(cost=4))
    assert _rows(payload)[3]["top100"] == net
    assert payload["cohort_picks_snapshot_id"] == "fpl-elite-picks-test"


def test_a_picks_capture_missing_one_of_the_hundred_publishes_a_gross_mean() -> None:
    """One unreadable member is not a failed capture — ``capture_elite_picks`` skips it —
    but a mean netted over 99 and grossed over the hundredth would be neither. The whole
    mean falls back to gross, and it says gross."""

    week = top100_week(
        _cohort(THREE_WEEKS, captured="2026-09-07T13:11:12Z"),
        _cohort_picks(ranks=range(1, 100), cost=4),
    )
    assert week["basis"] == "gross"
    assert week["mean_score"] == pytest.approx(5050 / 100)
    assert week["picks_snapshot_id"] is None


def test_a_picks_capture_from_another_week_is_refused_rather_than_netted() -> None:
    with pytest.raises(DataError, match="not the cohort capture's gameweek"):
        top100_week(
            _cohort(THREE_WEEKS, captured="2026-09-07T13:11:12Z"), _cohort_picks(gameweek=2)
        )


def test_a_partial_cohort_is_refused_rather_than_averaged() -> None:
    with pytest.raises(DataError, match="99 of ranks"):
        top100_week(_cohort(THREE_WEEKS, captured="2026-09-07T13:11:12Z", ranks=99))


def test_a_cohort_from_a_week_the_live_capture_has_not_played_is_refused() -> None:
    later = [
        *THREE_WEEKS[:3],
        _event(4, finished=False),
    ]
    cohort = _cohort(later, captured="2026-09-12T13:00:00Z")  # after the GW4 deadline
    with pytest.raises(DataError, match="not from the same week"):
        _payload(cohort=cohort)


def test_a_cohort_from_another_season_is_refused_not_matched_on_a_week_number() -> None:
    """A gameweek number repeats every season, so the same-week check proves nothing until
    the season is proven too.

    Nothing prunes the snapshot root, so once a season rolls over it holds cohort captures
    from both. Last season's GW2 capture against this season's GW2 live capture passes a
    number-only check, and its mean is published in this season's row marked only ``gross``
    or ``net`` — a transfer-cost basis, not a season. Both seasons come from the captures'
    own published deadlines.
    """

    last_season = [
        {**event, "deadline_time": event["deadline_time"].replace("2026-", "2025-")}
        for event in THREE_WEEKS
    ]
    cohort = _cohort(last_season, captured="2025-09-07T13:11:12Z")

    with pytest.raises(DataError, match="describes season 2025-26, not 2026-27"):
        _payload(cohort=cohort)


def test_a_cohort_from_this_season_is_still_accepted() -> None:
    payload = _payload(cohort=_cohort(THREE_WEEKS, captured="2026-09-07T13:11:12Z"))

    assert payload["cohort_snapshot_id"] == "fpl-top100-test"
    assert _rows(payload)[3]["top100"]["mean_score"] == pytest.approx(50.5)


def test_a_cohort_captured_before_any_deadline_has_no_week() -> None:
    assert top100_week(_cohort(THREE_WEEKS, captured="2026-08-01T00:00:00Z")) is None


def test_the_picks_capture_is_read_as_one_weeks_net_per_entry(tmp_path: Path) -> None:
    """``read_cohort_picks`` reads the block ``capture_elite_picks`` wrote: one gameweek,
    one ``entry_history`` per member, and a cost on every row — a mean netted from some
    rows and grossed on others would be neither."""

    snapshots = tmp_path / "snapshots"
    written = write_snapshot(
        snapshots,
        source="fpl-elite-picks",
        captured_at_utc="2026-09-07T13:11:33Z",
        payloads={
            "entry-900001-picks-gw03.json": _picks(3, points=66, cost=0),
            "entry-900002-picks-gw03.json": _picks(3, points=78, cost=4),
        },
    )

    picks = read_cohort_picks(snapshots, written.snapshot_id)
    assert picks.gameweek == 3
    assert picks.net == {900001: 66, 900002: 74}
    assert picks.hits == {900001: 0, 900002: 4}


def test_a_picks_row_without_a_transfer_cost_refuses_the_whole_capture(tmp_path: Path) -> None:
    snapshots = tmp_path / "snapshots"
    payload = json.dumps({"entry_history": {"event": 3, "points": 66}}).encode("utf-8")
    written = write_snapshot(
        snapshots,
        source="fpl-elite-picks",
        captured_at_utc="2026-09-07T13:11:33Z",
        payloads={"entry-900001-picks-gw03.json": payload},
    )
    with pytest.raises(DataError, match="event_transfers_cost"):
        read_cohort_picks(snapshots, written.snapshot_id)


# --- cumulative: each figure names what it covers --------------------------------------


def test_cumulative_figures_cover_the_finished_weeks_and_say_which_ours_covers() -> None:
    payload = _payload(
        histories={
            11: _history(
                [
                    {"event": 1, "points": 64, "total_points": 64, "event_transfers_cost": 0},
                    {"event": 2, "points": 78, "total_points": 138, "event_transfers_cost": 4},
                ]
            ),
            22: _history(
                [
                    {"event": 1, "points": 40, "total_points": 40, "event_transfers_cost": 0},
                    {"event": 2, "points": 60, "total_points": 100, "event_transfers_cost": 0},
                ]
            ),
        },
        ledger_entries=(
            _entry(1, mode="live", settled=True),
            _entry(2, mode="replay", settled=False),
        ),
    )

    assert payload["cumulative"] == {
        "through_gameweek": 2,
        "gameweeks": [1, 2],
        "ours_net": 26.0,
        "ours_gameweeks": [1],
        "members_mean_total_points": pytest.approx((138 + 100) / 2),
        "members_gameweeks": [1, 2],
        "members_counted": 2,
        "average_entry_score": 131.0,
    }


def test_cumulative_is_null_where_nothing_is_finished() -> None:
    payload = _payload(
        bootstrap=_bootstrap([_event(1, finished=False), _event(2, finished=False)]),
        captured_at_utc="2026-08-22T00:00:00Z",
    )
    assert payload["cumulative"] == {
        "through_gameweek": None,
        "gameweeks": [],
        "ours_net": None,
        "ours_gameweeks": [],
        "members_mean_total_points": None,
        "members_gameweeks": [],
        "members_counted": 0,
        "average_entry_score": None,
    }


def test_the_members_cumulative_names_the_weeks_it_covers_when_they_differ() -> None:
    """The three cumulative figures are summed over different sets, so each names its own.

    ``ours_net`` and ``average_entry_score`` are summed over the finished weeks; the
    members' figure is FPL's own running total at the last finished week, which advances
    for every week they played, finished or not. Those are the same weeks while the
    finished ones run without a gap. Leave GW2 unfinished — a postponed fixture — with GW3
    finished, and the members' column silently spans a week the other two exclude.
    """

    payload = _payload(
        bootstrap=_bootstrap(
            [
                _event(1, finished=True, average_entry_score=50, highest_score=120),
                _event(2, finished=False),
                _event(3, finished=True, average_entry_score=51, highest_score=122),
            ]
        ),
        histories={
            11: _history(
                [
                    {"event": 1, "points": 50, "total_points": 50, "event_transfers_cost": 0},
                    {"event": 2, "points": 40, "total_points": 90, "event_transfers_cost": 0},
                    {"event": 3, "points": 60, "total_points": 150, "event_transfers_cost": 0},
                ]
            )
        },
    )

    cumulative = payload["cumulative"]
    assert cumulative["gameweeks"] == [1, 3]
    assert cumulative["average_entry_score"] == 101.0
    assert cumulative["members_mean_total_points"] == 150.0
    # The one figure that spans GW2 says so, rather than sitting beside the other two
    # under a single "cumulative through GW3" label with nothing to tell them apart.
    assert cumulative["members_gameweeks"] == [1, 2, 3]


# --- the shell ---------------------------------------------------------------------------


def test_the_shell_writes_the_scoreboard_beside_the_league_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshots = tmp_path / "snapshots"
    live = write_snapshot(
        snapshots,
        source="fpl-live",
        captured_at_utc="2026-09-07T13:14:14Z",
        payloads={
            "bootstrap-static.json": _bootstrap(THREE_WEEKS),
            "entry-11-history.json": _history(
                [{"event": 1, "points": 64, "total_points": 64, "event_transfers_cost": 0}]
            ),
        },
    )
    cohort = write_snapshot(
        snapshots,
        source="fpl-top100",
        captured_at_utc="2026-09-07T13:11:12Z",
        payloads={
            "bootstrap-static.json": _bootstrap(THREE_WEEKS),
            "league-314-standings-page-01.json": _page(1, range(1, 51)),
            "league-314-standings-page-02.json": _page(2, range(51, 101)),
        },
    )
    # Rank n's standings event_total is n, gross; each took a 1-point hit, so its net is
    # n - 1 and the cohort's mean drops by exactly one.
    elite = write_snapshot(
        snapshots,
        source="fpl-elite-picks",
        captured_at_utc="2026-09-07T13:11:33Z",
        payloads={
            f"entry-{900_000 + rank}-picks-gw03.json": _picks(3, points=rank, cost=1)
            for rank in range(1, 101)
        },
    )
    registry = tmp_path / "registry.json"
    registry.write_text(
        json.dumps(
            {
                "contract_version": "entry_registry_v1",
                "entries": [{"entry_id": 11, "label": "a"}, {"entry_id": 22, "label": "b"}],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "build_scoreboard",
            "--league",
            "352490",
            "--snapshot-root",
            str(snapshots),
            "--registry",
            str(registry),
            "--ledger-root",
            str(tmp_path / "ledger"),
            "--cohort-snapshot",
            cohort.snapshot_id,
            "--elite-snapshot",
            elite.snapshot_id,
            "--out",
            str(tmp_path / "site"),
        ],
    )

    assert cli.main() == 0

    document = json.loads(
        (tmp_path / "site" / "data" / "league" / "scoreboard.json").read_text(encoding="utf-8")
    )
    payload = document["payload"]
    assert payload["source_snapshot_id"] == live.snapshot_id
    assert payload["cohort_snapshot_id"] == cohort.snapshot_id
    assert payload["season"] == SEASON
    assert payload["histories_held"] == 1 and payload["registered_members"] == 2
    rows = {row["gameweek"]: row for row in payload["gameweeks"]}
    assert rows[1]["members"][0]["net"] == 64
    assert rows[3]["top100"] == {
        "gameweek": 3,
        "basis": "net",
        "mean_score": pytest.approx(50.5 - 1),
        "hit_points": 100.0,
        "picks_snapshot_id": elite.snapshot_id,
        "cohort_size": 100,
        "final": False,
    }
    assert all(row["ours"] is None for row in rows.values()), "no ledger, no row of ours"


def test_the_shell_refuses_an_empty_registry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshots = tmp_path / "snapshots"
    write_snapshot(
        snapshots,
        source="fpl-live",
        captured_at_utc="2026-09-07T13:14:14Z",
        payloads={"bootstrap-static.json": _bootstrap(THREE_WEEKS)},
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "build_scoreboard",
            "--league",
            "352490",
            "--snapshot-root",
            str(snapshots),
            "--registry",
            str(tmp_path / "missing.json"),
            "--ledger-root",
            str(tmp_path / "ledger"),
            "--out",
            str(tmp_path / "site"),
        ],
    )
    assert cli.main() == 1
    assert not (tmp_path / "site").exists()
