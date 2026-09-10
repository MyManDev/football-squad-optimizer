"""Installed publication services use named captures and preserve the public contracts."""

import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
import scripts.build_league_site as league_cli
import scripts.build_scoreboard as scoreboard_cli
import tests.unit.test_advice_worker as member_fixture
import tests.unit.test_backend_runtime as handoff_fixture
import tests.unit.test_source_vaastav as archive_fixture

from squadopt.application import capture_entries, league_publication, scoreboard
from squadopt.application.league_publication import (
    LeaguePublicationRequest,
    prepare_league_publication,
    publish_league,
)
from squadopt.application.site_publication import SitePublicationRequest, publish_site
from squadopt.data.errors import DataError
from squadopt.data.snapshots import read_snapshot, write_snapshot
from squadopt.data.sources.vaastav import SUPPORTED_SEASONS
from squadopt.platform import capture_context
from squadopt.platform.publication_workers import league_mapper

NOW = datetime(2026, 8, 27, 10, tzinfo=UTC)


def publication_world(tmp_path: Path) -> LeaguePublicationRequest:
    """A capture, archive and handoff generated entirely from synthetic fixture builders."""

    snapshot_root = tmp_path / "snapshots"
    initial_id = member_fixture._capture_with_entries(snapshot_root)
    payloads = dict(read_snapshot(snapshot_root, initial_id).payloads)
    bootstrap = json.loads(payloads["bootstrap-static.json"])
    # The publication path additionally requires the source's final-score marker.
    # The worker fixture does not need it; no score has been confirmed in this fixture.
    for event in bootstrap["events"]:
        event["data_checked"] = False
    payloads["bootstrap-static.json"] = json.dumps(bootstrap).encode("utf-8")
    snapshot_id = write_snapshot(
        snapshot_root,
        source="fpl-live",
        captured_at_utc="2026-08-27T09:30:00Z",
        payloads=payloads,
    ).snapshot_id
    handoff = handoff_fixture._handoff(tmp_path / "handoffs", snapshot_id)
    archive = tmp_path / "archive"
    for season in SUPPORTED_SEASONS:
        archive_fixture._archive(
            tmp_path,
            [archive_fixture._gameweek_row(round_=1), archive_fixture._gameweek_row(round_=2)],
            season=season,
        )
    registry = tmp_path / "registry.json"
    registry.write_text(
        json.dumps(
            {
                "contract_version": "entry_registry_v1",
                "entries": [{"entry_id": member_fixture.ENTRY_ID, "label": "Synthetic member"}],
            }
        ),
        encoding="utf-8",
    )
    return LeaguePublicationRequest(
        snapshot_root=snapshot_root,
        snapshot_id=snapshot_id,
        archive_root=archive,
        registry_path=registry,
        out_dir=tmp_path / "site",
        league_id=352490,
        season=member_fixture.SEASON,
        gameweek=2,
        handoff_path=handoff,
        record_root=tmp_path / "records",
        rival_menu=False,
        now=NOW,
    )


def test_old_helpers_reexport_the_installed_owners() -> None:
    assert league_cli.member_points is league_publication.member_points
    assert league_cli.last_scored_gameweek is league_publication.last_scored_gameweek
    assert scoreboard_cli.scoreboard_payload is scoreboard.scoreboard_payload
    assert scoreboard_cli.CohortCapture is scoreboard.CohortCapture
    assert scoreboard_cli.CohortPicks is scoreboard.CohortPicks
    assert capture_context.CapturePicksProvider is capture_entries.CapturePicksProvider
    assert capture_context.capture_element_codes is capture_entries.capture_element_codes


def test_preparing_a_named_capture_neither_solves_nor_writes(tmp_path: Path) -> None:
    request = publication_world(tmp_path)
    # The panel is not needed for a dry run. Its absence would fail a real publication.
    request = replace(request, archive_root=tmp_path / "not-present")
    prepared = prepare_league_publication(request)
    assert prepared.request.snapshot_id == request.snapshot_id
    assert prepared.inputs.deadline.gameweek == 2
    assert len(prepared.registrations) == 1
    assert not request.out_dir.exists()
    assert request.record_root is not None and not request.record_root.exists()


