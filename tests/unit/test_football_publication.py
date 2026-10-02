"""Immutable pair publication over synthetic source bytes; no archive or live stores."""

import json
from copy import deepcopy
from pathlib import Path

import pandas as pd
import pytest
from scripts import build_football_forecast as command
from tests.unit.test_football_minute_integration import world
from tests.unit.test_minute_evidence import documents

from squadopt.data import atomic
from squadopt.data.errors import ConflictingBytesError
from squadopt.data.snapshots import read_snapshot, write_snapshot
from squadopt.data.sources.fpl_live import BOOTSTRAP_PAYLOAD, FIXTURES_PAYLOAD
from squadopt.live.football_artifact import football_artifact_path, forecast_digest
from squadopt.platform import football_publication as publication
from squadopt.platform.football_minute_basis import football_components_path


@pytest.fixture
def publication_case(tmp_path):
    served, companion, calendar, clubs = deepcopy(documents(dgw=True, eligibility=0.5))
    # The live reader requires the entire five-week window, including the original
    # double. Extend the synthetic second week without changing its football math.
    for week in (8, 9, 10):
        for row in [row for row in companion["rows"] if row["GW"] == 7]:
            added = dict(row, GW=week, fixture=row["fixture"] + 100 * (week - 7))
            added["kickoff"] = (
                pd.Timestamp(row["kickoff"]) + pd.Timedelta(weeks=week - 7)
            ).isoformat()
            companion["rows"].append(added)
        served["rows"].extend(
            dict(row, gameweek=week) for row in list(served["rows"]) if row["gameweek"] == 7
        )
    companion["gameweeks"] = [6, 7, 8, 9, 10]
    calendar = pd.DataFrame(companion["rows"])[
        ["GW", "fixture", "kickoff", "club", "opponent", "home"]
    ].drop_duplicates()
    bootstrap = {
        "teams": [{"id": club + 100, "code": club} for club in sorted(set(clubs.values()))],
        "elements": [{"code": player, "team": club + 100} for player, club in clubs.items()],
    }
    fixtures = [
        {
            "id": int(row.fixture),
            "event": int(row.GW),
            "team_h": int(row.club) + 100,
            "team_a": int(row.opponent) + 100,
            "kickoff_time": row.kickoff,
        }
        for row in calendar.loc[calendar.home.eq(1)].itertuples()
    ]
    snapshots = tmp_path / "snapshots"
    metadata = write_snapshot(
        snapshots,
        source="fpl-live",
        captured_at_utc=served["captured_at_utc"],
        payloads={
            BOOTSTRAP_PAYLOAD: json.dumps(bootstrap).encode(),
            FIXTURES_PAYLOAD: json.dumps(fixtures).encode(),
        },
    )
    snapshot = read_snapshot(snapshots, metadata.snapshot_id)
    for doc in (served, companion):
        doc.update(
            source_snapshot_id=metadata.snapshot_id,
            captured_at_utc=metadata.captured_at_utc,
            source_fingerprint=metadata.fingerprint,
        )
    served["fingerprint"] = forecast_digest(served)
    companion["forecast_fingerprint"] = served["fingerprint"]
    companion["fingerprint"] = forecast_digest(companion)
    _, inputs, _, _ = world((served, companion, calendar, clubs))
    return dict(
        artifact_root=tmp_path / "artifacts",
        snapshot=snapshot,
        inputs=inputs,
        document=served,
        companion=companion,
    )


def paths(case):
    return (
        football_artifact_path(case["artifact_root"], case["inputs"].snapshot_id),
        football_components_path(case["artifact_root"], case["inputs"].snapshot_id),
    )


def test_pair_is_validated_and_replay_preserves_existing_bytes(publication_case):
    case = publication_case
    forecast, companion = paths(case)
    forecast.parent.mkdir(parents=True)
    existing = json.dumps(case["document"], indent=4).encode()
    forecast.write_bytes(existing)
    assert publication.publish_football_artifacts(**case) == (forecast, companion)
    component_bytes = companion.read_bytes()
    publication.publish_football_artifacts(**case)
    assert forecast.read_bytes() == existing
    assert companion.read_bytes() == component_bytes
    assert not list(forecast.parent.glob(".*"))


@pytest.mark.parametrize("occupied", [0, 1])
def test_either_existing_mismatch_refuses_before_creating_other_half(publication_case, occupied):
    case = publication_case
    targets = paths(case)
    targets[occupied].parent.mkdir(parents=True)
    targets[occupied].write_bytes(b'{"different": true}')
    with pytest.raises(ValueError, match="different football document"):
        publication.publish_football_artifacts(**case)
    assert targets[occupied].read_bytes() == b'{"different": true}'
    assert not targets[1 - occupied].exists()


@pytest.mark.parametrize("damage", ["source", "calendar", "availability", "points"])
def test_invalid_pair_never_publishes_either_half(publication_case, damage):
    case = publication_case
    companion = case["companion"]
    if damage == "source":
        for doc in (case["document"], companion):
            doc["source_fingerprint"] = "f" * 64
        case["document"]["fingerprint"] = forecast_digest(case["document"])
        companion["forecast_fingerprint"] = case["document"]["fingerprint"]
    elif damage == "calendar":
        companion["rows"][0]["kickoff"] = "2026-09-24T15:00:00+00:00"
    elif damage == "availability":
        companion["captured_availability"]["multipliers"][0]["multiplier"] = 1.0
    else:
        companion["rows"][0]["expected_points"] += 1.0
    companion["fingerprint"] = forecast_digest(companion)
    with pytest.raises(ValueError):
        publication.publish_football_artifacts(**case)
    assert not any(path.exists() for path in paths(case))


