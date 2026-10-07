"""Shadow publication over synthetic captures, with the production publisher and reader."""

import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from scripts import build_football_forecast as ordinary
from scripts import build_football_shadow as shadow
from tests.unit.test_football_publication import publication_case as publication_case

from squadopt.data.snapshots import read_snapshot, write_snapshot
from squadopt.live.football_artifact import (
    football_artifact_path,
    forecast_digest,
    read_football_forecast,
)
from squadopt.prediction.football import FOOTBALL_MODEL_VERSION


def tree(root):
    return {
        path.relative_to(root).as_posix(): path.read_bytes() if path.is_file() else None
        for path in root.rglob("*")
    }


@pytest.fixture
def case(publication_case, tmp_path, monkeypatch):
    case = publication_case
    case["inputs"] = replace(
        case["inputs"],
        deadline=replace(case["inputs"].deadline, deadline_utc="2099-10-10T10:00:00Z"),
    )
    case["document"]["archive_hashes"] = {"synthetic.csv": "a" * 64}
    case["document"]["fingerprint"] = forecast_digest(case["document"])
    case["snapshot_root"] = tmp_path / "snapshots"
    case["shadow_root"] = tmp_path / "artifacts/shadow/football_team_share_v1"
    case["archive_root"] = tmp_path / "archive-must-not-be-read"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(shadow, "REPOSITORY_ROOT", tmp_path)
    monkeypatch.setattr(shadow, "_repository_state", lambda: ("b" * 40, True))
    for command in (shadow, ordinary):
        monkeypatch.setattr(command, "infer_season", lambda snapshot: case["inputs"].season)
        monkeypatch.setattr(
            command,
            "read_inputs",
            lambda snapshot, **kwargs: replace(
                case["inputs"],
                snapshot_id=snapshot.metadata.snapshot_id,
                captured_at_utc=snapshot.metadata.captured_at_utc,
            ),
        )
        monkeypatch.setattr(command, "produce_football_forecast", lambda *a, **kw: case["document"])
    return case


def build(case):
    return shadow.build_shadow(
        snapshot_root=case["snapshot_root"],
        snapshot_id=case["inputs"].snapshot_id,
        archive_root=case["archive_root"],
        shadow_root=case["shadow_root"],
    )


def test_only_two_files_are_added_and_receipt_agrees_with_reader(case, tmp_path, monkeypatch):
    before = tree(tmp_path)
    calls = []

    def producer(snapshot, archive_root, **kwargs):
        assert snapshot == case["snapshot"]
        assert archive_root == case["archive_root"]
        assert kwargs == dict(contextual=False, manager_words=None, training_seasons=None)
        calls.append("fit")
        return case["document"]

    monkeypatch.setattr(shadow, "produce_football_forecast", producer)
    receipt = build(case)
    after = tree(tmp_path)
    added_files = {name for name in after.keys() - before.keys() if after[name] is not None}
    capture = case["inputs"].snapshot_id
    prefix = "artifacts/shadow/football_team_share_v1"
    assert added_files == {f"{prefix}/football/{capture}.json", f"{prefix}/receipts/{capture}.json"}
    assert {name: after[name] for name in before} == before
    artifact = football_artifact_path(case["shadow_root"], capture)
    forecast = read_football_forecast(artifact, case["inputs"])
    assert calls == ["fit"]
    assert receipt["contract_version"] == "football_shadow_receipt_v1"
    assert receipt["fingerprint"] == forecast.fingerprint
    assert receipt["model_version"] == forecast.horizon.model_version == FOOTBALL_MODEL_VERSION
    assert receipt["artifact_sha256"] == hashlib.sha256(artifact.read_bytes()).hexdigest()
    assert datetime.fromisoformat(receipt["artifact_write_utc"]) == datetime.fromtimestamp(
        artifact.stat().st_mtime, UTC
    )
    assert receipt["written_before_deadline"] is True
    assert receipt["served"] is False
    assert receipt["repository_commit"] == "b" * 40
    assert receipt["repository_tree_clean"] is True
    assert receipt["archive_hashes"] == case["document"]["archive_hashes"]
    assert receipt["wall_seconds"] >= 0
    assert receipt["gameweek"] == 6
    assert receipt["newest_for_gameweek"] is True
    assert receipt["gameweek_captures"] == [
        {"snapshot_id": capture, "captured_at_utc": case["inputs"].captured_at_utc}
    ]
    assert json.loads((case["shadow_root"] / "receipts" / artifact.name).read_bytes()) == receipt


