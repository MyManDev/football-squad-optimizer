"""The read side: league state from the published tree, advice from the cache only."""

import json
from pathlib import Path

import pytest

from squadopt.platform.advice_cache import FileAdviceCache, advice_cache_key
from squadopt.platform.advice_read import (
    AdviceBackendNotReadyError,
    AdviceNotComputedError,
    AdviceReadStore,
    AdviceRequestContext,
    FileLeagueDirectory,
    LeagueNotConnectedError,
    UnknownEntryError,
    UnknownStrategyError,
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
    def __init__(self, context: AdviceRequestContext | None) -> None:
        self._context = context

    def current(self) -> AdviceRequestContext | None:
        return self._context


def _publish_members(root: Path, league_id: int = LEAGUE_ID) -> None:
    payload = {
        "league_id": league_id,
        "league_name": "Test League",
        "season": "2026-27",
        "gameweek": 3,
        "members": [
            {"member_kind": "human", "entry_id": 313686},
            {"member_kind": "human", "entry_id": 2199732},
            {"member_kind": "system", "entry_id": 0},
        ],
    }
    document = {"contract_version": "provisional_league_ui_v1", "payload": payload}
    path = root / "league" / "members.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document), encoding="utf-8", newline="\n")


def _store(tmp_path: Path, *, context: AdviceRequestContext | None = CONTEXT) -> AdviceReadStore:
    _publish_members(tmp_path / "site")
    return AdviceReadStore(
        FileLeagueDirectory(tmp_path / "site"),
        FileAdviceCache(tmp_path / "cache"),
        _Context(context),
        {"saf-puan": False, "fark-yarat": True},
    )


def test_league_state_reads_the_published_tree_and_counts_humans(tmp_path: Path) -> None:
    store = _store(tmp_path)
    connected = store.league_state(LEAGUE_ID)
    assert connected["connected"] is True
    assert connected["member_count"] == 2  # the system row is not a member
    assert store.league_state(999999) == {"league_id": 999999, "connected": False}


def test_a_hit_returns_the_exact_cached_bytes(tmp_path: Path) -> None:
    store = _store(tmp_path)
    cache = FileAdviceCache(tmp_path / "cache")
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

    result = store.read_advice(league_id=LEAGUE_ID, entry_id=313686, strategy="saf-puan", window=1)

    assert result == b'{"payload": {"moves": []}}'
    # An ignored rival on a rival-less strategy hits the same entry: forced null.
    with_rival = store.read_advice(
        league_id=LEAGUE_ID, entry_id=313686, strategy="saf-puan", window=1, rival_entry_id=2199732
    )
    assert with_rival == result


def test_every_refusal_is_typed(tmp_path: Path) -> None:
    store = _store(tmp_path)
    with pytest.raises(UnknownStrategyError):
        store.read_advice(league_id=LEAGUE_ID, entry_id=313686, strategy="yok", window=1)
    with pytest.raises(LeagueNotConnectedError):
        store.read_advice(league_id=1, entry_id=313686, strategy="saf-puan", window=1)
    with pytest.raises(UnknownEntryError):
        store.read_advice(league_id=LEAGUE_ID, entry_id=42, strategy="saf-puan", window=1)
    with pytest.raises(UnknownEntryError):
        store.read_advice(
            league_id=LEAGUE_ID,
            entry_id=313686,
            strategy="fark-yarat",
            window=1,
            rival_entry_id=42,
        )
    with pytest.raises(AdviceNotComputedError):
        store.read_advice(league_id=LEAGUE_ID, entry_id=313686, strategy="saf-puan", window=1)


def test_no_context_is_not_ready_not_a_404(tmp_path: Path) -> None:
    store = _store(tmp_path, context=None)
    with pytest.raises(AdviceBackendNotReadyError):
        store.read_advice(league_id=LEAGUE_ID, entry_id=313686, strategy="saf-puan", window=1)
    # League state needs no capture: the published tree alone answers it.
    assert store.league_state(LEAGUE_ID)["connected"] is True
