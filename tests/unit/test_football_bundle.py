"""Offline ready-marker checks over real synthetic capture/pair/news/site readers."""

import json
from dataclasses import replace
from pathlib import Path

import pytest
from tests.unit.test_club_news_coding_versions import _document, _response
from tests.unit.test_football_publication import publication_case as publication_case

from squadopt.application.rotation_export import RotationExportRequest, export_rotation_evidence
from squadopt.data.errors import DataError
from squadopt.data.snapshots import read_snapshot, write_snapshot
from squadopt.data.sources.club_news_capture import CodedClub, write_club_news_capture
from squadopt.data.sources.club_news_coding import (
    ROTATION_CLAIM_CODING_CONTRACT_VERSION,
    coding_prompt_sha256,
)
from squadopt.data.sources.fpl_live import BOOTSTRAP_PAYLOAD, FIXTURES_PAYLOAD
from squadopt.live import InSeasonProjection, read_inputs, write_projection_handoff
from squadopt.live.football_artifact import forecast_digest
from squadopt.platform import football_bundle as bundle
from squadopt.platform.football_publication import publish_football_artifacts


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


@pytest.fixture
def case(publication_case, tmp_path):
    source = publication_case
    served, companion = source["document"], source["companion"]
    roster = source["inputs"].players
    boot = {
        "teams": [{"id": club + 100, "code": club, "name": f"Club {club}"} for club in range(1, 7)],
        "events": [
            {"id": 1, "deadline_time": "2026-08-15T10:00:00Z", "finished": True},
            *[
                {
                    "id": week,
                    "deadline_time": day + "T12:00:00Z",
                    "finished": False,
                }
                for week, day in (
                    (6, "2026-09-23"),
                    (7, "2026-09-30"),
                    (8, "2026-10-07"),
                    (9, "2026-10-14"),
                    (10, "2026-10-21"),
                )
            ],
        ],
        "elements": [
            {
                "id": int(row.player_id),
                "code": int(row.player_id),
                "team": int(row.team_id) + 100,
                "web_name": row.name,
                "first_name": "Player",
                "second_name": str(row.player_id),
                "element_type": {"GK": 1, "DEF": 2, "MID": 3, "FWD": 4}[row.position],
                "now_cost": 50,
                "status": "d",
                "chance_of_playing_next_round": 50,
                "chance_of_playing_this_round": 50,
                "news": "",
                "news_added": None,
                "scout_risks": [],
                "scout_news_link": None,
            }
            for row in roster.itertuples(index=False)
        ],
    }
    # Optional captured season rules for callers exercising the real planner.
    boot.update(source.get("bootstrap_extra", {}))
    fixtures = json.loads(source["snapshot"].payloads[FIXTURES_PAYLOAD])
    for row in fixtures:
        row.update(
            team_h_difficulty=3, team_a_difficulty=3, finished=False, provisional_start_time=False
        )
    root = tmp_path / "captures"
    meta = write_snapshot(
        root,
        source="fpl-live",
        captured_at_utc=served["captured_at_utc"],
        payloads={
            BOOTSTRAP_PAYLOAD: json.dumps(boot).encode(),
            FIXTURES_PAYLOAD: json.dumps(fixtures).encode(),
        },
    )
    snapshot = read_snapshot(root, meta.snapshot_id)
    for doc in (served, companion):
        doc.update(
            source_snapshot_id=meta.snapshot_id,
            source_fingerprint=meta.fingerprint,
            captured_at_utc=meta.captured_at_utc,
        )
    for row in served["rows"]:
        row["team_id"] = f"Club {row['team_id']}"
    served["fingerprint"] = forecast_digest(served)
    companion["forecast_fingerprint"] = served["fingerprint"]
    companion["fingerprint"] = forecast_digest(companion)
    inputs = read_inputs(snapshot, season="2026-27")
    publish_football_artifacts(
        artifact_root=source["artifact_root"],
        snapshot=snapshot,
        inputs=inputs,
        document=served,
        companion=companion,
    )
    handoff = tmp_path / "handoff.json"
    projection = InSeasonProjection(
        "2026-27",
        6,
        meta.snapshot_id,
        "synthetic",
        "synthetic-v1",
        "synthetic",
        {int(p): 2.0 for p in roster.player_id},
    )
    write_projection_handoff(handoff, projection)
    site = tmp_path / "public-data"
    envelope = {
        "contract_version": "provisional_league_ui_v1",
        "generated_at_utc": "2026-09-22T13:00:00Z",
    }
    members = [{"member_kind": "human", "entry_id": value} for value in (101, 202)]
    dump(
        site / "league/members.json",
        {
            **envelope,
            "payload": {
                "league_id": 1,
                "league_name": "Synthetic",
                "season": "2026-27",
                "gameweek": 6,
                "members": members,
            },
        },
    )
    for member in members:
        dump(
            site / f"league/entries/{member['entry_id']}.json",
            {
                **envelope,
                "payload": {
                    "league_id": 1,
                    "season": "2026-27",
                    "gameweek": 6,
                    "source_snapshot_id": meta.snapshot_id,
                    "entry": member,
                },
            },
        )
    return dict(
        artifact_root=source["artifact_root"],
        snapshot_root=root,
        snapshot_id=meta.snapshot_id,
        handoff_path=handoff,
        site_data_root=site,
    )


