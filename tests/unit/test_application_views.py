"""The application layer: view models, the ui_view_v1 schema, and the static site tree.

The live path is exercised through the same synthetic capture the ledger tests use, so a
recorded decision, its ledger row and its site file all come from one world.
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import jsonschema
import pytest
import tests.unit.test_season_ledger as ledger_world
from tests.unit.test_season_ledger import _capture, _flat_points, _panel

from squadopt.application import (
    UI_VIEW_CONTRACT_VERSION,
    build_site,
    ledger_view,
    pool_view,
    recommendation_view,
    recommendation_view_from_ledger,
    status_view,
    ui_view_schema,
    write_ui_view_schema,
)
from squadopt.application.views import ViewError, jsonable, short_name
from squadopt.live import (
    Recommendation,
    build_recommendation,
    load_entry,
    project,
    read_inputs,
    record_decision,
    record_outcome,
    render,
)
from squadopt.live.recommendation import Projection
from squadopt.live.tick import HeldSnapshot, LedgerState, plan_tick

SEASON = ledger_world.SEASON


@pytest.fixture(name="world")
def _world(tmp_path: Path) -> tuple[Recommendation, Projection, Path, Any]:
    snapshot = _capture(tmp_path / "snapshots")
    inputs = read_inputs(snapshot, season=SEASON)
    projection = project(inputs, _panel(players=(1001, 1004, 1012)))
    recommendation = build_recommendation(inputs, projection)
    return recommendation, projection, tmp_path / "ledger", snapshot


def _validate(payload: dict[str, Any], definition: str) -> None:
    schema = ui_view_schema()
    jsonschema.validate(payload, {**schema["$defs"][definition], "$defs": schema["$defs"]})


def test_the_schema_is_a_valid_draft_2020_12_document_and_writes_deterministically(
    tmp_path: Path,
) -> None:
    schema = ui_view_schema()
    jsonschema.Draft202012Validator.check_schema(schema)
    first = write_ui_view_schema(tmp_path / "a" / "schema.json")
    second = write_ui_view_schema(tmp_path / "b" / "schema.json")
    assert first.read_bytes() == second.read_bytes()
    assert (
        json.loads(first.read_text(encoding="utf-8"))["$defs"]["ViewEnvelope"]["properties"][
            "contract_version"
        ]["const"]
        == UI_VIEW_CONTRACT_VERSION
    )


def test_a_recommendation_view_matches_the_ledger_view_of_the_same_decision(
    world: tuple[Recommendation, Projection, Path, Any],
) -> None:
    recommendation, projection, root, _ = world
    in_memory = recommendation_view(recommendation)
    record_decision(root, recommendation, projection, report_text=render(recommendation))
    from_ledger = recommendation_view_from_ledger(load_entry(root, SEASON, 1))

    for view in (in_memory, from_ledger):
        payload = view.to_dict()
        _validate(payload, "RecommendationView")
        json.dumps(payload)  # JSON-native only
        assert len(view.starting_xi) == 11 and len(view.bench) == 4 and len(view.squad) == 15
        assert sum(p.is_captain for p in view.starting_xi) == 1
        assert view.captain_player_id == int(recommendation.captain["player_id"])
        assert view.decision_kind == "opening" and view.transfers is None
        assert view.solver_proved_optimal is True
        assert [p.position for p in view.starting_xi] == sorted(
            [p.position for p in view.starting_xi], key=["GK", "DEF", "MID", "FWD"].index
        )
        assert [p.bench_order for p in view.bench] == [1, 2, 3, 4]
    # Everything the ledger freezes agrees between the two paths.
    for name in (
        "season",
        "gameweek",
        "snapshot_id",
        "prediction_fingerprint",
        "solver_status",
        "captain_player_id",
        "total_cost_tenths",
        "projected_score",
    ):
        assert getattr(in_memory, name) == getattr(from_ledger, name)
    assert [p.player_id for p in in_memory.squad] == [p.player_id for p in from_ledger.squad]
    # GW1's honest risk state: not requested, said in words on both paths.
    assert in_memory.risk.status == from_ledger.risk.status == "not_requested"
    assert from_ledger.risk.stated_limits and in_memory.risk.reason


def test_the_ledger_view_totals_settled_and_unsettled_rows_separately(
    world: tuple[Recommendation, Projection, Path, Any],
) -> None:
    recommendation, projection, root, _ = world
    record_decision(root, recommendation, projection, report_text="report")
    before = ledger_view(root, SEASON)
    _validate(before.to_dict(), "LedgerView")
    assert before.decided_gameweeks == 1 and before.settled_gameweeks == 0
    assert before.total_realized_score is None and before.rows[0].settled is False

    points = _flat_points(recommendation, value=3.0)
    record_outcome(root, SEASON, 1, points, source_snapshot_id=recommendation.snapshot_id)
    after = ledger_view(root, SEASON)
    _validate(after.to_dict(), "LedgerView")
    row = after.rows[0]
    assert after.settled_gameweeks == 1 and row.settled is True
    assert row.realized_score is not None and row.projection_error is not None
    assert row.projection_error == pytest.approx(row.realized_score - row.projected_score)
    assert after.total_realized_score == pytest.approx(row.realized_score)
    assert after.total_projected_score_settled == pytest.approx(row.projected_score)
    assert after.total_projection_error == pytest.approx(row.projection_error)
    assert before.total_projection_error is None
    view = recommendation_view_from_ledger(load_entry(root, SEASON, 1))
    assert view.settled is True and view.outcome_realized_score == pytest.approx(row.realized_score)


def test_the_status_view_reports_the_plan_and_the_recent_run_log(
    world: tuple[Recommendation, Projection, Path, Any], tmp_path: Path
) -> None:
    _, _, _root, snapshot = world
    held = [HeldSnapshot(snapshot.metadata.snapshot_id, snapshot.metadata.captured_at_utc)]
    plan = plan_tick(
        now_utc="2026-08-21T15:30:00Z",
        held=held,
        latest=snapshot,
        ledger=LedgerState(),
        handoff_root=tmp_path / "handoffs",
        season=SEASON,
    )
    log_root = tmp_path / "logs"
    (log_root / "season_tick").mkdir(parents=True)
    lines = [
        json.dumps(
            {"ts": "2026-08-21T15:00:00Z", "level": "INFO", "message": "tick.start", "run_id": "r1"}
        ),
        json.dumps(
            {
                "ts": "2026-08-21T15:00:01Z",
                "level": "INFO",
                "message": "tick.done",
                "run_id": "r1",
                "fields": {"performed": 0},
            }
        ),
        "not json",
    ]
    (log_root / "season_tick" / "2026-08-21.jsonl").write_text("\n".join(lines) + "\n", "utf-8")

    view = status_view(plan, ledger=LedgerState(decided=frozenset({1})), runlog_root=log_root)
    payload = view.to_dict()
    _validate(payload, "StatusView")
    assert view.next_gameweek == 1 and view.next_deadline_utc == "2026-08-21T17:30:00Z"
    assert view.decided_gameweeks == (1,) and view.settled_gameweeks == ()
    assert [event.message for event in view.recent_events] == ["tick.done", "tick.start"]
    assert view.recent_events[0].fields == {"performed": 0}
    assert status_view(plan, ledger=LedgerState()).recent_events == ()


def test_build_site_writes_a_deterministic_validated_tree(
    world: tuple[Recommendation, Projection, Path, Any], tmp_path: Path
) -> None:
    recommendation, projection, root, snapshot = world
    record_decision(root, recommendation, projection, report_text="report")
    held = [HeldSnapshot(snapshot.metadata.snapshot_id, snapshot.metadata.captured_at_utc)]
    plan = plan_tick(
        now_utc="2026-08-21T15:30:00Z",
        held=held,
        latest=snapshot,
        ledger=LedgerState(decided=frozenset({1})),
        handoff_root=tmp_path / "handoffs",
        season=SEASON,
    )
    now = datetime(2026, 8, 21, 15, 31, tzinfo=UTC)

    first = build_site(
        ledger_root=root, season=SEASON, out_dir=tmp_path / "one", plan=plan, now=now
    )
    second = build_site(
        ledger_root=root, season=SEASON, out_dir=tmp_path / "two", plan=plan, now=now
    )

    assert first.files == second.files
    assert set(first.files) == {
        "index.json",
        f"{SEASON}/gw01/recommendation.json",
        f"{SEASON}/gw01/pool.json",
        f"{SEASON}/ledger.json",
        f"{SEASON}/status.json",
        f"schema/{UI_VIEW_CONTRACT_VERSION}.schema.json",
    }
    for relative in first.files:
        a = (tmp_path / "one" / "data" / relative).read_bytes()
        b = (tmp_path / "two" / "data" / relative).read_bytes()
        assert a == b, relative
        assert b"\r\n" not in a
    schema = json.loads(
        (tmp_path / "one" / "data" / f"schema/{UI_VIEW_CONTRACT_VERSION}.schema.json").read_text(
            "utf-8"
        )
    )
    for relative in first.files:
        if relative.startswith("schema/"):
            continue
        document = json.loads((tmp_path / "one" / "data" / relative).read_text("utf-8"))
        jsonschema.validate(document, schema)
        assert document["contract_version"] == UI_VIEW_CONTRACT_VERSION
    index = json.loads((tmp_path / "one" / "data" / "index.json").read_text("utf-8"))["payload"]
    assert index["latest"] == {
        "season": SEASON,
        "gameweek": 1,
        "path": f"{SEASON}/gw01/recommendation.json",
    }
    assert index["gameweeks"] == {SEASON: [1]}
    assert first.status_written is True and first.decided_gameweeks == (1,)
    # No leftover temporary files from the atomic writes.
    assert not [p for p in (tmp_path / "one").rglob(".*.tmp-*")]


def test_the_pool_view_ranks_the_projected_pool_and_marks_the_squad(
    world: tuple[Recommendation, Projection, Path, Any],
) -> None:
    recommendation, projection, root, _ = world
    record_decision(root, recommendation, projection, report_text="report")
    view = pool_view(load_entry(root, SEASON, 1), per_position=5)
    _validate(view.to_dict(), "PoolView")
    assert view.gameweek == 1 and view.per_position == 5
    assert view.pool_size == len(projection.table)
    squad_ids = {int(p) for p in recommendation.squad["player_id"]}
    for position in ("GK", "DEF", "MID", "FWD"):
        block = [p for p in view.players if p.position == position]
        assert [p.rank_in_position for p in block] == list(range(1, len(block) + 1))
        assert [p.expected_points for p in block] == sorted(
            (p.expected_points for p in block), reverse=True
        )
        for player in block:
            assert player.selected == (player.player_id in squad_ids)
            assert (player.role != "pool") == player.selected


def test_ledger_rows_carry_cumulative_scores(
    world: tuple[Recommendation, Projection, Path, Any],
) -> None:
    recommendation, projection, root, _ = world
    record_decision(root, recommendation, projection, report_text="report")
    view = ledger_view(root, SEASON)
    assert view.rows[0].cumulative_projected_score == pytest.approx(view.rows[0].projected_score)
    assert view.rows[0].cumulative_realized_score is None
    record_outcome(
        root,
        SEASON,
        1,
        _flat_points(recommendation, 2.0),
        source_snapshot_id=recommendation.snapshot_id,
    )
    settled = ledger_view(root, SEASON).rows[0]
    assert settled.cumulative_realized_score == pytest.approx(settled.realized_score)


def test_short_names_keep_their_particles() -> None:
    assert short_name("Virgil van Dijk") == "van Dijk"
    assert short_name("Gianluigi Donnarumma") == "Donnarumma"
    assert short_name("Rayan Vitor Simplício Rocha") == "Rocha"
    assert short_name("Kevin De Bruyne") == "De Bruyne"
    assert short_name("Rodri") == "Rodri"


def test_jsonable_refuses_what_a_page_could_not_show() -> None:
    assert jsonable({"a": (1, 2), "b": Path("x") / "y"}) == {"a": [1, 2], "b": "x/y"}
    with pytest.raises(ViewError, match="Non-finite"):
        jsonable(float("nan"))
