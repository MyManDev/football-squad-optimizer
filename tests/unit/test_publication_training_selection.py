"""Prospective publication never opens an archive outside its explicit selection.

All archive bytes below are synthetic. No fit, solve, network or held data is used.
"""

import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from scripts import build_league_site, build_projection_handoff
from tests.unit import test_build_projection_handoff as handoff_fixture
from tests.unit import test_source_vaastav as player_fixture
from tests.unit import test_source_vaastav_fixtures as fixture_fixture
from tests.unit.test_publication_services import publication_world

from squadopt.application import league_publication, projection_handoff
from squadopt.application.publication_history import explicit_archive_seasons
from squadopt.data.errors import DataSourceError
from squadopt.data.snapshots import read_snapshot, write_snapshot
from squadopt.data.sources import vaastav
from squadopt.platform import publication_workers

ARCHIVES = ("2022-23", "2023-24", "2024-25")
SELECTED = (*ARCHIVES, "2026-27")
BASELINE_ARCHIVES = ("2021-22", *ARCHIVES)
BASELINE_SELECTED = (*BASELINE_ARCHIVES, "2026-27")


class ReachedBoundary(Exception):
    """The real readers completed; stop before a fit, solve or publication."""


def _guard_archive_reads(
    monkeypatch: pytest.MonkeyPatch, archives: tuple[str, ...] = ARCHIVES
) -> set[str]:
    opened: set[str] = set()
    original = vaastav._read_required

    def read(path: Path, required: Any, label: str) -> pd.DataFrame:
        # This hook is immediately before the real CSV open, not a fake panel loader.
        assert any(season in path.parts for season in archives), path
        assert "2025-26" not in path.parts and "2020-21" not in path.parts, path
        opened.add(Path(*path.parts[path.parts.index("data") + 1 :]).as_posix())
        return original(path, required, label)

    monkeypatch.setattr(vaastav, "_read_required", read)
    return opened


@pytest.mark.parametrize(
    "selected",
    [
        (),
        ("2026-27",),
        ("2022-23",),
        ("2025-26", "2026-27"),
        ("2020-21", "2026-27"),
        (*BASELINE_SELECTED, "2025-26"),
        (*SELECTED, "2024-25"),
        ("../2024-25", "2026-27"),
        "2024-25",
        (1, "2026-27"),
    ],
)
def test_bad_selection_refuses_before_even_opening_the_capture(
    tmp_path: Path, selected: Any
) -> None:
    with pytest.raises(DataSourceError, match="Explicit training seasons"):
        projection_handoff.build(
            tmp_path / "missing-captures",
            tmp_path / "missing-archive",
            tmp_path / "handoffs",
            snapshot_id="not-present",
            training_seasons=selected,
        )


def test_current_season_is_capture_permission_not_an_archive_directory() -> None:
    assert explicit_archive_seasons(tuple(reversed(SELECTED))) == ARCHIVES
    assert explicit_archive_seasons(("2024-25", "2026-27")) == ("2024-25",)
    with pytest.raises(DataSourceError, match="Explicit training seasons"):
        explicit_archive_seasons(SELECTED, current_season="2025-26")


def test_baseline_can_preserve_its_existing_component_training_population() -> None:
    assert explicit_archive_seasons(BASELINE_SELECTED) == (
        projection_handoff.COMPONENT_TRAINING_SEASONS
    )
    assert explicit_archive_seasons(("2021-22", "2026-27")) == ("2021-22",)


@pytest.mark.parametrize("worker", [False, True])
@pytest.mark.parametrize("archives", [ARCHIVES, BASELINE_ARCHIVES])
def test_parent_and_worker_only_open_selected_synthetic_archive_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, worker: bool, archives: tuple[str, ...]
) -> None:
    request = replace(publication_world(tmp_path), training_seasons=(*archives, "2026-27"))
    opened = _guard_archive_reads(monkeypatch, archives)
    if worker:
        monkeypatch.setattr(publication_workers, "_WORKER_CONTEXT", {})
        publication_workers._worker_init(
            str(request.snapshot_root),
            request.snapshot_id,
            str(request.season),
            str(request.handoff_path),
            str(request.archive_root),
            request.gameweek,
            request=request,
        )
        assert publication_workers._WORKER_CONTEXT["inputs"].snapshot_id == request.snapshot_id
    else:

        def stop(*_args: Any, **_kwargs: Any) -> Any:
            raise ReachedBoundary

        monkeypatch.setattr(league_publication, "build_league_views", stop)
        with pytest.raises(ReachedBoundary):
            league_publication.publish_league(request)
    assert opened == {
        f"{season}/{name}"
        for season in archives
        for name in ("gws/merged_gw.csv", "players_raw.csv")
    }