def marker(case):
    return bundle.football_bundle_path(case["artifact_root"], case["snapshot_id"])


def read(case):
    return bundle.read_football_bundle(
        **{key: case[key] for key in ("artifact_root", "snapshot_root", "snapshot_id")}
    )


def test_ready_marker_is_last_and_replays_exact_bytes(case, monkeypatch):
    original = bundle.write_bytes_once
    calls = []

    def write(raw, target):
        calls.append(target)
        if target == marker(case):
            assert all(path.exists() for path in calls[:-1])
        return original(raw, target)

    monkeypatch.setattr(bundle, "write_bytes_once", write)
    result = bundle.seal_football_bundle(**case)
    assert calls[-1] == marker(case)
    before = marker(case).read_bytes()
    assert bundle.seal_football_bundle(**case).fingerprint == result.fingerprint
    assert marker(case).read_bytes() == before
    record = json.loads(before)
    assert all(not Path(row["path"]).is_absolute() for row in record["files"].values())
    assert record["news"] is None
    assert len([key for key in result.files if key.startswith("site_entry")]) == 2


@pytest.mark.parametrize(
    "damage",
    [
        "entry_capture",
        "entry_week",
        "entry_season",
        "missing_entry",
        "duplicate_member",
        "site_time",
        "handoff",
        "components",
    ],
)
def test_mismatched_input_never_publishes_ready_marker(case, damage):
    entry = case["site_data_root"] / "league/entries/202.json"
    if damage in {"entry_capture", "entry_week", "entry_season"}:
        value = json.loads(entry.read_bytes())
        key, wrong = {
            "entry_capture": ("source_snapshot_id", "fpl-live-wrong"),
            "entry_week": ("gameweek", 7),
            "entry_season": ("season", "2024-25"),
        }[damage]
        value["payload"][key] = wrong
        dump(entry, value)
    elif damage == "missing_entry":
        entry.unlink()
    elif damage in {"duplicate_member", "site_time"}:
        path = case["site_data_root"] / "league/members.json"
        value = json.loads(path.read_bytes())
        if damage == "duplicate_member":
            value["payload"]["members"].append(value["payload"]["members"][0])
        else:
            value["generated_at_utc"] = "2026-09-20T12:00:00Z"
        dump(path, value)
    elif damage == "handoff":
        value = json.loads(case["handoff_path"].read_bytes())
        value["source_snapshot_id"] = "wrong"
        value.pop("fingerprint")
        dump(case["handoff_path"], value)
    else:
        path = bundle.football_components_path(case["artifact_root"], case["snapshot_id"])
        value = json.loads(path.read_bytes())
        value["rows"][0]["expected_points"] += 1
        value["fingerprint"] = forecast_digest(value)
        dump(path, value)
    with pytest.raises((ValueError, DataError, OSError)):
        bundle.seal_football_bundle(**case)
    assert not marker(case).exists()


def test_changed_ready_inputs_cannot_replace_previous_marker(case):
    bundle.seal_football_bundle(**case)
    before = marker(case).read_bytes()
    handoff = json.loads(case["handoff_path"].read_bytes())
    handoff["diagnostics"]["new"] = True
    dump(case["handoff_path"], handoff)
    with pytest.raises(ValueError, match="different ready bundle"):
        bundle.seal_football_bundle(**case)
    assert marker(case).read_bytes() == before
    assert read(case).snapshot_id == case["snapshot_id"]


