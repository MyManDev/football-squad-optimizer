"""An empty ledger root beside a tree that already publishes decisions keeps the decisions.

The local ledger can be lost while the published tree still holds the truth. Absent and
zero are different things here: a site or scoreboard build over an empty ledger root must
not publish "no decisions" over rows the tree already carries. Where nothing is published
either, both behave as before and publish empty.
"""

import json
from pathlib import Path
from typing import Any

import pytest
from tests.unit.test_build_scoreboard import THREE_WEEKS, _bootstrap, _entry, _history
from tests.unit.test_season_ledger import _capture, _panel

from squadopt.application.scoreboard import (
    ScoreboardPublicationRequest,
    publish_scoreboard,
    scoreboard_payload,
)
from squadopt.application.site import build_site
from squadopt.data.snapshots import write_snapshot
from squadopt.live import build_recommendation, project, read_inputs, record_decision

SEASON = "2026-27"


def _published_tree(tmp_path: Path) -> Path:
    """A site built from a one-decision ledger, then that ledger's root removed."""

    snapshot = _capture(tmp_path / "snapshots")
    inputs = read_inputs(snapshot, season=SEASON)
    projection = project(inputs, _panel(players=(1001, 1004, 1012)))
    recommendation = build_recommendation(inputs, projection)
    record_decision(tmp_path / "ledger", recommendation, projection, report_text="report")
    report = build_site(ledger_root=tmp_path / "ledger", season=SEASON, out_dir=tmp_path / "site")
    assert report.decided_gameweeks == (1,) and not report.ledger_kept_from_published
    return tmp_path / "site"


