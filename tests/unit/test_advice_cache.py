"""The advice cache: the key is the whole identity, and writes never overwrite."""

import os
from pathlib import Path

import pytest

from squadopt.platform import _damaged_entry
from squadopt.platform.advice_cache import (
    AdviceCacheError,
    FileAdviceCache,
    advice_cache_key,
)
from squadopt.platform.advice_observability import AdviceLog


def _key(**overrides: object) -> str:
    fields: dict[str, object] = {
        "advice_contract_version": "advice_v1",
        "capture_snapshot_id": "fpl-live-20260826T083133Z-d45f1bea8b68",
        "season": "2026-27",
        "gameweek": 3,
        "league_id": 352490,
        "entry_id": 313686,
        "strategy": "saf-puan",
        "window": 1,
        "projection_handoff_fingerprint": "f" * 64,
        "repository_commit": "abc1234",
        "configuration_fingerprint": "d" * 64,
    }
    fields.update(overrides)
    return advice_cache_key(**fields)  # type: ignore[arg-type]


# --- the key ------------------------------------------------------------------------


def test_the_key_is_deterministic_and_every_field_is_load_bearing() -> None:
    assert _key() == _key()
    baseline = _key()
    for change in (
        {"capture_snapshot_id": "fpl-live-other"},
        {"gameweek": 4},
        {"entry_id": 2199732},
        {"strategy": "fark-yarat"},
        {"window": 3},
        {"projection_handoff_fingerprint": "e" * 64},
        {"repository_commit": "def5678"},
        {"configuration_fingerprint": "c" * 64},
    ):
        assert _key(**change) != baseline, change


def test_an_ignored_rival_is_forced_null_before_hashing() -> None:
    """Two requests differing only in a rival the strategy ignores must hit one entry."""

    without = _key()
    with_ignored_rival = _key(rival_entry_id=2199732)
    assert with_ignored_rival == without  # strategy_uses_rival defaults False

    used = _key(rival_entry_id=2199732, strategy_uses_rival=True)
    assert used != without
    default_rival = _key(strategy_uses_rival=True)
    assert default_rival != used  # None means the server's default choice, distinctly


def test_key_inputs_are_validated() -> None:
    with pytest.raises(AdviceCacheError, match="season"):
        _key(season=" ")
    with pytest.raises(AdviceCacheError, match="window"):
        _key(window=0)
    with pytest.raises(AdviceCacheError, match="rival_entry_id"):
        _key(rival_entry_id=-3)


# --- the store ----------------------------------------------------------------------


def test_roundtrip_and_a_miss_is_none(tmp_path: Path) -> None:
    cache = FileAdviceCache(tmp_path)
    key = _key()
    assert cache.get(key) is None
    cache.put(key, b'{"answer": 1}')
    assert cache.get(key) == b'{"answer": 1}'


def test_the_retry_is_a_no_op_and_the_overwrite_is_refused(tmp_path: Path) -> None:
    cache = FileAdviceCache(tmp_path)
    key = _key()
    cache.put(key, b'{"answer": 1}')
    cache.put(key, b'{"answer": 1}')  # the disposable worker's retry: identical, silent
    with pytest.raises(AdviceCacheError, match="determinism defect"):
        cache.put(key, b'{"answer": 2}')
    assert cache.get(key) == b'{"answer": 1}'  # the first answer stands


def test_malformed_keys_and_payloads_are_refused(tmp_path: Path) -> None:
    cache = FileAdviceCache(tmp_path)
    with pytest.raises(AdviceCacheError, match="SHA-256"):
        cache.get("../escape")
    with pytest.raises(AdviceCacheError, match="SHA-256"):
        cache.put("short", b"x")
    with pytest.raises(AdviceCacheError, match="payload"):
        cache.put(_key(), b"")


def test_no_torn_entry_is_left_behind(tmp_path: Path) -> None:
    """The store directory holds finished entries only — no .tmp leftovers."""

    cache = FileAdviceCache(tmp_path)
    key = _key()
    cache.put(key, b'{"answer": 1}')
    leftovers = [p for p in tmp_path.rglob("*") if p.is_file() and p.suffix == ".tmp"]
    assert leftovers == []
    stored = [p for p in tmp_path.rglob("*.json")]
    assert len(stored) == 1 and stored[0].name == f"{key}.json"


def test_two_synchronized_writers_cannot_both_win(tmp_path: Path) -> None:
    """The reviewed race, forced: both writers observe the miss together; creation is
    atomic, so exactly one set of bytes stands and the loser conflicts loudly."""

    import threading

    from squadopt.platform.advice_cache import AdviceCacheConflictError

    cache = FileAdviceCache(tmp_path)
    key = _key()
    barrier = threading.Barrier(2)
    outcomes: list[str] = []

    def write(payload: bytes) -> None:
        class _RacingCache(FileAdviceCache):
            def get(self, inner_key: str) -> bytes | None:  # observe the miss together
                value = super().get(inner_key)
                if value is None:
                    barrier.wait(timeout=5)
                return value

        try:
            _RacingCache(tmp_path).put(key, payload)
            outcomes.append("ok")
        except AdviceCacheConflictError:
            outcomes.append("conflict")

    first = threading.Thread(target=write, args=(b'{"answer": 1}',))
    second = threading.Thread(target=write, args=(b'{"answer": 2}',))
    first.start(), second.start()
    first.join(timeout=10), second.join(timeout=10)

    assert sorted(outcomes) == ["conflict", "ok"]
    assert cache.get(key) in (b'{"answer": 1}', b'{"answer": 2}')  # one winner, whole


