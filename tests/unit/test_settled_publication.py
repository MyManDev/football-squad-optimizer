"""Synthetic outcome publication, with the real readers/renderers and no solver."""

import hashlib
import json
import stat
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest
from tests.unit.test_check_league_tree import _tree as clean_league_tree
from tests.unit.test_scoreboard_diagnostics import decision_inputs
from tests.unit.test_weekly_suggestion_eval import recorded

from squadopt.application import league_publication, scoreboard, site
from squadopt.application import settled_publication as publication
from squadopt.application.advice_record import record_member_advice
from squadopt.application.contract import ui_view_schema
from squadopt.application.fixtures_view import fixtures_schema
from squadopt.application.live_score import live_score_schema
from squadopt.application.views import SiteIndex, ViewEnvelope
from squadopt.data.errors import DataError
from squadopt.data.snapshots import write_snapshot
from squadopt.live.ledger import write_manifest

SEASON = "2026-27"
STAMP = "2026-09-22T09:00:00Z"
IDS = tuple(range(101, 116))
#: What the accepted decision publish's root index names: the files the candidate carries
#: once the season builder has run, as ``build_site`` lists them (status is not listed).
FROZEN_FILES = (
    f"{SEASON}/gw05/live.json",
    f"{SEASON}/gw05/pool.json",
    f"{SEASON}/gw05/recommendation.json",
    f"{SEASON}/league.json",
    f"{SEASON}/ledger.json",
    "fixtures.json",
    "schema/fixtures_v1.schema.json",
    "schema/live_score_v1.schema.json",
    "schema/ui_view_v1.schema.json",
)


def write(path: Path, document: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document), encoding="utf-8")


