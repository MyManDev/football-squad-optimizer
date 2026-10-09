"""Offline ready-marker checks over real synthetic capture/pair/news/site readers."""

import json
import os
import shutil
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


@pytest.mark.parametrize("role", ["capture", "handoff", "forecast", "components"])
def test_resumed_preparation_refuses_each_changed_writer_input(case, monkeypatch, role):
    original = bundle.write_bytes_once

    def fail_copy(raw, path, **kwargs):
        if path.name == "handoff.json":
            raise OSError("synthetic copy interruption")
        return original(raw, path, **kwargs)

    monkeypatch.setattr(bundle, "write_bytes_once", fail_copy)
    with pytest.raises(OSError, match="synthetic copy"):
        bundle.seal_football_bundle(**case)
    marker = bundle.football_bundle_path(case["artifact_root"], case["snapshot_id"])
    assert not marker.exists()
    preparation_path = marker.with_suffix(".preparation.json")
    preparation = json.loads(preparation_path.read_bytes())
    assert set(preparation["inputs"]) == {"capture", "handoff", "forecast", "components"}
    held = preparation_path.read_bytes()
    path = {
        "capture": case["snapshot_root"] / case["snapshot_id"] / "metadata.json",
        "handoff": case["handoff_path"],
        "forecast": bundle.football_artifact_path(case["artifact_root"], case["snapshot_id"]),
        "components": bundle.football_components_path(case["artifact_root"], case["snapshot_id"]),
    }[role]
    before = path.read_bytes()
    # Even a whitespace-only replacement changes the normal writer's byte identity.
    path.write_bytes(before + b"\n")
    monkeypatch.setattr(bundle, "write_bytes_once", original)
    with pytest.raises(ValueError, match=f"input {role} changed; resume refused"):
        bundle.seal_football_bundle(**case)
    assert not marker.exists()
    assert preparation_path.read_bytes() == held
    path.write_bytes(before)
    ready = bundle.seal_football_bundle(**case)
    assert ready.snapshot_id == case["snapshot_id"]
    assert preparation_path.read_bytes() == held


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


def test_a_site_with_the_league_directory_seals_and_reads_back(case):
    """The first publication into the directory layout moves the tree to leagues/<id>/;
    the bundle seals it there, and the reader takes the folder from the sealed record."""

    site = case["site_data_root"]
    (site / "leagues").mkdir()
    (site / "league").rename(site / "leagues" / "1")
    directory = {
        "contract_version": "league_directory_v1",
        "generated_at_utc": "2026-09-22T13:00:00Z",
        "payload": {
            "leagues": [
                {
                    "league_id": 1,
                    "league_name": "Synthetic",
                    "season": "2026-27",
                    "gameweek": 6,
                    "path": "leagues/1",
                }
            ]
        },
    }
    dump(site / "leagues.json", directory)
    result = bundle.seal_football_bundle(**case)
    record = json.loads(marker(case).read_bytes())
    assert record["files"]["site_members"]["path"].endswith(".bundle/site/leagues/1/members.json")
    assert read(case).fingerprint == result.fingerprint
    # A record naming a tree no site publishes is refused, as any other unexpected path.
    record["files"]["site_members"]["path"] = record["files"]["site_members"]["path"].replace(
        "leagues/1", "leagues/x"
    )
    with pytest.raises(ValueError, match="unexpected filename"):
        bundle._relative_files(marker(case), case["snapshot_id"], record["files"])


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
    with pytest.raises(ValueError, match="input handoff changed; resume refused"):
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


def add_quiet_news(
    case, tmp_path, table_name="rotation-bundle", captured_at_utc="2026-09-22T11:00:00Z"
):
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
        captured_at_utc=captured_at_utc,
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
            table_name=table_name,
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


@pytest.mark.parametrize("stem", ["my.table", "rotation bundle"])
def test_a_rotation_name_the_reader_refuses_is_refused_before_the_marker(case, tmp_path, stem):
    """The seal validates what the reader validates, or a marker is written that no read accepts."""

    # The export takes the operator's table name as given; the bundle's reader does not.
    outputs = add_quiet_news(case, tmp_path, table_name=stem)
    assert Path(outputs["table_path"]).name == stem + ".csv"

    # The message is the reader's own; the previous seal raised it too, from the read-back
    # after the marker was written. What this test holds is the two lines after it.
    with pytest.raises(ValueError, match="Invalid sealed rotation filename"):
        bundle.seal_football_bundle(**case)
    assert not marker(case).exists()
    assert not (marker(case).parent / (case["snapshot_id"] + ".bundle")).exists()
    # The same capture and news seal once the pair carries a name the reader accepts.
    accepted = export_rotation_evidence(
        RotationExportRequest(
            "2026-27",
            6,
            "2026-09-23T12:00:00Z",
            case["snapshot_id"],
            case["snapshot_root"],
            None,
            tmp_path / "accepted",
            club_news_snapshot=case["news_capture_id"],
            table_name="rotation-bundle",
        ),
        repository_commit="0" * 40,
    )
    case["rotation_table_path"] = accepted["table_path"]
    assert "rotation_table" in bundle.seal_football_bundle(**case).files


