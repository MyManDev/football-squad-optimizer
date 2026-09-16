"""Create a file exactly once, atomically, and say which of two things happened.

Several artifacts in this repository are records: a measurement, a manifest, a retained
handoff. A record is written once and never replaced in place, so the writer has to be
crash-safe and safe under concurrent writers. The bytes are completed and fsynced in a
sibling temporary file and published with a no-overwrite hard link; the temporary is
removed on every path. A losing writer compares its own bytes with the winner's and
reports a replay when they agree, and refuses when they do not.

"Create once" means exactly what ``projection_retention`` and the live ledger mean by it:
an occupant holding the same bytes is a success (``"replay"``), an occupant holding
different bytes is an error, and nothing on disk is ever overwritten.

The other half of publishing is here too, and for the same reason: :func:`replace_retrying`
is the one rename a record lands by. A writer that stages bytes in a sibling and moves them
into place with ``os.replace`` is publishing, and on Windows that last move is refused with
``PermissionError`` while anything still holds a handle on what was written a moment ago.
Every writer that owned its own rename owned its own answer to that, which is how a record
came to be deleted for a refusal the next attempt would have survived.
"""

import contextlib
import json
import os
import secrets
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Final

from squadopt.data._long_paths import addressable
from squadopt.data.errors import AtomicWriteError, ConflictingBytesError, RenameRefusedError

WRITTEN = "written"
REPLAY = "replay"

RENAME_RETRY_ATTEMPTS: Final = 5
"""How many times a rename refused with ``PermissionError`` is attempted in all."""
RENAME_RETRY_INITIAL_SECONDS: Final = 0.05
"""The first pause before a retry; it doubles, so five attempts span 0.75 s of waiting."""


def replace_retrying(source: Path, destination: Path) -> None:
    """``os.replace``, retried for a moment while the operating system refuses it.

    Windows refuses a rename with ``PermissionError`` (WinError 5) while any process still
    holds a handle on a path involved - a scanner or an indexer reading bytes that were
    written a moment ago, which is likelier when the suite runs many workers at once. The
    same rename then succeeds, so that error alone is retried, ``RENAME_RETRY_ATTEMPTS``
    times with a doubling pause, and the last refusal is reported rather than swallowed,
    as ``RenameRefusedError`` naming how long it waited.

    One case that is not transient arrives as the very same error: Windows refuses a
    rename onto a destination that already exists as a directory. Retrying that would turn
    a real refusal into a slow one, so the original ``PermissionError`` is re-raised at
    once, and a caller that can tell what an occupied destination means - a record already
    written by someone else - separates the two by catching it. This function never decides
    whether a record may be written; create-once is the caller's check under its own lock.

    Both paths go through ``addressable``, so a destination past Windows' MAX_PATH is still
    reachable: the staging sibling a record is built in is longer than the record's own
    name, and the rename is the call that writes the shorter one.
    """

    delay = RENAME_RETRY_INITIAL_SECONDS
    waited = 0.0
    for attempt in range(1, RENAME_RETRY_ATTEMPTS + 1):
        try:
            os.replace(addressable(source), addressable(destination))
            return
        except PermissionError as error:
            if Path(addressable(destination)).is_dir():
                raise
            if attempt == RENAME_RETRY_ATTEMPTS:
                raise RenameRefusedError(
                    f"Renaming {source} onto {destination} was refused on all "
                    f"{RENAME_RETRY_ATTEMPTS} attempts over {waited:.2f} s; something "
                    "still holds a handle on it."
                ) from error
        time.sleep(delay)
        waited += delay
        delay *= 2


def write_bytes_once(
    payload: bytes,
    destination: Path,
    *,
    parse: Callable[[bytes], object] | None = None,
) -> str:
    """Publish ``payload`` at ``destination`` exactly once.

    Returns ``"written"`` when this call created the file and ``"replay"`` when the file
    already held the same bytes. ``parse`` widens what counts as the same: when given, an
    occupant whose bytes differ is read through it and compared with the parsed payload,
    so a caller can declare that, say, only a wall-clock stamp may differ. Whatever
    ``parse`` raises propagates untouched; a caller that wants a friendlier error wraps it.

    Raises ``ConflictingBytesError`` when the occupant is a different document and
    ``AtomicWriteError`` when the occupant cannot be read or the link cannot be made.
    Every path-based call goes through ``addressable`` so a destination past Windows'
    MAX_PATH is still reachable (the temporary beside it is longer than the target).
    """

    Path(addressable(destination.parent)).mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(
        f".{destination.name}.tmp-{os.getpid()}-{secrets.token_hex(8)}"
    )
    try:
        with Path(addressable(temporary)).open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(addressable(temporary), addressable(destination))
            return WRITTEN
        except FileExistsError:
            try:
                existing_bytes = Path(addressable(destination)).read_bytes()
            except OSError as error:
                raise AtomicWriteError(
                    f"{destination} is occupied by something that cannot be read: {error}"
                ) from error
            if existing_bytes == payload:
                return REPLAY
            if parse is not None and parse(existing_bytes) == parse(payload):
                return REPLAY
            raise ConflictingBytesError(
                f"{destination} already exists with different content; a record is never "
                "overwritten in place. Choose another name or remove it deliberately."
            ) from None
        except OSError as error:
            raise AtomicWriteError(f"{destination} could not be published: {error}") from error
    finally:
        with contextlib.suppress(OSError):
            Path(addressable(temporary)).unlink()


def document_bytes(document: Mapping[str, object]) -> bytes:
    """The one serialization a record document is written in.

    Sorted keys, two-space indent, a trailing newline, and no NaN: the same bytes for the
    same mapping on every machine, so a digest or a byte comparison identifies the document
    and not the process that wrote it.
    """

    return (json.dumps(dict(document), indent=2, sort_keys=True, allow_nan=False) + "\n").encode(
        "utf-8"
    )


def write_document_once(
    document: Mapping[str, object],
    destination: Path,
    *,
    replay_identity: Callable[[Mapping[str, object]], object] | None = None,
) -> str:
    """Publish one JSON document under the create-once rule.

    ``replay_identity`` names the part of a document two writes of the same record must
    agree on; a caller whose document carries a wall-clock stamp passes a function that
    drops it, so a rerun replays instead of conflicting. Without it, only identical
    documents replay. An occupant that is not readable JSON is an ``AtomicWriteError``.
    """

    def parse(raw: bytes) -> object:
        try:
            loaded = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise AtomicWriteError(
                f"{destination} already exists but is not readable JSON."
            ) from error
        return loaded if replay_identity is None else replay_identity(loaded)

    return write_bytes_once(document_bytes(document), destination, parse=parse)


__all__: tuple[str, ...] = (
    "RENAME_RETRY_ATTEMPTS",
    "RENAME_RETRY_INITIAL_SECONDS",
    "REPLAY",
    "WRITTEN",
    "document_bytes",
    "replace_retrying",
    "write_bytes_once",
    "write_document_once",
)
