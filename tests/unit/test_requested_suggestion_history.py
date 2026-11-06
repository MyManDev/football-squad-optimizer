"""A requested answer becomes a scored history row without solving or rewriting legacy history."""

import copy
import json
from dataclasses import replace

import pytest
from scripts.build_requested_history import build_requested_history
from scripts.export_requested_history import requested_history
from tests.unit import test_weekly_suggestion_eval as legacy

from squadopt.data.snapshots import read_snapshot, write_snapshot
from squadopt.platform.advice_cache import FileAdviceCache, advice_cache_key
from squadopt.platform.advice_job_spec import AdviceJobSpec, FileAdviceJobSpecStore
from squadopt.platform.advice_queue import FileJobQueue
from squadopt.platform.advice_read import AdviceRequestContext
from squadopt.platform.jobs_contract import AdviceJob
from squadopt.platform.requested_suggestion_history import requested_week


def _capture(root, *, captured, finished, checked=True, actual=True):
    old = legacy.snapshot(
        root, captured=captured, finished=finished, checked=checked, actual=actual
    )
    payloads = dict(old.payloads)
    bootstrap = json.loads(payloads["bootstrap-static.json"])
    for row, position in zip(bootstrap["elements"], legacy.POSITIONS, strict=True):
        row["element_type"] = {"GK": 1, "DEF": 2, "MID": 3, "FWD": 4}[position]
    payloads["bootstrap-static.json"] = json.dumps(bootstrap).encode()
    written = write_snapshot(root, source="fpl-live", captured_at_utc=captured, payloads=payloads)
    return read_snapshot(root, written.snapshot_id)


def _store(root, spec, payload, *, captured=legacy.CAPTURED, completed=legacy.PUBLISHED):
    key = advice_cache_key(
        **spec.as_payload()["context"],
        league_id=spec.league_id,
        entry_id=spec.entry_id,
        strategy=spec.strategy,
        window=spec.window,
        switches=spec.switches,
    )
    FileAdviceJobSpecStore(root / "specs").put(key, spec)
    document = {
        "contract_version": "provisional_league_ui_v1",
        "source_kind": "live",
        "generated_at_utc": captured,
        "payload": payload,
    }
    cache = FileAdviceCache(root / "cache")
    queue = FileJobQueue(root / "jobs")
    queue.submit(AdviceJob(f"request-{key}", "queued", "a" * 64, key, captured, captured))
    job = queue.claim(at_utc=captured)
    queue.complete(job, cache=cache, payload=json.dumps(document).encode(), at_utc=completed)
    return key


@pytest.fixture
def world(tmp_path):
    snapshots = tmp_path / "snapshots"
    decision = _capture(snapshots, captured=legacy.CAPTURED, finished=False)
    outcome = _capture(snapshots, captured="2026-09-15T09:00:00Z", finished=True)

    def player(identifier):
        return {
            "player_id": identifier,
            "position": legacy.POSITIONS[identifier - 1],
            "name": f"Player {identifier}",
            "short_name": f"P{identifier}",
            "expected_points": 3.5,
            "team": "Test",
        }

    payload = {
        "season": legacy.SEASON,
        "gameweek": 4,
        "entry_id": 101,
        "league_id": 0,
        "source_snapshot_id": decision.metadata.snapshot_id,
        "mode": "saf-puan",
        "window": 1,
        "starting_xi": [player(i) for i in legacy.STARTERS],
        "bench": [player(i) for i in legacy.BENCH],
        "captain": player(8),
        "vice_captain": player(9),
        "chip": None,
        "transfer_hit_points": 4,
        "expected_own_points": 42.0,
        "moves": [],
        "data_quality": "complete",
        "missing_fields": [],
    }
    context = AdviceRequestContext(
        "provisional_league_ui_v1",
        decision.metadata.snapshot_id,
        legacy.SEASON,
        4,
        "f" * 64,
        "a" * 40,
        "d" * 64,
    )
    spec = AdviceJobSpec(
        0, 101, "saf-puan", 1, context, switches={"public_entry": {"fingerprint": "b" * 64}}
    )
    store = tmp_path / "store"
    key = _store(store, spec, payload)
    return {
        "store_snapshot": store,
        "snapshot_root": snapshots,
        "as_of_snapshot_id": outcome.metadata.snapshot_id,
        "league_id": 239,
        "entry_id": 101,
        "gameweeks": [4],
        "out_dir": tmp_path / "league",
        "spec": spec,
        "payload": payload,
        "key": key,
        "decision": decision,
        "outcome": outcome,
    }


def _build(world):
    return build_requested_history(
        **{
            k: world[k]
            for k in (
                "store_snapshot",
                "snapshot_root",
                "as_of_snapshot_id",
                "league_id",
                "entry_id",
                "gameweeks",
                "out_dir",
            )
        }
    )


def _export(world):
    return requested_history(
        world["store_snapshot"],
        season=legacy.SEASON,
        gameweek=4,
        entry_id=101,
        deadline_utc=legacy.DEADLINE,
    )


