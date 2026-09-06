"""The composition root: one store, a real capture context, and honest readiness.

These are the boundary behaviours, not a mirror of the wiring. What they pin is what a
misassembly would break: two processes reaching different stores, a request that names a
path, a strategy the reader accepts and the writer refuses, and a deployment that calls
itself ready with nothing to answer from.
"""

import json
from pathlib import Path
from typing import Any

import pytest
import tests.unit.test_live_transfers as world_module
from fastapi.testclient import TestClient

from squadopt.api.runtime import app_for_backend
from squadopt.application.advice import COMPUTED_MODE, COMPUTED_WINDOW
from squadopt.application.strategies import STRATEGY_CATALOG
from squadopt.data.snapshots import write_snapshot
from squadopt.live import InSeasonProjection, write_projection_handoff
from squadopt.live import recommendation as live_recommendation
from squadopt.live.tick import handoff_path_for
from squadopt.platform import backend_runtime
from squadopt.platform.backend_runtime import (
    BackendConfig,
    BackendConfigError,
    build_backend,
    computable_strategies,
    configuration_fingerprint,
)

SEASON = world_module.SEASON
BOOTSTRAP_PAYLOAD = world_module.BOOTSTRAP_PAYLOAD
FIXTURES_PAYLOAD = world_module.FIXTURES_PAYLOAD
LEAGUE_ID = 352490
ENTRY_ID = 101


def _capture(snapshot_root: Path) -> str:
    """One capture whose next open deadline is gameweek 2."""

    gw1_finished = [dict(world_module.EVENTS[0], finished=True), *world_module.EVENTS[1:]]
    written = write_snapshot(
        snapshot_root,
        source="fpl-live",
        captured_at_utc=world_module.GW2_CAPTURED_AT,
        payloads={
            BOOTSTRAP_PAYLOAD: world_module._bootstrap(
                events=gw1_finished, elements=world_module._elements(event_points=2)
            ),
            FIXTURES_PAYLOAD: b"[]",
        },
    )
    return written.snapshot_id


def _handoff(handoff_root: Path, snapshot_id: str, *, gameweek: int = 2) -> Path:
    expected = {code: 2.0 + (code % 3) * 0.5 for code in range(1001, 1025)}
    projection = InSeasonProjection(
        season=SEASON,
        gameweek=gameweek,
        source_snapshot_id=snapshot_id,
        model_name=live_recommendation.CONTROL_MODEL_NAME,
        model_version=world_module.IN_SEASON_VERSION,
        feature_contract_version="synthetic-in-season-features-v0",
        expected_points=expected,
        diagnostics={"producer": "test"},
    )
    return write_projection_handoff(handoff_path_for(handoff_root, SEASON, gameweek), projection)


def _publish_members(site_root: Path) -> None:
    document = {
        "contract_version": "provisional_league_ui_v1",
        "payload": {
            "league_id": LEAGUE_ID,
            "league_name": "Test League",
            "season": SEASON,
            "gameweek": 2,
            "members": [{"member_kind": "human", "entry_id": ENTRY_ID}],
        },
    }
    path = site_root / "league" / "members.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document), encoding="utf-8", newline="\n")


@pytest.fixture(name="deployment")
def _deployment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    monkeypatch.setenv("SQUADOPT_REPOSITORY_COMMIT", "a" * 40)
    snapshot_root = tmp_path / "snapshots"
    handoff_root = tmp_path / "handoffs"
    site_root = tmp_path / "site"
    snapshot_id = _capture(snapshot_root)
    _handoff(handoff_root, snapshot_id)
    _publish_members(site_root)
    config = BackendConfig(
        store_root=tmp_path / "store",
        site_data_root=site_root,
        snapshot_root=snapshot_root,
        handoff_root=handoff_root,
        allowed_origins=("https://squadopt.pages.dev",),
    )
    return {
        "config": config,
        "snapshot_id": snapshot_id,
        "snapshot_root": snapshot_root,
        "handoff_root": handoff_root,
        "site_root": site_root,
    }


def test_the_queue_and_the_cache_come_from_one_configured_store(tmp_path: Path) -> None:
    """The api writes the queue the worker reads; two roots would be two backends."""

    config = BackendConfig(
        store_root=tmp_path / "mount",
        site_data_root=tmp_path / "site",
        snapshot_root=tmp_path / "snapshots",
        handoff_root=tmp_path / "handoffs",
    )
    assert config.queue_root.parent == config.cache_root.parent == tmp_path / "mount"
    assert config.queue_root != config.cache_root


def test_missing_configuration_names_every_variable_at_once() -> None:
    with pytest.raises(BackendConfigError) as error:
        BackendConfig.from_environment({"SQUADOPT_BACKEND_STORE_ROOT": "/mnt/store"})
    message = str(error.value)
    for variable in (
        "SQUADOPT_BACKEND_SITE_DATA_ROOT",
        "SQUADOPT_BACKEND_SNAPSHOT_ROOT",
        "SQUADOPT_BACKEND_HANDOFF_ROOT",
    ):
        assert variable in message
    assert "SQUADOPT_BACKEND_STORE_ROOT" not in message


def test_a_wildcard_origin_is_refused_by_configuration(tmp_path: Path) -> None:
    """ADR 0006: the allowlist is the Pages domains. A wildcard is not an allowlist."""

    environment = {
        "SQUADOPT_BACKEND_STORE_ROOT": str(tmp_path / "store"),
        "SQUADOPT_BACKEND_SITE_DATA_ROOT": str(tmp_path / "site"),
        "SQUADOPT_BACKEND_SNAPSHOT_ROOT": str(tmp_path / "snapshots"),
        "SQUADOPT_BACKEND_HANDOFF_ROOT": str(tmp_path / "handoffs"),
        "SQUADOPT_BACKEND_ALLOWED_ORIGINS": "https://squadopt.pages.dev, *",
    }
    with pytest.raises(BackendConfigError, match="wildcard"):
        BackendConfig.from_environment(environment)