def test_component_fit_inputs_use_the_same_selection_before_any_fit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archives = BASELINE_ARCHIVES
    for season in archives:
        archive = player_fixture._archive(tmp_path, [player_fixture._gameweek_row()], season=season)
        fixture_fixture._archive(
            tmp_path,
            [fixture_fixture._fixture_row(kickoff=f"{season[:4]}-08-15T19:00:00Z")],
            season=season,
        )
    opened = _guard_archive_reads(monkeypatch, archives)

    def stop(
        panel: pd.DataFrame,
        fixtures: pd.DataFrame,
        clubs: pd.DataFrame,
        *,
        seasons: Any,
        **_kwargs: Any,
    ) -> Any:
        assert tuple(seasons) == archives
        assert set(panel.season) == set(fixtures.season) == set(clubs.season) == set(archives)
        raise ReachedBoundary

    monkeypatch.setattr(projection_handoff, "build_component_modelling_frame", stop)
    with pytest.raises(ReachedBoundary):
        projection_handoff._component_table(
            archive,
            bootstrap=b"{}",
            fixtures=b"[]",
            event_payloads={},
            season="2026-27",
            target=2,
            source_snapshot_id="synthetic",
            captured_at_utc="2026-08-28T15:30:00Z",
            deadline_utc="2026-08-29T10:00:00Z",
            fallback=pd.DataFrame(),
            training_seasons=(*archives, "2026-27"),
        )
    assert opened == {
        f"{season}/{name}"
        for season in archives
        for name in ("gws/merged_gw.csv", "players_raw.csv", "teams.csv", "fixtures.csv")
    }


@pytest.mark.parametrize("archives", [ARCHIVES, ("2021-22",), ("2024-25",)])
def test_phase_c_refuses_a_subset_before_reading_or_fitting_any_archive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, archives: tuple[str, ...]
) -> None:
    def forbidden(*_args: Any, **_kwargs: Any) -> Any:
        pytest.fail("A different training population must not use the Phase C version.")

    monkeypatch.setattr(projection_handoff, "build_panel", forbidden)
    monkeypatch.setattr(projection_handoff, "build_fixture_panel", forbidden)
    monkeypatch.setattr(projection_handoff, "load_team_codes", forbidden)
    monkeypatch.setattr(projection_handoff, "fit_component_models", forbidden)
    with pytest.raises(DataSourceError, match="requires the full Phase C training population"):
        projection_handoff._component_table(
            tmp_path / "unused-archive",
            bootstrap=b"{}",
            fixtures=b"[]",
            event_payloads={},
            season="2026-27",
            target=2,
            source_snapshot_id="synthetic",
            captured_at_utc="2026-08-28T15:30:00Z",
            deadline_utc="2026-08-29T10:00:00Z",
            fallback=pd.DataFrame(),
            training_seasons=(*archives, "2026-27"),
        )


def test_handoff_forwards_selection_to_fallback_and_component_and_records_actual_roles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = handoff_fixture._world.__wrapped__(tmp_path, monkeypatch)
    original = read_snapshot(world["snapshot_root"], world["after"])
    capture = write_snapshot(
        world["snapshot_root"],
        source="fpl-live",
        captured_at_utc=original.metadata.captured_at_utc,
        payloads={**original.payloads, "event-gw01-live.json": handoff_fixture._live()},
    )
    calls = []

    def panel(_root: Path, *, seasons: Any) -> pd.DataFrame:
        calls.append(tuple(seasons))
        return handoff_fixture._panel().assign(season="2024-25")

    def component(
        *_args: Any, fallback: pd.DataFrame, training_seasons: Any, **_kwargs: Any
    ) -> Any:
        assert tuple(training_seasons) == BASELINE_SELECTED
        return fallback.copy(), {"component_training_seasons": list(BASELINE_ARCHIVES)}

    monkeypatch.setattr(projection_handoff, "build_panel", panel)
    monkeypatch.setattr(projection_handoff, "_component_table", component)
    _projection, written, report = handoff_fixture._build(
        world,
        snapshot_id=capture.snapshot_id,
        training_seasons=BASELINE_SELECTED,
        dry_run=True,
    )
    assert written is None and calls == [BASELINE_ARCHIVES]
    assert report["fallback_training_seasons"] == list(BASELINE_ARCHIVES)
    assert report["component_training_seasons"] == list(BASELINE_ARCHIVES)
    assert report["training_selection"] == {
        "contract_version": "prospective_training_selection_v1",
        "allowed_seasons": list(BASELINE_SELECTED),
        "archive_seasons_read": list(BASELINE_ARCHIVES),
        "captured_history_season": "2026-27",
        "captured_history_role": "scoring_and_fallback_only",
    }


@pytest.mark.parametrize("league", [False, True])
def test_operator_cli_forwards_the_explicit_selection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, league: bool
) -> None:
    arguments = ["command", "--snapshot-root", str(tmp_path), "--archive-root", str(tmp_path)]
    for season in SELECTED:
        arguments.extend(("--training-season", season))
    if league:
        arguments.extend(("--league", "352490", "--snapshot-id", "named-capture"))
        monkeypatch.setattr(
            build_league_site, "resolve_live_snapshot_id", lambda *_args: "named-capture"
        )

        def prepared(request: Any) -> Any:
            assert request.training_seasons == SELECTED
            raise ReachedBoundary

        monkeypatch.setattr(build_league_site, "prepare_league_publication", prepared)
        main = build_league_site.main
    else:

        def build(*_args: Any, **kwargs: Any) -> Any:
            assert kwargs["training_seasons"] == SELECTED
            raise ReachedBoundary

        monkeypatch.setattr(build_projection_handoff, "build", build)
        main = build_projection_handoff.main
    monkeypatch.setattr(sys, "argv", arguments)
    with pytest.raises(ReachedBoundary):
        main()