def test_interrupted_copy_is_not_ready_and_can_complete(case, monkeypatch):
    original = bundle.write_bytes_once

    def write(raw, target):
        if target == marker(case):
            raise OSError("synthetic interruption")
        return original(raw, target)

    monkeypatch.setattr(bundle, "write_bytes_once", write)
    with pytest.raises(OSError, match="interruption"):
        bundle.seal_football_bundle(**case)
    assert not marker(case).exists()
    monkeypatch.setattr(bundle, "write_bytes_once", original)
    assert bundle.seal_football_bundle(**case).snapshot_id == case["snapshot_id"]


@pytest.mark.parametrize("damage", ["bytes", "path", "source_fingerprint"])
def test_reader_refuses_postseal_tampering(case, damage):
    result = bundle.seal_football_bundle(**case)
    record = json.loads(marker(case).read_bytes())
    if damage == "bytes":
        result.files["site_entry_101"].write_bytes(b"changed")
    elif damage == "path":
        record["files"]["handoff"]["path"] = "../handoff.json"
        dump(marker(case), record)
    else:
        record["decision"]["fingerprint"] = "f" * 64
        dump(marker(case), record)
    with pytest.raises(ValueError):
        read(case)


def add_quiet_news(case, tmp_path):
    response = _response()
    raw = json.loads(response.text)
    raw["claims"] = []
    response = replace(response, text=json.dumps(raw))
    version = ROTATION_CLAIM_CODING_CONTRACT_VERSION
    news = write_club_news_capture(
        case["snapshot_root"],
        documents=(replace(_document(), club="Club 1"),),
        coded=(
            CodedClub("Club 1", response, version, coding_prompt_sha256(contract_version=version)),
        ),
        clubs_declared=("Club 1",),
        clubs_covered=("Club 1",),
        captured_at_utc="2026-09-22T11:00:00Z",
    )
    outputs = export_rotation_evidence(
        RotationExportRequest(
            "2026-27",
            6,
            "2026-09-23T12:00:00Z",
            case["snapshot_id"],
            case["snapshot_root"],
            None,
            tmp_path / "rotation",
            club_news_snapshot=news.snapshot_id,
            table_name="rotation-bundle",
        ),
        repository_commit="0" * 40,
    )
    case.update(news_capture_id=news.snapshot_id, rotation_table_path=outputs["table_path"])
    return outputs


def test_quiet_news_still_requires_and_preserves_exact_capture_binding(case, tmp_path):
    add_quiet_news(case, tmp_path)
    result = bundle.seal_football_bundle(**case)
    assert result.news_capture_id == case["news_capture_id"]
    assert "rotation_table" in result.files
    assert read(case).fingerprint == result.fingerprint


def test_news_without_rotation_is_not_a_ready_bundle(case):
    case["news_capture_id"] = "club-news-not-held"
    with pytest.raises(ValueError, match="News requires"):
        bundle.seal_football_bundle(**case)
    assert not marker(case).exists()


def test_cli_seals_without_activation(case, capsys):
    from scripts.prepare_football_bundle import main

    args = []
    for key, flag in {
        "artifact_root": "--artifact-root",
        "snapshot_root": "--snapshot-root",
        "snapshot_id": "--snapshot-id",
        "handoff_path": "--handoff",
        "site_data_root": "--site-data-root",
    }.items():
        args.extend([flag, str(case[key])])
    assert main(args) == 0
    assert json.loads(capsys.readouterr().out)["activation"] == "not_performed"


def test_disabled_central_source_cannot_be_sealed_or_read(case, monkeypatch):
    from squadopt.contracts.injuries import OFFICIAL_INJURY_SOURCE_ENABLED

    assert OFFICIAL_INJURY_SOURCE_ENABLED is False
    with pytest.raises(ValueError, match="central official injury source is disabled"):
        bundle.seal_football_bundle(**case, official_injury_capture_id="official-pl-not-read")
    assert not marker(case).exists()
    assert not (marker(case).parent / (case["snapshot_id"] + ".bundle")).exists()

    bundle.seal_football_bundle(**case)
    record = json.loads(marker(case).read_bytes())
    record["official_injuries"] = {"snapshot_id": "official-pl-not-read"}
    dump(marker(case), record)
    monkeypatch.setattr(
        bundle, "_source", lambda *_: pytest.fail("Disabled input must not be read")
    )
    with pytest.raises(ValueError, match="central official injury source is disabled"):
        read(case)