def frozen_index(
    files: tuple[str, ...] = FROZEN_FILES,
    weeks: tuple[int, ...] = (5,),
    latest: int | None = 5,
) -> dict[str, Any]:
    index = SiteIndex(
        generated_at_utc="2026-09-18T12:00:00Z",
        seasons=(SEASON,),
        gameweeks={SEASON: weeks},
        latest=(
            None
            if latest is None
            else {
                "season": SEASON,
                "gameweek": latest,
                "path": f"{SEASON}/gw{latest:02d}/recommendation.json",
            }
        ),
        schema_path="schema/ui_view_v1.schema.json",
        files=files,
    )
    return ViewEnvelope(payload=index.to_dict(), generated_at_utc="2026-09-18T12:00:00Z").to_dict()


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
        "teams": [
            {"id": 1, "name": "Arsenal", "short_name": "ARS"},
            {"id": 2, "name": "Chelsea", "short_name": "CHE"},
        ],
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
        "fixtures.json": json.dumps(
            [
                {
                    "id": 50,
                    "event": 5,
                    "team_h": 1,
                    "team_a": 2,
                    "finished": True,
                    "kickoff_time": "2026-09-20T14:00:00Z",
                    "team_h_score": 2,
                    "team_a_score": 1,
                }
            ]
        ).encode(),
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
        # All advice envelope shapes in the published member menu must survive
        # preflight and remain byte-identical, not just the plain plan.
        for variant in (
            "saf-puan/hoca-sozu.json",
            "saf-puan/top100-10.json",
            "saf-puan/top100-10-hoca-sozu.json",
            "yakala/1/102.json",
            "index.json",
        ):
            write(
                advice_path.parents[1] / variant,
                {
                    "contract_version": "provisional_league_ui_v1",
                    "payload": {"gameweek": 5, "entry_id": entry_id, "fixture_variant": variant},
                },
            )
        write(accepted / f"data/league/entries/{entry_id}.json", {"payload": {"gameweek": 5}})
        record_member_advice(
            tmp_path / "records",
            recorded(
                gameweek=5,
                entry_id=entry_id,
                digest=hashlib.sha256(
                    json.dumps(
                        json.loads(advice_path.read_bytes())["payload"],
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode()
                ).hexdigest(),
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
    # The schemas the accepted tree froze, and a root index naming what it served.
    for name, schema in (
        ("ui_view_v1", ui_view_schema()),
        ("live_score_v1", live_score_schema()),
        ("fixtures_v1", fixtures_schema()),
    ):
        write(accepted / f"data/schema/{name}.schema.json", schema)
    write(accepted / "data/index.json", frozen_index())
    write(accepted / "data/fixtures.json", {"accepted": "fixtures.json"})
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
                    ]
                    + [
                        {"kind": kind, "net": 9999, "source_snapshot_id": "old-ordinary"}
                        for kind in ("system", "league_mean", "game_mean")
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
        actual = next(row for row in four["comparisons"] if row["kind"] == cell["kind"])
        if cell["kind"] in {"system", "league_mean", "game_mean"}:
            reference_four = next(
                row for row in reference["payload"]["gameweeks"] if row["gameweek"] == 4
            )
            assert actual == next(
                row for row in reference_four["comparisons"] if row["kind"] == cell["kind"]
            )
            assert actual != cell
        else:
            assert actual == cell
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
    # Reformatting or a new envelope clock must not be confused with new advice.
    path = request.accepted_dir / "data/league/advice/101/saf-puan/1.json"
    document = json.loads(path.read_text())
    document["generated_at_utc"] = "2026-09-18T12:01:00Z"
    path.write_text(json.dumps(document, indent=4))
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
    assert "data/fixtures.json" in result.changed_files
    fixtures = json.loads(after["data/fixtures.json"])["payload"]
    assert fixtures["source_snapshot_id"] == request.snapshot_id
    assert fixtures["current_gameweek"] == 6
    five_fixtures = next(w for w in fixtures["gameweeks"] if w["gameweek"] == 5)
    assert five_fixtures["fixtures"][0]["home_score"] == 2
    assert five_fixtures["fixtures"][0]["away_score"] == 1
    assert five_fixtures["fixtures"][0]["finished"] is True
    assert (
        "data/league/series-horizon.json" not in after
    )  # One settled week cannot support a horizon.
    for name, content in before.items():
        if (
            "advice/" in name
            or "entries/" in name
            or name.startswith("data/schema/")
            or name == "data/index.json"
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
    assert not list(request.out_dir.parent.glob("settled-*"))


@pytest.mark.parametrize(
    "path",
    [
        "data/new-root.json",
        "data/league/entries/101.json",
        "data/league/advice/101/saf-puan/1.json",
        f"data/{SEASON}/advice/retained.json",
    ],
)
@pytest.mark.parametrize("delete", [False, True])
def test_new_output_outside_boundary_refuses_and_names_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, path: str, delete: bool
) -> None:
    request = world(tmp_path)
    # The season-prefix case also kills removal of the global advice denial:
    # without it the broad season allowance would admit this mutation.
    if not (request.accepted_dir / path).exists() and (delete or "advice" in Path(path).parts):
        write(request.accepted_dir / path, {"payload": {"gameweek": 5}})
    original = publication._publish_scoreboard

    def unexpected(req: Any, capture: Any, candidate: Path, ids: Any) -> Any:
        result = original(req, capture, candidate, ids)
        if delete:
            (candidate / path).unlink()
        else:
            write(candidate / path, {"unexpected": True})
        return result

    monkeypatch.setattr(publication, "_publish_scoreboard", unexpected)
    with pytest.raises(DataError, match=path):
        publication.publish_settled(request)
    assert not request.out_dir.exists()
    assert not list(request.out_dir.parent.glob("settled-*"))


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


def cli_arguments(request: publication.SettledPublicationRequest) -> list[str]:
    return [
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


def test_cli_reports_the_actual_candidate_file_list(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    import scripts.build_settled_site as cli

    request = world(tmp_path)
    # The synthetic advice here is not a publishable menu; the tree check's own wiring
    # is held to a real league tree below.
    checked: list[Path] = []
    monkeypatch.setattr(cli, "run_checks", lambda tree: checked.append(Path(tree.root)) or [])
    assert cli.main(cli_arguments(request)) == 0
    output = capsys.readouterr().out
    assert STAMP in output and "data/league/members.json" in output
    assert "data/league/series-horizon.json" in output
    assert "data/league/entries/101.json" not in output
    # The candidate was checked where it was generated, before it was written.
    assert len(checked) == 1 and checked[0].name == "data"
    assert checked[0].parents[2] == request.out_dir.parent
    assert checked[0].parent != request.out_dir
    # Every check it ran is printed, and no check is left for the operator to run.
    rebuilt = len(list((request.out_dir / "data" / SEASON).rglob("*.json"))) + 1
    assert "Checked before the candidate was written:" in output
    assert f"  {rebuilt} rebuilt documents match the frozen schemas" in output
    assert f"  data/fixtures.json comes from {request.snapshot_id}" in output
    assert "  the frozen data/index.json names the candidate's" in output
    assert "  the league tree check found nothing" in output
    assert "python -m scripts.check_league_tree" not in output
    changed = output.split("Changed files (post this list before a site PR):\n")[1].splitlines()
    season_count = sum(name.startswith(f"data/{SEASON}/") for name in changed)
    assert f"Changed file count: {len(changed)} ({season_count} season documents)" in output


def test_cli_refuses_a_candidate_the_league_tree_check_finds_fault_with(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    import scripts.build_settled_site as cli

    request = world(tmp_path)
    monkeypatch.setattr(
        cli, "run_checks", lambda tree: ["101: advice/101/saf-puan/3.json not published"]
    )
    assert cli.main(cli_arguments(request)) == 1
    error = capsys.readouterr().err
    assert "Settled publication refused: The candidate fails the league tree check" in error
    assert "101: advice/101/saf-puan/3.json not published" in error
    assert not request.out_dir.exists()
    assert not list(request.out_dir.parent.glob("settled-*"))


def test_cli_tree_check_is_the_release_checker_on_the_candidate(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from scripts.build_settled_site import league_tree_findings

    data = tmp_path / "data"
    clean_league_tree(data)
    assert league_tree_findings(data) == []
    (data / "league/advice/1/saf-puan/3.json").unlink()
    assert league_tree_findings(data) == ["1: advice/1/saf-puan/3.json not published"]
    assert f"League tree check on the candidate before it is written ({data})" in (
        capsys.readouterr().out
    )


def test_missing_past_week_with_only_ordinary_cells_refuses(tmp_path: Path) -> None:
    request = world(tmp_path)
    old = historical_scoreboard()
    old["payload"]["gameweeks"].append(
        {"gameweek": 3, "comparisons": [{"kind": "system", "net": 45}], "top100": None}
    )
    write(request.accepted_dir / "data/league/scoreboard.json", old)
    with pytest.raises(DataError, match="GW3 is absent from capture"):
        publication.publish_settled(request)
    assert not request.out_dir.exists()
    assert not list(request.out_dir.parent.glob("settled-*"))


def test_other_outcome_capture_in_history_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = world(tmp_path)
    original = publication.review_member_weeks

    def different_capture(**kwargs: Any) -> Any:
        reviews = original(**kwargs)
        reviews[101] = tuple(
            replace(row, outcome_snapshot_id="another-capture") for row in reviews[101]
        )
        return reviews

    monkeypatch.setattr(publication, "review_member_weeks", different_capture)
    assert_early_refusal(request, monkeypatch, "101 history did not settle on the named capture")


@pytest.mark.parametrize("link_kind", ["symlink", "windows-reparse"])
def test_accepted_link_refuses_before_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, link_kind: str
) -> None:
    request = world(tmp_path)
    target = request.accepted_dir / "data/index.json"
    # Exercise both real metadata predicates without needing Windows symlink
    # privilege or creating a junction the test runner then has to remove.
    if link_kind == "symlink":
        original_link = Path.is_symlink
        monkeypatch.setattr(Path, "is_symlink", lambda p: p == target or original_link(p))
    else:
        original_stat = Path.lstat

        def reparse(p: Path) -> Any:
            result = original_stat(p)
            return (
                SimpleNamespace(
                    st_mode=result.st_mode, st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT
                )
                if p == target
                else result
            )

        monkeypatch.setattr(Path, "lstat", reparse)
    assert_early_refusal(request, monkeypatch, "contains a link: data")


def test_accepted_tree_change_during_generation_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = world(tmp_path)
    original = publication._publish_scoreboard

    def changed_input(req: Any, capture: Any, candidate: Path, ids: Any) -> None:
        original(req, capture, candidate, ids)
        write(request.accepted_dir / "data/index.json", {"changed": "during generation"})

    monkeypatch.setattr(publication, "_publish_scoreboard", changed_input)
    with pytest.raises(DataError, match="accepted tree changed during generation"):
        publication.publish_settled(request)
    assert not request.out_dir.exists()
    assert not list(request.out_dir.parent.glob("settled-*"))


def assert_refused_before_writing(request: publication.SettledPublicationRequest) -> None:
    assert not request.out_dir.exists()
    assert not list(request.out_dir.parent.glob("settled-*"))


def test_every_rebuilt_document_is_checked_against_the_frozen_schemas(tmp_path: Path) -> None:
    request = world(tmp_path)
    result = publication.publish_settled(request)
    season_documents = list((request.out_dir / "data" / SEASON).rglob("*.json"))
    # Three week views, the ledger, the league comparison and the status; the fixture
    # list makes seven.
    assert len(season_documents) == 6
    assert result.checks == (
        "7 rebuilt documents match the frozen schemas",
        f"data/fixtures.json comes from {request.snapshot_id}",
        f"the frozen data/index.json names the candidate's {len(FROZEN_FILES)} files and weeks",
    )


def test_a_rebuilt_view_whose_shape_moved_since_the_accepted_publish_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = world(tmp_path)
    original = publication.build_site

    def moved(**kwargs: Any) -> Any:
        result = original(**kwargs)
        path = kwargs["out_dir"] / f"data/{SEASON}/gw05/recommendation.json"
        document = json.loads(path.read_bytes())
        document["payload"]["field_the_frozen_schema_never_had"] = 1
        write(path, document)
        return result

    monkeypatch.setattr(publication, "build_site", moved)
    with pytest.raises(
        DataError,
        match=rf"data/{SEASON}/gw05/recommendation\.json does not match the frozen "
        r"data/schema/ui_view_v1\.schema\.json",
    ):
        publication.publish_settled(request)
    assert_refused_before_writing(request)


def test_a_rebuilt_document_with_no_frozen_schema_refuses(tmp_path: Path) -> None:
    request = world(tmp_path)
    (request.accepted_dir / "data/schema/live_score_v1.schema.json").unlink()
    with pytest.raises(
        DataError,
        match=r"live_score_v1, and the accepted tree froze no "
        r"data/schema/live_score_v1\.schema\.json",
    ):
        publication.publish_settled(request)
    assert_refused_before_writing(request)


def test_a_fixture_list_the_outcome_capture_did_not_refresh_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = world(tmp_path)
    # The accepted tree serves the decision capture's fixture list, and this capture's
    # list cannot be read: the season builder prints a line and writes none.
    publication.publish_settled(replace(request, out_dir=tmp_path / "reference"))
    fixtures = json.loads((tmp_path / "reference/data/fixtures.json").read_bytes())
    fixtures["payload"]["source_snapshot_id"] = "fpl-live-20260918T120000Z-decision"
    write(request.accepted_dir / "data/fixtures.json", fixtures)
    monkeypatch.setattr(site, "fixtures_view", Mock(side_effect=DataError("unreadable list")))
    with pytest.raises(
        DataError,
        match=r"data/fixtures\.json comes from 'fpl-live-20260918T120000Z-decision', not the "
        r"outcome capture",
    ):
        publication.publish_settled(request)
    assert_refused_before_writing(request)


@pytest.mark.parametrize(
    ("index", "match"),
    [
        (
            frozen_index(files=(*FROZEN_FILES, f"{SEASON}/gw04/recommendation.json")),
            r"names 1 file\(s\) the candidate lacks: \['2026-27/gw04/recommendation\.json'\]",
        ),
        (
            frozen_index(files=tuple(f for f in FROZEN_FILES if not f.endswith("pool.json"))),
            r"1 gameweek view\(s\) the frozen data/index\.json does not name: "
            r"\['2026-27/gw05/pool\.json'\]",
        ),
        (
            frozen_index(weeks=(4, 5)),
            r"lists 2026-27 gameweeks \[4, 5\], and the candidate's "
            r"data/2026-27/ledger\.json holds \[5\]",
        ),
        (frozen_index(latest=None), r"names None as the latest view"),
        (frozen_index(files=(*FROZEN_FILES, "../outside.json")), r"outside data/"),
    ],
    ids=["names-a-missing-file", "omits-a-view", "other-weeks", "no-latest", "outside"],
)
def test_a_frozen_root_index_that_disagrees_with_the_candidate_refuses(
    tmp_path: Path, index: dict[str, Any], match: str
) -> None:
    request = world(tmp_path)
    write(request.accepted_dir / "data/index.json", index)
    with pytest.raises(DataError, match=match):
        publication.publish_settled(request)
    assert_refused_before_writing(request)


def test_the_league_tree_check_reads_the_settled_candidate_not_the_accepted_tree(
    tmp_path: Path,
) -> None:
    request = world(tmp_path)
    seen: list[dict[str, Any]] = []

    def check(data: Path) -> list[str]:
        seen.append(json.loads((data / "league/members.json").read_bytes())["payload"])
        assert not data.is_relative_to(request.accepted_dir)
        return []

    result = publication.publish_settled(request, league_tree_check=check)
    assert [payload["scored_gameweek"] for payload in seen] == [5]
    assert result.checks[-1] == "the league tree check found nothing"


def test_a_league_tree_check_finding_refuses_and_writes_nothing(tmp_path: Path) -> None:
    request = world(tmp_path)
    before = inventory(request.accepted_dir)
    with pytest.raises(
        DataError,
        match=r"fails the league tree check with 2 finding\(s\); the first: 101: index",
    ):
        publication.publish_settled(
            request, league_tree_check=lambda data: ["101: index", "102: index"]
        )
    assert_refused_before_writing(request)
    assert inventory(request.accepted_dir) == before
