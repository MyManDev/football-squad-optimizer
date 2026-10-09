"""Shadow publication over synthetic captures, with the production publisher and reader."""

import hashlib
import json
import os
import platform
import subprocess
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime
from importlib.metadata import version

import pytest
from scripts import build_football_forecast as ordinary
from scripts import build_football_shadow as shadow
from tests.unit.test_football_publication import publication_case as publication_case

from squadopt.data.snapshots import read_snapshot, write_snapshot
from squadopt.data.sources.fpl_live import BOOTSTRAP_PAYLOAD
from squadopt.live.football_artifact import (
    football_artifact_path,
    forecast_digest,
    read_football_forecast,
)
from squadopt.planning.horizon import APPEARANCE_HORIZON_CONTRACT_VERSION
from squadopt.prediction.football import (
    FOOTBALL_MODEL_VERSION,
    JOINT_ROLE_RETAINED_HISTORY_MODEL_VERSION,
)
from squadopt.prediction.football_contextual import CONTEXTUAL_MODEL_VERSION
from squadopt.prediction.football_minutes_role import RETAINED_HISTORY_ROLE_FEATURE_VERSION


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
    assert receipt["deadline_utc"] == case["inputs"].deadline.deadline_utc
    assert receipt["captured_at_utc"] == case["inputs"].captured_at_utc
    assert receipt["season"] == case["inputs"].season
    assert receipt["served"] is False
    assert receipt["repository_commit"] == "b" * 40
    assert receipt["repository_tree_clean"] is True
    assert receipt["python_version"] == platform.python_version()
    assert receipt["library_versions"] == {
        name: version(name) for name in ("numpy", "scipy", "scikit-learn", "pandas")
    }
    assert receipt["archive_hashes"] == case["document"]["archive_hashes"]
    assert receipt["wall_seconds"] >= 0
    assert receipt["gameweek"] == 6
    assert receipt["newest_for_gameweek"] is True
    assert receipt["ambiguous_latest"] is False
    assert receipt["skipped_captures"] == []
    assert receipt["gameweek_captures"] == [
        {"snapshot_id": capture, "captured_at_utc": case["inputs"].captured_at_utc}
    ]
    assert json.loads((case["shadow_root"] / "receipts" / artifact.name).read_bytes()) == receipt


@pytest.mark.parametrize("seconds", [-1, 0, 1])
def test_receipt_uses_strict_artifact_mtime_not_the_run_clock(case, monkeypatch, seconds):
    deadline = datetime.fromisoformat(case["inputs"].deadline.deadline_utc)
    monkeypatch.setattr(shadow, "_utc_now", lambda: datetime(2099, 10, 10, 9, tzinfo=UTC))
    publisher = shadow.publish_football_artifacts

    def publish(**kwargs):
        publisher(**kwargs)
        artifact = football_artifact_path(kwargs["artifact_root"], case["inputs"].snapshot_id)
        stamp = deadline.timestamp() + seconds
        os.utime(artifact, (stamp, stamp))

    monkeypatch.setattr(shadow, "publish_football_artifacts", publish)
    receipt = build(case)
    assert receipt["written_before_deadline"] is (seconds < 0)
    assert datetime.fromisoformat(receipt["artifact_write_utc"]).timestamp() == (
        deadline.timestamp() + seconds
    )


@pytest.mark.parametrize("encoding", ["utf-8", "utf-8-sig"])
@pytest.mark.parametrize("relative", [False, True])
def test_backend_selection_accepts_another_existing_root(case, tmp_path, encoding, relative):
    selected = tmp_path / "artifacts/served"
    selected.mkdir(parents=True)
    value = selected.relative_to(tmp_path) if relative else selected
    selection = tmp_path / "artifacts/backend-artifact-root.json"
    selection.write_text(json.dumps({"artifact_root": str(value)}), encoding=encoding)
    receipt = build(case)
    assert receipt["served"] is False
    assert receipt["model_version"] == FOOTBALL_MODEL_VERSION


@pytest.mark.parametrize("encoding", ["utf-8", "utf-8-sig"])
def test_relative_selected_root_is_anchored_to_repository_not_working_directory(
    case, tmp_path, monkeypatch, encoding
):
    selection = tmp_path / "artifacts/backend-artifact-root.json"
    selection.parent.mkdir(exist_ok=True)
    selection.write_text(
        json.dumps({"artifact_root": str(case["shadow_root"].relative_to(tmp_path))}),
        encoding=encoding,
    )
    sibling = tmp_path.parent / (tmp_path.name + "-sibling")
    sibling.mkdir()
    monkeypatch.chdir(sibling)
    before = tree(tmp_path)

    def forbidden(*args, **kwargs):
        pytest.fail("Selected-root refusal must precede archive reads and fitting")

    monkeypatch.setattr(shadow, "produce_football_forecast", forbidden)
    with pytest.raises(ValueError, match="shadow root"):
        build(case)
    assert tree(tmp_path) == before