def test_competing_writer_cannot_be_overwritten(publication_case, monkeypatch):
    case = publication_case
    _, component_target = paths(case)
    original_link = atomic.os.link

    def competing_link(source, destination):
        if Path(destination).name == component_target.name:
            component_target.write_bytes(b'{"other writer": true}')
        return original_link(source, destination)

    monkeypatch.setattr(atomic.os, "link", competing_link)
    with pytest.raises(ConflictingBytesError):
        publication.publish_football_artifacts(**case)
    assert component_target.read_bytes() == b'{"other writer": true}'
    assert not paths(case)[0].exists()


def test_interrupted_pair_can_complete_without_replacing_companion(publication_case, monkeypatch):
    case = publication_case
    forecast, companion = paths(case)
    original_write = publication.write_bytes_once

    def interrupted(payload, path, **kwargs):
        if path == forecast:
            raise OSError("synthetic interruption")
        return original_write(payload, path, **kwargs)

    monkeypatch.setattr(publication, "write_bytes_once", interrupted)
    with pytest.raises(OSError, match="synthetic interruption"):
        publication.publish_football_artifacts(**case)
    saved = companion.read_bytes()
    assert not forecast.exists()
    monkeypatch.setattr(publication, "write_bytes_once", original_write)
    publication.publish_football_artifacts(**case)
    assert companion.read_bytes() == saved
    assert forecast.exists()


def test_active_publication_marker_refuses_without_removing_it(publication_case):
    case = publication_case
    forecast, _ = paths(case)
    forecast.parent.mkdir(parents=True)
    marker = forecast.with_name(f".{forecast.stem}.publication.lock")
    marker.write_bytes(b"another publication")
    with pytest.raises(FileExistsError):
        publication.publish_football_artifacts(**case)
    assert marker.read_bytes() == b"another publication"
    assert not any(path.exists() for path in paths(case))


@pytest.mark.parametrize("with_components", [False, True])
@pytest.mark.parametrize("training_seasons", [None, ["2022-23", "2024-25"]])
def test_cli_selects_one_producer_and_keeps_default_output(
    publication_case, monkeypatch, capsys, with_components, training_seasons
):
    case = publication_case
    calls = []

    def ordinary(*args, **kwargs):
        assert kwargs["training_seasons"] == training_seasons
        calls.append("ordinary")
        return case["document"]

    def paired(*args, **kwargs):
        assert kwargs["training_seasons"] == training_seasons
        calls.append("paired")
        return case["document"], case["companion"]

    monkeypatch.setattr(command, "produce_football_forecast", ordinary)
    monkeypatch.setattr(command, "produce_football_components", paired)
    monkeypatch.setattr(command, "read_snapshot", lambda *args: case["snapshot"])
    monkeypatch.setattr(command, "read_inputs", lambda *args, **kwargs: case["inputs"])
    monkeypatch.setattr(command, "infer_season", lambda *args: case["inputs"].season)
    argv = [
        "build_football_forecast.py",
        "--snapshot-root",
        "unused-synthetic",
        "--snapshot-id",
        case["inputs"].snapshot_id,
        "--archive-root",
        "must-not-be-read",
        "--artifact-root",
        str(case["artifact_root"]),
    ]
    for season in training_seasons or []:
        argv.extend(["--training-season", season])
    if with_components:
        argv.append("--with-components")
    monkeypatch.setattr("sys.argv", argv)
    command.main()
    assert calls == ["paired" if with_components else "ordinary"]
    output = json.loads(capsys.readouterr().out)
    expected = {
        "fingerprint": case["document"]["fingerprint"],
        "rows": len(case["document"]["rows"]),
        "model_version": case["document"]["model_version"],
    }
    if with_components:
        expected["components_fingerprint"] = case["companion"]["fingerprint"]
    assert output == expected
    assert paths(case)[1].exists() is with_components


@pytest.mark.parametrize(
    "extra",
    [["--contextual"], ["--rotation-evidence", "unused", "--club-news-source", "unused"]],
)
def test_cli_refuses_incompatible_mode_before_read_or_fit(monkeypatch, extra):
    def forbidden(*args, **kwargs):
        pytest.fail("An incompatible mode must fail before reading or fitting")

    monkeypatch.setattr(command, "read_snapshot", forbidden)
    monkeypatch.setattr(command, "produce_football_components", forbidden)
    monkeypatch.setattr(
        "sys.argv",
        [
            "build_football_forecast.py",
            "--snapshot-root",
            "unused",
            "--snapshot-id",
            "synthetic",
            "--archive-root",
            "unused",
            "--artifact-root",
            "unused",
            "--with-components",
            *extra,
        ],
    )
    with pytest.raises(SystemExit) as error:
        command.main()
    assert error.value.code == 2
