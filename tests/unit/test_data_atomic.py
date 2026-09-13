"""The create-once atomic writer now lives in the data layer.

It moved out of the laboratory so the product can publish a manifest without importing
``squadopt.experiments``. The laboratory's ``write_document_once`` is a wrapper over it, and
these tests pin the contract the wrapper and the product both rely on: identical bytes
replay, different bytes are refused, nothing on disk is ever overwritten, and a destination
past Windows' MAX_PATH is still reachable.

The retried rename lives here too, and the tests at the bottom pin what every writer that
publishes by renaming a sibling now shares: a refusal while something holds a handle is
waited out, a refusal that outlasts the budget says how long it waited, and a destination
that already exists is refused at once instead of slowly.
"""

import errno
import json
from pathlib import Path
from typing import Any

import pytest

from squadopt.data import atomic
from squadopt.data.errors import (
    AtomicWriteError,
    ConflictingBytesError,
    DataError,
    RenameRefusedError,
)
from squadopt.experiments import shadow_report


def test_the_first_write_creates_and_the_same_bytes_replay(tmp_path: Path) -> None:
    target = tmp_path / "record.bin"

    assert atomic.write_bytes_once(b"one", target) == "written"
    assert atomic.write_bytes_once(b"one", target) == "replay"
    assert target.read_bytes() == b"one"
    assert sorted(path.name for path in tmp_path.iterdir()) == ["record.bin"]


def test_different_bytes_are_refused_and_the_occupant_is_untouched(tmp_path: Path) -> None:
    target = tmp_path / "record.bin"
    atomic.write_bytes_once(b"one", target)

    with pytest.raises(ConflictingBytesError, match="never overwritten"):
        atomic.write_bytes_once(b"two", target)

    assert target.read_bytes() == b"one"
    assert sorted(path.name for path in tmp_path.iterdir()) == ["record.bin"]
    assert issubclass(ConflictingBytesError, AtomicWriteError)
    assert issubclass(AtomicWriteError, DataError)


def test_parse_decides_what_counts_as_the_same_record(tmp_path: Path) -> None:
    target = tmp_path / "record.json"
    atomic.write_bytes_once(b'{"a": 1, "stamp": "x"}', target)

    def without_stamp(raw: bytes) -> object:
        return {key: value for key, value in json.loads(raw).items() if key != "stamp"}

    assert atomic.write_bytes_once(b'{"a": 1, "stamp": "y"}', target, parse=without_stamp) == (
        "replay"
    )
    with pytest.raises(ConflictingBytesError):
        atomic.write_bytes_once(b'{"a": 2, "stamp": "y"}', target, parse=without_stamp)
    assert target.read_bytes() == b'{"a": 1, "stamp": "x"}'


def test_an_unreadable_occupant_is_an_atomic_write_error(tmp_path: Path) -> None:
    directory = tmp_path / "occupied.json"
    directory.mkdir()

    with pytest.raises(AtomicWriteError, match="cannot be read"):
        atomic.write_bytes_once(b"one", directory)
    assert sorted(path.name for path in tmp_path.iterdir()) == ["occupied.json"]


def test_a_document_is_written_in_the_bytes_the_laboratory_writer_produced(
    tmp_path: Path,
) -> None:
    document = {"b": [1, 2.5, None], "a": {"nested": "x"}, "flag": True}

    assert atomic.write_document_once(document, tmp_path / "new.json") == "written"
    assert shadow_report.write_document_once(document, tmp_path / "old.json") == "written"

    assert (tmp_path / "new.json").read_bytes() == (tmp_path / "old.json").read_bytes()
    assert (tmp_path / "new.json").read_bytes() == atomic.document_bytes(document)
    assert (tmp_path / "new.json").read_bytes().endswith(b"}\n")


def test_a_document_writer_replays_only_under_its_declared_identity(tmp_path: Path) -> None:
    target = tmp_path / "manifest.json"
    first = {"rows": 3, "generated_at_utc": "2026-09-10T10:00:00Z"}
    later = {"rows": 3, "generated_at_utc": "2026-09-10T11:00:00Z"}

    def identity(document: object) -> object:
        assert isinstance(document, dict)
        return {key: value for key, value in document.items() if key != "generated_at_utc"}

    assert atomic.write_document_once(first, target) == "written"
    with pytest.raises(ConflictingBytesError):
        atomic.write_document_once(later, target)
    assert atomic.write_document_once(later, target, replay_identity=identity) == "replay"
    with pytest.raises(ConflictingBytesError):
        atomic.write_document_once({**later, "rows": 4}, target, replay_identity=identity)
    assert json.loads(target.read_text(encoding="utf-8")) == first