def test_real_repository_state_reports_clean_and_dirty_without_optional_locks(
    tmp_path, monkeypatch
):
    repository = tmp_path / "repository"
    repository.mkdir()

    def git(*args):
        return subprocess.check_output(["git", "-C", str(repository), *args], text=True).strip()

    git("init", "--initial-branch=fixture")
    (repository / "tracked.txt").write_text("invented repository\n", encoding="utf-8")
    git("add", "tracked.txt")
    git(
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=fixture@example.invalid",
        "commit",
        "-m",
        "fixture",
    )
    expected_head = git("rev-parse", "HEAD")
    monkeypatch.setattr(shadow, "REPOSITORY_ROOT", repository)
    calls = []
    original = subprocess.check_output

    def checked(command, **kwargs):
        calls.append(command)
        return original(command, **kwargs)

    monkeypatch.setattr(shadow.subprocess, "check_output", checked)
    assert shadow._repository_state() == (expected_head, True)
    (repository / "untracked.txt").write_text("new file\n", encoding="utf-8")
    assert shadow._repository_state() == (expected_head, False)
    assert len(calls) == 4
    assert all(
        command[:4] == ["git", "--no-optional-locks", "-C", str(repository)] for command in calls
    )


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


@pytest.mark.parametrize("older_build", [False, True])
def test_inventory_uses_every_own_target_capture_and_marks_an_older_build(
    case, monkeypatch, older_build
):
    later = write_snapshot(
        case["snapshot_root"],
        source="fpl-live",
        captured_at_utc="2026-09-22T23:00:00Z" if older_build else "2026-09-22T10:00:00Z",
        payloads=case["snapshot"].payloads,
    )
    wrong_week = write_snapshot(
        case["snapshot_root"],
        source="fpl-live",
        captured_at_utc="2026-09-22T19:00:00Z",
        payloads=case["snapshot"].payloads,
    )
    wrong_season = write_snapshot(
        case["snapshot_root"],
        source="fpl-live",
        captured_at_utc="2026-09-22T20:00:00Z",
        payloads=case["snapshot"].payloads,
    )
    monkeypatch.setattr(
        shadow,
        "infer_season",
        lambda snapshot: (
            "2025-26"
            if snapshot.metadata.snapshot_id == wrong_season.snapshot_id
            else case["inputs"].season
        ),
    )
    original_inputs = shadow.read_inputs
    monkeypatch.setattr(
        shadow,
        "read_inputs",
        lambda snapshot, **kwargs: replace(
            original_inputs(snapshot, **kwargs),
            deadline=replace(case["inputs"].deadline, gameweek=5)
            if snapshot.metadata.snapshot_id == wrong_week.snapshot_id
            else case["inputs"].deadline,
        ),
    )
    # Deliberately unsorted enumeration makes the capture-order assertion meaningful.
    monkeypatch.setattr(
        shadow,
        "list_snapshot_ids",
        lambda *args, **kwargs: [
            later.snapshot_id,
            wrong_season.snapshot_id,
            case["inputs"].snapshot_id,
            wrong_week.snapshot_id,
        ],
    )
    receipt = build(case)
    assert receipt["newest_for_gameweek"] is (not older_build)
    expected = [case["inputs"].snapshot_id, later.snapshot_id]
    if not older_build:
        expected.reverse()
    assert [row["snapshot_id"] for row in receipt["gameweek_captures"]] == expected
    assert (
        read_snapshot(case["snapshot_root"], later.snapshot_id).metadata.captured_at_utc
        == receipt["gameweek_captures"][1 if older_build else 0]["captured_at_utc"]
    )


def test_inventory_refuses_when_decision_capture_is_missing(case, tmp_path):
    missing_root = tmp_path / "inventory-without-decision"
    write_snapshot(
        missing_root,
        source="fpl-live",
        captured_at_utc="2026-09-22T23:00:00Z",
        payloads=case["snapshot"].payloads,
    )
    before = tree(tmp_path)
    with pytest.raises(ValueError, match="decision capture is absent"):
        shadow._gameweek_captures(missing_root, case["inputs"])
    assert tree(tmp_path) == before


