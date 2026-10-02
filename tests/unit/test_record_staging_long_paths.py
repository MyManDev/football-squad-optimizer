"""A record whose own files fit a path limit can still be written.

A record is assembled in a hidden staging sibling and each of its files lands through a
temporary of its own. Both names are longer than the ones they become, so the longest paths
a write touches are longer than any path the finished record has. On Windows a path-based
call fails at 260 characters, and a publish once ended there, on a 268 character manifest
temporary, after every plan had been solved.

These build a record whose finished paths sit just under that limit and whose staging paths
sit over it. On a system with no such limit they still write the same record the same way.
"""

import errno
import json
import os
from pathlib import Path
from typing import Any

import pytest
from tests.unit.test_advice_record import CAPTURE, _bare_record

from squadopt.application.advice_record import (
    RECORD_FILE,
    AdviceRecordConflictError,
    AdviceRecordNotLandedError,
    load_member_advice_record,
    record_directory,
    record_member_advice,
)
from squadopt.data import atomic
from squadopt.data._long_paths import addressable
from squadopt.live import ledger

WINDOWS_LIMIT = 260


def _finished_manifest(root: Path) -> Path:
    record = _bare_record()
    directory = record_directory(
        root, record["season"], record["gameweek"], record["entry_id"], CAPTURE
    )
    return directory / "manifest.json"


def _deep_root(tmp_path: Path, *, finished_length: int) -> Path:
    """A records root such that the finished manifest path is exactly ``finished_length``.

    One padded directory name under the temporary directory, well under a single name's
    limit, so the depth is the only thing that changes between cases.
    """

    padding = finished_length - len(str(_finished_manifest(tmp_path / "x")))
    assert 0 < padding <= 200, "the temporary directory is too deep or too shallow for this"
    root = tmp_path / ("x" + "d" * padding)
    assert len(str(_finished_manifest(root))) == finished_length
    return root


def _lengths(root: Path) -> tuple[int, int]:
    """The finished manifest path's length, and the longest staging path's."""

    record = _bare_record()
    directory = record_directory(
        root, record["season"], record["gameweek"], record["entry_id"], CAPTURE
    )
    staging = ledger.staging_directory(directory)
    temporary = staging / f".manifest.json.tmp-{os.getpid()}-00000000"
    return len(str(directory / "manifest.json")), len(str(temporary))


def test_a_record_lands_when_only_its_staging_paths_pass_the_limit(tmp_path: Path) -> None:
    root = _deep_root(tmp_path, finished_length=WINDOWS_LIMIT - 8)
    finished, staging = _lengths(root)
    # The case that failed: every finished path fits, and the manifest temporary does not.
    assert finished < WINDOWS_LIMIT <= staging

    record = _bare_record()
    directory = record_member_advice(root, record)

    names = sorted(path.name for path in Path(addressable(directory)).iterdir())
    assert names == [RECORD_FILE, "manifest.json"]
    stored = json.loads(Path(addressable(directory / RECORD_FILE)).read_bytes())
    assert stored["told"] == record["told"]
    ledger.verify_manifest(directory)
    # Nothing is left beside it: no staging sibling and no lock.
    siblings = sorted(path.name for path in Path(addressable(directory.parent)).iterdir())
    assert siblings == [directory.name]
    # Written again from the same capture, it is the same record and not a second one.
    assert record_member_advice(root, _bare_record()) == directory


def test_a_ledger_staging_directory_is_written_through_the_same_door(tmp_path: Path) -> None:
    """The shared primitives, used directly, on a staging path past the limit."""

    root = _deep_root(tmp_path, finished_length=WINDOWS_LIMIT - 8)
    directory = root / "season" / ("record-" + "r" * 40)
    assert len(str(directory / "manifest.json")) < WINDOWS_LIMIT
    staging = ledger.staging_directory(directory)
    Path(addressable(staging)).mkdir(parents=True)
    Path(addressable(staging / "payload.json")).write_bytes(b"{}")
    assert len(str(staging / ".manifest.json.tmp-0-00000000")) >= WINDOWS_LIMIT

    ledger.write_manifest(staging, contract_version="test_record_v1")
    ledger.verify_manifest(staging)
    ledger.write_atomic(staging / "payload.json", b"[]")

    with pytest.raises(ledger.LedgerError, match="does not match its recorded digest"):
        ledger.verify_manifest(staging)
    assert ledger.prune_stale_staging(root, "season", older_than_seconds=0) == 1
    assert not Path(addressable(staging)).exists()


@pytest.mark.parametrize("finished_length", [WINDOWS_LIMIT - 1, WINDOWS_LIMIT, WINDOWS_LIMIT + 12])
def test_a_record_past_the_limit_is_written_read_back_and_replayed(
    tmp_path: Path, finished_length: int
) -> None:
    """The finished record's own files at and past the limit: landed, read, replayed.

    Without the reads going through the same door a record this deep would land and
    every later read of it would fail, which is worse than refusing to write it.
    """

    root = _deep_root(tmp_path, finished_length=finished_length)
    record = _bare_record()

    directory = record_member_advice(root, record)

    loaded = load_member_advice_record(
        root, record["season"], record["gameweek"], record["entry_id"], CAPTURE
    )
    assert loaded["told"] == record["told"]
    assert record_member_advice(root, _bare_record()) == directory
    with pytest.raises(AdviceRecordConflictError):
        record_member_advice(root, _bare_record(advice="two"))


def test_a_stale_staging_directory_past_the_limit_is_still_swept(tmp_path: Path) -> None:
    root = _deep_root(tmp_path, finished_length=WINDOWS_LIMIT - 8)
    record = _bare_record()
    directory = record_directory(
        root, record["season"], record["gameweek"], record["entry_id"], CAPTURE
    )
    staging = ledger.staging_directory(directory)
    assert len(str(staging)) >= WINDOWS_LIMIT
    Path(addressable(staging)).mkdir(parents=True)

    swept = ledger.prune_stale_staging(
        directory.parent.parent, directory.parent.name, older_than_seconds=0
    )

    assert swept == 1
    assert not Path(addressable(staging)).exists()


def test_a_record_that_cannot_land_leaves_nothing_behind_and_lands_on_the_next_try(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The write failing costs this attempt only; the same record is written by the next.

    What the record is made from is in the caller's hands, so recording again needs no
    plan to be solved again: the publish is re-run for the capture and the record lands.
    """

    root = _deep_root(tmp_path, finished_length=WINDOWS_LIMIT - 8)
    record = _bare_record()
    directory = record_directory(
        root, record["season"], record["gameweek"], record["entry_id"], CAPTURE
    )
    real_replace = atomic.os.replace

    def refused(source: Any, destination: Any) -> None:
        if Path(source).is_dir():
            raise PermissionError(errno.EACCES, "Access is denied")
        real_replace(source, destination)

    monkeypatch.setattr(atomic.os, "replace", refused)
    monkeypatch.setattr(atomic.time, "sleep", lambda _seconds: None)
    with pytest.raises(AdviceRecordNotLandedError, match="re-run the publish of this capture"):
        record_member_advice(root, record)

    week = Path(addressable(directory.parent))
    assert not Path(addressable(directory)).exists()
    assert list(week.iterdir()) == []

    monkeypatch.setattr(atomic.os, "replace", real_replace)
    assert record_member_advice(root, record) == directory
    ledger.verify_manifest(directory)