def test_bytes_equal_the_existing_command_without_flags(case, monkeypatch, capsys):
    receipt = build(case)
    ordinary_root = case["shadow_root"].parent / "ordinary"
    monkeypatch.setattr(
        "sys.argv",
        [
            "build_football_forecast",
            "--snapshot-root",
            str(case["snapshot_root"]),
            "--snapshot-id",
            case["inputs"].snapshot_id,
            "--archive-root",
            str(case["archive_root"]),
            "--artifact-root",
            str(ordinary_root),
        ],
    )
    ordinary.main()
    capture = receipt["snapshot_id"]
    assert (
        football_artifact_path(case["shadow_root"], capture).read_bytes()
        == football_artifact_path(ordinary_root, capture).read_bytes()
    )
    assert json.loads(capsys.readouterr().out)["fingerprint"] == receipt["fingerprint"]


@pytest.mark.parametrize(
    "refusal",
    [
        "artifacts",
        "selected-relative",
        "selected-absolute",
        "source",
        "deadline",
        "after-deadline",
        "receipt",
        "selection",
    ],
)
def test_refusal_precedes_archive_or_fit_and_changes_nothing(case, tmp_path, monkeypatch, refusal):
    if refusal == "artifacts":
        case["shadow_root"] = tmp_path / "artifacts" / ".." / "artifacts"
    elif refusal.startswith("selected"):
        selection = tmp_path / "artifacts/backend-artifact-root.json"
        selection.parent.mkdir(exist_ok=True)
        selected = case["shadow_root"]
        if refusal == "selected-relative":
            selected = selected.relative_to(tmp_path)
        selection.write_text(json.dumps({"artifact_root": str(selected)}))
    elif refusal == "source":
        monkeypatch.setattr(
            shadow,
            "read_snapshot",
            lambda *args: replace(
                case["snapshot"], metadata=replace(case["snapshot"].metadata, source="archive")
            ),
        )
    elif refusal in ("deadline", "after-deadline"):
        monkeypatch.setattr(
            shadow,
            "_utc_now",
            lambda: datetime(2099, 10, 10 if refusal == "deadline" else 11, 10, tzinfo=UTC),
        )
    elif refusal == "receipt":
        path = case["shadow_root"] / "receipts" / (case["inputs"].snapshot_id + ".json")
        path.parent.mkdir(parents=True)
        path.write_bytes(b"existing receipt")
    else:
        path = tmp_path / "artifacts/backend-artifact-root.json"
        path.parent.mkdir(exist_ok=True)
        path.write_text('{"unknown": "root"}')
    before = tree(tmp_path)

    def forbidden(*args, **kwargs):
        pytest.fail("Refusal must happen before any archive read or fit")

    monkeypatch.setattr(shadow, "produce_football_forecast", forbidden)
    with pytest.raises(ValueError):
        build(case)
    assert tree(tmp_path) == before


def test_inventory_uses_every_own_target_capture_and_marks_an_older_build(case):
    later = write_snapshot(
        case["snapshot_root"],
        source="fpl-live",
        captured_at_utc="2026-09-22T23:00:00Z",
        payloads=case["snapshot"].payloads,
    )
    receipt = build(case)
    assert receipt["newest_for_gameweek"] is False
    assert [row["snapshot_id"] for row in receipt["gameweek_captures"]] == [
        case["inputs"].snapshot_id,
        later.snapshot_id,
    ]
    assert (
        read_snapshot(case["snapshot_root"], later.snapshot_id).metadata.captured_at_utc
        == receipt["gameweek_captures"][1]["captured_at_utc"]
    )


def test_deadline_crossed_during_fit_publishes_nothing(case, tmp_path, monkeypatch):
    instants = iter([datetime(2099, 10, 10, 9, tzinfo=UTC), datetime(2099, 10, 10, 10, tzinfo=UTC)])
    monkeypatch.setattr(shadow, "_utc_now", lambda: next(instants))
    before = tree(tmp_path)
    with pytest.raises(ValueError, match="during fitting"):
        build(case)
    assert tree(tmp_path) == before


def test_cli_default_root_and_no_model_flags(case, monkeypatch, capsys):
    argv = [
        "build_football_shadow",
        "--snapshot-root",
        str(case["snapshot_root"]),
        "--snapshot-id",
        case["inputs"].snapshot_id,
        "--archive-root",
        str(case["archive_root"]),
    ]
    monkeypatch.setattr("sys.argv", argv)
    shadow.main()
    assert json.loads(capsys.readouterr().out)["contract_version"] == shadow.RECEIPT_CONTRACT
    for flag in (
        "--contextual",
        "--with-components",
        "--role-minutes",
        "--retained-role-history",
        "--training-season",
    ):
        monkeypatch.setattr("sys.argv", [*argv, flag])
        with pytest.raises(SystemExit) as error:
            shadow.main()
        assert error.value.code == 2