def test_a_document_writer_refuses_nan_before_touching_disk(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        atomic.write_document_once({"x": float("nan")}, tmp_path / "nan.json")
    assert list(tmp_path.iterdir()) == []


def test_an_occupant_that_is_not_json_is_an_atomic_write_error(tmp_path: Path) -> None:
    target = tmp_path / "record.json"
    target.write_bytes(b"not json")

    with pytest.raises(AtomicWriteError, match="not readable JSON"):
        atomic.write_document_once({"a": 1}, target)
    assert target.read_bytes() == b"not json"


def test_a_destination_past_windows_max_path_is_still_created_once(tmp_path: Path) -> None:
    """The temporary beside the target is 27 characters longer than the target.

    Windows caps path-based calls at 260 characters (measured; see ``_long_paths``). Before
    the writer moved here it created its temporary by plain ``open``, which failed with
    FileNotFoundError once the path passed the cap. Every call now goes through
    ``addressable``, so a long target is created once, replayed, and defended.
    """

    name = "manifest_" + "x" * 60 + ".json"
    root = tmp_path.absolute()
    while len(str(root / name)) <= 274:
        root = root / "deeper"
    target = root / name
    assert len(str(target)) > 260, "target must exceed MAX_PATH for this to be a regression test"

    assert atomic.write_document_once({"a": 1}, target) == "written"
    assert atomic.write_document_once({"a": 1}, target) == "replay"
    with pytest.raises(ConflictingBytesError):
        atomic.write_document_once({"a": 2}, target)
    assert Path(atomic.addressable(target)).read_bytes() == atomic.document_bytes({"a": 1})
    assert [path.name for path in Path(atomic.addressable(root)).iterdir()] == [name]


def _refuse_rename(monkeypatch: pytest.MonkeyPatch, *, times: int) -> list[float]:
    """Refuse the next ``times`` renames the way Windows does; return the pauses asked for.

    The handle race cannot be provoked on demand, so the ``PermissionError`` it raises
    (WinError 5, "Access is denied") is injected instead. The pauses are recorded rather
    than slept, so proving the retry costs the suite no wall-clock time.
    """

    real_replace = atomic.os.replace
    refused = 0
    pauses: list[float] = []

    def flaky(source: Any, destination: Any) -> None:
        nonlocal refused
        if refused < times:
            refused += 1
            raise PermissionError(errno.EACCES, "Access is denied")
        real_replace(source, destination)

    monkeypatch.setattr(atomic.os, "replace", flaky)
    monkeypatch.setattr(atomic.time, "sleep", pauses.append)
    return pauses


def test_a_rename_refused_while_a_handle_is_held_is_waited_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "staged.json"
    source.write_bytes(b"published")
    destination = tmp_path / "record.json"
    pauses = _refuse_rename(monkeypatch, times=atomic.RENAME_RETRY_ATTEMPTS - 1)

    atomic.replace_retrying(source, destination)

    assert destination.read_bytes() == b"published"
    assert not source.exists()
    first = atomic.RENAME_RETRY_INITIAL_SECONDS
    assert pauses == [first, first * 2, first * 4, first * 8]


def test_a_rename_refused_for_the_whole_budget_says_how_long_it_waited(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The refusal is reported, and what it was asked to move is left where it is."""

    source = tmp_path / "staged.json"
    source.write_bytes(b"published")
    destination = tmp_path / "record.json"
    attempts = atomic.RENAME_RETRY_ATTEMPTS
    pauses = _refuse_rename(monkeypatch, times=attempts)

    with pytest.raises(RenameRefusedError) as refusal:
        atomic.replace_retrying(source, destination)

    assert f"refused on all {attempts} attempts" in str(refusal.value)
    assert f"over {sum(pauses):.2f} s" in str(refusal.value)
    assert len(pauses) == attempts - 1
    assert isinstance(refusal.value, AtomicWriteError)
    assert source.read_bytes() == b"published"
    assert not destination.exists()


def test_a_destination_that_already_exists_is_refused_at_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Windows reports an occupied destination with the same error as a held handle.

    Retrying that would answer a real refusal slowly instead of at once, and it would tell
    a caller that a record already at the address is a transient problem. So the original
    error passes through untouched, and a caller that knows what an occupant means reads
    it for itself.
    """

    source = tmp_path / "staging"
    source.mkdir()
    destination = tmp_path / "record"
    destination.mkdir()
    pauses = _refuse_rename(monkeypatch, times=99)

    with pytest.raises(PermissionError):
        atomic.replace_retrying(source, destination)

    assert pauses == []
    assert source.is_dir()


def test_the_laboratory_wrapper_keeps_its_own_exception_type(tmp_path: Path) -> None:
    target = tmp_path / "measurement.json"
    assert shadow_report.write_document_once({"a": 1}, target) == "written"

    with pytest.raises(shadow_report.ShadowReportError, match="different measurement"):
        shadow_report.write_document_once({"a": 2}, target)
    target.write_bytes(b"not json")
    with pytest.raises(shadow_report.ShadowReportError, match="not readable JSON"):
        shadow_report.write_document_once({"a": 3}, target)