@pytest.mark.parametrize("damage", ["missing-decision", "unreadable-capture"])
def test_inventory_refusal_happens_before_fit_and_writes_nothing(
    case, tmp_path, monkeypatch, damage
):
    other = write_snapshot(
        case["snapshot_root"],
        source="fpl-live",
        captured_at_utc="2026-09-22T23:00:00Z",
        payloads=case["snapshot"].payloads,
    )
    if damage == "missing-decision":
        monkeypatch.setattr(
            shadow, "list_snapshot_ids", lambda *args, **kwargs: [other.snapshot_id]
        )
    else:
        read = shadow.read_snapshot

        def unreadable(root, identifier):
            if identifier == other.snapshot_id:
                raise ValueError("synthetic unreadable capture")
            return read(root, identifier)

        monkeypatch.setattr(shadow, "read_snapshot", unreadable)

    def forbidden(*args, **kwargs):
        pytest.fail("Inventory refusal must precede archive reads and fitting")

    monkeypatch.setattr(shadow, "produce_football_forecast", forbidden)
    before = tree(tmp_path)
    with pytest.raises(ValueError, match=r"decision capture is absent|unreadable capture"):
        build(case)
    assert tree(tmp_path) == before


def test_incomplete_capture_is_skipped_before_season_read_and_recorded(case, monkeypatch):
    interrupted = write_snapshot(
        case["snapshot_root"],
        source="fpl-live",
        captured_at_utc="2026-09-22T23:00:00Z",
        payloads={"interrupted.json": b"{}"},
    )
    infer = shadow.infer_season
    inferred = []

    def complete_only(snapshot):
        assert BOOTSTRAP_PAYLOAD in snapshot.payloads, "incomplete capture reached the parser"
        inferred.append(snapshot.metadata.snapshot_id)
        return infer(snapshot)

    monkeypatch.setattr(shadow, "infer_season", complete_only)
    receipt = build(case)
    assert receipt["skipped_captures"] == [interrupted.snapshot_id]
    assert interrupted.snapshot_id not in inferred
    assert receipt["gameweek_captures"] == [
        {
            "snapshot_id": case["inputs"].snapshot_id,
            "captured_at_utc": case["inputs"].captured_at_utc,
        }
    ]
    assert receipt["newest_for_gameweek"] is True
    assert receipt["ambiguous_latest"] is False


@pytest.mark.parametrize("tie", ["decision-latest", "later-latest", "older-only"])
def test_capture_ties_match_latest_selection_ambiguity(case, tie):
    stamp = {
        "decision-latest": case["inputs"].captured_at_utc,
        "later-latest": "2026-09-22T23:00:00Z",
        "older-only": "2026-09-22T10:00:00Z",
    }[tie]
    for variant in range(1 if tie == "decision-latest" else 2):
        write_snapshot(
            case["snapshot_root"],
            source="fpl-live",
            captured_at_utc=stamp,
            payloads={**case["snapshot"].payloads, "tie.json": str(variant).encode()},
        )
    receipt = build(case)
    assert receipt["ambiguous_latest"] is (tie != "older-only")
    assert receipt["newest_for_gameweek"] is (tie == "older-only")
    assert receipt["skipped_captures"] == []


@pytest.mark.parametrize(
    "version", [JOINT_ROLE_RETAINED_HISTORY_MODEL_VERSION, CONTEXTUAL_MODEL_VERSION]
)
@pytest.mark.parametrize("guard", ["producer", "reader"])
def test_both_v1_guards_refuse_valid_other_versions_without_changes(
    case, tmp_path, monkeypatch, version, guard
):
    document = deepcopy(case["document"])
    document["model_version"] = version
    if version == JOINT_ROLE_RETAINED_HISTORY_MODEL_VERSION:
        document["role_metadata"] = {"role_feature_version": RETAINED_HISTORY_ROLE_FEATURE_VERSION}
    else:
        document["availability_application"] = "before_team_shares_v1"
        document["projection_contract"] = APPEARANCE_HORIZON_CONTRACT_VERSION
    document["fingerprint"] = forecast_digest(document)
    valid_other = tmp_path / "valid-other-version.json"
    valid_other.write_text(json.dumps(document), encoding="utf-8")
    other_forecast = read_football_forecast(valid_other, case["inputs"])
    assert other_forecast.horizon.model_version == version
    if guard == "producer":
        case["document"] = document
    else:
        # Existing valid v1 bytes let publication replay without changing the tree.
        shadow.publish_football_artifacts(
            artifact_root=case["shadow_root"],
            snapshot=case["snapshot"],
            inputs=case["inputs"],
            document=case["document"],
            companion=None,
        )
        monkeypatch.setattr(shadow, "read_football_forecast", lambda *args: other_forecast)
    before = tree(tmp_path)
    with pytest.raises(ValueError, match=f"shadow {guard} must return football_team_share_v1"):
        build(case)
    assert tree(tmp_path) == before


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