@pytest.mark.parametrize("stem", ["handoff", "site"])
def test_a_reserved_rotation_name_is_refused_by_the_seal_and_by_the_reader(case, tmp_path, stem):
    add_quiet_news(case, tmp_path, table_name=stem)
    case["rotation_table_path"] = Path(case["rotation_table_path"]).with_suffix(".json")
    with pytest.raises(ValueError, match="Reserved rotation artifact filename"):
        bundle.seal_football_bundle(**case)
    assert not marker(case).exists()

    # A marker written by hand that names a reserved file is not a readable bundle.
    sealed = bundle.seal_football_bundle(
        **{**case, "rotation_table_path": None, "news_capture_id": None}
    )
    record = json.loads(sealed.marker_path.read_bytes())
    record["files"]["rotation_table"] = {
        "path": case["snapshot_id"] + ".bundle/" + stem + ".json",
        "sha256": record["files"]["handoff"]["sha256"],
    }
    sealed.marker_path.write_bytes(json.dumps(record).encode("utf-8"))
    with pytest.raises(ValueError, match="Invalid sealed rotation filename"):
        read(case)


def test_a_news_capture_completed_after_the_decision_capture_is_refused_at_export(case, tmp_path):
    """The order of the two instants holds before a bundle is even possible: the export
    refuses the pair, so there is no table for a seal to read, and the seal's own check
    (``News capture must complete before the decision capture``) is its second line."""

    decision_captured_at = read_snapshot(
        case["snapshot_root"], case["snapshot_id"]
    ).metadata.captured_at_utc
    assert decision_captured_at < "2026-09-22T23:59:00Z"
    with pytest.raises(DataError, match="must complete before the decision capture"):
        add_quiet_news(case, tmp_path, captured_at_utc="2026-09-22T23:59:00Z")
    assert "rotation_table_path" not in case
    assert not marker(case).exists()


