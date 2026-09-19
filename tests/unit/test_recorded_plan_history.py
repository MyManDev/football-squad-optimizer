"""The optional history rows repeat the archive, without scoring switched plans."""

import copy
import json
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

import jsonschema
import pytest
from tests.unit.test_publication_services import publication_world
from tests.unit.test_weekly_suggestion_eval import SEASON, recorded, snapshot

from squadopt.application import weekly_suggestion_eval as review
from squadopt.application.advice_record import load_member_advice_record, record_member_advice
from squadopt.application.league_publication import publish_league
from squadopt.application.weekly_suggestion_eval import WeekReview, _history_week
from squadopt.platform.history_documents import history_schema

ROOT = Path(__file__).resolve().parents[2]


def test_real_publication_carries_recorded_chip_moves_into_unsettled_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SQUADOPT_REPOSITORY_COMMIT", "c" * 40)
    request = publication_world(tmp_path)
    with patch.object(review, "load_member_advice_record", wraps=load_member_advice_record) as read:
        publish_league(request)
    member_reads = [call for call in read.call_args_list if call.args[3] == 101]
    assert len(member_reads) == 1
    history = json.loads(
        (request.out_dir / "data/league/history/101.json").read_text(encoding="utf-8")
    )
    jsonschema.validate(history, history_schema())
    week = history["payload"]["weeks"][0]
    assert week["status"] == "unsettled"
    record = load_member_advice_record(
        request.record_root, request.season, 2, 101, request.snapshot_id
    )
    rows = {row["published_path"]: row for row in week["recorded_plans"]}
    assert rows
    assert all(row["window"] == 1 for row in rows.values())
    assert rows.keys() <= {doc["published_path"] for doc in record["advice"]}
    path = "advice/101/saf-puan/1/chip-bboost.json"
    published = json.loads((request.out_dir / "data/league" / path).read_text(encoding="utf-8"))[
        "payload"
    ]
    assert rows[path]["chip"] == "bboost"
    assert rows[path]["captain"] == published["captain"]["name"]
    assert rows[path]["moves"] == [
        {
            key: move[key]["name"] if move[key] is not None else None
            for key in ("player_out", "player_in")
        }
        for move in published["moves"]
    ]
    assert rows[path]["expected_points_cost"] == published["expected_points_cost"]
    assert "top100_weight" not in rows[path]


def test_recorded_settings_moves_captain_and_price_are_optional_and_repeat_the_archive(
    tmp_path: Path,
) -> None:
    record = recorded()
    baseline = record["advice"][0]
    baseline.update(published_path="advice/101/saf-puan/1.json", moves=[])
    week = WeekReview(4, "unsettled", "not_settled", advice_snapshot_id="capture-a")
    record_member_advice(tmp_path / "old", record)
    assert _history_week(week, record) == asdict(week)
    baseline["expected_points_cost"] = 0

    record["advice"] += [
        {
            **baseline,
            "published_path": "advice/101/saf-puan/1/top100-20-hoca-sozu.json",
            "top100_weight": 20,
            "managers_word": True,
            "expected_points_cost": 2.5,
            "expected_points_cost_ceiling": 4,
            "moves": [{"player_out": 1, "player_in": 17}],
        },
        {**baseline, "published_path": "advice/101/saf-puan/1/chip-bboost.json", "chip": "bboost"},
    ]
    before = copy.deepcopy(record)
    record_member_advice(tmp_path / "new", record)
    result = _history_week(
        week, load_member_advice_record(tmp_path / "new", SEASON, 4, 101, "capture-a")
    )
    expected = json.loads(
        (ROOT / "web/src/fixtures/recordedPlanRows.json").read_text(encoding="utf-8")
    )
    assert result.pop("recorded_plans") == expected
    assert result == asdict(week)
    assert record == before
    assert "recorded_plans" not in _history_week(
        WeekReview(5, "unavailable", "missing_advice"), None
    )


def test_history_limits_rows_to_one_week_default_rival_and_deduplicates_only_equal_aliases() -> (
    None
):
    record = recorded()
    baseline = record["advice"][0]
    baseline.update(published_path="advice/101/saf-puan/1.json", expected_points_cost=0)
    alias = {
        **baseline,
        "strategy": "ortak-koru",
        "rival_entry_id": 202,
        "published_path": "advice/101/ortak-koru/1.json",
    }
    twin = {**alias, "published_path": "advice/101/ortak-koru/1/vs-202.json"}
    record["advice"] += [
        alias,
        twin,
        {**twin, "rival_entry_id": 303, "published_path": "advice/101/ortak-koru/1/vs-303.json"},
        {**twin, "window": 3, "published_path": "advice/101/ortak-koru/3/vs-202.json"},
        {**baseline, "window": 5, "published_path": "advice/101/saf-puan/5.json"},
    ]
    week = WeekReview(4, "unsettled", "not_settled")
    assert [row["published_path"] for row in _history_week(week, record)["recorded_plans"]] == [
        baseline["published_path"],
        twin["published_path"],
    ]
    twin["advice_sha256"] = "b" * 64
    assert len(_history_week(week, record)["recorded_plans"]) == 3


@pytest.mark.parametrize("bad_plan", [False, True])
def test_invalid_record_degrades_one_member_without_aborting_history_publication(
    tmp_path: Path,
    bad_plan: bool,
) -> None:
    bad = recorded(entry_id=202)
    if bad_plan:
        bad["advice"].append(None)
    else:
        bad["advice"][0]["expected_own_points"] = "invalid"
    for record in (recorded(), bad):
        record_member_advice(tmp_path / "records", record)
    anchor = snapshot(tmp_path / "snapshots")
    paths = review.publish_suggestion_histories(
        record_root=tmp_path / "records",
        snapshot_root=tmp_path / "snapshots",
        as_of_snapshot=anchor,
        season=SEASON,
        league_id=352490,
        entry_ids=(101, 202),
        out_dir=tmp_path / "site",
    )
    histories = [json.loads(path.read_text(encoding="utf-8")) for path in paths]
    assert histories[0]["payload"]["weeks"][0]["status"] == "available"
    refused = histories[1]["payload"]["weeks"][0]
    assert refused["reason"] == (None if bad_plan else "invalid_record")
    assert "recorded_plans" not in refused


def test_reproducible_history_schema_accepts_both_shapes_and_refuses_a_null_price() -> None:
    schema = history_schema()
    committed = ROOT / "docs/contracts/weekly_suggestion_history_v1.schema.json"
    assert json.loads(committed.read_text(encoding="utf-8")) == schema
    legacy = json.loads(
        (ROOT / "web/src/fixtures/weeklySuggestionHistory.json").read_text(encoding="utf-8")
    )
    jsonschema.validate(legacy, schema)
    rows = json.loads((ROOT / "web/src/fixtures/recordedPlanRows.json").read_text(encoding="utf-8"))
    legacy["payload"]["weeks"][0]["recorded_plans"] = rows
    jsonschema.validate(legacy, schema)
    rows[0]["expected_points_cost"] = None
    assert list(jsonschema.Draft202012Validator(schema).iter_errors(legacy))