def test_an_empty_ledger_root_keeps_the_published_ledger_untouched(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    site = _published_tree(tmp_path)
    ledger_path = site / "data" / SEASON / "ledger.json"
    published = ledger_path.read_bytes()

    report = build_site(ledger_root=tmp_path / "lost-ledger", season=SEASON, out_dir=site)

    assert ledger_path.read_bytes() == published, "the kept file is not rewritten"
    assert report.ledger_kept_from_published
    assert report.decided_gameweeks == (1,)
    index = json.loads((site / "data" / "index.json").read_text("utf-8"))["payload"]
    assert index["gameweeks"] == {SEASON: [1]}
    assert index["latest"]["path"] == f"{SEASON}/gw01/recommendation.json"
    assert {f"{SEASON}/ledger.json", f"{SEASON}/gw01/recommendation.json"} <= set(index["files"])
    assert all((site / "data" / name).is_file() for name in report.files)
    out = capsys.readouterr().out
    assert "kept the published" in out and "gameweeks [1]" in out


def test_an_empty_ledger_root_over_an_empty_tree_still_publishes_an_empty_ledger(
    tmp_path: Path,
) -> None:
    site = tmp_path / "site"
    report = build_site(ledger_root=tmp_path / "lost-ledger", season=SEASON, out_dir=site)
    assert not report.ledger_kept_from_published and report.decided_gameweeks == ()
    ledger = json.loads((site / "data" / SEASON / "ledger.json").read_text("utf-8"))
    assert ledger["payload"]["rows"] == [] and ledger["payload"]["decided_gameweeks"] == 0


def test_a_published_ledger_of_another_season_or_shape_is_not_kept(tmp_path: Path) -> None:
    site = _published_tree(tmp_path)
    ledger_path = site / "data" / SEASON / "ledger.json"
    document = json.loads(ledger_path.read_text("utf-8"))
    document["payload"]["season"] = "2025-26"
    ledger_path.write_text(json.dumps(document), encoding="utf-8")

    report = build_site(ledger_root=tmp_path / "lost-ledger", season=SEASON, out_dir=site)

    assert not report.ledger_kept_from_published and report.decided_gameweeks == ()
    assert json.loads(ledger_path.read_text("utf-8"))["payload"]["rows"] == []


# --- scoreboard --------------------------------------------------------------------------


def _published_row(gameweek: int) -> dict[str, Any]:
    payload = scoreboard_payload(
        season=SEASON,
        league_id=352490,
        bootstrap=_bootstrap(THREE_WEEKS),
        captured_at_utc="2026-09-07T13:14:14Z",
        source_snapshot_id="fpl-live-20260907T131414Z-db9314d00961",
        histories={},
        registered=[11],
        ledger_entries=(_entry(gameweek, mode="live", settled=True),),
        cohort=None,
        generated_at_utc="2026-09-07T13:20:00Z",
    )["payload"]
    assert isinstance(payload, dict)
    row = next(row for row in payload["gameweeks"] if row["gameweek"] == gameweek)
    assert isinstance(row["ours"], dict)
    return dict(row["ours"])


def test_the_ledger_entry_wins_over_a_published_row_and_nothing_is_invented() -> None:
    payload = scoreboard_payload(
        season=SEASON,
        league_id=352490,
        bootstrap=_bootstrap(THREE_WEEKS),
        captured_at_utc="2026-09-07T13:14:14Z",
        source_snapshot_id="fpl-live-20260907T131414Z-db9314d00961",
        histories={},
        registered=[11],
        ledger_entries=(_entry(2, mode="replay", settled=False, hits=4.0),),
        cohort=None,
        published_ours={1: _published_row(1), 2: {"net": 99.0}},
        generated_at_utc="2026-09-07T13:20:00Z",
    )["payload"]
    assert isinstance(payload, dict)
    rows = {row["gameweek"]: row for row in payload["gameweeks"]}
    assert rows[1]["ours"]["net"] == 26.0, "kept from the published scoreboard"
    assert rows[2]["ours"]["mode"] == "replay" and rows[2]["ours"]["net"] is None
    assert rows[3]["ours"] is None, "no ledger entry and no published row: none"
    assert payload["cumulative"]["ours_net"] == 26.0
    assert payload["cumulative"]["ours_gameweeks"] == [1]


def _scoreboard_world(tmp_path: Path) -> ScoreboardPublicationRequest:
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
    registry = tmp_path / "registry.json"
    registry.write_text(
        json.dumps(
            {"contract_version": "entry_registry_v1", "entries": [{"entry_id": 11, "label": "a"}]}
        ),
        encoding="utf-8",
    )
    return ScoreboardPublicationRequest(
        snapshot_root=snapshots,
        snapshot_id=live.snapshot_id,
        registry_path=registry,
        ledger_root=tmp_path / "lost-ledger",
        out_dir=tmp_path / "site",
        league_id=352490,
        season=SEASON,
        now_utc="2026-09-07T13:20:00Z",
    )


def test_an_empty_ledger_root_keeps_our_published_scoreboard_rows(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    request = _scoreboard_world(tmp_path)
    target = request.out_dir / "data" / "league" / "scoreboard.json"
    target.parent.mkdir(parents=True)
    target.write_text(
        json.dumps(
            {
                "contract_version": "provisional_league_ui_v1",
                "payload": {
                    "season": SEASON,
                    "gameweeks": [
                        {"gameweek": 1, "ours": _published_row(1)},
                        {"gameweek": 2, "ours": None},
                    ],
                },
            }
        ),
        encoding="utf-8",
    )

    result = publish_scoreboard(request)

    assert result.ours_kept_from_published == (1,)
    rows = {row["gameweek"]: row for row in result.document["payload"]["gameweeks"]}
    assert rows[1]["ours"]["net"] == 26.0 and rows[1]["ours"]["mode"] == "live"
    assert rows[2]["ours"] is None and rows[3]["ours"] is None
    assert result.document["payload"]["cumulative"]["ours_gameweeks"] == [1]
    assert "kept our published scoreboard rows for gameweeks [1]" in capsys.readouterr().out


def test_an_empty_ledger_root_with_no_published_scoreboard_publishes_no_row_of_ours(
    tmp_path: Path,
) -> None:
    result = publish_scoreboard(_scoreboard_world(tmp_path))
    assert result.ours_kept_from_published == ()
    assert all(row["ours"] is None for row in result.document["payload"]["gameweeks"])