def test_two_synchronized_identical_writers_both_succeed(tmp_path: Path) -> None:
    import threading

    cache = FileAdviceCache(tmp_path)
    key = _key()
    barrier = threading.Barrier(2)
    outcomes: list[str] = []

    def write() -> None:
        class _RacingCache(FileAdviceCache):
            def get(self, inner_key: str) -> bytes | None:
                value = super().get(inner_key)
                if value is None:
                    barrier.wait(timeout=5)
                return value

        _RacingCache(tmp_path).put(key, b'{"answer": 1}')
        outcomes.append("ok")

    threads = [threading.Thread(target=write) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    assert outcomes == ["ok", "ok"]
    assert cache.get(key) == b'{"answer": 1}'


# --- durability and damage ----------------------------------------------------------


def _recorded_events(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict[str, object]]]:
    events: list[tuple[str, dict[str, object]]] = []

    def record(self: AdviceLog, name: str, **fields: object) -> None:
        events.append((name, fields))

    monkeypatch.setattr(AdviceLog, "event", record)
    return events


def test_put_fsyncs_the_whole_payload_before_linking_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = b'{"answer": 1}'
    calls: list[tuple[str, int]] = []
    fsync, link = os.fsync, os.link

    def spy_fsync(descriptor: int) -> None:
        calls.append(("fsync", os.fstat(descriptor).st_size))
        fsync(descriptor)

    def spy_link(source: str, destination: str) -> None:
        calls.append(("link", Path(source).stat().st_size))
        link(source, destination)

    monkeypatch.setattr(os, "fsync", spy_fsync)
    monkeypatch.setattr(os, "link", spy_link)
    cache = FileAdviceCache(tmp_path)
    cache.put(_key(), payload)
    assert calls == [("fsync", len(payload)), ("link", len(payload))]
    assert cache.get(_key()) == payload


@pytest.mark.parametrize("torn", [b"", b"\x00" * 64, b'{"answer": ', b"\x80{}"])
def test_an_entry_that_is_not_json_is_moved_aside_and_computed_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, torn: bytes
) -> None:
    events = _recorded_events(monkeypatch)
    cache = FileAdviceCache(tmp_path)
    key = _key()
    path = tmp_path / key[:2] / f"{key}.json"
    path.parent.mkdir(parents=True)
    path.write_bytes(torn)

    assert cache.get(key) is None
    [aside] = [p for p in path.parent.iterdir() if p != path]
    assert aside.name.startswith(f"{key}.json.damaged-")
    assert aside.read_bytes() == torn
    assert not path.exists()
    assert [name for name, _fields in events] == ["advice_damaged_entry_quarantined"]
    assert events[0][1]["source"] == path.name
    assert events[0][1]["moved_to"] == aside.name
    assert events[0][1]["size"] == len(torn)

    cache.put(key, b'{"answer": 1}')
    assert cache.get(key) == b'{"answer": 1}'


def test_a_write_over_a_torn_entry_moves_it_aside_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events = _recorded_events(monkeypatch)
    cache = FileAdviceCache(tmp_path)
    key = _key()
    path = tmp_path / key[:2] / f"{key}.json"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"")

    cache.put(key, b'{"answer": 1}')  # the worker publishing the recomputed answer
    assert cache.get(key) == b'{"answer": 1}'
    assert len([p for p in path.parent.iterdir() if ".damaged-" in p.name]) == 1
    assert len(events) == 1


def test_a_payload_that_is_not_json_is_never_written(tmp_path: Path) -> None:
    cache = FileAdviceCache(tmp_path)
    with pytest.raises(AdviceCacheError, match="JSON document"):
        cache.put(_key(), b"answer")  # it would read back as damage
    assert not tmp_path.exists() or list(tmp_path.rglob("*")) == []


@pytest.mark.parametrize("parsed", [b"null", b'{"private":"corrupt"}'])
def test_an_entry_that_parses_is_returned_as_it_is(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, parsed: bytes
) -> None:
    events = _recorded_events(monkeypatch)
    cache = FileAdviceCache(tmp_path)
    key = _key()
    cache.put(key, parsed)
    assert cache.get(key) == parsed  # validation above the store still refuses it
    assert [p.name for p in (tmp_path / key[:2]).iterdir()] == [f"{key}.json"]
    assert events == []


def test_a_whole_entry_published_during_the_move_is_put_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events = _recorded_events(monkeypatch)
    cache = FileAdviceCache(tmp_path)
    key = _key()
    cache.put(key, b'{"answer": 1}')
    path = tmp_path / key[:2] / f"{key}.json"

    # A reader read torn bytes; by the time it moves the file, a writer has replaced the
    # damage with a whole entry. The move is undone and nothing is reported.
    _damaged_entry.quarantine(path, b"", component="cache")
    assert cache.get(key) == b'{"answer": 1}'
    assert [p.name for p in path.parent.iterdir()] == [path.name]
    assert events == []


def test_a_reader_that_finds_the_damage_already_moved_does_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events = _recorded_events(monkeypatch)
    path = tmp_path / "ab" / f"{'ab' * 32}.json"
    path.parent.mkdir(parents=True)
    _damaged_entry.quarantine(path, b"", component="cache")
    assert list(path.parent.iterdir()) == []
    assert events == []