def test_requested_score_matches_existing_scoring_and_preserves_legacy_bytes(world, monkeypatch):
    import squadopt.application.advice_menu as menu

    monkeypatch.setattr(
        menu, "advise_menu_entry", lambda *a, **k: pytest.fail("History ran a solver")
    )
    original = world["out_dir"] / "history" / "101.json"
    original.parent.mkdir(parents=True)
    original.write_bytes(b"legacy publication bytes remain untouched\n")
    path = _build(world)
    assert path == original.parent / "requested" / "101.json"
    document = json.loads(path.read_bytes())
    (row,) = document["payload"]["weeks"]
    assert document["payload"]["league_id"] == 239
    assert row["status"] == "available"
    assert row["suggested"]["gross_points"] == 24
    assert row["suggested"]["net_points"] == 20
    assert row["actual"]["net_points"] == 22
    assert row["net_difference"] == -2
    assert row["advice_generated_at_utc"] == legacy.PUBLISHED
    assert row["advice_source"] == "requested_server"
    assert row["request_cache_key"] == world["key"]
    assert len(row["players"]) == 15
    assert original.read_bytes() == b"legacy publication bytes remain untouched\n"
    before = path.read_bytes()
    assert _build(world).read_bytes() == before


@pytest.mark.parametrize("finished,checked", [(False, True), (True, False), (False, False)])
def test_unfinished_outcomes_never_turn_into_final_scores(world, finished, checked):
    capture = _capture(
        world["snapshot_root"], captured="2026-09-13T09:00:00Z", finished=finished, checked=checked
    )
    world["as_of_snapshot_id"] = capture.metadata.snapshot_id
    (row,) = json.loads(_build(world).read_bytes())["payload"]["weeks"]
    assert row["status"] == "unsettled"
    assert row["suggested"] is None and row["actual"] is None and row["net_difference"] is None


def test_uncaptured_member_result_stays_unknown_instead_of_zero(world):
    capture = _capture(
        world["snapshot_root"], captured="2026-09-16T09:00:00Z", finished=True, actual=False
    )
    world["as_of_snapshot_id"] = capture.metadata.snapshot_id
    (row,) = json.loads(_build(world).read_bytes())["payload"]["weeks"]
    assert row["status"] == "available"
    assert row["suggested"]["net_points"] == 20
    assert row["actual"] is None and row["net_difference"] is None
    assert row["actual_reason"] == "actual_score_missing"


def test_latest_completed_answer_is_selected_without_overwriting_either_cache_entry(world):
    payload = {**world["payload"], "transfer_hit_points": 8}
    spec = replace(
        world["spec"], context=replace(world["spec"].context, repository_commit="c" * 40)
    )
    key = _store(world["store_snapshot"], spec, payload, completed="2026-09-10T10:00:00Z")
    (row,) = json.loads(_build(world).read_bytes())["payload"]["weeks"]
    assert row["request_cache_key"] == key
    assert row["suggested"]["net_points"] == 16
    assert len(list((world["store_snapshot"] / "cache").rglob("*.json"))) == 2


def test_conflicting_equal_time_answers_cannot_silently_select_a_winner(world):
    spec = replace(
        world["spec"], context=replace(world["spec"].context, repository_commit="c" * 40)
    )
    _store(world["store_snapshot"], spec, {**world["payload"], "transfer_hit_points": 8})
    with pytest.raises(ValueError, match="Equally recent"):
        _build(world)
    assert not world["out_dir"].exists()


@pytest.mark.parametrize(
    "damage", ["digest", "entry", "deadline", "position", "duplicate", "captain"]
)
def test_requested_evidence_is_checked_again_before_scoring(world, damage):
    exported = copy.deepcopy(_export(world))
    row = exported["records"][0]
    if damage == "digest":
        row["response_sha256"] = "0" * 64
    elif damage == "entry":
        exported["entry_id"] += 1
    elif damage == "deadline":
        exported["deadline_utc"] = "2026-09-13T10:00:00Z"
    else:
        import hashlib

        document = json.loads(row["response_json"])
        payload = document["payload"]
        if damage == "position":
            payload["starting_xi"][0]["position"] = "MID"
        elif damage == "duplicate":
            payload["bench"][0] = payload["starting_xi"][0]
        else:
            payload["captain"] = payload["bench"][0]
        row["response_json"] = json.dumps(document)
        row["response_sha256"] = hashlib.sha256(row["response_json"].encode()).hexdigest()
    with pytest.raises(ValueError):
        requested_week(
            exported, captures=[world["decision"], world["outcome"]], as_of=world["outcome"]
        )


def test_as_of_cutoff_cannot_borrow_a_later_completed_request(world):
    assert (
        requested_week(
            _export(world), captures=[world["decision"], world["outcome"]], as_of=world["decision"]
        )
        is None
    )


def test_missing_store_evidence_does_not_replace_an_existing_requested_history(world):
    path = _build(world)
    before = path.read_bytes()
    key = world["key"]
    (world["store_snapshot"] / "cache" / key[:2] / f"{key}.json").unlink()
    with pytest.raises(OSError):
        _build(world)
    assert path.read_bytes() == before


def test_archived_job_is_still_published_as_requested_history(world):
    queue = FileJobQueue(world["store_snapshot"] / "jobs")
    assert queue.archive(now_utc="2026-11-06T00:00:00Z")
    assert queue.jobs() == ()
    assert json.loads(_build(world).read_bytes())["payload"]["weeks"][0]["status"] == "available"