def test_a_rotation_pair_naming_another_decision_capture_is_not_sealed(case, tmp_path):
    """A pair exported for a different decision of the same week does not seal this one."""

    outputs = add_quiet_news(case, tmp_path)
    manifest_path = Path(outputs["table_path"]).with_suffix(".manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["roster_snapshot_id"] = "fpl-live-20260922T120001Z-another-decision"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises((ValueError, DataError)):
        bundle.seal_football_bundle(**case)
    assert not marker(case).exists()
    assert not (marker(case).parent / (case["snapshot_id"] + ".bundle")).exists()


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


def test_a_site_with_several_leagues_seals_the_league_it_is_told(case):
    site = case["site_data_root"]
    (site / "leagues").mkdir()
    (site / "league").rename(site / "leagues" / "1")
    shutil.copytree(site / "leagues" / "1", site / "leagues" / "2")
    rows = [
        {
            "league_id": league,
            "league_name": "Synthetic",
            "season": "2026-27",
            "gameweek": 6,
            "path": f"leagues/{league}",
        }
        for league in (1, 2)
    ]
    dump(
        site / "leagues.json",
        {
            "contract_version": "league_directory_v1",
            "generated_at_utc": "2026-09-22T13:00:00Z",
            "payload": {"leagues": rows},
        },
    )
    with pytest.raises(ValueError, match="lists 2 leagues"):
        bundle.seal_football_bundle(**case)
    result = bundle.seal_football_bundle(**case, league_id=1)
    record = json.loads(marker(case).read_bytes())
    assert record["files"]["site_members"]["path"].endswith(".bundle/site/leagues/1/members.json")
    assert read(case).fingerprint == result.fingerprint


@pytest.mark.parametrize("partial", [False, True])
def test_legacy_wrong_replay_does_not_pin_wrong_preparation(case, monkeypatch, partial):
    original_writer = bundle.write_bytes_once
    if partial:

        def interrupted(raw, target):
            if target == marker(case):
                raise OSError("synthetic legacy interruption")
            return original_writer(raw, target)

        monkeypatch.setattr(bundle, "write_bytes_once", interrupted)
        with pytest.raises(OSError, match="legacy interruption"):
            bundle.seal_football_bundle(**case)
        monkeypatch.setattr(bundle, "write_bytes_once", original_writer)
    else:
        bundle.seal_football_bundle(**case)
    receipt = marker(case).with_suffix(".preparation.json")
    receipt.unlink()
    original_handoff = case["handoff_path"].read_bytes()
    altered = json.loads(original_handoff)
    altered["diagnostics"]["new"] = True
    dump(case["handoff_path"], altered)
    with pytest.raises(
        ValueError,
        match="different immutable bundle artifact" if partial else "different ready bundle",
    ):
        bundle.seal_football_bundle(**case)
    assert not receipt.exists()
    case["handoff_path"].write_bytes(original_handoff)
    assert bundle.seal_football_bundle(**case).snapshot_id == case["snapshot_id"]
    assert read(case).snapshot_id == case["snapshot_id"]


def test_interrupted_preparation_resumes_from_identical_retained_handoff(case, monkeypatch):
    original = bundle.write_bytes_once

    def interrupted(raw, target):
        if target.name == "handoff.json":
            raise OSError("synthetic retained interruption")
        return original(raw, target)

    monkeypatch.setattr(bundle, "write_bytes_once", interrupted)
    with pytest.raises(OSError, match="retained interruption"):
        bundle.seal_football_bundle(**case)
    receipt = marker(case).with_suffix(".preparation.json")
    before = receipt.read_bytes()
    retained = case["handoff_path"].parent / "by-capture" / case["snapshot_id"] / "original.json"
    retained.parent.mkdir(parents=True)
    retained.write_bytes(case["handoff_path"].read_bytes())
    changed = {**case, "handoff_path": retained}
    monkeypatch.setattr(bundle, "write_bytes_once", original)
    assert bundle.seal_football_bundle(**changed).snapshot_id == case["snapshot_id"]
    assert receipt.read_bytes() == before
    assert read(case).snapshot_id == case["snapshot_id"]


def test_capture_preparation_identity_is_relative_and_membership_bound(case, tmp_path):
    files = {
        "handoff": case["handoff_path"],
        "forecast": bundle.football_artifact_path(case["artifact_root"], case["snapshot_id"]),
        "components": bundle.football_components_path(case["artifact_root"], case["snapshot_id"]),
    }
    prior = bundle._preparation_inputs(case["snapshot_root"], case["snapshot_id"], files)
    copied = tmp_path / "copy-captures"
    shutil.copytree(case["snapshot_root"], copied)
    current = bundle._preparation_inputs(copied, case["snapshot_id"], files)
    bundle._check_preparation(prior, current)
    (copied / case["snapshot_id"] / "unexpected.txt").write_text("extra")
    changed = bundle._preparation_inputs(copied, case["snapshot_id"], files)
    with pytest.raises(ValueError, match="input capture changed"):
        bundle._check_preparation(prior, changed)


def test_source_changed_after_identity_recheck_cannot_seal_a_different_receipt(case, monkeypatch):
    original = bundle._preparation_inputs
    calls = []

    def changed_after_return(*args, **kwargs):
        value = original(*args, **kwargs)
        calls.append(True)
        if len(calls) == 2:
            document = json.loads(case["handoff_path"].read_bytes())
            document["diagnostics"]["late_change"] = True
            dump(case["handoff_path"], document)
        return value

    monkeypatch.setattr(bundle, "_preparation_inputs", changed_after_return)
    with pytest.raises(ValueError, match="handoff changed before copying"):
        bundle.seal_football_bundle(**case)
    assert not marker(case).exists()
    assert not marker(case).with_suffix(".preparation.json").exists()


def test_missing_writer_role_names_the_missing_path(case):
    case["handoff_path"].unlink()
    with pytest.raises(ValueError) as error:
        bundle.seal_football_bundle(**case)
    assert "handoff" in str(error.value)
    assert case["handoff_path"].name in str(error.value)
    assert not marker(case).exists()


@pytest.mark.parametrize("damage", ["inputs_list", "contract", "extra_role", "extra_key"])
def test_malformed_preparation_receipt_refuses_before_new_writes(case, damage):
    bundle.seal_football_bundle(**case)
    receipt = marker(case).with_suffix(".preparation.json")
    document = json.loads(receipt.read_bytes())
    if damage == "inputs_list":
        document["inputs"] = []
    elif damage == "contract":
        document["contract_version"] = "other"
    elif damage == "extra_role":
        document["inputs"]["unexpected"] = {}
    else:
        document["unexpected"] = True
    dump(receipt, document)
    held = marker(case).read_bytes()
    with pytest.raises(ValueError, match="preparation"):
        bundle.seal_football_bundle(**case)
    assert marker(case).read_bytes() == held


@pytest.mark.skipif(os.name != "nt", reason="Windows path casing")
@pytest.mark.parametrize("role", ["snapshot_root", "artifact_root", "handoff_path"])
def test_byte_identical_windows_path_casing_replays(case, role):
    ready = bundle.seal_football_bundle(**case)
    different_spelling = {**case, role: Path(str(case[role]).upper())}
    assert bundle.seal_football_bundle(**different_spelling).fingerprint == ready.fingerprint