def test_the_computable_strategies_are_exactly_the_ones_advice_will_answer() -> None:
    """The reader must accept a request if and only if the writer can compute it."""

    strategies = computable_strategies()
    assert strategies[COMPUTED_MODE] is False
    for slug, uses_rival in strategies.items():
        if slug == COMPUTED_MODE:
            continue
        constraints = STRATEGY_CATALOG[slug].constraints
        assert uses_rival is True
        assert constraints.overlap_floor is not None or constraints.overlap_ceiling is not None
    unwired = {
        slug
        for slug, strategy in STRATEGY_CATALOG.items()
        if strategy.constraints.overlap_floor is None
        and strategy.constraints.overlap_ceiling is None
    }
    # ``saf-puan`` is in the catalogue with no band and is still computed: advice
    # answers it on its own branch, before the catalogue is consulted at all.
    assert (unwired - {COMPUTED_MODE}).isdisjoint(strategies)


def test_the_configuration_fingerprint_tracks_computation_not_placement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """It must move when the answer would change, and stay when only the mount moves.

    Both halves matter. A fingerprint that ignored the computed window would let a cache
    entry outlive the question it answered; one that folded in the store path would
    orphan a whole correct cache the day the mount is renamed.
    """

    placed = configuration_fingerprint()
    assert len(placed) == 64
    assert placed == configuration_fingerprint()

    monkeypatch.setattr(backend_runtime, "COMPUTED_WINDOW", 3)
    assert configuration_fingerprint() != placed


def test_a_deployment_without_a_capture_is_unready_rather_than_broken(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SQUADOPT_REPOSITORY_COMMIT", "b" * 40)
    backend = build_backend(
        BackendConfig(
            store_root=tmp_path / "store",
            site_data_root=tmp_path / "site",
            snapshot_root=tmp_path / "snapshots",
            handoff_root=tmp_path / "handoffs",
        )
    )
    assert backend.contexts.current() is None
    ready, checks = backend.readiness()
    assert ready is False
    assert checks["capture_context"] is False
    assert checks["league_tree"] is False


def test_a_capture_without_its_handoff_yields_no_context(deployment: dict[str, Any]) -> None:
    """A projection nobody fingerprinted may not enter a cache key, so: not ready."""

    handoff = handoff_path_for(deployment["handoff_root"], SEASON, 2)
    handoff.unlink()
    backend = build_backend(deployment["config"])
    assert backend.contexts.current() is None
    ready, checks = backend.readiness()
    assert ready is False
    assert checks["capture_context"] is False
    assert checks["league_tree"] is True


def test_the_context_names_the_capture_and_its_handoff(deployment: dict[str, Any]) -> None:
    backend = build_backend(deployment["config"])
    context = backend.contexts.current()
    assert context is not None
    assert context.capture_snapshot_id == deployment["snapshot_id"]
    assert context.season == SEASON
    assert context.gameweek == 2
    assert context.repository_commit == "a" * 40
    assert len(context.projection_handoff_fingerprint) == 64
    ready, checks = backend.readiness()
    assert ready is True
    assert checks == {"capture_context": True, "league_tree": True, "cache_store": True}


def test_a_new_capture_replaces_the_context_without_a_restart(
    deployment: dict[str, Any],
) -> None:
    """Ops publishes a capture and its handoff; the backend answers for the new week."""

    backend = build_backend(deployment["config"])
    first = backend.contexts.current()
    assert first is not None

    later = write_snapshot(
        deployment["snapshot_root"],
        source="fpl-live",
        captured_at_utc="2026-09-12T10:00:00Z",
        payloads={
            BOOTSTRAP_PAYLOAD: world_module._bootstrap(
                events=[
                    dict(world_module.EVENTS[0], finished=True),
                    dict(world_module.EVENTS[1], finished=True),
                    *world_module.EVENTS[2:],
                ],
                elements=world_module._elements(event_points=3),
            ),
            FIXTURES_PAYLOAD: b"[]",
        },
    )
    _handoff(deployment["handoff_root"], later.snapshot_id, gameweek=3)
    second = backend.contexts.current()
    assert second is not None
    assert second.capture_snapshot_id == later.snapshot_id
    assert second.gameweek == 3
    assert second != first


def test_the_wired_app_accepts_a_real_request_instead_of_answering_503(
    deployment: dict[str, Any],
) -> None:
    """The whole point: an assembled backend queues work rather than refusing it."""

    backend = build_backend(deployment["config"])
    client = TestClient(app_for_backend(backend))

    ready = client.get("/ready")
    assert ready.status_code == 200

    response = client.post(
        f"/api/v1/leagues/{LEAGUE_ID}/entries/{ENTRY_ID}/advice",
        json={"strategy": COMPUTED_MODE, "window": COMPUTED_WINDOW},
    )
    assert response.status_code in {200, 202}, response.text
    assert backend.queue_depth() == 1

    job = backend.queue.jobs()[0]
    assert job.status == "queued"
    context = backend.contexts.current()
    assert context is not None
    # The job's address is the answer's address under *this* capture: the worker cannot
    # be handed a key that belongs to a capture the reader never validated.
    assert (
        job.cache_key
        == backend.reader.resolve_key(
            league_id=LEAGUE_ID,
            entry_id=ENTRY_ID,
            strategy=COMPUTED_MODE,
            window=COMPUTED_WINDOW,
        )[0]
    )
