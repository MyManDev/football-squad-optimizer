"""The advice GET routes: reads only, typed refusals, and a clean 503 when absent."""

import json
from pathlib import Path

from fastapi.testclient import TestClient

from squadopt.api.app import create_app
from squadopt.platform.advice_cache import FileAdviceCache, advice_cache_key
from squadopt.platform.advice_read import (
    AdviceReadStore,
    AdviceRequestContext,
    FileLeagueDirectory,
)

LEAGUE_ID = 352490
CONTEXT = AdviceRequestContext(
    advice_contract_version="advice_v1",
    capture_snapshot_id="fpl-live-20260826T083133Z-d45f1bea8b68",
    season="2026-27",
    gameweek=3,
    projection_handoff_fingerprint="f" * 64,
    repository_commit="abc1234",
    configuration_fingerprint="d" * 64,
)


class _Context:
    def current(self) -> AdviceRequestContext:
        return CONTEXT


def _publish_members(root: Path) -> None:
    payload = {
        "league_id": LEAGUE_ID,
        "league_name": "Test League",
        "season": "2026-27",
        "gameweek": 3,
        "members": [
            {"member_kind": "human", "entry_id": 313686},
            {"member_kind": "human", "entry_id": 2199732},
        ],
    }
    document = {"contract_version": "provisional_league_ui_v1", "payload": payload}
    path = root / "league" / "members.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document), encoding="utf-8", newline="\n")


def _client(tmp_path: Path) -> tuple[TestClient, FileAdviceCache]:
    _publish_members(tmp_path / "site")
    cache = FileAdviceCache(tmp_path / "cache")
    store = AdviceReadStore(
        FileLeagueDirectory(tmp_path / "site"), cache, _Context(), {"saf-puan": False}
    )
    application = create_app(data_root=tmp_path / "site", advice_store=store)
    return TestClient(application, raise_server_exceptions=False), cache


def test_league_state_and_the_three_answers(tmp_path: Path) -> None:
    client, cache = _client(tmp_path)

    connected = client.get(f"/api/v1/leagues/{LEAGUE_ID}")
    assert connected.status_code == 200
    assert connected.json()["connected"] is True

    unknown = client.get("/api/v1/leagues/999999")
    assert unknown.status_code == 200
    assert unknown.json() == {"league_id": 999999, "connected": False}


def test_advice_is_a_pure_cache_read(tmp_path: Path) -> None:
    client, cache = _client(tmp_path)
    url = f"/api/v1/leagues/{LEAGUE_ID}/entries/313686/advice?strategy=saf-puan&window=1"

    miss = client.get(url)
    assert miss.status_code == 404
    assert miss.json()["error"]["code"] == "NOT_COMPUTED"

    key = advice_cache_key(
        advice_contract_version=CONTEXT.advice_contract_version,
        capture_snapshot_id=CONTEXT.capture_snapshot_id,
        season=CONTEXT.season,
        gameweek=CONTEXT.gameweek,
        league_id=LEAGUE_ID,
        entry_id=313686,
        strategy="saf-puan",
        window=1,
        projection_handoff_fingerprint=CONTEXT.projection_handoff_fingerprint,
        repository_commit=CONTEXT.repository_commit,
        configuration_fingerprint=CONTEXT.configuration_fingerprint,
    )
    cache.put(key, b'{"payload": {"moves": []}}')

    hit = client.get(url)
    assert hit.status_code == 200
    assert hit.content == b'{"payload": {"moves": []}}'  # the exact cached bytes


def test_refusals_map_onto_status_codes(tmp_path: Path) -> None:
    client, _cache = _client(tmp_path)
    base = f"/api/v1/leagues/{LEAGUE_ID}/entries"

    unknown_entry = client.get(f"{base}/42/advice?strategy=saf-puan&window=1")
    assert unknown_entry.status_code == 404
    assert unknown_entry.json()["error"]["code"] == "UNKNOWN_ENTRY"

    unknown_strategy = client.get(f"{base}/313686/advice?strategy=bilinmez&window=1")
    assert unknown_strategy.status_code == 404
    assert unknown_strategy.json()["error"]["code"] == "UNKNOWN_STRATEGY"

    bad_window = client.get(f"{base}/313686/advice?strategy=saf-puan&window=2")
    assert bad_window.status_code == 422

    disconnected = client.get("/api/v1/leagues/1/entries/313686/advice?strategy=saf-puan&window=1")
    assert disconnected.status_code == 404
    assert disconnected.json()["error"]["code"] == "LEAGUE_NOT_CONNECTED"


def test_without_a_store_the_routes_say_disabled_and_the_old_app_is_untouched(
    tmp_path: Path,
) -> None:
    application = create_app(data_root=tmp_path / "site")
    client = TestClient(application, raise_server_exceptions=False)

    league = client.get(f"/api/v1/leagues/{LEAGUE_ID}")
    assert league.status_code == 503
    assert league.json()["error"]["code"] == "ADVICE_BACKEND_DISABLED"

    health = client.get("/health")
    assert health.status_code == 200  # the read-only app is exactly what it was