def test_installed_member_publication_and_pool_write_the_same_contracts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SQUADOPT_REPOSITORY_COMMIT", "c" * 40)
    request = publication_world(tmp_path)
    first = publish_league(request)
    assert first.report.rendered_count == 1
    assert first.gameweek == 2 and first.snapshot_id == request.snapshot_id
    assert all(path.is_file() for path in first.output_paths)
    assert any(path.name == "advice.json" for path in first.output_paths)
    assert any(path.name == "manifest.json" for path in first.output_paths)
    history = request.out_dir / "data/league/history" / f"{member_fixture.ENTRY_ID}.json"
    assert history in first.output_paths
    document = json.loads(history.read_text(encoding="utf-8"))
    assert document["payload"]["weeks"][0]["status"] == "unsettled"
    assert document["payload"]["weeks"][0]["advice_generated_at_utc"] == "2026-08-27T10:00:00Z"

    parallel = replace(request, out_dir=tmp_path / "parallel")
    with league_mapper(parallel, workers=2) as mapper:
        second = publish_league(parallel, mapper=mapper)
    assert first.report.files == second.report.files
    for name in first.report.files:
        assert (request.out_dir / "data/league" / name).read_bytes() == (
            parallel.out_dir / "data/league" / name
        ).read_bytes()
    assert (
        history.read_bytes()
        == (
            parallel.out_dir / "data/league/history" / f"{member_fixture.ENTRY_ID}.json"
        ).read_bytes()
    )


def test_scoreboard_service_uses_the_named_capture_and_returns_the_written_path(
    tmp_path: Path,
) -> None:
    request = publication_world(tmp_path)
    # A newer live capture is deliberately unusable; an implicit latest read would fail.
    write_snapshot(
        request.snapshot_root,
        source="fpl-live",
        captured_at_utc="2026-08-28T10:00:00Z",
        payloads={"bootstrap-static.json": b"{}"},
    )
    result = scoreboard.publish_scoreboard(
        scoreboard.ScoreboardPublicationRequest(
            snapshot_root=request.snapshot_root,
            snapshot_id=request.snapshot_id,
            registry_path=request.registry_path,
            ledger_root=tmp_path / "empty-ledger",
            out_dir=request.out_dir,
            league_id=request.league_id,
            season=request.season,
            now_utc="2026-08-27T10:00:00Z",
        )
    )
    assert result.output_paths == (request.out_dir / "data/league/scoreboard.json",)
    assert result.snapshot_id == request.snapshot_id
    raw = result.target.read_bytes()
    assert json.loads(raw)["payload"]["source_snapshot_id"] == request.snapshot_id
    assert raw.endswith(b"\n")
    assert result.document["generated_at_utc"] == "2026-08-27T10:00:00Z"


def test_site_publication_pins_its_read_only_status_and_league_to_one_capture(
    tmp_path: Path,
) -> None:
    request = publication_world(tmp_path)
    write_snapshot(
        request.snapshot_root,
        source="fpl-live",
        captured_at_utc="2026-08-28T10:00:00Z",
        payloads={"bootstrap-static.json": b"{}"},
    )
    ledger_root = tmp_path / "empty-ledger"
    result = publish_site(
        SitePublicationRequest(
            snapshot_root=request.snapshot_root,
            snapshot_id=request.snapshot_id,
            ledger_root=ledger_root,
            archive_root=request.archive_root,
            handoff_root=tmp_path / "handoffs",
            summary_root=tmp_path / "summaries",
            log_root=tmp_path / "logs",
            out_dir=request.out_dir,
            season=request.season,
            now_utc="2026-08-27T10:00:00Z",
        )
    )
    assert result.snapshot_id == request.snapshot_id
    assert result.report.status_written and result.report.league_written
    assert all(path.is_file() for path in result.output_paths)
    assert len(result.output_paths) == len(result.report.files)
    assert not ledger_root.exists(), "rendering a tick plan must not execute any action"
    assert not (tmp_path / "summaries").exists()


def test_site_publication_rejects_a_pinned_non_live_capture(tmp_path: Path) -> None:
    request = publication_world(tmp_path)
    cohort = write_snapshot(
        request.snapshot_root,
        source="fpl-top100",
        captured_at_utc="2026-08-28T10:00:00Z",
        payloads={"bootstrap-static.json": b"{}"},
    )
    with pytest.raises(DataError, match="not an fpl-live capture"):
        publish_site(
            SitePublicationRequest(
                snapshot_root=request.snapshot_root,
                snapshot_id=cohort.snapshot_id,
                ledger_root=tmp_path / "empty-ledger",
                archive_root=request.archive_root,
                handoff_root=tmp_path / "handoffs",
                summary_root=tmp_path / "summaries",
                log_root=tmp_path / "logs",
                out_dir=request.out_dir,
                season=request.season,
                now_utc="2026-08-27T10:00:00Z",
            )
        )
    assert not request.out_dir.exists()
