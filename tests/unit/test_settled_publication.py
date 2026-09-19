"""Synthetic outcome publication, with the real readers/renderers and no solver."""

import hashlib
import json
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest
from tests.unit.test_scoreboard_diagnostics import decision_inputs
from tests.unit.test_weekly_suggestion_eval import recorded

from squadopt.application import league_publication, scoreboard
from squadopt.application import settled_publication as publication
from squadopt.application.advice_record import record_member_advice
from squadopt.data.errors import DataError
from squadopt.data.snapshots import write_snapshot
from squadopt.live.ledger import write_manifest

SEASON = "2026-27"
STAMP = "2026-09-22T09:00:00Z"
IDS = tuple(range(101, 116))


def write(path: Path, document: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document), encoding="utf-8")


def inventory(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def world(
    tmp_path: Path,
    *,
    finished: bool = True,
    checked: bool = True,
    missing: int | None = None,
    standings_ids: tuple[int, ...] = IDS,
    with_standings: bool = True,
) -> publication.SettledPublicationRequest:
    accepted = tmp_path / "accepted"
    bootstrap = {
        "events": [
            {
                "id": 1,
                "deadline_time": "2026-08-21T10:00:00Z",
                "finished": True,
                "data_checked": True,
            },
            {
                "id": 4,
                "deadline_time": "2026-09-12T10:00:00Z",
                "finished": True,
                "data_checked": True,
                "average_entry_score": 69,
            },
            {
                "id": 5,
                "deadline_time": "2026-09-19T10:00:00Z",
                "finished": finished,
                "data_checked": checked,
                "average_entry_score": 40,
                "highest_score": 90,
            },
            {
                "id": 6,
                "deadline_time": "2026-09-26T10:00:00Z",
                "finished": False,
                "data_checked": False,
            },
        ],
        "elements": [{"id": i + 100, "code": i, "selected_by_percent": "10"} for i in range(1, 16)],
    }
    payloads = {
        "bootstrap-static.json": json.dumps(bootstrap).encode(),
        "event-gw05-live.json": json.dumps(
            {
                "elements": [
                    {"id": i + 100, "stats": {"total_points": 2, "minutes": 90, "starts": 1}}
                    for i in range(1, 16)
                ]
            }
        ).encode(),
    }
    if with_standings:
        payloads["league-352490-standings.json"] = json.dumps(
            {
                "league": {"id": 352490},
                "standings": {
                    "has_next": False,
                    "results": [
                        {
                            "entry": i,
                            "entry_name": "New captured name",
                            "player_name": "New name",
                            "rank": n,
                            "last_rank": n + 1,
                        }
                        for n, i in enumerate(standings_ids, 1)
                    ],
                },
            }
        ).encode()
    for entry_id in IDS:
        if entry_id != missing:
            payloads[f"entry-{entry_id}-history.json"] = json.dumps(
                {
                    "current": [
                        {"event": 5, "points": 30, "total_points": 150, "event_transfers_cost": 8}
                    ]
                }
            ).encode()
        advice_path = accepted / f"data/league/advice/{entry_id}/saf-puan/1.json"
        write(advice_path, {"payload": {"gameweek": 5, "entry_id": entry_id}})
        write(accepted / f"data/league/entries/{entry_id}.json", {"payload": {"gameweek": 5}})
        record_member_advice(
            tmp_path / "records",
            recorded(
                gameweek=5,
                entry_id=entry_id,
                digest=hashlib.sha256(advice_path.read_bytes()).hexdigest(),
            ),
        )
    metadata = write_snapshot(
        tmp_path / "snapshots", source="fpl-live", captured_at_utc=STAMP, payloads=payloads
    )
    write(
        accepted / "data/league/members.json",
        {
            "contract_version": "provisional_league_ui_v1",
            "generated_at_utc": "2026-09-18T12:00:00Z",
            "payload": {
                "season": SEASON,
                "gameweek": 5,
                "scored_gameweek": 4,
                "league_id": 352490,
                "members": [
                    {"entry_id": i, "team_name": f"Accepted {i}", "total_points": 120} for i in IDS
                ],
            },
        },
    )
    for name in ("index.json", "fixtures.json", "schema/ui_view_v1.schema.json"):
        write(accepted / "data" / name, {"accepted": name})
    write(accepted / f"data/{SEASON}/status.json", {"payload": {"next_gameweek": 5}})
    write(accepted / "data/league/series-horizon.json", {"old": "superseded history keys"})
    write(
        tmp_path / "registry.json",
        {"contract_version": "entry_registry_v1", "entries": [{"entry_id": i} for i in IDS]},
    )
    decision, projections, _ = decision_inputs()
    decision.pop("transfers")
    decision.update(
        season=SEASON,
        gameweek=5,
        deadline_utc="2026-09-19T10:00:00Z",
        snapshot_id="decision-capture",
        captured_at_utc="2026-09-18T12:00:00Z",
        model_name="fixture",
        model_version="fixture",
        feature_contract_version="fixture",
        prediction_fingerprint="fixture",
        report_contract_version="fixture",
        solver_status="OPTIMAL",
        total_cost_tenths=750,
        projected_score=120.0,
        mode="live",
    )
    projections["name"] = [f"Player {i}" for i in range(1, 16)]
    projections["team_id"] = "Club"
    projections["price_tenths"] = 50
    ledger = tmp_path / "ledger" / SEASON / "gw05"
    write(ledger / "decision.json", decision)
    projections.to_csv(ledger / "projections.csv", index=False)
    write(
        ledger / "outcome.json",
        {
            "realized_xi_score": 24.0,
            "realized_net_score": 24.0,
            "scoring_basis": "named_eleven_no_autosubs",
            "source_snapshot_id": metadata.snapshot_id,
        },
    )
    write_manifest(ledger)
    return publication.SettledPublicationRequest(
        accepted,
        tmp_path / "snapshots",
        metadata.snapshot_id,
        tmp_path / "registry.json",
        tmp_path / "records",
        tmp_path / "ledger",
        tmp_path / "candidate",
        SEASON,
        5,
    )


@pytest.fixture(autouse=True)
def no_solving(monkeypatch: pytest.MonkeyPatch) -> Iterator[Mock]:
    forbidden = Mock(side_effect=AssertionError("Settled publication must never solve"))
    monkeypatch.setattr(league_publication, "build_league_views", forbidden)
    monkeypatch.setattr(league_publication, "project", forbidden)
    monkeypatch.setattr(scoreboard, "settled_scoreboard_entries", forbidden)
    yield forbidden
    forbidden.assert_not_called()


def historical_scoreboard() -> dict[str, Any]:
    """The three non-null GW4 evidence cells a single-week fixture missed."""
    return {
        "payload": {
            "season": SEASON,
            "league_id": 352490,
            "cohort_snapshot_id": "prior-gw4-cohort",
            "cohort_picks_snapshot_id": "prior-gw4-picks",
            "gameweeks": [
                {
                    "gameweek": 4,
                    "finished": True,
                    "data_checked": True,
                    "top100": {
                        "gameweek": 4,
                        "mean_score": 100.86,
                        "basis": "net",
                        "final": True,
                        "cohort_size": 100,
                        "hit_points": 4.0,
                        "picks_snapshot_id": "prior-gw4-picks",
                    },
                    "comparisons": [
                        {
                            "kind": kind,
                            "net": net,
                            "scoring_basis": "official_autosub_captain_v2",
                            "source_snapshot_id": f"prior-gw4-{kind}",
                            "outcome_snapshot_id": "prior-gw4-outcome",
                            "diagnostics": {"captain_shortfall": -1.25},
                        }
                        for kind, net in (
                            ("base", 17.25),
                            ("elite_xi", 58.0),
                            ("ownership_template", 99.0),
                        )
                    ],
                }
            ],
        }
    }


def test_historical_cells_keep_provenance_without_entering_new_week_or_totals(
    tmp_path: Path,
) -> None:
    request = world(tmp_path)
    # Reference totals are rendered without the independent historical evidence.
    publication.publish_settled(replace(request, out_dir=tmp_path / "reference"))
    reference = json.loads((tmp_path / "reference/data/league/scoreboard.json").read_bytes())
    old = historical_scoreboard()
    write(request.accepted_dir / "data/league/scoreboard.json", old)
    accepted_bytes = inventory(request.accepted_dir)
    publication.publish_settled(request)
    result = json.loads((request.out_dir / "data/league/scoreboard.json").read_bytes())["payload"]
    four = next(row for row in result["gameweeks"] if row["gameweek"] == 4)
    five = next(row for row in result["gameweeks"] if row["gameweek"] == 5)
    prior = old["payload"]["gameweeks"][0]
    assert four["top100"] == prior["top100"]
    for cell in prior["comparisons"]:
        assert next(row for row in four["comparisons"] if row["kind"] == cell["kind"]) == cell
    for key in ("cohort_snapshot_id", "cohort_picks_snapshot_id"):
        assert result[key] == old["payload"][key]
    assert result["source_snapshot_id"] == request.snapshot_id
    assert five["top100"] is None
    for cell in five["comparisons"]:
        if cell["kind"] in {"base", "elite_xi", "ownership_template"}:
            assert cell["net"] is None and cell["source_snapshot_id"] is None
    assert result["cumulative"] == reference["payload"]["cumulative"]
    assert result["cumulative"]["members_mean_total_points"] == 150
    assert inventory(request.accepted_dir) == accepted_bytes


@pytest.mark.parametrize("defect", ["new-week", "wrong-week", "no-cohort", "unknown-kind"])
def test_historical_evidence_that_cannot_be_carried_refuses(tmp_path: Path, defect: str) -> None:
    request = world(tmp_path)
    old = historical_scoreboard()
    row = old["payload"]["gameweeks"][0]
    if defect == "new-week":
        row["gameweek"] = row["top100"]["gameweek"] = 5
    elif defect == "wrong-week":
        row["top100"]["gameweek"] = 3
    elif defect == "no-cohort":
        old["payload"]["cohort_snapshot_id"] = None
    else:
        row["comparisons"][0]["kind"] = "unapproved-comparison"
    write(request.accepted_dir / "data/league/scoreboard.json", old)
    with pytest.raises(DataError, match="Cannot carry"):
        publication.publish_settled(request)
    assert not request.out_dir.exists()


def test_real_publish_retains_every_protected_byte(tmp_path: Path) -> None:
    request = world(tmp_path)
    before = inventory(request.accepted_dir)
    inputs = {name: inventory(tmp_path / name) for name in ("snapshots", "records", "ledger")}
    result = publication.publish_settled(request)
    after = inventory(request.out_dir)
    assert inventory(request.accepted_dir) == before
    assert inputs == {name: inventory(tmp_path / name) for name in inputs}
    actual_diff = tuple(
        sorted(p for p in before.keys() | after.keys() if before.get(p) != after.get(p))
    )
    assert result.changed_files == actual_diff
    assert "data/league/series-horizon.json" in result.changed_files
    assert (
        "data/league/series-horizon.json" not in after
    )  # One settled week cannot support a horizon.
    for name, content in before.items():
        if (
            "advice/" in name
            or "entries/" in name
            or name.startswith("data/schema/")
            or name in ("data/index.json", "data/fixtures.json")
        ):
            assert after[name] == content
    members = json.loads(after["data/league/members.json"])
    assert members["payload"]["gameweek"] == members["payload"]["scored_gameweek"] == 5
    assert members["generated_at_utc"] == STAMP
    assert all(
        row["gameweek_points"] == 30 and row["transfer_cost"] == 8
        for row in members["payload"]["members"]
    )
    assert all(
        row["team_name"] == f"Accepted {row['entry_id']}" and row["movement"] == "up"
        for row in members["payload"]["members"]
    )
    assert json.loads(after[f"data/{SEASON}/status.json"])["payload"]["next_gameweek"] == 6
    board = json.loads(after["data/league/scoreboard.json"])["payload"]["gameweeks"]
    five = next(w for w in board if w["gameweek"] == 5)
    assert five["finished"] and five["data_checked"] and five["members_counted"] == 15
    for entry in IDS:
        weeks = json.loads(after[f"data/league/history/{entry}.json"])["payload"]["weeks"]
        assert weeks[0]["gameweek"] == 5 and weeks[0]["actual"]["net_points"] == 22


def assert_early_refusal(
    request: publication.SettledPublicationRequest, monkeypatch: pytest.MonkeyPatch, match: str
) -> None:
    builder = Mock(side_effect=AssertionError("Refusal must precede generation"))
    monkeypatch.setattr(publication, "build_site", builder)
    with pytest.raises(DataError, match=match):
        publication.publish_settled(request)
    builder.assert_not_called()
    assert not request.out_dir.exists()
    assert not list(request.out_dir.parent.glob("settled-*"))


def test_unfinished_week_refuses_before_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert_early_refusal(world(tmp_path, finished=False), monkeypatch, "finished AND data_checked")


def test_unchecked_week_refuses_before_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert_early_refusal(world(tmp_path, checked=False), monkeypatch, "finished AND data_checked")


def test_missing_member_outcome_refuses_before_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert_early_refusal(world(tmp_path, missing=115), monkeypatch, "entry-115-history")


def test_premature_advice_refuses_before_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = world(tmp_path)
    write(
        request.accepted_dir / "data/league/advice/101/saf-puan/hidden.json",
        {"payload": {"gameweek": 6}},
    )
    assert_early_refusal(request, monkeypatch, "hidden.json")


def test_other_record_cannot_score_accepted_advice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = world(tmp_path)
    write(
        request.accepted_dir / "data/league/advice/101/saf-puan/1.json",
        {"payload": {"gameweek": 5, "different": True}},
    )
    assert_early_refusal(request, monkeypatch, "does not match accepted advice")


def test_failure_after_generation_does_not_expose_half_candidate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = world(tmp_path)
    before = inventory(request.accepted_dir)
    monkeypatch.setattr(
        publication, "_publish_scoreboard", Mock(side_effect=DataError("broken score"))
    )
    with pytest.raises(DataError, match="broken score"):
        publication.publish_settled(request)
    assert not request.out_dir.exists() and inventory(request.accepted_dir) == before


@pytest.mark.parametrize("path", ["data/new-root.json", "data/league/entries/101.json"])
def test_new_output_outside_boundary_refuses_and_names_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    request = world(tmp_path)
    original = publication._publish_scoreboard

    def unexpected(req: Any, capture: Any, candidate: Path, ids: Any) -> Any:
        result = original(req, capture, candidate, ids)
        write(candidate / path, {"unexpected": True})
        return result

    monkeypatch.setattr(publication, "_publish_scoreboard", unexpected)
    with pytest.raises(DataError, match=path):
        publication.publish_settled(request)
    assert not request.out_dir.exists()


def test_existing_output_is_never_overwritten(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = world(tmp_path)
    with pytest.raises(DataError, match="new scratch"):
        publication.publish_settled(replace(request, out_dir=request.accepted_dir))


def test_cli_requires_explicit_inputs() -> None:
    from scripts.build_settled_site import main

    with pytest.raises(SystemExit) as error:
        main([])
    assert error.value.code == 2


def test_missing_standings_refuses_before_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert_early_refusal(world(tmp_path, with_standings=False), monkeypatch, "Missing.*standings")


@pytest.mark.parametrize(
    "ids,match", [(IDS[:-1], "missing \\[115\\]"), ((*IDS, 999), "extra \\[999\\]")]
)
def test_standings_member_set_must_match_exactly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ids: tuple[int, ...], match: str
) -> None:
    assert_early_refusal(world(tmp_path, standings_ids=ids), monkeypatch, match)


def test_missing_ledger_outcome_refuses_before_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = world(tmp_path)
    assert_early_refusal(
        replace(request, ledger_root=tmp_path / "missing-ledger"),
        monkeypatch,
        "missing-ledger.*no GW5 outcome",
    )


def test_no_predeadline_history_record_refuses_before_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = world(tmp_path)
    assert_early_refusal(
        replace(request, record_root=tmp_path / "missing-records"), monkeypatch, "member 101"
    )


def test_season_builder_cannot_smuggle_a_new_root_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = world(tmp_path)
    original = publication.build_site

    def extra(**kwargs: Any) -> Any:
        result = original(**kwargs)
        write(kwargs["out_dir"] / "data/new-needed-file.json", {"new": True})
        return result

    monkeypatch.setattr(publication, "build_site", extra)
    with pytest.raises(DataError, match=r"data/new-needed-file\.json"):
        publication.publish_settled(request)
    assert not request.out_dir.exists()


def test_missing_past_ledger_decision_refuses_before_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = world(tmp_path)
    write(
        request.accepted_dir / f"data/{SEASON}/ledger.json",
        {"payload": {"rows": [{"gameweek": 4}, {"gameweek": 5}]}},
    )
    assert_early_refusal(request, monkeypatch, "Ledger decision weeks differ")


def test_system_gw6_recommendation_also_refuses_before_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = world(tmp_path)
    write(
        request.accepted_dir / f"data/{SEASON}/gw06/recommendation.json",
        {"payload": {"gameweek": 6}},
    )
    assert_early_refusal(request, monkeypatch, "gw06/recommendation")


def test_cli_reports_the_actual_candidate_file_list(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from scripts.build_settled_site import main

    request = world(tmp_path)
    assert (
        main(
            [
                "--accepted-dir",
                str(request.accepted_dir),
                "--snapshot-root",
                str(request.snapshot_root),
                "--snapshot-id",
                request.snapshot_id,
                "--registry",
                str(request.registry_path),
                "--record-root",
                str(request.record_root),
                "--ledger-root",
                str(request.ledger_root),
                "--out",
                str(request.out_dir),
                "--season",
                SEASON,
                "--gameweek",
                "5",
            ]
        )
        == 0
    )
    output = capsys.readouterr().out
    assert STAMP in output and "data/league/members.json" in output
    assert "data/league/series-horizon.json" in output
    assert "data/league/entries/101.json" not in output
